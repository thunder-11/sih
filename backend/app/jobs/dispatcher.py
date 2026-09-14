"""Transport-neutral dispatcher for the transactional outbox."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.repositories.phase2 import OutboxRepository


Publisher = Callable[[str, dict], None]


def dispatch_outbox_batch(session: Session, publisher: Publisher, *, limit: int = 100) -> tuple[int, int]:
    """Publish one batch using at-least-once semantics.

    A publisher must consume ``deduplication_key`` from the payload envelope or
    otherwise deduplicate deliveries. Database state is committed by the caller.
    """

    repository = OutboxRepository(session)
    published = failed = 0
    for event in repository.pending(limit=limit):
        envelope = {
            "event_id": event.id,
            "deduplication_key": event.deduplication_key,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "payload": event.payload,
        }
        try:
            publisher(event.topic, envelope)
        except Exception as exc:  # transport failures are persisted for retry
            repository.mark_failed(event, type(exc).__name__)
            failed += 1
        else:
            repository.mark_published(event)
            published += 1
    session.flush()
    return published, failed
