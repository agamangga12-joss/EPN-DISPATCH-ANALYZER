from __future__ import annotations

import base64
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .models import GoogleRoutesConfiguration


logger = logging.getLogger(__name__)
CONFIGURATION_ID = "default"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
SUPPORTED_ROUTING_MODES = {"DRIVE"}
SUPPORTED_ROUTING_PREFERENCES = {"TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"}


class GoogleRoutesError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _fernet() -> Fernet:
    encryption_key = (get_settings().google_routes_encryption_key or "").strip()
    if len(encryption_key) < 16:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SECRET_ENCRYPTION_NOT_CONFIGURED",
                "message": "GOOGLE_ROUTES_ENCRYPTION_KEY must be configured before an API key can be stored.",
            },
        )
    derived = base64.urlsafe_b64encode(hashlib.sha256(encryption_key.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_api_key: str) -> str:
    try:
        return _fernet().decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SECRET_DECRYPTION_FAILED", "message": "Stored Google Routes API key could not be decrypted."},
        ) from exc


def mask_api_key(api_key: str) -> str:
    return f"••••••••••••{api_key[-4:]}"


def get_google_routes_configuration(db: Session, *, create: bool = True) -> GoogleRoutesConfiguration | None:
    configuration = db.get(GoogleRoutesConfiguration, CONFIGURATION_ID)
    if configuration or not create:
        return configuration
    configuration = GoogleRoutesConfiguration(configuration_id=CONFIGURATION_ID)
    db.add(configuration)
    db.flush()
    return configuration


def configuration_snapshot(configuration: GoogleRoutesConfiguration | None) -> dict:
    if not configuration:
        return {
            "configuration_id": None,
            "configuration_version": None,
            "api_key_configured": False,
            "routing_mode": "DRIVE",
            "routing_preference": "TRAFFIC_AWARE",
            "fallback_policy": "NOT_APPLICABLE",
            "cache_ttl_minutes": 60,
            "departure_time_bucket_minutes": 15,
            "default_depot_processing_minutes": 30,
            "default_spbu_service_minutes": 45,
            "default_return_processing_minutes": 15,
            "default_turnaround_buffer_minutes": 30,
            "default_route_duration_minutes": 120,
            "connection_status": "NOT_CONFIGURED",
            "truck_routing_status": "DISABLED_FOR_INDONESIA",
        }
    return {
        "configuration_id": configuration.configuration_id,
        "configuration_version": configuration.configuration_version,
        "api_key_configured": bool(configuration.encrypted_api_key),
        "routing_mode": "DRIVE",
        "routing_preference": configuration.routing_preference,
        "fallback_policy": "NOT_APPLICABLE",
        "cache_ttl_minutes": configuration.cache_ttl_minutes,
        "departure_time_bucket_minutes": configuration.departure_time_bucket_minutes,
        "default_depot_processing_minutes": configuration.default_depot_processing_minutes,
        "default_spbu_service_minutes": configuration.default_spbu_service_minutes,
        "default_return_processing_minutes": configuration.default_return_processing_minutes,
        "default_turnaround_buffer_minutes": configuration.default_turnaround_buffer_minutes,
        "default_route_duration_minutes": configuration.default_route_duration_minutes,
        "connection_status": configuration.connection_status,
        "truck_routing_status": "DISABLED_FOR_INDONESIA",
    }


def public_google_routes_configuration(db: Session, *, depot_id: str | None = None) -> dict:
    configuration = get_google_routes_configuration(db)
    assert configuration is not None
    _ = depot_id  # Retained for backward-compatible callers; DRIVE-only routing is depot agnostic here.
    return {
        **configuration_snapshot(configuration),
        "masked_api_key": configuration.masked_api_key,
        "last_test_result": configuration.last_test_result or {},
        "encryption_ready": len((get_settings().google_routes_encryption_key or "").strip()) >= 16,
        "updated_by": configuration.updated_by,
        "updated_at": configuration.updated_at.isoformat() if configuration.updated_at else None,
    }


