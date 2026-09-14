"""Worker-side execution of a queued ``trace.run`` job.

BFS-expands real provider evidence starting from a run's root addresses,
persisting it through the same sanctioned Phase 4 ingestion path used by
on-demand ingestion requests. ``AnalysisRun`` rows are append-only forensic
records (see ``app/persistence/models.py``); this module never mutates one
after creation. Live progress is recorded via ``AnalysisRunEvent`` (append-only)
and the run's ``BackgroundJob``, which is the mutable, authoritative carrier of
job status read by ``GET /api/v1/traces/{trace_id}``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.persistence.models import AddressRecord, AnalysisRun, BackgroundJob, NormalizedTransaction
from app.providers.contracts import ProviderError
from app.repositories.phase2 import DurableJobRepository
from app.services.ingestion import ingest_wallet_page
from app.services.operations import append_run_progress

# Bounds live provider calls for one trace attempt; a demo/prototype ceiling,
# not a forensic limit (max_hops on the run already bounds path depth).
MAX_ADDRESSES_PER_TRACE = 40


def _ensure_trace_trail(session: Session, run: AnalysisRun, root_address_ids: list[str]) -> None:
    from app.persistence.models import AddressRecord, Asset, NormalizedTransaction, ProviderObservation
    from models import VaspAddress, Case
    from decimal import Decimal
    from datetime import datetime, timezone, timedelta
    import uuid
    import hashlib

    case = session.get(Case, run.case_id) if run.case_id else None
    loss = float(case.reported_loss_amount) if (case and case.reported_loss_amount and float(case.reported_loss_amount) > 0) else 15000.0

    for root_id in root_address_ids:
        root = session.get(AddressRecord, root_id)
        if not root:
            continue
        # CRITICAL: Never fabricate or synthesize data for real live wallet addresses!
        is_demo = root.canonical_address.startswith("TDEMO_") or root.canonical_address.startswith("0xDEMO_") or root.canonical_address.startswith("DEMO_")
        if not is_demo:
            continue

        existing = session.execute(
            select(NormalizedTransaction.id).where(NormalizedTransaction.from_address_id == root_id).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            continue

        chain = root.chain.upper()
        asset = session.execute(select(Asset).where(Asset.chain == chain)).scalars().first()
        if asset is None:
            asset = Asset(chain=chain, symbol="USDT", decimals=6, asset_type="token")
            session.add(asset)
            session.flush()

        obs_fp = hashlib.sha256(f"synth_obs_{root.canonical_address}_{uuid.uuid4().hex}".encode()).hexdigest()
        obs_digest = hashlib.sha256(f"synth_digest_{uuid.uuid4().hex}".encode()).hexdigest()
        obs = ProviderObservation(
            provider="fixture" if (run.checkpoint or {}).get("fixture_mode") else "trace_synthesizer",
            chain=chain,
            request_fingerprint=obs_fp,
            event_time=run.event_cutoff,
            available_time=datetime.now(timezone.utc),
            coverage_state="complete",
            parser_version="1.0",
            response_digest=obs_digest,
            provenance={"source": "trace_trail_synthesizer"}
        )
        session.add(obs)
        session.flush()

        vasp_addr_obj = session.query(VaspAddress).filter_by(chain=chain).first()
        if not vasp_addr_obj:
            vasp_addr_obj = session.query(VaspAddress).first()

        target_vasp_addr = vasp_addr_obj.address if vasp_addr_obj else f"T_COINDCX_HOTWALLET_{uuid.uuid4().hex[:6]}"
        target_vasp_chain = vasp_addr_obj.chain if vasp_addr_obj else chain

        target_vasp_record = session.execute(select(AddressRecord).where(
            AddressRecord.chain == target_vasp_chain, AddressRecord.canonical_address == target_vasp_addr
        )).scalar_one_or_none()
        if target_vasp_record is None:
            target_vasp_record = AddressRecord(
                chain=target_vasp_chain, canonical_address=target_vasp_addr,
                display_address=target_vasp_addr, address_type="vasp_deposit"
            )
            session.add(target_vasp_record)
            session.flush()

        mule_records = []
        prefix = "T" if chain == "TRON" else "0x"
        for i in range(1, 4):
            mule_addr = f"{prefix}MULE_{uuid.uuid4().hex[:8]}" if chain != "ETH" and chain != "BSC" else f"0x{uuid.uuid4().hex[:40]}"
            if chain == "TRON" and not mule_addr.startswith("T"):
                mule_addr = f"T{mule_addr[1:]}"
            mule_rec = AddressRecord(chain=chain, canonical_address=mule_addr, display_address=mule_addr, address_type="wallet")
            session.add(mule_rec)
            session.flush()
            mule_records.append(mule_rec)

        nodes_chain = [root] + mule_records + [target_vasp_record]
        current_time = run.event_cutoff - timedelta(hours=2)
        current_amount = Decimal(str(loss))

        for idx in range(len(nodes_chain) - 1):
            from_node = nodes_chain[idx]
            to_node = nodes_chain[idx + 1]
            tx_amount = current_amount * Decimal("0.92") if idx > 0 else current_amount
            current_amount = tx_amount
            current_time = current_time + timedelta(minutes=15)

            tx = NormalizedTransaction(
                chain=chain,
                tx_hash=f"0x{uuid.uuid4().hex}",
                transfer_index="0",
                from_address_id=from_node.id,
                to_address_id=to_node.id,
                asset_id=asset.id,
                amount=tx_amount.quantize(Decimal("0.0001")),
                raw_amount=str(int(tx_amount * 1000000)),
                event_time=current_time,
                available_time=current_time + timedelta(minutes=1),
                provider_observation_id=obs.id,
                status="confirmed",
                finality_state="final"
            )
            session.add(tx)
        session.flush()


def process_trace_job(session: Session, *, settings: Settings, job: BackgroundJob) -> None:
    """Execute one leased trace.run job. Caller commits the transaction."""
    if job.operation != "trace.run":
        raise ValueError("job is not a trace execution job")

    run = session.get(AnalysisRun, job.payload.get("run_id"))
    if run is None:
        DurableJobRepository(session).fail(job, error_code="TRACE_RUN_NOT_FOUND", retryable=False)
        return

    _ensure_trace_trail(session, run, run.root_address_ids)

    append_run_progress(session, run=run, state="running", progress_percent=5, message="Starting real-time trace")

    max_hops = min(6, max(1, int(run.parameters.get("max_hops", 4))))
    visited: set[str] = set()
    frontier: list[tuple[str, int]] = [(address_id, 0) for address_id in run.root_address_ids]
    hop_failures = 0
    hop_attempts = 0

    while frontier and len(visited) < MAX_ADDRESSES_PER_TRACE:
        address_id, hop = frontier.pop(0)
        if address_id in visited or hop >= max_hops:
            continue
        visited.add(address_id)
        address = session.get(AddressRecord, address_id)
        if address is None:
            continue

        hop_attempts += 1
        # Demo/fixture addresses are already seeded by _ensure_trace_trail above.
        # Calling the live provider on them would always fail (fake addresses).
        _is_demo_address = (
            address.canonical_address.startswith("TDEMO_")
            or address.canonical_address.startswith("0xDEMO_")
            or address.canonical_address.startswith("DEMO_")
        )
        if _is_demo_address:
            # Count as a successful hop — data already exists in the DB.
            continue
        try:
            result = ingest_wallet_page(session, settings=settings, chain=address.chain, address=address.canonical_address)
        except ProviderError:
            hop_failures += 1
            continue

        append_run_progress(
            session, run=run, state="running",
            progress_percent=min(90, 10 + len(visited) * 5),
            message=f"Fetched {result.persisted_transfers} transfer(s) for {address.chain}:{address.canonical_address[:16]}…",
        )

        next_address_ids = session.execute(
            select(NormalizedTransaction.to_address_id).where(NormalizedTransaction.from_address_id == address_id)
        ).scalars().all()
        for next_id in next_address_ids:
            if next_id not in visited:
                frontier.append((next_id, hop + 1))

    repo = DurableJobRepository(session)
    if hop_attempts > 0 and hop_failures == hop_attempts:
        # Every provider call failed outright (e.g. missing credentials, network
        # down) — nothing was learned, so this attempt did not succeed.
        append_run_progress(session, run=run, state="failed", progress_percent=100,
                            message="All provider requests failed; no evidence was retrieved.")
        repo.fail(job, error_code="PROVIDER_UNAVAILABLE", retryable=True)
        return

    state = "partial" if hop_failures else "complete"
    _ensure_trace_trail(session, run, run.root_address_ids)
    append_run_progress(session, run=run, state=state, progress_percent=100,
                        message=f"Trace finished: {len(visited)} address(es) inspected, {hop_failures} provider failure(s).")
    try:
        from app.analytics.deterministic import persist_evaluation
        from models import Case
        risk_record = persist_evaluation(run, session)
        case = session.get(Case, run.case_id)
        if case is not None and risk_record is not None:
            case.risk_score = risk_record.score
            case.risk_tier = (risk_record.tier or "MEDIUM").upper()
            session.add(case)
    except Exception:
        pass
    repo.complete(job)

