import pytest
from datetime import datetime, timedelta, timezone
from app.phase7_constants import effective_parameters
from app.phase7_timing import trip_clock, travel_time_matrix, UNREACHABLE
from app.phase7_optimization import VRPOptimizationService


def test_clock_excludes_service_and_resets_each_trip():
    p=effective_parameters({})
    clock=trip_clock([3*3600, 2*3600], 5*3600, p)
    assert clock["driving_seconds"] == 5*3600
    assert clock["break_seconds"] == 1800
    assert clock["refueling_seconds"] == 2400
    assert clock["arrival_offsets"] == [3*3600+2400]
    assert clock["total_seconds"] == 10*3600+1800+2400
    assert trip_clock([3600,3600],0,p)["break_seconds"] == 0


@pytest.mark.parametrize("legs,count", [([14400],0), ([14401],1), ([28800],1), ([28801],2), ([14400,1],1)])
def test_break_boundaries(legs,count):
    clock=trip_clock(legs,0,effective_parameters({}))
    assert clock["break_seconds"] == count*1800
    assert sum(e["end_offset_seconds"]-e["start_offset_seconds"] for e in clock["events"]) == clock["total_seconds"]


def test_manual_speed_preserves_unreachable_and_google_cache():
    times=[[0,100,UNREACHABLE],[200,0,300],[UNREACHABLE,400,0]]
    distances=[[0,90000,1000],[60000,0,1000],[1000,2000,0]]
    p=effective_parameters({"travel_time_mode":"MANUAL_SPEED","average_speed_kmh":30})
    manual=travel_time_matrix(distances,times,p)
    assert manual[0][1] == 10800 and manual[1][0] == 7200
    assert manual[0][2] == UNREACHABLE and times[0][1] == 100
    assert travel_time_matrix(distances,times,effective_parameters({})) is times


@pytest.mark.parametrize("overrides", [{"average_speed_kmh":0},{"average_speed_kmh":float("nan")},{"travel_time_mode":"bad"},{"driving_break_interval_minutes":0},{"driving_break_minutes":-1},{"refueling_minutes":-1}])
def test_invalid_timing_parameters(overrides):
    with pytest.raises(ValueError): effective_parameters(overrides)


def solve(window_end=1440, working_minutes=720, **overrides):
    now=datetime(2026,10,30,tzinfo=timezone.utc)
    p=effective_parameters({"route_optimization_time_limit":1,"maximum_trips_per_mt":1,"default_spbu_service_minutes":0, "vehicle_activation_cost_rules":[],**overrides})
    return VRPOptimizationService().solve(loading_orders=[{"loading_order_id":"L","spbu_id":"S","product_id":"P","volume_kl":8,"allowed_vehicle_ids":["M"],"time_window_start_minutes":0,"time_window_end_minutes":window_end}],
        vehicles=[{"mt_id":"M","capacity_kl":8,"compartments":[{"compartment_id":"C1","capacity_kl":8}],"effective_eta_depot":now,"working_time_remaining_minutes":working_minutes}],
        distance_matrix=[[0,150000],[150000,0]],time_matrix=[[0,18000],[18000,0]],day_start=now,depot_close=now+timedelta(days=1),parameters=p)


def test_solver_adds_fuel_and_driving_breaks():
    result=solve()
    assert len(result["trips"]) == 1
    trip=result["trips"][0]
    assert trip["driving_seconds"] == 36000
    assert trip["trip_timing"]["break_seconds"] == 3600
    assert trip["operating_minutes"] == 700
    assert (trip["stops"][0]["arrival"] - trip["gate_out"]).total_seconds() == 22200


def test_solver_manual_speed_changes_duration():
    trip=solve(travel_time_mode="MANUAL_SPEED",average_speed_kmh=75)["trips"][0]
    assert trip["driving_seconds"] == 14400
    assert trip["operating_minutes"] == 280


def test_break_and_refueling_make_tight_receiving_window_infeasible():
    assert solve(window_end=340, refueling_minutes=0, driving_break_minutes=0)["trips"]
    assert solve(window_end=340)["trips"] == []


def test_break_and_refueling_count_towards_working_limit():
    assert solve(working_minutes=650, refueling_minutes=0, driving_break_minutes=0)["trips"]
    assert solve(working_minutes=650)["trips"] == []


