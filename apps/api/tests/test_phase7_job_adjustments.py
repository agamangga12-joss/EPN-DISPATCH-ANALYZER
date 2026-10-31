from datetime import date, datetime, time, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import (Base, MasterDepot, MasterMT, MasterSPBU, MasterProduct, MasterTag,
    BridgeMTTag, BridgeSPBUTag, PredictionRun, OptimizationJob, LOOperationalState,
    VehicleOperationalState, ActualVehicleEvent)
from app.phase7_routes import router
from app.phase7_constants import effective_parameters
from app.phase7_service import _solver_inputs, validate_job

NOW = datetime(2026, 10, 29, 0, tzinfo=timezone.utc)

@pytest.fixture
def workspace():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            MasterDepot(depot_id="D", depot_name="Depot", depot_operational_start=time(0), depot_operational_end=time(23,59)),
            MasterDepot(depot_id="OTHER", depot_name="Other"),
            MasterProduct(product_id="P", product_name="Fuel", normalized_product="FUEL"),
            MasterSPBU(spbu_id="S", spbu_code="123", primary_depot_id="D", vehicle_type_tag=8),
            MasterSPBU(spbu_id="OUTSIDE", spbu_code="456", primary_depot_id="OTHER"),
            MasterMT(mt_id="M", vehicle_name_raw="Truck", depot_id="D", vehicle_type_tag=8),
            MasterTag(tag_id="T", tag_value="SPECIAL", normalized_tag="SPECIAL"),
            MasterTag(tag_id="X", tag_value="OTHER", normalized_tag="OTHER"),
            PredictionRun(id="P6", prediction_run_no="P6", depot_id="D", model_id="MODEL", model_version=1,
                status="COMPLETED", input_loading_order_filename="lo.csv", input_mt_availability_filename="mt.csv", algorithm_version="test"),
        ])
        db.flush()
        db.add_all([
            OptimizationJob(job_id="J", job_no="JOB", job_name="Job", depot_id="D", operating_date=date(2026,10,29), source_prediction_run_id="P6"),
            OptimizationJob(job_id="J2", job_no="JOB2", job_name="Other Job", depot_id="D", operating_date=date(2026,10,29), source_prediction_run_id="P6"),
            BridgeMTTag(mt_id="M", tag_id="T"), BridgeSPBUTag(spbu_id="S", tag_id="T"),
        ])
        db.flush()
        for job_id in ["J", "J2"]:
            db.add(VehicleOperationalState(vehicle_state_id="V"+job_id, job_id=job_id, mt_id="M", vehicle_class=8,
                tag_snapshot=["SPECIAL"], capacity_kl=8, number_of_compartments=1,
                compartment_configuration=[{"compartment_id":"C1", "capacity_kl":8}], planned_eta_depot=NOW))
        db.commit()
        app = FastAPI(); app.include_router(router)
        def session():
            try:
                yield db
            except Exception:
                db.rollback()
                raise
        app.dependency_overrides[get_db] = session
        yield db, TestClient(app)
    engine.dispose()


def add(client, number="LO1", **overrides):
    return client.post("/api/v1/phase7/jobs/J/loading-orders", json={"loading_order_id":number,
        "spbu_id":"S", "product_id":"P", "volume_kl":8, **overrides})


def inputs(db):
    return _solver_inputs(db, db.get(OptimizationJob,"J"), effective_parameters({}), current_time=NOW, reroute=False)


def test_tag_override_affects_readiness_solver_and_only_current_job(workspace):
    db, client = workspace
    assert add(client).status_code == 201
    assert inputs(db)["loading_orders"][0]["allowed_vehicle_ids"] == ["M"]
    result = client.patch("/api/v1/phase7/jobs/J/vehicles", json={"updates":[{"mt_id":"M", "disabled_tag_ids":["T"]}]})
    assert result.status_code == 200, result.text
    assert result.json()["vehicles"][0]["tags"] == []
    assert result.json()["vehicles"][0]["master_tags"] == [{"tag_id":"T", "tag_value":"SPECIAL"}]
    assert inputs(db)["loading_orders"][0]["allowed_vehicle_ids"] == []
    assert inputs(db)["vehicles"][0]["tags"] == []
    assert any(row["code"] == "NO_COMPATIBLE_MT" for row in validate_job(db,"J")["messages"])
    assert db.get(BridgeMTTag, ("M","T")) is not None
    assert client.get("/api/v1/phase7/jobs/J2/vehicles").json()[0]["tags"] == ["SPECIAL"]
    assert db.scalar(select(ActualVehicleEvent).where(ActualVehicleEvent.event_type == "TAG_UPDATE")) is not None
    assert client.patch("/api/v1/phase7/jobs/J/vehicles",json={"updates":[{"mt_id":"M", "disabled_tag_ids":[]}]}).status_code == 200
    assert inputs(db)["loading_orders"][0]["allowed_vehicle_ids"] == ["M"]


@pytest.mark.parametrize("value", [["X"], ["unknown"], None])
def test_tag_override_rejects_foreign_tags_and_null(workspace, value):
    _,client=workspace
    assert client.patch("/api/v1/phase7/jobs/J/vehicles",json={"updates":[{"mt_id":"M", "disabled_tag_ids":value}]}).status_code == 422


