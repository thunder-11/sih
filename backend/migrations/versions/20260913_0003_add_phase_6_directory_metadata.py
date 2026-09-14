"""add phase 6 directory review and provenance metadata

Revision ID: 20260913_0003
Revises: 20260913_0002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.persistence import types as persistence_types


revision: str = "20260913_0003"
down_revision: Union[str, None] = "20260913_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch_op:
        batch_op.add_column(sa.Column("legal_name", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("service_type", sa.String(60), nullable=True))
        batch_op.add_column(sa.Column("fiu_status", sa.String(32), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("fiu_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fiu_as_of", persistence_types.UtcTimestamp(), nullable=True))
        batch_op.add_column(sa.Column("contact_email", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("contact_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("contact_as_of", persistence_types.UtcTimestamp(), nullable=True))
    with op.batch_alter_table("entity_address_assertions") as batch_op:
        batch_op.add_column(sa.Column("review_status", sa.String(24), nullable=False, server_default="unreviewed"))
        batch_op.add_column(sa.Column("reviewed_by", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", persistence_types.UtcTimestamp(), nullable=True))
        batch_op.create_foreign_key("fk_entity_assertion_reviewer", "users", ["reviewed_by"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("entity_address_assertions") as batch_op:
        batch_op.drop_constraint("fk_entity_assertion_reviewer", type_="foreignkey")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("review_status")
    with op.batch_alter_table("entities") as batch_op:
        batch_op.drop_column("contact_as_of")
        batch_op.drop_column("contact_source")
        batch_op.drop_column("contact_email")
        batch_op.drop_column("fiu_as_of")
        batch_op.drop_column("fiu_source")
        batch_op.drop_column("fiu_status")
        batch_op.drop_column("service_type")
        batch_op.drop_column("legal_name")
