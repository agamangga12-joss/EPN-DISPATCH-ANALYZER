from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, MasterDepot, MasterMT, OptimizationJob, VehicleOperationalState


def test_bulk_partial_updates_preserve_other_fields_and_unselected_mt():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    original_eta = datetime(2026, 10, 8, 0, tzinfo=timezone.utc)
    with Session(engine) as db:
        db.add(MasterDepot(depot_id="D", depot_name="Depot"))
        db.add(OptimizationJob(job_id="J", job_no="JOB", job_name="Job", depot_id="D", operating_date=date(2026, 10, 8)))
        for index in range(3):
            db.add(MasterMT(mt_id=f"M{index}", vehicle_name_raw=f"MT{index}", depot_id="D"))
            db.add(VehicleOperationalState(vehicle_state_id=f"V{index}", job_id="J", mt_id=f"M{index}", capacity_kl=8, number_of_compartments=1, compartment_configuration=[], planned_eta_depot=original_eta, operational_status="READY"))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            response = client.patch("/api/v1/phase7/jobs/J/vehicles", json={"updates": [{"mt_id": f"M{i}", "operational_status": "UNAVAILABLE"} for i in range(2)]})
            assert response.status_code == 200, response.text
            for i in range(3):
                row = db.get(VehicleOperationalState, f"V{i}")
                assert row.planned_eta_depot.replace(tzinfo=timezone.utc) == original_eta
                assert row.operational_status == ("UNAVAILABLE" if i < 2 else "READY")
            new_eta = "2026-10-08T03:00:00+00:00"
            response = client.patch("/api/v1/phase7/jobs/J/vehicles", json={"updates": [{"mt_id": f"M{i}", "planned_eta_depot": new_eta} for i in range(2)]})
            assert response.status_code == 200, response.text
            for i in range(3):
                row = db.get(VehicleOperationalState, f"V{i}")
                expected = datetime.fromisoformat(new_eta) if i < 2 else original_eta
                assert row.planned_eta_depot.replace(tzinfo=timezone.utc) == expected
                assert row.operational_status == ("UNAVAILABLE" if i < 2 else "READY")
        finally:
            app.dependency_overrides.clear()
    engine.dispose()
