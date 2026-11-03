"""Depot operational shifts and per-LO deadline snapshots."""
from alembic import op
import sqlalchemy as sa
revision = "0036_shift_compliance"
down_revision = "0035_phase7_mt_readiness"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("master_depot", sa.Column("operational_shifts", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("lo_operational_state", sa.Column("shift_id", sa.String(80), nullable=True))
    op.add_column("lo_operational_state", sa.Column("shift_name", sa.String(120), nullable=True))
    op.add_column("lo_operational_state", sa.Column("shift_gate_out_deadline", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for field in ("shift_gate_out_deadline", "shift_name", "shift_id"):
        op.drop_column("lo_operational_state", field)
    op.drop_column("master_depot", "operational_shifts")
