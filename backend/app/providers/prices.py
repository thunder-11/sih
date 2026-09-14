"""Optional real historical fiat quotes; unsupported assets remain explicitly unvalued."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.contracts import ProviderError
from app.providers.http import JsonHttpTransport, utc_now


NATIVE_COIN_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "TRON": "tron", "BSC": "binancecoin", "POLYGON": "matic-network"}


@dataclass(frozen=True, slots=True)
class PriceQuote:
    amount_usd: Decimal
    quote_time: datetime
    source: str
    source_uri: str


class CoinGeckoHistoricalProvider:
    provider_name = "coingecko"

    def __init__(self, *, api_key: str, base_url: str, transport: JsonHttpTransport):
        self.api_key, self.base_url, self.transport = api_key, base_url.rstrip("/"), transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key and "placeholder" not in self.api_key.lower())

    def quote_native(self, *, chain: str, event_time: datetime, amount: Decimal) -> PriceQuote | None:
        if not self.configured or chain not in NATIVE_COIN_IDS:
            return None
        coin_id = NATIVE_COIN_IDS[chain]
        date = event_time.astimezone(timezone.utc).strftime("%d-%m-%Y")
        headers = {"x-cg-demo-api-key": self.api_key}
        payload = self.transport.get(f"{self.base_url}/coins/{coin_id}/history", params={"date": date, "localization": "false"}, headers=headers)
        try:
            unit = Decimal(str(payload["market_data"]["current_price"]["usd"]))
        except (KeyError, TypeError, InvalidOperation) as exc:
            raise ProviderError("PRICE_PROVIDER_MALFORMED_RESPONSE", "Historical price response was incomplete", retryable=False) from exc
        if not unit.is_finite() or unit < 0:
            raise ProviderError("PRICE_PROVIDER_MALFORMED_RESPONSE", "Historical price was invalid", retryable=False)
        return PriceQuote(amount_usd=amount * unit, quote_time=event_time.astimezone(timezone.utc), source=self.provider_name,
                          source_uri=f"{self.base_url}/coins/{coin_id}/history?date={date}")
