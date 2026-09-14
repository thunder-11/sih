from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.persistence.models import NormalizedTransaction, ProviderObservation
from app.providers.bitcoin import EsploraBitcoinProvider
from app.providers.contracts import ProviderError
from app.providers.evm import EvmScanProvider
from app.providers.http import JsonHttpTransport
from app.providers.tron import TronGridProvider
from app.repositories.phase4 import BlockchainObservationRepository, exact_amount
from app.services.ingestion import ingest_wallet_page
from database import Base


class Response:
    def __init__(self, status_code, payload, headers=None):
        self.status_code, self.payload, self.headers = status_code, payload, headers or {}

    def json(self):
        return self.payload


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def transport(responses, sleeps=None):
    return JsonHttpTransport(connect_timeout_seconds=3, request_timeout_seconds=10, max_attempts=3,
                             client=Client(responses), sleep=(sleeps.append if sleeps is not None else lambda _: None),
                             random_source=lambda: 0)


def evm_record(**extra):
    result = {
        "hash": "0xabc", "from": "0x" + "1" * 40, "to": "0x" + "2" * 40,
        "value": "1234567890123456789", "timeStamp": "1725100000", "blockNumber": "123",
        "blockHash": "0xblock", "transactionIndex": "7", "confirmations": "12", "isError": "0",
    }
    result.update(extra)
    return result


def test_evm_adapter_uses_v2_chain_id_and_keeps_exact_raw_units():
    responses = [
        Response(200, {"status": "1", "result": [evm_record()]}),
        Response(200, {"status": "1", "result": [evm_record(tokenSymbol="USDT", tokenDecimal="6", value="1000001", contractAddress="0x" + "a" * 40, logIndex="3")]}),
        Response(200, {"status": "1", "result": []}),
    ]
    http = transport(responses)
    provider = EvmScanProvider(chain="POLYGON", api_key="test-key", base_url="https://example.test/v2/api", transport=http)
    page = provider.fetch_address("0x" + "1" * 40, page_size=1)

    assert page.next_cursor == "2"
    assert len(page.transfers) == 2
    assert page.transfers[1].raw_amount == "1000001"
    assert page.transfers[1].asset_decimals == 6
    assert all(call[1]["chainid"] == "137" for call in http.client.calls)
    assert {call[1]["action"] for call in http.client.calls} == {"txlist", "tokentx", "txlistinternal"}


def test_trongrid_adapter_uses_fingerprint_and_millisecond_precision():
    native = {"data": [{"txID": "native-1", "block_timestamp": 1725100000123, "block_number": 1,
                          "raw_data": {"contract": [{"parameter": {"value": {"amount": 1_000_000, "owner_address": "TA", "to_address": "TB"}}}]}}],
              "meta": {"fingerprint": "next-native"}}
    token = {"data": [{"transaction_id": "token-1", "from": "TA", "to": "TB", "value": "1000001", "block_timestamp": 1725100000123,
                         "token_info": {"symbol": "USDT", "address": "TContract", "decimals": 6}}], "meta": {"fingerprint": "next-token"}}
    http = transport([Response(200, native), Response(200, token)])
    page = TronGridProvider(api_key="key", base_url="https://tron.example", transport=http).fetch_address("TA", cursor="old", page_size=100)

    assert page.next_cursor == "next-token"
    assert page.transfers[0].timestamp_precision == "millisecond"
    assert http.client.calls[0][1]["fingerprint"] == "old"
    assert http.client.calls[0][2]["TRON-PRO-API-KEY"] == "key"


def test_bitcoin_multi_input_is_not_allocated_to_first_sender():
    payload = [{"txid": "btc-1", "vin": [{"prevout": {"scriptpubkey_address": "sender-a"}}, {"prevout": {"scriptpubkey_address": "sender-b"}}],
                "vout": [{"scriptpubkey_address": "recipient", "value": 100}],
                "status": {"confirmed": True, "block_time": 1725100000, "block_height": 1, "block_hash": "block"}}]
    page = EsploraBitcoinProvider(base_url="https://btc.example", transport=transport([Response(200, payload)])).fetch_address("recipient")

    assert page.transfers == ()
    assert "bitcoin_multi_input_unallocated" in page.warnings


