import copy
from datetime import timedelta
from time import perf_counter
import pytest
from app.phase7_constants import effective_parameters
from app.phase7_timing import spbu_stop_service, pairing_distance_violations, trip_clock
from app.phase7_optimization import VRPOptimizationService
from test_phase7_dynamic_vrp import parameters, vehicle, loading_order, DAY_START


def test_administration_once_and_sequential_unique_compartments():
    p = effective_parameters({})
    assert p["discharge_minutes_per_compartment"] == 15
    rows = [{"compartment_id": "C1"}, {"compartment_id": "C1"}, {"compartment_id": "C2"}]
    service = spbu_stop_service(rows, p)
    assert service == {"administration_seconds": 1800, "discharge_seconds": 1800, "unloaded_compartment_count": 2, "service_seconds": 3600}
    clock = trip_clock([600, 600, 600], [3600, 2700], {"refueling_minutes": 0, "driving_break_minutes": 0})
    assert clock["departure_offsets"] == [4200, 7500]
    assert clock["total_seconds"] == 8100


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf"), 20001])
def test_invalid_pairing_limits_rejected(limit):
    with pytest.raises(ValueError):
        effective_parameters({"constraint_rules": {"spbu_pairing_distance": {"limit_km": limit}}})


def test_all_pairs_and_asymmetric_distance_count_each_pair_once():
    p = effective_parameters({"constraint_rules": {"spbu_pairing_distance": {"mode": "SOFT", "limit_km": 25, "penalty": 100}}})
    orders = [{"spbu_id": s, "matrix_node_index": n} for s, n in [("A", 1), ("A", 1), ("B", 2), ("C", 3)]]
    matrix = [[0, 0, 0, 0], [0, 0, 10000, 40000], [0, 12000, 0, 18000], [0, 41000, 18000, 0]]
    violations = pairing_distance_violations(orders, matrix, p)
    assert len(violations) == 1
    assert violations[0]["spbu_ids"] == ["A", "C"]
    assert violations[0]["penalty"] == 1600
    assert violations[0]["excess_km"] == 16


@pytest.mark.parametrize("mode,expected_trips", [("HARD", 2), ("SOFT", 1), ("SOFT_HIGH", 2), ("DISABLED", 1)])
def test_routing_checks_non_adjacent_pair_not_just_route_edges(mode, expected_trips):
    rules = {"spbu_pairing_distance": {"mode": "HARD" if mode == "HARD" else "SOFT", "enabled": mode != "DISABLED", "limit_km": 20, "penalty": 1000000 if mode == "SOFT_HIGH" else 1},
             "vehicle_full_load": {"enabled": False}}
    matrix = [[0, 1000, 1000, 1000], [1000, 0, 10000, 40000], [1000, 10000, 0, 10000], [1000, 40000, 10000, 0]]
    result = VRPOptimizationService().solve(
        loading_orders=[loading_order(f"L{i}", station, allowed=["M1", "M2"]) for i, station in enumerate(["A", "B", "C"])],
        vehicles=[vehicle("M1", capacity=24, compartments=3), vehicle("M2", capacity=24, compartments=3)],
        distance_matrix=matrix, time_matrix=[[0 if a==b else 60 for b in range(4)] for a in range(4)],
        day_start=DAY_START, depot_close=DAY_START+timedelta(hours=18),
        parameters=parameters(constraint_rules=rules, vehicle_activation_cost_rules=[{"activation_cost": 1000000}], refueling_minutes=0, driving_break_minutes=0, route_optimization_time_limit=1))
    assert not result["dropped"], result
    assert len(result["trips"]) == expected_trips
    if mode == "SOFT":
        violations = [v for t in result["trips"] for v in t["constraint_violations"] if v["constraint_id"] == "spbu_pairing_distance"]
        assert len(violations) == 1
        assert violations[0]["penalty"] == 20


def test_solver_service_uses_assigned_compartments_at_each_spbu():
    result = VRPOptimizationService().solve(loading_orders=[loading_order("L1", "S"), loading_order("L2", "S")],
        vehicles=[vehicle("M1", capacity=16, compartments=2)], distance_matrix=[[0, 1000, 1000], [1000, 0, 0], [1000, 0, 0]],
        time_matrix=[[0, 60, 60], [60, 0, 0], [60, 0, 0]], day_start=DAY_START, depot_close=DAY_START+timedelta(hours=18),
        parameters=parameters(default_spbu_service_minutes=30, refueling_minutes=0, driving_break_minutes=0, route_optimization_time_limit=1))
    trip = result["trips"][0]
    assert len(trip["stops"]) == 1
    assert trip["service_seconds"] == 3600
    assert trip["stops"][0]["unloaded_compartment_count"] == 2
    assert (trip["stops"][0]["departure"]-trip["stops"][0]["arrival"]).total_seconds() == 3600
    assert trip["operating_minutes"] == 62


