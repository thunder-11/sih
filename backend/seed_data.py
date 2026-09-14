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

        # ── Protocol Contracts ──
        MixerBridgeDirectory(contract_address="TTronBridgeContract7xLqR2mKvJ8sDwT5y", chain="TRON", protocol_name="Cross-Chain Bridge Router", entity_type="BRIDGE", source_chain="TRON", destination_chain="ETH", risk_weight=20),
        MixerBridgeDirectory(contract_address="TTronMixerPoolContract9jP3bH7sD4tE1c", chain="TRON", protocol_name="Privacy Protocol Pool", entity_type="MIXER", risk_weight=30),
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
def _seed_demo_cases(db: Session, vasp_map: dict):
    from seed_predefined_cases import seed_database
    seed_database()

