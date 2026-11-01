from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import (OptimizationJob, LOOperationalState, RouteVersion, RouteVersionTrip,
    RouteVersionLOAssignment, RouteVersionStop, ActualVehicleEvent)
from app.phase7_service import _solver_inputs, _copy_frozen_plan
from app.phase7_constants import effective_parameters
from test_phase7_job_adjustments import workspace, NOW, add

@pytest.fixture
def plan(workspace):
    db,client=workspace
    add(client,"L1"); add(client,"L2")
    job=db.get(OptimizationJob,"J")
    version=RouteVersion(route_version_id="V1",job_id="J",version_number=1,version_label="V1",reason="Initial",state_snapshot_id="SS",parameter_snapshot_id="PS",objective="MIN_TOTAL_COST",solver_status="FEASIBLE")
    db.add(version); db.flush()
    job.current_route_version_id="V1"
    trip=RouteVersionTrip(route_version_trip_id="T1",route_version_id="V1",vehicle_id="M",trip_number=1,shipment_id="SHIP",vehicle_ready_at_depot=NOW,gate_out=NOW,estimated_return_depot=NOW+timedelta(hours=2))
    db.add(trip); db.flush()
    for lo in db.scalars(select(LOOperationalState)).all():
        lo.current_vehicle_id="M"; lo.current_trip_number=1; lo.current_shipment_id="SHIP"; lo.current_compartment_id="C1"; lo.planned_gate_out=NOW
        db.add(RouteVersionLOAssignment(route_version_lo_assignment_id=lo.loading_order_id,route_version_id="V1",route_version_trip_id="T1",loading_order_id=lo.loading_order_id,vehicle_id="M",trip_number=1,spbu_id="S",product_id="P",volume_kl=8,assignment_status="PLANNED",planned_gate_out=NOW))
    db.add(RouteVersionStop(route_version_stop_id="STOP",route_version_trip_id="T1",sequence_number=1,stop_type="SPBU",spbu_id="S",arrival_time=NOW+timedelta(hours=1),departure_time=NOW+timedelta(hours=1,minutes=30),loading_order_ids=["L1","L2"],products=["P"],volume_kl=16))
    db.commit()
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"updates":[{"loading_order_id":"L1","status":"ONGOING"}]})
    assert response.status_code == 200,response.text
    return db,client


def test_route_status_uses_shared_live_lo_state_without_mutating_history(plan):
    db,client=plan
    rows={r["loading_order_id"]:r for r in client.get("/api/v1/phase7/jobs/J/loading-orders").json()}
    assert rows["L1"]["status"] == "ONGOING"
    assert rows["L2"]["frozen_reason"] == "FROZEN_TRIP_DEPENDENCY"
    assert db.get(RouteVersionLOAssignment,"L1").assignment_status == "PLANNED"
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"V1","updates":[{"loading_order_id":"L2","status":"DONE"}]})
    assert response.status_code == 200
    assert {r["status"] for r in client.get("/api/v1/phase7/jobs/J/loading-orders").json()} == {"DONE"}
    assert db.get(RouteVersionLOAssignment,"L1").assignment_status == "PLANNED"


def test_release_detaches_and_survives_next_freeze_evaluation(plan):
    db,client=plan
    response=client.post("/api/v1/phase7/jobs/J/loading-orders/release-dependency",json={"loading_order_ids":["L2"]})
    assert response.status_code == 200,response.text
    rows={r["loading_order_id"]:r for r in client.get("/api/v1/phase7/jobs/J/loading-orders").json()}
    assert rows["L2"]["status"] == "PLANNED" and not rows["L2"]["frozen"]
    assert rows["L2"]["current_mt_id"] is None and rows["L2"]["planned_gate_out"] is None
    state=_solver_inputs(db,db.get(OptimizationJob,"J"),effective_parameters({}),current_time=NOW,reroute=True)
    assert [r["loading_order_id"] for r in state["loading_orders"]] == ["L2"]
    assert state["copy_frozen_loading_order_ids"] == ["L1"]
    assert db.scalar(select(ActualVehicleEvent).where(ActualVehicleEvent.event_type == "LO_DEPENDENCY_RELEASE")) is not None
    assert db.get(RouteVersionLOAssignment,"L2").route_version_trip_id == "T1"


