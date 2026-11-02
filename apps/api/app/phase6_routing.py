from __future__ import annotations

import hashlib
import json
import math
import statistics
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .google_routes import (
    GoogleRoutesClient,
    GoogleRoutesError,
    decrypt_api_key,
)
from .models import (
    GoogleRoutesConfiguration,
    MLSPBUClusterAssignment,
    MasterDepot,
    MasterMT,
    MasterSPBU,
    RouteEstimationCache,
)


CONFIDENCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _aware_utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _haversine_meters(first: tuple[float, float], second: tuple[float, float]) -> int:
    latitude_1, longitude_1 = map(math.radians, first)
    latitude_2, longitude_2 = map(math.radians, second)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1
    value = math.sin(delta_latitude / 2) ** 2 + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    return round(6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


class Phase6RouteEstimationService:
    """Estimate one predicted trip at a time; never solve a fleet-wide VRP.

    Stops are sequenced from nearest to farthest relative to the depot.
    No Google Route Optimization / GMPRO endpoint is present in this service.
    """

    def __init__(
        self,
        db: Session,
        *,
        configuration: GoogleRoutesConfiguration,
        model_id: str,
        metrics: dict[str, int] | None = None,
        google_client: GoogleRoutesClient | None = None,
    ):
        self.db = db
        self.configuration = configuration
        self.model_id = model_id
        self.metrics = metrics if metrics is not None else {}
        for key in (
            "google_routes_request_count",
            "google_routes_cache_hit_count",
            "google_routes_cache_miss_count",
            "google_routes_failed_request_count",
        ):
            self.metrics.setdefault(key, 0)
        # SessionLocal disables autoflush. Track cache rows added by this
        # prediction transaction so repeated legs reuse them before final flush.
        self._pending_cache: dict[str, RouteEstimationCache] = {}
        self.geometry_error_codes: set[str] = set()
        self.client = google_client
        if self.client is None and configuration.encrypted_api_key:
            try:
                self.client = GoogleRoutesClient(decrypt_api_key(configuration.encrypted_api_key))
            except Exception:
                self.metrics["google_routes_failed_request_count"] += 1

    @staticmethod
    def _coordinates(entity: MasterDepot | MasterSPBU) -> tuple[float, float] | None:
        if entity.latitude is None or entity.longitude is None:
            return None
        return float(entity.latitude), float(entity.longitude)

    def _departure_bucket(self, departure: datetime) -> datetime:
        value = _aware_utc(departure)
        bucket = max(1, int(self.configuration.departure_time_bucket_minutes))
        minute = (value.minute // bucket) * bucket
        return value.replace(minute=minute, second=0, microsecond=0)

    def _cache_key(
        self,
        *,
        origin_id: str,
        destination_id: str,
        departure: datetime,
        profile_hash: str,
        routing_mode: str,
        routing_preference: str,
    ) -> str:
        payload = {
            "origin": origin_id,
            "destination": destination_id,
            "departure_bucket": self._departure_bucket(departure).isoformat(),
            "vehicle_profile_hash": profile_hash,
            "routing_mode": routing_mode,
            "routing_preference": routing_preference,
            "configuration_version": self.configuration.configuration_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _cached_leg(self, cache_key: str, *, require_road_geometry: bool = False) -> dict | None:
        now = datetime.now(timezone.utc)
        row = self._pending_cache.get(cache_key)
        if not row:
            row = self.db.scalar(
                select(RouteEstimationCache).where(
                    RouteEstimationCache.cache_key == cache_key,
                    RouteEstimationCache.expires_at > now,
                )
            )
        if not row:
            self.metrics["google_routes_cache_miss_count"] += 1
            return None
        metadata = row.response_metadata or {}
        geometry = metadata.get("route_geometry") or []
        geometry_source = metadata.get("route_geometry_source")
        if require_road_geometry and self.client and (
            geometry_source != "GOOGLE_ROUTES_GEOJSON" or len(geometry) < 2
        ):
            self.metrics["google_routes_cache_miss_count"] += 1
            return None
        if not geometry:
            geometry = [
                {"latitude": row.origin_latitude, "longitude": row.origin_longitude},
                {"latitude": row.destination_latitude, "longitude": row.destination_longitude},
            ]
            geometry_source = "MASTER_COORDINATE_FALLBACK"
        self.metrics["google_routes_cache_hit_count"] += 1
        return {
            "distance_meters": row.distance_meters,
            "duration_seconds": row.duration_seconds,
            "static_duration_seconds": row.static_duration_seconds,
            "source": "ROUTE_CACHE",
            "underlying_source": row.provider_source,
            "route_geometry": geometry,
            "route_geometry_source": geometry_source,
            "road_geometry_attempted": bool(metadata.get("road_geometry_attempted", False)),
            "routing_confidence": metadata.get("routing_confidence", "HIGH"),
            "fallback_used": bool(metadata.get("fallback_used", False)),
            "warning_codes": metadata.get("warning_codes", []),
        }

    def _store_cache(
        self,
        *,
        cache_key: str,
        origin_id: str,
        destination_id: str,
        origin: tuple[float, float],
        destination: tuple[float, float],
        departure: datetime,
        profile_hash: str,
        routing_mode: str,
        routing_preference: str,
        estimate: dict,
    ) -> None:
        now = datetime.now(timezone.utc)
        existing = self._pending_cache.get(cache_key)
        if not existing:
            existing = self.db.scalar(select(RouteEstimationCache).where(RouteEstimationCache.cache_key == cache_key))
        values = {
            "origin_location_id": origin_id,
            "destination_location_id": destination_id,
            "origin_latitude": origin[0],
            "origin_longitude": origin[1],
            "destination_latitude": destination[0],
            "destination_longitude": destination[1],
            "departure_time_bucket": self._departure_bucket(departure),
            "vehicle_profile_hash": profile_hash,
            "routing_mode": routing_mode,
            "routing_preference": routing_preference,
            "distance_meters": estimate["distance_meters"],
            "duration_seconds": estimate["duration_seconds"],
            "static_duration_seconds": estimate.get("static_duration_seconds"),
            "provider_source": estimate["source"],
            "response_metadata": {
                "routing_confidence": estimate["routing_confidence"],
                "fallback_used": estimate.get("fallback_used", False),
                "warning_codes": estimate.get("warning_codes", []),
                "route_geometry": estimate.get("route_geometry", []),
                "route_geometry_source": estimate.get("route_geometry_source"),
                "road_geometry_attempted": bool(estimate.get("road_geometry_attempted", False)),
            },
            "calculated_at": now,
            "expires_at": now + timedelta(minutes=int(self.configuration.cache_ttl_minutes)),
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            existing = RouteEstimationCache(id=uuid.uuid4().hex, cache_key=cache_key, **values)
            self.db.add(existing)
        self._pending_cache[cache_key] = existing

    def _historical_fallback(
        self,
        origin_entity: MasterDepot | MasterSPBU,
        destination_entity: MasterDepot | MasterSPBU,
        origin: tuple[float, float] | None,
        destination: tuple[float, float] | None,
    ) -> dict:
        straight_geometry = (
            [
                {"latitude": origin[0], "longitude": origin[1]},
                {"latitude": destination[0], "longitude": destination[1]},
            ]
            if origin and destination
            else []
        )
        spbu = destination_entity if isinstance(destination_entity, MasterSPBU) else origin_entity if isinstance(origin_entity, MasterSPBU) else None
        if isinstance(spbu, MasterSPBU) and spbu.master_travel_time_min and spbu.master_travel_time_min > 0:
            duration = round(float(spbu.master_travel_time_min) * 60)
            distance = round(float(spbu.master_distance_km or 0) * 1000)
            if not distance and origin and destination:
                distance = round(_haversine_meters(origin, destination) * 1.25)
            return {
                "distance_meters": distance,
                "duration_seconds": duration,
                "static_duration_seconds": duration,
                "route_geometry": straight_geometry,
                "route_geometry_source": "MASTER_COORDINATE_FALLBACK",
                "source": "HISTORICAL_ROUTE",
                "routing_confidence": "MEDIUM",
                "fallback_used": True,
                "warning_codes": ["GOOGLE_ROUTES_FALLBACK"],
            }
        if isinstance(spbu, MasterSPBU):
            assignment = self.db.scalar(
                select(MLSPBUClusterAssignment).where(
                    MLSPBUClusterAssignment.model_id == self.model_id,
                    MLSPBUClusterAssignment.spbu_id == spbu.spbu_id,
                )
            )
            if assignment and assignment.cluster_id is not None:
                peer_ids = self.db.scalars(
                    select(MLSPBUClusterAssignment.spbu_id).where(
                        MLSPBUClusterAssignment.model_id == self.model_id,
                        MLSPBUClusterAssignment.cluster_id == assignment.cluster_id,
                    )
                ).all()
                peer_times = [
                    float(value)
                    for (value,) in self.db.execute(
                        select(MasterSPBU.master_travel_time_min).where(
                            MasterSPBU.spbu_id.in_(peer_ids), MasterSPBU.master_travel_time_min.is_not(None)
                        )
                    ).all()
                    if value and value > 0
                ]
                if peer_times:
                    duration = round(statistics.median(peer_times) * 60)
                    distance = round(_haversine_meters(origin, destination) * 1.25) if origin and destination else 0
                    return {
                        "distance_meters": distance,
                        "duration_seconds": duration,
                        "static_duration_seconds": duration,
                        "route_geometry": straight_geometry,
                        "route_geometry_source": "MASTER_COORDINATE_FALLBACK",
                        "source": "HISTORICAL_CLUSTER",
                        "routing_confidence": "MEDIUM",
                        "fallback_used": True,
                        "warning_codes": ["GOOGLE_ROUTES_FALLBACK"],
                    }
        duration = int(self.configuration.default_route_duration_minutes) * 60
        distance = round(_haversine_meters(origin, destination) * 1.25) if origin and destination else 0
        return {
            "distance_meters": distance,
            "duration_seconds": duration,
            "static_duration_seconds": duration,
            "route_geometry": straight_geometry,
            "route_geometry_source": "MASTER_COORDINATE_FALLBACK",
            "source": "DEFAULT_ESTIMATE",
            "routing_confidence": "LOW",
            "fallback_used": True,
            "warning_codes": ["DEFAULT_ROUTE_ESTIMATE"],
        }

    @staticmethod
    def _resolve_mode(_mt: MasterMT) -> dict:
        # Phase 6 Indonesia is deliberately DRIVE-only. Vehicle-specific TRUCK
        # profiles are not sent to Google Routes and cannot be enabled by stale settings.
        return {
            "api_mode": "DRIVE",
            "result_mode": "DRIVE",
            "profile": {
                "status": "NOT_REQUIRED",
                "missing_fields": [],
                "unsupported_hazmat_categories": [],
                "profile_hash": "drive-generic",
            },
            "fallback_used": False,
            "warning_codes": [],
        }

    def _estimate_leg(
        self,
        *,
        origin_entity: MasterDepot | MasterSPBU,
        destination_entity: MasterDepot | MasterSPBU,
        departure: datetime,
        mt: MasterMT,
        mode: dict,
        require_road_geometry: bool = False,
    ) -> dict:
        origin_id = origin_entity.depot_id if isinstance(origin_entity, MasterDepot) else origin_entity.spbu_id
        destination_id = destination_entity.depot_id if isinstance(destination_entity, MasterDepot) else destination_entity.spbu_id
        origin = self._coordinates(origin_entity)
        destination = self._coordinates(destination_entity)
        profile_hash = "drive-generic"
        cache_key = self._cache_key(
            origin_id=origin_id,
            destination_id=destination_id,
            departure=departure,
            profile_hash=profile_hash,
            routing_mode=mode["result_mode"],
            routing_preference=self.configuration.routing_preference,
        )
        cached = self._cached_leg(cache_key, require_road_geometry=require_road_geometry)
        if cached:
            cached["warning_codes"] = sorted(set(cached["warning_codes"] + mode["warning_codes"]))
            cached["fallback_used"] = cached["fallback_used"] or mode["fallback_used"]
            return cached
        estimate = None
        road_geometry_attempted = False
        if self.client and origin and destination:
            road_geometry_attempted = True
            self.metrics["google_routes_request_count"] += 1
            try:
                response = self.client.compute_route(
                    origin=origin,
                    destination=destination,
                    departure_datetime=departure,
                    routing_mode="DRIVE",
                    routing_preference=self.configuration.routing_preference,
                )
                if len(response.get("route_geometry") or []) < 2:
                    self.geometry_error_codes.add("GOOGLE_ROUTE_GEOMETRY_EMPTY")
                warnings = list(mode["warning_codes"])
                if response["restrictions_partially_ignored"]:
                    warnings.append("ROUTE_RESTRICTIONS_PARTIALLY_IGNORED")
                estimate = {
                    **response,
                    "source": "GOOGLE_ROUTES_DRIVE",
                    "routing_confidence": "MEDIUM" if response["restrictions_partially_ignored"] else "HIGH",
                    "fallback_used": mode["fallback_used"],
                    "road_geometry_attempted": True,
                    "warning_codes": sorted(set(warnings)),
                }
            except GoogleRoutesError as exc:
                self.metrics["google_routes_failed_request_count"] += 1
                self.geometry_error_codes.add(exc.code)
        elif require_road_geometry:
            self.geometry_error_codes.add("ROUTE_COORDINATES_MISSING" if not origin or not destination else "GOOGLE_ROUTES_KEY_UNAVAILABLE")
        if estimate is None:
            estimate = self._historical_fallback(origin_entity, destination_entity, origin, destination)
            estimate["road_geometry_attempted"] = road_geometry_attempted
            estimate["warning_codes"] = sorted(set(estimate["warning_codes"] + mode["warning_codes"]))
            estimate["fallback_used"] = True
        if origin and destination:
            self._store_cache(
                cache_key=cache_key,
                origin_id=origin_id,
                destination_id=destination_id,
                origin=origin,
                destination=destination,
                departure=departure,
                profile_hash=profile_hash,
                routing_mode=mode["result_mode"],
                routing_preference=self.configuration.routing_preference,
                estimate=estimate,
            )
        return estimate

    def _nearest_to_farthest_from_depot(self, depot: MasterDepot, spbus: list[MasterSPBU]) -> list[MasterSPBU]:
        """Order stops by radial distance from the depot, never by the previous stop."""
        depot_coordinates = self._coordinates(depot)

        def distance_key(spbu: MasterSPBU) -> tuple[float, str]:
            spbu_coordinates = self._coordinates(spbu)
            if depot_coordinates and spbu_coordinates:
                distance = _haversine_meters(depot_coordinates, spbu_coordinates)
            elif spbu.master_distance_km is not None:
                distance = float(spbu.master_distance_km) * 1000
            else:
                distance = math.inf
            return distance, spbu.spbu_code

        return sorted(spbus, key=distance_key)

    def estimate_trip(
        self,
        *,
        depot: MasterDepot,
        spbus: list[MasterSPBU],
        mt: MasterMT,
        predicted_departure_datetime: datetime,
        max_exact_sequence_stops: int,
        require_road_geometry: bool = False,
    ) -> dict:
        if not spbus:
            raise GoogleRoutesError("GOOGLE_ROUTE_NOT_FOUND", "Shipment has no SPBU stops.", status_code=422)
        mode = self._resolve_mode(mt)
        unique_spbus = list({spbu.spbu_id: spbu for spbu in spbus}.values())
        # Operations explicitly require the SPBU sequence to progress from the
        # nearest stop to the farthest stop relative to the depot. The
        # max_exact_sequence_stops argument remains in the public contract for
        # backward-compatible run snapshots but no longer changes this rule.
        _ = max_exact_sequence_stops
        sequence = self._nearest_to_farthest_from_depot(depot, unique_spbus)
        entities: list[MasterDepot | MasterSPBU] = [depot, *sequence, depot]
        legs = [
            self._estimate_leg(
                origin_entity=entities[index],
                destination_entity=entities[index + 1],
                departure=predicted_departure_datetime,
                mt=mt,
                mode=mode,
                require_road_geometry=require_road_geometry,
            )
            for index in range(len(entities) - 1)
        ]
        travel_duration = sum(leg["duration_seconds"] for leg in legs)
        depot_processing = int(self.configuration.default_depot_processing_minutes) * 60
        spbu_service = int(self.configuration.default_spbu_service_minutes) * 60 * len(sequence)
        return_processing = int(self.configuration.default_return_processing_minutes) * 60
        turnaround = int(self.configuration.default_turnaround_buffer_minutes) * 60
        service_duration = depot_processing + spbu_service + return_processing
        total_cycle = travel_duration + service_duration
        departure = _aware_utc(predicted_departure_datetime)
        estimated_return = departure + timedelta(seconds=total_cycle)
        next_available = estimated_return + timedelta(seconds=turnaround)
        confidence = min((leg["routing_confidence"] for leg in legs), key=lambda value: CONFIDENCE_ORDER[value])
        sources = sorted({leg["source"] for leg in legs})
        warnings = sorted({code for leg in legs for code in leg["warning_codes"]})
        fallback_used = mode["fallback_used"] or any(leg["fallback_used"] for leg in legs)
        route_geometry = []
        for leg in legs:
            for point in leg.get("route_geometry") or []:
                if not route_geometry or route_geometry[-1] != point:
                    route_geometry.append(point)
        geometry_sources = sorted({leg.get("route_geometry_source") for leg in legs if leg.get("route_geometry_source")})
        return {
            "estimated_visit_sequence": [spbu.spbu_id for spbu in sequence],
            "estimated_visit_sequence_codes": [spbu.spbu_code for spbu in sequence],
            "routing_provider": "GOOGLE_ROUTES" if all(source.startswith("GOOGLE_ROUTES") or source == "ROUTE_CACHE" for source in sources) else "FALLBACK_ESTIMATE",
            "routing_mode": "DRIVE",
            "routing_preference": self.configuration.routing_preference,
            "large_vehicle_used": False,
            "route_distance_meters": sum(leg["distance_meters"] for leg in legs),
            "route_duration_seconds": travel_duration,
            "static_duration_seconds": sum(leg.get("static_duration_seconds") or leg["duration_seconds"] for leg in legs),
            "service_duration_seconds": service_duration,
            "turnaround_buffer_seconds": turnaround,
            "total_cycle_duration_seconds": total_cycle,
            "estimated_return_datetime": estimated_return,
            "next_available_datetime": next_available,
            "routing_confidence": confidence,
            "route_estimation_source": sources[0] if len(sources) == 1 else "MIXED_ESTIMATE",
            "route_geometry": route_geometry,
            "route_geometry_source": geometry_sources[0] if len(geometry_sources) == 1 else "MIXED_GEOMETRY",
            "fallback_used": fallback_used,
            "warning_codes": warnings,
            "vehicle_profile_snapshot": {
                "profile_status": mode["profile"]["status"],
                "missing_fields": mode["profile"]["missing_fields"],
                "unsupported_hazmat_categories": mode["profile"]["unsupported_hazmat_categories"],
                "profile_hash": mode["profile"]["profile_hash"],
            },
            "service_time_source": "CONFIGURED_DEFAULT",
        }
