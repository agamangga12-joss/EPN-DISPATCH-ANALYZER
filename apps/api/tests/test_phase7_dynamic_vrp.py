from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    ActualBayState,
    Base,
    LOOperationalState,
    MasterDepot,
    MasterLoadingBay,
    MasterMT,
    MasterProduct,
    MasterSPBU,
    OperationalStateSnapshot,
    OptimizationBayAssignment,
    OptimizationBayOperation,
    OptimizationInitialQueue,
    OptimizationJob,
    OptimizationParameterSnapshot,
    OptimizationRun,
    PredictionAssignment,
    PredictionRun,
    PredictionShipment,
    PredictionShipmentLine,
    PredictionTrip,
    RouteAPIRequestLog,
    RouteMatrixCache,
    RouteVersion,
    RouteVersionLOAssignment,
    RouteVersionStop,
    RouteVersionTrip,
    VehicleOperationalState,
)
from app.phase7_optimization import BayQueueOptimizationService, CompartmentAssignmentService, OptimizationCoordinatorService, VRPOptimizationService, _cp_sat_result_status
from app import phase7_optimization
from app.phase7_constants import constraint_catalog, constraint_is_hard, constraint_is_soft, constraint_limit_minutes, constraint_penalty, effective_parameters
from app.phase7_matrix import RouteMatrixService
from app import phase7_service
from app.phase7_service import (
    _complete_vehicle_eta_state,
    _copy_frozen_plan,
    _comparison,
    _cost_breakdown,
    _normalize_optimization_reference_time,
    _trip_cost_breakdowns,
    apply_freeze_rules,
    delete_job,
    delete_bay_configuration,
    get_bay_configuration,
    get_lo_comparison,
    get_route_version,
    load_mt_from_master,
    recover_interrupted_phase7_optimizations,
    route_time_limit_recommendation,
    update_vehicle_states,
)


DAY_START = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)


def parameters(**overrides) -> dict:
    return effective_parameters({
        "objective": "MIN_TOTAL_DISTANCE",
        "default_spbu_service_minutes": 10,
        "optimization_time_limit": 1,
        "unserved_penalty": 10_000_000,
        "maximum_trips_per_mt": 4,
        "cost_per_km": 10_000,
        "cost_per_operating_hour": 50_000,
        "phase6_vehicle_change_penalty": 0,
        "vehicle_activation_cost_rules": [],
        "gate_process_time": 5,
        "loading_mode": "SEQUENTIAL",
        "max_coordination_iterations": 3,
        "departure_time_tolerance_minutes": 5,
        **overrides,
    })


def test_mt_turnaround_buffer_is_a_validated_profile_parameter() -> None:
    assert effective_parameters({})["mt_turnaround_buffer_minutes"] == 30
    assert effective_parameters({"mt_turnaround_buffer_minutes": 0})["mt_turnaround_buffer_minutes"] == 0
    with pytest.raises(ValueError, match="mt_turnaround_buffer_minutes"):
        effective_parameters({"mt_turnaround_buffer_minutes": -1})


def constraint_override(constraint_id: str, *, enabled: bool = True, mode: str = "SOFT", penalty: float = 123_456) -> dict:
    return {"constraint_rules": {constraint_id: {"enabled": enabled, "mode": mode, "penalty": penalty}}}


def test_vehicle_working_time_limit_is_owned_by_the_constraint_rule() -> None:
    configured = effective_parameters({
        "default_vehicle_working_time_minutes": 999,
        "constraint_rules": {
            "vehicle_working_time": {
                "enabled": True,
                "mode": "HARD",
                "penalty": 500_000,
                "limit_minutes": 480,
            }
        },
    })
    assert "default_vehicle_working_time_minutes" not in configured
    assert constraint_limit_minutes(configured, "vehicle_working_time") == 480


def test_legacy_time_limit_populates_independent_route_and_bay_budgets() -> None:
    legacy = effective_parameters({"optimization_time_limit": 17})
    assert legacy["route_optimization_time_limit"] == 17
    assert legacy["bay_optimization_time_limit"] == 17

    configured = effective_parameters({
        "optimization_time_limit": 17,
        "route_optimization_time_limit": 23,
        "bay_optimization_time_limit": 41,
        "bay_cp_sat_workers": 6,
    })
    assert configured["route_optimization_time_limit"] == 23
    assert configured["bay_optimization_time_limit"] == 41
    assert configured["bay_cp_sat_workers"] == 6


def test_route_time_limit_recommendation_scales_with_lo_and_mt_workload() -> None:
    recommendation = route_time_limit_recommendation(675, 206, 30)

    assert recommendation == {
        "lo_count": 675,
        "mt_count": 206,
        "estimated_lo_per_mt": 4,
        "configured_seconds": 30,
        "recommended_minimum_seconds": 240,
        "below_recommendation": True,
        "requires_confirmation": True,
        "calculation_basis": "round30(15 + 0.25 x LO + 10 x ceil(LO / MT))",
    }
    assert route_time_limit_recommendation(20, 20, 60)["requires_confirmation"] is False


def test_fifo_balanced_is_the_default_bay_scheduler_and_cp_sat_is_opt_in() -> None:
    assert effective_parameters({})["bay_scheduler_strategy"] == "FIFO_BALANCED"
    assert effective_parameters({"bay_scheduler_strategy": "cp_sat"})["bay_scheduler_strategy"] == "CP_SAT"

    with pytest.raises(ValueError, match="bay_scheduler_strategy"):
        effective_parameters({"bay_scheduler_strategy": "RANDOM"})


def test_cp_sat_unknown_and_timeout_are_not_reported_as_infeasible() -> None:
    assert _cp_sat_result_status(
        phase7_optimization.cp_model.UNKNOWN,
        elapsed_seconds=1,
        time_limit_seconds=30,
    ) == "UNKNOWN"
    assert _cp_sat_result_status(
        phase7_optimization.cp_model.UNKNOWN,
        elapsed_seconds=30,
        time_limit_seconds=30,
    ) == "TIMEOUT"
    assert _cp_sat_result_status(
        phase7_optimization.cp_model.INFEASIBLE,
        elapsed_seconds=1,
        time_limit_seconds=30,
    ) == "INFEASIBLE"


def test_delete_job_cascades_workspace_and_preserves_detached_route_audit_log() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.flush()
        db.add(OptimizationJob(job_id="JOB-DELETE", job_no="P7-JOB-DELETE", job_name="Delete Me", depot_id="D1", operating_date=date(2026, 8, 26)))
        db.flush()
        db.add(OperationalStateSnapshot(state_snapshot_id="SNAP-DELETE", job_id="JOB-DELETE", snapshot_reason="TEST"))
        db.add(RouteAPIRequestLog(request_log_id="LOG-DELETE", job_id="JOB-DELETE", request_type="MATRIX", request_fingerprint="delete-test"))
        db.commit()

        result = delete_job(db, "JOB-DELETE")

        assert result == {"job_id": "JOB-DELETE", "job_no": "P7-JOB-DELETE", "status": "DELETED"}
        assert db.get(OptimizationJob, "JOB-DELETE") is None
        assert db.get(OperationalStateSnapshot, "SNAP-DELETE") is None
        assert db.get(RouteAPIRequestLog, "LOG-DELETE").job_id is None


def test_delete_job_rejects_calculating_workspace() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.add(OptimizationJob(job_id="JOB-RUNNING", job_no="P7-JOB-RUNNING", job_name="Running", depot_id="D1", operating_date=date(2026, 8, 26), status="CALCULATING"))
        db.commit()

        with pytest.raises(HTTPException) as raised:
            delete_job(db, "JOB-RUNNING")

        assert raised.value.status_code == 409
        assert db.get(OptimizationJob, "JOB-RUNNING") is not None


def test_route_version_exposes_canonical_product_name() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.flush()
        db.add_all([
            MasterMT(mt_id="M1", vehicle_name_raw="MT 1", vehicle_registration="BK 1001 AA", depot_id="D1"),
            MasterSPBU(spbu_id="S1", spbu_code="14200001", spbu_name="SPBU 1"),
            MasterProduct(product_id="P-BIOSOLAR", product_name="Bio Solar", normalized_product="BIO SOLAR"),
            OptimizationJob(job_id="JOB-PRODUCT", job_no="P7-JOB-PRODUCT", job_name="Product", depot_id="D1", operating_date=date(2026, 8, 26)),
        ])
        db.flush()
        db.add_all([
            OperationalStateSnapshot(state_snapshot_id="STATE-PRODUCT", job_id="JOB-PRODUCT", snapshot_reason="Initial"),
            OptimizationParameterSnapshot(parameter_snapshot_id="PARAM-PRODUCT", job_id="JOB-PRODUCT", effective_parameters={}, parameter_checksum="product"),
        ])
        db.flush()
        db.add(RouteVersion(route_version_id="VERSION-PRODUCT", job_id="JOB-PRODUCT", version_number=1, version_label="V1", reason="Initial", state_snapshot_id="STATE-PRODUCT", parameter_snapshot_id="PARAM-PRODUCT", objective="MIN_TOTAL_COST", solver_status="FEASIBLE", first_gate_out=DAY_START + timedelta(minutes=30), last_gate_out=DAY_START + timedelta(minutes=30), depot_dispatch_span_minutes=0))
        db.flush()
        db.add(RouteVersionTrip(route_version_trip_id="TRIP-PRODUCT", route_version_id="VERSION-PRODUCT", vehicle_id="M1", trip_number=1, shipment_id="SHIP-1", vehicle_ready_at_depot=DAY_START, loading_start=DAY_START + timedelta(minutes=10), loading_finish=DAY_START + timedelta(minutes=25), gate_out=DAY_START + timedelta(minutes=30), estimated_return_depot=DAY_START + timedelta(hours=2)))
        db.flush()
        db.add_all([
            RouteVersionStop(route_version_stop_id="STOP-PRODUCT", route_version_trip_id="TRIP-PRODUCT", sequence_number=1, spbu_id="S1", loading_order_ids=["LO-1"], products=["P-BIOSOLAR"], volume_kl=8),
            RouteVersionLOAssignment(route_version_lo_assignment_id="ASSIGN-PRODUCT", route_version_id="VERSION-PRODUCT", route_version_trip_id="TRIP-PRODUCT", loading_order_id="LO-1", vehicle_id="M1", trip_number=1, shipment_id="SHIP-1", compartment_id="C1", spbu_id="S1", product_id="P-BIOSOLAR", volume_kl=8, stop_sequence=1, assignment_status="PLANNED"),
        ])
        db.commit()

        payload = get_route_version(db, "JOB-PRODUCT", "VERSION-PRODUCT")

        assert payload["trips"][0]["loading_orders"][0]["product_id"] == "P-BIOSOLAR"
        assert payload["trips"][0]["loading_orders"][0]["product_name"] == "Bio Solar"
        assert payload["trips"][0]["stops"][0]["product_names"] == ["Bio Solar"]
        assert payload["first_loading_start"] == (DAY_START + timedelta(minutes=10)).isoformat()
        assert payload["depot_dispatch_span_minutes"] == 20


def test_lo_comparison_uses_immutable_phase6_and_route_version_snapshots() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add_all([
            MasterDepot(depot_id="D1", depot_name="Depot 1"),
            MasterMT(mt_id="M1", vehicle_name_raw="MT 1", vehicle_registration="BK 1001 AA", depot_id="D1"),
            MasterMT(mt_id="M2", vehicle_name_raw="MT 2", vehicle_registration="BK 1002 AA", depot_id="D1"),
            MasterSPBU(spbu_id="S1", spbu_code="14200001", spbu_name="SPBU A"),
            MasterSPBU(spbu_id="S2", spbu_code="14200002", spbu_name="SPBU B"),
            MasterProduct(product_id="P1", product_name="Bio Solar", normalized_product="BIO SOLAR"),
            PredictionRun(
                id="P6",
                prediction_run_no="PRED-TEST",
                depot_id="D1",
                model_id="MODEL-1",
                model_version=1,
                status="COMPLETED",
                input_loading_order_filename="lo.csv",
                input_mt_availability_filename="mt.csv",
                algorithm_version="test",
            ),
        ])
        db.flush()
        db.add(OptimizationJob(job_id="JOB-COMPARE", job_no="P7-JOB-COMPARE", job_name="Compare", depot_id="D1", operating_date=date(2026, 8, 26), source_prediction_run_id="P6"))
        db.add_all([
            PredictionShipment(id="SHIP-A", prediction_run_id="P6", predicted_shipment_id="P6-SHIP-A", shift_id="SHIFT-1", shift_name="Shift 1"),
            PredictionShipment(id="SHIP-B", prediction_run_id="P6", predicted_shipment_id="P6-SHIP-B", shift_id="SHIFT-1", shift_name="Shift 1"),
        ])
        db.flush()
        db.add_all([
            PredictionShipmentLine(id="LINE-1", prediction_run_id="P6", prediction_shipment_id="SHIP-A", loading_order_no="LO-1", spbu_id="S1", spbu_no="14200001", product_id="P1", product_name="Bio Solar", order_quantity_kl=8, model_predicted_shipment_id="P6-SHIP-A"),
            PredictionShipmentLine(id="LINE-2", prediction_run_id="P6", prediction_shipment_id="SHIP-B", loading_order_no="LO-2", spbu_id="S2", spbu_no="14200002", product_id="P1", product_name="Bio Solar", order_quantity_kl=8, model_predicted_shipment_id="P6-SHIP-B"),
            PredictionAssignment(id="P6-A1", prediction_shipment_id="SHIP-A", final_vehicle_id="M1", assignment_status="ASSIGNED"),
            PredictionAssignment(id="P6-A2", prediction_shipment_id="SHIP-B", final_vehicle_id="M1", assignment_status="ASSIGNED"),
            PredictionTrip(id="P6-T1", prediction_run_id="P6", prediction_shipment_id="SHIP-A", trip_id="TRIP-1", trip_number=1, vehicle_id="M1", planned_start_datetime=DAY_START, predicted_departure_datetime=DAY_START + timedelta(hours=1), estimated_return_datetime=DAY_START + timedelta(hours=3), assignment_status="ASSIGNED"),
            PredictionTrip(id="P6-T2", prediction_run_id="P6", prediction_shipment_id="SHIP-B", trip_id="TRIP-2", trip_number=2, vehicle_id="M1", planned_start_datetime=DAY_START + timedelta(hours=3), predicted_departure_datetime=DAY_START + timedelta(hours=4), estimated_return_datetime=DAY_START + timedelta(hours=6), assignment_status="ASSIGNED"),
            RouteVersion(route_version_id="V1-COMPARE", job_id="JOB-COMPARE", version_number=1, version_label="V1", reason="Initial", state_snapshot_id="STATE-1", parameter_snapshot_id="PARAM-1", objective="MIN_TOTAL_COST", solver_status="FEASIBLE"),
        ])
        db.flush()
        db.add(RouteVersionTrip(route_version_trip_id="V1-T1", route_version_id="V1-COMPARE", vehicle_id="M2", trip_number=1, shipment_id="V1-SHIP-A", vehicle_ready_at_depot=DAY_START, gate_out=DAY_START + timedelta(hours=1, minutes=30), estimated_return_depot=DAY_START + timedelta(hours=4)))
        db.flush()
        db.add_all([
            RouteVersionLOAssignment(route_version_lo_assignment_id="V1-A1", route_version_id="V1-COMPARE", route_version_trip_id="V1-T1", loading_order_id="LO-1", vehicle_id="M2", trip_number=1, shipment_id="V1-SHIP-A", spbu_id="S1", product_id="P1", volume_kl=8, planned_gate_out=DAY_START + timedelta(hours=1, minutes=30), assignment_status="PLANNED"),
            RouteVersionLOAssignment(route_version_lo_assignment_id="V1-A2", route_version_id="V1-COMPARE", loading_order_id="LO-2", spbu_id="S2", product_id="P1", volume_kl=8, assignment_status="DROPPED", dropped_reason_code="NO_COMPATIBLE_MT"),
            RouteVersionLOAssignment(route_version_lo_assignment_id="V1-A3", route_version_id="V1-COMPARE", route_version_trip_id="V1-T1", loading_order_id="LO-3", vehicle_id="M2", trip_number=1, shipment_id="V1-SHIP-A", spbu_id="S1", product_id="P1", volume_kl=8, planned_gate_out=DAY_START + timedelta(hours=1, minutes=30), assignment_status="PLANNED"),
        ])
        db.commit()

        payload = get_lo_comparison(db, "JOB-COMPARE", "PHASE6", "V1-COMPARE")

        assert payload["source_a"]["label"] == "Phase 6 · PRED-TEST"
        assert payload["source_b"]["label"] == "Phase 7 · V1"
        assert payload["summary"] == {
            "total_lo_a": 2,
            "total_lo_b": 3,
            "union_lo_count": 3,
            "common_lo_count": 2,
            "only_a_count": 0,
            "only_b_count": 1,
            "assigned_lo_a": 2,
            "assigned_lo_b": 2,
            "dropped_or_unassigned_a": 0,
            "dropped_or_unassigned_b": 1,
            "same_mt_count": 0,
            "changed_mt_count": 1,
            "comparable_mt_count": 1,
            "mt_change_pct": 100.0,
            "gate_out_changed_count": 1,
            "average_abs_gate_out_delta_minutes": 30.0,
            "eta_depot_changed_count": 1,
            "average_abs_eta_depot_delta_minutes": 60.0,
        }
        rows = {row["loading_order_id"]: row for row in payload["rows"]}
        assert rows["LO-1"]["a"]["mt_registration"] == "BK 1001 AA"
        assert rows["LO-1"]["b"]["mt_registration"] == "BK 1002 AA"
        assert rows["LO-1"]["gate_out_delta_minutes"] == 30
        assert rows["LO-1"]["eta_depot_delta_minutes"] == 60
        assert rows["LO-2"]["b"]["status"] == "DROPPED"
        assert rows["LO-3"]["a"]["present"] is False

        with pytest.raises(HTTPException) as raised:
            get_lo_comparison(db, "JOB-COMPARE", "PHASE6", "PHASE6")
        assert raised.value.status_code == 422


