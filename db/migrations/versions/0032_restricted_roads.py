"""Depot-scoped confirmed restricted road master.

Revision ID: 0032_restricted_roads
Revises: 0031_active_depot_import
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_restricted_roads"
down_revision = "0031_active_depot_import"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "master_restricted_road",
        sa.Column("restricted_road_id", sa.String(64), primary_key=True),
        sa.Column("depot_id", sa.String(64), sa.ForeignKey("master_depot.depot_id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=False),
        sa.Column("buffer_meters", sa.Float(), nullable=False, server_default="12"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_master_restricted_road_depot_id", "master_restricted_road", ["depot_id"])


def downgrade():
    op.drop_table("master_restricted_road")
