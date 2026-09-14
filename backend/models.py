"""
SQLAlchemy ORM models — maps 1:1 to PRD §6 PostgreSQL schema.
Uses SQLite-compatible types (no UUID extension, no ARRAY — uses JSON string instead).
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, Numeric, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database import Base


def generate_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════
# 1. USERS & RBAC
# ═══════════════════════════════════════════════════════════
class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    badge_number = Column(String(50))
    police_station = Column(String(150))
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False)  # 'investigator', 'analyst', 'admin'
    status = Column(String(24), nullable=False, default="active")
    primary_agency_id = Column(String(36), ForeignKey("agencies.id"))
    created_at = Column(DateTime, default=utcnow)

    cases = relationship("Case", back_populates="assigned_officer", foreign_keys="Case.assigned_officer_id")
    alerts = relationship("Alert", back_populates="user")


# ═══════════════════════════════════════════════════════════
# 2. COMPLAINTS & CASES
# ═══════════════════════════════════════════════════════════
class Case(Base):
    __tablename__ = "cases"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    complaint_source = Column(String(30), default="ncrp")
    external_complaint_id = Column(String(100), nullable=False)
    victim_name = Column(String(150))
    victim_phone = Column(String(30))
    reported_loss_amount = Column(Numeric(18, 4), nullable=False)
    loss_currency = Column(String(10), default="USDT")
    incident_timestamp = Column(DateTime)
    complaint_text = Column(Text)
    fraud_typology = Column(String(50), nullable=False)
    status = Column(String(30), default="NEW")
    risk_score = Column(Integer, default=0)
    risk_tier = Column(String(20), default="MEDIUM")
    possible_syndicate = Column(Boolean, default=False)
    assigned_officer_id = Column(String(36), ForeignKey("users.id"))
    agency_id = Column(String(36), ForeignKey("agencies.id"), nullable=False, default="agency-local")
    revision = Column(Integer, nullable=False, default=1)
    primary_report_event_id = Column(
        String(36), ForeignKey("report_events.id", use_alter=True, name="fk_cases_primary_report_event")
    )
    created_by = Column(String(36), ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("agency_id", "complaint_source", "external_complaint_id", name="uq_case_agency_source_external"),
    )

    assigned_officer = relationship("User", back_populates="cases", foreign_keys=[assigned_officer_id])
    case_wallets = relationship("CaseWallet", back_populates="case", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="case", cascade="all, delete-orphan")
    legal_notices = relationship("LegalNotice", back_populates="case", cascade="all, delete-orphan")
    forensic_reports = relationship("ForensicReport", back_populates="case", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════════
# 3. WALLETS
# ═══════════════════════════════════════════════════════════
class Wallet(Base):
    __tablename__ = "wallets"

    address = Column(String(120), primary_key=True)
    chain = Column(String(20), primary_key=True)
    node_type = Column(String(30), default="NORMAL_WALLET")
    vasp_id = Column(String(36), ForeignKey("vasp_directory.id"))
    attribution_tier = Column(String(30))
    attribution_confidence = Column(Float, default=0.0)
    attribution_evidence = Column(Text)
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    total_received_usd = Column(Float, default=0.0)
    risk_flags = Column(Text, default="[]")  # JSON string array (SQLite compat)

    vasp = relationship("VaspDirectory", backref="wallets")


# ═══════════════════════════════════════════════════════════
# 4. CASE_WALLETS (Join Table)
# ═══════════════════════════════════════════════════════════
class CaseWallet(Base):
    __tablename__ = "case_wallets"

    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    wallet_address = Column(String(120), primary_key=True)
    wallet_chain = Column(String(20), primary_key=True)
    hop_depth = Column(Integer, default=0)
    is_origin_reported = Column(Boolean, default=False)
    is_terminal_destination = Column(Boolean, default=False)

    case = relationship("Case", back_populates="case_wallets")


# ═══════════════════════════════════════════════════════════
# 5. TRANSACTIONS
# ═══════════════════════════════════════════════════════════
class Transaction(Base):
    __tablename__ = "transactions"

    tx_hash = Column(String(150), primary_key=True)
    chain = Column(String(20), nullable=False)
    from_address = Column(String(120), nullable=False)
    to_address = Column(String(120), nullable=False)
    token_symbol = Column(String(20), default="NATIVE")
    token_contract = Column(String(120))
    amount = Column(Float, nullable=False)
    amount_usd = Column(Float)
    block_number = Column(Integer)
    timestamp = Column(DateTime, nullable=False)
    is_peeling_tx = Column(Boolean, default=False)
    is_bridge_tx = Column(Boolean, default=False)
    fetched_at = Column(DateTime, default=utcnow)


# ═══════════════════════════════════════════════════════════
# 6. VASP DIRECTORY
# ═══════════════════════════════════════════════════════════
class VaspDirectory(Base):
    __tablename__ = "vasp_directory"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    vasp_name = Column(String(150), nullable=False)
    legal_entity_name = Column(String(200))
    is_fiu_ind_registered = Column(Boolean, default=False)
    fiu_registration_number = Column(String(100))
    nodal_officer_name = Column(String(150))
    nodal_officer_email = Column(String(255), nullable=False)
    law_enforcement_portal_url = Column(String(255))
    jurisdiction = Column(String(100), default="India")
    sla_freeze_hours = Column(Integer, default=24)
    notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)

    addresses = relationship("VaspAddress", back_populates="vasp", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════════
# 7. VASP KNOWN ADDRESSES
# ═══════════════════════════════════════════════════════════
class VaspAddress(Base):
    __tablename__ = "vasp_addresses"

    address = Column(String(120), primary_key=True)
    chain = Column(String(20), primary_key=True)
    vasp_id = Column(String(36), ForeignKey("vasp_directory.id", ondelete="CASCADE"), nullable=False)
    address_tag = Column(String(100), nullable=False)
    source_provenance = Column(String(150), default="Etherscan Tag / Public Registry")
    is_verified = Column(Boolean, default=True)
    added_at = Column(DateTime, default=utcnow)

    vasp = relationship("VaspDirectory", back_populates="addresses")


# ═══════════════════════════════════════════════════════════
# 8. MIXER & BRIDGE DIRECTORY
# ═══════════════════════════════════════════════════════════
class MixerBridgeDirectory(Base):
    __tablename__ = "mixer_bridge_directory"

    contract_address = Column(String(120), primary_key=True)
    chain = Column(String(20), primary_key=True)
    protocol_name = Column(String(100), nullable=False)
    entity_type = Column(String(30), nullable=False)  # 'MIXER', 'BRIDGE', 'DEX_ROUTER'
    source_chain = Column(String(20))
    destination_chain = Column(String(20))
    risk_weight = Column(Integer, default=30)


# ═══════════════════════════════════════════════════════════
# 9. LEGAL NOTICES (Sec 91/94 BNSS)
# ═══════════════════════════════════════════════════════════
class LegalNotice(Base):
    __tablename__ = "legal_notices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"))
    vasp_id = Column(String(36), ForeignKey("vasp_directory.id"))
    notice_type = Column(String(50), default="SEC_94_BNSS_FREEZE_REQUISITION")
    reference_number = Column(String(100), unique=True, nullable=False)
    target_wallet = Column(String(120), nullable=False)
    target_tx_hash = Column(String(150))
    amount_to_freeze = Column(Float)
    currency = Column(String(10))
    status = Column(String(30), default="DRAFTED")
    pdf_storage_path = Column(Text)
    dispatched_to_email = Column(String(255))
    dispatched_at = Column(DateTime)
    generated_by = Column(String(36), ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow)

    case = relationship("Case", back_populates="legal_notices")
    vasp = relationship("VaspDirectory")


# ═══════════════════════════════════════════════════════════
# 10. FORENSIC REPORTS (Sec 63 BSA / 65B IEA)
# ═══════════════════════════════════════════════════════════
class ForensicReport(Base):
    __tablename__ = "forensic_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"))
    report_reference_number = Column(String(100), unique=True, nullable=False)
    sha256_content_hash = Column(String(64), nullable=False)
    generated_by = Column(String(36), ForeignKey("users.id"))
    generated_at = Column(DateTime, default=utcnow)
    pdf_storage_path = Column(Text, nullable=False)
    is_court_certified = Column(Boolean, default=True)

    case = relationship("Case", back_populates="forensic_reports")


# ═══════════════════════════════════════════════════════════
# 11. ALERTS
# ═══════════════════════════════════════════════════════════
class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"))
    user_id = Column(String(36), ForeignKey("users.id"))
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), default="HIGH")
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    case = relationship("Case", back_populates="alerts")
    user = relationship("User", back_populates="alerts")


# ═══════════════════════════════════════════════════════════
# 12. AUDIT TRAIL
# ═══════════════════════════════════════════════════════════
class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"))
    case_id = Column(String(36))
    action = Column(String(100), nullable=False)
    target_entity = Column(String(100))
    ip_address = Column(String(50))
    timestamp = Column(DateTime, default=utcnow)