def test_rate_limit_honours_retry_after_and_error_is_typed():
    sleeps = []
    http = transport([Response(429, {}, {"Retry-After": "7"}), Response(429, {}), Response(429, {})], sleeps)
    with pytest.raises(ProviderError) as raised:
        http.get("https://example.test")
    assert raised.value.code == "PROVIDER_RATE_LIMITED"
    assert sleeps[0] == 7


def test_malformed_provider_response_is_not_empty_success():
    provider = EvmScanProvider(chain="ETH", api_key="key", base_url="https://example.test/v2/api",
                                transport=transport([Response(200, {"status": "1", "result": "not-a-list"})]))
    with pytest.raises(ProviderError, match="not a list"):
        provider.fetch_address("0x" + "1" * 40)


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_persistence_is_idempotent_and_exact(database):
    candidate = EvmScanProvider(chain="ETH", api_key="key", base_url="https://example.test/v2/api", transport=transport([
        Response(200, {"status": "1", "result": [evm_record(value="9007199254740993123456")]}),
        Response(200, {"status": "1", "result": []}), Response(200, {"status": "1", "result": []}),
    ])).fetch_address("0x" + "1" * 40)
    repository = BlockchainObservationRepository(database)
    _, first = repository.persist_page(candidate)
    _, second = repository.persist_page(candidate)
    database.commit()
    transfer = database.execute(select(NormalizedTransaction)).scalar_one()

    assert (first, second) == (1, 0)
    assert transfer.raw_amount == "9007199254740993123456"
    assert transfer.amount == Decimal("9007.199254740993123456")
    assert database.execute(select(ProviderObservation)).scalars().all()[0].coverage_state == "complete"


def test_exact_amount_never_uses_binary_float():
    assert exact_amount("1000001", 6) == Decimal("1.000001")
    with pytest.raises(ValueError):
        exact_amount("1.0", 6)


def test_ingestion_propagates_unavailable_provider_without_false_zero(database):
    settings = Settings.from_env({"APP_ENV": "test", "DATA_MODE": "fixture", "DEMO_ENABLED": "true", "DATABASE_URL": "sqlite://"})
    provider = EvmScanProvider(chain="ETH", api_key="", base_url="https://example.test/v2/api", transport=transport([]))
    with pytest.raises(ProviderError) as raised:
        ingest_wallet_page(database, settings=settings, chain="ETH", address="0x" + "1" * 40, provider=provider)
    assert raised.value.code == "PROVIDER_CREDENTIALS_MISSING"


def test_phase4_chain_capabilities_and_scoped_refresh_contract(client, auth_headers):
    chains = client.get("/api/v1/chains", headers=auth_headers)
    assert chains.status_code == 200
    assert {item["network"] for item in chains.json()["items"]} == {"BTC", "ETH", "TRON", "BSC", "POLYGON"}
    assert all(item["retrieval"] == "provider_adapter" for item in chains.json()["items"])

    intake = client.post("/api/v1/complaints", headers={**auth_headers, "Idempotency-Key": "phase4-intake"}, json={
        "complaint_source": "manual", "external_complaint_id": "P4-INGEST-1", "victim_name": "A",
        "suspect_wallets": [{"address": "0x" + "3" * 40, "chain": "ETH"}],
    })
    assert intake.status_code == 201
    case_id = intake.json()["case_id"]
    queued = client.post(f"/api/v1/cases/{case_id}/ingestions", headers=auth_headers,
                         json={"address": "0x" + "3" * 40, "chain": "ETH"})
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"


@pytest.mark.skipif(os.getenv("RUN_LIVE_PROVIDER_SMOKE") != "true" or not os.getenv("ETHERSCAN_API_KEY"),
                    reason="requires explicit live-smoke opt-in and ETHERSCAN_API_KEY")
def test_live_evm_smoke_is_explicitly_gated():
    settings = Settings.from_env(os.environ)
    provider = EvmScanProvider(chain="ETH", api_key=settings.etherscan_api_key,
                                base_url=settings.etherscan_base_url,
                                transport=JsonHttpTransport(connect_timeout_seconds=settings.provider_connect_timeout_seconds,
                                                            request_timeout_seconds=settings.provider_request_timeout_seconds,
                                                            max_attempts=settings.provider_max_attempts))
    page = provider.fetch_address("0x0000000000000000000000000000000000000000", page_size=1)
    assert page.provider == "etherscan_v2"