def test_updated_service_occupies_spbu_slot_and_increases_queue():
    from test_phase7_spbu_queue import fixture_data
    from app.phase7_spbu import schedule_spbu
    p, trips, result, bays = fixture_data()
    for i, trip in enumerate(trips):
        duration = 3600 if i == 0 else 2700
        trip["stops"][0]["departure"] = trip["stops"][0]["arrival"] + timedelta(seconds=duration)
        trip["estimated_return_depot"] += timedelta(seconds=duration-1800)
        trip["trip_timing"] = trip_clock([3600,3600], [duration], p)
        if i == 1:
            trip["stops"][0]["arrival"] += timedelta(minutes=20)
            trip["stops"][0]["departure"] += timedelta(minutes=20)
            trip["stops"][0]["leg_seconds"] = 4800
            trip["estimated_return_depot"] += timedelta(minutes=20)
            trip["trip_timing"] = trip_clock([4800,3600], [duration], p)
    # Fixed gate times (bay end) force the second MT to wait at the SPBU.
    answer = schedule_spbu(trips,result,bays,p,trips[0]["vehicle_ready_at_depot"],trips[0]["vehicle_ready_at_depot"]+timedelta(days=1),perf_counter()+3)
    assert not answer["dropped_trip_indexes"]
    assert sum(t["spbu_queue_seconds"] for t in trips) == 2400
    for t in trips:
        assert t["estimated_return_depot"] == t["gate_out"] + timedelta(seconds=t["trip_timing"]["total_seconds"])


@pytest.mark.parametrize("enabled", [True, False])
def test_pairing_boundary_and_sum_of_distinct_pairs(enabled):
    p = effective_parameters({"constraint_rules": {"spbu_pairing_distance": {"enabled": enabled, "mode": "SOFT", "limit_km": 20, "penalty": 100}}})
    orders = [{"spbu_id": station, "matrix_node_index": n} for n, station in enumerate(["A", "B", "C"], 1)]
    matrix = [[0,0,0,0], [0,0,20000,30000], [0,20000,0,25000], [0,30000,25000,0]]
    violations = pairing_distance_violations(orders, matrix, p)
    assert sum(v["penalty"] for v in violations) == (1500 if enabled else 0)
    assert len(violations) == (2 if enabled else 0)


def test_separate_spbu_each_gets_one_administration_and_its_own_compartments():
    p = effective_parameters({"refueling_minutes": 0, "driving_break_minutes": 0})
    first = spbu_stop_service([{"compartment_id": "C1"}, {"compartment_id": "C2"}], p)
    second = spbu_stop_service([{"compartment_id": "C3"}], p)
    assert first["service_seconds"] == 3600
    assert second["service_seconds"] == 2700
    assert trip_clock([0,0,0], [first["service_seconds"],second["service_seconds"]], p)["total_seconds"] == 6300


def test_hard_pairing_distance_fallback_checks_every_selected_station(monkeypatch):
    from app import phase7_optimization
    monkeypatch.setattr(phase7_optimization, "ORTOOLS_AVAILABLE", False)
    orders = [loading_order(f"L{i}", station) for i, station in enumerate(["A", "B", "C"])]
    matrix = [[0,1000,1000,1000], [1000,0,10000,40000], [1000,10000,0,10000], [1000,40000,10000,0]]
    result = VRPOptimizationService().solve(loading_orders=orders, vehicles=[vehicle("M1", capacity=24, compartments=3)],
        distance_matrix=matrix, time_matrix=[[0 if a==b else 60 for b in range(4)] for a in range(4)], day_start=DAY_START,
        depot_close=DAY_START+timedelta(hours=18), parameters=parameters(constraint_rules={"vehicle_full_load": {"enabled": False},
            "spbu_pairing_distance": {"mode": "HARD", "limit_km": 20}}, refueling_minutes=0, driving_break_minutes=0))
    assert not result["dropped"]
    for trip in result["trips"]:
        stations = {row["spbu_id"] for row in trip["lo_assignments"]}
        assert not {"A", "C"}.issubset(stations)