def test_enqueue_optimization_reserves_job_and_rejects_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(phase7_service, "validate_job", lambda *_args, **_kwargs: {"status": "READY", "messages": []})
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1", timezone="Asia/Jakarta"))
        db.add(MasterMT(mt_id="M-ASYNC", vehicle_name_raw="MT Async", vehicle_registration="BK 1000 AA", depot_id="D1"))
        db.add(MasterLoadingBay(master_bay_id="B-ASYNC", depot_id="D1", bay_id="BAY-1", bay_name="Bay 1"))
        db.add(OptimizationJob(job_id="JOB-ASYNC", job_no="P7-JOB-ASYNC", job_name="Async", depot_id="D1", operating_date=date(2026, 8, 26)))
        db.flush()
        db.add(ActualBayState(
            actual_bay_state_id="STATE-ASYNC",
            job_id="JOB-ASYNC",
            master_bay_id="B-ASYNC",
            remaining_loading_minutes=12,
            actual_queue_length=1,
            state_effective_at=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        ))
        db.add(OptimizationInitialQueue(
            initial_queue_id="QUEUE-ASYNC",
            job_id="JOB-ASYNC",
            master_bay_id="B-ASYNC",
            queue_position=1,
            vehicle_id="M-ASYNC",
            estimated_loading_duration_minutes=10,
            state_effective_at=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        ))
        db.commit()

        accepted = phase7_service.enqueue_optimization(
            db,
            "JOB-ASYNC",
            {"current_time": "2026-08-26T08:00:00", "parameters": {}},
            reroute=False,
        )

        assert accepted["status"] == "CALCULATING"
        assert accepted["run_type"] == "INITIAL"
        assert accepted["optimization_reference_time"] == "2026-08-26T01:00:00+00:00"
        assert db.get(OptimizationJob, "JOB-ASYNC").status == "CALCULATING"
        actual_state = db.get(ActualBayState, "STATE-ASYNC")
        queued = db.get(OptimizationInitialQueue, "QUEUE-ASYNC")
        assert phase7_service._iso(actual_state.state_effective_at) == accepted["optimization_reference_time"]
        assert phase7_service._iso(queued.state_effective_at) == accepted["optimization_reference_time"]

        with pytest.raises(HTTPException) as raised:
            phase7_service.enqueue_optimization(
                db,
                "JOB-ASYNC",
                {"current_time": "2026-08-26T08:01:00", "parameters": {}},
                reroute=False,
            )
        assert raised.value.status_code == 409
        assert raised.value.detail["code"] == "OPTIMIZATION_ALREADY_RUNNING"


@pytest.mark.parametrize(
    ("planned_eta", "accepted", "invalid_bucket"),
    [
        (None, False, "missing_mt"),
        (datetime(2026, 8, 26, 0, 59, tzinfo=timezone.utc), False, "before_optimization_mt"),
        (datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc), True, None),
    ],
)
def test_optimization_requires_planned_eta_at_or_after_reference_time(
    monkeypatch: pytest.MonkeyPatch,
    planned_eta: datetime | None,
    accepted: bool,
    invalid_bucket: str | None,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(phase7_service, "validate_job", lambda *_args, **_kwargs: {"status": "READY", "messages": []})
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1", timezone="Asia/Jakarta"))
        db.add(MasterMT(mt_id="M-ETA", vehicle_name_raw="MT ETA", vehicle_registration="BK 2000 AA", depot_id="D1"))
        db.add(OptimizationJob(job_id="JOB-ETA", job_no="P7-JOB-ETA", job_name="ETA", depot_id="D1", operating_date=date(2026, 8, 26)))
        db.flush()
        db.add(VehicleOperationalState(
            vehicle_state_id="VS-ETA",
            job_id="JOB-ETA",
            mt_id="M-ETA",
            registration_snapshot="BK 2000 AA",
            planned_eta_depot=planned_eta,
        ))
        db.commit()

        if accepted:
            result = phase7_service.enqueue_optimization(
                db,
                "JOB-ETA",
                {"current_time": "2026-08-26T08:00:00", "parameters": {}},
                reroute=False,
            )
            assert result["status"] == "CALCULATING"
            assert result["optimization_reference_time"] == "2026-08-26T01:00:00+00:00"
        else:
            with pytest.raises(HTTPException) as raised:
                phase7_service.enqueue_optimization(
                    db,
                    "JOB-ETA",
                    {"current_time": "2026-08-26T08:00:00", "parameters": {}},
                    reroute=False,
                )
            assert raised.value.status_code == 422
            assert raised.value.detail["code"] == "PLANNED_ETA_DEPOT_INVALID"
            assert raised.value.detail[invalid_bucket][0]["mt_id"] == "M-ETA"
            assert db.get(OptimizationJob, "JOB-ETA").status != "CALCULATING"


def test_enqueue_requires_acknowledgement_when_route_limit_is_below_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    recommendation = route_time_limit_recommendation(675, 206, 30)
    monkeypatch.setattr(
        phase7_service,
        "validate_job",
        lambda *_args, **_kwargs: {
            "status": "WARNING",
            "messages": [],
            "route_time_limit_recommendation": recommendation,
        },
    )
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1", timezone="Asia/Jakarta"))
        db.add(MasterMT(mt_id="M-LIMIT", vehicle_name_raw="MT Limit", vehicle_registration="BK 3000 AA", depot_id="D1"))
        db.add(OptimizationJob(job_id="JOB-LIMIT", job_no="P7-JOB-LIMIT", job_name="Limit", depot_id="D1", operating_date=date(2026, 8, 26)))
        db.flush()
        db.add(VehicleOperationalState(
            vehicle_state_id="VS-LIMIT",
            job_id="JOB-LIMIT",
            mt_id="M-LIMIT",
            registration_snapshot="BK 3000 AA",
            planned_eta_depot=datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc),
        ))
        db.commit()

        with pytest.raises(HTTPException) as raised:
            phase7_service.enqueue_optimization(
                db,
                "JOB-LIMIT",
                {"current_time": "2026-08-26T08:00:00", "parameters": {"route_optimization_time_limit": 30}},
                reroute=False,
            )
        assert raised.value.status_code == 422
        assert raised.value.detail["code"] == "ROUTE_TIME_LIMIT_CONFIRMATION_REQUIRED"
        assert db.get(OptimizationJob, "JOB-LIMIT").status != "CALCULATING"

        accepted = phase7_service.enqueue_optimization(
            db,
            "JOB-LIMIT",
            {
                "current_time": "2026-08-26T08:00:00",
                "parameters": {"route_optimization_time_limit": 30},
                "route_time_limit_confirmed": True,
            },
            reroute=False,
        )
        assert accepted["status"] == "CALCULATING"


def test_delete_bay_soft_deletes_master_without_exposing_it_in_configuration() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.flush()
        db.add(MasterLoadingBay(master_bay_id="B1", depot_id="D1", bay_id="BAY-1", bay_name="Bay 1"))
        db.commit()

        result = delete_bay_configuration(db, "D1", "B1")

        assert result == {"master_bay_id": "B1", "bay_id": "BAY-1", "status": "DELETED"}
        assert db.get(MasterLoadingBay, "B1").active_status == "DELETED"
        assert get_bay_configuration(db, "D1")["bays"] == []


def test_constraint_registry_applies_penalty_only_to_enabled_soft_rules() -> None:
    for definition in constraint_catalog():
        assert definition["default_mode"] in {"HARD", "SOFT"}
    soft = effective_parameters(constraint_override("vehicle_capacity", mode="SOFT", penalty=321_000))
    assert constraint_is_soft(soft, "vehicle_capacity")
    assert constraint_penalty(soft, "vehicle_capacity") == 321_000
    hard = effective_parameters(constraint_override("vehicle_capacity", mode="HARD", penalty=321_000))
    assert constraint_is_hard(hard, "vehicle_capacity")
    assert constraint_penalty(hard, "vehicle_capacity") == 0
    disabled = effective_parameters(constraint_override("vehicle_capacity", enabled=False, mode="SOFT", penalty=321_000))
    assert not constraint_is_hard(disabled, "vehicle_capacity")
    assert not constraint_is_soft(disabled, "vehicle_capacity")
    assert constraint_penalty(disabled, "vehicle_capacity") == 0


def test_compartment_product_constraint_can_be_soft_or_disabled() -> None:
    loading_orders = [
        {"loading_order_id": "LO-1", "product_id": "PERTALITE", "volume_kl": 4},
        {"loading_order_id": "LO-2", "product_id": "BIOSOLAR", "volume_kl": 4},
    ]
    compartments = [{"compartment_id": "C1", "capacity_kl": 8}]
    soft = CompartmentAssignmentService().assign(
        loading_orders,
        compartments,
        parameters=parameters(**constraint_override("compartment_product_separation", mode="SOFT", penalty=777_000)),
    )
    assert soft["feasible"] is True
    assert any(row["constraint_id"] == "compartment_product_separation" for row in soft["constraint_violations"])
    assert soft["penalty_cost"] == 777_000
    disabled = CompartmentAssignmentService().assign(
        loading_orders,
        compartments,
        parameters=parameters(**constraint_override("compartment_product_separation", enabled=False, penalty=777_000)),
    )
    assert disabled["feasible"] is True
    assert disabled["constraint_violations"] == []
    assert disabled["penalty_cost"] == 0


def vehicle(mt_id: str, *, eta_hour: int = 5, capacity: float = 8, compartments: int = 1) -> dict:
    return {
        "mt_id": mt_id,
        "vehicle_class": int(capacity),
        "tags": [],
        "capacity_kl": capacity,
        "compartments": [
            {"compartment_id": f"C{index}", "capacity_kl": capacity / compartments}
            for index in range(1, compartments + 1)
        ],
        "effective_eta_depot": DAY_START + timedelta(hours=eta_hour),
        "operational_status": "READY",
        "working_time_remaining_minutes": 600,
        "working_time_used_minutes": 0,
    }


def loading_order(lo_id: str, spbu_id: str, *, product_id: str = "P1", allowed=None, preferred="M1") -> dict:
    return {
        "loading_order_id": lo_id,
        "spbu_id": spbu_id,
        "product_id": product_id,
        "volume_kl": 8,
        "allowed_vehicle_ids": allowed if allowed is not None else ["M1"],
        "phase6_predicted_vehicle_id": preferred,
        "phase6_predicted_shipment_id": "P6-SHIP-1",
        "mandatory": True,
    }


@pytest.mark.parametrize("count,capacity,expected_trips", [(3, 24, 1), (2, 24, 0), (2, 16, 1), (7, 24, 2)])
def test_full_load_is_required_on_every_used_trip(count, capacity, expected_trips) -> None:
    orders = [loading_order(f"LO-{index}", f"S{index}") for index in range(count)]
    matrix = [[0 if i == j else 300 for j in range(count + 1)] for i in range(count + 1)]
    result = VRPOptimizationService().solve(
        loading_orders=orders, vehicles=[vehicle("M1", capacity=capacity, compartments=capacity // 8)],
        distance_matrix=matrix, time_matrix=matrix, day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_optimization_time_limit=4, refueling_minutes=0),
    )
    assert len(result["trips"]) == expected_trips
    assert all(sum(lo["volume_kl"] for lo in trip["lo_assignments"]) == capacity for trip in result["trips"])
    assert len(result["dropped"]) == count - expected_trips * (capacity // 8)
    if result["dropped"]:
        assert all(row["reason_code"] == "FULL_LOAD_NOT_MET" for row in result["dropped"])


@pytest.mark.parametrize("mode,enabled", [("SOFT", True), ("HARD", False)])
def test_full_load_can_be_soft_or_disabled(mode, enabled) -> None:
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-1", "S1"), loading_order("LO-2", "S2")],
        vehicles=[vehicle("M1", capacity=24, compartments=3), vehicle("M2", capacity=24, compartments=3)],
        distance_matrix=[[0, 300, 300], [300, 0, 300], [300, 300, 0]],
        time_matrix=[[0, 300, 300], [300, 0, 300], [300, 300, 0]],
        day_start=DAY_START, depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(**constraint_override("vehicle_full_load", mode=mode, enabled=enabled, penalty=1000)),
    )
    assert len(result["trips"]) == 1
    violations = [row for row in result["trips"][0]["constraint_violations"] if row["constraint_id"] == "vehicle_full_load"]
    assert len(violations) == (1 if enabled else 0)
    if violations:
        assert violations[0]["penalty"] == 1000


def test_full_load_defaults_to_hard_for_existing_profiles() -> None:
    assert constraint_is_hard(effective_parameters({"constraint_rules": {"vehicle_capacity": {"enabled": True, "mode": "HARD"}}}), "vehicle_full_load")


@pytest.mark.parametrize("same_station", [True, False])
def test_historical_pairing_only_penalizes_distinct_stations(same_station):
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("PAIR-1", "S1"), loading_order("PAIR-2", "S1" if same_station else "S2")],
        vehicles=[vehicle("M1", capacity=16, compartments=2)],
        distance_matrix=[[0, 300, 300], [300, 0, 300], [300, 300, 0]],
        time_matrix=[[0, 300, 300], [300, 0, 300], [300, 300, 0]],
        day_start=DAY_START, depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(**constraint_override("historical_pairing_preference", mode="SOFT", penalty=12345)),
    )
    assert len(result["trips"]) == 1
    penalties = [v for v in result["trips"][0]["constraint_violations"] if v["constraint_id"] == "historical_pairing_preference"]
    assert sum(v["penalty"] for v in penalties) == (0 if same_station else 12345)


