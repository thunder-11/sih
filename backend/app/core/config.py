"""Typed runtime configuration with fail-fast production validation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import Mapping
from dotenv import load_dotenv

# Load .env file from backend root or current directory
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()


DEVELOPMENT_SECRET = "development-only-secret-change-me"
VALID_ENVIRONMENTS = {"development", "test", "staging", "production"}
VALID_DATA_MODES = {"live", "fixture"}
VALID_CHAINS = {"BTC", "ETH", "TRON", "BSC", "POLYGON"}


class ConfigurationError(RuntimeError):
    """Raised when runtime settings would create an unsafe or invalid service."""

    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        super().__init__("Invalid application configuration: " + "; ".join(errors))


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError([f"Invalid boolean value: {value!r}"])


def _as_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _is_configured(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized) and "placeholder" not in normalized and not normalized.startswith("change-me")


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    app_version: str
    log_level: str
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_hours: int
    refresh_token_expire_hours: int
    pii_encryption_key: str
    report_time_max_future_skew_seconds: int
    cors_allowed_origins: tuple[str, ...]
    data_mode: str
    demo_enabled: bool
    enabled_chains: tuple[str, ...]
    etherscan_api_key: str
    trongrid_api_key: str
    tronscan_api_key: str
    bscscan_api_key: str
    polygonscan_api_key: str
    ethereum_rpc_url: str
    bsc_rpc_url: str
    polygon_rpc_url: str
    blockstream_base_url: str
    etherscan_base_url: str
    trongrid_base_url: str
    bscscan_base_url: str
    polygonscan_base_url: str
    reports_dir: str
    notices_dir: str
    default_max_hops: int
    max_hop_limit: int
    min_amount_filter_usd: float
    tx_cache_ttl_hours: int
    redis_cache_url: str
    redis_registry_url: str
    celery_broker_url: str
    celery_result_backend: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    job_lease_seconds: int
    job_max_attempts: int
    outbox_batch_size: int
    provider_connect_timeout_seconds: float
    provider_request_timeout_seconds: float
    provider_max_attempts: int
    provider_page_size: int
    bitcoin_finality_confirmations: int
    evm_finality_confirmations: int
    tron_finality_confirmations: int
    coingecko_api_key: str
    coingecko_base_url: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        app_env = source.get("APP_ENV", "development").strip().lower()
        default_mode = "fixture" if app_env in {"development", "test"} else "live"
        data_mode = source.get("DATA_MODE", default_mode).strip().lower()
        demo_default = data_mode == "fixture"
        default_origins = ("http://localhost:5173", "http://127.0.0.1:5173")

        try:
            access_hours = int(source.get("ACCESS_TOKEN_EXPIRE_HOURS", "24"))
            refresh_hours = int(source.get("REFRESH_TOKEN_EXPIRE_HOURS", "168"))
            report_skew = int(source.get("REPORT_TIME_MAX_FUTURE_SKEW_SECONDS", "300"))
            default_hops = int(source.get("DEFAULT_MAX_HOPS", "4"))
            max_hops = int(source.get("MAX_HOP_LIMIT", "6"))
            min_amount = float(source.get("MIN_AMOUNT_FILTER_USD", "50"))
            cache_hours = int(source.get("TX_CACHE_TTL_HOURS", "6"))
            job_lease_seconds = int(source.get("JOB_LEASE_SECONDS", "60"))
            job_max_attempts = int(source.get("JOB_MAX_ATTEMPTS", "5"))
            outbox_batch_size = int(source.get("OUTBOX_BATCH_SIZE", "100"))
            provider_max_attempts = int(source.get("PROVIDER_MAX_ATTEMPTS", "3"))
            provider_page_size = int(source.get("PROVIDER_PAGE_SIZE", "100"))
            bitcoin_finality = int(source.get("BITCOIN_FINALITY_CONFIRMATIONS", "6"))
            evm_finality = int(source.get("EVM_FINALITY_CONFIRMATIONS", "12"))
            tron_finality = int(source.get("TRON_FINALITY_CONFIRMATIONS", "19"))
            provider_connect_timeout = float(source.get("PROVIDER_CONNECT_TIMEOUT_SECONDS", "3"))
            provider_request_timeout = float(source.get("PROVIDER_REQUEST_TIMEOUT_SECONDS", "10"))
        except ValueError as exc:
            raise ConfigurationError([f"Invalid numeric configuration: {exc}"]) from exc

        return cls(
            app_env=app_env,
            app_version=source.get("APP_VERSION", "1.13.0-phase13"),
            log_level=source.get("LOG_LEVEL", "INFO").upper(),
            database_url=source.get("DATABASE_URL", "sqlite:///./cfas.db"),
            jwt_secret_key=source.get("JWT_SECRET_KEY", source.get("SECRET_KEY", DEVELOPMENT_SECRET)),
            jwt_algorithm=source.get("JWT_ALGORITHM", "HS256"),
            access_token_expire_hours=access_hours,
            refresh_token_expire_hours=refresh_hours,
            pii_encryption_key=source.get("PII_ENCRYPTION_KEY", ""),
            report_time_max_future_skew_seconds=report_skew,
            cors_allowed_origins=_as_csv(source.get("CORS_ALLOWED_ORIGINS"), default_origins),
            data_mode=data_mode,
            demo_enabled=_as_bool(source.get("DEMO_ENABLED"), demo_default),
            enabled_chains=tuple(chain.upper() for chain in _as_csv(
                source.get("ENABLED_CHAINS"), ("BTC", "ETH", "TRON", "BSC", "POLYGON")
            )),
            etherscan_api_key=source.get("ETHERSCAN_API_KEY", ""),
            trongrid_api_key=source.get("TRONGRID_API_KEY", ""),
            tronscan_api_key=source.get("TRONSCAN_API_KEY", ""),
            bscscan_api_key=source.get("BSCSCAN_API_KEY", ""),
            polygonscan_api_key=source.get("POLYGONSCAN_API_KEY", ""),
            ethereum_rpc_url=source.get("ETHEREUM_RPC_URL", ""),
            bsc_rpc_url=source.get("BSC_RPC_URL", ""),
            polygon_rpc_url=source.get("POLYGON_RPC_URL", ""),
            blockstream_base_url=source.get("BLOCKSTREAM_BASE_URL", "https://blockstream.info/api"),
            # EvmScanProvider always sends a V2-style `chainid` param (one key
            # queries chain ids 1/56/137 on the unified host); the legacy
            # per-chain V1 hosts reject that combination outright with
            # {"status":"0","message":"NOTOK","result":"...deprecated V1 endpoint..."}.
            etherscan_base_url=source.get("ETHERSCAN_BASE_URL", "https://api.etherscan.io/v2/api"),
            trongrid_base_url=source.get("TRONGRID_BASE_URL", "https://api.trongrid.io"),
            bscscan_base_url=source.get("BSCSCAN_BASE_URL", "https://api.etherscan.io/v2/api"),
            polygonscan_base_url=source.get("POLYGONSCAN_BASE_URL", "https://api.etherscan.io/v2/api"),
            reports_dir=source.get("REPORTS_DIR", "./reports"),
            notices_dir=source.get("NOTICES_DIR", "./notices"),
            default_max_hops=default_hops,
            max_hop_limit=max_hops,
            min_amount_filter_usd=min_amount,
            tx_cache_ttl_hours=cache_hours,
            redis_cache_url=source.get("REDIS_CACHE_URL", ""),
            redis_registry_url=source.get("REDIS_REGISTRY_URL", ""),
            celery_broker_url=source.get("CELERY_BROKER_URL", ""),
            celery_result_backend=source.get("CELERY_RESULT_BACKEND", ""),
            neo4j_uri=source.get("NEO4J_URI", ""),
            neo4j_user=source.get("NEO4J_USER", ""),
            neo4j_password=source.get("NEO4J_PASSWORD", ""),
            job_lease_seconds=job_lease_seconds,
            job_max_attempts=job_max_attempts,
            outbox_batch_size=outbox_batch_size,
            provider_connect_timeout_seconds=provider_connect_timeout,
            provider_request_timeout_seconds=provider_request_timeout,
            provider_max_attempts=provider_max_attempts,
            provider_page_size=provider_page_size,
            bitcoin_finality_confirmations=bitcoin_finality,
            evm_finality_confirmations=evm_finality,
            tron_finality_confirmations=tron_finality,
            coingecko_api_key=source.get("COINGECKO_API_KEY", ""),
            coingecko_base_url=source.get("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"),
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_deployed(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def fixture_data_enabled(self) -> bool:
        return self.data_mode == "fixture" and self.demo_enabled

    def provider_status(self) -> dict[str, str]:
        configured = {
            "BTC": _is_configured(self.blockstream_base_url),
            "ETH": _is_configured(self.etherscan_api_key) or _is_configured(self.ethereum_rpc_url),
            "TRON": _is_configured(self.trongrid_api_key) or _is_configured(self.tronscan_api_key),
            "BSC": _is_configured(self.bscscan_api_key) or _is_configured(self.bsc_rpc_url),
            "POLYGON": _is_configured(self.polygonscan_api_key) or _is_configured(self.polygon_rpc_url),
        }
        return {
            chain: ("configured" if configured.get(chain, False) else "missing_credentials")
            for chain in self.enabled_chains
        }

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.app_env not in VALID_ENVIRONMENTS:
            errors.append(f"APP_ENV must be one of {sorted(VALID_ENVIRONMENTS)}")
        if self.data_mode not in VALID_DATA_MODES:
            errors.append(f"DATA_MODE must be one of {sorted(VALID_DATA_MODES)}")
        unknown_chains = sorted(set(self.enabled_chains) - VALID_CHAINS)
        if unknown_chains:
            errors.append(f"ENABLED_CHAINS contains unsupported values: {unknown_chains}")
        if not 1 <= self.default_max_hops <= self.max_hop_limit <= 6:
            errors.append("Tracing depth must satisfy 1 <= DEFAULT_MAX_HOPS <= MAX_HOP_LIMIT <= 6")
        if self.access_token_expire_hours <= 0 or self.refresh_token_expire_hours <= 0:
            errors.append("ACCESS_TOKEN_EXPIRE_HOURS and REFRESH_TOKEN_EXPIRE_HOURS must be positive")
        if self.report_time_max_future_skew_seconds < 0:
            errors.append("REPORT_TIME_MAX_FUTURE_SKEW_SECONDS cannot be negative")
        if self.job_lease_seconds <= 0 or self.job_max_attempts <= 0 or self.outbox_batch_size <= 0:
            errors.append("JOB_LEASE_SECONDS, JOB_MAX_ATTEMPTS, and OUTBOX_BATCH_SIZE must be positive")
        if not 1 <= self.provider_max_attempts <= 3:
            errors.append("PROVIDER_MAX_ATTEMPTS must be between 1 and 3")
        if not 1 <= self.provider_page_size <= 1000:
            errors.append("PROVIDER_PAGE_SIZE must be between 1 and 1000")
        if self.provider_connect_timeout_seconds <= 0 or self.provider_request_timeout_seconds <= 0:
            errors.append("Provider timeouts must be positive")
        if self.provider_connect_timeout_seconds > self.provider_request_timeout_seconds:
            errors.append("PROVIDER_CONNECT_TIMEOUT_SECONDS cannot exceed PROVIDER_REQUEST_TIMEOUT_SECONDS")
        if min(self.bitcoin_finality_confirmations, self.evm_finality_confirmations, self.tron_finality_confirmations) < 1:
            errors.append("Network finality confirmation thresholds must be positive")
        if self.data_mode == "fixture" and not self.demo_enabled:
            errors.append("DATA_MODE=fixture requires DEMO_ENABLED=true")
        if self.data_mode == "live" and self.demo_enabled:
            errors.append("DATA_MODE=live requires DEMO_ENABLED=false")

        if self.is_deployed:
            if self.fixture_data_enabled or self.demo_enabled:
                errors.append("Staging/production cannot enable fixture or demo data")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                errors.append("Staging/production DATABASE_URL must use PostgreSQL")

        if self.is_production:
            if (not _is_configured(self.jwt_secret_key) or self.jwt_secret_key == DEVELOPMENT_SECRET
                    or len(self.jwt_secret_key) < 32):
                errors.append("Production JWT_SECRET_KEY must be a non-default secret of at least 32 characters")
            if self.pii_encryption_key and (not _is_configured(self.pii_encryption_key) or len(self.pii_encryption_key) < 32):
                errors.append("PII_ENCRYPTION_KEY, when set, must be a non-default secret of at least 32 characters")
            if not self.cors_allowed_origins or "*" in self.cors_allowed_origins:
                errors.append("Production CORS_ALLOWED_ORIGINS must contain explicit origins")
            missing = [chain for chain, state in self.provider_status().items() if state != "configured"]
            if missing:
                errors.append(f"Production provider credentials are missing for enabled chains: {missing}")
            if not _is_configured(self.redis_cache_url):
                errors.append("Production REDIS_CACHE_URL must be configured")
            if not _is_configured(self.celery_broker_url):
                errors.append("Production CELERY_BROKER_URL must be configured")
        return errors

    def validate_startup(self) -> None:
        errors = self.validate()
        if errors:
            raise ConfigurationError(errors)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