def test_service_and_waiting_do_not_reset_driving_clock():
    clock=trip_clock([3*3600,2*3600],0,effective_parameters({}),[8*3600])
    assert clock["break_seconds"] == 1800
    assert any(e["kind"] == "WAITING" for e in clock["events"])


def test_two_physical_trips_reset_driving_and_refuel_each_time():
    now=datetime(2026,10,30,tzinfo=timezone.utc)
    p=effective_parameters({"route_optimization_time_limit":2,"maximum_trips_per_mt":2,"default_spbu_service_minutes":0})
    result=VRPOptimizationService().solve(loading_orders=[{"loading_order_id":str(i),"spbu_id":"S","product_id":"P","volume_kl":8,"allowed_vehicle_ids":["M"]} for i in range(2)],
        vehicles=[{"mt_id":"M","capacity_kl":8,"compartments":[{"compartment_id":"C1","capacity_kl":8}],"effective_eta_depot":now,"working_time_remaining_minutes":720}],
        distance_matrix=[[0,60000,60000],[60000,0,0],[60000,0,0]],time_matrix=[[0,5400,5400],[5400,0,0],[5400,0,0]],day_start=now,depot_close=now+timedelta(days=1),parameters=p)
    assert len(result["trips"]) == 2
    assert all(t["trip_timing"]["refueling_seconds"] == 2400 and t["trip_timing"]["break_seconds"] == 0 for t in result["trips"])
    assert result["trips"][1]["gate_out"] == result["trips"][0]["estimated_return_depot"] + timedelta(minutes=30)


from test_phase7_job_adjustments import workspace


@pytest.mark.parametrize("strategy", ["FIFO_BALANCED", "CP_SAT"])
def test_run_persists_timing_with_actual_bay_gate_out(workspace, monkeypatch, strategy):
    from datetime import time
    from app.models import MasterDepot, OptimizationJob, MasterLoadingBay, ProductCompartmentLoadingDuration, MasterSPBU, RouteVersionTrip
    from app.phase7_service import add_job_lo, run_optimization, get_route_version
    from app.phase7_matrix import RouteMatrixService
    from sqlalchemy import select
    db,_=workspace
    depot=db.get(MasterDepot,"D"); depot.timezone="UTC"; depot.latitude=0; depot.longitude=100
    job=db.get(OptimizationJob,"J"); job.depot_operational_start=time(0); job.depot_operational_end=time(23,59)
    spbu=db.get(MasterSPBU,"S"); spbu.latitude=1; spbu.longitude=100
    db.add(MasterLoadingBay(master_bay_id="B",depot_id="D",bay_id="B",bay_name="Bay",all_products_allowed=True,operational_start=time(0),operational_end=time(23,59)))
    db.add(ProductCompartmentLoadingDuration(loading_duration_id="DUR",depot_id="D",product_id="P",duration_minutes_per_compartment=10))
    db.commit()
    add_job_lo(db,"J",{"loading_order_id":"L","spbu_id":"S","product_id":"P","volume_kl":8})
    monkeypatch.setattr(RouteMatrixService,"build",lambda *a,**kw:{"distance_matrix":[[0,150000],[150000,0]],"time_matrix":[[0,18000],[18000,0]],"geometry":{},"metadata":{}})
    monkeypatch.setattr(RouteMatrixService,"build_route_geometry",lambda *a,**kw:{"route_geometry":[],"route_geometry_source":"TEST"})
    now=datetime(2026,10,29,tzinfo=timezone.utc)
    result=run_optimization(db,"J",{"current_time":now.isoformat(),"route_time_limit_confirmed":True,"parameters":{"route_optimization_time_limit":1,"default_spbu_service_minutes":0,"bay_scheduler_strategy":strategy,"bay_optimization_time_limit":1}},reroute=False)
    assert result["trips"], result
    trip=result["trips"][0]
    assert trip["trip_timing"]["refueling_seconds"] == 2400
    assert trip["trip_timing"]["break_seconds"] == 3600
    gate=datetime.fromisoformat(trip["gate_out"])
    arrival=datetime.fromisoformat(trip["stops"][0]["arrival_time"])
    assert (arrival-gate).total_seconds() == trip["trip_timing"]["arrival_offsets"][0]
    assert trip["operating_minutes"] >= 715
    persisted=db.scalar(select(RouteVersionTrip))
    assert persisted.cost_breakdown["trip_timing"] == trip["trip_timing"]
    assert get_route_version(db,"J")["trips"][0]["trip_timing"] == trip["trip_timing"]
