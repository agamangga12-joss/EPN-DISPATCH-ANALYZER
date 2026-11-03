"""Distinguish depot parking from dispatch readiness."""
from alembic import op
import sqlalchemy as sa

revision = "0035_phase7_mt_readiness"
down_revision = "0034_phase7_mt_tag_overrides"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE vehicle_operational_state SET operational_status = 'READY_SIOD' WHERE operational_status = 'READY'")
    with op.batch_alter_table("vehicle_operational_state") as batch:
        batch.alter_column("operational_status", existing_type=sa.String(30), server_default="PARKING_DEPOT", existing_nullable=False)


def downgrade():
    op.execute("UPDATE vehicle_operational_state SET operational_status = 'READY' WHERE operational_status IN ('READY_SIOD', 'PARKING_DEPOT')")
    with op.batch_alter_table("vehicle_operational_state") as batch:
        batch.alter_column("operational_status", existing_type=sa.String(30), server_default="READY", existing_nullable=False)
