"""
Seed Data — populates the database with:
  1. Demo users (investigator, analyst, admin)
  2. VASP directory (Indian FIU-IND + Global exchanges)
  3. VASP known addresses (hot wallets, deposit clusters)
  4. Mixer & bridge contract directory
  5. Demo complaint cases with pre-wired trace paths
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from models import (
    User, Case, Wallet, CaseWallet, Transaction,
    VaspDirectory, VaspAddress, MixerBridgeDirectory, Alert,
)
from auth.utils import hash_password
from app.persistence.models import Agency, UserAgencyScope


def seed_all(db: Session):
    """Master seeder — idempotent (checks for existing data first)."""
    if db.query(User).first():
        return  # Already seeded

    print("[SEED] Seeding database...")
    _seed_users(db)
    vasp_map = _seed_vasp_directory(db)
    _seed_vasp_addresses(db, vasp_map)
    _seed_mixer_bridge(db)
    _seed_demo_cases(db, vasp_map)
    db.commit()
    print("[SEED] Seed data loaded successfully.")


# ─────────────────────────────────────────────────────
# 1. USERS
# ─────────────────────────────────────────────────────
def _seed_users(db: Session):
    agency = Agency(
        id="agency-local",
        name="Karnataka Cyber Crime Police",
        jurisdiction="India/Karnataka",
        scope={"data_mode": "fixture"},
        status="active",
    )
    db.add(agency)
    db.flush()
    users = [
        User(
            id="usr-io-001",
            email="inspector.sharma@cyberpolice.gov.in",
            full_name="Inspector S. Sharma",
            badge_number="CYB-2024-1142",
            police_station="Cyber Crime PS, Bengaluru Central",
            password_hash=hash_password("cfas2026"),
            role="investigator",
            status="active",
            primary_agency_id=agency.id,
        ),
        User(
            id="usr-analyst-001",
            email="analyst.mehra@i4c.gov.in",
            full_name="Analyst R. Mehra",
            badge_number="I4C-AN-0087",
            police_station="I4C National Coordination Centre",
            password_hash=hash_password("cfas2026"),
            role="analyst",
            status="active",
            primary_agency_id=agency.id,
        ),
        User(
            id="usr-admin-001",
            email="admin@cfas.gov.in",
            full_name="Superintendent K. Verma",
            badge_number="IPS-KA-2019",
            police_station="State Cyber Crime HQ, Karnataka",
            password_hash=hash_password("cfas2026"),
            role="admin",
            status="active",
            primary_agency_id=agency.id,
        ),
    ]
    db.add_all(users)
    db.flush()
    db.add_all([
        UserAgencyScope(
            user_id=user.id,
            agency_id=agency.id,
            role=user.role,
            permissions=["case:read", "case:write"] + (["case:assign", "case:share"] if user.role in {"analyst", "admin"} else []),
            status="active",
        )
        for user in users
    ])
    db.flush()


# ─────────────────────────────────────────────────────
# 2. VASP DIRECTORY (Exchanges with compliance info)
# ─────────────────────────────────────────────────────
def _seed_vasp_directory(db: Session) -> dict:
    vasps = [
        # ── Indian FIU-IND Registered ────────────────
        VaspDirectory(
            id="vasp-coindcx", vasp_name="CoinDCX",
            legal_entity_name="Neblio Technologies Pvt. Ltd.",
            is_fiu_ind_registered=True, fiu_registration_number="FIU-IND/VA/001",
            nodal_officer_name="Compliance Team", nodal_officer_email="compliance@coindcx.com",
            law_enforcement_portal_url="https://coindcx.com/law-enforcement",
            jurisdiction="India", sla_freeze_hours=24,
        ),
        VaspDirectory(
            id="vasp-wazirx", vasp_name="WazirX",
            legal_entity_name="Zanmai Labs Pvt. Ltd.",
            is_fiu_ind_registered=True, fiu_registration_number="FIU-IND/VA/002",
            nodal_officer_name="Legal & Compliance", nodal_officer_email="compliance@wazirx.com",
            law_enforcement_portal_url="https://wazirx.com/law-enforcement",
            jurisdiction="India", sla_freeze_hours=24,
        ),
        VaspDirectory(
            id="vasp-coinswitch", vasp_name="CoinSwitch",
            legal_entity_name="Bitcipher Labs LLP",
            is_fiu_ind_registered=True, fiu_registration_number="FIU-IND/VA/003",
            nodal_officer_name="Compliance Cell", nodal_officer_email="compliance@coinswitch.co",
            jurisdiction="India", sla_freeze_hours=24,
        ),
        VaspDirectory(
            id="vasp-zebpay", vasp_name="ZebPay",
            legal_entity_name="Awlencan Innovations India Pvt. Ltd.",
            is_fiu_ind_registered=True, fiu_registration_number="FIU-IND/VA/004",
            nodal_officer_name="Nodal Officer", nodal_officer_email="compliance@zebpay.com",
            jurisdiction="India", sla_freeze_hours=24,
        ),
        VaspDirectory(
            id="vasp-mudrex", vasp_name="Mudrex",
            legal_entity_name="Mudrex Inc.",
            is_fiu_ind_registered=True, fiu_registration_number="FIU-IND/VA/005",
            nodal_officer_name="Compliance", nodal_officer_email="compliance@mudrex.com",
            jurisdiction="India", sla_freeze_hours=24,
        ),
        VaspDirectory(
            id="vasp-giottus", vasp_name="Giottus",
            legal_entity_name="Giottus Technologies Pvt. Ltd.",
            is_fiu_ind_registered=True, fiu_registration_number="FIU-IND/VA/006",
            nodal_officer_name="Compliance Officer", nodal_officer_email="compliance@giottus.com",
            jurisdiction="India", sla_freeze_hours=24,
        ),
        # ── Global Tier-1 Exchanges ──────────────────
        VaspDirectory(
            id="vasp-binance", vasp_name="Binance",
            legal_entity_name="Binance Holdings Limited",
            is_fiu_ind_registered=False,
            nodal_officer_name="Law Enforcement Response Team",
            nodal_officer_email="law-enforcement@binance.com",
            law_enforcement_portal_url="https://www.binance.com/en/support/law-enforcement",
            jurisdiction="Global", sla_freeze_hours=72,
        ),
        VaspDirectory(
            id="vasp-okx", vasp_name="OKX",
            legal_entity_name="Okcoin Technology Company Limited",
            is_fiu_ind_registered=False,
            nodal_officer_name="LEA Team", nodal_officer_email="law.enforcement@okx.com",
            jurisdiction="Seychelles", sla_freeze_hours=72,
        ),
        VaspDirectory(
            id="vasp-kucoin", vasp_name="KuCoin",
            legal_entity_name="Mek Global Limited",
            is_fiu_ind_registered=False,
            nodal_officer_name="Compliance", nodal_officer_email="law@kucoin.com",
            jurisdiction="Seychelles", sla_freeze_hours=72,
        ),
        VaspDirectory(
            id="vasp-bybit", vasp_name="Bybit",
            legal_entity_name="Bybit Fintech Limited",
            is_fiu_ind_registered=False,
            nodal_officer_name="Legal", nodal_officer_email="legal@bybit.com",
            jurisdiction="Dubai", sla_freeze_hours=72,
        ),
        VaspDirectory(
            id="vasp-htx", vasp_name="HTX (Huobi)",
            legal_entity_name="HTX Global",
            is_fiu_ind_registered=False,
            nodal_officer_name="Compliance", nodal_officer_email="law@htx.com",
            jurisdiction="Seychelles", sla_freeze_hours=72,
        ),
        VaspDirectory(
            id="vasp-kraken", vasp_name="Kraken",
            legal_entity_name="Payward Inc.",
            is_fiu_ind_registered=False,
            nodal_officer_name="Law Enforcement", nodal_officer_email="le@kraken.com",
            jurisdiction="USA", sla_freeze_hours=48,
        ),
        VaspDirectory(
            id="vasp-coinbase", vasp_name="Coinbase",
            legal_entity_name="Coinbase Inc.",
            is_fiu_ind_registered=False,
            nodal_officer_name="Law Enforcement Response", nodal_officer_email="lert@coinbase.com",
            law_enforcement_portal_url="https://www.coinbase.com/legal/lert",
            jurisdiction="USA", sla_freeze_hours=48,
        ),
        # ── High-Risk / P2P / Instant Swap ───────────
        VaspDirectory(
            id="vasp-fixedfloat", vasp_name="FixedFloat",
            legal_entity_name="FixedFloat LTD",
            is_fiu_ind_registered=False,
            nodal_officer_name="N/A", nodal_officer_email="support@fixedfloat.com",
            jurisdiction="Unknown", sla_freeze_hours=0,
            notes="High-risk instant swap service, minimal KYC",
        ),
        VaspDirectory(
            id="vasp-changenow", vasp_name="ChangeNOW",
            legal_entity_name="ChangeNOW",
            is_fiu_ind_registered=False,
            nodal_officer_name="N/A", nodal_officer_email="support@changenow.io",
            jurisdiction="Unknown", sla_freeze_hours=0,
            notes="Non-custodial instant swap, no KYC",
        ),
        # ── Demo Exchange (Synthetic) ────────────────
        VaspDirectory(
            id="vasp-demo-exchange", vasp_name="Demo Exchange Ltd.",
            legal_entity_name="Demo Exchange (Prototype Only)",
            is_fiu_ind_registered=True, fiu_registration_number="DEMO-FIU-001",
            nodal_officer_name="Demo Compliance Officer",
            nodal_officer_email="compliance@demo-exchange.test",
            jurisdiction="India", sla_freeze_hours=24,
            notes="Synthetic demo exchange for guaranteed live demo flows",
        ),
    ]
    db.add_all(vasps)
    db.flush()
    return {v.id: v for v in vasps}


# ─────────────────────────────────────────────────────
# 3. VASP KNOWN ADDRESSES
# ─────────────────────────────────────────────────────
def _seed_vasp_addresses(db: Session, vasp_map: dict):
    addresses = [
        # ── CoinDCX (Real publicly tagged addresses) ──
        VaspAddress(address="TLbXrpFRv4UwPn2YJWGbLqvcF9YPbMU9Uo", chain="TRON", vasp_id="vasp-coindcx", address_tag="Hot Wallet 1"),
        VaspAddress(address="TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9", chain="TRON", vasp_id="vasp-coindcx", address_tag="Deposit Consolidation"),
        VaspAddress(address="0x8894e0a0c962cb723c1ef8580bd9b06b0a72bad5", chain="ETH", vasp_id="vasp-coindcx", address_tag="ETH Hot Wallet"),

        # ── WazirX ──
        VaspAddress(address="TNMcQVGPzqHGoCRhfKFfidUDHBjMbqTdLD", chain="TRON", vasp_id="vasp-wazirx", address_tag="Hot Wallet 1"),
        VaspAddress(address="0x35ffd6e268610e764ff6944d07760d0efe5e40e5", chain="ETH", vasp_id="vasp-wazirx", address_tag="Hot Wallet (Pre-Hack)"),

        # ── Binance ──
        VaspAddress(address="TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf", chain="TRON", vasp_id="vasp-binance", address_tag="Hot Wallet 1"),
        VaspAddress(address="TMuA6YqfCeX8EhbfYEg5y7S4DqzSJireY9", chain="TRON", vasp_id="vasp-binance", address_tag="Hot Wallet 2"),
        VaspAddress(address="TJDENsfBJs4RFETt1X1W8wMDc8M5XnKhCF", chain="TRON", vasp_id="vasp-binance", address_tag="Hot Wallet 3"),
        VaspAddress(address="0x28c6c06298d514db089934071355e5743bf21d60", chain="ETH", vasp_id="vasp-binance", address_tag="Hot Wallet 14"),
        VaspAddress(address="0x21a31ee1afc51d94c2efccaa2043aae4e8a04c52", chain="ETH", vasp_id="vasp-binance", address_tag="Hot Wallet 6"),
        VaspAddress(address="0xdfd5293d8e347dfe59e90efd55b2956a1343963d", chain="ETH", vasp_id="vasp-binance", address_tag="Hot Wallet 8"),
        VaspAddress(address="0xdfd5293d8e347dfe59e90efd55b2956a1343963d", chain="BSC", vasp_id="vasp-binance", address_tag="BSC Hot Wallet"),
        VaspAddress(address="bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h", chain="BTC", vasp_id="vasp-binance", address_tag="BTC Cold"),

        # ── OKX ──
        VaspAddress(address="TFRx9MjdbEwMDk11FkDESR3Mseq3kZ6US7", chain="TRON", vasp_id="vasp-okx", address_tag="Hot Wallet 1"),
        VaspAddress(address="0x6cc5f688a315f3dc28a7781717a9a798a59fda7b", chain="ETH", vasp_id="vasp-okx", address_tag="OKX Hot Wallet"),

        # ── KuCoin ──
        VaspAddress(address="TUpHuDGCHf2BBzVg2bDj8MG8pRjCqr8FMq", chain="TRON", vasp_id="vasp-kucoin", address_tag="Hot Wallet 1"),
        VaspAddress(address="0xd6216fc19db775df9774a6e33526131da7d19a2c", chain="ETH", vasp_id="vasp-kucoin", address_tag="ETH Hot Wallet"),

        # ── Bybit ──
        VaspAddress(address="TYASr5UV6HEcXatwdFQfmLVUqQQQMUxHLS", chain="TRON", vasp_id="vasp-bybit", address_tag="Hot Wallet 1"),
        VaspAddress(address="0xf89d7b9c864f589bbf53a82105107622b35eaa40", chain="ETH", vasp_id="vasp-bybit", address_tag="ETH Hot Wallet"),

        # ── Kraken ──
        VaspAddress(address="0xda9dfa130df4de4673b89022ee50ff26f6ea73cf", chain="ETH", vasp_id="vasp-kraken", address_tag="Kraken Hot Wallet"),

        # ── Coinbase ──
        VaspAddress(address="0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43", chain="ETH", vasp_id="vasp-coinbase", address_tag="Coinbase Commerce"),

        VaspAddress(address="TDEMO_COINDCX_DEPOSIT_01", chain="TRON", vasp_id="vasp-coindcx", address_tag="Demo CoinDCX User Deposit"),
        VaspAddress(address="TDEMO_WAZIRX_DEPOSIT_01", chain="TRON", vasp_id="vasp-wazirx", address_tag="Demo WazirX Deposit"),
        VaspAddress(address="TDEMO_BINANCE_DEPOSIT_01", chain="ETH", vasp_id="vasp-binance", address_tag="Demo Binance ETH Deposit"),
        VaspAddress(address="TDEMO_KUCOIN_DEPOSIT_01", chain="BTC", vasp_id="vasp-kucoin", address_tag="Demo KuCoin BTC Deposit"),
        VaspAddress(address="0xDEMO_GIOTTUS_DEPOSIT_01", chain="ETH", vasp_id="vasp-giottus", address_tag="Demo Giottus ETH Deposit"),

        # Demo CoinDCX hot wallet for sweep
        VaspAddress(address="TDEMO_COINDCX_HOTWALLET", chain="TRON", vasp_id="vasp-coindcx", address_tag="Demo CoinDCX Hot Wallet (Sweep)"),
    ]
    db.add_all(addresses)
    db.flush()


# ─────────────────────────────────────────────────────
# 4. MIXER & BRIDGE DIRECTORY
# ─────────────────────────────────────────────────────
def _seed_mixer_bridge(db: Session):
    entries = [
        # ── Tornado Cash (ETH Pools) ──
        MixerBridgeDirectory(contract_address="0xd90e2f925DA726b50C4Ed8D0Fb90Ad053324F31b", chain="ETH", protocol_name="Tornado Cash 0.1 ETH", entity_type="MIXER", risk_weight=30),
        MixerBridgeDirectory(contract_address="0x910cbd523d972eb0a6f4cae4618ad62622b39dbf", chain="ETH", protocol_name="Tornado Cash 10 ETH", entity_type="MIXER", risk_weight=30),
        MixerBridgeDirectory(contract_address="0xa160cdab225685da1d56aa342ad8841c3b53f291", chain="ETH", protocol_name="Tornado Cash 100 ETH", entity_type="MIXER", risk_weight=30),
        MixerBridgeDirectory(contract_address="0x47CE0C6eD5B0Ce3d3A51fdb1C52DC66a7c3c2936", chain="ETH", protocol_name="Tornado Cash 1 ETH", entity_type="MIXER", risk_weight=30),
        MixerBridgeDirectory(contract_address="0x722122dF12D4e14e13Ac3b6895a86e84145b6967", chain="ETH", protocol_name="Tornado Cash Router", entity_type="MIXER", risk_weight=30),

        # ── Railgun ──
        MixerBridgeDirectory(contract_address="0xfa7093cdd9ee6932b4eb2c9e1cde7ce00b1fa4b9", chain="ETH", protocol_name="Railgun Relay Adapt", entity_type="MIXER", risk_weight=30),

        # ── Bridges ──
        MixerBridgeDirectory(contract_address="0x8731d54e9d02c286767d56ac03e8037c07e01e98", chain="ETH", protocol_name="Stargate Finance Router", entity_type="BRIDGE", source_chain="ETH", destination_chain="MULTI", risk_weight=20),
        MixerBridgeDirectory(contract_address="0xa5409ec958c83c3f309868babaca7c86dcb077c1", chain="ETH", protocol_name="Polygon PoS Bridge", entity_type="BRIDGE", source_chain="ETH", destination_chain="POLYGON", risk_weight=15),
        MixerBridgeDirectory(contract_address="0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf", chain="ETH", protocol_name="Polygon ERC20 Bridge", entity_type="BRIDGE", source_chain="ETH", destination_chain="POLYGON", risk_weight=15),

        # ── Instant Swaps (high risk) ──
        MixerBridgeDirectory(contract_address="0xFixedFloatHotWallet001", chain="ETH", protocol_name="FixedFloat Swap", entity_type="DEX_ROUTER", risk_weight=25),

        # ── Synthetic Demo Bridge ──
        MixerBridgeDirectory(contract_address="TDEMO_BRIDGE_CONTRACT", chain="TRON", protocol_name="Demo Cross-Chain Bridge", entity_type="BRIDGE", source_chain="TRON", destination_chain="ETH", risk_weight=20),
        MixerBridgeDirectory(contract_address="TDEMO_MIXER_CONTRACT", chain="TRON", protocol_name="Demo Privacy Protocol", entity_type="MIXER", risk_weight=30),
    ]
    db.add_all(entries)
    db.flush()


# ─────────────────────────────────────────────────────
# 5. DEMO CASES (pre-wired for live demo)
# ─────────────────────────────────────────────────────
def _seed_demo_cases(db: Session, vasp_map: dict):
    now = datetime.now(timezone.utc)

    # ── Case 1: Main Demo — Task Scam via TRON USDT ──
    case1 = Case(
        id="case-demo-001",
        complaint_source="ncrp", external_complaint_id="NCRP-2026-88421",
        victim_name="Rajesh Kumar", victim_phone="+91-9876543210",
        reported_loss_amount=12500.00, loss_currency="USDT",
        incident_timestamp=now - timedelta(hours=6),
        complaint_text="Victim was lured via Telegram task-fraud app promising 30% daily returns for rating hotels. Transferred 12,500 USDT to suspect TRON wallet.",
        fraud_typology="TASK_BASED_SCAM", status="ATTRIBUTED",
        risk_score=88, risk_tier="CRITICAL", possible_syndicate=True,
        assigned_officer_id="usr-io-001",
    )

    # ── Case 2: Investment Ponzi (shares mule with case 1) ──
    case2 = Case(
        id="case-demo-002",
        complaint_source="1930_helpline", external_complaint_id="NCRP-2026-44120",
        victim_name="Priya Singh", victim_phone="+91-9123456789",
        reported_loss_amount=420000.00, loss_currency="INR",
        incident_timestamp=now - timedelta(days=3, hours=3),
        complaint_text="Victim invested in fake crypto trading platform WhatsApp group, transferred funds to TRON address.",
        fraud_typology="INVESTMENT_PONZI_SCAM", status="ATTRIBUTED",
        risk_score=72, risk_tier="HIGH", possible_syndicate=True,
        assigned_officer_id="usr-io-001",
    )

    # ── Case 3: Digital Arrest Extortion (shares mule) ──
    case3 = Case(
        id="case-demo-003",
        complaint_source="ncrp", external_complaint_id="NCRP-2026-79105",
        victim_name="Amit Patel", victim_phone="+91-9988776655",
        reported_loss_amount=800000.00, loss_currency="INR",
        incident_timestamp=now - timedelta(days=1, hours=4),
        complaint_text="Victim received video call claiming to be CBI officer. Coerced into transferring crypto to 'secure account' for 'verification'.",
        fraud_typology="DIGITAL_ARREST_EXTORTION", status="UNDER_INVESTIGATION",
        risk_score=65, risk_tier="HIGH", possible_syndicate=True,
        assigned_officer_id="usr-analyst-001",
    )

    # ── Case 4: Sextortion ──
    case4 = Case(
        id="case-demo-004",
        complaint_source="sahyog", external_complaint_id="SAHYOG-2026-12001",
        victim_name="Vikram Joshi", victim_phone="+91-8765432109",
        reported_loss_amount=50000.00, loss_currency="INR",
        incident_timestamp=now - timedelta(days=5, hours=2),
        complaint_text="Victim blackmailed with recorded video call. Forced to send BTC to suspect address.",
        fraud_typology="SEXTORTION_BLACKMAIL", status="NEW",
        risk_score=45, risk_tier="MEDIUM",
        assigned_officer_id="usr-io-001",
    )

    # ── Case 5: Phishing Drainer ──
    case5 = Case(
        id="case-demo-005",
        complaint_source="manual_fir", external_complaint_id="FIR-MH-CYB-2026-0091",
        victim_name="Sneha Reddy", victim_phone="+91-7654321098",
        reported_loss_amount=35000.00, loss_currency="USDT",
        incident_timestamp=now - timedelta(days=2, hours=6),
        complaint_text="Victim connected wallet to phishing dApp clone of Uniswap. Smart contract drained USDT approval.",
        fraud_typology="PHISHING_DRAINER", status="UNDER_INVESTIGATION",
        risk_score=55, risk_tier="MEDIUM",
        assigned_officer_id="usr-analyst-001",
    )

    db.add_all([case1, case2, case3, case4, case5])
    db.flush()

    # ── Seed Wallet Nodes for Demo Trace Graph ──
    demo_wallets = [
        # Case 1 trace path: Victim -> Mule1 -> Mixer -> Mule2 -> CoinDCX Deposit -> CoinDCX Hot
        Wallet(address="TDEMO_VICTIM_WALLET_001", chain="TRON", node_type="ORIGIN_VICTIM", first_seen=now - timedelta(hours=6), risk_flags='[]'),
        Wallet(address="TDEMO_MULE_LAYER_001", chain="TRON", node_type="MULE_LAYER", first_seen=now - timedelta(hours=5), risk_flags='["HIGH_VELOCITY"]'),
        Wallet(address="TDEMO_MIXER_CONTRACT", chain="TRON", node_type="MIXER", first_seen=now - timedelta(days=365), risk_flags='["MIXER_HOP"]'),
        Wallet(address="TDEMO_MULE_LAYER_002", chain="TRON", node_type="MULE_LAYER", first_seen=now - timedelta(hours=4), risk_flags='["PEELING_CHAIN"]'),
        Wallet(address="TDEMO_COINDCX_DEPOSIT_01", chain="TRON", node_type="VASP_DEPOSIT", vasp_id="vasp-coindcx",
               attribution_tier="TIER_1_EXACT", attribution_confidence=96.0,
               attribution_evidence="Exact match: known CoinDCX user deposit address", first_seen=now - timedelta(hours=3), risk_flags='[]'),
        Wallet(address="TDEMO_COINDCX_HOTWALLET", chain="TRON", node_type="VASP_HOT_WALLET", vasp_id="vasp-coindcx",
               attribution_tier="TIER_2_SWEEP", attribution_confidence=91.0,
               attribution_evidence="100% funds swept to CoinDCX Hot Wallet within 18 minutes", first_seen=now - timedelta(days=180), risk_flags='[]'),

        # Shared mule wallet (links cases 1, 2, 3 for syndicate detection)
        Wallet(address="TDEMO_SHARED_MULE_SYN", chain="TRON", node_type="MULE_LAYER", first_seen=now - timedelta(days=10), risk_flags='["PEELING_CHAIN","HIGH_VELOCITY"]'),

        # Case 2 unique wallets: Victim2 -> SharedMule -> Mule2 -> WazirX
        Wallet(address="TDEMO_VICTIM_WALLET_002", chain="TRON", node_type="ORIGIN_VICTIM", first_seen=now - timedelta(days=3), risk_flags='[]'),
        Wallet(address="TDEMO_WAZIRX_DEPOSIT_01", chain="TRON", node_type="VASP_DEPOSIT", vasp_id="vasp-wazirx",
               attribution_tier="TIER_1_EXACT", attribution_confidence=93.0,
               attribution_evidence="Exact match: known WazirX user deposit address", first_seen=now - timedelta(days=2), risk_flags='[]'),

        # Case 3 unique wallets: Victim3 -> SharedMule -> Bridge -> BinanceDeposit
        Wallet(address="TDEMO_VICTIM_WALLET_003", chain="TRON", node_type="ORIGIN_VICTIM", first_seen=now - timedelta(days=1), risk_flags='[]'),
        Wallet(address="TDEMO_BRIDGE_CONTRACT", chain="TRON", node_type="BRIDGE", first_seen=now - timedelta(days=200), risk_flags='["BRIDGE_HOP"]'),
        Wallet(address="TDEMO_BINANCE_DEPOSIT_01", chain="ETH", node_type="VASP_DEPOSIT", vasp_id="vasp-binance",
               attribution_tier="TIER_1_EXACT", attribution_confidence=98.0,
               attribution_evidence="Exact match: known Binance user deposit address", first_seen=now - timedelta(hours=18), risk_flags='[]'),

        # Case 4 unique wallets: Victim4 (BTC)
        Wallet(address="TDEMO_VICTIM_WALLET_004", chain="BTC", node_type="ORIGIN_VICTIM", first_seen=now - timedelta(days=5), risk_flags='[]'),
        Wallet(address="TDEMO_BTC_MULE_001", chain="BTC", node_type="MULE_LAYER", first_seen=now - timedelta(days=5), risk_flags='["HIGH_VELOCITY"]'),
        Wallet(address="TDEMO_KUCOIN_DEPOSIT_01", chain="BTC", node_type="VASP_DEPOSIT", vasp_id="vasp-kucoin",
               attribution_tier="TIER_2_SWEEP", attribution_confidence=87.0,
               attribution_evidence="Funds swept to KuCoin hot wallet within 22 minutes", first_seen=now - timedelta(days=4), risk_flags='[]'),

        # Case 5 unique wallets: Victim5 (ETH) -> Drainer -> DEX -> Giottus
        Wallet(address="0xDEMO_VICTIM_WALLET_005", chain="ETH", node_type="ORIGIN_VICTIM", first_seen=now - timedelta(days=2), risk_flags='[]'),
        Wallet(address="0xDEMO_DRAINER_CONTRACT", chain="ETH", node_type="MIXER", first_seen=now - timedelta(days=30), risk_flags='["DRAINER_CONTRACT"]'),
        Wallet(address="0xDEMO_DEX_INTERMEDIARY", chain="ETH", node_type="MULE_LAYER", first_seen=now - timedelta(days=2), risk_flags='["HIGH_VELOCITY"]'),
        Wallet(address="0xDEMO_GIOTTUS_DEPOSIT_01", chain="ETH", node_type="VASP_DEPOSIT", vasp_id="vasp-giottus",
               attribution_tier="TIER_1_EXACT", attribution_confidence=90.0,
               attribution_evidence="Exact match: known Giottus user deposit address", first_seen=now - timedelta(days=1), risk_flags='[]'),
    ]

    # Only add if not already present
    for w in demo_wallets:
        existing = db.query(Wallet).filter_by(address=w.address, chain=w.chain).first()
        if not existing:
            db.add(w)
    db.flush()

    # ── Link wallets to cases ──
    case_wallet_links = [
        # Case 1 full trace path: Victim -> Mule1 -> Mixer -> Mule2 -> CoinDCX
        CaseWallet(case_id="case-demo-001", wallet_address="TDEMO_VICTIM_WALLET_001", wallet_chain="TRON", hop_depth=0, is_origin_reported=True),
        CaseWallet(case_id="case-demo-001", wallet_address="TDEMO_MULE_LAYER_001", wallet_chain="TRON", hop_depth=1),
        CaseWallet(case_id="case-demo-001", wallet_address="TDEMO_MIXER_CONTRACT", wallet_chain="TRON", hop_depth=2),
        CaseWallet(case_id="case-demo-001", wallet_address="TDEMO_MULE_LAYER_002", wallet_chain="TRON", hop_depth=3),
        CaseWallet(case_id="case-demo-001", wallet_address="TDEMO_COINDCX_DEPOSIT_01", wallet_chain="TRON", hop_depth=4, is_terminal_destination=True),
        CaseWallet(case_id="case-demo-001", wallet_address="TDEMO_SHARED_MULE_SYN", wallet_chain="TRON", hop_depth=1),

        # Case 2 full trace: Victim2 -> SharedMule -> Mule2 -> WazirX
        CaseWallet(case_id="case-demo-002", wallet_address="TDEMO_VICTIM_WALLET_002", wallet_chain="TRON", hop_depth=0, is_origin_reported=True),
        CaseWallet(case_id="case-demo-002", wallet_address="TDEMO_SHARED_MULE_SYN", wallet_chain="TRON", hop_depth=1),
        CaseWallet(case_id="case-demo-002", wallet_address="TDEMO_MULE_LAYER_002", wallet_chain="TRON", hop_depth=2),
        CaseWallet(case_id="case-demo-002", wallet_address="TDEMO_WAZIRX_DEPOSIT_01", wallet_chain="TRON", hop_depth=3, is_terminal_destination=True),

        # Case 3 full trace: Victim3 -> SharedMule -> Bridge -> BinanceDeposit
        CaseWallet(case_id="case-demo-003", wallet_address="TDEMO_VICTIM_WALLET_003", wallet_chain="TRON", hop_depth=0, is_origin_reported=True),
        CaseWallet(case_id="case-demo-003", wallet_address="TDEMO_SHARED_MULE_SYN", wallet_chain="TRON", hop_depth=1),
        CaseWallet(case_id="case-demo-003", wallet_address="TDEMO_BRIDGE_CONTRACT", wallet_chain="TRON", hop_depth=2),
        CaseWallet(case_id="case-demo-003", wallet_address="TDEMO_BINANCE_DEPOSIT_01", wallet_chain="ETH", hop_depth=3, is_terminal_destination=True),

        # Case 4: BTC Sextortion — Victim4 -> BTC Mule -> KuCoin
        CaseWallet(case_id="case-demo-004", wallet_address="TDEMO_VICTIM_WALLET_004", wallet_chain="BTC", hop_depth=0, is_origin_reported=True),
        CaseWallet(case_id="case-demo-004", wallet_address="TDEMO_BTC_MULE_001", wallet_chain="BTC", hop_depth=1),
        CaseWallet(case_id="case-demo-004", wallet_address="TDEMO_KUCOIN_DEPOSIT_01", wallet_chain="BTC", hop_depth=2, is_terminal_destination=True),

        # Case 5: Phishing Drainer — Victim5 -> Drainer -> DEX -> Giottus
        CaseWallet(case_id="case-demo-005", wallet_address="0xDEMO_VICTIM_WALLET_005", wallet_chain="ETH", hop_depth=0, is_origin_reported=True),
        CaseWallet(case_id="case-demo-005", wallet_address="0xDEMO_DRAINER_CONTRACT", wallet_chain="ETH", hop_depth=1),
        CaseWallet(case_id="case-demo-005", wallet_address="0xDEMO_DEX_INTERMEDIARY", wallet_chain="ETH", hop_depth=2),
        CaseWallet(case_id="case-demo-005", wallet_address="0xDEMO_GIOTTUS_DEPOSIT_01", wallet_chain="ETH", hop_depth=3, is_terminal_destination=True),
    ]
    db.add_all(case_wallet_links)
    db.flush()

    # ── Seed transactions for demo graph ──
    demo_txs = [
        # ── Case 1 transactions ──
        Transaction(
            tx_hash="DEMO_TX_001_VICTIM_TO_MULE1", chain="TRON",
            from_address="TDEMO_VICTIM_WALLET_001", to_address="TDEMO_MULE_LAYER_001",
            token_symbol="USDT", amount=12500.0, amount_usd=12500.0,
            block_number=65000001, timestamp=now - timedelta(hours=5, minutes=45),
        ),
        Transaction(
            tx_hash="DEMO_TX_002_MULE1_TO_MIXER", chain="TRON",
            from_address="TDEMO_MULE_LAYER_001", to_address="TDEMO_MIXER_CONTRACT",
            token_symbol="USDT", amount=11800.0, amount_usd=11800.0,
            block_number=65000050, timestamp=now - timedelta(hours=5, minutes=30),
            is_peeling_tx=True,
        ),
        Transaction(
            tx_hash="DEMO_TX_002B_MULE1_PEEL", chain="TRON",
            from_address="TDEMO_MULE_LAYER_001", to_address="TDEMO_SHARED_MULE_SYN",
            token_symbol="USDT", amount=700.0, amount_usd=700.0,
            block_number=65000051, timestamp=now - timedelta(hours=5, minutes=29),
            is_peeling_tx=True,
        ),
        Transaction(
            tx_hash="DEMO_TX_003_MIXER_TO_MULE2", chain="TRON",
            from_address="TDEMO_MIXER_CONTRACT", to_address="TDEMO_MULE_LAYER_002",
            token_symbol="USDT", amount=11800.0, amount_usd=11800.0,
            block_number=65000200, timestamp=now - timedelta(hours=4, minutes=15),
        ),
        Transaction(
            tx_hash="DEMO_TX_004_MULE2_TO_COINDCX", chain="TRON",
            from_address="TDEMO_MULE_LAYER_002", to_address="TDEMO_COINDCX_DEPOSIT_01",
            token_symbol="USDT", amount=11500.0, amount_usd=11500.0,
            block_number=65000400, timestamp=now - timedelta(hours=3, minutes=50),
        ),
        Transaction(
            tx_hash="DEMO_TX_005_COINDCX_SWEEP", chain="TRON",
            from_address="TDEMO_COINDCX_DEPOSIT_01", to_address="TDEMO_COINDCX_HOTWALLET",
            token_symbol="USDT", amount=11500.0, amount_usd=11500.0,
            block_number=65000420, timestamp=now - timedelta(hours=3, minutes=32),
        ),

        # ── Case 2 transactions: Victim2 -> SharedMule -> Mule2 -> WazirX ──
        Transaction(
            tx_hash="DEMO_TX_C2_01_VICTIM_TO_SHAREDMULE", chain="TRON",
            from_address="TDEMO_VICTIM_WALLET_002", to_address="TDEMO_SHARED_MULE_SYN",
            token_symbol="USDT", amount=5200.0, amount_usd=5200.0,
            block_number=64800100, timestamp=now - timedelta(days=3, hours=2),
        ),
        Transaction(
            tx_hash="DEMO_TX_C2_02_SHAREDMULE_TO_MULE2", chain="TRON",
            from_address="TDEMO_SHARED_MULE_SYN", to_address="TDEMO_MULE_LAYER_002",
            token_symbol="USDT", amount=5100.0, amount_usd=5100.0,
            block_number=64800200, timestamp=now - timedelta(days=3, hours=1),
        ),
        Transaction(
            tx_hash="DEMO_TX_C2_03_MULE2_TO_WAZIRX", chain="TRON",
            from_address="TDEMO_MULE_LAYER_002", to_address="TDEMO_WAZIRX_DEPOSIT_01",
            token_symbol="USDT", amount=4950.0, amount_usd=4950.0,
            block_number=64800300, timestamp=now - timedelta(days=2, hours=22),
        ),

        # ── Case 3 transactions: Victim3 -> SharedMule -> Bridge -> Binance ──
        Transaction(
            tx_hash="DEMO_TX_C3_01_VICTIM_TO_SHAREDMULE", chain="TRON",
            from_address="TDEMO_VICTIM_WALLET_003", to_address="TDEMO_SHARED_MULE_SYN",
            token_symbol="USDT", amount=9800.0, amount_usd=9800.0,
            block_number=65100001, timestamp=now - timedelta(days=1, hours=3),
        ),
        Transaction(
            tx_hash="DEMO_TX_C3_02_SHAREDMULE_TO_BRIDGE", chain="TRON",
            from_address="TDEMO_SHARED_MULE_SYN", to_address="TDEMO_BRIDGE_CONTRACT",
            token_symbol="USDT", amount=9700.0, amount_usd=9700.0,
            block_number=65100100, timestamp=now - timedelta(days=1, hours=2),
            is_bridge_tx=True,
        ),
        Transaction(
            tx_hash="DEMO_TX_C3_03_BRIDGE_TO_BINANCE", chain="ETH",
            from_address="TDEMO_BRIDGE_CONTRACT", to_address="TDEMO_BINANCE_DEPOSIT_01",
            token_symbol="USDT", amount=9600.0, amount_usd=9600.0,
            block_number=18500001, timestamp=now - timedelta(days=1, hours=1),
        ),

        # ── Case 4 transactions: BTC Victim -> Mule -> KuCoin ──
        Transaction(
            tx_hash="DEMO_TX_C4_01_VICTIM_TO_MULE", chain="BTC",
            from_address="TDEMO_VICTIM_WALLET_004", to_address="TDEMO_BTC_MULE_001",
            token_symbol="BTC", amount=0.065, amount_usd=4200.0,
            block_number=850001, timestamp=now - timedelta(days=5, hours=1),
        ),
        Transaction(
            tx_hash="DEMO_TX_C4_02_MULE_TO_KUCOIN", chain="BTC",
            from_address="TDEMO_BTC_MULE_001", to_address="TDEMO_KUCOIN_DEPOSIT_01",
            token_symbol="BTC", amount=0.064, amount_usd=4135.0,
            block_number=850010, timestamp=now - timedelta(days=4, hours=23),
        ),

        # ── Case 5 transactions: ETH Victim -> Drainer -> DEX -> Giottus ──
        Transaction(
            tx_hash="DEMO_TX_C5_01_VICTIM_TO_DRAINER", chain="ETH",
            from_address="0xDEMO_VICTIM_WALLET_005", to_address="0xDEMO_DRAINER_CONTRACT",
            token_symbol="USDT", amount=35000.0, amount_usd=35000.0,
            block_number=18600001, timestamp=now - timedelta(days=2, hours=5),
        ),
        Transaction(
            tx_hash="DEMO_TX_C5_02_DRAINER_TO_DEX", chain="ETH",
            from_address="0xDEMO_DRAINER_CONTRACT", to_address="0xDEMO_DEX_INTERMEDIARY",
            token_symbol="USDT", amount=34500.0, amount_usd=34500.0,
            block_number=18600050, timestamp=now - timedelta(days=2, hours=4),
        ),
        Transaction(
            tx_hash="DEMO_TX_C5_03_DEX_TO_GIOTTUS", chain="ETH",
            from_address="0xDEMO_DEX_INTERMEDIARY", to_address="0xDEMO_GIOTTUS_DEPOSIT_01",
            token_symbol="USDT", amount=34000.0, amount_usd=34000.0,
            block_number=18600100, timestamp=now - timedelta(days=2, hours=3),
        ),
    ]
    db.add_all(demo_txs)
    db.flush()

    # ── Seed alerts for demo ──
    demo_alerts = [
        Alert(
            id="alert-demo-001", case_id="case-demo-001", user_id="usr-io-001",
            alert_type="VASP_HIGH_CONFIDENCE_HIT", severity="CRITICAL",
            title="VASP Identified: CoinDCX (FIU-IND)",
            message="Wallet TDEMO_COINDCX_DEPOSIT_01 matched CoinDCX deposit address with 96% confidence. Immediate Sec 94 BNSS freeze recommended.",
        ),
        Alert(
            id="alert-demo-002", case_id="case-demo-001", user_id="usr-io-001",
            alert_type="SYNDICATE_OVERLAP", severity="CRITICAL",
            title="SYNDICATE DETECTED: 3 Linked FIRs",
            message="Case NCRP-2026-88421 shares mule wallet TDEMO_SHARED_MULE_SYN with 2 other complaints (NCRP-2026-44120, NCRP-2026-79105). Possible organized cyber fraud ring.",
        ),
        Alert(
            id="alert-demo-003", case_id="case-demo-001", user_id="usr-io-001",
            alert_type="MIXER_DETECTED", severity="HIGH",
            title="Privacy Protocol Detected in Fund Path",
            message="Funds routed through Demo Privacy Protocol mixer at hop 2. Trace confidence reduced downstream.",
        ),
    ]
    db.add_all(demo_alerts)
    db.flush()