def test_freeze_copy_does_not_duplicate_released_lo_membership(plan):
    db,client=plan
    client.post("/api/v1/phase7/jobs/J/loading-orders/release-dependency",json={"loading_order_ids":["L2"]})
    version=RouteVersion(route_version_id="V2",job_id="J",version_number=2,version_label="V2",reason="Reroute",state_snapshot_id="SS2",parameter_snapshot_id="PS2",objective="MIN_TOTAL_COST",solver_status="FEASIBLE")
    db.add(version);db.flush()
    frozen=db.scalars(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L1")).all()
    trips,ids=_copy_frozen_plan(db,db.get(OptimizationJob,"J"),version,frozen)
    db.flush()
    assert ids == {"L1"}
    stop=db.scalar(select(RouteVersionStop).where(RouteVersionStop.route_version_trip_id == trips[0].route_version_trip_id))
    assert stop.loading_order_ids == ["L1"] and stop.volume_kl == 8
    assert db.get(RouteVersionStop,"STOP").loading_order_ids == ["L1","L2"]


@pytest.mark.parametrize("ids", [["L1"],["L1","L2"],["missing"]])
def test_release_protects_direct_frozen_and_is_atomic(plan,ids):
    db,client=plan
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/release-dependency",json={"loading_order_ids":ids}).status_code in {404,409}
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L2"))
    assert row.current_trip_number == 1


def test_stale_route_and_cross_job_are_rejected(plan):
    db,client=plan
    assert client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"old-version","updates":[{"loading_order_id":"L1","status":"DONE"}]}).status_code == 409
    assert client.post("/api/v1/phase7/jobs/J2/loading-orders/release-dependency",json={"loading_order_ids":["L2"]}).status_code == 404
    job=db.get(OptimizationJob,"J"); job.status="CALCULATING";db.commit()
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/release-dependency",json={"loading_order_ids":["L2"]}).status_code == 409


def test_route_status_cannot_reattach_a_released_lo(plan):
    db,client=plan
    client.post("/api/v1/phase7/jobs/J/loading-orders/release-dependency",json={"loading_order_ids":["L2"]})
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"V1","updates":[{"loading_order_id":"L2","status":"ONGOING"}]})
    assert response.status_code == 409,response.text
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L2"))
    assert row.status == "PLANNED" and row.current_vehicle_id is None


def test_dependency_resolves_when_source_status_reverts_to_planned(plan):
    _,client=plan
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"updates":[{"loading_order_id":"L1","status":"PLANNED"}]})
    assert response.status_code == 200
    assert not any(row["frozen"] for row in client.get("/api/v1/phase7/jobs/J/loading-orders").json())


@pytest.mark.parametrize("status", ["PLANNED","ONGOING","DONE"])
def test_route_update_changes_entire_trip_including_dependency(plan,status):
    db,client=plan
    result=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"V1","updates":[{"loading_order_id":"L2","status":status}]})
    assert result.status_code == 200,result.text
    assert {row["loading_order_id"] for row in result.json()["changed"]} == {"L1","L2"}
    assert {row["status"] for row in client.get("/api/v1/phase7/jobs/J/loading-orders").json()} == {status}
    assert not any(row["frozen_reason"] == "FROZEN_TRIP_DEPENDENCY" for row in client.get("/api/v1/phase7/jobs/J/loading-orders").json())


def test_trip_status_excludes_released_members(plan):
    _,client=plan
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/release-dependency",json={"loading_order_ids":["L2"]}).status_code == 200
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"V1","updates":[{"loading_order_id":"L1","status":"DONE"}]})
    assert response.status_code == 200
    assert [row["loading_order_id"] for row in response.json()["changed"]] == ["L1"]
    rows={row["loading_order_id"]:row for row in client.get("/api/v1/phase7/jobs/J/loading-orders").json()}
    assert rows["L2"]["status"] == "PLANNED" and rows["L2"]["current_mt_id"] is None


def test_conflicting_trip_status_batch_is_rejected_atomically(plan):
    _,client=plan
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"V1","updates":[{"loading_order_id":"L1","status":"DONE"},{"loading_order_id":"L2","status":"PLANNED"}]})
    assert response.status_code == 409
    rows={row["loading_order_id"]:row for row in client.get("/api/v1/phase7/jobs/J/loading-orders").json()}
    assert rows["L1"]["status"] == "ONGOING" and rows["L2"]["status"] == "PLANNED"


