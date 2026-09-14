from dotenv import load_dotenv
from app.core.config import get_settings

load_dotenv()
settings = get_settings()

# ── Database ──────────────────────────────────────────────
DATABASE_URL = settings.database_url

# ── JWT Auth ──────────────────────────────────────────────
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_HOURS = settings.access_token_expire_hours

# ── Blockchain API Keys (plug in when available) ──────────
# Set these in a .env file or environment variables:
#   ETHERSCAN_API_KEY=your_key_here
#   TRONGRID_API_KEY=your_key_here
#   BSCSCAN_API_KEY=your_key_here
ETHERSCAN_API_KEY = settings.etherscan_api_key
TRONGRID_API_KEY = settings.trongrid_api_key
TRONSCAN_API_KEY = settings.tronscan_api_key
BSCSCAN_API_KEY = settings.bscscan_api_key
POLYGONSCAN_API_KEY = settings.polygonscan_api_key

# Fixture behavior is controlled only by explicit DATA_MODE and DEMO_ENABLED settings.
USE_DEMO_DATA = settings.fixture_data_enabled

# ── API Base URLs ─────────────────────────────────────────
ETHERSCAN_BASE_URL = settings.etherscan_base_url
TRONGRID_BASE_URL = settings.trongrid_base_url
BSCSCAN_BASE_URL = settings.bscscan_base_url
POLYGONSCAN_BASE_URL = settings.polygonscan_base_url
BLOCKSTREAM_BASE_URL = settings.blockstream_base_url

# ── Tracing Defaults ─────────────────────────────────────
DEFAULT_MAX_HOPS = settings.default_max_hops
MAX_HOP_LIMIT = settings.max_hop_limit
MIN_AMOUNT_FILTER_USD = settings.min_amount_filter_usd
TX_CACHE_TTL_HOURS = settings.tx_cache_ttl_hours

# ── Risk Scoring Weights ─────────────────────────────────
RISK_WEIGHT_MIXER = 30
RISK_WEIGHT_BRIDGE = 20
RISK_WEIGHT_HIGH_VELOCITY = 15
RISK_WEIGHT_PEELING = 15
RISK_WEIGHT_BURNER = 10
RISK_WEIGHT_MULTI_COMPLAINT = 10

# ── Syndicate Detection ──────────────────────────────────
SYNDICATE_THRESHOLD = 3

# ── Report Generation ────────────────────────────────────
REPORTS_DIR = settings.reports_dir
NOTICES_DIR = settings.notices_dir
