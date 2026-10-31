from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import get_db
from app.google_routes import get_google_routes_configuration, encrypt_api_key
from app.models import Base, MasterDepot, MasterRestrictedRoad, MasterSPBU, RouteMatrixCache
from app.phase7_constants import effective_parameters
from app.phase7_matrix import RouteMatrixService
from app.phase7_optimization import VRPOptimizationService
from app.restricted_road_routes import router
from app.restricted_roads import RestrictedRoadRouter, RestrictedRoutingError, UNREACHABLE, geometry_conflicts, restriction_snapshot

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)
ROAD = {"restricted_road_id": "R1", "name": "Narrow road", "geometry": [[106, -6.01], [106, -5.99]], "buffer_meters": 12}
DETOUR = [[105.99, -6], [105.99, -6.02], [106.01, -6.02], [106.01, -6]]


@pytest.fixture
def workspace(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(get_settings(), "google_routes_encryption_key", "test-encryption-key-at-least-16-chars")
    with Session(engine) as db:
        db.add_all([MasterDepot(depot_id="D1", depot_name="Depot 1", latitude=-6, longitude=105.99),
                    MasterDepot(depot_id="D2", depot_name="Depot 2")])
        configuration = get_google_routes_configuration(db)
        configuration.encrypted_api_key = encrypt_api_key("test-google-key")
        db.commit()
        app = FastAPI()
        app.include_router(router)
        def session():
            yield db
        app.dependency_overrides[get_db] = session
        yield db, TestClient(app)
    engine.dispose()


def create_road(client, **overrides):
    return client.post("/api/v1/depots/D1/restricted-roads", json={
        "name": "Narrow road", "reason": "Tankers cannot pass", "geometry": ROAD["geometry"],
        "buffer_meters": 12, "geometry_confirmed": True, "direction": "BOTH",
        "forward_waypoints": [[105.99, -6.02], [106.01, -6.02]],
        "reverse_waypoints": [[106.01, -6.02], [105.99, -6.02]], **overrides,
    })


def test_master_scope_confirmation_revision_and_disable(workspace):
    db, client = workspace
    assert create_road(client, geometry_confirmed=False).status_code == 422
    created = create_road(client)
    assert created.status_code == 201
    road = created.json()
    assert road["revision"] == 1
    assert client.get("/api/v1/depots/D2/restricted-roads").json()["roads"] == []
    url = f"/api/v1/depots/D1/restricted-roads/{road['restricted_road_id']}"
    assert client.put(url.replace("D1", "D2"), json={**road, "geometry_confirmed": True}).status_code == 404
    result = client.put(url, json={**road, "geometry_confirmed": True, "active": False})
    assert result.status_code == 200
    assert result.json()["revision"] == 2
    assert client.put(url, json={**road, "geometry_confirmed": True}).status_code == 409
    assert restriction_snapshot(db, "D1", NOW)["roads"] == []
    assert db.get(MasterRestrictedRoad, road["restricted_road_id"]) is not None


@pytest.mark.parametrize("overrides", [
    {"geometry": [[106, -6], [106, -6]]}, {"geometry": [[181, 0], [106, -6]]},
    {"buffer_meters": 0}, {"name": "  "}, {"valid_from": "2026-10-28T00:00:00"},
    {"valid_from": "2026-10-29T00:00:00+07:00", "valid_until": "2026-10-28T00:00:00+07:00"},
])
def test_master_rejects_invalid_restrictions(workspace, overrides):
    _, client = workspace
    assert create_road(client, **overrides).status_code == 422


def test_validity_includes_upcoming_closures_and_snapshot_is_immutable(workspace):
    db, client = workspace
    road = create_road(client, valid_from=(NOW + timedelta(hours=20)).isoformat()).json()
    old = restriction_snapshot(db, "D1", NOW)
    assert len(old["roads"]) == 1
    client.put(f"/api/v1/depots/D1/restricted-roads/{road['restricted_road_id']}",
               json={**road, "geometry_confirmed": True, "name": "Changed", "valid_until": (NOW + timedelta(hours=21)).isoformat()})
    assert restriction_snapshot(db, "D1", NOW)["checksum"] != old["checksum"]
    assert old["roads"][0]["name"] == "Narrow road"
    assert restriction_snapshot(db, "D1", NOW + timedelta(hours=22))["roads"] == []


def test_intersections_detect_sparse_crossing_parallel_and_reverse_routes():
    def shape(points):
        return [{"longitude": x, "latitude": y} for x, y in points]
    direct = [[105.99, -6], [106.01, -6]]
    assert geometry_conflicts(shape(direct), [ROAD]) == ["R1"]
    assert geometry_conflicts(shape(list(reversed(direct))), [ROAD]) == ["R1"]
    assert geometry_conflicts(shape(DETOUR), [ROAD]) == []
    assert geometry_conflicts(shape([[106.001, -6.01], [106.001, -5.99]]), [ROAD]) == []






def test_restricted_matrix_uses_detour_metrics_and_exact_geometry_and_invalidates_cache(workspace, monkeypatch):
    db, client = workspace
    road = create_road(client).json()
    depot = db.get(MasterDepot, "D1")
    spbu = MasterSPBU(spbu_id="S1", spbu_code="S1", spbu_name="Station", latitude=-6, longitude=106.01)
    db.add(spbu)
    db.commit()
    calls = []
    def route(self, coords, roads, **kwargs):
        calls.append(coords)
        shape = DETOUR if coords[0][0] < coords[1][0] else list(reversed(DETOUR))
        return {"distance_meters": 19000, "duration_seconds": 1200, "route_geometry": [
            {"longitude": x, "latitude": y} for x, y in shape], "provider": "GOOGLE_RESTRICTED_WAYPOINTS",
            "metadata": {"restriction_checked": True}}
    monkeypatch.setattr(RestrictedRoadRouter, "route", route)
    parameters = {**effective_parameters({}), "restricted_roads": restriction_snapshot(db, "D1", NOW)}
    def build(service):
        return service.build(depot=depot, loading_orders=[{"spbu_id": "S1"}, {"spbu_id": "S1"}],
            spbus={"S1": spbu}, departure=NOW, parameters=parameters)
    service = RouteMatrixService(db)
    matrix = build(service)
    assert matrix["distance_matrix"][0][1:] == [19000, 19000]
    assert matrix["time_matrix"][0][1:] == [1200, 1200]
    assert len(calls) == 2  # unique locations, including the return direction
    geometry = service.build_route_geometry(depot=depot, ordered_spbus=[spbu], departure=NOW + timedelta(hours=10), parameters=parameters)
    assert geometry["route_geometry_source"] == "GOOGLE_RESTRICTED_WAYPOINTS"
    assert len(calls) == 2  # geometry reuses matrix paths, regardless of trip time
    db.commit()
    assert build(RouteMatrixService(db))["metadata"]["cache_hit_count"] == 2
    assert len(calls) == 2
    client.put(f"/api/v1/depots/D1/restricted-roads/{road['restricted_road_id']}",
               json={**road, "name": "Updated", "geometry_confirmed": True})
    parameters["restricted_roads"] = restriction_snapshot(db, "D1", NOW)
    build(RouteMatrixService(db))
    assert len(calls) == 4
    assert len(db.scalars(select(RouteMatrixCache)).all()) == 4


@pytest.mark.parametrize("serve_mode", ["SOFT", "HARD"])
def test_solver_cannot_use_forbidden_arcs_even_when_time_constraints_disabled(serve_mode):
    parameters = effective_parameters({"optimization_time_limit": 1, "constraint_rules": {
        **{name: {"enabled": False} for name in ("vehicle_working_time", "spbu_time_window", "depot_operating_window")},
        "serve_loading_order": {"enabled": True, "mode": serve_mode}}})
    vehicle = {"mt_id": "M1", "capacity_kl": 8, "vehicle_class": 8, "tags": [],
        "compartments": [{"compartment_id": "C1", "capacity_kl": 8}], "effective_eta_depot": NOW,
        "operational_status": "READY", "working_time_remaining_minutes": 600}
    lo = {"loading_order_id": "L1", "spbu_id": "S1", "product_id": "P1", "volume_kl": 8,
          "allowed_vehicle_ids": ["M1"], "mandatory": False}
    result = VRPOptimizationService().solve(loading_orders=[lo], vehicles=[vehicle],
        distance_matrix=[[0, UNREACHABLE], [100, 0]], time_matrix=[[0, UNREACHABLE], [60, 0]],
        day_start=NOW, depot_close=NOW + timedelta(hours=24), parameters=parameters)
    assert result["trips"] == []
    assert result["dropped"][0]["reason_code"] == "RESTRICTED_ROUTE_REVIEW_REQUIRED"


def test_migration_upgrade_and_downgrade():
    path = Path(__file__).resolve().parents[3] / "db/migrations/versions/0032_restricted_roads.py"
    spec = importlib.util.spec_from_file_location("restricted_road_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        MasterDepot.__table__.create(connection)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert "master_restricted_road" in inspect(connection).get_table_names()
        migration.downgrade()
        assert "master_restricted_road" not in inspect(connection).get_table_names()
    engine.dispose()


def test_restricted_road_migration_extends_the_existing_single_head():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "db/migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["0034_phase7_mt_tag_overrides"]


def test_waypoint_migration_preserves_old_roads_and_marks_them_incomplete():
    root = Path(__file__).resolve().parents[3]
    def migration(name):
        spec = importlib.util.spec_from_file_location(name, root / f"db/migrations/versions/{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    old, new = migration("0032_restricted_roads"), migration("0033_restricted_road_waypoints")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        MasterDepot.__table__.create(connection)
        operations = Operations(MigrationContext.configure(connection))
        old.op, new.op = operations, operations
        old.upgrade()
        connection.execute(text("INSERT INTO master_restricted_road (restricted_road_id,depot_id,name,reason,geometry) VALUES ('OLD','D1','Old road','Narrow','[[106,-6],[106.01,-6]]')"))
        new.upgrade()
        row = connection.execute(text("SELECT name,geometry,direction,forward_waypoints,reverse_waypoints FROM master_restricted_road")).one()
        assert row.name == "Old road" and row.geometry == "[[106,-6],[106.01,-6]]"
        assert row.direction == "BOTH" and row.forward_waypoints == "[]" and row.reverse_waypoints == "[]"
        new.downgrade()
        assert connection.execute(text("SELECT name FROM master_restricted_road")).scalar() == "Old road"
    engine.dispose()


def test_legacy_road_can_be_reviewed_or_disabled_without_losing_geometry(workspace):
    db, client = workspace
    db.add(MasterRestrictedRoad(restricted_road_id="OLD", depot_id="D1", name="Old", reason="Narrow", geometry=ROAD["geometry"]))
    db.commit()
    result = client.get("/api/v1/depots/D1/restricted-roads").json()
    assert result["missing_detour_ids"] == ["OLD"]
    road = result["roads"][0]
    assert client.put("/api/v1/depots/D1/restricted-roads/OLD", json={**road, "geometry_confirmed": True}).status_code == 422
    disabled = client.put("/api/v1/depots/D1/restricted-roads/OLD", json={**road, "active": False, "geometry_confirmed": True})
    assert disabled.status_code == 200
    assert disabled.json()["geometry"] == ROAD["geometry"]


def test_phase7_readiness_uses_google_integration_not_a_local_routing_server(workspace):
    from datetime import date
    from app.models import OptimizationJob
    from app.phase7_service import validate_job
    db, client = workspace
    create_road(client)
    db.add(OptimizationJob(job_id="J1", job_no="J1", job_name="Test", depot_id="D1", operating_date=date(2026, 10, 28)))
    db.commit()
    codes = {item["code"] for item in validate_job(db, "J1")["messages"]}
    assert "RESTRICTED_ROADS_ACTIVE" in codes
    assert "RESTRICTED_ROUTING_NOT_CONFIGURED" not in codes
    configuration = get_google_routes_configuration(db)
    configuration.encrypted_api_key = None
    db.commit()
    codes = {item["code"] for item in validate_job(db, "J1")["messages"]}
    assert "GOOGLE_ROUTES_REQUIRED" in codes


