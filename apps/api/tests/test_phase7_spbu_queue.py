import copy
from datetime import datetime,timedelta,timezone
from time import perf_counter
import pytest
from app.phase7_constants import effective_parameters
from app.phase7_spbu import schedule_spbu
from app.phase7_timing import trip_clock
from app.phase7_optimization import VRPOptimizationService, OptimizationCoordinatorService

DAY=datetime(2026,11,1,tzinfo=timezone.utc)


def fixture_data(**overrides):
    p=effective_parameters({"refueling_minutes":0,"driving_break_minutes":0,"gate_process_time":0,"default_spbu_service_minutes":30,"spbu_route_search_iterations":1,**overrides})
    trips=[];assignments=[];bays=[]
    for i in range(2):
        order={"loading_order_id":f"L{i}","spbu_id":"S","product_id":"P","volume_kl":8,"time_window_start_minutes":0,"time_window_end_minutes":1440}
        clock=trip_clock([3600,3600],1800,p)
        trip={"vehicle_id":f"M{i}","trip_number":1,"vehicle_ready_at_depot":DAY,"preliminary_gate_out":DAY,"gate_out":DAY+timedelta(minutes=10),"estimated_return_depot":DAY+timedelta(minutes=160),"distance_meters":100000,"operating_minutes":160,"working_time_remaining_before_trip":720,"trip_timing":clock,"lo_assignments":[order],"stops":[{"sequence":1,"loading_order":order,"loading_orders":[order],"arrival":DAY+timedelta(hours=1),"departure":DAY+timedelta(hours=1,minutes=30),"leg_seconds":3600,"leg_distance_meters":50000}],"constraint_violations":[]}
        trips.append(trip)
        assignments.append({"trip_index":i,"master_bay_id":f"B{i}","loading_start":DAY,"loading_finish":DAY+timedelta(minutes=10),"gate_out":trip["gate_out"],"queue_start":DAY,"queue_minutes":0,"loading_minutes":10})
        bays.append({"master_bay_id":f"B{i}","operational_end_minutes":10})
    return p,trips,{"solver_status":"FEASIBLE","assignments":assignments,"dropped_trip_indexes":[],"engine":"TEST"},bays


def run(data):
    p,trips,result,bays=data
    answer=schedule_spbu(trips,result,bays,p,DAY,DAY+timedelta(hours=24),perf_counter()+3)
    return answer,trips


def intervals(trips):
    return sorted((trip["gate_out"]+timedelta(seconds=row["unloading_start_offset_seconds"]),trip["gate_out"]+timedelta(seconds=row["departure_offset_seconds"])) for trip in trips for row in trip["trip_timing"]["spbu_visits"])


def test_same_spbu_waits_without_overlapping_and_updates_clock():
    result,trips=run(fixture_data())
    assert not result["dropped_trip_indexes"]
    slots=intervals(trips)
    assert slots[1][0]>=slots[0][1]
    assert sum(t["spbu_queue_seconds"] for t in trips)==1800
    for t in trips:
        assert t["estimated_return_depot"] == t["gate_out"]+timedelta(seconds=t["trip_timing"]["total_seconds"])
        assert t["stops"][0]["service_minutes"] == 30
        assert sum(e["end_offset_seconds"]-e["start_offset_seconds"] for e in t["trip_timing"]["events"]) == t["trip_timing"]["total_seconds"]


def test_joint_model_can_shift_loading_instead_of_queueing_at_spbu():
    data=fixture_data()
    for bay in data[3]: bay["operational_end_minutes"]=1440
    result,trips=run(data)
    assert not result["dropped_trip_indexes"]
    assert sum(t["spbu_queue_seconds"] for t in trips)==0
    assert abs((trips[1]["loading_start"]-trips[0]["loading_start"]).total_seconds())>=1800
    slots=intervals(trips);assert slots[1][0]>=slots[0][1]


def test_different_spbu_can_unload_at_the_same_time():
    data=fixture_data();data[1][1]["stops"][0]["loading_order"]["spbu_id"]="OTHER"
    result,trips=run(data)
    assert not result["dropped_trip_indexes"]
    assert trips[0]["trip_timing"]["spbu_visits"][0]["unloading_start_offset_seconds"] == trips[1]["trip_timing"]["spbu_visits"][0]["unloading_start_offset_seconds"]


def test_disabled_allows_original_schedule():
    data=fixture_data(constraint_rules={"spbu_no_overlap":{"enabled":False}})
    result,trips=run(data)
    assert "spbu_engine" not in result


def test_soft_overlap_is_allowed_with_audited_penalty():
    result,trips=run(fixture_data(constraint_rules={"spbu_no_overlap":{"mode":"SOFT","penalty":1}}))
    assert not result["dropped_trip_indexes"]
    assert sum(t["spbu_queue_seconds"] for t in trips)==0
    penalties=[v for t in trips for v in t["constraint_violations"] if v["constraint_id"]=="spbu_no_overlap"]
    assert sum(v["penalty"] for v in penalties)==1


