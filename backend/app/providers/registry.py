"""Provider construction and capability disclosure for Phase 4."""

from __future__ import annotations

from app.core.config import Settings
from app.providers.bitcoin import EsploraBitcoinProvider
from app.providers.contracts import ProviderError
from app.providers.evm import EvmScanProvider
from app.providers.http import JsonHttpTransport
from app.providers.tron import TronGridProvider


def provider_for(chain: str, settings: Settings, *, transport: JsonHttpTransport | None = None):
    chain = chain.upper()
    transport = transport or JsonHttpTransport(connect_timeout_seconds=settings.provider_connect_timeout_seconds,
                                                request_timeout_seconds=settings.provider_request_timeout_seconds,
                                                max_attempts=settings.provider_max_attempts)
    if chain == "BTC":
        return EsploraBitcoinProvider(base_url=settings.blockstream_base_url, transport=transport,
                                      finality_confirmations=settings.bitcoin_finality_confirmations)
    if chain == "TRON":
        return TronGridProvider(api_key=settings.trongrid_api_key, base_url=settings.trongrid_base_url, transport=transport,
                                finality_confirmations=settings.tron_finality_confirmations)
    if chain == "ETH":
        return EvmScanProvider(chain=chain, api_key=settings.etherscan_api_key, base_url=settings.etherscan_base_url,
                               transport=transport, finality_confirmations=settings.evm_finality_confirmations)
    if chain == "BSC":
        return EvmScanProvider(chain=chain, api_key=settings.bscscan_api_key, base_url=settings.bscscan_base_url,
                               transport=transport, finality_confirmations=settings.evm_finality_confirmations)
    if chain == "POLYGON":
        return EvmScanProvider(chain=chain, api_key=settings.polygonscan_api_key, base_url=settings.polygonscan_base_url,
                               transport=transport, finality_confirmations=settings.evm_finality_confirmations)
    raise ProviderError("UNSUPPORTED_CHAIN", f"Unsupported chain {chain}", retryable=False)


def provider_capabilities(settings: Settings) -> list[dict]:
    result = []
    for chain in settings.enabled_chains:
        provider = provider_for(chain, settings)
        configured = getattr(provider, "configured", True)
        result.append({"network": chain, "enabled": True, "provider": provider.provider_name,
                       "provider_status": "configured" if configured else "missing_credentials",
                       "native_transfers": True, "token_transfers": chain != "BTC",
                       "receipts_or_logs": chain != "BTC", "balances": True,
                       "finality_policy": {"BTC": settings.bitcoin_finality_confirmations,
                                           "TRON": settings.tron_finality_confirmations}.get(chain, settings.evm_finality_confirmations)})
    return result
