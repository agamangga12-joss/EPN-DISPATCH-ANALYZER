"""Regression coverage for the real FT Tembilahan geometry/matrix bottleneck."""
import random
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident

import pytest
from sqlalchemy import event, select

from app import phase7_matrix, restricted_roads
from app.models import MasterDepot, MasterSPBU, RouteMatrixCache
from app.phase7_constants import effective_parameters
from app.phase7_matrix import RouteMatrixService
from app.restricted_roads import GoogleRequestBudget, RestrictedRoadRouter, RestrictedRoutingError, restriction_snapshot
from test_restricted_roads import NOW, create_road, workspace


def brute_force_conflicts(geometry, roads):
    """Original exhaustive detector as an independent spatial-index oracle."""
    import math
    points = [[p["longitude"], p["latitude"]] for p in geometry]
    found = {}
    for road in roads:
        mode = road.get("direction", "BOTH")
        for a, b in zip(road["geometry"], road["geometry"][1:]):
            rings = restricted_roads.corridor_polygons([{**road, "geometry": [a, b]}])
            if not rings:
                continue
            ring = rings[0]
            def inside(p):
                signs = [restricted_roads._cross(e, f, p) for e, f in zip(ring, ring[1:])]
                return all(s >= 0 for s in signs) or all(s <= 0 for s in signs)
            for position, (c, d) in enumerate(zip(points, points[1:])):
                if c == d or not (inside(c) or inside(d) or any(
                    restricted_roads._intersects(c, d, e, f) for e, f in zip(ring, ring[1:]))):
                    continue
                sx = math.cos(math.radians((a[1] + b[1]) / 2))
                rx, ry = (b[0] - a[0]) * sx, b[1] - a[1]
                tx, ty = (d[0] - c[0]) * sx, d[1] - c[1]
                dot, scale = rx * tx + ry * ty, math.hypot(rx, ry) * math.hypot(tx, ty)
                forward, ambiguous = dot >= 0, abs(dot) <= scale * 0.15
                if mode != "BOTH" and not ambiguous and (mode == "FORWARD") != forward:
                    continue
                direction = mode if mode != "BOTH" and ambiguous else ("FORWARD" if forward else "REVERSE")
                key = road["restricted_road_id"], direction
                found[key] = min(position, found.get(key, position))
    return sorted((road, direction, position) for (road, direction), position in found.items())


def test_spatial_index_matches_exhaustive_detection_for_curved_and_directional_roads():
    rng = random.Random(29026)
    for _ in range(80):
        def point():
            return [106 + rng.uniform(-0.02, 0.02), -6 + rng.uniform(-0.02, 0.02)]
        roads = [{"restricted_road_id": str(i), "geometry": [point() for _ in range(4)],
                  "buffer_meters": rng.choice([2, 12, 100]), "direction": rng.choice(["BOTH", "FORWARD", "REVERSE"])} for i in range(5)]
        points = [point() for _ in range(12)]
        geometry = [{"longitude": p[0], "latitude": p[1]} for p in points]
        indexed = restricted_roads.geometry_conflict_details(geometry, roads)
        assert sorted((item["road"]["restricted_road_id"], item["direction"], item["position"]) for item in indexed) == brute_force_conflicts(geometry, roads)


def test_distant_dense_geometry_is_rejected_by_bounds_before_exact_polygon_checks(monkeypatch):
    roads = [{"restricted_road_id": "dense", "geometry": [[106 + i * 0.00001, -6] for i in range(1863)], "buffer_meters": 12}]
    geometry = [{"longitude": 104 + i * 0.00001, "latitude": -4} for i in range(4774)]
    def unexpected_exact_check(*args):
        raise AssertionError("Distant route/road segments must not enter exact intersection checks")
    monkeypatch.setattr(restricted_roads, "_cross", unexpected_exact_check)
    assert restricted_roads.geometry_conflict_details(geometry, roads) == []


def test_shared_google_budget_never_overshoots_with_concurrent_workers():
    budget = GoogleRequestBudget(7)
    def consume(_):
        try:
            budget.consume()
            return True
        except RestrictedRoutingError as exc:
            assert exc.code == "RESTRICTED_GOOGLE_REQUEST_BUDGET"
            return False
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(consume, range(100))) == 7
    assert budget.used == 7


