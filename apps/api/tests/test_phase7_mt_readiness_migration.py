"""Exercise readiness migration and server defaults using an isolated database."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_readiness_migration_preserves_other_statuses_and_updates_default():
    path = Path(__file__).resolve().parents[3] / "db/migrations/versions/0035_phase7_mt_readiness.py"
    spec = importlib.util.spec_from_file_location("readiness_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE vehicle_operational_state (id INTEGER PRIMARY KEY, operational_status VARCHAR(30) NOT NULL DEFAULT 'READY')")
        connection.exec_driver_sql("INSERT INTO vehicle_operational_state (operational_status) VALUES ('READY'), ('ON_TRIP'), ('UNAVAILABLE')")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.exec_driver_sql("INSERT INTO vehicle_operational_state DEFAULT VALUES")
        assert connection.exec_driver_sql("SELECT operational_status FROM vehicle_operational_state ORDER BY id").scalars().all() == ["READY_SIOD", "ON_TRIP", "UNAVAILABLE", "PARKING_DEPOT"]
        migration.downgrade()
        connection.exec_driver_sql("INSERT INTO vehicle_operational_state DEFAULT VALUES")
        assert connection.exec_driver_sql("SELECT operational_status FROM vehicle_operational_state ORDER BY id").scalars().all() == ["READY", "ON_TRIP", "UNAVAILABLE", "READY", "READY"]
    engine.dispose()