def test_receiving_window_can_make_one_visit_infeasible():
    data=fixture_data()
    for trip in data[1]: trip["stops"][0]["loading_order"]["time_window_end_minutes"]=80
    result,trips=run(data)
    assert len(result["dropped_trip_indexes"])==1
    assert len(result["assignments"])==1


def test_immutable_reservations_block_new_unloading_and_merge_old_conflicts():
    data=fixture_data()
    data[0]["_spbu_reservations"]=[{"spbu_id":"S","start_seconds":70*60,"end_seconds":90*60},{"spbu_id":"S","start_seconds":80*60,"end_seconds":110*60}]
    result,trips=run(data)
    assert not result["dropped_trip_indexes"]
    assert intervals(trips)[0][0]>=DAY+timedelta(minutes=110)


def test_timeout_never_publishes_unverified_overlapping_trips():
    p,trips,result,bays=fixture_data()
    answer=schedule_spbu(trips,result,bays,p,DAY,DAY+timedelta(days=1),perf_counter()-1)
    assert answer["solver_status"]=="TIMEOUT" and not answer["assignments"]


def test_routing_engine_changes_mt_allocation_to_satisfy_spbu_capacity():
    orders=[{"loading_order_id":"A1","spbu_id":"A","product_id":"P","volume_kl":8,"allowed_vehicle_ids":["M1","M2"],"phase6_predicted_vehicle_id":"M1","time_window_start_minutes":10,"time_window_end_minutes":20},
            {"loading_order_id":"A2","spbu_id":"A","product_id":"P","volume_kl":8,"allowed_vehicle_ids":["M1","M2"],"phase6_predicted_vehicle_id":"M2","time_window_start_minutes":10,"time_window_end_minutes":20},
            {"loading_order_id":"B","spbu_id":"B","product_id":"P","volume_kl":8,"allowed_vehicle_ids":["M1","M2"],"phase6_predicted_vehicle_id":"M1","time_window_start_minutes":0,"time_window_end_minutes":1440}]
    vehicles=[{"mt_id":m,"capacity_kl":16,"compartments":[{"compartment_id":"C1","capacity_kl":8},{"compartment_id":"C2","capacity_kl":8}],"effective_eta_depot":DAY,"working_time_remaining_minutes":720} for m in ["M1","M2"]]
    d=[[0,10000,10000,10000],[10000,0,0,1000],[10000,0,0,1000],[10000,1000,1000,0]]
    times=[[0,600,600,600],[600,0,0,60],[600,0,0,60],[600,60,60,0]]
    common={"loading_orders":orders,"vehicles":vehicles,"distance_matrix":d,"time_matrix":times,"day_start":DAY,"depot_close":DAY+timedelta(hours=20)}
    base={"objective":"MIN_TOTAL_COST","refueling_minutes":0,"driving_break_minutes":0,"maximum_trips_per_mt":1,"route_optimization_time_limit":2,"phase6_vehicle_change_penalty":1000000}
    disabled=VRPOptimizationService().solve(**common,parameters=effective_parameters({**base,"constraint_rules":{"spbu_no_overlap":{"enabled":False}}}))
    hard=VRPOptimizationService().solve(**common,parameters=effective_parameters(base))
    def owners(result): return {lo["loading_order_id"]:t["vehicle_id"] for t in result["trips"] for lo in t["lo_assignments"]}
    assert not hard["dropped"]
    assert owners(disabled)["A1"]!=owners(disabled)["A2"]
    assert owners(hard)["A1"]==owners(hard)["A2"]


def test_route_feedback_is_scored_after_joint_scheduling(monkeypatch):
    c=OptimizationCoordinatorService();calls=[]
    p=effective_parameters({"objective":"MIN_TOTAL_DISTANCE","spbu_route_search_iterations":2})
    def once(**kwargs):
        calls.append(kwargs)
        meters=100 if len(calls)==1 else 80
        return {"solver_status":"FEASIBLE","dropped":[],"solver_metadata":{},"trips":[{"vehicle_id":"M","distance_meters":meters,"operating_minutes":100,"constraint_violations":[],"stops":[{"loading_order":{"spbu_id":"A"}},{"loading_order":{"spbu_id":"B"}}]}]}
    monkeypatch.setattr(c,"_optimize_once",once)
    result=c.optimize(parameters=p,loading_orders=[{"spbu_id":"A"},{"spbu_id":"A"}],vehicles=[])
    assert len(calls)==2 and calls[1]["parameters"]["_spbu_first_stop_penalties"]["A"]>0
    assert result["trips"][0]["distance_meters"]==80
    assert result["solver_metadata"]["spbu_route_candidates"][1]["accepted"]