def test_add_cancel_lo_preserves_source_and_excludes_solver(workspace):
    db,client=workspace
    original = db.get(PredictionRun,"P6").input_loading_order_snapshot
    assert add(client).status_code == 201
    assert add(client,"LO2").status_code == 201
    assert len(inputs(db)["loading_orders"]) == 2
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/cancel",json={"loading_order_ids":["LO1"]}).status_code == 200
    assert [row["loading_order_id"] for row in client.get("/api/v1/phase7/jobs/J/loading-orders").json()] == ["LO2"]
    assert [row["loading_order_id"] for row in inputs(db)["loading_orders"]] == ["LO2"]
    assert client.get("/api/v1/phase7/jobs/J").json()["total_lo"] == 1
    assert db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "LO1")).user_cancelled
    assert db.get(PredictionRun,"P6").input_loading_order_snapshot == original
    assert add(client).status_code == 409
    assert client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"updates":[{"loading_order_id":"LO1", "status":"ONGOING"}]}).status_code == 409


@pytest.mark.parametrize("overrides", [{"volume_kl":0}, {"volume_kl":-1}, {"spbu_id":"OUTSIDE"}, {"product_id":"missing"}, {"loading_order_id":"  "}])
def test_add_rejects_invalid_input(workspace, overrides):
    _,client=workspace
    assert add(client, **overrides).status_code == 422


@pytest.mark.parametrize("status,frozen", [("ONGOING",False),("DONE",False),("PLANNED",True)])
def test_cancellation_is_atomic_and_protects_operational_los(workspace,status,frozen):
    db,client=workspace
    add(client); add(client,"LO2")
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "LO2"))
    row.status=status; row.frozen=frozen; db.commit()
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/cancel",json={"loading_order_ids":["LO1","LO2"]}).status_code == 409
    assert not any(row.user_cancelled for row in db.scalars(select(LOOperationalState)).all())


def test_calculating_and_cross_job_protection(workspace):
    db,client=workspace
    add(client)
    assert client.post("/api/v1/phase7/jobs/J2/loading-orders/cancel",json={"loading_order_ids":["LO1"]}).status_code == 404
    job=db.get(OptimizationJob,"J"); job.status="CALCULATING"; db.commit()
    assert add(client,"LO2").status_code == 409
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/cancel",json={"loading_order_ids":["LO1"]}).status_code == 409
    assert client.patch("/api/v1/phase7/jobs/J/vehicles",json={"updates":[{"mt_id":"M", "disabled_tag_ids":[]}]}).status_code == 409


def test_spbu_options_are_depot_scoped(workspace):
    _,client=workspace
    assert [row["spbu_id"] for row in client.get("/api/v1/phase7/jobs/J/loading-orders/options").json()] == ["S"]


def test_cannot_cancel_planned_lo_in_a_trip_already_started(workspace):
    db,client=workspace
    add(client); add(client,"LO2")
    rows=db.scalars(select(LOOperationalState)).all()
    for row in rows:
        row.current_vehicle_id="M"; row.current_trip_number=1
    rows[0].status="ONGOING"; db.commit()
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/cancel",json={"loading_order_ids":[rows[1].loading_order_id]}).status_code == 409
    assert not rows[1].user_cancelled


def test_missing_lo_cancels_nothing(workspace):
    db,client=workspace
    add(client)
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/cancel",json={"loading_order_ids":["LO1","missing"]}).status_code == 404
    assert not db.scalar(select(LOOperationalState)).user_cancelled


def test_migration_backfills_existing_mt_without_changing_snapshot():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    path=Path(__file__).resolve().parents[3] / "db/migrations/versions/0034_phase7_mt_tag_overrides.py"
    spec=importlib.util.spec_from_file_location("migration34",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine=create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicle_operational_state (vehicle_state_id TEXT PRIMARY KEY, tag_snapshot JSON)"))
        connection.execute(text("INSERT INTO vehicle_operational_state VALUES (:id, :tags)"), {"id": "existing", "tags": '["SPECIAL"]'})
        module.op=Operations(MigrationContext.configure(connection))
        module.upgrade()
        row=connection.execute(text("SELECT tag_snapshot, disabled_tag_ids FROM vehicle_operational_state")).one()
        assert row == ('["SPECIAL"]','[]')
    engine.dispose()


def test_cancelling_all_los_allows_empty_replacement_plan(workspace):
    from app.phase7_optimization import OptimizationCoordinatorService
    db,client=workspace
    add(client)
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/cancel",json={"loading_order_ids":["LO1"]}).status_code == 200
    messages=validate_job(db,"J")["messages"]
    assert any(row["code"] == "ALL_LO_CANCELLED" for row in messages)
    assert not any(row["code"] == "LO_REQUIRED" for row in messages)
    state=inputs(db)
    assert state["all_lo_rows"] == []
    result=OptimizationCoordinatorService().optimize(loading_orders=[], vehicles=state["vehicles"], distance_matrix=[[0]],
        time_matrix=[[0]], bays=[], actual_bay_states=[], initial_queue=[], loading_durations={}, day_start=NOW,
        depot_close=NOW.replace(hour=23), parameters=effective_parameters({}))
    assert result["trips"] == [] and result["dropped"] == []
