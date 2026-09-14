"""Append-only human label revisions and dual-review eligibility."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.contracts import LABEL_STATES, TASKS
from app.persistence.models import AddressRecord, EvidenceSnapshot, LabelAdjudication, LabelRevision


PROHIBITED_LABEL_SOURCES = {"model", "prediction", "analyst_override", "alert", "legacy_ml"}


def append_label(session: Session, *, subject_type: str, subject_id: str, task: str, target_class: str,
                 group_key: str, window_start, window_end, label: str, maturity: str, known_at,
                 evidence_snapshot_ids: list[str], source_name: str, license_name: str,
                 source_confidence, rationale: str, created_by: str | None, maturation_days: int = 90) -> LabelRevision:
    if task not in TASKS:
        raise ApplicationError(code="INVALID_ML_TASK", message="Unsupported ML label task", status_code=422)
    if label not in LABEL_STATES:
        raise ApplicationError(code="INVALID_LABEL_STATE", message="Unsupported label state", status_code=422)
    if window_end <= window_start:
        raise ApplicationError(code="INVALID_LABEL_WINDOW", message="Observation window must be positive", status_code=422)
    if source_name.strip().lower() in PROHIBITED_LABEL_SOURCES:
        raise ApplicationError(code="PROHIBITED_LABEL_SOURCE", message="Operational/model output cannot become a training label", status_code=422)
    if label in {"positive", "negative", "disputed"} and not evidence_snapshot_ids:
        raise ApplicationError(code="LABEL_EVIDENCE_REQUIRED", message="Reviewed labels require evidence references", status_code=422)
    if task == "wallet_risk" and session.get(AddressRecord, subject_id) is None:
        raise ApplicationError(code="LABEL_SUBJECT_NOT_FOUND", message="Wallet label subject is not a registered address", status_code=404)
    if evidence_snapshot_ids:
        found = set(session.execute(select(EvidenceSnapshot.id).where(
            EvidenceSnapshot.id.in_(evidence_snapshot_ids)
        )).scalars())
        missing = sorted(set(evidence_snapshot_ids) - found)
        if missing:
            raise ApplicationError(code="LABEL_EVIDENCE_NOT_FOUND", message="Label evidence references are unavailable",
                                   status_code=422, details={"missing_ids": missing})
    latest = session.execute(select(LabelRevision).where(
        LabelRevision.subject_type == subject_type, LabelRevision.subject_id == subject_id,
        LabelRevision.task == task, LabelRevision.target_class == target_class,
    ).order_by(LabelRevision.revision.desc()).limit(1).with_for_update()).scalar_one_or_none()
    revision = 1 if latest is None else latest.revision + 1
    record = LabelRevision(subject_type=subject_type, subject_id=subject_id, task=task, target_class=target_class,
                           group_key=group_key, observation_window_start=window_start, observation_window_end=window_end,
                           label=label, maturity=maturity, matures_at=window_end + timedelta(days=maturation_days),
                           known_at=known_at, source_name=source_name, license_name=license_name,
                           source_confidence=source_confidence, rationale=rationale, created_by=created_by,
                           evidence_snapshot_ids=sorted(set(evidence_snapshot_ids)), revision=revision)
    session.add(record); session.flush()
    return record


def add_review(session: Session, *, label_revision: LabelRevision, reviewer_id: str, decision: str, reason: str) -> LabelAdjudication:
    if decision not in {"confirm", "reject", "uncertain"}:
        raise ApplicationError(code="INVALID_REVIEW_DECISION", message="Unsupported label review decision", status_code=422)
    if label_revision.created_by and label_revision.created_by == reviewer_id:
        raise ApplicationError(code="INDEPENDENT_REVIEW_REQUIRED", message="Label author cannot review their own label", status_code=409)
    existing = session.execute(select(LabelAdjudication).where(
        LabelAdjudication.label_revision_id == label_revision.id, LabelAdjudication.reviewer_id == reviewer_id
    )).scalar_one_or_none()
    if existing:
        raise ApplicationError(code="DUPLICATE_LABEL_REVIEW", message="Reviewer already reviewed this label revision", status_code=409)
    review = LabelAdjudication(label_revision_id=label_revision.id, reviewer_id=reviewer_id,
                               decision=decision, reason=reason)
    session.add(review); session.flush()
    return review


def eligibility(session: Session, label: LabelRevision, *, label_cutoff) -> dict:
    reviews = list(session.execute(select(LabelAdjudication).where(
        LabelAdjudication.label_revision_id == label.id,
        LabelAdjudication.adjudicated_at <= label_cutoff,
    )).scalars())
    confirmations = {item.reviewer_id for item in reviews if item.decision == "confirm"}
    rejects = {item.reviewer_id for item in reviews if item.decision == "reject"}
    mature = label.matures_at is not None and label.matures_at <= label_cutoff and label.maturity == "mature"
    eligible = (label.label in {"positive", "negative"} and label.known_at <= label_cutoff and mature
                and len(confirmations) >= 2 and not rejects)
    reasons = []
    if label.label not in {"positive", "negative"}: reasons.append(f"label_state_{label.label}")
    if label.known_at > label_cutoff: reasons.append("label_not_yet_known")
    if not mature: reasons.append("label_not_mature")
    if len(confirmations) < 2: reasons.append("dual_review_incomplete")
    if rejects: reasons.append("review_disagreement")
    return {"eligible": eligible, "reasons": reasons, "confirming_reviewers": sorted(confirmations),
            "rejecting_reviewers": sorted(rejects)}