def test_queue_delays_propagate_to_next_trip_of_same_mt():
    data=fixture_data()
    p,trips,result,bays=data
    p["_spbu_reservations"]=[{"spbu_id":"S","start_seconds":70*60,"end_seconds":130*60}]
    next_trip=copy.deepcopy(trips[0]);next_trip["trip_number"]=2
    next_trip["stops"][0]["loading_order"]["spbu_id"]="OTHER"
    next_trip["vehicle_ready_at_depot"]=DAY+timedelta(minutes=190)
    next_trip["gate_out"]=DAY+timedelta(minutes=200)
    next_trip["estimated_return_depot"]=DAY+timedelta(minutes=350)
    next_trip["working_time_remaining_before_trip"]=560
    trips.append(next_trip)
    assignment=copy.deepcopy(result["assignments"][0]);assignment.update(trip_index=2,master_bay_id="B2",loading_start=DAY+timedelta(minutes=190),loading_finish=DAY+timedelta(minutes=200),gate_out=next_trip["gate_out"])
    result["assignments"].append(assignment);bays.append({"master_bay_id":"B2","operational_end_minutes":1440})
    answer,trips=run(data)
    assert not answer["dropped_trip_indexes"]
    assert trips[2]["loading_start"] >= trips[0]["estimated_return_depot"]+timedelta(minutes=30)
    assert trips[2]["loading_start"]>DAY+timedelta(minutes=190)
    assert trips[2]["vehicle_ready_at_depot"]>=trips[0]["estimated_return_depot"]+timedelta(minutes=30)


def test_queue_time_is_included_in_hard_working_limit():
    data=fixture_data()
    for trip in data[1]: trip["working_time_remaining_before_trip"]=165
    result,trips=run(data)
    assert len(result["assignments"])==1 and len(result["dropped_trip_indexes"])==1


def test_soft_receiving_window_after_queue_is_audited():
    data=fixture_data(constraint_rules={"spbu_time_window":{"mode":"SOFT","penalty":1}})
    for trip in data[1]: trip["stops"][0]["loading_order"]["time_window_end_minutes"]=80
    result,trips=run(data)
    assert not result["dropped_trip_indexes"]
    assert any(v["constraint_id"]=="spbu_time_window" for t in trips for v in t["constraint_violations"])


from test_phase7_job_adjustments import workspace, NOW, add


def test_coordinated_unloading_is_persisted_and_exposed_in_route_details(workspace,monkeypatch):
    from datetime import time
    from app.models import MasterMT, MasterDepot, MasterSPBU, OptimizationJob, MasterLoadingBay, ProductCompartmentLoadingDuration, VehicleOperationalState, BridgeMTTag
    from app.phase7_service import run_optimization
    from app.phase7_matrix import RouteMatrixService
    db,client=workspace
    depot=db.get(MasterDepot,"D");depot.timezone="UTC";depot.latitude=0;depot.longitude=100
    job=db.get(OptimizationJob,"J");job.depot_operational_start=time(0);job.depot_operational_end=time(23,59)
    spbu=db.get(MasterSPBU,"S");spbu.latitude=1;spbu.longitude=100
    db.add(MasterMT(mt_id="M2",vehicle_name_raw="MT2",depot_id="D",vehicle_type_tag=8));db.flush()
    db.add(BridgeMTTag(mt_id="M2",tag_id="T"))
    db.add(VehicleOperationalState(vehicle_state_id="V2",job_id="J",mt_id="M2",vehicle_class=8,capacity_kl=8,number_of_compartments=1,compartment_configuration=[{"compartment_id":"C1","capacity_kl":8}],planned_eta_depot=NOW))
    for i in range(2):db.add(MasterLoadingBay(master_bay_id=f"B{i}",depot_id="D",bay_id=f"B{i}",bay_name="Bay",all_products_allowed=True,operational_start=time(0),operational_end=time(0,10)))
    db.add(ProductCompartmentLoadingDuration(loading_duration_id="DUR",depot_id="D",product_id="P",duration_minutes_per_compartment=10))
    db.commit()
    assert add(client,"A1").status_code==201
    assert add(client,"A2").status_code==201
    monkeypatch.setattr(RouteMatrixService,"build",lambda *a,**kw:{"distance_matrix":[[0,10000,10000],[10000,0,0],[10000,0,0]],"time_matrix":[[0,3600,3600],[3600,0,0],[3600,0,0]],"geometry":{},"metadata":{}})
    monkeypatch.setattr(RouteMatrixService,"build_route_geometry",lambda *a,**kw:{"route_geometry":[],"route_geometry_source":"TEST"})
    result=run_optimization(db,"J",{"current_time":NOW.isoformat(),"route_time_limit_confirmed":True,"parameters":{"refueling_minutes":0,"driving_break_minutes":0,"gate_process_time":0,"maximum_trips_per_mt":1,"route_optimization_time_limit":2,"bay_optimization_time_limit":5,"spbu_route_search_iterations":1}},reroute=False)
    assert len(result["trips"])==2,result
    stops=[stop for trip in result["trips"] for stop in trip["stops"]]
    assert sum(stop["spbu_queue_seconds"] for stop in stops)==1800
    assert all(stop["service_minutes"]==30 for stop in stops)
    slots=sorted((datetime.fromisoformat(s["unloading_start_time"]),datetime.fromisoformat(s["departure_time"])) for s in stops)
    assert slots[1][0]>=slots[0][1]
    assert sum(trip["cost_breakdown"]["queue_cost"] for trip in result["trips"])==30000