def test_full_load_selects_smaller_mt_instead_of_partial_preferred_mt() -> None:
    orders = [loading_order(f"LO-{index}", f"S{index}", allowed=["M1", "M2"]) for index in range(2)]
    matrix = [[0, 300, 300], [300, 0, 300], [300, 300, 0]]
    result = VRPOptimizationService().solve(
        loading_orders=orders,
        vehicles=[vehicle("M1", capacity=24, compartments=3), vehicle("M2", capacity=16, compartments=2)],
        distance_matrix=matrix, time_matrix=matrix, day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18), parameters=parameters(),
    )
    assert not result["dropped"]
    assert len(result["trips"]) == 1
    assert result["trips"][0]["vehicle_id"] == "M2"


def test_post_bay_validation_rejects_partial_trip_even_if_route_solver_returns_it() -> None:
    dropped, reasons, retryable = OptimizationCoordinatorService._post_bay_failures(
        trips=[{"vehicle_id": "M1", "trip_number": 1, "lo_assignments": [{"volume_kl": 8}, {"volume_kl": 8}]}],
        bay_result={}, vehicles=[{**vehicle("M1", capacity=24, compartments=3), "working_time_limit_minutes": 600}],
        parameters=parameters(), day_start=DAY_START,
    )
    assert dropped == retryable == {0}
    assert reasons[0][0] == "FULL_LOAD_NOT_MET"