def matrix_inputs(workspace):
    db, client = workspace
    create_road(client)
    db.add_all([MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="One", latitude=-6, longitude=106.01),
                MasterSPBU(spbu_id="S2", spbu_code="S2", spbu_name="Two", latitude=-6, longitude=106.02)])
    db.commit()
    return {"depot": db.get(MasterDepot, "D1"), "loading_orders": [{"spbu_id": "S1"}, {"spbu_id": "S2"}, {"spbu_id": "S1"}],
            "spbus": {key: db.get(MasterSPBU, key) for key in ("S1", "S2")}, "departure": NOW,
            "parameters": {**effective_parameters({}), "restricted_roads": restriction_snapshot(db, "D1", NOW)}}


def estimate(coords):
    return {"distance_meters": 19000, "duration_seconds": 1200, "route_geometry": [
        {"longitude": p[0], "latitude": p[1]} for p in coords], "provider": "GOOGLE_RESTRICTED_WAYPOINTS",
        "metadata": {"restriction_checked": True, "request_count": 1}}


def test_parallel_matrix_keeps_database_work_on_coordinator_and_reuses_cache(workspace, monkeypatch):
    db, _ = workspace
    inputs = matrix_inputs(workspace)
    inputs["parameters"].update({"restricted_matrix_workers": 3, "restricted_matrix_time_limit_seconds": 123,
                                 "route_matrix_time_limit_seconds": 1})
    main_thread, worker_threads, calls = get_ident(), set(), []
    barrier = Barrier(3, timeout=5)
    def route(self, coords, roads, **kwargs):
        worker_threads.add(get_ident())
        kwargs["request_budget"].consume()
        barrier.wait()
        calls.append(coords)
        return estimate(coords)
    monkeypatch.setattr(RestrictedRoadRouter, "route", route)
    def assert_coordinator(*args):
        assert get_ident() == main_thread
    event.listen(db.get_bind(), "before_cursor_execute", assert_coordinator)
    progress = []
    try:
        result = RouteMatrixService(db).build(**inputs, progress_callback=lambda p: (progress.append(p), db.commit()))
        assert len(calls) == 6  # three unique locations, both directions
        assert len(worker_threads) == 3 and main_thread not in worker_threads
        assert result["metadata"]["google_request_count"] == 6
        assert result["metadata"]["time_limit_seconds"] == 123
        assert progress[-1]["completed_unique_pairs"] == 6
        cached = RouteMatrixService(db).build(**inputs)
        assert cached["metadata"]["cache_hit_count"] == 6
        assert cached["metadata"]["google_request_count"] == 0 and len(calls) == 6
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", assert_coordinator)


def test_matrix_timeout_retains_completed_pairs_and_stops_scheduling(workspace, monkeypatch):
    db, _ = workspace
    inputs = matrix_inputs(workspace)
    inputs["parameters"].update({"restricted_matrix_workers": 2, "restricted_matrix_time_limit_seconds": 1})
    clock = [0.0]
    monkeypatch.setattr(phase7_matrix, "perf_counter", lambda: clock[0])
    calls = []
    def route(self, coords, roads, **kwargs):
        kwargs["request_budget"].consume()
        calls.append(coords)
        clock[0] = 2.0
        return estimate(coords)
    monkeypatch.setattr(RestrictedRoadRouter, "route", route)
    with pytest.raises(RestrictedRoutingError) as error:
        RouteMatrixService(db).build(**inputs, progress_callback=lambda p: db.commit())
    assert error.value.code == "RESTRICTED_MATRIX_TIME_LIMIT"
    assert len(calls) == 2
    assert len(db.scalars(select(RouteMatrixCache)).all()) == 2


def test_restricted_matrix_defaults_and_bounds():
    assert effective_parameters({})["restricted_matrix_time_limit_seconds"] == 900
    assert effective_parameters({})["restricted_matrix_workers"] == 4
    for values in ({"restricted_matrix_workers": 0}, {"restricted_matrix_workers": 17}, {"restricted_matrix_time_limit_seconds": 0}):
        with pytest.raises(ValueError):
            effective_parameters(values)
