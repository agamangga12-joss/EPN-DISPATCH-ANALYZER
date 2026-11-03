from datetime import date, timedelta, timezone
from io import BytesIO
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from openpyxl import load_workbook
from app.models import MasterDepot, LOOperationalState
from app.main import build_crud_record, apply_crud_update
from app.shift_compliance import validate_operational_shifts, shift_deadline
from app.phase6_validation import validate_loading_orders
from app.phase6_export import loading_order_workbook
from app.phase7_optimization import OptimizationCoordinatorService, BayQueueOptimizationService, VRPOptimizationService
from test_phase6_prediction_assignment import make_session, seed, workbook
from test_phase7_dynamic_vrp import DAY_START, parameters, vehicle, loading_order, constraint_override

SHIFTS = [{"shift_id": "1", "name": "Shift 1", "start_time": "05:00", "end_time": "11:00"},
          {"shift_id": "2", "name": "Shift 2", "start_time": "11:01", "end_time": "23:00"}]


def test_master_depot_shift_crud_validation_and_overnight():
    depot = build_crud_record("DEPOT", {"depot_name": "Depot", "operational_shifts": SHIFTS})
    assert depot.operational_shifts == SHIFTS
    apply_crud_update("DEPOT", depot, {"operational_shifts": SHIFTS[:1]})
    assert len(depot.operational_shifts) == 1
    with pytest.raises(HTTPException):
        validate_operational_shifts([SHIFTS[0], SHIFTS[0]])
    night = {"start_time": "23:00", "end_time": "05:00"}
    deadline = shift_deadline(date(2026, 11, 3), night, "Asia/Jakarta")
    assert deadline.isoformat() == "2026-11-03T22:00:00+00:00"


@pytest.mark.parametrize("shift,valid", [("1", True), ("Shift 2", True), ("3", False), (None, False)])
def test_upload_explicit_shift_snapshots_deadline_independent_of_planned_time(shift, valid):
    Session = make_session()
    with Session() as db:
        model = seed(db)
        db.get(MasterDepot, "D1").operational_shifts = SHIFTS
        db.commit()
        result = validate_loading_orders(db, depot_id="D1", model=model,
            content=workbook(["loading_order_no", "shipment_start_datetime", "spbu_no", "product", "order_quantity_kl", "shift"],
                [["LO1", "2026-08-22 03:00:00", "SPBU-A", "PERTAMAX", 8, shift]]), file_name="lo.xlsx")
        if valid:
            row = result["normalized_rows"][0]
            assert row["shift_id"] == ("1" if shift == "1" else "2")
            assert row["shift_gate_out_deadline"] == ("2026-08-22T04:00:00+00:00" if shift == "1" else "2026-08-22T16:00:00+00:00")
        else:
            assert not result["normalized_rows"]
            assert any(issue["error_code"] == "INVALID_OPERATIONAL_SHIFT" for issue in result["issues"])


def test_managed_workbook_preserves_shift():
    content = loading_order_workbook([{"loading_order_no": "LO1", "shift": "1"}])
    sheet = load_workbook(BytesIO(content)).active
    assert list(sheet.values)[0][-1] == "shift"
    assert list(sheet.values)[1][-1] == "1"


@pytest.mark.parametrize("mode,enabled,late,expected_drop,penalty", [
    ("HARD", True, -30, False, 0), ("HARD", True, 0, False, 0),
    ("HARD", True, 1, True, 0), ("SOFT", True, 20, False, 2000),
    ("SOFT", True, 60, False, 6000), ("HARD", False, 20, False, 0),
])
def test_final_gate_out_compliance_and_per_minute_penalty(mode, enabled, late, expected_drop, penalty):
    deadline = DAY_START + timedelta(hours=11)
    trip = {"vehicle_id": "M1", "trip_number": 1, "gate_out": deadline + timedelta(minutes=late),
        "operating_minutes": 60, "lo_assignments": [{**loading_order("LO1", "S1"), "shift_gate_out_deadline": deadline}],
        "constraint_violations": []}
    fleet = [{**vehicle("M1"), "working_time_limit_minutes": 600}]
    params = parameters(**constraint_override("shift_compliance", mode=mode, enabled=enabled, penalty=100))
    for _ in range(2):
        dropped, reasons, retry = OptimizationCoordinatorService._post_bay_failures(
            trips=[trip], bay_result={}, vehicles=fleet, parameters=params, day_start=DAY_START)
        assert (0 in dropped) == expected_drop
        if expected_drop:
            assert reasons[0][0] == "SHIFT_DEADLINE_EXCEEDED"
            assert 0 in retry
        else:
            assert trip["constraint_penalty_cost"] == penalty


