"""Trace execution & graph data routers."""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models import CaseWallet, Alert, User
from auth.utils import get_current_user
from services.risk_scoring import compute_risk_score
from services.correlation import find_linked_cases
from config import DEFAULT_MAX_HOPS
from app.core.errors import ApplicationError
from app.jobs.contracts import JobState
from app.persistence.models import AddressRecord, AnalysisRun, BackgroundJob, ReportEvent, TracePath
from app.repositories.phase2 import DurableJobRepository
from app.repositories.phase3 import WorkflowRepository
from app.security.authorization import get_accessible_case
from app.services.temporal_graph import GraphRequest, graph_payload

router = APIRouter(prefix="/api/v1/cases", tags=["Traces"])

# Generous window for the worker's async BFS ingestion to complete after a run
# is created; see the ASYNC_INGESTION_WINDOW comment at each AnalysisRun(...) call.
ASYNC_INGESTION_WINDOW = timedelta(hours=1)


class TraceRequest(BaseModel):
    start_wallet: str | None = None
    chain: str | None = None
    token_symbol: str = "USDT"
    max_hops: int = Field(default=DEFAULT_MAX_HOPS, ge=1, le=6)
    min_amount_filter_usd: float = 50.0


@router.post("/{case_id}/trace", status_code=202)
def execute_case_trace(case_id: str, req: TraceRequest, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user),
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """Compatibility start route over the durable Phase 3 run created at intake."""
    case = get_accessible_case(db, user, case_id, write=True)
    # AnalysisRun.state is immutable and frozen at creation (append-only forensic
    # record), so liveness is read from the mutable BackgroundJob it enqueued —
    # not from the run row itself, which would otherwise look "active" forever.
    active_job = db.query(BackgroundJob).filter(
        BackgroundJob.case_id == case.id,
        BackgroundJob.operation == "trace.run",
        BackgroundJob.state.in_([JobState.QUEUED.value, JobState.RUNNING.value, JobState.RETRYING.value]),
    ).order_by(BackgroundJob.created_at.desc()).first()
    if active_job is not None:
        active_run = db.query(AnalysisRun).filter(
            AnalysisRun.case_id == case.id, AnalysisRun.run_type == "trace",
        ).order_by(AnalysisRun.revision.desc()).first()
        return {"trace_id": active_run.id if active_run else active_job.payload.get("run_id"), "case_id": case.id,
                "job_id": active_job.id, "status": active_job.state,
                "status_url": f"/api/v1/traces/{active_run.id if active_run else active_job.payload.get('run_id')}",
                "idempotent_replay": True}

    origin = db.query(CaseWallet).filter_by(case_id=case.id, is_origin_reported=True).first()
    if origin is None:
        raise ApplicationError(code="ORIGIN_WALLET_REQUIRED", message="The case has no validated origin wallet",
                               status_code=422, details={"case_id": case.id})
    if req.start_wallet and not req.chain:
        raise ApplicationError(code="NETWORK_REQUIRED", message="The wallet network is ambiguous or unsupported",
                               status_code=422, details={"case_id": case.id})
    start_wallet = req.start_wallet or origin.wallet_address
    chain = (req.chain or origin.wallet_chain or "").upper()
    if start_wallet != origin.wallet_address or chain != origin.wallet_chain:
        raise ApplicationError(code="ROOT_NOT_IN_CASE", message="Trace root must be a validated case wallet", status_code=422)
    report = db.query(ReportEvent).filter(ReportEvent.id == case.primary_report_event_id).first()
    if report is None:
        raise ApplicationError(code="REPORT_TIMESTAMP_REQUIRED", message="A report event is required before tracing", status_code=422)
    address = db.query(AddressRecord).filter(AddressRecord.chain == chain,
                                             AddressRecord.canonical_address == start_wallet).first()
    if address is None:
        raise ApplicationError(code="ORIGIN_WALLET_REQUIRED", message="Validated address record is missing", status_code=422)
    revision = db.query(func.coalesce(func.max(AnalysisRun.revision), 0)).filter(
        AnalysisRun.case_id == case.id, AnalysisRun.run_type == "trace").scalar() + 1
    now = datetime.now(timezone.utc)
    run = AnalysisRun(case_id=case.id, run_type="trace", revision=revision, state="queued", requested_by=user.id,
                      report_event_id=report.id, root_address_ids=[address.id], event_cutoff=now,
                      # The worker ingests evidence asynchronously after this row is created, and
                      # each persisted transfer's available_time is stamped at fetch time — always
                      # later than "now". cutoff_available_time is immutable once set (AnalysisRun
                      # is append-only), so it must already cover that ingestion window, or every
                      # transfer the trace itself fetches would be excluded by its own cutoff.
                      cutoff_available_time=now + ASYNC_INGESTION_WINDOW,
                      parameters=req.model_dump(), stage="queued", checkpoint={},
                      coverage={"state": "not_requested"})
    db.add(run)
    db.flush()
    job, created = DurableJobRepository(db).enqueue_once(operation="trace.run",
        idempotency_key=idempotency_key or f"trace:{case.id}:{revision}", case_id=case.id,
        payload={"run_id": run.id, "case_id": case.id, "root_address_ids": [address.id]})
    job.actor_id = user.id
    case.status = "investigating"
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="trace_queued", actor_id=user.id,
                               payload={"run_id": run.id, "job_id": job.id})
    workflow.audit(actor_id=user.id, case_id=case.id, action="trace.queue", resource_type="analysis_run",
                   resource_id=run.id, details={"job_id": job.id})
    db.commit()
    return {"trace_id": run.id, "case_id": case.id, "job_id": job.id, "status": JobState.QUEUED.value,
            "status_url": f"/api/v1/traces/{run.id}", "idempotent_replay": not created}


