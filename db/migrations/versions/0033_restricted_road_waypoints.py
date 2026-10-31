"""Operator-defined Google Routes detours; retain existing road geometry/history."""
from alembic import op
import sqlalchemy as sa

revision = "0033_restricted_road_waypoints"
down_revision = "0032_restricted_roads"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("master_restricted_road", sa.Column("direction", sa.String(16), nullable=False, server_default="BOTH"))
    op.add_column("master_restricted_road", sa.Column("forward_waypoints", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("master_restricted_road", sa.Column("reverse_waypoints", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column("master_restricted_road", "reverse_waypoints")
    op.drop_column("master_restricted_road", "forward_waypoints")
    op.drop_column("master_restricted_road", "direction")