@pytest.mark.parametrize("strategy", ["FIFO_BALANCED", "CP_SAT"])
@pytest.mark.parametrize("mode", ["HARD", "SOFT"])
def test_bay_loading_and_gate_time_are_included_in_compliance(strategy, mode):
    params = parameters(bay_scheduler_strategy=strategy,
        **constraint_override("shift_compliance", mode=mode, penalty=100))
    trip = {"vehicle_id": "M1", "trip_number": 1, "vehicle_ready_at_depot": DAY_START + timedelta(hours=10, minutes=50),
        "gate_out": DAY_START + timedelta(hours=10, minutes=50), "operating_minutes": 60,
        "lo_assignments": [{**loading_order("LO1", "S1"), "compartment_id": "C1", "shift_gate_out_deadline": DAY_START + timedelta(hours=11)}]}
    result = BayQueueOptimizationService().schedule(trips=[trip],
        bays=[{"master_bay_id": "B1", "all_products_allowed": True, "allowed_product_ids": [], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        actual_states=[], initial_queue=[], loading_durations={"P1": 10}, day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18), parameters=params)
    if result["assignments"]:
        trip["gate_out"] = result["assignments"][0]["gate_out"]
    dropped, reasons, retry = OptimizationCoordinatorService._post_bay_failures(trips=[trip], bay_result=result,
        vehicles=[{**vehicle("M1"), "working_time_limit_minutes": 600}], parameters=params, day_start=DAY_START)
    if mode == "HARD":
        assert 0 in dropped
        assert reasons[0][0] == "SHIFT_DEADLINE_EXCEEDED"
    else:
        assert not dropped
        assert trip["constraint_penalty_cost"] == 500


def test_phase6_prediction_to_phase7_keeps_deadline_snapshot_after_master_edit():
    from app.phase6_service import create_prediction_run
    from app.phase7_service import create_job, load_prediction_run
    Session = make_session()
    with Session() as db:
        seed(db)
        depot = db.get(MasterDepot, "D1")
        depot.operational_shifts = SHIFTS
        db.commit()
        result = create_prediction_run(db, depot_id="D1", model_id="M1",
            loading_order_content=workbook(["loading_order_no", "shipment_start_datetime", "spbu_no", "product", "order_quantity_kl", "shift"],
                [["LO1", "2026-08-22 09:00:00", "SPBU-A", "PERTAMAX", 8, "1"]]),
            loading_order_filename="lo.xlsx",
            availability_content=workbook(["vehicle_registration_no", "initial_available_datetime"], [["B1001AA", "2026-08-22 04:30:00"]]),
            availability_filename="mt.xlsx", parameters=None, created_by="tester")
        depot.operational_shifts = [{**SHIFTS[0], "end_time": "12:00"}]
        db.commit()
        job = create_job(db, {"depot_id": "D1", "operating_date": "2026-08-22"})
        load_prediction_run(db, job["job_id"], result["prediction_run_id"])
        lo = db.scalar(select(LOOperationalState).where(LOOperationalState.job_id == job["job_id"]))
        assert lo.shift_id == "1"
        assert lo.shift_gate_out_deadline.replace(tzinfo=timezone.utc).isoformat() == "2026-08-22T04:00:00+00:00"


def test_mixed_shift_shipment_uses_each_lo_deadline_and_penalty():
    deadline = DAY_START + timedelta(hours=11)
    trip = {"vehicle_id": "M1", "trip_number": 1, "gate_out": deadline + timedelta(minutes=20),
        "operating_minutes": 60, "lo_assignments": [
            {**loading_order("LO1", "S1"), "shift_gate_out_deadline": deadline},
            {**loading_order("LO2", "S2"), "shift_gate_out_deadline": deadline + timedelta(hours=12)}]}
    fleet = [{**vehicle("M1", capacity=16), "working_time_limit_minutes": 600}]
    dropped, _, _ = OptimizationCoordinatorService._post_bay_failures(trips=[trip], bay_result={}, vehicles=fleet,
        parameters=parameters(**constraint_override("shift_compliance", mode="SOFT", penalty=100)), day_start=DAY_START)
    assert not dropped
    assert trip["constraint_penalty_cost"] == 2000
    assert trip["constraint_violations"][0]["entity"] == "LO1"


def test_shift_migration_adds_nullable_deadlines_without_inventing_legacy_shifts():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[3] / "db/migrations/versions/0036_shift_compliance.py"
    spec = importlib.util.spec_from_file_location("shift_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE master_depot (depot_id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE lo_operational_state (loading_order_id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO master_depot VALUES ('D1')")
        connection.exec_driver_sql("INSERT INTO lo_operational_state VALUES ('LO1')")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.exec_driver_sql("SELECT operational_shifts FROM master_depot").scalar() == "[]"
        assert connection.exec_driver_sql("SELECT shift_gate_out_deadline FROM lo_operational_state").scalar() is None
        migration.downgrade()
    engine.dispose()


@pytest.mark.parametrize("mode,expected", [("HARD", 0), ("SOFT", 1)])
def test_full_coordinator_applies_shift_to_actual_gate_out(mode, expected):
    lo = {**loading_order("LO1", "S1"), "shift_gate_out_deadline": DAY_START + timedelta(hours=5, minutes=10)}
    fleet = [{**vehicle("M1"), "working_time_limit_minutes": 600}]
    result = OptimizationCoordinatorService().optimize(loading_orders=[lo], vehicles=fleet,
        distance_matrix=[[0, 300], [300, 0]], time_matrix=[[0, 300], [300, 0]],
        bays=[{"master_bay_id": "B1", "all_products_allowed": True, "allowed_product_ids": [], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        actual_bay_states=[], initial_queue=[], loading_durations={"P1": 10},
        day_start=DAY_START, depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_optimization_time_limit=1, bay_optimization_time_limit=1,
            refueling_minutes=0, **constraint_override("shift_compliance", mode=mode, penalty=100)))
    assert len(result["trips"]) == expected
    if expected:
        violations = result["trips"][0]["constraint_violations"]
        assert any(row["constraint_id"] == "shift_compliance" and row["penalty"] == 500 for row in violations)
    else:
        assert result["dropped"][0]["reason_code"] == "SHIFT_DEADLINE_EXCEEDED"


def test_routing_deadline_before_mt_availability_drops_only_expired_lo():
    result = VRPOptimizationService().solve(
        loading_orders=[{**loading_order("LO1", "S1"), "shift_gate_out_deadline": DAY_START + timedelta(hours=4)}, loading_order("LO2", "S2")],
        vehicles=[vehicle("M1")], distance_matrix=[[0, 300, 300], [300, 0, 300], [300, 300, 0]],
        time_matrix=[[0, 300, 300], [300, 0, 300], [300, 300, 0]], day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18), parameters=parameters(route_optimization_time_limit=1, refueling_minutes=0))
    assert len(result["trips"]) == 1
    assert [lo["loading_order_id"] for lo in result["trips"][0]["lo_assignments"]] == ["LO2"]
    assert result["dropped"][0]["reason_code"] == "SHIFT_DEADLINE_EXCEEDED"
