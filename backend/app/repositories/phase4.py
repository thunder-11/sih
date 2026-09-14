"""Durable persistence of provider observations and normalized transfers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.models import AddressRecord, Asset, NormalizedTransaction, ProviderObservation
from app.providers.contracts import ProviderPage, TransferCandidate
from app.providers.prices import PriceQuote


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class BlockchainObservationRepository:
    def __init__(self, session: Session):
        self.session = session

    def persist_page(self, page: ProviderPage, *, price_quote: Any | None = None) -> tuple[ProviderObservation, int]:
        fingerprint = digest({"address": page.address, "cursor": page.next_cursor, "source": page.source_uri})
        response_digest = digest(page.raw_payload)
        observation = self.session.execute(select(ProviderObservation).where(
            ProviderObservation.provider == page.provider, ProviderObservation.chain == page.chain,
            ProviderObservation.request_fingerprint == fingerprint, ProviderObservation.response_digest == response_digest,
        )).scalar_one_or_none()
        if observation is None:
            observation = ProviderObservation(
                provider=page.provider, chain=page.chain, request_fingerprint=fingerprint,
                available_time=page.fetched_at, fetched_at=page.fetched_at, ingested_at=datetime.now(timezone.utc),
                coverage_state=page.coverage_state, source_uri=page.source_uri, cursor=page.next_cursor,
                parser_version="phase4-adapters-v1", response_digest=response_digest,
                block_height=page.observed_height, finality_state="unknown",
                provenance={"address": page.address, "warnings": list(page.warnings), "raw_payload": page.raw_payload},
            )
            self.session.add(observation)
            try:
                with self.session.begin_nested():
                    self.session.flush()
            except IntegrityError:
                observation = self.session.execute(select(ProviderObservation).where(
                    ProviderObservation.provider == page.provider, ProviderObservation.chain == page.chain,
                    ProviderObservation.request_fingerprint == fingerprint, ProviderObservation.response_digest == response_digest,
                )).scalar_one()
        created = 0
        for candidate in page.transfers:
            if candidate.execution_status != "successful" or candidate.from_address is None or candidate.to_address is None:
                continue
            quote = price_quote(candidate) if price_quote else None
            transfer, was_created = self.persist_transfer(candidate, observation, available_at=page.fetched_at, price_quote=quote)
            created += int(was_created)
        self.session.flush()
        return observation, created

    def persist_transfer(self, candidate: TransferCandidate, observation: ProviderObservation, *, available_at: datetime,
                         price_quote: PriceQuote | None = None) -> tuple[NormalizedTransaction, bool]:
        existing = self.session.execute(select(NormalizedTransaction).where(
            NormalizedTransaction.chain == candidate.chain,
            NormalizedTransaction.tx_hash == candidate.tx_hash,
            NormalizedTransaction.transfer_index == candidate.transfer_index,
        )).scalar_one_or_none()
        if existing is not None:
            return existing, False
        if candidate.event_time is None:
            raise ValueError("confirmed transfer candidates require event_time")
        source = self._address(candidate.chain, candidate.from_address)
        destination = self._address(candidate.chain, candidate.to_address)
        asset = self._asset(candidate)
        amount = exact_amount(candidate.raw_amount, candidate.asset_decimals)
        transfer = NormalizedTransaction(
            chain=candidate.chain, tx_hash=candidate.tx_hash, transfer_index=candidate.transfer_index,
            from_address_id=source.id, to_address_id=destination.id, asset_id=asset.id, amount=amount,
            raw_amount=candidate.raw_amount, event_time=candidate.event_time, available_time=available_at,
            ingested_at=datetime.now(timezone.utc), provider_observation_id=observation.id,
            block_height=candidate.block_height, block_hash=candidate.block_hash, confirmations=candidate.confirmations,
            finality_state=candidate.finality_state, status="confirmed",
        )
        if price_quote is not None:
            transfer.fiat_value = price_quote.amount_usd
            transfer.fiat_currency = "USD"
            transfer.valuation_source = price_quote.source
            transfer.valuation_time = price_quote.quote_time
        try:
            with self.session.begin_nested():
                self.session.add(transfer)
                self.session.flush()
        except IntegrityError:
            transfer = self.session.execute(select(NormalizedTransaction).where(
                NormalizedTransaction.chain == candidate.chain, NormalizedTransaction.tx_hash == candidate.tx_hash,
                NormalizedTransaction.transfer_index == candidate.transfer_index,
            )).scalar_one()
            return transfer, False
        return transfer, True

    def _address(self, chain: str, address: str) -> AddressRecord:
        canonical = address.lower() if chain in {"ETH", "BSC", "POLYGON"} else address
        record = self.session.execute(select(AddressRecord).where(
            AddressRecord.chain == chain, AddressRecord.canonical_address == canonical
        )).scalar_one_or_none()
        if record is None:
            record = AddressRecord(chain=chain, canonical_address=canonical, display_address=address,
                                   first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc))
            self.session.add(record)
            self.session.flush()
        return record

    def _asset(self, candidate: TransferCandidate) -> Asset:
        contract = candidate.asset_contract.lower() if candidate.asset_contract else None
        record = self.session.execute(select(Asset).where(
            Asset.chain == candidate.chain, Asset.symbol == candidate.asset_symbol,
            Asset.contract_address == contract,
        )).scalar_one_or_none()
        if record is None:
            record = Asset(chain=candidate.chain, symbol=candidate.asset_symbol, contract_address=contract,
                           decimals=candidate.asset_decimals, asset_type="native" if contract is None else "token")
            self.session.add(record)
            self.session.flush()
        elif record.decimals != candidate.asset_decimals:
            raise ValueError("provider asset decimals conflict with the established network-qualified asset")
        return record


def exact_amount(raw_amount: str, decimals: int) -> Decimal:
    if not isinstance(raw_amount, str) or not raw_amount.isdigit() or not 0 <= decimals <= 36:
        raise ValueError("raw amount must be a non-negative integer with valid asset decimals")
    try:
        return Decimal(raw_amount).scaleb(-decimals)
    except InvalidOperation as exc:
        raise ValueError("invalid exact amount") from exc
