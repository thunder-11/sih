"""Phase 4 orchestration: fetch provider evidence, persist it, and expose coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.providers.contracts import ProviderError
from app.providers.registry import provider_for
from app.providers.prices import CoinGeckoHistoricalProvider
from app.repositories.phase4 import BlockchainObservationRepository
from app.repositories.phase2 import DurableJobRepository


@dataclass(frozen=True, slots=True)
class IngestionResult:
    chain: str
    provider: str
    coverage_state: str
    persisted_transfers: int
    next_cursor: str | None
    warnings: tuple[str, ...]


def ingest_wallet_page(session: Session, *, settings: Settings, chain: str, address: str,
                       cursor: str | None = None, page_size: int | None = None,
                       provider: Any | None = None) -> IngestionResult:
    adapter = provider or provider_for(chain, settings)
    try:
        page = adapter.fetch_address(address, cursor=cursor, page_size=page_size or settings.provider_page_size)
    except ProviderError:
        # Deliberately propagate typed errors: callers can persist retry state rather
        # than falsely presenting an empty transaction history as complete.
        raise
    quote_provider = CoinGeckoHistoricalProvider(api_key=settings.coingecko_api_key, base_url=settings.coingecko_base_url,
                                                  transport=adapter.transport)
    def quote(candidate):
        # Contract-specific tokens require a verified asset mapping.  Phase 4 never
        # derives a USD value merely from a symbol such as USDT or USDC.
        if candidate.asset_contract or candidate.event_time is None:
            return None
        try:
            from app.repositories.phase4 import exact_amount
            return quote_provider.quote_native(chain=candidate.chain, event_time=candidate.event_time,
                                               amount=exact_amount(candidate.raw_amount, candidate.asset_decimals))
        except ProviderError:
            return None
    observation, persisted = BlockchainObservationRepository(session).persist_page(page, price_quote=quote)
    return IngestionResult(chain=page.chain, provider=page.provider, coverage_state=page.coverage_state,
                           persisted_transfers=persisted, next_cursor=page.next_cursor, warnings=page.warnings)


def process_ingestion_job(session: Session, *, settings: Settings, job, provider: Any | None = None) -> IngestionResult:
    """Execute one leased durable job; caller commits the job state transaction."""
    if job.operation != "blockchain.ingest":
        raise ValueError("job is not a blockchain ingestion job")
    payload = job.payload
    try:
        result = ingest_wallet_page(session, settings=settings, chain=payload["chain"], address=payload["address"],
                                    cursor=payload.get("cursor"), page_size=payload.get("page_size"), provider=provider)
    except ProviderError as exc:
        DurableJobRepository(session).fail(job, error_code=exc.code, retryable=exc.retryable,
                                           retry_delay_seconds=exc.retry_after_seconds or 30)
        raise
    DurableJobRepository(session).complete(job)
    return result
