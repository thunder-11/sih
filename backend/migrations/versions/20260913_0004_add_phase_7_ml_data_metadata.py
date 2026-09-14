"""add phase 7 fresh ML data and feature metadata

Revision ID: 20260913_0004
Revises: 20260913_0003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.persistence import types as persistence_types


revision: str = "20260913_0004"
down_revision: Union[str, None] = "20260913_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ml_dataset_snapshots") as batch_op:
        batch_op.add_column(sa.Column("data_mode", sa.String(24), nullable=False, server_default="research"))
        batch_op.add_column(sa.Column("task_types", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("manifest", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("ml_dataset_sources") as batch_op:
        batch_op.add_column(sa.Column("source_kind", sa.String(32), nullable=False, server_default="authorized"))
        batch_op.add_column(sa.Column("owner", sa.String(150), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("permitted_purpose", sa.String(200), nullable=False, server_default="research"))
        batch_op.add_column(sa.Column("chains", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("coverage_start", persistence_types.UtcTimestamp(), nullable=True))
        batch_op.add_column(sa.Column("coverage_end", persistence_types.UtcTimestamp(), nullable=True))
        batch_op.add_column(sa.Column("collection_method", sa.String(120), nullable=False, server_default="registered_import"))
        batch_op.add_column(sa.Column("identity_keys", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("label_meaning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("availability_semantics", sa.Text(), nullable=False, server_default="recorded_at"))
        batch_op.add_column(sa.Column("quality_limits", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("deletion_constraints", sa.Text(), nullable=True))
    with op.batch_alter_table("ml_label_revisions") as batch_op:
        batch_op.drop_constraint("uq_label_revision", type_="unique")
        batch_op.add_column(sa.Column("task", sa.String(40), nullable=False, server_default="wallet_risk"))
        batch_op.add_column(sa.Column("target_class", sa.String(80), nullable=False, server_default="fraud_linked_activity"))
        batch_op.add_column(sa.Column("group_key", sa.String(120), nullable=False, server_default="ungrouped"))
        batch_op.add_column(sa.Column("matures_at", persistence_types.UtcTimestamp(), nullable=True))
        batch_op.add_column(sa.Column("source_name", sa.String(150), nullable=False, server_default="authorized_review"))
        batch_op.add_column(sa.Column("license_name", sa.String(150), nullable=False, server_default="restricted"))
        batch_op.add_column(sa.Column("source_confidence", persistence_types.ExactDecimal(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("rationale", sa.Text(), nullable=False, server_default="reviewed evidence"))
        batch_op.add_column(sa.Column("created_by", sa.String(36), nullable=True))
        batch_op.create_foreign_key("fk_ml_label_creator", "users", ["created_by"], ["id"])
        batch_op.create_unique_constraint("uq_label_revision", ["subject_type", "subject_id", "task", "target_class", "revision"])
    with op.batch_alter_table("ml_label_adjudications") as batch_op:
        batch_op.create_unique_constraint("uq_label_reviewer", ["label_revision_id", "reviewer_id"])
    with op.batch_alter_table("ml_feature_definitions") as batch_op:
        batch_op.add_column(sa.Column("family", sa.String(60), nullable=False, server_default="data_quality"))
        batch_op.add_column(sa.Column("value_type", sa.String(32), nullable=False, server_default="decimal"))
        batch_op.add_column(sa.Column("source", sa.String(150), nullable=False, server_default="normalized_evidence"))
        batch_op.add_column(sa.Column("aggregation", sa.String(100), nullable=False, server_default="defined"))
        batch_op.add_column(sa.Column("missing_behavior", sa.String(100), nullable=False, server_default="explicit_missing_indicator"))
        batch_op.add_column(sa.Column("owner", sa.String(100), nullable=False, server_default="new_ml"))
    with op.batch_alter_table("ml_feature_snapshots") as batch_op:
        batch_op.add_column(sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("quality", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("ml_split_manifests") as batch_op:
        batch_op.add_column(sa.Column("membership", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("class_counts", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("ml_split_manifests") as batch_op:
        batch_op.drop_column("class_counts")
        batch_op.drop_column("membership")
    with op.batch_alter_table("ml_feature_snapshots") as batch_op:
        batch_op.drop_column("quality")
        batch_op.drop_column("evidence_ids")
    with op.batch_alter_table("ml_feature_definitions") as batch_op:
        for name in ("owner", "missing_behavior", "aggregation", "source", "value_type", "family"):
            batch_op.drop_column(name)
    with op.batch_alter_table("ml_label_adjudications") as batch_op:
        batch_op.drop_constraint("uq_label_reviewer", type_="unique")
    with op.batch_alter_table("ml_label_revisions") as batch_op:
        batch_op.drop_constraint("uq_label_revision", type_="unique")
        batch_op.drop_constraint("fk_ml_label_creator", type_="foreignkey")
        for name in ("created_by", "rationale", "source_confidence", "license_name", "source_name", "matures_at", "group_key", "target_class", "task"):
            batch_op.drop_column(name)
        batch_op.create_unique_constraint("uq_label_revision", ["subject_type", "subject_id", "revision"])
    with op.batch_alter_table("ml_dataset_sources") as batch_op:
        for name in ("deletion_constraints", "quality_limits", "availability_semantics", "label_meaning", "identity_keys", "collection_method", "coverage_end", "coverage_start", "chains", "permitted_purpose", "owner", "source_kind"):
            batch_op.drop_column(name)
    with op.batch_alter_table("ml_dataset_snapshots") as batch_op:
        batch_op.drop_column("manifest")
        batch_op.drop_column("task_types")
        batch_op.drop_column("data_mode")