@pytest.mark.parametrize("counts,mt_count", [([2] * 4, 4), ([1, 1, 2, 4, 4, 4, 4, 4, 4, 5, 6, 6, 7, 8, 8, 10, 10], 27)])
def test_full_load_cold_start_with_hard_historical_pairing_serves_feasible_pairs(counts, mt_count) -> None:
    # Each SPBU has two 8 KL LO. Cross-SPBU history is absent, so HARD
    # pairing allows only the same-SPBU pair to fill a 16 KL vehicle.
    # The larger case reproduced an all-dropped solution with insertion search.
    mts = [f"M{i}" for i in range(mt_count)]
    orders = [loading_order(f"LO-{s}-{i}", f"S{s}", allowed=mts, preferred=None) for s, count in enumerate(counts) for i in range(count)]
    size = len(orders) + 1
    matrix = [[0 if i == j or (i and j and orders[i - 1]["spbu_id"] == orders[j - 1]["spbu_id"]) else 80_000 for j in range(size)] for i in range(size)]
    result = VRPOptimizationService().solve(
        loading_orders=orders, vehicles=[vehicle(mt, capacity=16, compartments=2) for mt in mts],
        distance_matrix=matrix, time_matrix=matrix, day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_warm_start_source="CURRENT_ROUTE", maximum_trips_per_mt=1,
                              route_optimization_time_limit=4, objective="MIN_TOTAL_OPERATING_TIME",
                              travel_time_mode="MANUAL_SPEED", average_speed_kmh=35,
                              **constraint_override("historical_pairing_preference", mode="HARD")),
    )
    expected_trips = min(sum(count // 2 for count in counts), mt_count)
    assert len(result["trips"]) == expected_trips
    assert len(result["dropped"]) == len(orders) - 2 * expected_trips
    assert all(sum(lo["volume_kl"] for lo in trip["lo_assignments"]) == 16 for trip in result["trips"])


def test_a_phase6_warm_start_is_soft_and_can_reassign_when_preferred_mt_is_too_late() -> None:
    lo = loading_order("LO-1", "S1", allowed=["M1", "M2"], preferred="M1")
    lo.update({"time_window_start_minutes": 300, "time_window_end_minutes": 420})
    result = VRPOptimizationService().solve(
        loading_orders=[lo],
        vehicles=[vehicle("M1", eta_hour=10), vehicle("M2", eta_hour=5)],
        distance_matrix=[[0, 10_000], [10_000, 0]],
        time_matrix=[[0, 1_200], [1_200, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )
    assert result["trips"][0]["vehicle_id"] == "M2"
    assert result["trips"][0]["lo_assignments"][0]["phase6_predicted_vehicle_id"] == "M1"


def test_reroute_warm_start_uses_the_next_trip_from_the_current_route_version() -> None:
    m1 = vehicle("M1")
    m1["completed_trip_count"] = 1
    m2 = vehicle("M2")
    current_rows = [
        {
            **loading_order("LO-M1-T2-B", "S2", allowed=["M1"]),
            "current_vehicle_id": "M1",
            "current_trip_number": 2,
            "current_stop_sequence": 2,
        },
        {
            **loading_order("LO-M1-T2-A", "S1", allowed=["M1"]),
            "current_vehicle_id": "M1",
            "current_trip_number": 2,
            "current_stop_sequence": 1,
        },
        {
            **loading_order("LO-M1-T3", "S3", allowed=["M1"]),
            "current_vehicle_id": "M1",
            "current_trip_number": 3,
            "current_stop_sequence": 1,
        },
        loading_order("LO-NEW", "S4", allowed=["M1", "M2"]),
    ]

    routes, seeded_count = VRPOptimizationService._build_warm_routes(
        current_rows,
        [m1, m2],
        source="CURRENT_ROUTE",
    )

    assert routes == [[2, 1], []]
    assert seeded_count == 2

    # After Trip 2 has become completed/current, the next optimization round
    # seeds Trip 3. Newly added LO remains available to the optimizer but is
    # not falsely presented as part of the previous immutable route.
    m1["completed_trip_count"] = 2
    routes, seeded_count = VRPOptimizationService._build_warm_routes(
        current_rows,
        [m1, m2],
        source="CURRENT_ROUTE",
    )
    assert routes == [[3], []]
    assert seeded_count == 1


def test_reroute_hard_freeze_retains_current_mt_and_relative_stop_sequence() -> None:
    second_stop = {
        **loading_order("LO-SECOND", "S2", allowed=["M1", "M2"]),
        "current_vehicle_id": "M1",
        "current_trip_number": 1,
        "current_stop_sequence": 2,
        "reroute_assignment_locked": True,
    }
    first_stop = {
        **loading_order("LO-FIRST", "S1", allowed=["M1", "M2"]),
        "current_vehicle_id": "M1",
        "current_trip_number": 1,
        "current_stop_sequence": 1,
        "reroute_assignment_locked": True,
    }
    result = VRPOptimizationService().solve(
        loading_orders=[second_stop, first_stop],
        vehicles=[vehicle("M1", capacity=16, compartments=2), vehicle("M2", capacity=16, compartments=2)],
        distance_matrix=[[0, 1_000, 1_000], [1_000, 0, 1_000], [1_000, 1_000, 0]],
        time_matrix=[[0, 600, 600], [600, 0, 600], [600, 600, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_warm_start_source="CURRENT_ROUTE", route_warm_start_version_id="V1"),
    )

    assert result["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert len(result["trips"]) == 1
    assert result["trips"][0]["vehicle_id"] == "M1"
    assert [stop["loading_order"]["loading_order_id"] for stop in result["trips"][0]["stops"]] == [
        "LO-FIRST",
        "LO-SECOND",
    ]
    assert result["solver_metadata"]["route_warm_start_source"] == "CURRENT_ROUTE"
    assert result["solver_metadata"]["route_warm_start_version_id"] == "V1"


def test_b_one_compartment_one_product_rejects_mixed_product() -> None:
    result = CompartmentAssignmentService().assign(
        [
            {"loading_order_id": "LO-1", "product_id": "PERTALITE", "volume_kl": 4},
            {"loading_order_id": "LO-2", "product_id": "BIOSOLAR", "volume_kl": 4},
        ],
        [{"compartment_id": "C1", "capacity_kl": 8}],
    )
    assert result["feasible"] is False
    assert result["reason"] == "COMPARTMENT_INFEASIBLE"


def test_c_multi_trip_assigns_same_mt_again_after_return() -> None:
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-1", "S1"), loading_order("LO-2", "S2")],
        vehicles=[vehicle("M1")],
        distance_matrix=[[0, 10_000, 12_000], [10_000, 0, 5_000], [12_000, 5_000, 0]],
        time_matrix=[[0, 1_200, 1_500], [1_200, 0, 600], [1_500, 600, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(mt_turnaround_buffer_minutes=25),
    )
    assert [trip["trip_number"] for trip in result["trips"]] == [1, 2]
    assert result["trips"][1]["vehicle_ready_at_depot"] == (
        result["trips"][0]["estimated_return_depot"] + timedelta(minutes=25)
    )


def test_d_vehicle_availability_prevents_early_departure() -> None:
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-1", "S1")],
        vehicles=[vehicle("M1", eta_hour=10)],
        distance_matrix=[[0, 10_000], [10_000, 0]],
        time_matrix=[[0, 1_200], [1_200, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )
    assert result["trips"][0]["gate_out"] >= DAY_START + timedelta(hours=10)


def test_depot_window_limits_dispatch_but_allows_return_after_close() -> None:
    mt = vehicle("M1", eta_hour=17)
    mt["effective_eta_depot"] = DAY_START + timedelta(hours=17, minutes=30)
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-1", "S1")],
        vehicles=[mt],
        distance_matrix=[[0, 10_000], [10_000, 0]],
        # The MT can reach the SPBU before close, but the long return leg ends
        # after depot operating hours.
        time_matrix=[[0, 15 * 60], [90 * 60, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )

    assert len(result["trips"]) == 1
    assert result["trips"][0]["gate_out"] <= DAY_START + timedelta(hours=18)
    assert result["trips"][0]["estimated_return_depot"] > DAY_START + timedelta(hours=18)
    assert not any(
        violation["constraint_id"] == "depot_operating_window"
        for violation in result["trips"][0]["constraint_violations"]
    )


def test_vehicle_availability_can_be_soft_or_disabled() -> None:
    lo = loading_order("LO-1", "S1")
    lo.update({"time_window_start_minutes": 0, "time_window_end_minutes": 120})
    common = {
        "loading_orders": [lo],
        "vehicles": [vehicle("M1", eta_hour=10)],
        "distance_matrix": [[0, 10_000], [10_000, 0]],
        "time_matrix": [[0, 1_200], [1_200, 0]],
        "day_start": DAY_START,
        "depot_close": DAY_START + timedelta(hours=18),
    }
    soft = VRPOptimizationService().solve(
        **common,
        parameters=parameters(**constraint_override("vehicle_availability", mode="SOFT", penalty=1_000)),
    )
    assert soft["trips"][0]["vehicle_ready_at_depot"] < DAY_START + timedelta(hours=10)
    assert any(row["constraint_id"] == "vehicle_availability" for row in soft["trips"][0]["constraint_violations"])
    disabled = VRPOptimizationService().solve(
        **common,
        parameters=parameters(**constraint_override("vehicle_availability", enabled=False, penalty=1_000)),
    )
    assert disabled["trips"][0]["vehicle_ready_at_depot"] < DAY_START + timedelta(hours=10)
    assert not any(row["constraint_id"] == "vehicle_availability" for row in disabled["trips"][0]["constraint_violations"])


def test_vehicle_capacity_can_be_soft_or_disabled() -> None:
    overloaded_vehicle = vehicle("M1", capacity=8)
    overloaded_vehicle["compartments"] = [
        {"compartment_id": "C1", "capacity_kl": 8},
        {"compartment_id": "C2", "capacity_kl": 8},
    ]
    common = {
        "loading_orders": [loading_order("LO-1", "S1"), loading_order("LO-2", "S2")],
        "vehicles": [overloaded_vehicle],
        "distance_matrix": [[0, 10_000, 12_000], [10_000, 0, 5_000], [12_000, 5_000, 0]],
        "time_matrix": [[0, 1_200, 1_500], [1_200, 0, 600], [1_500, 600, 0]],
        "day_start": DAY_START,
        "depot_close": DAY_START + timedelta(hours=18),
    }
    soft = VRPOptimizationService().solve(
        **common,
        parameters=parameters(maximum_trips_per_mt=1, constraint_rules={"vehicle_capacity": {"mode": "SOFT", "penalty": 1000}, "vehicle_full_load": {"enabled": False}}),
    )
    assert len(soft["trips"][0]["lo_assignments"]) == 2
    assert any(row["constraint_id"] == "vehicle_capacity" for row in soft["trips"][0]["constraint_violations"])
    disabled = VRPOptimizationService().solve(
        **common,
        parameters=parameters(maximum_trips_per_mt=1, constraint_rules={"vehicle_capacity": {"enabled": False}, "vehicle_full_load": {"enabled": False}}),
    )
    assert len(disabled["trips"][0]["lo_assignments"]) == 2
    assert not any(row["constraint_id"] == "vehicle_capacity" for row in disabled["trips"][0]["constraint_violations"])


def lo_state(lo_id: str, *, status: str, gate_out: datetime | None = None) -> LOOperationalState:
    return LOOperationalState(
        lo_state_id=lo_id,
        job_id="JOB-1",
        loading_order_id=lo_id,
        spbu_id="S1",
        volume_kl=8,
        depot_id="D1",
        operating_date=date(2026, 8, 26),
        source_prediction_run_id="P6-1",
        status=status,
        planned_gate_out=gate_out,
    )


def test_e_freeze_window_locks_near_term_planned_lo() -> None:
    now = DAY_START + timedelta(hours=5)
    row = lo_state("LO-1", status="PLANNED", gate_out=now + timedelta(minutes=59))
    apply_freeze_rules([row], current_time=now, freeze_window_minutes=60)
    assert row.frozen is True
    assert row.frozen_reason == "FREEZE_WINDOW"


def test_f_ongoing_lo_is_frozen() -> None:
    row = lo_state("LO-1", status="ONGOING")
    apply_freeze_rules([row], current_time=DAY_START, freeze_window_minutes=60)
    assert row.frozen is True
    assert row.frozen_reason == "ONGOING"


def test_g_done_lo_is_permanently_excluded_from_reoptimizable_set() -> None:
    row = lo_state("LO-1", status="DONE")
    rows = apply_freeze_rules([row], current_time=DAY_START, freeze_window_minutes=60)
    reoptimizable = [item for item in rows if item.status == "PLANNED" and not item.frozen]
    assert row.frozen is True
    assert reoptimizable == []


def test_reroute_inputs_lock_early_mt_release_late_mt_and_copy_only_executed_trip() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        db.add(
            MasterDepot(
                depot_id="D1",
                depot_name="Depot",
                timezone="UTC",
                depot_operational_start=time(0),
                depot_operational_end=time(23, 59),
            )
        )
        db.add(
            MasterSPBU(
                spbu_id="S1",
                spbu_code="S1",
                spbu_name="SPBU",
                primary_depot_id="D1",
                vehicle_type_tag=8,
                official_window_start=time(0),
                official_window_end=time(23, 59),
            )
        )
        for mt_id in ("MT-EARLY", "MT-LATE", "MT-ONGOING"):
            db.add(
                MasterMT(
                    mt_id=mt_id,
                    vehicle_name_raw=mt_id,
                    vehicle_registration=mt_id,
                    depot_id="D1",
                    vehicle_type_tag=8,
                    number_of_compartments=1,
                )
            )
        job = OptimizationJob(
            job_id="JOB-1",
            job_no="P7-JOB-1",
            job_name="Reroute",
            depot_id="D1",
            operating_date=date(2026, 8, 26),
            current_route_version_id="V1",
            depot_operational_start=time(0),
            depot_operational_end=time(23, 59),
        )
        db.add(job)
        db.flush()

        vehicle_eta = {
            "MT-EARLY": DAY_START + timedelta(hours=6, minutes=30),
            "MT-LATE": DAY_START + timedelta(hours=8),
            "MT-ONGOING": DAY_START + timedelta(hours=9),
        }
        for mt_id, eta in vehicle_eta.items():
            db.add(
                VehicleOperationalState(
                    vehicle_state_id=f"VS-{mt_id}",
                    job_id=job.job_id,
                    mt_id=mt_id,
                    registration_snapshot=mt_id,
                    vehicle_class=8,
                    capacity_kl=8,
                    number_of_compartments=1,
                    compartment_configuration=[{"compartment_id": "C1", "capacity_kl": 8}],
                    planned_eta_depot=eta,
                    effective_eta_depot=eta,
                    operational_status="READY",
                )
            )

        lo_specs = [
            ("LO-EARLY", "MT-EARLY", "PLANNED", DAY_START + timedelta(hours=7)),
            ("LO-LATE", "MT-LATE", "PLANNED", DAY_START + timedelta(hours=7)),
            ("LO-ONGOING", "MT-ONGOING", "ONGOING", DAY_START + timedelta(hours=5)),
        ]
        for index, (lo_id, mt_id, status, gate_out) in enumerate(lo_specs, start=1):
            trip_id = f"TRIP-{lo_id}"
            db.add(
                LOOperationalState(
                    lo_state_id=f"STATE-{lo_id}",
                    job_id=job.job_id,
                    loading_order_id=lo_id,
                    spbu_id="S1",
                    spbu_name_snapshot="SPBU",
                    volume_kl=8,
                    depot_id="D1",
                    operating_date=job.operating_date,
                    source_prediction_run_id="P6-1",
                    phase6_predicted_vehicle_id=mt_id,
                    current_vehicle_id=mt_id,
                    current_trip_number=1,
                    current_shipment_id=f"SHIP-{index}",
                    planned_gate_out=gate_out,
                    status=status,
                )
            )
            db.add(
                RouteVersionTrip(
                    route_version_trip_id=trip_id,
                    route_version_id="V1",
                    vehicle_id=mt_id,
                    trip_number=1,
                    shipment_id=f"SHIP-{index}",
                    vehicle_ready_at_depot=gate_out - timedelta(minutes=20),
                    queue_start=gate_out - timedelta(minutes=20),
                    loading_start=gate_out - timedelta(minutes=15),
                    loading_finish=gate_out - timedelta(minutes=5),
                    gate_out=gate_out,
                    estimated_return_depot=gate_out + timedelta(hours=1),
                    operating_minutes=80,
                )
            )
            db.add(
                RouteVersionLOAssignment(
                    route_version_lo_assignment_id=f"ASSIGN-{lo_id}",
                    route_version_id="V1",
                    route_version_trip_id=trip_id,
                    loading_order_id=lo_id,
                    vehicle_id=mt_id,
                    trip_number=1,
                    shipment_id=f"SHIP-{index}",
                    spbu_id="S1",
                    volume_kl=8,
                    stop_sequence=1,
                )
            )
        db.commit()

        inputs = phase7_service._solver_inputs(
            db,
            job,
            parameters(freeze_window_minutes=60, departure_time_tolerance_minutes=5),
            current_time=DAY_START + timedelta(hours=6),
            reroute=True,
        )

        payload_by_lo = {row["loading_order_id"]: row for row in inputs["loading_orders"]}
        assert inputs["route_warm_start_source"] == "CURRENT_ROUTE"
        assert inputs["route_warm_start_version_id"] == "V1"
        assert inputs["copy_frozen_loading_order_ids"] == ["LO-ONGOING"]
        assert payload_by_lo["LO-EARLY"]["reroute_assignment_locked"] is True
        assert payload_by_lo["LO-EARLY"]["reroute_release_reason"] is None
        assert payload_by_lo["LO-EARLY"]["allowed_vehicle_ids"] == ["MT-EARLY"]
        assert payload_by_lo["LO-LATE"]["reroute_assignment_locked"] is False
        assert payload_by_lo["LO-LATE"]["reroute_release_reason"] == "MT_LATE"
        assert set(payload_by_lo["LO-LATE"]["allowed_vehicle_ids"]) == {
            "MT-EARLY",
            "MT-LATE",
            "MT-ONGOING",
        }
        completed_by_mt = {row["mt_id"]: row["completed_trip_count"] for row in inputs["vehicles"]}
        assert completed_by_mt == {"MT-EARLY": 0, "MT-LATE": 0, "MT-ONGOING": 1}
        working_by_mt = {
            row["mt_id"]: (row["working_time_used_minutes"], row["working_time_remaining_minutes"])
            for row in inputs["vehicles"]
        }
        assert working_by_mt == {
            "MT-EARLY": (0, 720),
            "MT-LATE": (0, 720),
            # The current trip started at 04:40 and dispatcher ETA is 09:00.
            "MT-ONGOING": (260, 460),
        }


def test_h_bay_product_compatibility_is_hard() -> None:
    trip = {
        "vehicle_ready_at_depot": DAY_START + timedelta(hours=5),
        "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "BIOSOLAR", "volume_kl": 8}],
    }
    result = BayQueueOptimizationService().schedule(
        trips=[trip],
        bays=[{"master_bay_id": "B1", "all_products_allowed": False, "allowed_product_ids": ["PERTALITE"], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        actual_states=[],
        initial_queue=[],
        loading_durations={"BIOSOLAR": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )
    assert result["dropped_trip_indexes"] == [0]


def test_bay_product_compatibility_can_be_soft_or_disabled() -> None:
    trip = {
        "vehicle_ready_at_depot": DAY_START + timedelta(hours=5),
        "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "BIOSOLAR", "volume_kl": 8}],
    }
    common = {
        "trips": [trip],
        "bays": [{"master_bay_id": "B1", "all_products_allowed": False, "allowed_product_ids": ["PERTALITE"], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        "actual_states": [],
        "initial_queue": [],
        "loading_durations": {"BIOSOLAR": 10},
        "day_start": DAY_START,
        "depot_close": DAY_START + timedelta(hours=18),
    }
    soft = BayQueueOptimizationService().schedule(
        **common,
        parameters=parameters(**constraint_override("bay_product_compatibility", mode="SOFT", penalty=654_000)),
    )
    assert soft["dropped_trip_indexes"] == []
    assert any(row["constraint_id"] == "bay_product_compatibility" for row in soft["assignments"][0]["constraint_violations"])
    disabled = BayQueueOptimizationService().schedule(
        **common,
        parameters=parameters(**constraint_override("bay_product_compatibility", enabled=False, penalty=654_000)),
    )
    assert disabled["dropped_trip_indexes"] == []
    assert disabled["assignments"][0]["constraint_violations"] == []


def test_fifo_balanced_distributes_identical_ready_trips_across_all_product_bays() -> None:
    trips = [
        {
            "vehicle_id": f"MT-{index:03d}",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "lo_assignments": [{
                "loading_order_id": f"LO-{index:03d}",
                "compartment_id": "C1",
                "product_id": "P1",
                "volume_kl": 8,
            }],
        }
        for index in range(100)
    ]
    bays = [
        {
            "master_bay_id": f"BAY-{index}",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 24 * 60 - 1,
        }
        for index in range(1, 7)
    ]

    result = BayQueueOptimizationService().schedule(
        trips=trips,
        bays=bays,
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=23, minutes=59),
        parameters=parameters(),
    )

    assignments_per_bay = {
        bay["master_bay_id"]: sum(
            row["master_bay_id"] == bay["master_bay_id"] for row in result["assignments"]
        )
        for bay in bays
    }
    assert result["solver_status"] == "FEASIBLE"
    assert result["engine"] == "FIFO_BALANCED"
    assert len(result["assignments"]) == 100
    assert max(assignments_per_bay.values()) - min(assignments_per_bay.values()) <= 1
    assert result["scheduler_metadata"]["candidate_evaluation_count"] == 600


def test_fifo_balanced_prefers_product_specific_bay_before_flexible_bay() -> None:
    trips = [
        {
            "vehicle_id": "MT-P1",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "lo_assignments": [{"loading_order_id": "LO-P1", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        },
        {
            "vehicle_id": "MT-P2",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "lo_assignments": [{"loading_order_id": "LO-P2", "compartment_id": "C1", "product_id": "P2", "volume_kl": 8}],
        },
    ]
    bays = [
        {"master_bay_id": "BAY-P1", "all_products_allowed": False, "allowed_product_ids": ["P1"], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"},
        {"master_bay_id": "BAY-P2", "all_products_allowed": False, "allowed_product_ids": ["P2"], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"},
        {"master_bay_id": "BAY-ALL", "all_products_allowed": True, "allowed_product_ids": [], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"},
    ]

    result = BayQueueOptimizationService().schedule(
        trips=trips,
        bays=bays,
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10, "P2": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )

    selected_by_trip = {row["trip_index"]: row["master_bay_id"] for row in result["assignments"]}
    assert selected_by_trip == {0: "BAY-P1", 1: "BAY-P2"}


def test_fifo_balanced_propagates_actual_return_before_same_mt_next_trip() -> None:
    trips = [
        {
            "vehicle_id": "MT-1",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "gate_out": DAY_START,
            "estimated_return_depot": DAY_START + timedelta(minutes=60),
            "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        },
        {
            "vehicle_id": "MT-1",
            "trip_number": 2,
            "vehicle_ready_at_depot": DAY_START,
            "gate_out": DAY_START,
            "estimated_return_depot": DAY_START + timedelta(minutes=60),
            "lo_assignments": [{"loading_order_id": "LO-2", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        },
    ]

    result = BayQueueOptimizationService().schedule(
        trips=trips,
        bays=[{"master_bay_id": "BAY-1", "all_products_allowed": True, "allowed_product_ids": [], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(gate_process_time=5, mt_turnaround_buffer_minutes=20),
    )

    first, second = result["assignments"]
    assert first["gate_out"] == DAY_START + timedelta(minutes=15)
    assert second["vehicle_ready_at_depot"] == DAY_START + timedelta(minutes=95)
    assert second["loading_start"] == DAY_START + timedelta(minutes=95)


def test_cp_sat_bay_scheduler_remains_available_as_explicit_strategy() -> None:
    result = BayQueueOptimizationService().schedule(
        trips=[{
            "vehicle_id": "MT-1",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        }],
        bays=[{"master_bay_id": "BAY-1", "all_products_allowed": True, "allowed_product_ids": [], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(bay_scheduler_strategy="CP_SAT", bay_cp_sat_workers=3),
    )

    assert result["engine"] == "OR_TOOLS_CP_SAT"
    assert result["num_search_workers"] == 3


def test_fifo_bay_scheduler_keeps_feasible_subset_and_labels_exhausted_window() -> None:
    trips = [
        {
            "vehicle_id": f"MT-{index}",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "lo_assignments": [{"loading_order_id": f"LO-{index}", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        }
        for index in (1, 2)
    ]
    result = BayQueueOptimizationService().schedule(
        trips=trips,
        bays=[{
            "master_bay_id": "B1",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 15,
        }],
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )

    assert result["solver_status"] == "PARTIAL"
    assert len(result["assignments"]) == 1
    assert len(result["dropped_trip_indexes"]) == 1
    dropped_index = result["dropped_trip_indexes"][0]
    assert result["dropped_trip_reasons"][dropped_index] == "BAY_WINDOW_EXHAUSTED"
    assert result["engine"] == "FIFO_BALANCED"
    assert result["num_search_workers"] == 0
    assert result["time_limit_reached"] is False


def test_soft_bay_service_drops_only_later_trip_ready_after_depot_close() -> None:
    trips = [
        {
            "vehicle_id": "MT-1",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START + timedelta(hours=17),
            "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        },
        {
            "vehicle_id": "MT-1",
            "trip_number": 2,
            "vehicle_ready_at_depot": DAY_START + timedelta(hours=19),
            "lo_assignments": [{"loading_order_id": "LO-2", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        },
    ]
    result = BayQueueOptimizationService().schedule(
        trips=trips,
        bays=[{
            "master_bay_id": "B1",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 18 * 60,
        }],
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )

    assert result["solver_status"] == "PARTIAL"
    assert [row["trip_index"] for row in result["assignments"]] == [0]
    assert result["dropped_trip_indexes"] == [1]
    assert result["dropped_trip_reasons"] == {1: "BAY_WINDOW_EXHAUSTED"}


def test_hard_serve_loading_order_keeps_all_or_reports_infeasible() -> None:
    trips = [
        {
            "vehicle_id": f"MT-{index}",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "lo_assignments": [{"loading_order_id": f"LO-{index}", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        }
        for index in (1, 2)
    ]
    result = BayQueueOptimizationService().schedule(
        trips=trips,
        bays=[{
            "master_bay_id": "B1",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 15,
        }],
        actual_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(**constraint_override("serve_loading_order", mode="HARD")),
    )

    assert result["solver_status"] == "INFEASIBLE"
    assert result["assignments"] == []
    assert result["dropped_trip_indexes"] == [0, 1]
    assert set(result["dropped_trip_reasons"].values()) == {"BAY_WINDOW_EXHAUSTED"}


def test_coordinator_persists_partial_bay_window_exhaustion_instead_of_product_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    trips = [
        {
            "vehicle_id": f"MT-{index}",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "gate_out": DAY_START,
            "estimated_return_depot": DAY_START + timedelta(hours=1),
            "operating_minutes": 60,
            "constraint_violations": [],
            "constraint_penalty_cost": 0,
            "lo_assignments": [{"loading_order_id": f"LO-{index}", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        }
        for index in (1, 2)
    ]
    coordinator = OptimizationCoordinatorService()
    monkeypatch.setattr(coordinator.vrp, "solve", lambda **_kwargs: {
        "solver_status": "FEASIBLE",
        "objective_value": 0,
        "trips": trips,
        "dropped": [],
        "vehicle_state": [],
        "solver_metadata": {},
    })
    result = coordinator.optimize(
        loading_orders=[],
        vehicles=[
            {"mt_id": "MT-1", "working_time_limit_minutes": 600, "working_time_used_minutes": 0, "capacity_kl": 8},
            {"mt_id": "MT-2", "working_time_limit_minutes": 600, "working_time_used_minutes": 0, "capacity_kl": 8},
        ],
        distance_matrix=[[0]],
        time_matrix=[[0]],
        bays=[{
            "master_bay_id": "B1",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 15,
        }],
        actual_bay_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(max_coordination_iterations=1),
    )

    assert result["solver_status"] == "PARTIAL"
    assert len(result["trips"]) == 1
    assert len(result["dropped"]) == 1
    assert result["dropped"][0]["reason_code"] == "BAY_WINDOW_EXHAUSTED"
    assert result["solver_metadata"]["bay_served_trip_count"] == 1
    assert result["solver_metadata"]["bay_dropped_trip_count"] == 1
    assert result["solver_metadata"]["bay_scheduler_strategy"] == "FIFO_BALANCED"


def test_coordinator_keeps_trip_that_gates_out_before_close_and_returns_after(monkeypatch: pytest.MonkeyPatch) -> None:
    trip = {
        "vehicle_id": "MT-1",
        "trip_number": 1,
        "vehicle_ready_at_depot": DAY_START + timedelta(hours=17, minutes=40),
        "preliminary_gate_out": DAY_START + timedelta(hours=17, minutes=40),
        "gate_out": DAY_START + timedelta(hours=17, minutes=40),
        "estimated_return_depot": DAY_START + timedelta(hours=18, minutes=40),
        "distance_meters": 10_000,
        "driving_seconds": 3_600,
        "service_seconds": 0,
        "operating_minutes": 60,
        "stops": [],
        "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}],
        "constraint_violations": [],
        "constraint_penalty_cost": 0,
    }
    coordinator = OptimizationCoordinatorService()
    monkeypatch.setattr(coordinator.vrp, "solve", lambda **_kwargs: {
        "solver_status": "FEASIBLE",
        "objective_value": 0,
        "trips": [trip],
        "dropped": [],
        "vehicle_state": [],
        "solver_metadata": {},
    })

    result = coordinator.optimize(
        loading_orders=[],
        vehicles=[{"mt_id": "MT-1", "working_time_limit_minutes": 600, "working_time_used_minutes": 0, "capacity_kl": 8}],
        distance_matrix=[[0]],
        time_matrix=[[0]],
        bays=[{
            "master_bay_id": "B1",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 18 * 60,
        }],
        actual_bay_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )

    assert result["solver_status"] == "FEASIBLE"
    assert len(result["trips"]) == 1
    assert result["trips"][0]["gate_out"] <= DAY_START + timedelta(hours=18)
    assert result["trips"][0]["estimated_return_depot"] > DAY_START + timedelta(hours=18)
    assert result["dropped"] == []


@pytest.mark.parametrize("consume_initial_budget", [False, True])
def test_coordinator_reassigns_post_bay_working_failure_using_actual_retained_state(
    monkeypatch: pytest.MonkeyPatch,
    consume_initial_budget: bool,
) -> None:
    failed_lo = {
        "loading_order_id": "LO-RETRY",
        "spbu_id": "SPBU-1",
        "product_id": "P1",
        "volume_kl": 8,
        "allowed_vehicle_ids": ["MT-1", "MT-2"],
    }
    retained_lo = {
        "loading_order_id": "LO-RETAINED",
        "spbu_id": "SPBU-2",
        "product_id": "P1",
        "volume_kl": 8,
        "allowed_vehicle_ids": ["MT-2"],
    }
    initial_trips = [
        {
            "vehicle_id": "MT-1",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "gate_out": DAY_START,
            "estimated_return_depot": DAY_START + timedelta(minutes=60),
            "operating_minutes": 60,
            "constraint_violations": [],
            "constraint_penalty_cost": 0,
            "lo_assignments": [{**failed_lo, "compartment_id": "C1"}],
        },
        {
            "vehicle_id": "MT-2",
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "gate_out": DAY_START,
            "estimated_return_depot": DAY_START + timedelta(minutes=30),
            "operating_minutes": 30,
            "constraint_violations": [],
            "constraint_penalty_cost": 0,
            "lo_assignments": [{**retained_lo, "compartment_id": "C1"}],
        },
    ]
    retried_trip = {
        "vehicle_id": "MT-2",
        "trip_number": 2,
        "vehicle_ready_at_depot": DAY_START + timedelta(minutes=40),
        "gate_out": DAY_START + timedelta(minutes=40),
        "estimated_return_depot": DAY_START + timedelta(minutes=90),
        "operating_minutes": 50,
        "constraint_violations": [],
        "constraint_penalty_cost": 0,
        "lo_assignments": [{**failed_lo, "allowed_vehicle_ids": ["MT-2"], "compartment_id": "C1"}],
    }
    coordinator = OptimizationCoordinatorService()
    solve_calls = 0

    def fake_solve(**kwargs: object) -> dict:
        nonlocal solve_calls
        solve_calls += 1
        if solve_calls == 1:
            return {
                "solver_status": "FEASIBLE",
                "objective_value": 100,
                "trips": initial_trips,
                "dropped": [],
                "vehicle_state": [],
                "solver_metadata": {},
            }
        assert [row["loading_order_id"] for row in kwargs["loading_orders"]] == ["LO-RETRY"]  # type: ignore[index]
        assert kwargs["loading_orders"][0]["allowed_vehicle_ids"] == ["MT-2"]  # type: ignore[index]
        retry_vehicle = next(row for row in kwargs["vehicles"] if row["mt_id"] == "MT-2")  # type: ignore[index]
        assert retry_vehicle["working_time_used_minutes"] == 40
        assert retry_vehicle["working_time_remaining_minutes"] == 60
        assert retry_vehicle["effective_eta_depot"] == DAY_START + timedelta(minutes=40)
        return {
            "solver_status": "FEASIBLE",
            "objective_value": 50,
            "trips": [retried_trip],
            "dropped": [],
            "vehicle_state": [],
            "solver_metadata": {},
        }

    bay_calls = 0

    def fake_bay_schedule(**kwargs: object) -> dict:
        nonlocal bay_calls
        bay_calls += 1
        assignments = []
        for index, trip in enumerate(kwargs["trips"]):  # type: ignore[index]
            shift = timedelta(0)
            if bay_calls == 1:
                shift = timedelta(minutes=20 if trip["vehicle_id"] == "MT-1" else 10)
            gate_out = trip["gate_out"] + shift
            assignments.append({
                "trip_index": index,
                "master_bay_id": "B1",
                "vehicle_ready_at_depot": trip["vehicle_ready_at_depot"],
                "queue_start": trip["vehicle_ready_at_depot"],
                "loading_start": gate_out - timedelta(minutes=5),
                "loading_finish": gate_out,
                "gate_out": gate_out,
                "queue_minutes": 0,
                "loading_minutes": 5,
                "constraint_violations": [],
            })
        return {
            "solver_status": "FEASIBLE",
            "raw_solver_status": "OPTIMAL",
            "assignments": assignments,
            "dropped_trip_indexes": [],
            "dropped_trip_reasons": {},
            "engine": "TEST_BAY",
            "num_search_workers": 1,
            "time_limit_reached": False,
        }

    monkeypatch.setattr(coordinator.vrp, "solve", fake_solve)
    monkeypatch.setattr(coordinator.bay, "schedule", fake_bay_schedule)
    if consume_initial_budget:
        real_counter = phase7_optimization.perf_counter
        clock_offset = [0.0]
        monkeypatch.setattr(phase7_optimization, "perf_counter", lambda: real_counter() + clock_offset[0])
        original_schedule = coordinator._schedule_bays
        schedule_calls = []

        def consume_schedule_budget(**kwargs: object) -> tuple:
            schedule_calls.append(kwargs["deadline"])
            answer = original_schedule(**kwargs)
            if len(schedule_calls) == 1:
                # Reproduce CP-SAT returning FEASIBLE at the initial deadline.
                clock_offset[0] = max(0, kwargs["deadline"] - real_counter())
            return answer

        monkeypatch.setattr(coordinator, "_schedule_bays", consume_schedule_budget)
    result = coordinator.optimize(
        loading_orders=[failed_lo, retained_lo],
        vehicles=[
            {"mt_id": "MT-1", "working_time_limit_minutes": 70, "working_time_used_minutes": 0, "capacity_kl": 8},
            {"mt_id": "MT-2", "working_time_limit_minutes": 100, "working_time_used_minutes": 0, "capacity_kl": 8},
        ],
        distance_matrix=[[0, 1, 1], [1, 0, 1], [1, 1, 0]],
        time_matrix=[[0, 60, 60], [60, 0, 60], [60, 60, 0]],
        bays=[],
        actual_bay_states=[],
        initial_queue=[],
        loading_durations={"P1": 5},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(max_coordination_iterations=1),
    )

    assert solve_calls == 2
    assert result["solver_status"] == "FEASIBLE"
    assert result["dropped"] == []
    assert {(trip["vehicle_id"], trip["trip_number"]) for trip in result["trips"]} == {
        ("MT-2", 1),
        ("MT-2", 2),
    }
    assert result["solver_metadata"]["post_bay_reassignment_attempts"] == 1
    assert result["solver_metadata"]["post_bay_reassigned_lo_count"] == 1
    assert result["solver_metadata"]["post_bay_reassignment_exhausted_lo_count"] == 0
    if consume_initial_budget:
        assert len(schedule_calls) == 2
        assert schedule_calls[1] > schedule_calls[0]
        assert result["solver_metadata"]["post_bay_reserved_time_seconds"] > 0


@pytest.mark.parametrize("repair_capacity", [8, 24])
def test_coordinator_reassigns_bay_window_failure_to_unused_compatible_mt(
    monkeypatch: pytest.MonkeyPatch,
    repair_capacity: int,
) -> None:
    loading_order = {
        "loading_order_id": "LO-BAY-RETRY",
        "spbu_id": "SPBU-1",
        "product_id": "P1",
        "volume_kl": 8,
        "allowed_vehicle_ids": ["MT-LATE", "MT-UNUSED"],
    }
    late_trip = {
        "vehicle_id": "MT-LATE",
        "trip_number": 1,
        "vehicle_ready_at_depot": DAY_START + timedelta(hours=17, minutes=50),
        "preliminary_gate_out": DAY_START + timedelta(hours=17, minutes=50),
        "gate_out": DAY_START + timedelta(hours=17, minutes=50),
        "estimated_return_depot": DAY_START + timedelta(hours=19),
        "operating_minutes": 70,
        "constraint_violations": [],
        "constraint_penalty_cost": 0,
        "lo_assignments": [{**loading_order, "compartment_id": "C1"}],
    }
    repaired_trip = {
        "vehicle_id": "MT-UNUSED",
        "trip_number": 1,
        "vehicle_ready_at_depot": DAY_START,
        "preliminary_gate_out": DAY_START,
        "gate_out": DAY_START,
        "estimated_return_depot": DAY_START + timedelta(minutes=70),
        "operating_minutes": 70,
        "constraint_violations": [],
        "constraint_penalty_cost": 0,
        "lo_assignments": [{**loading_order, "allowed_vehicle_ids": ["MT-UNUSED"], "compartment_id": "C1"}],
    }
    coordinator = OptimizationCoordinatorService()
    solve_calls = 0

    def fake_solve(**kwargs: object) -> dict:
        nonlocal solve_calls
        solve_calls += 1
        trips = [late_trip] if solve_calls == 1 else [repaired_trip]
        if solve_calls == 2:
            assert [row["mt_id"] for row in kwargs["vehicles"]] == ["MT-UNUSED"]  # type: ignore[index]
        return {
            "solver_status": "FEASIBLE",
            "objective_value": 0,
            "trips": trips,
            "dropped": [],
            "vehicle_state": [],
            "solver_metadata": {},
        }

    monkeypatch.setattr(coordinator.vrp, "solve", fake_solve)
    vehicle_defaults = {
        "capacity_kl": 8,
        "compartments": [{"compartment_id": "C1", "capacity_kl": 8}],
        "working_time_limit_minutes": 600,
        "working_time_used_minutes": 0,
        "working_time_remaining_minutes": 600,
        "completed_trip_count": 0,
        "operational_status": "READY",
    }
    result = coordinator.optimize(
        loading_orders=[loading_order],
        vehicles=[
            {**vehicle_defaults, "mt_id": "MT-LATE", "effective_eta_depot": DAY_START + timedelta(hours=17, minutes=50)},
            {**vehicle_defaults, "mt_id": "MT-UNUSED", "capacity_kl": repair_capacity, "effective_eta_depot": DAY_START},
        ],
        distance_matrix=[[0, 1], [1, 0]],
        time_matrix=[[0, 60], [60, 0]],
        bays=[{
            "master_bay_id": "B1",
            "all_products_allowed": True,
            "allowed_product_ids": [],
            "number_of_loading_arms": 1,
            "loading_mode": "SEQUENTIAL",
            "operational_start_minutes": 0,
            "operational_end_minutes": 18 * 60,
        }],
        actual_bay_states=[],
        initial_queue=[],
        loading_durations={"P1": 10},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_optimization_time_limit=10, bay_optimization_time_limit=10),
    )

    if repair_capacity == 24:
        assert solve_calls == 1  # Reject partial-load repair before calling the solver.
        assert result["trips"] == []
        assert result["dropped"][0]["reason_code"] == "FULL_LOAD_NOT_MET"
        assert result["solver_metadata"]["post_bay_candidate_audit"][-1]["reason_code"] == "FULL_LOAD_NOT_MET"
        return
    assert solve_calls == 2
    assert result["solver_status"] == "FEASIBLE"
    assert result["dropped"] == []
    assert result["trips"][0]["vehicle_id"] == "MT-UNUSED"
    assert result["solver_metadata"]["post_bay_reassigned_lo_count"] == 1
    assert result["solver_metadata"]["post_bay_candidate_audit"][-1]["status"] == "ACCEPTED"
    assert result["solver_metadata"]["post_bay_candidate_audit"][-1]["candidate_mt_id"] == "MT-UNUSED"


def test_coordinator_drops_post_bay_lo_only_after_all_alternative_mt_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loading_order = {
        "loading_order_id": "LO-EXHAUST",
        "spbu_id": "SPBU-1",
        "product_id": "P1",
        "volume_kl": 8,
        "allowed_vehicle_ids": ["MT-1", "MT-2"],
    }

    def trip_for(vehicle_id: str, allowed_vehicle_ids: list[str]) -> dict:
        return {
            "vehicle_id": vehicle_id,
            "trip_number": 1,
            "vehicle_ready_at_depot": DAY_START,
            "gate_out": DAY_START,
            "estimated_return_depot": DAY_START + timedelta(minutes=60),
            "operating_minutes": 60,
            "constraint_violations": [],
            "constraint_penalty_cost": 0,
            "lo_assignments": [{
                **loading_order,
                "allowed_vehicle_ids": allowed_vehicle_ids,
                "compartment_id": "C1",
            }],
        }

    coordinator = OptimizationCoordinatorService()
    solve_calls = 0

    def fake_solve(**kwargs: object) -> dict:
        nonlocal solve_calls
        solve_calls += 1
        vehicle_id = "MT-1" if solve_calls == 1 else "MT-2"
        allowed = ["MT-1", "MT-2"] if solve_calls == 1 else ["MT-2"]
        if solve_calls == 2:
            assert kwargs["loading_orders"][0]["allowed_vehicle_ids"] == ["MT-2"]  # type: ignore[index]
        return {
            "solver_status": "FEASIBLE",
            "objective_value": 0,
            "trips": [trip_for(vehicle_id, allowed)],
            "dropped": [],
            "vehicle_state": [],
            "solver_metadata": {},
        }

    def fake_bay_schedule(**kwargs: object) -> dict:
        trip = kwargs["trips"][0]  # type: ignore[index]
        gate_out = trip["gate_out"] + timedelta(minutes=20)
        return {
            "solver_status": "FEASIBLE",
            "raw_solver_status": "OPTIMAL",
            "assignments": [{
                "trip_index": 0,
                "master_bay_id": "B1",
                "vehicle_ready_at_depot": trip["vehicle_ready_at_depot"],
                "queue_start": trip["vehicle_ready_at_depot"],
                "loading_start": gate_out - timedelta(minutes=5),
                "loading_finish": gate_out,
                "gate_out": gate_out,
                "queue_minutes": 0,
                "loading_minutes": 5,
                "constraint_violations": [],
            }],
            "dropped_trip_indexes": [],
            "dropped_trip_reasons": {},
            "engine": "TEST_BAY",
            "num_search_workers": 1,
            "time_limit_reached": False,
        }

    monkeypatch.setattr(coordinator.vrp, "solve", fake_solve)
    monkeypatch.setattr(coordinator.bay, "schedule", fake_bay_schedule)
    result = coordinator.optimize(
        loading_orders=[loading_order],
        vehicles=[
            {"mt_id": "MT-1", "working_time_limit_minutes": 70, "working_time_used_minutes": 0, "capacity_kl": 8},
            {"mt_id": "MT-2", "working_time_limit_minutes": 70, "working_time_used_minutes": 0, "capacity_kl": 8},
        ],
        distance_matrix=[[0, 1], [1, 0]],
        time_matrix=[[0, 60], [60, 0]],
        bays=[],
        actual_bay_states=[],
        initial_queue=[],
        loading_durations={"P1": 5},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(max_coordination_iterations=1),
    )

    assert solve_calls == 2
    assert result["trips"] == []
    assert result["solver_status"] == "INFEASIBLE"
    assert len(result["dropped"]) == 1
    assert result["dropped"][0]["reason_code"] == "VEHICLE_TIME_EXHAUSTED"
    assert "Every compatible alternative MT" in result["dropped"][0]["reason_description"]
    assert result["solver_metadata"]["post_bay_reassignment_attempts"] == 1
    assert result["solver_metadata"]["post_bay_reassignment_exhausted_lo_count"] == 1
    assert result["solver_metadata"]["bay_dropped_trip_count"] == 1


def test_i_initial_queue_delays_future_gate_out() -> None:
    ready = DAY_START + timedelta(hours=5)
    trip = {"vehicle_ready_at_depot": ready, "lo_assignments": [{"loading_order_id": "LO-1", "compartment_id": "C1", "product_id": "P1", "volume_kl": 8}]}
    result = BayQueueOptimizationService().schedule(
        trips=[trip],
        bays=[{"master_bay_id": "B1", "all_products_allowed": True, "allowed_product_ids": [], "number_of_loading_arms": 1, "loading_mode": "SEQUENTIAL"}],
        actual_states=[],
        initial_queue=[{"master_bay_id": "B1", "queue_position": 1, "estimated_loading_duration_minutes": 20}],
        loading_durations={"P1": 8},
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )
    assert result["assignments"][0]["loading_start"] >= ready + timedelta(minutes=20)
    assert result["assignments"][0]["gate_out"] >= ready + timedelta(minutes=33)


def test_j_loading_duration_is_summed_per_compartment_in_sequential_mode() -> None:
    trip = {
        "lo_assignments": [
            {"compartment_id": "C1", "product_id": "PERTALITE"},
            {"compartment_id": "C2", "product_id": "PERTALITE"},
            {"compartment_id": "C3", "product_id": "BIOSOLAR"},
        ]
    }
    assert BayQueueOptimizationService.loading_minutes(trip, {"PERTALITE": 8, "BIOSOLAR": 10}, loading_mode="SEQUENTIAL") == 26


def test_k_planned_eta_is_the_only_user_availability_input() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.add(MasterMT(mt_id="M1", vehicle_name_raw="MT 1", vehicle_registration="BL 1", depot_id="D1"))
        db.add(OptimizationJob(job_id="JOB-1", job_no="P7-JOB-1", job_name="Job", depot_id="D1", operating_date=date(2026, 8, 26), depot_operational_start=time(5), depot_operational_end=time(22)))
        db.add(VehicleOperationalState(vehicle_state_id="VS-1", job_id="JOB-1", mt_id="M1", capacity_kl=8, number_of_compartments=1, compartment_configuration=[{"compartment_id": "C1", "capacity_kl": 8}], planned_eta_depot=DAY_START + timedelta(hours=5), system_eta_depot=DAY_START + timedelta(hours=7), user_eta_override=DAY_START + timedelta(hours=8), effective_eta_depot=DAY_START + timedelta(hours=8)))
        db.commit()
        planned = DAY_START + timedelta(hours=6)
        result = update_vehicle_states(db, "JOB-1", [{"mt_id": "M1", "planned_eta_depot": planned.isoformat()}])
        state = db.scalar(select(VehicleOperationalState).where(VehicleOperationalState.mt_id == "M1"))
        assert state.planned_eta_depot.replace(tzinfo=timezone.utc) == planned
        assert state.effective_eta_depot.replace(tzinfo=timezone.utc) == planned
        assert state.user_eta_override is None
        assert "user_eta_override" not in result["vehicles"][0]


def test_k1_system_eta_is_empty_when_mt_is_first_loaded_before_v1() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.add(MasterMT(mt_id="M1", vehicle_name_raw="MT 1", vehicle_registration="BL 1", depot_id="D1"))
        db.add(OptimizationJob(job_id="JOB-1", job_no="P7-JOB-1", job_name="Job", depot_id="D1", operating_date=date(2026, 8, 26)))
        db.commit()

        result = load_mt_from_master(db, "JOB-1")

        assert result["vehicles"][0]["system_eta_depot"] is None
        assert db.scalar(select(VehicleOperationalState).where(VehicleOperationalState.mt_id == "M1")).system_eta_depot is None


def test_k1a_lo_system_eta_is_trip_specific_and_mt_delivery_status_follows_lo_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        db.add(MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="SPBU 1"))
        db.add_all([
            MasterMT(mt_id="M1", vehicle_name_raw="MT 1", vehicle_registration="BL 1", depot_id="D1"),
            MasterMT(mt_id="M2", vehicle_name_raw="MT 2", vehicle_registration="BL 2", depot_id="D1"),
            MasterMT(mt_id="M3", vehicle_name_raw="MT 3", vehicle_registration="BL 3", depot_id="D1"),
            MasterMT(mt_id="M4", vehicle_name_raw="MT 4", vehicle_registration="BL 4", depot_id="D1"),
        ])
        job = OptimizationJob(
            job_id="JOB-1",
            job_no="P7-JOB-1",
            job_name="Job",
            depot_id="D1",
            operating_date=date(2026, 8, 26),
        )
        db.add(job)
        db.add_all([
            OperationalStateSnapshot(state_snapshot_id="STATE-1", job_id="JOB-1", snapshot_reason="Initial"),
            OptimizationParameterSnapshot(parameter_snapshot_id="PARAM-1", job_id="JOB-1", effective_parameters={}, parameter_checksum="a"),
        ])
        db.flush()
        db.add(RouteVersion(
            route_version_id="V1",
            job_id="JOB-1",
            version_number=1,
            version_label="V1",
            reason="Initial",
            state_snapshot_id="STATE-1",
            parameter_snapshot_id="PARAM-1",
            objective="MIN_TOTAL_COST",
            solver_status="FEASIBLE",
        ))
        db.flush()
        trip_1_return = DAY_START + timedelta(hours=8)
        trip_2_return = DAY_START + timedelta(hours=12)
        m2_ongoing_return = DAY_START + timedelta(hours=10)
        db.add_all([
            RouteVersionTrip(route_version_trip_id="T1", route_version_id="V1", vehicle_id="M1", trip_number=1, shipment_id="SHIP-1", vehicle_ready_at_depot=DAY_START, gate_out=DAY_START + timedelta(hours=6), estimated_return_depot=trip_1_return),
            RouteVersionTrip(route_version_trip_id="T2", route_version_id="V1", vehicle_id="M1", trip_number=2, shipment_id="SHIP-2", vehicle_ready_at_depot=trip_1_return, gate_out=DAY_START + timedelta(hours=9), estimated_return_depot=trip_2_return),
            RouteVersionTrip(route_version_trip_id="T3", route_version_id="V1", vehicle_id="M2", trip_number=2, shipment_id="SHIP-4", vehicle_ready_at_depot=DAY_START, gate_out=DAY_START + timedelta(hours=7), estimated_return_depot=m2_ongoing_return),
        ])
        db.flush()
        db.add_all([
            RouteVersionLOAssignment(route_version_lo_assignment_id="A1", route_version_id="V1", route_version_trip_id="T1", loading_order_id="LO-1", vehicle_id="M1", trip_number=1, shipment_id="SHIP-1", spbu_id="S1", volume_kl=8, assignment_status="DONE"),
            RouteVersionLOAssignment(route_version_lo_assignment_id="A2", route_version_id="V1", route_version_trip_id="T2", loading_order_id="LO-2", vehicle_id="M1", trip_number=2, shipment_id="SHIP-2", spbu_id="S1", volume_kl=8, assignment_status="PLANNED"),
            RouteVersionLOAssignment(route_version_lo_assignment_id="A4", route_version_id="V1", route_version_trip_id="T3", loading_order_id="LO-4", vehicle_id="M2", trip_number=2, shipment_id="SHIP-4", spbu_id="S1", volume_kl=8, assignment_status="ONGOING"),
        ])
        for mt_id in ["M1", "M2", "M3", "M4"]:
            db.add(VehicleOperationalState(vehicle_state_id=f"VS-{mt_id}", job_id="JOB-1", mt_id=mt_id, registration_snapshot=f"BL {mt_id[-1]}", capacity_kl=8, number_of_compartments=1, compartment_configuration=[{"compartment_id": "C1", "capacity_kl": 8}], system_eta_depot=DAY_START + timedelta(hours=20)))
        lo_rows = [
            ("LO-1", "M1", 1, "DONE"),
            ("LO-2", "M1", 2, "PLANNED"),
            ("LO-3", "M2", 1, "DONE"),
            ("LO-4", "M2", 2, "ONGOING"),
            ("LO-5", "M3", 1, "PLANNED"),
        ]
        for lo_id, mt_id, trip_number, status in lo_rows:
            db.add(LOOperationalState(
                lo_state_id=f"STATE-{lo_id}",
                job_id="JOB-1",
                loading_order_id=lo_id,
                spbu_id="S1",
                volume_kl=8,
                depot_id="D1",
                operating_date=date(2026, 8, 26),
                source_prediction_run_id="P6-1",
                current_vehicle_id=mt_id,
                current_trip_number=trip_number,
                status=status,
            ))
        job.current_route_version_id = "V1"
        db.commit()

        los = {row["loading_order_id"]: row for row in phase7_service.list_job_los(db, "JOB-1")}
        vehicles = {row["mt_id"]: row for row in phase7_service.list_job_vehicles(db, "JOB-1")}

        assert los["LO-1"]["system_eta_depot"] == trip_1_return.isoformat()
        assert los["LO-2"]["system_eta_depot"] == trip_2_return.isoformat()
        assert los["LO-3"]["system_eta_depot"] is None
        assert vehicles["M1"]["delivery_status"] == "DONE"
        assert vehicles["M2"]["delivery_status"] == "ONGOING"
        assert vehicles["M3"]["delivery_status"] == "PLANNED"
        assert vehicles["M4"]["delivery_status"] == "PLANNED"
        assert vehicles["M1"]["system_eta_depot"] is None
        assert vehicles["M2"]["system_eta_depot"] == m2_ongoing_return.isoformat()
        assert vehicles["M3"]["system_eta_depot"] is None
        assert vehicles["M4"]["system_eta_depot"] is None


def test_k2_initial_completion_publishes_first_trip_return_and_clears_planned_eta() -> None:
    planned = DAY_START + timedelta(hours=5)
    first_return = DAY_START + timedelta(hours=8)
    second_return = DAY_START + timedelta(hours=12)
    state = VehicleOperationalState(
        vehicle_state_id="VS-1",
        job_id="JOB-1",
        mt_id="M1",
        planned_eta_depot=planned,
        effective_eta_depot=planned,
    )
    trips = [
        RouteVersionTrip(
            route_version_trip_id="T2",
            route_version_id="V1",
            vehicle_id="M1",
            trip_number=2,
            shipment_id="SHIP-2",
            gate_out=DAY_START + timedelta(hours=9),
            estimated_return_depot=second_return,
        ),
        RouteVersionTrip(
            route_version_trip_id="T1",
            route_version_id="V1",
            vehicle_id="M1",
            trip_number=1,
            shipment_id="SHIP-1",
            gate_out=DAY_START + timedelta(hours=6),
            estimated_return_depot=first_return,
        ),
    ]

    system_eta = _complete_vehicle_eta_state(
        state,
        reroute=False,
        trips=trips,
        ongoing_trip_keys=set(),
    )

    assert system_eta == first_return
    assert state.system_eta_depot == first_return
    assert state.effective_eta_depot == first_return
    assert state.planned_eta_depot is None


def test_k3_reroute_completion_publishes_ongoing_trip_eta_and_clears_planned_eta() -> None:
    planned_input = DAY_START + timedelta(hours=9)
    calculated_ongoing_return = DAY_START + timedelta(hours=6, minutes=4)
    state = VehicleOperationalState(
        vehicle_state_id="VS-1",
        job_id="JOB-1",
        mt_id="M1",
        planned_eta_depot=planned_input,
        system_eta_depot=DAY_START + timedelta(hours=12),
        effective_eta_depot=DAY_START + timedelta(hours=12),
    )
    trips = [
        RouteVersionTrip(
            route_version_trip_id="T1-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=1,
            shipment_id="SHIP-1",
            gate_out=DAY_START + timedelta(hours=4),
            estimated_return_depot=calculated_ongoing_return,
        ),
        RouteVersionTrip(
            route_version_trip_id="T2-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=2,
            shipment_id="SHIP-2",
            gate_out=DAY_START + timedelta(hours=10),
            estimated_return_depot=DAY_START + timedelta(hours=14),
        ),
    ]

    system_eta = _complete_vehicle_eta_state(
        state,
        reroute=True,
        trips=trips,
        ongoing_trip_keys={("M1", 1)},
    )

    assert system_eta == calculated_ongoing_return
    assert state.system_eta_depot == calculated_ongoing_return
    assert state.effective_eta_depot == calculated_ongoing_return
    assert state.planned_eta_depot is None


def test_k3b_reroute_ignores_and_clears_legacy_user_eta_override() -> None:
    planned_ongoing_eta = DAY_START + timedelta(hours=6, minutes=4)
    state = VehicleOperationalState(
        vehicle_state_id="VS-1",
        job_id="JOB-1",
        mt_id="M1",
        planned_eta_depot=planned_ongoing_eta,
        system_eta_depot=DAY_START + timedelta(hours=12),
        user_eta_override=DAY_START + timedelta(hours=9),
        effective_eta_depot=DAY_START + timedelta(hours=9),
    )
    trips = [
        RouteVersionTrip(
            route_version_trip_id="T1-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=1,
            shipment_id="SHIP-1",
            gate_out=DAY_START + timedelta(hours=4),
            estimated_return_depot=DAY_START + timedelta(hours=7),
        ),
        RouteVersionTrip(
            route_version_trip_id="T2-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=2,
            shipment_id="SHIP-2",
            gate_out=DAY_START + timedelta(hours=10),
            estimated_return_depot=DAY_START + timedelta(hours=14),
        ),
    ]

    system_eta = _complete_vehicle_eta_state(
        state,
        reroute=True,
        trips=trips,
        ongoing_trip_keys={("M1", 1)},
    )

    assert system_eta == DAY_START + timedelta(hours=7)
    assert state.system_eta_depot == DAY_START + timedelta(hours=7)
    assert state.effective_eta_depot == DAY_START + timedelta(hours=7)
    assert state.planned_eta_depot is None
    assert state.user_eta_override is None


def test_k4_reroute_without_ongoing_trip_publishes_calculated_trip_1_return() -> None:
    state = VehicleOperationalState(
        vehicle_state_id="VS-1",
        job_id="JOB-1",
        mt_id="M1",
        planned_eta_depot=DAY_START + timedelta(hours=5),
        system_eta_depot=DAY_START + timedelta(hours=8),
        effective_eta_depot=DAY_START + timedelta(hours=8),
    )
    first_return = DAY_START + timedelta(hours=8)
    trips = [
        RouteVersionTrip(
            route_version_trip_id="T2-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=2,
            shipment_id="SHIP-2",
            gate_out=DAY_START + timedelta(hours=10),
            estimated_return_depot=DAY_START + timedelta(hours=14),
        ),
        RouteVersionTrip(
            route_version_trip_id="T1-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=1,
            shipment_id="SHIP-1",
            gate_out=DAY_START + timedelta(hours=5),
            estimated_return_depot=first_return,
        ),
    ]

    system_eta = _complete_vehicle_eta_state(
        state,
        reroute=True,
        trips=trips,
        ongoing_trip_keys=set(),
    )

    assert system_eta == first_return
    assert state.system_eta_depot == first_return
    assert state.effective_eta_depot == first_return
    assert state.planned_eta_depot is None


def test_k5_reroute_publishes_trip_2_when_trip_2_contains_ongoing_lo() -> None:
    trip_2_return = DAY_START + timedelta(hours=14)
    state = VehicleOperationalState(
        vehicle_state_id="VS-1",
        job_id="JOB-1",
        mt_id="M1",
        planned_eta_depot=DAY_START + timedelta(hours=10),
        system_eta_depot=DAY_START + timedelta(hours=8),
        effective_eta_depot=DAY_START + timedelta(hours=10),
    )
    trips = [
        RouteVersionTrip(
            route_version_trip_id="T1-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=1,
            shipment_id="SHIP-1",
            gate_out=DAY_START + timedelta(hours=5),
            estimated_return_depot=DAY_START + timedelta(hours=8),
        ),
        RouteVersionTrip(
            route_version_trip_id="T2-REROUTE",
            route_version_id="V2",
            vehicle_id="M1",
            trip_number=2,
            shipment_id="SHIP-2",
            gate_out=DAY_START + timedelta(hours=10),
            estimated_return_depot=trip_2_return,
        ),
    ]

    system_eta = _complete_vehicle_eta_state(
        state,
        reroute=True,
        trips=trips,
        ongoing_trip_keys={("M1", 2)},
    )

    assert system_eta == trip_2_return
    assert state.system_eta_depot == trip_2_return
    assert state.effective_eta_depot == trip_2_return
    assert state.planned_eta_depot is None


def test_l_route_versioning_keeps_v1_immutable_when_v2_becomes_current() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        job = OptimizationJob(job_id="JOB-1", job_no="P7-JOB-1", job_name="Job", depot_id="D1", operating_date=date(2026, 8, 26), depot_operational_start=time(5), depot_operational_end=time(22))
        db.add(job)
        state_1 = OperationalStateSnapshot(state_snapshot_id="S1", job_id="JOB-1", snapshot_reason="Initial")
        state_2 = OperationalStateSnapshot(state_snapshot_id="S2", job_id="JOB-1", snapshot_reason="Reroute")
        parameter_1 = OptimizationParameterSnapshot(parameter_snapshot_id="P1", job_id="JOB-1", effective_parameters={"objective": "MIN_TOTAL_COST"}, parameter_checksum="a")
        parameter_2 = OptimizationParameterSnapshot(parameter_snapshot_id="P2", job_id="JOB-1", effective_parameters={"objective": "MIN_TOTAL_DISTANCE"}, parameter_checksum="b")
        db.add_all([state_1, state_2, parameter_1, parameter_2])
        db.flush()
        v1 = RouteVersion(route_version_id="V1", job_id="JOB-1", version_number=1, version_label="V1", reason="Initial", state_snapshot_id="S1", parameter_snapshot_id="P1", objective="MIN_TOTAL_COST", solver_status="FEASIBLE", summary_snapshot={"total_trips": 1})
        v2 = RouteVersion(route_version_id="V2", job_id="JOB-1", version_number=2, version_label="V2", reason="Reroute", state_snapshot_id="S2", parameter_snapshot_id="P2", objective="MIN_TOTAL_DISTANCE", solver_status="FEASIBLE", summary_snapshot={"total_trips": 2})
        db.add_all([v1, v2])
        job.current_route_version_id = "V2"
        db.commit()
        assert db.get(RouteVersion, "V1").summary_snapshot == {"total_trips": 1}
        assert db.get(OptimizationJob, "JOB-1").current_route_version_id == "V2"


def test_m_infeasible_lo_is_returned_with_reason_instead_of_disappearing() -> None:
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-117", "S1", allowed=[])],
        vehicles=[vehicle("M1")],
        distance_matrix=[[0, 10_000], [10_000, 0]],
        time_matrix=[[0, 1_200], [1_200, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )
    assert result["trips"] == []
    assert result["dropped"][0]["loading_order_id"] == "LO-117"
    assert result["dropped"][0]["reason_code"] == "NO_COMPATIBLE_MT"
    assert result["dropped"][0]["reason_description"]


def test_n_final_route_geometry_materializes_depot_stop_depot_without_callback_error() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        depot = MasterDepot(depot_id="D1", depot_name="Depot", latitude=3.59, longitude=98.67)
        spbu = MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="SPBU", latitude=3.65, longitude=98.72)
        db.add_all([depot, spbu])
        db.commit()
        result = RouteMatrixService(db).build_route_geometry(
            depot=depot,
            ordered_spbus=[spbu],
            departure=DAY_START + timedelta(hours=5),
            parameters={"route_matrix_cache_enabled": True, "route_matrix_cache_ttl_minutes": 60, "route_vehicle_mode": "GENERAL_VEHICLE", "traffic_aware": False},
        )
        assert len(result["route_geometry"]) == 3
        assert result["route_geometry"][0] == result["route_geometry"][-1]
        assert result["route_geometry_source"] == "MIXED_OR_MASTER_FALLBACK"


def test_n2_final_route_geometry_uses_one_road_request_with_ordered_intermediates() -> None:
    class StubRoadClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def compute_route(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "distance_meters": 25_000,
                "duration_seconds": 2_400,
                "route_geometry": [
                    {"latitude": 3.59, "longitude": 98.67},
                    {"latitude": 3.62, "longitude": 98.69},
                    {"latitude": 3.65, "longitude": 98.72},
                    {"latitude": 3.68, "longitude": 98.74},
                    {"latitude": 3.59, "longitude": 98.67},
                ],
                "route_geometry_source": "GOOGLE_ROUTES_GEOJSON",
            }

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        depot = MasterDepot(depot_id="D1", depot_name="Depot", latitude=3.59, longitude=98.67)
        first = MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="SPBU 1", latitude=3.65, longitude=98.72)
        second = MasterSPBU(spbu_id="S2", spbu_code="S2", spbu_name="SPBU 2", latitude=3.68, longitude=98.74)
        db.add_all([depot, first, second])
        db.commit()
        service = RouteMatrixService(db)
        client = StubRoadClient()
        service.client = client

        result = service.build_route_geometry(
            depot=depot,
            ordered_spbus=[first, second],
            departure=DAY_START + timedelta(hours=5),
            parameters={"route_vehicle_mode": "GENERAL_VEHICLE", "traffic_aware": True, "route_geometry_google_request_budget": 1, "route_geometry_time_limit_seconds": 30},
        )

        assert result["route_geometry_source"] == "GOOGLE_ROUTES_GEOJSON"
        assert result["geometry_strategy"] == "SINGLE_ROUTE_WITH_INTERMEDIATES"
        assert result["google_request_count"] == 1
        assert len(client.calls) == 1
        assert client.calls[0]["origin"] == (3.59, 98.67)
        assert client.calls[0]["intermediates"] == [(3.65, 98.72), (3.68, 98.74)]
        assert client.calls[0]["destination"] == (3.59, 98.67)


def test_o_new_trip_numbers_continue_after_copied_frozen_trip_number() -> None:
    mt = vehicle("M1")
    mt["completed_trip_count"] = 2
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-3", "S1")],
        vehicles=[mt],
        distance_matrix=[[0, 10_000], [10_000, 0]],
        time_matrix=[[0, 1_200], [1_200, 0]],
        day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(),
    )
    assert result["trips"][0]["trip_number"] == 3


def test_p_explicit_truck_mode_never_masquerades_as_general_drive_geometry() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        depot = MasterDepot(depot_id="D1", depot_name="Depot", latitude=3.59, longitude=98.67)
        spbu = MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="SPBU", latitude=3.65, longitude=98.72)
        db.add_all([depot, spbu])
        db.commit()
        result = RouteMatrixService(db).build_route_geometry(
            depot=depot,
            ordered_spbus=[spbu],
            departure=DAY_START + timedelta(hours=5),
            parameters={"route_matrix_cache_enabled": True, "route_matrix_cache_ttl_minutes": 60, "route_vehicle_mode": "TRUCK", "traffic_aware": True},
        )
        assert result["google_request_count"] == 0
        assert result["leg_sources"] == [
            "TRUCK_MODE_UNAVAILABLE_MASTER_HAVERSINE_FALLBACK",
            "TRUCK_MODE_UNAVAILABLE_MASTER_HAVERSINE_FALLBACK",
        ]


def test_q_trip_cost_drilldown_activates_each_mt_only_once() -> None:
    mt = vehicle("M1")
    result = {
        "trips": [
            {"vehicle_id": "M1", "trip_number": number, "distance_meters": 10_000, "operating_minutes": 60, "queue_minutes": 5, "loading_minutes": 8, "lo_assignments": [{"phase6_predicted_vehicle_id": "M1"}]}
            for number in (1, 2)
        ]
    }
    costs = _trip_cost_breakdowns(
        result,
        [mt],
        parameters(
            vehicle_activation_cost_rules=[{"vehicle_class": 8, "vehicle_tag": None, "activation_cost": 500_000, "priority": 10}],
            queue_cost=1_000,
            loading_cost=1_000,
            overtime_cost=5_000,
        ),
    )
    assert costs[("M1", 1)]["vehicle_activation_cost"] == 500_000
    assert costs[("M1", 2)]["vehicle_activation_cost"] == 0
    assert costs[("M1", 1)]["total_cost"] == 663_000
    assert costs[("M1", 2)]["total_cost"] == 163_000


def test_r_plan_stability_counts_material_gate_out_changes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot 1"))
        job = OptimizationJob(job_id="JOB-1", job_no="P7-JOB-1", job_name="Job", depot_id="D1", operating_date=date(2026, 8, 26), depot_operational_start=time(5), depot_operational_end=time(22), current_route_version_id=None)
        db.add(job)
        db.add_all([
            OperationalStateSnapshot(state_snapshot_id="STATE-1", job_id="JOB-1", snapshot_reason="Initial"),
            OptimizationParameterSnapshot(parameter_snapshot_id="PARAM-1", job_id="JOB-1", effective_parameters={}, parameter_checksum="a"),
        ])
        db.flush()
        version = RouteVersion(route_version_id="V1", job_id="JOB-1", version_number=1, version_label="V1", reason="Initial", state_snapshot_id="STATE-1", parameter_snapshot_id="PARAM-1", objective="MIN_TOTAL_COST", solver_status="FEASIBLE")
        db.add(version)
        db.flush()
        db.add(RouteVersionLOAssignment(route_version_lo_assignment_id="A1", route_version_id="V1", loading_order_id="LO-1", vehicle_id="M1", shipment_id="S1", spbu_id="SPBU-1", volume_kl=8, stop_sequence=1, planned_gate_out=DAY_START + timedelta(hours=5), assignment_status="PLANNED"))
        job.current_route_version_id = "V1"
        db.commit()
        comparison = _comparison(db, job, {"trips": [{"vehicle_id": "M2", "shipment_id": "S2", "gate_out": DAY_START + timedelta(hours=5, minutes=20), "stops": [{"sequence": 2, "loading_order": {"loading_order_id": "LO-1"}}], "lo_assignments": [{"loading_order_id": "LO-1"}]}]}, gate_out_tolerance_minutes=5)
        assert comparison["vehicle_assignment_changes"] == 1
        assert comparison["shipment_changes"] == 1
        assert comparison["route_sequence_changes"] == 1
        assert comparison["gate_out_changes"] == 1
        assert comparison["plan_adherence_pct"] == 0


def test_s_matrix_build_deduplicates_lo_locations_and_batches_google_elements() -> None:
    class StubGoogleRoutesClient:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        def compute_route_matrix_batch(self, *, origins, destinations, departure_datetime):
            self.calls.append((len(origins), len(destinations)))
            return [
                {
                    "originIndex": origin_index,
                    "destinationIndex": destination_index,
                    "condition": "ROUTE_EXISTS",
                    "distanceMeters": 10_000 + origin_index * 100 + destination_index,
                    "duration": "1200s",
                    "status": {},
                }
                for origin_index in range(len(origins))
                for destination_index in range(len(destinations))
            ]

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        depot = MasterDepot(depot_id="D1", depot_name="Depot", latitude=3.59, longitude=98.67)
        spbus = {
            "S1": MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="SPBU 1", latitude=3.65, longitude=98.72),
            "S2": MasterSPBU(spbu_id="S2", spbu_code="S2", spbu_name="SPBU 2", latitude=3.70, longitude=98.77),
        }
        db.add_all([depot, *spbus.values()])
        db.commit()
        service = RouteMatrixService(db)
        client = StubGoogleRoutesClient()
        service.client = client
        progress: list[dict] = []
        result = service.build(
            depot=depot,
            loading_orders=[{"loading_order_id": f"LO-{index}", "spbu_id": "S1" if index % 2 else "S2"} for index in range(1, 101)],
            spbus=spbus,
            departure=DAY_START + timedelta(hours=5),
            parameters={
                "route_matrix_cache_enabled": True,
                "route_matrix_cache_ttl_minutes": 60,
                "route_vehicle_mode": "GENERAL_VEHICLE",
                "traffic_aware": True,
                "route_matrix_time_limit_seconds": 90,
                "route_matrix_google_element_budget": 2500,
            },
            progress_callback=progress.append,
        )
        db.commit()
        assert result["metadata"]["location_count"] == 101
        assert result["metadata"]["unique_location_count"] == 3
        assert result["metadata"]["unique_pair_count"] == 6
        assert result["metadata"]["google_batch_request_count"] == 1
        assert client.calls == [(3, 3)]
        assert result["distance_matrix"][1][3] == 0  # Both LO nodes point to S1.
        assert db.query(RouteMatrixCache).count() == 6
        assert progress[-1]["completed_unique_pairs"] == 6


def test_t_cost_breakdown_treats_missing_phase6_mt_as_no_change() -> None:
    result = {
        "trips": [
            {
                "vehicle_id": "M1",
                "distance_meters": 10_000,
                "operating_minutes": 60,
                "queue_minutes": 0,
                "loading_minutes": 8,
                "lo_assignments": [{"volume_kl": 8, "phase6_predicted_vehicle_id": None}],
            }
        ],
        "dropped": [],
    }
    costs = _cost_breakdown(
        result,
        [vehicle("M1")],
        parameters(queue_cost=0, loading_cost=0, overtime_cost=0),
    )
    assert costs["penalty_cost"] == 0
    assert costs["total_cost"] > 0


def test_u_startup_recovery_unlocks_interrupted_phase7_job() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot"))
        db.add(OptimizationJob(job_id="JOB-1", job_no="P7-JOB-1", job_name="Job", depot_id="D1", operating_date=date(2026, 8, 26), status="CALCULATING"))
        db.add(OperationalStateSnapshot(state_snapshot_id="STATE-1", job_id="JOB-1", snapshot_reason="Initial"))
        db.add(OptimizationParameterSnapshot(parameter_snapshot_id="PARAM-1", job_id="JOB-1", effective_parameters={}, parameter_checksum="a"))
        db.flush()
        db.add(
            OptimizationRun(
                optimization_run_id="RUN-1",
                job_id="JOB-1",
                run_type="INITIAL",
                status="RUNNING",
                state_snapshot_id="STATE-1",
                parameter_snapshot_id="PARAM-1",
                start_time=DAY_START,
                solver_status="PENDING",
                objective="MIN_TOTAL_COST",
                solver_metadata={"stage": "BUILDING_MATRIX", "progress_pct": 20},
            )
        )
        db.commit()
        assert recover_interrupted_phase7_optimizations(db) == 1
        run = db.get(OptimizationRun, "RUN-1")
        job = db.get(OptimizationJob, "JOB-1")
        assert run.status == "FAILED"
        assert run.error_code == "PHASE7_PROCESS_INTERRUPTED"
        assert run.solver_metadata["stage"] == "INTERRUPTED"
        assert job.status == "FAILED"


def test_v_copy_frozen_plan_flushes_parent_trip_and_bay_before_dependents() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        db.add(MasterDepot(depot_id="D1", depot_name="Depot"))
        db.flush()
        db.add_all(
            [
                MasterMT(mt_id="M1", vehicle_name_raw="MT 1", vehicle_registration="BL 1", depot_id="D1"),
                MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="SPBU"),
                MasterLoadingBay(master_bay_id="B1", depot_id="D1", bay_id="BAY-1", bay_name="Bay 1"),
                OptimizationJob(
                    job_id="JOB-1",
                    job_no="P7-JOB-1",
                    job_name="Job",
                    depot_id="D1",
                    operating_date=date(2026, 8, 26),
                    depot_operational_start=time(5),
                    depot_operational_end=time(22),
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                OperationalStateSnapshot(state_snapshot_id="STATE-1", job_id="JOB-1", snapshot_reason="Initial"),
                OperationalStateSnapshot(state_snapshot_id="STATE-2", job_id="JOB-1", snapshot_reason="Retry"),
                OptimizationParameterSnapshot(parameter_snapshot_id="PARAM-1", job_id="JOB-1", effective_parameters={}, parameter_checksum="a"),
                OptimizationParameterSnapshot(parameter_snapshot_id="PARAM-2", job_id="JOB-1", effective_parameters={}, parameter_checksum="b"),
            ]
        )
        db.flush()
        v1 = RouteVersion(route_version_id="V1", job_id="JOB-1", version_number=1, version_label="V1", reason="Initial", state_snapshot_id="STATE-1", parameter_snapshot_id="PARAM-1", objective="MIN_TOTAL_COST", solver_status="FEASIBLE")
        v2 = RouteVersion(route_version_id="V2", job_id="JOB-1", version_number=2, version_label="V2", reason="Retry", state_snapshot_id="STATE-2", parameter_snapshot_id="PARAM-2", objective="MIN_TOTAL_COST", solver_status="FEASIBLE")
        db.add_all([v1, v2])
        db.flush()
        trip = RouteVersionTrip(
            route_version_trip_id="TRIP-1",
            route_version_id="V1",
            vehicle_id="M1",
            trip_number=1,
            shipment_id="SHIP-1",
            vehicle_ready_at_depot=DAY_START,
            queue_start=DAY_START,
            loading_start=DAY_START + timedelta(minutes=5),
            loading_finish=DAY_START + timedelta(minutes=13),
            gate_out=DAY_START + timedelta(minutes=18),
            estimated_return_depot=DAY_START + timedelta(hours=1),
        )
        db.add(trip)
        db.flush()
        db.add(
            RouteVersionLOAssignment(
                route_version_lo_assignment_id="LOA-1",
                route_version_id="V1",
                route_version_trip_id="TRIP-1",
                loading_order_id="LO-1",
                vehicle_id="M1",
                trip_number=1,
                shipment_id="SHIP-1",
                compartment_id="C1",
                spbu_id="S1",
                volume_kl=8,
                assignment_status="PLANNED",
            )
        )
        db.add(
            OptimizationBayAssignment(
                bay_assignment_id="BA-1",
                route_version_id="V1",
                route_version_trip_id="TRIP-1",
                master_bay_id="B1",
                vehicle_ready_at_depot=DAY_START,
                queue_start=DAY_START,
                loading_start=DAY_START + timedelta(minutes=5),
                loading_finish=DAY_START + timedelta(minutes=13),
                gate_out=DAY_START + timedelta(minutes=18),
                queue_minutes=5,
                loading_minutes=8,
            )
        )
        db.flush()
        db.add(
            OptimizationBayOperation(
                bay_operation_id="BO-1",
                bay_assignment_id="BA-1",
                master_bay_id="B1",
                compartment_id="C1",
                loading_start=DAY_START + timedelta(minutes=5),
                loading_finish=DAY_START + timedelta(minutes=13),
                duration_minutes=8,
                loading_mode="SEQUENTIAL",
            )
        )
        job = db.get(OptimizationJob, "JOB-1")
        job.current_route_version_id = "V1"
        db.commit()

        frozen = lo_state("LO-1", status="ONGOING")
        frozen.frozen = True
        actual_return = DAY_START + timedelta(hours=2)
        copied_trips, copied_ids = _copy_frozen_plan(
            db,
            job,
            v2,
            [frozen],
            ongoing_return_by_mt={"M1": actual_return},
        )
        db.flush()

        assert copied_ids == {"LO-1"}
        assert len(copied_trips) == 1
        assert phase7_service._utc(copied_trips[0].estimated_return_depot) == actual_return
        assert copied_trips[0].operating_minutes == 120
        assert copied_trips[0].cost_breakdown["actual_state_adjustment"]["source"] == "REROUTE_PLANNED_ETA_DEPOT"
        copied_trip_id = copied_trips[0].route_version_trip_id
        assert db.get(RouteVersionTrip, copied_trip_id) is not None
        copied_bay = db.scalar(
            select(OptimizationBayAssignment).where(
                OptimizationBayAssignment.route_version_trip_id == copied_trip_id
            )
        )
        assert copied_bay is not None
        assert db.scalar(
            select(OptimizationBayOperation).where(
                OptimizationBayOperation.bay_assignment_id == copied_bay.bay_assignment_id
            )
        ) is not None


def test_w_initial_optimization_reference_time_uses_depot_timezone() -> None:
    depot = MasterDepot(depot_id="D1", depot_name="Depot", timezone="Asia/Jakarta")
    job = OptimizationJob(
        job_id="JOB-1",
        job_no="P7-JOB-1",
        job_name="Job",
        depot_id="D1",
        operating_date=date(2026, 8, 26),
        depot_operational_start=time(5),
        depot_operational_end=time(22),
    )

    reference = _normalize_optimization_reference_time(
        job,
        depot,
        "2026-08-26T09:30:00",
        reroute=False,
    )

    assert reference == datetime(2026, 8, 26, 2, 30, tzinfo=timezone.utc)


def test_x_initial_optimization_reference_date_must_match_job_date() -> None:
    depot = MasterDepot(depot_id="D1", depot_name="Depot", timezone="Asia/Jakarta")
    job = OptimizationJob(
        job_id="JOB-1",
        job_no="P7-JOB-1",
        job_name="Job",
        depot_id="D1",
        operating_date=date(2026, 8, 26),
        depot_operational_start=time(5),
        depot_operational_end=time(22),
    )

    with pytest.raises(HTTPException) as captured:
        _normalize_optimization_reference_time(
            job,
            depot,
            "2026-08-27T09:30:00",
            reroute=False,
        )

    assert captured.value.status_code == 422
    assert captured.value.detail["code"] == "OPTIMIZATION_DATE_MISMATCH"


def test_y_reroute_date_is_locked_and_time_cannot_move_backwards() -> None:
    depot = MasterDepot(depot_id="D1", depot_name="Depot", timezone="Asia/Jakarta")
    job = OptimizationJob(
        job_id="JOB-1",
        job_no="P7-JOB-1",
        job_name="Job",
        depot_id="D1",
        operating_date=date(2026, 8, 26),
        depot_operational_start=time(5),
        depot_operational_end=time(22),
    )
    initial_reference = datetime(2026, 8, 26, 2, 30, tzinfo=timezone.utc)
    latest_reference = datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)

    with pytest.raises(HTTPException) as wrong_date:
        _normalize_optimization_reference_time(
            job,
            depot,
            "2026-08-27T11:30:00",
            reroute=True,
            initial_reference_time=initial_reference,
            latest_reference_time=latest_reference,
        )
    assert wrong_date.value.detail["code"] == "REROUTE_DATE_LOCKED"

    with pytest.raises(HTTPException) as backwards:
        _normalize_optimization_reference_time(
            job,
            depot,
            "2026-08-26T10:30:00",
            reroute=True,
            initial_reference_time=initial_reference,
            latest_reference_time=latest_reference,
        )
    assert backwards.value.detail["code"] == "OPTIMIZATION_TIME_BEFORE_LAST_RUN"

    accepted = _normalize_optimization_reference_time(
        job,
        depot,
        "2026-08-26T11:30:00",
        reroute=True,
        initial_reference_time=initial_reference,
        latest_reference_time=latest_reference,
    )
    assert accepted == datetime(2026, 8, 26, 4, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("status", ["PARKING_DEPOT", "ON_TRIP", "RETURNING", "QUEUEING", "LOADING"])
def test_ready_siod_preferred_over_other_available_statuses(monkeypatch, fallback, status):
    if fallback:
        monkeypatch.setattr(phase7_optimization, "ORTOOLS_AVAILABLE", False)
    parking = {**vehicle("M1"), "operational_status": status}
    ready = {**vehicle("M2"), "operational_status": "READY_SIOD"}
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-1", "S1", allowed=["M1", "M2"], preferred="M1")],
        vehicles=[parking, ready], distance_matrix=[[0, 300], [300, 0]],
        time_matrix=[[0, 300], [300, 0]], day_start=DAY_START,
        depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_optimization_time_limit=1, refueling_minutes=0),
    )
    assert len(result["trips"]) == 1
    assert result["trips"][0]["vehicle_id"] == "M2"


@pytest.mark.parametrize("status", ["PARKING_DEPOT", "ON_TRIP", "RETURNING"])
def test_other_status_remains_eligible_when_ready_siod_incompatible(status):
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order("LO-1", "S1", allowed=["M1"])],
        vehicles=[{**vehicle("M1", eta_hour=10), "operational_status": status},
                  {**vehicle("M2"), "operational_status": "READY_SIOD"}],
        distance_matrix=[[0, 300], [300, 0]], time_matrix=[[0, 300], [300, 0]],
        day_start=DAY_START, depot_close=DAY_START + timedelta(hours=18),
        parameters=parameters(route_optimization_time_limit=1, refueling_minutes=0),
    )
    assert result["trips"][0]["vehicle_id"] == "M1"
    assert result["trips"][0]["vehicle_ready_at_depot"] >= DAY_START + timedelta(hours=10)


def test_readiness_priority_consumed_by_retained_trip():
    ready = {**vehicle("M1"), "operational_status": "READY_SIOD", "working_time_limit_minutes": 600}
    retained = [{"vehicle_id": "M1", "trip_number": 1, "operating_minutes": 60,
                 "estimated_return_depot": DAY_START + timedelta(hours=8)}]
    updated = OptimizationCoordinatorService._vehicles_after_retained_trips([ready], retained)[0]
    assert not VRPOptimizationService._ready_siod_pending(updated)
    assert VRPOptimizationService._ready_siod_pending(ready)
