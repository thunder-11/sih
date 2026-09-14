"""add phase 3 identity and intake workflow

Revision ID: 20260913_0002
Revises: 20260912_0001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.persistence import types as persistence_types


revision: str = "20260913_0002"
down_revision: Union[str, None] = "20260912_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO agencies (id, name, jurisdiction, scope, status, created_at) "
        "SELECT 'agency-local', 'Local Cyber Crime Agency', 'India', '{}', 'active', CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM agencies)"
    )

    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "status" not in user_columns or "primary_agency_id" not in user_columns:
        with op.batch_alter_table("users") as batch_op:
            if "status" not in user_columns:
                batch_op.add_column(sa.Column("status", sa.String(24), nullable=False, server_default="active"))
            if "primary_agency_id" not in user_columns:
                batch_op.add_column(sa.Column("primary_agency_id", sa.String(36), nullable=True))
                batch_op.create_foreign_key("fk_users_primary_agency", "agencies", ["primary_agency_id"], ["id"])
    op.execute("UPDATE users SET primary_agency_id = 'agency-local' WHERE primary_agency_id IS NULL")

    case_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("cases")}
    if not {"agency_id", "revision", "primary_report_event_id", "created_by"}.issubset(case_columns):
        with op.batch_alter_table("cases") as batch_op:
            if "agency_id" not in case_columns:
                batch_op.add_column(sa.Column("agency_id", sa.String(36), nullable=True))
                batch_op.create_foreign_key("fk_cases_agency", "agencies", ["agency_id"], ["id"])
            if "revision" not in case_columns:
                batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
            if "primary_report_event_id" not in case_columns:
                batch_op.add_column(sa.Column("primary_report_event_id", sa.String(36), nullable=True))
                batch_op.create_foreign_key("fk_cases_primary_report_event", "report_events", ["primary_report_event_id"], ["id"])
            if "created_by" not in case_columns:
                batch_op.add_column(sa.Column("created_by", sa.String(36), nullable=True))
                batch_op.create_foreign_key("fk_cases_creator", "users", ["created_by"], ["id"])
    op.execute("UPDATE cases SET agency_id = 'agency-local' WHERE agency_id IS NULL")
    existing_case_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("cases")}
    if "ix_cases_agency_id" not in existing_case_indexes:
        op.create_index("ix_cases_agency_id", "cases", ["agency_id"], unique=False)
    case_uniques = sa.inspect(op.get_bind()).get_unique_constraints("cases")
    legacy_unique = next((item for item in case_uniques if item.get("column_names") == ["external_complaint_id"]), None)
    composite_unique = next((item for item in case_uniques if item.get("column_names") == ["agency_id", "complaint_source", "external_complaint_id"]), None)
    if legacy_unique or not composite_unique:
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("cases", naming_convention=naming) as batch_op:
            if legacy_unique:
                batch_op.drop_constraint(legacy_unique.get("name") or "uq_cases_external_complaint_id", type_="unique")
            if not composite_unique:
                batch_op.create_unique_constraint("uq_case_agency_source_external",
                                                  ["agency_id", "complaint_source", "external_complaint_id"])

    with op.batch_alter_table("report_events") as batch_op:
        batch_op.add_column(sa.Column("complaint_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("original_timestamp", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("iana_timezone", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("channel", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("receipt_reference", sa.String(180), nullable=True))
        batch_op.create_foreign_key("fk_report_event_complaint", "complaint_records", ["complaint_id"], ["id"], ondelete="CASCADE")
    op.execute(
        "UPDATE report_events SET complaint_id = (SELECT complaint_id FROM case_complaints "
        "WHERE case_complaints.case_id = report_events.case_id LIMIT 1) WHERE complaint_id IS NULL"
    )
    op.execute("UPDATE report_events SET original_timestamp = CAST(report_timestamp AS VARCHAR) WHERE original_timestamp IS NULL")
    op.execute("UPDATE report_events SET channel = source_system WHERE channel IS NULL")
    with op.batch_alter_table("report_events") as batch_op:
        batch_op.create_index("ix_report_events_complaint_id", ["complaint_id"], unique=False)

    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.add_column(sa.Column("revoked_reason", sa.String(100), nullable=True))

    op.create_table(
        "case_access_grants",
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("permission", sa.String(24), nullable=False),
        sa.Column("granted_by", sa.String(36), nullable=False),
        sa.Column("granted_at", persistence_types.UtcTimestamp(), nullable=False),
        sa.Column("revoked_at", persistence_types.UtcTimestamp(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("case_id", "user_id"),
    )
    op.create_table(
        "case_attachments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_reference", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("created_at", persistence_types.UtcTimestamp(), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_case_attachment_size"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "sha256", name="uq_case_attachment_digest"),
    )
    op.create_index("ix_case_attachments_case_id", "case_attachments", ["case_id"])
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", persistence_types.UtcTimestamp(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"),
    )
    op.create_index("ix_idempotency_records_actor_id", "idempotency_records", ["actor_id"])

    op.execute(
        "INSERT INTO user_agency_scopes (user_id, agency_id, role, permissions, status, valid_from) "
        "SELECT users.id, 'agency-local', users.role, '[]', 'active', CURRENT_TIMESTAMP FROM users "
        "WHERE NOT EXISTS (SELECT 1 FROM user_agency_scopes s WHERE s.user_id = users.id AND s.agency_id = 'agency-local')"
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_actor_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_case_attachments_case_id", table_name="case_attachments")
    op.drop_table("case_attachments")
    op.drop_table("case_access_grants")
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.drop_column("revoked_reason")
    with op.batch_alter_table("report_events") as batch_op:
        batch_op.drop_index("ix_report_events_complaint_id")
        batch_op.drop_constraint("fk_report_event_complaint", type_="foreignkey")
        batch_op.drop_column("receipt_reference")
        batch_op.drop_column("channel")
        batch_op.drop_column("iana_timezone")
        batch_op.drop_column("original_timestamp")
        batch_op.drop_column("complaint_id")
    with op.batch_alter_table("cases") as batch_op:
        batch_op.drop_index("ix_cases_agency_id")
        batch_op.drop_constraint("uq_case_agency_source_external", type_="unique")
        batch_op.create_unique_constraint("uq_cases_external_complaint_id", ["external_complaint_id"])
        batch_op.drop_constraint("fk_cases_primary_report_event", type_="foreignkey")
        batch_op.drop_constraint("fk_cases_creator", type_="foreignkey")
        batch_op.drop_constraint("fk_cases_agency", type_="foreignkey")
        batch_op.drop_column("created_by")
        batch_op.drop_column("primary_report_event_id")
        batch_op.drop_column("revision")
        batch_op.drop_column("agency_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_primary_agency", type_="foreignkey")
        batch_op.drop_column("primary_agency_id")
        batch_op.drop_column("status")
