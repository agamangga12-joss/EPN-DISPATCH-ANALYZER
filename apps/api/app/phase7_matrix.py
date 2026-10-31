from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Event
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .google_routes import GoogleRoutesClient, GoogleRoutesError, decrypt_api_key, get_google_routes_configuration
from .models import (
    MasterDepot,
    MasterSPBU,
    OptimizationJob,
    PredictionRun,
    PredictionTrip,
    RouteAPIRequestLog,
    RouteMatrixCache,
    RouteVersion,
    RouteVersionStop,
    RouteVersionTrip,
)
from .road_geometry import OSRMRoadGeometryClient, RoadGeometryError
from .restricted_roads import RestrictedRoadRouter, RestrictedRoutingError, GoogleRequestBudget, UNREACHABLE


def _utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _coordinates(entity: MasterDepot | MasterSPBU) -> tuple[float, float] | None:
    if entity.latitude is None or entity.longitude is None:
        return None
    latitude, longitude = float(entity.latitude), float(entity.longitude)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or (latitude == 0 and longitude == 0):
        return None
    return latitude, longitude


def _location_id(entity: MasterDepot | MasterSPBU) -> str:
    return entity.depot_id if isinstance(entity, MasterDepot) else entity.spbu_id


def _haversine_meters(first: tuple[float, float], second: tuple[float, float]) -> int:
    latitude_1, longitude_1 = map(math.radians, first)
    latitude_2, longitude_2 = map(math.radians, second)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1
    value = math.sin(delta_latitude / 2) ** 2 + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    return round(6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


class RouteMatrixService:
    """Materialize matrix data before solver callbacks and cache every pair."""

    def __init__(self, db: Session, *, job_id: str | None = None):
        self.db = db
        self.job_id = job_id
        configuration = get_google_routes_configuration(db)
        self.configuration = configuration
        self.client = None
        if configuration and configuration.encrypted_api_key:
            try:
                self.client = GoogleRoutesClient(decrypt_api_key(configuration.encrypted_api_key))
            except Exception:
                self.client = None
        self.road_geometry_client = OSRMRoadGeometryClient()
        self.google_geometry_blocked = False
        self._restricted_estimates: dict[tuple[str, str], dict] = {}
        self._route_history_by_sequence: dict[tuple[str, tuple[str, ...]], tuple[str, str]] | None = None
        self._prediction_history_by_sequence: dict[tuple[str, tuple[str, ...]], str] | None = None

    @staticmethod
    def _bucket(departure: datetime) -> datetime:
        value = _utc(departure)
        return value.replace(minute=(value.minute // 15) * 15, second=0, microsecond=0)

    def _key(self, origin: MasterDepot | MasterSPBU, destination: MasterDepot | MasterSPBU, departure: datetime, parameters: dict) -> str:
        payload = {
            "origin": _location_id(origin),
            "destination": _location_id(destination),
            "departure": self._bucket(departure).isoformat(),
            "vehicle_mode": parameters.get("route_vehicle_mode", "GENERAL_VEHICLE"),
            "traffic_aware": bool(parameters.get("traffic_aware", True)),
        }
        if parameters.get("restricted_roads", {}).get("roads"):
            payload.update({"restricted_roads": parameters["restricted_roads"]["checksum"],
                            "provider": "GOOGLE_RESTRICTED_WAYPOINTS",
                            "google_configuration_version": self.configuration.configuration_version if self.configuration else None,
                            "coordinates": [_coordinates(origin), _coordinates(destination)],
                            "restricted_routing_contract": 2})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _build_restricted(self, *, depot, loading_orders, spbus, departure, parameters, progress_callback=None):
        started = perf_counter()
        snapshot = parameters["restricted_roads"]
        router = RestrictedRoadRouter(self.db, client=self.client)
        entities = [depot, *[spbus[row["spbu_id"]] for row in loading_orders]]
        unique = {_location_id(entity): entity for entity in entities}
        pairs = [(a, b) for a in unique.values() for b in unique.values() if _location_id(a) != _location_id(b)]
        time_limit = int(parameters.get("restricted_matrix_time_limit_seconds", 900))
        worker_count = int(parameters.get("restricted_matrix_workers", 4))
        deadline = started + time_limit
        budget = GoogleRequestBudget(parameters.get("route_matrix_google_element_budget", 2500))
        cancel_event = Event()
        keys = [self._key(a, b, departure, parameters) for a, b in pairs]
        cache_rows, hits = {}, 0
        use_cache = bool(parameters.get("route_matrix_cache_enabled", True))
        if use_cache:
            for offset in range(0, len(keys), 500):
                for row in self.db.scalars(select(RouteMatrixCache).where(RouteMatrixCache.cache_key.in_(keys[offset:offset + 500]))):
                    cache_rows[row.cache_key] = row
        missing = []
        for (origin, destination), key in zip(pairs, keys):
            cached = cache_rows.get(key)
            if (cached and cached.expires_at and _utc(cached.expires_at) > datetime.now(timezone.utc)
                    and cached.provider in {"GOOGLE_RESTRICTED_WAYPOINTS", "GOOGLE_RESTRICTED_UNRESOLVED"}
                    and (cached.response_metadata or {}).get("restriction_checksum") == snapshot["checksum"]):
                self._restricted_estimates[_location_id(origin), _location_id(destination)] = self._cached_estimate(cached)
                hits += 1
            else:
                first, second = _coordinates(origin), _coordinates(destination)
                if first is None or second is None:
                    raise RestrictedRoutingError("RESTRICTED_ROUTING_COORDINATES_REQUIRED", "All depot/SPBU coordinates are required when restricted roads apply.")
                # Resolve ORM values on the coordinator thread. Workers receive
                # primitives only and never read/write the SQLAlchemy session.
                missing.append((origin, destination, key, [[first[1], first[0]], [second[1], second[0]]]))
        completed, active, geometry_seconds = hits, 0, 0.0
        last_progress = 0.0
        def progress(force=False):
            nonlocal last_progress
            if progress_callback and (force or perf_counter() - last_progress >= 5):
                last_progress = perf_counter()
                progress_callback({"total_unique_pairs": len(pairs), "completed_unique_pairs": completed,
                    "restricted_request_count": budget.used, "cache_hit_count": hits,
                    "active_pair_count": active, "workers": worker_count, "time_limit_seconds": time_limit,
                    "elapsed_seconds": round(perf_counter() - started, 2),
                    "geometry_check_seconds": round(geometry_seconds, 3)})
        progress(True)
        if len(missing) > budget.limit:
            raise RestrictedRoutingError("RESTRICTED_GOOGLE_REQUEST_BUDGET", f"At least {len(missing)} Google requests are needed for uncached pairs, but the budget is {budget.limit}. Increase the matrix request budget.")
        first_error = None
        remaining = iter(missing)
        def submit_next(pool, pending):
            nonlocal active
            item = next(remaining, None)
            if item is not None:
                future = pool.submit(router.route, item[3], snapshot["roads"], departure=departure,
                    traffic_aware=bool(parameters.get("traffic_aware", True)), request_budget=budget,
                    deadline=deadline, cancel_event=cancel_event)
                pending[future] = item
                active = len(pending)
        if missing:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="restricted-matrix") as pool:
                pending = {}
                for _ in range(worker_count):
                    submit_next(pool, pending)
                while pending:
                    if first_error is None and perf_counter() >= deadline:
                        first_error = RestrictedRoutingError("RESTRICTED_MATRIX_TIME_LIMIT", f"Restricted matrix reached its {time_limit}-second limit after {completed}/{len(pairs)} pairs. Increase Restricted Matrix Time Limit in the parameter profile.")
                        cancel_event.set()
                    done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    for future in done:
                        origin, destination, key, _ = pending.pop(future)
                        active = len(pending)
                        try:
                            estimate = future.result()
                            estimate["metadata"]["restriction_checksum"] = snapshot["checksum"]
                            geometry_seconds += float(estimate["metadata"].get("geometry_check_seconds") or 0)
                            self._restricted_estimates[_location_id(origin), _location_id(destination)] = estimate
                            if use_cache:
                                self._store_cache_estimate(cache_rows=cache_rows, key=key, origin=origin, destination=destination,
                                    departure=departure, parameters=parameters, estimate=estimate)
                            completed += 1
                            # Persist successful work even when a different pair
                            # failed; retries should reuse verified cached paths.
                            progress(True)
                        except Exception as exc:
                            if first_error is None:
                                first_error = exc
                                cancel_event.set()
                        if first_error is None and perf_counter() < deadline:
                            submit_next(pool, pending)
                    progress()
            if first_error is not None:
                raise first_error
            if completed != len(pairs):
                raise RestrictedRoutingError("RESTRICTED_MATRIX_TIME_LIMIT", f"Restricted matrix time limit reached after {completed}/{len(pairs)} pairs. Increase Restricted Matrix Time Limit in the parameter profile.")
        calls = budget.used
        size = len(entities)
        distances, times, geometry = [[0] * size for _ in entities], [[0] * size for _ in entities], {}
        for i, a in enumerate(entities):
            for j, b in enumerate(entities):
                if _location_id(a) == _location_id(b):
                    continue
                estimate = self._restricted_estimates[_location_id(a), _location_id(b)]
                distances[i][j], times[i][j] = estimate["distance_meters"], estimate["duration_seconds"]
                geometry[f"{i}:{j}"] = {"geometry": estimate["route_geometry"], "provider": estimate["provider"]}
        self.db.add(RouteAPIRequestLog(request_log_id=uuid.uuid4().hex, job_id=self.job_id,
            request_type="PHASE7_MATRIX_BUILD", provider="GOOGLE_RESTRICTED_WAYPOINTS", request_fingerprint=snapshot["checksum"],
            requested_pair_count=len(pairs), cache_hit_count=hits, duration_ms=round((perf_counter() - started) * 1000), success=True))
        return {"distance_matrix": distances, "time_matrix": times, "geometry": geometry,
                "metadata": {"location_count": size, "pair_count": size * (size - 1), "unique_pair_count": len(pairs),
                    "cache_hit_count": hits, "google_request_count": calls, "restricted_request_count": calls,
                    "fallback_pair_count": 0, "provider": "GOOGLE_RESTRICTED_WAYPOINTS",
                    "review_required_pair_count": sum(e["duration_seconds"] >= UNREACHABLE for e in self._restricted_estimates.values()),
                    "restriction_checksum": snapshot["checksum"], "restriction_count": len(snapshot["roads"]),
                    "traffic_aware": bool(parameters.get("traffic_aware", True)), "matrix_duration_ms": round((perf_counter() - started) * 1000),
                    "workers": worker_count, "time_limit_seconds": time_limit,
                    "geometry_check_seconds": round(geometry_seconds, 3)}}

    def _fallback(self, origin: MasterDepot | MasterSPBU, destination: MasterDepot | MasterSPBU) -> dict:
        first, second = _coordinates(origin), _coordinates(destination)
        if first and second:
            distance = round(_haversine_meters(first, second) * 1.25)
            duration = max(60, round(distance / (35_000 / 3600)))
            geometry = [
                {"latitude": first[0], "longitude": first[1]},
                {"latitude": second[0], "longitude": second[1]},
            ]
        else:
            spbu = destination if isinstance(destination, MasterSPBU) else origin if isinstance(origin, MasterSPBU) else None
            distance = round(float(spbu.master_distance_km or 0) * 1000) if spbu else 0
            duration = round(float(spbu.master_travel_time_min or 120) * 60) if spbu else 7200
            geometry = []
        return {
            "distance_meters": distance,
            "duration_seconds": duration,
            "route_geometry": geometry,
            "provider": "MASTER_HAVERSINE_FALLBACK",
            "metadata": {"fallback_used": True},
        }

    def _leg(self, origin: MasterDepot | MasterSPBU, destination: MasterDepot | MasterSPBU, departure: datetime, parameters: dict) -> tuple[dict, bool, bool]:
        if _location_id(origin) == _location_id(destination):
            return {"distance_meters": 0, "duration_seconds": 0, "route_geometry": [], "provider": "SAME_LOCATION", "metadata": {}}, True, False
        key = self._key(origin, destination, departure, parameters)
        now = datetime.now(timezone.utc)
        use_cache = bool(parameters.get("route_matrix_cache_enabled", True))
        cached = self.db.scalar(select(RouteMatrixCache).where(RouteMatrixCache.cache_key == key, RouteMatrixCache.expires_at > now)) if use_cache else None
        if cached:
            return {
                "distance_meters": cached.distance_meters,
                "duration_seconds": cached.duration_seconds,
                "route_geometry": cached.route_geometry or [],
                "route_polyline": cached.route_polyline,
                "provider": cached.provider,
                "metadata": cached.response_metadata or {},
            }, True, False
        estimate = None
        api_called = False
        origin_coordinates, destination_coordinates = _coordinates(origin), _coordinates(destination)
        truck_requested = parameters.get("route_vehicle_mode") == "TRUCK"
        if self.client and origin_coordinates and destination_coordinates and not truck_requested:
            api_called = True
            try:
                response = self.client.compute_route_matrix(
                    origin=origin_coordinates,
                    destination=destination_coordinates,
                    departure_datetime=departure if parameters.get("traffic_aware", True) else None,
                )
                duration = str(response.get("duration") or "0s")
                estimate = {
                    "distance_meters": int(response.get("distanceMeters") or 0),
                    "duration_seconds": round(float(duration[:-1])) if duration.endswith("s") else 0,
                    "route_geometry": [],
                    "provider": "GOOGLE_ROUTES_MATRIX",
                    "metadata": {"fallback_used": False, "condition": response.get("condition")},
                }
            except GoogleRoutesError as exc:
                estimate = self._fallback(origin, destination)
                estimate["metadata"]["google_error_code"] = exc.code
        if estimate is None:
            estimate = self._fallback(origin, destination)
            if truck_requested:
                estimate["provider"] = "TRUCK_MODE_UNAVAILABLE_MASTER_HAVERSINE_FALLBACK"
                estimate["metadata"]["truck_routing_supported"] = False
        if use_cache:
            row = self.db.scalar(select(RouteMatrixCache).where(RouteMatrixCache.cache_key == key))
            if not row:
                row = RouteMatrixCache(route_matrix_cache_id=uuid.uuid4().hex, cache_key=key)
                self.db.add(row)
            row.origin_location_id = _location_id(origin)
            row.destination_location_id = _location_id(destination)
            row.departure_time_bucket = self._bucket(departure)
            row.route_vehicle_mode = parameters.get("route_vehicle_mode", "GENERAL_VEHICLE")
            row.traffic_aware = bool(parameters.get("traffic_aware", True))
            row.distance_meters = int(estimate["distance_meters"])
            row.duration_seconds = int(estimate["duration_seconds"])
            row.route_geometry = estimate.get("route_geometry") or []
            row.provider = estimate["provider"]
            row.response_metadata = estimate.get("metadata") or {}
            row.calculated_at = now
            row.expires_at = now + timedelta(minutes=int(parameters.get("route_matrix_cache_ttl_minutes", 60)))
        return estimate, False, api_called

    @staticmethod
    def _cached_estimate(row: RouteMatrixCache) -> dict:
        return {
            "distance_meters": row.distance_meters,
            "duration_seconds": row.duration_seconds,
            "route_geometry": row.route_geometry or [],
            "route_polyline": row.route_polyline,
            "provider": row.provider,
            "metadata": row.response_metadata or {},
        }

    def _store_cache_estimate(
        self,
        *,
        cache_rows: dict[str, RouteMatrixCache],
        key: str,
        origin: MasterDepot | MasterSPBU,
        destination: MasterDepot | MasterSPBU,
        departure: datetime,
        parameters: dict,
        estimate: dict,
    ) -> None:
        row = cache_rows.get(key)
        if row is None:
            row = RouteMatrixCache(route_matrix_cache_id=uuid.uuid4().hex, cache_key=key)
            cache_rows[key] = row
            self.db.add(row)
        now = datetime.now(timezone.utc)
        row.origin_location_id = _location_id(origin)
        row.destination_location_id = _location_id(destination)
        row.departure_time_bucket = self._bucket(departure)
        row.route_vehicle_mode = parameters.get("route_vehicle_mode", "GENERAL_VEHICLE")
        row.traffic_aware = bool(parameters.get("traffic_aware", True))
        row.distance_meters = int(estimate["distance_meters"])
        row.duration_seconds = int(estimate["duration_seconds"])
        row.route_geometry = estimate.get("route_geometry") or []
        row.provider = str(estimate["provider"])
        row.response_metadata = estimate.get("metadata") or {}
        row.calculated_at = now
        row.expires_at = now + timedelta(minutes=int(parameters.get("route_matrix_cache_ttl_minutes", 60)))

    def build(
        self,
        *,
        depot: MasterDepot,
        loading_orders: list[dict],
        spbus: dict[str, MasterSPBU],
        departure: datetime,
        parameters: dict,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        started = perf_counter()
        if parameters.get("restricted_roads", {}).get("roads"):
            return self._build_restricted(depot=depot, loading_orders=loading_orders, spbus=spbus,
                departure=departure, parameters=parameters, progress_callback=progress_callback)
        # The solver retains one node per LO, but road estimates are materialized
        # once per unique physical location and expanded back to LO-node indexes.
        # This prevents duplicate LOs for one SPBU from multiplying SQL and HTTP
        # work, and lets Google compute up to 625 elements in one request.
        entities: list[MasterDepot | MasterSPBU] = [depot]
        for row in loading_orders:
            entities.append(spbus[row["spbu_id"]])
        size = len(entities)
        unique_entities: list[MasterDepot | MasterSPBU] = []
        unique_index_by_location: dict[str, int] = {}
        entity_to_unique: list[int] = []
        for entity in entities:
            location_id = _location_id(entity)
            if location_id not in unique_index_by_location:
                unique_index_by_location[location_id] = len(unique_entities)
                unique_entities.append(entity)
            entity_to_unique.append(unique_index_by_location[location_id])

        unique_pair_count = max(0, len(unique_entities) * (len(unique_entities) - 1))
        pair_keys = {
            (origin_index, destination_index): self._key(origin, destination, departure, parameters)
            for origin_index, origin in enumerate(unique_entities)
            for destination_index, destination in enumerate(unique_entities)
            if origin_index != destination_index
        }
        use_cache = bool(parameters.get("route_matrix_cache_enabled", True))
        cache_rows: dict[str, RouteMatrixCache] = {}
        if use_cache and pair_keys:
            keys = list(pair_keys.values())
            # Keep each IN predicate portable to SQLite tests and bounded for
            # PostgreSQL query planning on large depot days.
            for offset in range(0, len(keys), 500):
                rows = self.db.scalars(
                    select(RouteMatrixCache).where(RouteMatrixCache.cache_key.in_(keys[offset : offset + 500]))
                ).all()
                cache_rows.update({row.cache_key: row for row in rows})

        now = datetime.now(timezone.utc)
        estimates: dict[tuple[int, int], dict] = {}
        cache_hits = 0
        for pair, key in pair_keys.items():
            cached = cache_rows.get(key)
            if cached and cached.expires_at and _utc(cached.expires_at) > now:
                estimates[pair] = self._cached_estimate(cached)
                cache_hits += 1

        missing = set(pair_keys) - set(estimates)
        google_batch_requests = 0
        google_elements = 0
        fallback_pairs = 0
        google_error_codes: set[str] = set()
        matrix_time_limit = int(parameters.get("route_matrix_time_limit_seconds", 90))
        google_element_budget = int(parameters.get("route_matrix_google_element_budget", 2500))

        def record(pair: tuple[int, int], estimate: dict) -> None:
            nonlocal fallback_pairs
            estimates[pair] = estimate
            missing.discard(pair)
            if estimate.get("provider") != "GOOGLE_ROUTES_MATRIX":
                fallback_pairs += 1
            if use_cache:
                self._store_cache_estimate(
                    cache_rows=cache_rows,
                    key=pair_keys[pair],
                    origin=unique_entities[pair[0]],
                    destination=unique_entities[pair[1]],
                    departure=departure,
                    parameters=parameters,
                    estimate=estimate,
                )

        truck_requested = parameters.get("route_vehicle_mode") == "TRUCK"
        google_indexes = [index for index, entity in enumerate(unique_entities) if _coordinates(entity)]
        google_index_set = set(google_indexes)
        for pair in list(missing):
            if self.client and not truck_requested and pair[0] in google_index_set and pair[1] in google_index_set:
                continue
            estimate = self._fallback(unique_entities[pair[0]], unique_entities[pair[1]])
            if truck_requested:
                estimate["provider"] = "TRUCK_MODE_UNAVAILABLE_MASTER_HAVERSINE_FALLBACK"
                estimate["metadata"]["truck_routing_supported"] = False
            record(pair, estimate)

        if progress_callback:
            progress_callback(
                {
                    "stage": "BUILDING_MATRIX",
                    "completed_unique_pairs": unique_pair_count - len(missing),
                    "total_unique_pairs": unique_pair_count,
                    "cache_hit_count": cache_hits,
                    "google_batch_request_count": google_batch_requests,
                    "google_element_count": google_elements,
                }
            )

        # 25 × 25 is the documented 625-element non-transit request limit.
        blocks = [google_indexes[index : index + 25] for index in range(0, len(google_indexes), 25)]
        stop_google = False
        for origin_block in blocks:
            if stop_google:
                break
            for destination_block in blocks:
                candidates = {
                    (origin_index, destination_index)
                    for origin_index in origin_block
                    for destination_index in destination_block
                    if (origin_index, destination_index) in missing
                }
                if not candidates:
                    continue
                if perf_counter() - started >= matrix_time_limit or google_elements >= google_element_budget:
                    stop_google = True
                    break

                remaining_budget = google_element_budget - google_elements
                request_origins = list(origin_block[: min(len(origin_block), remaining_budget)])
                if not request_origins:
                    stop_google = True
                    break
                destination_limit = min(len(destination_block), remaining_budget // len(request_origins))
                if destination_limit <= 0:
                    stop_google = True
                    break
                request_destinations = list(destination_block[:destination_limit])
                requested_pairs = {
                    (origin_index, destination_index)
                    for origin_index in request_origins
                    for destination_index in request_destinations
                    if (origin_index, destination_index) in missing
                }
                if not requested_pairs:
                    continue
                google_elements += len(request_origins) * len(request_destinations)
                google_batch_requests += 1
                try:
                    response_rows = self.client.compute_route_matrix_batch(
                        origins=[_coordinates(unique_entities[index]) for index in request_origins],
                        destinations=[_coordinates(unique_entities[index]) for index in request_destinations],
                        departure_datetime=departure if parameters.get("traffic_aware", True) else None,
                    )
                    response_by_pair = {
                        (request_origins[int(row.get("originIndex") or 0)], request_destinations[int(row.get("destinationIndex") or 0)]): row
                        for row in response_rows
                        if int(row.get("originIndex") or 0) < len(request_origins)
                        and int(row.get("destinationIndex") or 0) < len(request_destinations)
                    }
                    for pair in requested_pairs:
                        row = response_by_pair.get(pair) or {}
                        status = row.get("status") or {}
                        status_code = int(status.get("code") or 0) if isinstance(status, dict) else 0
                        if row.get("condition") in {None, "ROUTE_EXISTS"} and status_code == 0 and row.get("distanceMeters") is not None:
                            record(
                                pair,
                                {
                                    "distance_meters": int(row.get("distanceMeters") or 0),
                                    "duration_seconds": int(round(float(str(row.get("duration") or "0s")[:-1]))) if str(row.get("duration") or "0s").endswith("s") else 0,
                                    "route_geometry": [],
                                    "provider": "GOOGLE_ROUTES_MATRIX",
                                    "metadata": {"fallback_used": False, "condition": row.get("condition")},
                                },
                            )
                        else:
                            estimate = self._fallback(unique_entities[pair[0]], unique_entities[pair[1]])
                            estimate["metadata"]["google_error_code"] = "GOOGLE_ROUTE_NOT_FOUND"
                            record(pair, estimate)
                except GoogleRoutesError as exc:
                    google_error_codes.add(exc.code)
                    for pair in requested_pairs:
                        estimate = self._fallback(unique_entities[pair[0]], unique_entities[pair[1]])
                        estimate["metadata"]["google_error_code"] = exc.code
                        record(pair, estimate)

                if progress_callback:
                    progress_callback(
                        {
                            "stage": "BUILDING_MATRIX",
                            "completed_unique_pairs": unique_pair_count - len(missing),
                            "total_unique_pairs": unique_pair_count,
                            "cache_hit_count": cache_hits,
                            "google_batch_request_count": google_batch_requests,
                            "google_element_count": google_elements,
                        }
                    )

        fallback_reason = "GOOGLE_MATRIX_TIME_BUDGET" if perf_counter() - started >= matrix_time_limit else "GOOGLE_MATRIX_ELEMENT_BUDGET"
        for pair in list(missing):
            estimate = self._fallback(unique_entities[pair[0]], unique_entities[pair[1]])
            estimate["metadata"]["google_error_code"] = fallback_reason
            record(pair, estimate)

        distance_matrix = [[0] * size for _ in range(size)]
        time_matrix = [[0] * size for _ in range(size)]
        geometry: dict[str, dict] = {}
        for origin_index, origin in enumerate(entities):
            for destination_index, destination in enumerate(entities):
                unique_origin = entity_to_unique[origin_index]
                unique_destination = entity_to_unique[destination_index]
                if unique_origin == unique_destination:
                    continue
                estimate = estimates[unique_origin, unique_destination]
                distance_matrix[origin_index][destination_index] = int(estimate["distance_meters"])
                time_matrix[origin_index][destination_index] = int(estimate["duration_seconds"])
                geometry[f"{origin_index}:{destination_index}"] = {
                    "geometry": estimate.get("route_geometry") or [],
                    "provider": estimate.get("provider"),
                }
        fingerprint = hashlib.sha256(
            json.dumps([_location_id(entity) for entity in entities], sort_keys=True).encode()
        ).hexdigest()
        self.db.add(
            RouteAPIRequestLog(
                request_log_id=uuid.uuid4().hex,
                job_id=self.job_id,
                request_type="PHASE7_MATRIX_BUILD",
                provider="GOOGLE_ROUTES_WITH_FALLBACK",
                request_fingerprint=fingerprint,
                requested_pair_count=max(0, size * (size - 1)),
                cache_hit_count=cache_hits,
                duration_ms=round((perf_counter() - started) * 1000),
                success=True,
                error_message=None,
            )
        )
        return {
            "distance_matrix": distance_matrix,
            "time_matrix": time_matrix,
            "geometry": geometry,
            "metadata": {
                "location_count": size,
                "pair_count": max(0, size * (size - 1)),
                "unique_location_count": len(unique_entities),
                "unique_pair_count": unique_pair_count,
                "cache_hit_count": cache_hits,
                "google_request_count": google_batch_requests,
                "google_batch_request_count": google_batch_requests,
                "google_element_count": google_elements,
                "fallback_pair_count": fallback_pairs,
                "google_error_codes": sorted(google_error_codes),
                "matrix_duration_ms": round((perf_counter() - started) * 1000),
                "google_routes_is_optimizer": False,
                "route_vehicle_mode": parameters.get("route_vehicle_mode", "GENERAL_VEHICLE"),
            },
        }

    def _map_geometry_key(self, depot: MasterDepot, ordered_spbus: list[MasterSPBU]) -> str:
        entities: list[MasterDepot | MasterSPBU] = [depot, *ordered_spbus, depot]
        payload = {
            "kind": "PHASE7_MAP_ROAD_GEOMETRY_V1",
            "locations": [_location_id(entity) for entity in entities],
            "coordinates": [_coordinates(entity) for entity in entities],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _load_historical_geometry_indexes(self, depot_id: str) -> None:
        if self._route_history_by_sequence is not None and self._prediction_history_by_sequence is not None:
            return

        road_sources = (
            "GOOGLE_ROUTES_GEOJSON",
            "HISTORICAL_GOOGLE_ROUTES_GEOJSON",
            "OSRM_ROAD_GEOMETRY",
        )
        route_rows = self.db.execute(
            select(
                RouteVersionTrip.route_version_trip_id,
                RouteVersionTrip.route_geometry_source,
            )
            .join(RouteVersion, RouteVersion.route_version_id == RouteVersionTrip.route_version_id)
            .join(OptimizationJob, OptimizationJob.job_id == RouteVersion.job_id)
            .where(
                OptimizationJob.depot_id == depot_id,
                RouteVersionTrip.route_geometry_source.in_(road_sources),
            )
            .order_by(RouteVersionTrip.gate_out.desc())
        ).all()
        route_ids = [row[0] for row in route_rows]
        stops_by_trip: dict[str, list[str]] = defaultdict(list)
        for offset in range(0, len(route_ids), 500):
            for trip_id, spbu_id in self.db.execute(
                select(RouteVersionStop.route_version_trip_id, RouteVersionStop.spbu_id)
                .where(RouteVersionStop.route_version_trip_id.in_(route_ids[offset : offset + 500]))
                .order_by(RouteVersionStop.route_version_trip_id, RouteVersionStop.sequence_number)
            ).all():
                if spbu_id:
                    stops_by_trip[trip_id].append(spbu_id)
        route_index: dict[tuple[str, tuple[str, ...]], tuple[str, str]] = {}
        for trip_id, source in route_rows:
            sequence = tuple(stops_by_trip.get(trip_id) or [])
            if sequence:
                route_index.setdefault((depot_id, sequence), (trip_id, source))

        prediction_index: dict[tuple[str, tuple[str, ...]], str] = {}
        prediction_rows = self.db.execute(
            select(PredictionTrip.id, PredictionTrip.estimated_visit_sequence)
            .join(PredictionRun, PredictionRun.id == PredictionTrip.prediction_run_id)
            .where(
                PredictionRun.depot_id == depot_id,
                PredictionTrip.route_geometry_source == "GOOGLE_ROUTES_GEOJSON",
            )
            .order_by(PredictionTrip.created_at.desc())
        ).all()
        for trip_id, sequence in prediction_rows:
            normalized = tuple(str(value) for value in (sequence or []) if value)
            if normalized:
                prediction_index.setdefault((depot_id, normalized), trip_id)

        self._route_history_by_sequence = route_index
        self._prediction_history_by_sequence = prediction_index

    def _historical_road_geometry(self, depot: MasterDepot, ordered_spbus: list[MasterSPBU]) -> dict | None:
        self._load_historical_geometry_indexes(depot.depot_id)
        spbu_ids = tuple(spbu.spbu_id for spbu in ordered_spbus)
        route_match = (self._route_history_by_sequence or {}).get((depot.depot_id, spbu_ids))
        if route_match:
            trip_id, source = route_match
            geometry = self.db.scalar(
                select(RouteVersionTrip.route_geometry).where(RouteVersionTrip.route_version_trip_id == trip_id)
            ) or []
            if len(geometry) >= 2:
                return {
                    "route_geometry": geometry,
                    "route_geometry_source": f"HISTORICAL_{source}" if not source.startswith("HISTORICAL_") else source,
                    "history_source": "ROUTE_VERSION",
                }

        spbu_codes = tuple(spbu.spbu_code for spbu in ordered_spbus)
        prediction_match = (self._prediction_history_by_sequence or {}).get((depot.depot_id, spbu_codes))
        if prediction_match:
            geometry = self.db.scalar(
                select(PredictionTrip.route_geometry).where(PredictionTrip.id == prediction_match)
            ) or []
            if len(geometry) >= 2:
                return {
                    "route_geometry": geometry,
                    "route_geometry_source": "HISTORICAL_GOOGLE_ROUTES_GEOJSON",
                    "history_source": "PHASE6_PREDICTION_TRIP",
                }
        return None

    def _store_map_geometry_cache(
        self,
        *,
        key: str,
        depot: MasterDepot,
        ordered_spbus: list[MasterSPBU],
        departure: datetime,
        result: dict,
    ) -> None:
        row = self.db.scalar(select(RouteMatrixCache).where(RouteMatrixCache.cache_key == key))
        if row is None:
            row = RouteMatrixCache(route_matrix_cache_id=uuid.uuid4().hex, cache_key=key)
            self.db.add(row)
        settings = get_settings()
        now = datetime.now(timezone.utc)
        row.origin_location_id = depot.depot_id
        row.destination_location_id = depot.depot_id
        row.departure_time_bucket = self._bucket(departure)
        row.route_vehicle_mode = "GEOMETRY_ONLY"
        row.traffic_aware = False
        row.distance_meters = int(result.get("distance_meters") or 0)
        row.duration_seconds = int(result.get("duration_seconds") or 0)
        row.route_geometry = result.get("route_geometry") or []
        row.provider = str(result["route_geometry_source"])
        row.response_metadata = {
            "geometry_only": True,
            "stop_ids": [spbu.spbu_id for spbu in ordered_spbus],
            "stop_codes": [spbu.spbu_code for spbu in ordered_spbus],
            "history_source": result.get("history_source"),
        }
        row.calculated_at = now
        row.expires_at = now + timedelta(minutes=max(60, int(settings.road_geometry_cache_ttl_minutes)))

    def build_map_road_geometry(
        self,
        *,
        depot: MasterDepot,
        ordered_spbus: list[MasterSPBU],
        departure: datetime,
    ) -> dict:
        """Return road-following visualization geometry without changing solver facts."""
        started = perf_counter()
        entities: list[MasterDepot | MasterSPBU] = [depot, *ordered_spbus, depot]
        coordinates = [_coordinates(entity) for entity in entities]
        if len(entities) < 3 or not all(coordinates):
            return {
                "route_geometry": [],
                "route_geometry_source": "MASTER_COORDINATE_FALLBACK",
                "road_geometry": False,
                "cache_hit": False,
                "external_request_count": 0,
                "error_codes": ["ROAD_GEOMETRY_COORDINATES_REQUIRED"],
                "duration_ms": round((perf_counter() - started) * 1000),
            }

        key = self._map_geometry_key(depot, ordered_spbus)
        now = datetime.now(timezone.utc)
        cached = self.db.scalar(
            select(RouteMatrixCache).where(RouteMatrixCache.cache_key == key, RouteMatrixCache.expires_at > now)
        )
        if cached and len(cached.route_geometry or []) >= 2:
            return {
                "route_geometry": cached.route_geometry,
                "route_geometry_source": cached.provider,
                "road_geometry": True,
                "cache_hit": True,
                "external_request_count": 0,
                "error_codes": [],
                "duration_ms": round((perf_counter() - started) * 1000),
            }

        historical = self._historical_road_geometry(depot, ordered_spbus)
        if historical:
            result = {
                **historical,
                "distance_meters": 0,
                "duration_seconds": 0,
                "road_geometry": True,
                "cache_hit": True,
                "external_request_count": 0,
                "error_codes": [],
                "duration_ms": round((perf_counter() - started) * 1000),
            }
            self._store_map_geometry_cache(
                key=key,
                depot=depot,
                ordered_spbus=ordered_spbus,
                departure=departure,
                result=result,
            )
            return result

        errors: list[str] = []
        external_requests = 0
        if self.client and not self.google_geometry_blocked:
            try:
                external_requests += 1
                google = self.client.compute_route(
                    origin=coordinates[0],
                    destination=coordinates[-1],
                    intermediates=coordinates[1:-1],
                    departure_datetime=departure,
                    routing_mode="DRIVE",
                    routing_preference="TRAFFIC_AWARE",
                )
                result = {
                    **google,
                    "road_geometry": True,
                    "cache_hit": False,
                    "external_request_count": external_requests,
                    "error_codes": errors,
                    "duration_ms": round((perf_counter() - started) * 1000),
                }
                self._store_map_geometry_cache(key=key, depot=depot, ordered_spbus=ordered_spbus, departure=departure, result=result)
                return result
            except GoogleRoutesError as exc:
                errors.append(exc.code)
                if exc.code in {"GOOGLE_RATE_LIMIT", "GOOGLE_API_KEY_INVALID", "GOOGLE_ROUTES_NOT_ENABLED"}:
                    self.google_geometry_blocked = True

        try:
            external_requests += 1
            fallback = self.road_geometry_client.compute_route(coordinates)
            result = {
                **fallback,
                "road_geometry": True,
                "cache_hit": False,
                "external_request_count": external_requests,
                "error_codes": errors,
                "duration_ms": round((perf_counter() - started) * 1000),
            }
            self._store_map_geometry_cache(key=key, depot=depot, ordered_spbus=ordered_spbus, departure=departure, result=result)
            return result
        except RoadGeometryError as exc:
            errors.append(exc.code)
            return {
                "route_geometry": [],
                "route_geometry_source": "MASTER_COORDINATE_FALLBACK",
                "road_geometry": False,
                "cache_hit": False,
                "external_request_count": external_requests,
                "error_codes": errors,
                "duration_ms": round((perf_counter() - started) * 1000),
            }

    def build_route_geometry(
        self,
        *,
        depot: MasterDepot,
        ordered_spbus: list[MasterSPBU],
        departure: datetime,
        parameters: dict,
    ) -> dict:
        """Fetch geometry only for final solver-selected legs, never callbacks."""
        if parameters.get("restricted_roads", {}).get("roads"):
            entities = [depot, *ordered_spbus, depot]
            points = []
            evidence = []
            for origin, destination in zip(entities, entities[1:]):
                if _location_id(origin) == _location_id(destination):
                    continue
                estimate = self._restricted_estimates.get((_location_id(origin), _location_id(destination)))
                if not estimate or estimate["duration_seconds"] >= UNREACHABLE or not estimate["route_geometry"]:
                    raise RestrictedRoutingError("RESTRICTED_SELECTED_LEG_INVALID", "Selected trip has no verified restricted-road matrix geometry.")
                evidence.append({"origin": _location_id(origin), "destination": _location_id(destination), "metadata": estimate.get("metadata", {})})
                leg = estimate["route_geometry"]
                points.extend(leg[1:] if points and points[-1] == leg[0] else leg)
            return {"route_geometry": points, "route_geometry_source": "GOOGLE_RESTRICTED_WAYPOINTS",
                    "google_request_count": 0, "cache_hit_count": 0,
                    "restriction_checksum": parameters["restricted_roads"]["checksum"], "restricted_legs": evidence}
        started = perf_counter()
        google_request_budget = max(0, int(parameters.get("route_geometry_google_request_budget", 500)))
        geometry_time_limit = max(0, int(parameters.get("route_geometry_time_limit_seconds", 120)))
        entities: list[MasterDepot | MasterSPBU] = [depot, *ordered_spbus, depot]
        points: list[dict] = []
        sources: list[str] = []
        api_calls = 0
        cache_hits = 0
        cursor = _utc(departure)
        all_coordinates = [_coordinates(entity) for entity in entities]
        truck_requested = parameters.get("route_vehicle_mode") == "TRUCK"
        if (
            self.client
            and not truck_requested
            and google_request_budget > 0
            and geometry_time_limit > 0
            and len(entities) >= 2
            and all(coordinates is not None for coordinates in all_coordinates)
        ):
            try:
                api_calls = 1
                response = self.client.compute_route(
                    origin=all_coordinates[0],
                    destination=all_coordinates[-1],
                    intermediates=all_coordinates[1:-1],
                    departure_datetime=cursor if parameters.get("traffic_aware", True) else None,
                    routing_mode="DRIVE",
                    routing_preference="TRAFFIC_AWARE" if parameters.get("traffic_aware", True) else "TRAFFIC_UNAWARE",
                )
                road_geometry = response.get("route_geometry") or []
                if len(road_geometry) >= 2:
                    return {
                        "route_geometry": road_geometry,
                        "route_geometry_source": "GOOGLE_ROUTES_GEOJSON",
                        "leg_sources": ["GOOGLE_ROUTES_GEOJSON"] * (len(entities) - 1),
                        "google_request_count": api_calls,
                        "cache_hit_count": 0,
                        "geometry_duration_ms": round((perf_counter() - started) * 1000),
                        "google_request_budget": google_request_budget,
                        "geometry_strategy": "SINGLE_ROUTE_WITH_INTERMEDIATES",
                    }
            except GoogleRoutesError:
                # Continue through per-leg cache/API/fallback materialization so
                # one provider failure never removes the route from the map.
                pass
        for origin, destination in zip(entities, entities[1:]):
            leg_departure = cursor
            key = self._key(origin, destination, leg_departure, parameters)
            cached = self.db.scalar(
                select(RouteMatrixCache).where(
                    RouteMatrixCache.cache_key == key,
                    RouteMatrixCache.expires_at > datetime.now(timezone.utc),
                )
            ) if parameters.get("route_matrix_cache_enabled", True) else None
            estimate = None
            if cached and cached.provider == "GOOGLE_ROUTES_GEOJSON" and len(cached.route_geometry or []) >= 2:
                estimate = {
                    "distance_meters": cached.distance_meters,
                    "duration_seconds": cached.duration_seconds,
                    "route_geometry": cached.route_geometry,
                    "provider": cached.provider,
                    "metadata": cached.response_metadata or {},
                }
                cache_hits += 1
            origin_coordinates, destination_coordinates = _coordinates(origin), _coordinates(destination)
            google_budget_available = api_calls < google_request_budget and perf_counter() - started < geometry_time_limit
            if estimate is None and self.client and origin_coordinates and destination_coordinates and not truck_requested and google_budget_available:
                try:
                    api_calls += 1
                    response = self.client.compute_route(
                        origin=origin_coordinates,
                        destination=destination_coordinates,
                        departure_datetime=leg_departure if parameters.get("traffic_aware", True) else None,
                        routing_mode="DRIVE",
                        routing_preference="TRAFFIC_AWARE" if parameters.get("traffic_aware", True) else "TRAFFIC_UNAWARE",
                    )
                    estimate = {
                        "distance_meters": response["distance_meters"],
                        "duration_seconds": response["duration_seconds"],
                        "route_geometry": response["route_geometry"],
                        "provider": response["route_geometry_source"],
                        "metadata": {"fallback_used": False},
                    }
                except GoogleRoutesError:
                    estimate = None
            if estimate is None:
                estimate = self._fallback(origin, destination)
                if truck_requested:
                    estimate["provider"] = "TRUCK_MODE_UNAVAILABLE_MASTER_HAVERSINE_FALLBACK"
                    estimate["metadata"]["truck_routing_supported"] = False
            geometry = estimate.get("route_geometry") or []
            if points and geometry and points[-1] == geometry[0]:
                geometry = geometry[1:]
            points.extend(geometry)
            sources.append(str(estimate["provider"]))
            cursor += timedelta(seconds=int(estimate["duration_seconds"]))
            if parameters.get("route_matrix_cache_enabled", True):
                row = cached or self.db.scalar(select(RouteMatrixCache).where(RouteMatrixCache.cache_key == key))
                if not row:
                    row = RouteMatrixCache(route_matrix_cache_id=uuid.uuid4().hex, cache_key=key)
                    self.db.add(row)
                row.origin_location_id = _location_id(origin)
                row.destination_location_id = _location_id(destination)
                row.departure_time_bucket = self._bucket(leg_departure)
                row.route_vehicle_mode = parameters.get("route_vehicle_mode", "GENERAL_VEHICLE")
                row.traffic_aware = bool(parameters.get("traffic_aware", True))
                row.distance_meters = int(estimate["distance_meters"])
                row.duration_seconds = int(estimate["duration_seconds"])
                row.route_geometry = estimate.get("route_geometry") or []
                row.provider = str(estimate["provider"])
                row.response_metadata = estimate.get("metadata") or {}
                row.calculated_at = datetime.now(timezone.utc)
                row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=int(parameters.get("route_matrix_cache_ttl_minutes", 60)))
        return {
            "route_geometry": points,
            "route_geometry_source": "GOOGLE_ROUTES_GEOJSON" if sources and all(source == "GOOGLE_ROUTES_GEOJSON" for source in sources) else "MIXED_OR_MASTER_FALLBACK",
            "leg_sources": sources,
            "google_request_count": api_calls,
            "cache_hit_count": cache_hits,
            "geometry_duration_ms": round((perf_counter() - started) * 1000),
            "google_request_budget": google_request_budget,
            "geometry_strategy": "PER_LEG_WITH_FALLBACK",
        }