def save_google_routes_configuration(db: Session, payload: dict, *, updated_by: str) -> dict:
    configuration = get_google_routes_configuration(db)
    assert configuration is not None
    routing_preference = str(payload.get("routing_preference", configuration.routing_preference)).upper()
    if routing_preference not in SUPPORTED_ROUTING_PREFERENCES:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ROUTING_PREFERENCE", "message": "Unsupported Google routing preference."})
    numeric_bounds = {
        "cache_ttl_minutes": (1, 10080),
        "departure_time_bucket_minutes": (1, 1440),
        "default_depot_processing_minutes": (0, 1440),
        "default_spbu_service_minutes": (0, 1440),
        "default_return_processing_minutes": (0, 1440),
        "default_turnaround_buffer_minutes": (0, 1440),
        "default_route_duration_minutes": (1, 10080),
    }
    for field, (minimum, maximum) in numeric_bounds.items():
        if field not in payload:
            continue
        try:
            value = int(payload[field])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_ROUTE_CONFIGURATION", "message": f"{field} must be an integer."}) from exc
        if value < minimum or value > maximum:
            raise HTTPException(status_code=400, detail={"code": "INVALID_ROUTE_CONFIGURATION", "message": f"{field} must be between {minimum} and {maximum}."})
        setattr(configuration, field, value)
    api_key = str(payload.get("api_key") or "").strip()
    if api_key:
        if len(api_key) < 20:
            raise HTTPException(status_code=400, detail={"code": "INVALID_API_KEY_FORMAT", "message": "Google Maps API key is too short."})
        configuration.encrypted_api_key = encrypt_api_key(api_key)
        configuration.key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        configuration.masked_api_key = mask_api_key(api_key)
        configuration.connection_status = "NOT_TESTED"
        configuration.truck_routing_status = "DISABLED_FOR_INDONESIA"
        configuration.last_test_result = {}
    configuration.routing_mode = "DRIVE"
    configuration.routing_preference = routing_preference
    configuration.fallback_policy = "NOT_APPLICABLE"
    configuration.configuration_version = int(configuration.configuration_version or 0) + 1
    configuration.updated_by = updated_by
    db.commit()
    return public_google_routes_configuration(db)


def delete_google_routes_api_key(db: Session, *, updated_by: str) -> dict:
    configuration = get_google_routes_configuration(db)
    assert configuration is not None
    configuration.encrypted_api_key = None
    configuration.key_fingerprint = None
    configuration.masked_api_key = None
    configuration.connection_status = "NOT_CONFIGURED"
    configuration.truck_routing_status = "DISABLED_FOR_INDONESIA"
    configuration.last_test_result = {}
    configuration.configuration_version = int(configuration.configuration_version or 0) + 1
    configuration.updated_by = updated_by
    db.commit()
    return public_google_routes_configuration(db)


def _parse_duration(value: str | None) -> int:
    if not value or not value.endswith("s"):
        return 0
    return round(float(value[:-1]))


