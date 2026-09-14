"""
Multi-chain blockchain data fetcher — unified interface.
Uses real APIs in live mode and isolated fixtures only in explicit fixture mode.
"""
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from models import Transaction, Wallet, VaspAddress, MixerBridgeDirectory
from config import USE_DEMO_DATA


# ═══════════════════════════════════════════════════════════
# Address Validation & Chain Auto-Detection
# ═══════════════════════════════════════════════════════════
CHAIN_PATTERNS = {
    "BTC": re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$"),
    "ETH": re.compile(r"^0x[a-fA-F0-9]{40}$"),
    "TRON": re.compile(r"^T[a-zA-Z0-9]{33}$"),
    "BSC": re.compile(r"^0x[a-fA-F0-9]{40}$"),  # Same as ETH format
}


def detect_chain(address: str) -> str | None:
    """Auto-detect blockchain from address format. Returns chain name or None."""
    if re.match(r"^T[a-zA-Z0-9]{33}$", address):
        return "TRON"
    if re.match(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$", address):
        return "BTC"
    if re.match(r"^0x[a-fA-F0-9]{40}$", address):
        return "ETH"  # Default to ETH for EVM; user can override to BSC
    return None


def validate_address(address: str, chain: str) -> bool:
    """Validate address format against the specified chain's regex."""
    pattern = CHAIN_PATTERNS.get(chain)
    if not pattern:
        return False
    return bool(pattern.match(address))


# ═══════════════════════════════════════════════════════════
# Transaction Fetching — Unified Interface
# ═══════════════════════════════════════════════════════════
def _to_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def fetch_transactions(address: str, chain: str, db: Session, after_time: datetime = None) -> list[dict]:
    """
    Fetch all transactions for an address.
    1. Check DB cache first (6h TTL).
    2. If explicit fixture mode is active, return fixture transactions.
    3. Otherwise call a real provider without synthesizing a result.
    """
    # Check DB cache
    cached = _get_cached_transactions(address, chain, db)
    if cached:
        txs = cached
    elif USE_DEMO_DATA:
        txs = _get_demo_transactions(address, chain, db)
    else:
        txs = _fetch_from_api(address, chain)
        if txs:
            _cache_transactions(txs, db)

    # Apply time filter if provided (with 2-hour grace margin)
    if after_time and txs:
        after_utc = _to_utc(after_time)
        if after_utc:
            margin = after_utc - timedelta(hours=2)
            txs = [t for t in txs if t.get("timestamp") and (_to_utc(t["timestamp"]) or datetime.now(timezone.utc)) >= margin]

    return txs


def _is_demo_address(address: str) -> bool:
    if not address:
        return False
    addr_upper = address.upper()
    return (
        "DEMO" in addr_upper or
        "MULE" in addr_upper or
        "DEP_" in addr_upper or
        "VICTIM" in addr_upper or
        "MIXER" in addr_upper or
        "BRIDGE" in addr_upper or
        "COINDCX" in addr_upper or
        "WAZIRX" in addr_upper or
        "BINANCE" in addr_upper
    )


def _get_cached_transactions(address: str, chain: str, db: Session) -> list[dict] | None:
    """Return cached transactions if they exist and are fresh (< 6 hours old)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    txs = db.query(Transaction).filter(
        ((Transaction.from_address == address) | (Transaction.to_address == address)),
        Transaction.chain == chain,
        Transaction.fetched_at >= cutoff,
    ).all()

    if not txs:
        return None

    return [_tx_to_dict(tx) for tx in txs]


def _get_demo_transactions(address: str, chain: str, db: Session) -> list[dict]:
    """Get pre-seeded demo transactions from database, or generate synthetic trace path."""
    txs = db.query(Transaction).filter(
        ((Transaction.from_address == address) | (Transaction.to_address == address)),
        Transaction.chain == chain,
    ).all()
    if txs:
        return [_tx_to_dict(tx) for tx in txs]
    return _generate_synthetic_trace_path(address, chain, db)


def _generate_synthetic_trace_path(address: str, chain: str, db: Session) -> list[dict]:
    """Generate a realistic 3-hop synthetic trace path ending at a VASP for unknown demo addresses."""
    from models import VaspDirectory
    now = datetime.now(timezone.utc)
    clean_addr = address.replace("0x", "").replace("T", "")
    short_id = clean_addr[:8] if len(clean_addr) >= 8 else "001"

    vasp = db.query(VaspDirectory).filter_by(is_fiu_ind_registered=True).first()
    vasp_id = vasp.id if vasp else "vasp-coindcx"
    vasp_name = vasp.vasp_name if vasp else "CoinDCX"

    prefix = "T" if chain == "TRON" else "0x" if chain in ("ETH", "BSC") else "bc1q"

    mule1 = f"{prefix}MULE1_LAYER_{short_id}"
    mule2 = f"{prefix}MULE2_PEEL_{short_id}"
    deposit_addr = f"{prefix}DEP_{vasp_id[:6].upper()}_{short_id}"
    hot_wallet = f"{prefix}HOT_{vasp_id[:6].upper()}_{short_id}"

    existing_dep = db.query(VaspAddress).filter_by(address=deposit_addr, chain=chain).first()
    if not existing_dep:
        db.add(VaspAddress(address=deposit_addr, chain=chain, vasp_id=vasp_id, address_tag=f"{vasp_name} User Deposit"))

    existing_hot = db.query(VaspAddress).filter_by(address=hot_wallet, chain=chain).first()
    if not existing_hot:
        db.add(VaspAddress(address=hot_wallet, chain=chain, vasp_id=vasp_id, address_tag=f"{vasp_name} Hot Wallet"))

    _ensure_wallet_record(db, address, chain, "ORIGIN_VICTIM")
    _ensure_wallet_record(db, mule1, chain, "MULE_LAYER")
    _ensure_wallet_record(db, mule2, chain, "MULE_LAYER")
    _ensure_wallet_record(db, deposit_addr, chain, "VASP_DEPOSIT", vasp_id=vasp_id)
    _ensure_wallet_record(db, hot_wallet, chain, "VASP_HOT_WALLET", vasp_id=vasp_id)

    token = "USDT" if chain in ("TRON", "ETH", "BSC") else "BTC"
    amt1 = 10000.0 if token == "USDT" else 0.25
    amt2 = 9500.0 if token == "USDT" else 0.24
    amt3 = 9200.0 if token == "USDT" else 0.23

    syn_txs = [
        Transaction(
            tx_hash=f"SYN_TX_01_{short_id}", chain=chain,
            from_address=address, to_address=mule1,
            token_symbol=token, amount=amt1, amount_usd=amt1 if token == "USDT" else amt1 * 60000,
            block_number=70000001, timestamp=now - timedelta(hours=4),
        ),
        Transaction(
            tx_hash=f"SYN_TX_02_{short_id}", chain=chain,
            from_address=mule1, to_address=mule2,
            token_symbol=token, amount=amt2, amount_usd=amt2 if token == "USDT" else amt2 * 60000,
            block_number=70000050, timestamp=now - timedelta(hours=3),
            is_peeling_tx=True,
        ),
        Transaction(
            tx_hash=f"SYN_TX_03_{short_id}", chain=chain,
            from_address=mule2, to_address=deposit_addr,
            token_symbol=token, amount=amt3, amount_usd=amt3 if token == "USDT" else amt3 * 60000,
            block_number=70000200, timestamp=now - timedelta(hours=2),
        ),
        Transaction(
            tx_hash=f"SYN_TX_04_{short_id}", chain=chain,
            from_address=deposit_addr, to_address=hot_wallet,
            token_symbol=token, amount=amt3, amount_usd=amt3 if token == "USDT" else amt3 * 60000,
            block_number=70000220, timestamp=now - timedelta(hours=1, minutes=45),
        ),
    ]

    for t in syn_txs:
        ex = db.query(Transaction).filter_by(tx_hash=t.tx_hash).first()
        if not ex:
            db.add(t)
    db.flush()

    matching = [t for t in syn_txs if t.from_address == address or t.to_address == address]
    return [_tx_to_dict(t) for t in matching]


def _ensure_wallet_record(db: Session, address: str, chain: str, node_type: str, vasp_id: str = None):
    existing = db.query(Wallet).filter_by(address=address, chain=chain).first()
    if not existing:
        w = Wallet(
            address=address, chain=chain, node_type=node_type, vasp_id=vasp_id,
            first_seen=datetime.now(timezone.utc), risk_flags="[]"
        )
        db.add(w)
        db.flush()


def _tx_to_dict(tx: Transaction) -> dict:
    return {
        "tx_hash": tx.tx_hash,
        "chain": tx.chain,
        "from_address": tx.from_address,
        "to_address": tx.to_address,
        "token_symbol": tx.token_symbol,
        "token_contract": tx.token_contract,
        "amount": float(tx.amount),
        "amount_usd": float(tx.amount_usd) if tx.amount_usd else None,
        "block_number": tx.block_number,
        "timestamp": tx.timestamp,
        "is_peeling_tx": tx.is_peeling_tx,
        "is_bridge_tx": tx.is_bridge_tx,
    }


def _cache_transactions(txs: list[dict], db: Session):
    """Store fetched transactions in DB for caching."""
    for tx_data in txs:
        existing = db.query(Transaction).filter_by(tx_hash=tx_data["tx_hash"]).first()
        if not existing:
            tx = Transaction(
                tx_hash=tx_data["tx_hash"],
                chain=tx_data["chain"],
                from_address=tx_data["from_address"],
                to_address=tx_data["to_address"],
                token_symbol=tx_data.get("token_symbol", "NATIVE"),
                token_contract=tx_data.get("token_contract"),
                amount=tx_data["amount"],
                amount_usd=tx_data.get("amount_usd"),
                block_number=tx_data.get("block_number"),
                timestamp=tx_data["timestamp"],
            )
            db.add(tx)
    db.flush()


# ═══════════════════════════════════════════════════════════
# Real API Fetchers (activated when API keys are provided)
# ═══════════════════════════════════════════════════════════
def _fetch_from_api(address: str, chain: str) -> list[dict]:
    """Dispatch to chain-specific API fetcher."""
    if chain == "TRON":
        return _fetch_tron(address)
    elif chain in ("ETH", "BSC"):
        return _fetch_evm(address, chain)
    elif chain == "BTC":
        return _fetch_btc(address)
    return []


def _fetch_tron(address: str) -> list[dict]:
    """Fetch TRC-20 + native TRX transactions from TronGrid."""
    import httpx
    from config import TRONGRID_BASE_URL, TRONGRID_API_KEY

    if not TRONGRID_API_KEY:
        return []

    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
    results = []

    # TRC-20 token transfers (USDT etc.)
    try:
        resp = httpx.get(
            f"{TRONGRID_BASE_URL}/v1/accounts/{address}/transactions/trc20",
            params={"limit": 50, "only_confirmed": "true"},
            headers=headers,
            timeout=3.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for tx in data:
                token_info = tx.get("token_info", {})
                decimals = int(token_info.get("decimals", 6))
                raw_value = int(tx.get("value", "0"))
                amount = raw_value / (10 ** decimals)
                results.append({
                    "tx_hash": tx.get("transaction_id", ""),
                    "chain": "TRON",
                    "from_address": tx.get("from", ""),
                    "to_address": tx.get("to", ""),
                    "token_symbol": token_info.get("symbol", "TRC20"),
                    "token_contract": tx.get("token_info", {}).get("address"),
                    "amount": amount,
                    "amount_usd": amount if token_info.get("symbol") in ("USDT", "USDC") else None,
                    "block_number": tx.get("block_timestamp"),
                    "timestamp": datetime.fromtimestamp(
                        tx.get("block_timestamp", 0) / 1000, tz=timezone.utc
                    ),
                })
    except Exception:
        pass  # Graceful fallback on API failure

    # Native TRX transfers
    try:
        resp = httpx.get(
            f"{TRONGRID_BASE_URL}/v1/accounts/{address}/transactions",
            params={"limit": 50, "only_confirmed": "true"},
            headers=headers,
            timeout=3.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for tx in data:
                raw_data = tx.get("raw_data", {}).get("contract", [{}])[0]
                param = raw_data.get("parameter", {}).get("value", {})
                amount_sun = param.get("amount", 0)
                amount_trx = amount_sun / 1_000_000
                if amount_trx > 0:
                    results.append({
                        "tx_hash": tx.get("txID", ""),
                        "chain": "TRON",
                        "from_address": param.get("owner_address", ""),
                        "to_address": param.get("to_address", ""),
                        "token_symbol": "TRX",
                        "token_contract": None,
                        "amount": amount_trx,
                        "amount_usd": None,
                        "block_number": tx.get("blockNumber"),
                        "timestamp": datetime.fromtimestamp(
                            tx.get("block_timestamp", 0) / 1000, tz=timezone.utc
                        ),
                    })
    except Exception:
        pass

    return results


def _fetch_evm(address: str, chain: str) -> list[dict]:
    """Fetch ERC-20/BEP-20 + native ETH/BNB transactions from Etherscan/BscScan."""
    import httpx
    from config import ETHERSCAN_BASE_URL, BSCSCAN_BASE_URL, ETHERSCAN_API_KEY, BSCSCAN_API_KEY

    base_url = ETHERSCAN_BASE_URL if chain == "ETH" else BSCSCAN_BASE_URL
    api_key = ETHERSCAN_API_KEY if chain == "ETH" else BSCSCAN_API_KEY

    if not api_key:
        return []

    results = []

    # ERC-20 / BEP-20 token transfers
    try:
        resp = httpx.get(base_url, params={
            "module": "account", "action": "tokentx",
            "address": address, "sort": "desc", "page": 1, "offset": 50,
            "apikey": api_key,
        }, timeout=15)
        if resp.status_code == 200:
            data = resp.json().get("result", [])
            if isinstance(data, list):
                for tx in data:
                    decimals = int(tx.get("tokenDecimal", 18))
                    raw_value = int(tx.get("value", "0"))
                    amount = raw_value / (10 ** decimals)
                    symbol = tx.get("tokenSymbol", "TOKEN")
                    results.append({
                        "tx_hash": tx.get("hash", ""),
                        "chain": chain,
                        "from_address": tx.get("from", "").lower(),
                        "to_address": tx.get("to", "").lower(),
                        "token_symbol": symbol,
                        "token_contract": tx.get("contractAddress"),
                        "amount": amount,
                        "amount_usd": amount if symbol in ("USDT", "USDC", "DAI", "BUSD") else None,
                        "block_number": int(tx.get("blockNumber", 0)),
                        "timestamp": datetime.fromtimestamp(
                            int(tx.get("timeStamp", 0)), tz=timezone.utc
                        ),
                    })
    except Exception:
        pass

    # Native ETH/BNB transfers
    try:
        resp = httpx.get(base_url, params={
            "module": "account", "action": "txlist",
            "address": address, "sort": "desc", "page": 1, "offset": 50,
            "apikey": api_key,
        }, timeout=15)
        if resp.status_code == 200:
            data = resp.json().get("result", [])
            if isinstance(data, list):
                for tx in data:
                    wei = int(tx.get("value", "0"))
                    amount = wei / 1e18
                    if amount > 0:
                        native_symbol = "ETH" if chain == "ETH" else "BNB"
                        results.append({
                            "tx_hash": tx.get("hash", ""),
                            "chain": chain,
                            "from_address": tx.get("from", "").lower(),
                            "to_address": tx.get("to", "").lower(),
                            "token_symbol": native_symbol,
                            "token_contract": None,
                            "amount": amount,
                            "amount_usd": None,
                            "block_number": int(tx.get("blockNumber", 0)),
                            "timestamp": datetime.fromtimestamp(
                                int(tx.get("timeStamp", 0)), tz=timezone.utc
                            ),
                        })
    except Exception:
        pass

    return results


def _fetch_btc(address: str) -> list[dict]:
    """Fetch BTC transactions from Blockstream API (no key required)."""
    import httpx
    from config import BLOCKSTREAM_BASE_URL

    results = []
    try:
        resp = httpx.get(f"{BLOCKSTREAM_BASE_URL}/address/{address}/txs", timeout=15)
        if resp.status_code == 200:
            txs = resp.json()
            for tx in txs[:50]:
                # Determine if address is sender or receiver for each output
                for vout in tx.get("vout", []):
                    addr = vout.get("scriptpubkey_address", "")
                    if addr:
                        amount_btc = vout.get("value", 0) / 1e8
                        results.append({
                            "tx_hash": tx.get("txid", ""),
                            "chain": "BTC",
                            "from_address": address if addr != address else "unknown",
                            "to_address": addr,
                            "token_symbol": "BTC",
                            "token_contract": None,
                            "amount": amount_btc,
                            "amount_usd": None,
                            "block_number": tx.get("status", {}).get("block_height"),
                            "timestamp": datetime.fromtimestamp(
                                tx.get("status", {}).get("block_time", 0), tz=timezone.utc
                            ) if tx.get("status", {}).get("block_time") else datetime.now(timezone.utc),
                        })
    except Exception:
        pass

    return results


# ═══════════════════════════════════════════════════════════
# VASP & Mixer Lookup Helpers
# ═══════════════════════════════════════════════════════════
def check_vasp_address(address: str, chain: str, db: Session) -> dict | None:
    """Check if address is in the known VASP address database."""
    match = db.query(VaspAddress).filter_by(address=address, chain=chain).first()
    if match:
        return {
            "vasp_id": match.vasp_id,
            "vasp_name": match.vasp.vasp_name,
            "is_fiu_ind_registered": match.vasp.is_fiu_ind_registered,
            "nodal_officer_email": match.vasp.nodal_officer_email,
            "address_tag": match.address_tag,
        }
    return None


def check_mixer_bridge(address: str, chain: str, db: Session) -> dict | None:
    """Check if address is a known mixer or bridge contract."""
    match = db.query(MixerBridgeDirectory).filter_by(contract_address=address, chain=chain).first()
    if match:
        return {
            "protocol_name": match.protocol_name,
            "entity_type": match.entity_type,
            "risk_weight": match.risk_weight,
        }
    return None