def test_trip_status_does_not_change_another_trip_on_same_mt(plan):
    db,client=plan
    add(client,"L3")
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L3"))
    row.current_vehicle_id="M"; row.current_trip_number=2
    db.add(RouteVersionTrip(route_version_trip_id="T2",route_version_id="V1",vehicle_id="M",trip_number=2,shipment_id="SHIP2",vehicle_ready_at_depot=NOW,gate_out=NOW+timedelta(hours=3),estimated_return_depot=NOW+timedelta(hours=4)))
    db.flush()
    db.add(RouteVersionLOAssignment(route_version_lo_assignment_id="L3",route_version_id="V1",route_version_trip_id="T2",loading_order_id="L3",vehicle_id="M",trip_number=2,spbu_id="S",product_id="P",volume_kl=8,assignment_status="PLANNED"))
    db.commit()
    response=client.patch("/api/v1/phase7/jobs/J/loading-orders/status",json={"route_version_id":"V1","updates":[{"loading_order_id":"L1","status":"DONE"}]})
    assert response.status_code == 200,response.text
    assert {item["loading_order_id"] for item in response.json()["changed"]} == {"L1","L2"}
    assert db.get(LOOperationalState,row.lo_state_id).status == "PLANNED"


def test_release_freeze_window_detaches_and_is_not_reapplied(plan):
    db,client=plan
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L1"))
    row.status="PLANNED";row.frozen=True;row.frozen_reason="FREEZE_WINDOW";db.commit()
    result=client.post("/api/v1/phase7/jobs/J/loading-orders/release-freeze-window",json={"loading_order_ids":["L1"]})
    assert result.status_code == 200,result.text
    assert row.status == "PLANNED" and not row.frozen and row.current_vehicle_id is None and row.planned_gate_out is None
    state=_solver_inputs(db,db.get(OptimizationJob,"J"),effective_parameters({}),current_time=NOW,reroute=True)
    assert "L1" in {item["loading_order_id"] for item in state["loading_orders"]}
    assert not row.frozen
    assert db.scalar(select(ActualVehicleEvent).where(ActualVehicleEvent.event_type == "LO_FREEZE_WINDOW_RELEASE")) is not None
    assert db.get(RouteVersionLOAssignment,"L1").vehicle_id == "M"


@pytest.mark.parametrize("status", ["ONGOING","DONE"])
def test_freeze_window_release_protects_executed_los(plan,status):
    db,client=plan
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L1"))
    row.status=status;row.frozen=True;row.frozen_reason=status;db.commit()
    result=client.post("/api/v1/phase7/jobs/J/loading-orders/release-freeze-window",json={"loading_order_ids":["L1"]})
    assert result.status_code == 409
    assert row.current_vehicle_id == "M"


def test_freeze_window_release_validates_batch_scope_and_job_state(plan):
    db,client=plan
    row=db.scalar(select(LOOperationalState).where(LOOperationalState.loading_order_id == "L1"))
    row.status="PLANNED";row.frozen=True;row.frozen_reason="FREEZE_WINDOW";db.commit()
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/release-freeze-window",json={"loading_order_ids":["L1","L2"]}).status_code == 409
    assert row.current_vehicle_id == "M"
    assert client.post("/api/v1/phase7/jobs/J2/loading-orders/release-freeze-window",json={"loading_order_ids":["L1"]}).status_code == 404
    job=db.get(OptimizationJob,"J");job.status="CALCULATING";db.commit()
    assert client.post("/api/v1/phase7/jobs/J/loading-orders/release-freeze-window",json={"loading_order_ids":["L1"]}).status_code == 409


def test_ongoing_unloading_reservations_are_server_owned_and_done_trips_do_not_block(plan):
    db,_=plan
    job=db.get(OptimizationJob,"J")
    state=_solver_inputs(db,job,effective_parameters({}),current_time=NOW,reroute=True)
    assert state["spbu_reservations"]==[{"spbu_id":"S","start_seconds":round((NOW+timedelta(hours=1)-state["day_start"]).total_seconds()),"end_seconds":round((NOW+timedelta(hours=1,minutes=30)-state["day_start"]).total_seconds()),"source_trip_id":"T1"}]
    for row in db.scalars(select(LOOperationalState)).all():row.status="DONE"
    db.flush()
    state=_solver_inputs(db,job,effective_parameters({}),current_time=NOW,reroute=True)
    assert state["spbu_reservations"]==[]