def _geojson_route_geometry(route: dict) -> list[dict[str, float]]:
    coordinates = ((route.get("polyline") or {}).get("geoJsonLinestring") or {}).get("coordinates") or []
    geometry = []
    for coordinate in coordinates:
        if not isinstance(coordinate, list) or len(coordinate) < 2:
            continue
        try:
            longitude, latitude = float(coordinate[0]), float(coordinate[1])
        except (TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            geometry.append({"latitude": latitude, "longitude": longitude})
    return geometry


class GoogleRoutesClient:
    """Server-side Routes API client used only for per-trip travel estimation.

    This client intentionally has no Route Optimization / optimizeTours endpoint.
    Phase 6 estimates one route leg or route matrix; fleet-wide VRP belongs to Phase 7.
    """

    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key
        settings = get_settings()
        self._timeout = settings.google_routes_request_timeout_seconds
        self._max_retries = settings.google_routes_max_retries
        self._transport = transport

    def _post(self, url: str, payload: dict, field_mask: str) -> Any:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": field_mask,
        }
        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                    response = client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise GoogleRoutesError("GOOGLE_REQUEST_TIMEOUT", "Google Routes request timed out.", status_code=504) from exc
            except httpx.HTTPError as exc:
                if attempt < self._max_retries:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise GoogleRoutesError("GOOGLE_CONNECTION_ERROR", "Google Routes could not be reached.", status_code=502) from exc
            if response.status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                time.sleep(0.1 * (2**attempt))
                continue
            if response.is_success:
                return response.json()
            try:
                error_payload = response.json()
                safe_message = str(error_payload.get("error", {}).get("message") or "Google Routes request failed.")
                status = str(error_payload.get("error", {}).get("status") or "")
            except Exception:
                safe_message, status = "Google Routes request failed.", ""
            normalized = safe_message.lower()
            if "not been used" in normalized or "disabled" in normalized or "not enabled" in normalized:
                code = "GOOGLE_ROUTES_NOT_ENABLED"
            elif response.status_code in {401, 403} and ("api key" in normalized or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}):
                code = "GOOGLE_API_KEY_INVALID"
            elif response.status_code == 429:
                code = "GOOGLE_RATE_LIMIT"
            elif response.status_code == 404:
                code = "GOOGLE_ROUTE_NOT_FOUND"
            else:
                code = "GOOGLE_ROUTE_REQUEST_FAILED"
            logger.warning("Google Routes request failed: code=%s status=%s", code, response.status_code)
            raise GoogleRoutesError(code, safe_message, status_code=response.status_code)
        raise GoogleRoutesError("GOOGLE_ROUTE_REQUEST_FAILED", "Google Routes request failed.")

    @staticmethod
    def _waypoint(latitude: float, longitude: float) -> dict:
        return {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}

    @staticmethod
    def _future_departure(departure_datetime: datetime | None) -> str | None:
        if not departure_datetime:
            return None
        aware = departure_datetime if departure_datetime.tzinfo else departure_datetime.replace(tzinfo=timezone.utc)
        if aware <= datetime.now(timezone.utc) + timedelta(minutes=1):
            return None
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def compute_route(
        self,
        *,
        origin: tuple[float, float],
        destination: tuple[float, float],
        departure_datetime: datetime | None,
        routing_mode: str,
        routing_preference: str,
        intermediates: list[tuple[float, float]] | None = None,
        via_intermediates: bool = False,
        high_quality: bool = False,
    ) -> dict:
        if routing_mode not in SUPPORTED_ROUTING_MODES:
            raise GoogleRoutesError(
                "UNSUPPORTED_ROUTING_MODE",
                "Phase 6 Indonesia supports Google Routes DRIVE mode only.",
                status_code=422,
            )
        payload: dict[str, Any] = {
            "origin": self._waypoint(*origin),
            "destination": self._waypoint(*destination),
            "travelMode": "DRIVE",
            "routingPreference": routing_preference,
            "polylineQuality": "HIGH_QUALITY" if high_quality else "OVERVIEW",
            "polylineEncoding": "GEO_JSON_LINESTRING",
        }
        if intermediates:
            if len(intermediates) > 25:
                raise GoogleRoutesError("GOOGLE_WAYPOINT_LIMIT", "At most 25 intermediate waypoints are supported.", status_code=422)
            payload["intermediates"] = [self._waypoint(latitude, longitude) for latitude, longitude in intermediates]
            if via_intermediates:
                for waypoint in payload["intermediates"]:
                    waypoint["via"] = True
        departure = self._future_departure(departure_datetime)
        if departure:
            payload["departureTime"] = departure
        response = self._post(
            ROUTES_URL,
            payload,
            "routes.distanceMeters,routes.duration,routes.staticDuration,routes.polyline.geoJsonLinestring,routes.travelAdvisory.routeRestrictionsPartiallyIgnored,routes.warnings",
        )
        routes = response.get("routes") or []
        if not routes:
            raise GoogleRoutesError("GOOGLE_ROUTE_NOT_FOUND", "Google Routes returned no route.", status_code=404)
        route = routes[0]
        return {
            "distance_meters": int(route.get("distanceMeters") or 0),
            "duration_seconds": _parse_duration(route.get("duration")),
            "static_duration_seconds": _parse_duration(route.get("staticDuration")) or None,
            "route_geometry": _geojson_route_geometry(route),
            "route_geometry_source": "GOOGLE_ROUTES_GEOJSON",
            "restrictions_partially_ignored": bool((route.get("travelAdvisory") or {}).get("routeRestrictionsPartiallyIgnored")),
            "warnings": route.get("warnings") or [],
            "departure_time_sent": departure,
            "routing_preference": routing_preference,
        }

    def compute_route_matrix(
        self,
        *,
        origin: tuple[float, float],
        destination: tuple[float, float],
        departure_datetime: datetime | None,
    ) -> dict:
        rows = self.compute_route_matrix_batch(
            origins=[origin],
            destinations=[destination],
            departure_datetime=departure_datetime,
        )
        if not rows or rows[0].get("condition") not in {None, "ROUTE_EXISTS"}:
            raise GoogleRoutesError("GOOGLE_ROUTE_NOT_FOUND", "Google Route Matrix returned no route.", status_code=404)
        return rows[0]

    def compute_route_matrix_batch(
        self,
        *,
        origins: list[tuple[float, float]],
        destinations: list[tuple[float, float]],
        departure_datetime: datetime | None,
    ) -> list[dict]:
        """Return one matrix element per origin/destination combination.

        Google accepts at most 625 non-transit elements in one request.  Keep
        that guard next to the HTTP client so every caller receives the same
        fail-fast contract instead of accidentally creating thousands of
        single-pair requests.
        """
        if not origins or not destinations:
            return []
        element_count = len(origins) * len(destinations)
        if element_count > 625:
            raise GoogleRoutesError(
                "GOOGLE_MATRIX_ELEMENT_LIMIT",
                "Google Route Matrix requests support at most 625 elements.",
                status_code=422,
            )
        payload: dict[str, Any] = {
            "origins": [{"waypoint": self._waypoint(*origin)} for origin in origins],
            "destinations": [{"waypoint": self._waypoint(*destination)} for destination in destinations],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        departure = self._future_departure(departure_datetime)
        if departure:
            payload["departureTime"] = departure
        response = self._post(
            MATRIX_URL,
            payload,
            "originIndex,destinationIndex,status,condition,distanceMeters,duration,staticDuration",
        )
        return response if isinstance(response, list) else []


def test_google_routes_connection(db: Session, *, tested_by: str) -> dict:
    configuration = get_google_routes_configuration(db)
    assert configuration is not None
    if not configuration.encrypted_api_key:
        result = {
            "connection_status": "NOT_CONFIGURED",
            "checks": {
                "api_key_valid": "NOT_RUN",
                "routes_api": "NOT_RUN",
                "compute_routes": "NOT_RUN",
                "compute_route_matrix": "NOT_RUN",
            },
        }
        configuration.connection_status = "NOT_CONFIGURED"
        configuration.last_test_result = result
        db.commit()
        return result
    api_key = decrypt_api_key(configuration.encrypted_api_key)
    client = GoogleRoutesClient(api_key)
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    checks = {
        "api_key_valid": "NOT_RUN",
        "routes_api": "NOT_RUN",
        "compute_routes": "NOT_RUN",
        "compute_route_matrix": "NOT_RUN",
    }
    error_code = None
    try:
        client.compute_route(
            origin=(-6.2088, 106.8456),
            destination=(-6.2146, 106.8451),
            departure_datetime=future,
            routing_mode="DRIVE",
            routing_preference="TRAFFIC_AWARE",
        )
        checks.update({"api_key_valid": "PASS", "routes_api": "PASS", "compute_routes": "PASS"})
        client.compute_route_matrix(
            origin=(-6.2088, 106.8456), destination=(-6.2146, 106.8451), departure_datetime=future
        )
        checks["compute_route_matrix"] = "PASS"
        configuration.truck_routing_status = "DISABLED_FOR_INDONESIA"
        configuration.connection_status = "CONNECTED"
    except GoogleRoutesError as exc:
        error_code = exc.code
        checks["api_key_valid"] = "FAIL" if exc.code == "GOOGLE_API_KEY_INVALID" else checks["api_key_valid"]
        checks["routes_api"] = "FAIL"
        configuration.connection_status = {
            "GOOGLE_API_KEY_INVALID": "INVALID_KEY",
            "GOOGLE_ROUTES_NOT_ENABLED": "ROUTES_API_NOT_ENABLED",
        }.get(exc.code, "CONNECTION_ERROR")
    result = {
        "connection_status": configuration.connection_status,
        "truck_routing_status": "DISABLED_FOR_INDONESIA",
        "checks": checks,
        "error_code": error_code,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "tested_by": tested_by,
    }
    configuration.last_test_result = result
    configuration.updated_by = tested_by
    db.commit()
    return result
