"""Confirmed road restrictions and bounded Google Routes waypoint detours.

Coordinates in this module are GeoJSON [longitude, latitude]. Restrictions
apply to all MT in the operator-selected direction. A corridor is deliberately
visible to the operator: it may cover neighbouring roads at complex junctions.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from time import perf_counter
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .google_routes import GoogleRoutesClient, GoogleRoutesError, decrypt_api_key, get_google_routes_configuration
from .models import MasterRestrictedRoad

UNREACHABLE = 1_000_000_000


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def road_payload(row):
    result = {key: getattr(row, key) for key in (
        "restricted_road_id", "depot_id", "name", "reason", "geometry", "buffer_meters",
        "active", "revision", "valid_from", "valid_until", "direction", "forward_waypoints", "reverse_waypoints",
    )}
    for key in ("valid_from", "valid_until"):
        if result[key]:
            result[key] = utc(result[key])
    return result


def restriction_snapshot(db: Session, depot_id: str, reference: datetime) -> dict:
    # Include upcoming closures in the next 48 hours, conservatively for the
    # entire plan. Never let a later trip drive through a newly active closure.
    start, end = utc(reference), utc(reference) + timedelta(hours=48)
    rows = db.scalars(select(MasterRestrictedRoad).where(
        MasterRestrictedRoad.depot_id == depot_id, MasterRestrictedRoad.active.is_(True),
    ).order_by(MasterRestrictedRoad.restricted_road_id)).all()
    roads = []
    for row in rows:
        if row.valid_from and utc(row.valid_from) > end:
            continue
        if row.valid_until and utc(row.valid_until) <= start:
            continue
        item = road_payload(row)
        for key in ("valid_from", "valid_until"):
            item[key] = utc(item[key]).isoformat() if item[key] else None
        roads.append(item)
    checksum = hashlib.sha256(json.dumps(roads, sort_keys=True).encode()).hexdigest()
    return {"checksum": checksum, "roads": roads, "scope": "ALL_MT_DIRECTIONAL",
            "reference_time": start.isoformat(), "horizon_end": end.isoformat(),
            "temporal_policy": "CONSERVATIVE_48_HOUR_CORRIDOR"}


def corridor_polygons(roads: list[dict]) -> list[list[list[float]]]:
    polygons = []
    for road in roads:
        width = float(road["buffer_meters"])
        for a, b in zip(road["geometry"], road["geometry"][1:]):
            scale_x = 111_320 * math.cos(math.radians((a[1] + b[1]) / 2))
            scale_y = 111_320
            dx, dy = (b[0] - a[0]) * scale_x, (b[1] - a[1]) * scale_y
            length = math.hypot(dx, dy)
            if length < 0.01:
                continue
            ux, uy = dx / length, dy / length
            ax, ay, bx, by = -ux * width, -uy * width, dx + ux * width, dy + uy * width
            ring = [[a[0] + x / scale_x, a[1] + y / scale_y] for x, y in (
                (ax - uy * width, ay + ux * width), (bx - uy * width, by + ux * width),
                (bx + uy * width, by - ux * width), (ax + uy * width, ay - ux * width),
            )]
            polygons.append([*ring, ring[0]])
    return polygons


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    return _cross(a, b, c) * _cross(a, b, d) <= 0 and _cross(c, d, a) * _cross(c, d, b) <= 0


def _bounds_overlap(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


class RoadRestrictionIndex:
    """Immutable bounding-box tree, retaining full corridor precision.

    Query by complete route-segment bounds (not endpoints alone), so long
    segments that cross a narrow corridor cannot escape detection.
    """
    def __init__(self, roads):
        entries = []
        for road in roads:
            for a, b in zip(road["geometry"], road["geometry"][1:]):
                rings = corridor_polygons([{**road, "geometry": [a, b]}])
                if not rings:
                    continue
                ring = rings[0]
                bounds = (min(p[0] for p in ring), min(p[1] for p in ring),
                          max(p[0] for p in ring), max(p[1] for p in ring))
                sx = math.cos(math.radians((a[1] + b[1]) / 2))
                entries.append((bounds, ring, road, (b[0] - a[0]) * sx, b[1] - a[1], sx))
        self.root = self._build(entries) if entries else None

    @classmethod
    def _build(cls, entries):
        bounds = (min(e[0][0] for e in entries), min(e[0][1] for e in entries),
                  max(e[0][2] for e in entries), max(e[0][3] for e in entries))
        if len(entries) <= 8:
            return bounds, entries, None, None
        axis = 0 if bounds[2] - bounds[0] >= bounds[3] - bounds[1] else 1
        entries.sort(key=lambda e: e[0][axis] + e[0][axis + 2])
        middle = len(entries) // 2
        return bounds, None, cls._build(entries[:middle]), cls._build(entries[middle:])

    def candidates(self, bounds):
        pending = [self.root] if self.root else []
        while pending:
            node_bounds, entries, left, right = pending.pop()
            if not _bounds_overlap(bounds, node_bounds):
                continue
            if entries is not None:
                for entry in entries:
                    if _bounds_overlap(bounds, entry[0]):
                        yield entry
            else:
                pending.extend((left, right))


def geometry_conflict_details(geometry: list[dict], roads: list[dict], *, index=None) -> list[dict]:
    """Exact corridor/direction checks after conservative spatial filtering."""
    points = [[p["longitude"], p["latitude"]] for p in geometry]
    if len(points) < 2:
        return []
    index = index if index is not None else RoadRestrictionIndex(roads)
    found = {}
    for position, (c, d) in enumerate(zip(points, points[1:])):
        if c == d:
            continue
        bounds = (min(c[0], d[0]), min(c[1], d[1]), max(c[0], d[0]), max(c[1], d[1]))
        for _, ring, road, rx, ry, sx in index.candidates(bounds):
            def inside(p):
                signs = [_cross(a, b, p) for a, b in zip(ring, ring[1:])]
                return all(v >= 0 for v in signs) or all(v <= 0 for v in signs)
            if not (inside(c) or inside(d) or any(_intersects(c, d, a, b) for a, b in zip(ring, ring[1:]))):
                continue
            tx, ty = (d[0] - c[0]) * sx, d[1] - c[1]
            dot = rx * tx + ry * ty
            scale = math.hypot(rx, ry) * math.hypot(tx, ty)
            forward, ambiguous = dot >= 0, abs(dot) <= scale * 0.15
            mode = road.get("direction", "BOTH")
            if mode != "BOTH" and not ambiguous and (mode == "FORWARD") != forward:
                continue
            direction = mode if mode != "BOTH" and ambiguous else ("FORWARD" if forward else "REVERSE")
            key = road["restricted_road_id"], direction
            if key not in found:
                found[key] = {"road": road, "direction": direction, "position": position}
    return sorted(found.values(), key=lambda item: (item["position"], item["road"]["restricted_road_id"], item["direction"]))


def geometry_conflicts(geometry: list[dict], roads: list[dict]) -> list[str]:
    return list(dict.fromkeys(item["road"]["restricted_road_id"] for item in geometry_conflict_details(geometry, roads)))


def missing_detours(roads: list[dict]) -> list[str]:
    return [road["restricted_road_id"] for road in roads
            if (road.get("direction", "BOTH") in {"BOTH", "FORWARD"} and not road.get("forward_waypoints"))
            or (road.get("direction", "BOTH") in {"BOTH", "REVERSE"} and not road.get("reverse_waypoints"))]


class RestrictedRoutingError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class GoogleRequestBudget:
    """Share one logical-request limit across all restricted matrix workers."""
    def __init__(self, limit):
        self.limit = max(0, int(limit))
        self._used = 0
        self._lock = Lock()

    @property
    def used(self):
        with self._lock:
            return self._used

    def consume(self):
        with self._lock:
            if self._used >= self.limit:
                raise RestrictedRoutingError("RESTRICTED_GOOGLE_REQUEST_BUDGET", "Google request budget exhausted before restricted-road verification completed. Increase the matrix budget.")
            self._used += 1


class RestrictedRoadRouter:
    PROVIDER = "GOOGLE_RESTRICTED_WAYPOINTS"
    MAX_ATTEMPTS = 8

    def __init__(self, db: Session | None = None, *, client=None):
        self.client = client
        self.configuration_version = None
        if db is not None:
            configuration = get_google_routes_configuration(db, create=False)
            if configuration:
                self.configuration_version = configuration.configuration_version
                if self.client is None and configuration.encrypted_api_key:
                    try:
                        self.client = GoogleRoutesClient(decrypt_api_key(configuration.encrypted_api_key))
                    except Exception:
                        self.client = None

    @property
    def enabled(self):
        return self.client is not None

    def route(self, coordinates: list[list[float]], roads: list[dict], *, departure=None,
              traffic_aware=True, request_budget=None, deadline=None, cancel_event=None) -> dict:
        if not self.enabled:
            raise RestrictedRoutingError("GOOGLE_ROUTES_REQUIRED", "Configure a valid Google Routes API key in Google Maps Integration before routing restricted roads.")
        if missing_detours(roads):
            raise RestrictedRoutingError("RESTRICTED_DETOUR_REQUIRED", "Active restricted roads need ordered detour waypoints for every applicable direction.")
        geometry_index = RoadRestrictionIndex(roads)
        started = perf_counter()
        geometry_seconds = 0.0
        groups, via_order, applied, seen = [], [], set(), set()
        calls = 0
        last_conflicts = []
        def unresolved(reason):
            return {"distance_meters": UNREACHABLE, "duration_seconds": UNREACHABLE,
                    "route_geometry": [], "provider": "GOOGLE_RESTRICTED_UNRESOLVED",
                    "metadata": {"restriction_checked": True, "review_required": True,
                        "reason": reason, "request_count": calls, "conflicting_road_ids": last_conflicts,
                        "detours": groups, "elapsed_seconds": round(perf_counter() - started, 3),
                        "geometry_check_seconds": round(geometry_seconds, 3), "message": "Configured Google waypoint candidates did not yield a permitted route. This does not prove that no road alternative exists."}}
        for _ in range(self.MAX_ATTEMPTS):
            if deadline is not None and perf_counter() >= deadline:
                raise RestrictedRoutingError("RESTRICTED_MATRIX_TIME_LIMIT", "Restricted road matrix time limit exceeded. Increase Restricted Matrix Time Limit in the parameter profile.")
            if cancel_event is not None and cancel_event.is_set():
                raise RestrictedRoutingError("RESTRICTED_MATRIX_CANCELLED", "Restricted matrix processing stopped after another pair failed.")
            via = [entry["point"] for entry in via_order]
            if len(via) > 25:
                return unresolved("WAYPOINT_LIMIT")
            signature = json.dumps(via)
            if signature in seen:
                return unresolved("DETOUR_CYCLE")
            seen.add(signature)
            if isinstance(request_budget, GoogleRequestBudget):
                request_budget.consume()
            elif request_budget is not None and calls >= request_budget:
                raise RestrictedRoutingError("RESTRICTED_GOOGLE_REQUEST_BUDGET", "Google request budget exhausted before restricted-road verification completed. Increase the matrix budget.")
            calls += 1
            try:
                response = self.client.compute_route(
                    origin=(coordinates[0][1], coordinates[0][0]),
                    destination=(coordinates[-1][1], coordinates[-1][0]),
                    departure_datetime=departure if traffic_aware else None,
                    routing_mode="DRIVE", routing_preference="TRAFFIC_AWARE" if traffic_aware else "TRAFFIC_UNAWARE",
                    intermediates=[(p[1], p[0]) for p in via] or None,
                    via_intermediates=True, high_quality=True,
                )
            except GoogleRoutesError as exc:
                if exc.code == "GOOGLE_ROUTE_NOT_FOUND":
                    return unresolved("GOOGLE_CANDIDATE_NOT_FOUND")
                raise RestrictedRoutingError(exc.code, str(exc)) from exc
            geometry = response.get("route_geometry") or []
            try:
                valid = len(geometry) >= 2 and all(
                    math.isfinite(p["longitude"]) and math.isfinite(p["latitude"])
                    and -180 <= p["longitude"] <= 180 and -90 <= p["latitude"] <= 90 for p in geometry)
                distance, duration = float(response["distance_meters"]), float(response["duration_seconds"])
                valid = valid and math.isfinite(distance) and math.isfinite(duration) and distance >= 0 and duration >= 0
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                raise RestrictedRoutingError("GOOGLE_RESTRICTED_GEOMETRY_INVALID", "Google returned invalid road geometry or timing; no unrestricted fallback is allowed.")
            # Also check endpoint access; snapping must not jump across a closure.
            access = [{"longitude": coordinates[0][0], "latitude": coordinates[0][1]},
                      *geometry, {"longitude": coordinates[-1][0], "latitude": coordinates[-1][1]}]
            check_started = perf_counter()
            conflicts = geometry_conflict_details(access, roads, index=geometry_index)
            geometry_seconds += perf_counter() - check_started
            last_conflicts = list(dict.fromkeys(item["road"]["restricted_road_id"] for item in conflicts))
            if not conflicts:
                return {"distance_meters": round(distance), "duration_seconds": max(1, math.ceil(duration)),
                        "route_geometry": geometry, "provider": self.PROVIDER,
                        "metadata": {"restriction_checked": True, "fallback_used": False, "request_count": calls,
                            "detours": groups, "via_waypoints": via, "traffic_aware": traffic_aware,
                            "departure_time_sent": response.get("departure_time_sent"),
                            "warnings": response.get("warnings", []), "elapsed_seconds": round(perf_counter() - started, 3),
                            "geometry_check_seconds": round(geometry_seconds, 3)}}
            if any((item["road"]["restricted_road_id"], item["direction"]) in applied for item in conflicts):
                return unresolved("DETOUR_STILL_RESTRICTED")
            # Reproject existing groups onto the latest route, then insert new
            # waypoints at the first conflict position, including between points
            # of an earlier detour. Preserve each stored relative order.
            def nearest_position(point):
                return min(range(len(access)), key=lambda i: (access[i]["longitude"] - point[0]) ** 2 + (access[i]["latitude"] - point[1]) ** 2)
            ordered = [(nearest_position(entry["point"]), order, entry) for order, entry in enumerate(via_order)]
            for order, conflict in enumerate(conflicts, start=len(via_order)):
                road, direction = conflict["road"], conflict["direction"]
                key = (road["restricted_road_id"], direction)
                if key in applied:
                    continue
                applied.add(key)
                group = {"road_id": key[0], "direction": direction,
                         "waypoints": road["forward_waypoints" if direction == "FORWARD" else "reverse_waypoints"]}
                groups.append(group)
                for offset, point in enumerate(group["waypoints"]):
                    ordered.append((conflict["position"], order + offset / 100, {"road_id": key[0], "direction": direction, "point": point}))
            via_order = [entry for _, _, entry in sorted(ordered, key=lambda item: (item[0], item[1]))]
        return unresolved("ATTEMPT_LIMIT")


def routing_http_error(exc: RestrictedRoutingError):
    return HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})
