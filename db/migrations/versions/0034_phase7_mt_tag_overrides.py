"""Job-specific MT tag exclusions."""
from alembic import op
import sqlalchemy as sa
revision = "0034_phase7_mt_tag_overrides"
down_revision = "0033_restricted_road_waypoints"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("vehicle_operational_state", sa.Column("disabled_tag_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

def downgrade():
    op.drop_column("vehicle_operational_state", "disabled_tag_ids")