def _graph_request(*, temporal_view: str, boundary: str, include_context: bool, chain: str | None, asset: str | None,
                   min_amount: str | None, max_amount: str | None, to_time: datetime | None, trace_id: str | None,
                   report_event_id: str | None, report_revision: int | None) -> GraphRequest:
    if to_time and to_time.tzinfo is None:
        raise ApplicationError(code="INVALID_TIMESTAMP", message="The end time must include a timezone offset", status_code=422)
    return GraphRequest(temporal_view=temporal_view, boundary=boundary, include_context=include_context, chain=chain,
                        asset=asset, min_amount=min_amount, max_amount=max_amount, to_time=to_time, trace_id=trace_id,
                        report_event_id=report_event_id, report_revision=report_revision)


@router.get("/{case_id}/graph")
def get_case_graph(case_id: str, temporal_view: str = Query("all", alias="temporal_view"), boundary: str = "exclusive",
                   include_context: bool = False, chain: str | None = None, asset: str | None = None,
                   min_amount: str | None = None, max_amount: str | None = None, to_time: datetime | None = Query(None, alias="to"),
                   trace_id: str | None = None, report_event_id: str | None = None, report_revision: int | None = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Read a bounded temporal graph.  GET requests never start or recompute a trace."""
    case = get_accessible_case(db, user, case_id)
    return graph_payload(case, _graph_request(temporal_view=temporal_view, boundary=boundary, include_context=include_context,
                                               chain=chain, asset=asset, min_amount=min_amount, max_amount=max_amount,
                                               to_time=to_time, trace_id=trace_id, report_event_id=report_event_id,
                                               report_revision=report_revision), db)


@router.get("/{case_id}/transactions")
def get_case_transactions(case_id: str, temporal_view: str = "all", boundary: str = "exclusive", include_context: bool = False,
                          chain: str | None = None, asset: str | None = None, min_amount: str | None = None, max_amount: str | None = None,
                          to_time: datetime | None = Query(None, alias="to"), trace_id: str | None = None,
                          report_event_id: str | None = None, report_revision: int | None = None, limit: int = Query(50, ge=1, le=100),
                          cursor: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    request = _graph_request(temporal_view=temporal_view, boundary=boundary, include_context=include_context, chain=chain, asset=asset,
                             min_amount=min_amount, max_amount=max_amount, to_time=to_time, trace_id=trace_id,
                             report_event_id=report_event_id, report_revision=report_revision)
    graph = graph_payload(case, request, db)
    fingerprint = hashlib.sha256(json.dumps({"case": case.id, "request": asdict(request)}, default=str, sort_keys=True).encode()).hexdigest()
    offset = 0
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if decoded["fingerprint"] != fingerprint or not isinstance(decoded["offset"], int):
                raise ValueError
            offset = decoded["offset"]
        except Exception as exc:
            raise ApplicationError(code="INVALID_CURSOR", message="Cursor does not match this graph query", status_code=400) from exc
    values = graph["edges"]
    items = values[offset:offset + limit]
    next_cursor = None
    if offset + limit < len(values):
        next_cursor = base64.urlsafe_b64encode(json.dumps({"fingerprint": fingerprint, "offset": offset + limit}).encode()).decode()
    return {"case_id": case.id, "trace_id": graph["trace_id"], "items": items, "transactions": items, "total": len(values),
            "next_cursor": next_cursor, "summary": graph["summary"], "context_transfer_count": len(graph["context_edges"])}


@router.get("/{case_id}/graph/live-trail")
def live_transaction_trail(case_id: str, trace_id: str | None = None, report_event_id: str | None = None,
                           report_revision: int | None = None, boundary: str = "exclusive", db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Visualization-only ordered transfer trail; it has no persisted playback state."""
    case = get_accessible_case(db, user, case_id)
    graph = graph_payload(case, GraphRequest(temporal_view="post_report", boundary=boundary, trace_id=trace_id,
                                               report_event_id=report_event_id, report_revision=report_revision), db)
    steps = sorted(graph["edges"], key=lambda edge: (edge["event_time"], edge["hop"], edge["id"]))
    return {"case_id": case.id, "trace_id": graph["trace_id"], "visualization_only": True,
            "controls": ["play", "pause", "step_forward", "step_back", "restart", "speed"], "steps": steps,
            "stats": graph["summary"], "context_excluded": True}


trace_read_router = APIRouter(prefix="/api/v1/traces", tags=["Traces"])


@trace_read_router.get("/{trace_id}/paths")
def get_trace_paths(trace_id: str, case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return immutable, ordered trace paths without rebuilding a graph."""
    case = get_accessible_case(db, user, case_id)
    run = db.get(AnalysisRun, trace_id)
    if run is None or run.case_id != case.id:
        raise ApplicationError(code="TRACE_NOT_FOUND", message="Trace run not found for case", status_code=404)
    paths = db.query(TracePath).filter(TracePath.run_id == run.id).order_by(TracePath.path_index).all()
    return {"case_id": case.id, "trace_id": run.id, "items": [{"path_index": path.path_index, "hop_count": path.hop_count,
             "path": path.path_payload, "evidence_digest": path.evidence_digest} for path in paths], "total": len(paths), "read_only": True}


@router.get("/{case_id}/related")
def get_related_cases(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    return find_linked_cases(case_id, db)


def _get_label(wallet, db=None):
    if not wallet:
        return "Unknown"
    if wallet.vasp_id and db:
        from models import VaspDirectory
        vasp = db.query(VaspDirectory).filter_by(id=wallet.vasp_id).first()
        if vasp:
            return f"{vasp.vasp_name} ({wallet.node_type.replace('_', ' ').title()})"
    label_map = {
        "ORIGIN_VICTIM": "Victim Reported",
        "MULE_LAYER": "Intermediary / Mule",
        "MIXER": "Privacy Protocol",
        "BRIDGE": "Cross-Chain Bridge",
        "VASP_DEPOSIT": "Exchange Deposit",
        "VASP_HOT_WALLET": "Exchange Hot Wallet",
    }
    return label_map.get(wallet.node_type, "Wallet")


def _create_trace_alerts(case, trace_result, risk_data, correlation, user, db):
    """Create alerts based on trace findings."""
    attribution = trace_result.get("vasp_attribution")

    if attribution and attribution.get("confidence_score", 0) >= 85:
        fiu_tag = " (FIU-IND Registered)" if attribution.get("is_fiu_ind_registered") else ""
        alert = Alert(
            case_id=case.id, user_id=user.id,
            alert_type="VASP_HIGH_CONFIDENCE_HIT",
            severity="CRITICAL",
            title=f"🎯 VASP Identified: {attribution['vasp_name']}{fiu_tag}",
            message=f"Wallet {attribution['destination_address'][:20]}... matched {attribution['vasp_name']} "
                    f"with {attribution['confidence_score']:.0f}% confidence. "
                    f"Immediate Sec 94 BNSS freeze recommended.",
        )
        db.add(alert)

    if correlation.get("possible_syndicate"):
        alert = Alert(
            case_id=case.id, user_id=user.id,
            alert_type="SYNDICATE_OVERLAP",
            severity="CRITICAL",
            title=f"🚨 SYNDICATE DETECTED: {correlation['linked_count'] + 1} Linked FIRs",
            message=f"Case {case.external_complaint_id} shares mule wallets with "
                    f"{correlation['linked_count']} other complaints. Possible organized cyber fraud ring.",
        )
        db.add(alert)

    if "MIXER_HOP" in trace_result.get("risk_flags", []):
        alert = Alert(
            case_id=case.id, user_id=user.id,
            alert_type="MIXER_DETECTED",
            severity="HIGH",
            title="⚠️ Privacy Protocol Detected",
            message="Funds routed through mixer/privacy protocol. Trace confidence reduced downstream.",
        )
        db.add(alert)

    db.flush()
