"""add phase 9 append-only model serving lifecycle

Revision ID: 20260913_0005
Revises: 20260913_0004
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.persistence import types as persistence_types


revision: str = "20260913_0005"
down_revision: Union[str, None] = "20260913_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_model_lifecycle_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("ml_model_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prior_package_id", sa.String(36), sa.ForeignKey("ml_model_packages.id")),
        sa.Column("transition", sa.String(24), nullable=False),
        sa.Column("traffic_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", persistence_types.UtcTimestamp(), nullable=False),
        sa.CheckConstraint("traffic_percent >= 0 AND traffic_percent <= 100", name="ck_ml_lifecycle_traffic"),
    )
    op.create_index("ix_ml_lifecycle_package", "ml_model_lifecycle_events", ["package_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_lifecycle_package", table_name="ml_model_lifecycle_events")
    op.drop_table("ml_model_lifecycle_events")
