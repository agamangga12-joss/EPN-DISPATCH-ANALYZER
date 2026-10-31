"""Persist the depot selected when an import is queued."""

from alembic import op
import sqlalchemy as sa

revision = "0031_active_depot_import"
down_revision = "0030_depot_scoped_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_audit", sa.Column("depot_id", sa.String(64), nullable=True))
    op.create_foreign_key("fk_import_audit_depot", "import_audit", "master_depot", ["depot_id"], ["depot_id"])
    op.create_index("ix_import_audit_depot_id", "import_audit", ["depot_id"])
    op.add_column("master_spbu", sa.Column("master_rth_min", sa.Float(), nullable=True))
    op.add_column("master_spbu", sa.Column("master_travel_time_sample_count", sa.Integer(), nullable=False, server_default="0"))
    # Retain legacy columns for existing clients, while using one canonical input.
    op.execute("UPDATE master_mt SET vehicle_name_raw = vehicle_registration WHERE vehicle_registration IS NOT NULL")
    op.execute("UPDATE master_mt SET capacity_label = vehicle_type_tag::text || 'KL' WHERE vehicle_type_tag IS NOT NULL")
    op.execute("UPDATE master_spbu SET spbu_name = spbu_code, address = coalesce(address, city)")
    op.execute("UPDATE master_spbu SET city = address")
    op.execute("UPDATE fact_loading_order_line SET actual_km = coalesce(actual_km, source_distance_km)")
    op.execute("UPDATE fact_loading_order_line SET source_distance_km = actual_km")
    op.execute("""
        UPDATE master_spbu SET master_travel_time_min = NULL;
        WITH single_stop AS (
            SELECT shipment_id, min(spbu_id) AS spbu_id
            FROM fact_loading_order_line
            WHERE status IS NULL OR status <> 'DELETED'
            GROUP BY shipment_id
            HAVING count(DISTINCT spbu_id) = 1 AND count(spbu_id) = count(*)
        ), evidence AS (
            SELECT ss.spbu_id,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (s.shipment_end_datetime - s.gate_out_datetime)) / 60.0) AS rth,
                   count(*) AS samples
            FROM single_stop ss JOIN fact_shipment s USING (shipment_id)
            JOIN master_spbu m ON m.spbu_id = ss.spbu_id AND m.primary_depot_id = s.depot_id
            WHERE s.shipment_end_datetime > s.gate_out_datetime
            GROUP BY ss.spbu_id
        )
        UPDATE master_spbu m SET master_rth_min = e.rth,
            master_travel_time_min = e.rth / 2, master_travel_time_sample_count = e.samples
        FROM evidence e WHERE m.spbu_id = e.spbu_id;
    """)


def downgrade() -> None:
    op.drop_column("master_spbu", "master_travel_time_sample_count")
    op.drop_column("master_spbu", "master_rth_min")
    op.drop_index("ix_import_audit_depot_id", table_name="import_audit")
    op.drop_constraint("fk_import_audit_depot", "import_audit", type_="foreignkey")
    op.drop_column("import_audit", "depot_id")
