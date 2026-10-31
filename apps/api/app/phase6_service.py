from __future__ import annotations

import logging
import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session, defer

from .google_routes import GoogleRoutesError, configuration_snapshot, get_google_routes_configuration
from .compatibility import evaluate_compatibility_entities
from .models import (
    BridgeMTTag,
    BridgeSPBUTag,
    MasterTag,
    MLBehavioralModel,
    MLSPBUClusterAssignment,
    MasterDepot,
    MasterMT,
    MasterSPBU,
    PredictionAssignment,
    PredictionMTCandidate,
    PredictionRun,
    PredictionShipment,
    PredictionShipmentLine,
    PredictionTrip,
)
from .phase6_jobs import (
    PredictionLeaseLost,
    complete_prediction_job,
    enqueue_prediction_job,
    fail_prediction_job,
    prediction_job_payload,
)
from .phase5_registry import _model_summary
from .phase6_constants import (
    DEFAULT_PREDICTION_PARAMETERS,
    PHASE6_ALGORITHM_VERSION,
    PHASE6_VEHICLE_COMPATIBILITY_MODE,
)
from .phase6_capacity import mt_compartment_profile, shipment_capacity
from .phase6_inference import load_model_inference_evidence, predict_mt_candidates, predict_shipments
from .phase6_iterative import build_iterative_capacity_plan
from .phase6_routing import Phase6RouteEstimationService
from .phase6_validation import require_prediction_model, validate_loading_orders, validate_mt_availability


logger = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value else None


def _hourly_distribution(assigned_shipments: list[dict], depot: MasterDepot | None) -> list[dict]:
    timezone_name = depot.timezone if depot and depot.timezone else "Asia/Jakarta"
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = ZoneInfo("Asia/Jakarta")
    buckets: dict[datetime, dict[str, float | int]] = defaultdict(
        lambda: {"delivered_kl": 0.0, "shipment_count": 0, "loading_order_count": 0}
    )
    for shipment in assigned_shipments:
        trip = shipment.get("trip") or {}
        departure_value = trip.get("predicted_departure_datetime")
        if not departure_value:
            continue
        departure = datetime.fromisoformat(departure_value).astimezone(local_timezone)
        hour = departure.replace(minute=0, second=0, microsecond=0)
        buckets[hour]["delivered_kl"] += float(shipment.get("total_order_kl") or 0)
        buckets[hour]["shipment_count"] += 1
        buckets[hour]["loading_order_count"] += len(shipment.get("lines") or [])
    if not buckets:
        return []
    rows = []
    cumulative = 0.0
    current, last = min(buckets), max(buckets)
    while current <= last:
        values = buckets[current]
        delivered = round(float(values["delivered_kl"]), 3)
        cumulative = round(cumulative + delivered, 3)
        rows.append(
            {
                "hour_start": current.isoformat(),
                "timezone": timezone_name,
                "delivered_kl": delivered,
                "cumulative_kl": cumulative,
                "shipment_count": int(values["shipment_count"]),
                "loading_order_count": int(values["loading_order_count"]),
            }
        )
        current += timedelta(hours=1)
    return rows


def _coordinates(entity: MasterDepot | MasterSPBU | None) -> tuple[float, float] | None:
    if entity is None or entity.latitude is None or entity.longitude is None:
        return None
    latitude, longitude = float(entity.latitude), float(entity.longitude)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _distance_from_depot(depot: MasterDepot | None, spbu: MasterSPBU) -> float:
    depot_coordinates, spbu_coordinates = _coordinates(depot), _coordinates(spbu)
    if depot_coordinates and spbu_coordinates:
        lat1, lon1 = map(math.radians, depot_coordinates)
        lat2, lon2 = map(math.radians, spbu_coordinates)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6_371_000 * 2 * math.asin(math.sqrt(haversine))
    if spbu.master_distance_km is not None:
        return float(spbu.master_distance_km) * 1000
    return math.inf


def _display_route_geometry(points: list[dict], maximum_points: int = 2000) -> list[dict]:
    """Bound legacy high-resolution geometry payloads while retaining endpoints."""
    if len(points) <= maximum_points:
        return points
    last_index = len(points) - 1
    sampled = [points[round(index * last_index / (maximum_points - 1))] for index in range(maximum_points)]
    return sampled


def _geographic_routes(
    assigned_shipments: list[dict],
    depot: MasterDepot | None,
    spbus: dict[str, MasterSPBU],
    *,
    include_road_geometry: bool = False,
) -> dict:
    depot_coordinates = _coordinates(depot)
    routes = []
    for shipment in assigned_shipments:
        trip = shipment.get("trip") or {}
        unique_spbus = {
            line["spbu_id"]: spbus[line["spbu_id"]]
            for line in shipment.get("lines") or []
            if line.get("spbu_id") in spbus
        }
        ordered_spbus = sorted(unique_spbus.values(), key=lambda spbu: (_distance_from_depot(depot, spbu), spbu.spbu_code))
        stops = []
        points = []
        if depot_coordinates:
            points.append({"type": "DEPOT", "code": depot.depot_code if depot else "DEPOT", "name": depot.depot_name if depot else "Depot", "latitude": depot_coordinates[0], "longitude": depot_coordinates[1]})
        for sequence, spbu in enumerate(ordered_spbus, start=1):
            coordinates = _coordinates(spbu)
            distance_from_depot = _distance_from_depot(depot, spbu)
            stop = {
                "sequence": sequence,
                "spbu_id": spbu.spbu_id,
                "spbu_code": spbu.spbu_code,
                "spbu_name": spbu.spbu_name,
                "distance_from_depot_meters": None if math.isinf(distance_from_depot) else round(distance_from_depot),
                "latitude": coordinates[0] if coordinates else None,
                "longitude": coordinates[1] if coordinates else None,
            }
            stops.append(stop)
            if coordinates:
                points.append({"type": "SPBU", "code": spbu.spbu_code, "name": spbu.spbu_name, "sequence": sequence, "latitude": coordinates[0], "longitude": coordinates[1]})
        if depot_coordinates:
            points.append({"type": "DEPOT_RETURN", "code": depot.depot_code if depot else "DEPOT", "name": depot.depot_name if depot else "Depot", "latitude": depot_coordinates[0], "longitude": depot_coordinates[1]})
        route_geometry = []
        if include_road_geometry:
            for point in trip.get("route_geometry") or []:
                try:
                    latitude, longitude = float(point["latitude"]), float(point["longitude"])
                except (KeyError, TypeError, ValueError):
                    continue
                if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                    route_geometry.append({"latitude": latitude, "longitude": longitude})
        geometry_source = trip.get("route_geometry_source") if include_road_geometry else None
        original_geometry_point_count = len(route_geometry)
        if len(route_geometry) < 2:
            route_geometry = [
                {"latitude": point["latitude"], "longitude": point["longitude"]}
                for point in points
            ]
            geometry_source = "MASTER_COORDINATE_FALLBACK"
        route_geometry = _display_route_geometry(route_geometry)
        routes.append(
            {
                "trip_id": trip.get("trip_id"),
                "trip_number": trip.get("trip_number"),
                "shipment_id": shipment["predicted_shipment_id"],
                "vehicle_id": trip.get("vehicle_id"),
                "vehicle_registration_no": trip.get("vehicle_registration_no"),
                "predicted_departure_datetime": trip.get("predicted_departure_datetime"),
                "total_order_kl": shipment.get("total_order_kl", 0),
                "stops": stops,
                "points": points,
                "route_geometry": route_geometry,
                "route_geometry_source": geometry_source,
                "original_geometry_point_count": original_geometry_point_count,
                "uses_road_geometry": geometry_source == "GOOGLE_ROUTES_GEOJSON",
                "missing_coordinate_count": sum(stop["latitude"] is None or stop["longitude"] is None for stop in stops),
                "mappable": bool(depot_coordinates and any(point["type"] == "SPBU" for point in points)),
            }
        )
    return {
        "sequence_policy": "NEAREST_TO_FARTHEST_FROM_DEPOT",
        "geometry_source": "GOOGLE_ROUTES_WITH_MASTER_FALLBACK",
        "marker_coordinate_source": "MASTER_DEPOT_AND_SPBU",
        "depot": {
            "depot_id": depot.depot_id if depot else None,
            "depot_code": depot.depot_code if depot else None,
            "depot_name": depot.depot_name if depot else None,
            "latitude": depot_coordinates[0] if depot_coordinates else None,
            "longitude": depot_coordinates[1] if depot_coordinates else None,
        },
        "routes": routes,
    }


def list_prediction_models(db: Session, depot_id: str) -> list[dict]:
    models = db.scalars(
        select(MLBehavioralModel)
        .where(MLBehavioralModel.depot_id == depot_id, MLBehavioralModel.model_status.in_(("SAVED", "ACTIVE", "READY")))
        .order_by(desc(MLBehavioralModel.created_at))
    ).all()
    depot = db.get(MasterDepot, depot_id)
    return [
        {
            **_model_summary(model, depot.depot_name if depot else depot_id),
            "algorithm": "Phase 5 behavioral clustering and historical SPBU-MT affinity",
            "number_of_training_shipments": model.training_shipment_count,
            "number_of_spbu": model.training_spbu_count,
            "number_of_clusters": model.cluster_count,
            "model_quality_metrics": {
                "average_membership_probability": model.average_membership_probability,
                "noise_spbu_count": model.noise_spbu_count,
            },
            "shift_definition_snapshot": model.shift_definition_snapshot,
        }
        for model in models
    ]


def _parameters(overrides: dict | None) -> dict:
    parameters = {**DEFAULT_PREDICTION_PARAMETERS, **(overrides or {})}
    for key in ("minimum_prediction_confidence", "high_confidence_threshold", "medium_confidence_threshold"):
        try:
            parameters[key] = float(parameters[key])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": f"{key} must be numeric."}) from exc
        if not 0 <= parameters[key] <= 1:
            raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": f"{key} must be between 0 and 1."})
    if parameters["high_confidence_threshold"] < parameters["medium_confidence_threshold"]:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": "High confidence threshold must not be below medium threshold."})
    try:
        parameters["maximum_group_route_detour_ratio"] = float(parameters["maximum_group_route_detour_ratio"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": "maximum_group_route_detour_ratio must be numeric."}) from exc
    if not 1 <= parameters["maximum_group_route_detour_ratio"] <= 5:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": "maximum_group_route_detour_ratio must be between 1 and 5."})
    blocking = parameters.get("blocking_prediction_confidence")
    if blocking in ("", None):
        parameters["blocking_prediction_confidence"] = None
    else:
        parameters["blocking_prediction_confidence"] = float(blocking)
        if not 0 <= parameters["blocking_prediction_confidence"] <= 1:
            raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": "Blocking confidence must be between 0 and 1."})
    parameters["assignment_mode"] = str(parameters.get("assignment_mode", "STRICT_START")).upper()
    if parameters["assignment_mode"] not in {"STRICT_START", "ALLOW_DELAY"}:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": "assignment_mode must be STRICT_START or ALLOW_DELAY."})
    bounds = {
        "maximum_pairing_time_gap_minutes": (0, 1440),
        "maximum_shipment_compartments": (1, 4),
        "maximum_allowed_delay_minutes": (0, 1440),
        "max_exact_sequence_stops": (1, 7),
        "maximum_planning_horizon_days": (1, 31),
        "random_seed": (0, 2_147_483_647),
    }
    for field, (minimum, maximum) in bounds.items():
        try:
            parameters[field] = int(parameters[field])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": f"{field} must be an integer."}) from exc
        if not minimum <= parameters[field] <= maximum:
            raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": f"{field} must be between {minimum} and {maximum}."})
    # Phase 6 only dispatches a fully utilized MT: 4/3/2/1 LO must use an
    # MT with exactly 4/3/2/1 compartments respectively.
    parameters["require_full_mt_utilization"] = True
    # Vehicle class on an SPBU is its maximum admitted MT capacity, not an
    # exact class. Keep this invariant in the immutable run snapshot so worker
    # retries and later recalculation cannot drift with process configuration.
    parameters["vehicle_compatibility_mode"] = PHASE6_VEHICLE_COMPATIBILITY_MODE
    return parameters


def _run_number() -> str:
    return f"PRED-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _persist_candidates(
    db: Session,
    shipment_entities: dict[str, PredictionShipment],
    candidate_map: dict[str, list[dict]],
) -> None:
    for external_id, candidates in candidate_map.items():
        shipment = shipment_entities[external_id]
        for candidate in candidates:
            db.add(
                PredictionMTCandidate(
                    id=uuid.uuid4().hex,
                    prediction_shipment_id=shipment.id,
                    vehicle_id=candidate["vehicle_id"],
                    prediction_score=candidate["prediction_score"],
                    compatibility_status=candidate["compatibility_status"],
                    candidate_rank=candidate["candidate_rank"],
                    exclusion_reason=candidate["exclusion_reason"],
                    explanation=candidate["explanation"],
                )
            )


def _persist_iterative_capacity_plan(db: Session, run: PredictionRun, planning: dict) -> None:
    entities: dict[str, PredictionShipment] = {}
    original_snapshot = []
    for item in planning["plan"]:
        prediction = item["prediction"]
        entity = PredictionShipment(
            id=uuid.uuid4().hex,
            prediction_run_id=run.id,
            predicted_shipment_id=prediction["predicted_shipment_id"],
            shift_id=prediction["shift_id"],
            shift_name=prediction["shift"],
            planned_start_datetime=prediction["planned_start_datetime"],
            shipment_prediction_score=prediction["score"],
            confidence_level=prediction["confidence_level"],
            low_confidence=prediction["low_confidence"],
            explanation=prediction["explanation"],
        )
        db.add(entity)
        entities[prediction["predicted_shipment_id"]] = entity
        selected = item["selected_candidate"]
        original_snapshot.append(
            {
                "predicted_shipment_id": prediction["predicted_shipment_id"],
                "shift_id": prediction["shift_id"],
                "planned_start_datetime": _iso(prediction["planned_start_datetime"]),
                "score": prediction["score"],
                "loading_order_nos": [line["loading_order_no"] for line in prediction["lines"]],
                "spbu_ids": [line["spbu_id"] for line in prediction["lines"]],
                "assigned_vehicle_id": selected["vehicle_id"] if selected else None,
                "assignment_score": selected["prediction_score"] if selected else None,
            }
        )
    # These models intentionally use scalar foreign-key IDs instead of ORM
    # relationships, so persist all shipment parents first.
    db.flush()

    for item in planning["plan"]:
        prediction = item["prediction"]
        entity = entities[prediction["predicted_shipment_id"]]
        for line in prediction["lines"]:
            db.add(
                PredictionShipmentLine(
                    id=uuid.uuid4().hex,
                    prediction_run_id=run.id,
                    prediction_shipment_id=entity.id,
                    loading_order_no=line["loading_order_no"],
                    spbu_id=line["spbu_id"],
                    spbu_no=line["spbu_no"],
                    product_id=line.get("product_id"),
                    product_name=line.get("product_name"),
                    order_quantity_kl=line.get("order_quantity_kl"),
                    shipment_start_datetime=datetime.fromisoformat(line["shipment_start_datetime"]),
                    model_predicted_shipment_id=prediction["predicted_shipment_id"],
                )
            )
    _persist_candidates(
        db,
        entities,
        {
            item["prediction"]["predicted_shipment_id"]: item["candidates"]
            for item in planning["plan"]
        },
    )
    db.flush()

    final_snapshot = []
    for sequence, item in enumerate(planning["plan"], start=1):
        prediction = item["prediction"]
        shipment = entities[prediction["predicted_shipment_id"]]
        candidate = item["selected_candidate"]
        estimate = item["estimate"]
        status = item["assignment_status"]
        unassigned_reason = item["unassigned_reason"]
        assignment = PredictionAssignment(
            id=uuid.uuid4().hex,
            prediction_shipment_id=shipment.id,
            original_vehicle_id=candidate["vehicle_id"] if candidate else None,
            original_assignment_score=candidate["prediction_score"] if candidate else None,
            final_vehicle_id=candidate["vehicle_id"] if candidate else None,
            final_assignment_score=candidate["prediction_score"] if candidate else None,
            assignment_status=status,
            unassigned_reason=unassigned_reason,
        )
        db.add(assignment)
        planned = _utc(prediction["planned_start_datetime"])
        if candidate and estimate:
            trip = PredictionTrip(
                id=uuid.uuid4().hex,
                prediction_run_id=run.id,
                prediction_shipment_id=shipment.id,
                trip_id=f"TRIP-{sequence:04d}",
                trip_number=item["trip_number"],
                vehicle_id=candidate["vehicle_id"],
                planned_start_datetime=planned,
                predicted_departure_datetime=item["departure"],
                delay_minutes=item["delay_minutes"],
                estimated_visit_sequence=estimate["estimated_visit_sequence_codes"],
                routing_provider=estimate["routing_provider"],
                routing_mode=estimate["routing_mode"],
                routing_preference=estimate["routing_preference"],
                large_vehicle_used=estimate["large_vehicle_used"],
                route_distance_meters=estimate["route_distance_meters"],
                route_duration_seconds=estimate["route_duration_seconds"],
                static_duration_seconds=estimate["static_duration_seconds"],
                service_duration_seconds=estimate["service_duration_seconds"],
                turnaround_buffer_seconds=estimate["turnaround_buffer_seconds"],
                total_cycle_duration_seconds=estimate["total_cycle_duration_seconds"],
                estimated_return_datetime=estimate["estimated_return_datetime"],
                next_available_datetime=estimate["next_available_datetime"],
                routing_confidence=estimate["routing_confidence"],
                route_estimation_source=estimate["route_estimation_source"],
                route_geometry=estimate["route_geometry"],
                route_geometry_source=estimate["route_geometry_source"],
                service_time_source=estimate["service_time_source"],
                assignment_status=status,
                fallback_used=estimate["fallback_used"],
                warning_codes=estimate["warning_codes"],
                vehicle_profile_snapshot=estimate["vehicle_profile_snapshot"],
            )
        else:
            final_reason = unassigned_reason or "NO_MT_AVAILABLE_AT_REQUIRED_TIME"
            trip = PredictionTrip(
                id=uuid.uuid4().hex,
                prediction_run_id=run.id,
                prediction_shipment_id=shipment.id,
                trip_id=f"TRIP-{sequence:04d}",
                planned_start_datetime=planned,
                delay_minutes=0,
                assignment_status="UNASSIGNED",
                unassigned_reason=final_reason,
                warning_codes=[final_reason],
            )
        db.add(trip)
        final_snapshot.append(
            {
                "trip_id": trip.trip_id,
                "predicted_shipment_id": prediction["predicted_shipment_id"],
                "vehicle_id": trip.vehicle_id,
                "planned_start_datetime": _iso(planned),
                "predicted_departure_datetime": _iso(trip.predicted_departure_datetime),
                "estimated_return_datetime": _iso(trip.estimated_return_datetime),
                "next_available_datetime": _iso(trip.next_available_datetime),
                "predicted_visit_sequence": trip.estimated_visit_sequence,
                "shipment_score": prediction["score"],
                "vehicle_score": candidate["prediction_score"] if candidate else None,
                "assignment_status": trip.assignment_status,
                "route_estimation_source": trip.route_estimation_source,
            }
        )

    run.original_prediction_snapshot = original_snapshot
    run.final_prediction_snapshot = final_snapshot
    run.routing_metrics_snapshot = planning["routing_metrics"]


def enqueue_prediction_run(
    db: Session,
    *,
    depot_id: str,
    model_id: str,
    loading_order_content: bytes,
    loading_order_filename: str,
    availability_content: bytes,
    availability_filename: str,
    parameters: dict | None,
    created_by: str,
) -> dict:
    model = require_prediction_model(db, depot_id, model_id)
    parameter_snapshot = _parameters(parameters)
    lo_validation = validate_loading_orders(
        db,
        depot_id=depot_id,
        model=model,
        content=loading_order_content,
        file_name=loading_order_filename,
        maximum_planning_horizon_days=parameter_snapshot["maximum_planning_horizon_days"],
    )
    mt_validation = validate_mt_availability(
        db, depot_id=depot_id, model=model, content=availability_content, file_name=availability_filename
    )
    validation_issues = [*lo_validation["issues"], *mt_validation["issues"]]
    if lo_validation["blocking_error_count"] or mt_validation["blocking_error_count"]:
        raise HTTPException(
            status_code=422,
            detail={"code": "INPUT_VALIDATION_FAILED", "message": "Prediction input contains blocking validation errors.", "issues": validation_issues},
        )
    depot = db.get(MasterDepot, depot_id)
    if not depot:
        raise HTTPException(status_code=404, detail={"code": "DEPOT_NOT_FOUND", "message": "Depot was not found."})
    configuration = get_google_routes_configuration(db)
    assert configuration is not None
    run_id = uuid.uuid4().hex
    run_number = _run_number()
    run = PredictionRun(
        id=run_id,
        prediction_run_no=run_number,
        depot_id=depot_id,
        model_id=model_id,
        model_version=model.model_version,
        status="QUEUED",
        created_by=created_by,
        input_loading_order_filename=loading_order_filename,
        input_mt_availability_filename=availability_filename,
        input_loading_order_snapshot=lo_validation["normalized_rows"],
        input_mt_availability_snapshot=mt_validation["normalized_rows"],
        validation_snapshot=validation_issues,
        parameter_snapshot=parameter_snapshot,
        model_snapshot={
            "model_id": model.model_id,
            "model_name": model.model_name,
            "model_version": model.model_version,
            "algorithm_version": model.algorithm_version,
            "random_seed": model.random_seed,
            "shift_definition_snapshot": model.shift_definition_snapshot,
            "feature_weights": model.feature_weights,
        },
        original_prediction_snapshot=[],
        final_prediction_snapshot=[],
        routing_configuration_snapshot=configuration_snapshot(configuration),
        routing_metrics_snapshot={},
        algorithm_version=PHASE6_ALGORITHM_VERSION,
        validation_duration_ms=lo_validation["duration_ms"] + mt_validation["duration_ms"],
    )
    db.add(run)
    # PredictionJob intentionally has no ORM relationship; persist its parent
    # first so databases with immediate FK checks cannot reorder both inserts.
    db.flush()
    enqueue_prediction_job(db, run.id)
    db.commit()
    logger.info("prediction_run_queued", extra={"prediction_run_id": run_number, "model_id": model_id, "depot_id": depot_id})
    return {
        "id": run.id,
        "prediction_run_id": run.prediction_run_no,
        "status": run.status,
        "message": "Prediction was queued for background processing.",
    }


def process_prediction_run(db: Session, run_id: str, *, lease_token: str | None = None) -> dict:
    run = db.get(PredictionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail={"code": "PREDICTION_RUN_NOT_FOUND", "message": "Prediction run was not found."})
    if run.status == "COMPLETED":
        return get_prediction_run(db, run.id)
    if run.status == "FAILED":
        raise HTTPException(
            status_code=409,
            detail={"code": run.error_code or "INFERENCE_FAILED", "message": run.error_message or "Prediction run has failed."},
        )

    run_db_id = run.id
    run_no = run.prediction_run_no
    run_model_id = run.model_id
    run_depot_id = run.depot_id

    total_started = perf_counter()
    run.status = "RUNNING"
    run.error_code = None
    run.error_message = None
    db.commit()
    logger.info(
        "prediction_run_started",
        extra={"prediction_run_id": run_no, "model_id": run_model_id, "depot_id": run_depot_id},
    )
    try:
        model = require_prediction_model(db, run.depot_id, run.model_id)
        evidence = load_model_inference_evidence(db, model)
        run.model_snapshot = {**run.model_snapshot, **{key: evidence[key] for key in ("artifact_checksum", "artifact_source")}}
        planning = build_iterative_capacity_plan(db, run=run, model=model, evidence=evidence)
        run.model_snapshot = {
            **run.model_snapshot,
            "capacity_iteration_order": [32, 24, 16, 8],
            "capacity_iteration_summary": planning["iteration_summary"],
        }
        run.shipment_prediction_duration_ms = planning["durations_ms"]["shipment_prediction"]
        run.mt_prediction_duration_ms = planning["durations_ms"]["mt_prediction"]
        run.assignment_optimization_duration_ms = planning["durations_ms"]["assignment_optimization"]
        _persist_iterative_capacity_plan(db, run, planning)
        run.total_prediction_duration_ms = round((perf_counter() - total_started) * 1000)
        complete_prediction_job(db, run_id=run_db_id, lease_token=lease_token)
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            "iterative_capacity_assignment_completed",
            extra={"prediction_run_id": run_no, "model_id": run_model_id, "depot_id": run_depot_id},
        )
        return get_prediction_run(db, run_db_id)
    except PredictionLeaseLost:
        db.rollback()
        logger.warning("prediction_run_lease_lost", extra={"prediction_run_id": run_no})
        raise
    except HTTPException as exc:
        _mark_run_failed(
            db,
            run_db_id,
            total_started,
            exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)},
            lease_token=lease_token,
        )
        raise
    except Exception as exc:
        _mark_run_failed(
            db,
            run_db_id,
            total_started,
            {"code": "INFERENCE_FAILED", "message": f"{type(exc).__name__}: {exc}"},
            lease_token=lease_token,
        )
        logger.exception(
            "prediction_run_failed",
            extra={"prediction_run_id": run_no, "model_id": run_model_id, "depot_id": run_depot_id},
        )
        raise HTTPException(status_code=500, detail={"code": "INFERENCE_FAILED", "message": "Prediction failed; the run was retained for audit."}) from exc

def create_prediction_run(
    db: Session,
    *,
    depot_id: str,
    model_id: str,
    loading_order_content: bytes,
    loading_order_filename: str,
    availability_content: bytes,
    availability_filename: str,
    parameters: dict | None,
    created_by: str,
) -> dict:
    """Synchronous compatibility wrapper used by internal callers and tests."""
    queued = enqueue_prediction_run(
        db,
        depot_id=depot_id,
        model_id=model_id,
        loading_order_content=loading_order_content,
        loading_order_filename=loading_order_filename,
        availability_content=availability_content,
        availability_filename=availability_filename,
        parameters=parameters,
        created_by=created_by,
    )
    return process_prediction_run(db, queued["id"])


def _mark_run_failed(
    db: Session,
    run_id: str,
    started: float,
    detail: dict,
    *,
    lease_token: str | None = None,
) -> None:
    db.rollback()
    run = db.get(PredictionRun, run_id)
    if run:
        run.status = "FAILED"
        run.error_code = detail.get("code", "INFERENCE_FAILED")
        run.error_message = detail.get("message", "Prediction failed.")
        run.total_prediction_duration_ms = round((perf_counter() - started) * 1000)
        run.completed_at = datetime.now(timezone.utc)
        fail_prediction_job(
            db,
            run_id=run_id,
            lease_token=lease_token,
            message=run.error_message,
        )
        db.commit()


def _candidate_payloads(db: Session, shipment_ids: list[str]) -> dict[str, list[PredictionMTCandidate]]:
    result: dict[str, list[PredictionMTCandidate]] = defaultdict(list)
    if shipment_ids:
        for candidate in db.scalars(select(PredictionMTCandidate).where(PredictionMTCandidate.prediction_shipment_id.in_(shipment_ids))).all():
            result[candidate.prediction_shipment_id].append(candidate)
    return result


def _rolling_assign_and_persist(db: Session, run: PredictionRun, *, initial: bool) -> None:
    """Chronological assignment; vehicle state is updated after each estimated trip."""
    shipments = db.scalars(
        select(PredictionShipment)
        .where(PredictionShipment.prediction_run_id == run.id)
        .order_by(PredictionShipment.planned_start_datetime, PredictionShipment.predicted_shipment_id)
    ).all()
    shipment_ids = [shipment.id for shipment in shipments]
    candidates_by_shipment = _candidate_payloads(db, shipment_ids)
    existing_assignments = {
        row.prediction_shipment_id: row
        for row in (db.scalars(select(PredictionAssignment).where(PredictionAssignment.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else [])
    }
    fixed_manual = {
        shipment_id: row.final_vehicle_id
        for shipment_id, row in existing_assignments.items()
        if row.assignment_status == "MANUAL_OVERRIDE" and row.final_vehicle_id
    }
    db.execute(delete(PredictionTrip).where(PredictionTrip.prediction_run_id == run.id))
    availability = {row["vehicle_id"]: datetime.fromisoformat(row["initial_available_datetime"]) for row in run.input_mt_availability_snapshot}
    trip_numbers = {vehicle_id: 0 for vehicle_id in availability}
    vehicle_ids = list(availability)
    mts = {row.mt_id: row for row in db.scalars(select(MasterMT).where(MasterMT.mt_id.in_(vehicle_ids))).all()} if vehicle_ids else {}
    lines = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else []
    lines_by_shipment: dict[str, list[PredictionShipmentLine]] = defaultdict(list)
    for line in lines:
        lines_by_shipment[line.prediction_shipment_id].append(line)
    spbu_ids = sorted({line.spbu_id for line in lines})
    spbus = {row.spbu_id: row for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()} if spbu_ids else {}
    depot = db.get(MasterDepot, run.depot_id)
    configuration = get_google_routes_configuration(db)
    assert depot is not None and configuration is not None
    metrics: dict[str, int] = {}
    routing = Phase6RouteEstimationService(db, configuration=configuration, model_id=run.model_id, metrics=metrics)
    mode = run.parameter_snapshot["assignment_mode"]
    allowed_delay = int(run.parameter_snapshot["maximum_allowed_delay_minutes"])
    blocking = run.parameter_snapshot.get("blocking_prediction_confidence")
    final_snapshot = []

    # Recalculation after a manual shipment/MT change follows the same capacity
    # priority as the initial iterative planner: 32, then 24, 16, and 8 KL.
    shipments.sort(
        key=lambda shipment: (
            -shipment_capacity(
                [{"order_quantity_kl": line.order_quantity_kl} for line in lines_by_shipment[shipment.id]]
            )["required_compartments"],
            _utc(shipment.planned_start_datetime),
            shipment.predicted_shipment_id,
        )
    )

    for sequence_number, shipment in enumerate(shipments, start=1):
        planned = _utc(shipment.planned_start_datetime)
        required_compartments = shipment_capacity(
            [{"order_quantity_kl": line.order_quantity_kl} for line in lines_by_shipment[shipment.id]]
        )["required_compartments"]
        compatible = [candidate for candidate in candidates_by_shipment[shipment.id] if candidate.compatibility_status == "PASS"]
        compatible.sort(
            key=lambda row: (
                max(
                    0,
                    int(mt_compartment_profile(mts[row.vehicle_id])["effective_compartments"] or 999)
                    - required_compartments,
                ) if row.vehicle_id in mts else 999,
                -row.prediction_score,
                mts[row.vehicle_id].vehicle_registration if row.vehicle_id in mts else row.vehicle_id,
            )
        )
        fixed_vehicle = fixed_manual.get(shipment.id)
        if fixed_vehicle:
            compatible = sorted(compatible, key=lambda row: row.vehicle_id != fixed_vehicle)
        timing_eligible = []
        for candidate in compatible:
            next_available = _utc(availability[candidate.vehicle_id])
            delay_minutes = max(0, round((next_available - planned).total_seconds() / 60))
            if fixed_vehicle == candidate.vehicle_id or next_available <= planned or (mode == "ALLOW_DELAY" and delay_minutes <= allowed_delay):
                timing_eligible.append((candidate, next_available, delay_minutes))

        unassigned_reason = None
        if blocking is not None and shipment.shipment_prediction_score < float(blocking) and not fixed_vehicle:
            timing_eligible = []
            unassigned_reason = "LOW_PREDICTION_CONFIDENCE"
        elif not compatible:
            unassigned_reason = "NO_COMPATIBLE_MT"
        elif not timing_eligible:
            unassigned_reason = "NO_MT_AVAILABLE_AT_REQUIRED_TIME"

        selected = None
        estimate = None
        routing_failure = None
        for candidate, next_available, delay_minutes in timing_eligible:
            if fixed_vehicle and candidate.vehicle_id != fixed_vehicle:
                continue
            departure = max(planned, next_available)
            try:
                estimate = routing.estimate_trip(
                    depot=depot,
                    spbus=[spbus[line.spbu_id] for line in lines_by_shipment[shipment.id]],
                    mt=mts[candidate.vehicle_id],
                    predicted_departure_datetime=departure,
                    max_exact_sequence_stops=int(run.parameter_snapshot["max_exact_sequence_stops"]),
                )
                selected = (candidate, departure, delay_minutes)
                break
            except GoogleRoutesError as exc:
                routing_failure = exc.code
        if not selected and timing_eligible:
            unassigned_reason = routing_failure or "ROUTING_ESTIMATE_FAILED"

        assignment = existing_assignments.get(shipment.id)
        if not assignment:
            assignment = PredictionAssignment(id=uuid.uuid4().hex, prediction_shipment_id=shipment.id)
            db.add(assignment)
            existing_assignments[shipment.id] = assignment
        if selected and estimate:
            candidate, departure, delay_minutes = selected
            is_manual = fixed_vehicle == candidate.vehicle_id
            status = "MANUAL_OVERRIDE" if is_manual else "ASSIGNED_WITH_DELAY" if delay_minutes > 0 else "ASSIGNED"
            if initial:
                assignment.original_vehicle_id = candidate.vehicle_id
                assignment.original_assignment_score = candidate.prediction_score
            assignment.final_vehicle_id = candidate.vehicle_id
            assignment.final_assignment_score = candidate.prediction_score
            assignment.assignment_status = status
            assignment.unassigned_reason = None
            trip_numbers[candidate.vehicle_id] += 1
            availability[candidate.vehicle_id] = estimate["next_available_datetime"]
            trip = PredictionTrip(
                id=uuid.uuid4().hex,
                prediction_run_id=run.id,
                prediction_shipment_id=shipment.id,
                trip_id=f"TRIP-{sequence_number:04d}",
                trip_number=trip_numbers[candidate.vehicle_id],
                vehicle_id=candidate.vehicle_id,
                planned_start_datetime=planned,
                predicted_departure_datetime=departure,
                delay_minutes=delay_minutes,
                estimated_visit_sequence=estimate["estimated_visit_sequence_codes"],
                routing_provider=estimate["routing_provider"],
                routing_mode=estimate["routing_mode"],
                routing_preference=estimate["routing_preference"],
                large_vehicle_used=estimate["large_vehicle_used"],
                route_distance_meters=estimate["route_distance_meters"],
                route_duration_seconds=estimate["route_duration_seconds"],
                static_duration_seconds=estimate["static_duration_seconds"],
                service_duration_seconds=estimate["service_duration_seconds"],
                turnaround_buffer_seconds=estimate["turnaround_buffer_seconds"],
                total_cycle_duration_seconds=estimate["total_cycle_duration_seconds"],
                estimated_return_datetime=estimate["estimated_return_datetime"],
                next_available_datetime=estimate["next_available_datetime"],
                routing_confidence=estimate["routing_confidence"],
                route_estimation_source=estimate["route_estimation_source"],
                route_geometry=estimate["route_geometry"],
                route_geometry_source=estimate["route_geometry_source"],
                service_time_source=estimate["service_time_source"],
                assignment_status=status,
                fallback_used=estimate["fallback_used"],
                warning_codes=estimate["warning_codes"],
                vehicle_profile_snapshot=estimate["vehicle_profile_snapshot"],
            )
        else:
            if initial:
                assignment.original_vehicle_id = None
                assignment.original_assignment_score = None
            assignment.final_vehicle_id = None
            assignment.final_assignment_score = None
            assignment.assignment_status = "UNASSIGNED"
            assignment.unassigned_reason = unassigned_reason or "NO_MT_AVAILABLE_AT_REQUIRED_TIME"
            trip = PredictionTrip(
                id=uuid.uuid4().hex,
                prediction_run_id=run.id,
                prediction_shipment_id=shipment.id,
                trip_id=f"TRIP-{sequence_number:04d}",
                planned_start_datetime=planned,
                delay_minutes=0,
                assignment_status="UNASSIGNED",
                unassigned_reason=assignment.unassigned_reason,
                warning_codes=[assignment.unassigned_reason],
            )
        db.add(trip)
        final_snapshot.append(
            {
                "trip_id": trip.trip_id,
                "predicted_shipment_id": shipment.predicted_shipment_id,
                "vehicle_id": trip.vehicle_id,
                "planned_start_datetime": _iso(planned),
                "predicted_departure_datetime": _iso(trip.predicted_departure_datetime),
                "estimated_return_datetime": _iso(trip.estimated_return_datetime),
                "next_available_datetime": _iso(trip.next_available_datetime),
                "predicted_visit_sequence": trip.estimated_visit_sequence,
                "shipment_score": shipment.shipment_prediction_score,
                "vehicle_score": assignment.final_assignment_score,
                "assignment_status": trip.assignment_status,
                "route_estimation_source": trip.route_estimation_source,
            }
        )
    db.flush()
    if initial:
        by_external = {shipment.id: shipment.predicted_shipment_id for shipment in shipments}
        original_assignments = {
            shipment_id: assignment for shipment_id, assignment in existing_assignments.items()
        }
        run.original_prediction_snapshot = [
            {
                **item,
                "assigned_vehicle_id": original_assignments[next(key for key, value in by_external.items() if value == item["predicted_shipment_id"])].original_vehicle_id,
                "assignment_score": original_assignments[next(key for key, value in by_external.items() if value == item["predicted_shipment_id"])].original_assignment_score,
            }
            for item in run.original_prediction_snapshot
        ]
    run.final_prediction_snapshot = final_snapshot
    run.routing_metrics_snapshot = metrics


def list_prediction_runs(db: Session, depot_id: str | None = None) -> list[dict]:
    statement = select(PredictionRun)
    if depot_id:
        statement = statement.where(PredictionRun.depot_id == depot_id)
    return [_run_history_row(db, run) for run in db.scalars(statement.order_by(desc(PredictionRun.created_at))).all()]


def get_prediction_run_status(db: Session, run_id: str) -> dict:
    run = db.get(PredictionRun, run_id) or db.scalar(select(PredictionRun).where(PredictionRun.prediction_run_no == run_id))
    if not run:
        raise HTTPException(status_code=404, detail={"code": "PREDICTION_RUN_NOT_FOUND", "message": "Prediction run was not found."})
    job = prediction_job_payload(db, run.id)
    return {
        "id": run.id,
        "prediction_run_id": run.prediction_run_no,
        "status": run.status,
        "created_at": _iso(run.created_at),
        "completed_at": _iso(run.completed_at),
        "error_code": run.error_code,
        "error_message": run.error_message,
        "queue": {
            **job,
            "heartbeat_at": _iso(job["heartbeat_at"]),
            "lease_expires_at": _iso(job["lease_expires_at"]),
        },
        "durations_ms": {
            "validation": run.validation_duration_ms,
            "shipment_prediction": run.shipment_prediction_duration_ms,
            "mt_prediction": run.mt_prediction_duration_ms,
            "assignment_optimization": run.assignment_optimization_duration_ms,
            "total": run.total_prediction_duration_ms,
        },
    }


def _run_history_row(db: Session, run: PredictionRun) -> dict:
    shipments = db.scalars(select(PredictionShipment).where(PredictionShipment.prediction_run_id == run.id)).all()
    trips = db.scalars(
        select(PredictionTrip)
        .options(defer(PredictionTrip.route_geometry))
        .where(PredictionTrip.prediction_run_id == run.id)
    ).all()
    depot = db.get(MasterDepot, run.depot_id)
    job = prediction_job_payload(db, run.id)
    return {
        "id": run.id,
        "prediction_run_id": run.prediction_run_no,
        "date": _iso(run.created_at),
        "depot_id": run.depot_id,
        "depot": depot.depot_name if depot else run.depot_id,
        "model_id": run.model_id,
        "model": run.model_snapshot.get("model_name") or run.model_id,
        "loading_orders": len(run.input_loading_order_snapshot),
        "shipments": len(shipments),
        "trips": len(trips),
        "assigned": sum(trip.vehicle_id is not None for trip in trips),
        "unassigned": sum(trip.vehicle_id is None for trip in trips),
        "user": run.created_by,
        "status": run.status,
        "attempt_count": job["attempt_count"],
        "max_attempts": job["max_attempts"],
        "heartbeat_at": _iso(job["heartbeat_at"]),
        "queue_error": job["last_error"],
    }


def get_prediction_run(
    db: Session,
    run_id: str,
    *,
    shipment_page: int = 1,
    shipment_page_size: int = 25,
    shift_id: str | None = None,
    include_candidates: bool = True,
    route_vehicle_id: str | None = None,
    include_route_geometry: bool = False,
) -> dict:
    run = db.get(PredictionRun, run_id) or db.scalar(select(PredictionRun).where(PredictionRun.prediction_run_no == run_id))
    if not run:
        raise HTTPException(status_code=404, detail={"code": "PREDICTION_RUN_NOT_FOUND", "message": "Prediction run was not found."})
    depot = db.get(MasterDepot, run.depot_id)
    shipments = db.scalars(
        select(PredictionShipment).where(PredictionShipment.prediction_run_id == run.id).order_by(PredictionShipment.planned_start_datetime, PredictionShipment.predicted_shipment_id)
    ).all()
    shipment_page = max(1, shipment_page)
    shipment_page_size = min(100, max(1, shipment_page_size))
    filtered_shipments = [shipment for shipment in shipments if not shift_id or shipment.shift_id == shift_id]
    shipment_total = len(filtered_shipments)
    shipment_total_pages = max(1, math.ceil(shipment_total / shipment_page_size))
    shipment_page = min(shipment_page, shipment_total_pages)
    shipment_offset = (shipment_page - 1) * shipment_page_size
    page_shipments = filtered_shipments[shipment_offset:shipment_offset + shipment_page_size]
    page_shipment_ids = {shipment.id for shipment in page_shipments}
    shipment_ids = [shipment.id for shipment in shipments]
    lines = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else []
    candidates = db.scalars(
        select(PredictionMTCandidate).where(PredictionMTCandidate.prediction_shipment_id.in_(page_shipment_ids))
    ).all() if include_candidates and page_shipment_ids else []
    assignments = db.scalars(select(PredictionAssignment).where(PredictionAssignment.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else []
    trip_statement = (
        select(PredictionTrip)
        .options(defer(PredictionTrip.route_geometry))
        .where(PredictionTrip.prediction_run_id == run.id)
        .order_by(PredictionTrip.planned_start_datetime, PredictionTrip.trip_id)
    )
    trips = db.scalars(trip_statement).all()
    if include_route_geometry and route_vehicle_id:
        db.scalars(
            select(PredictionTrip)
            .where(PredictionTrip.prediction_run_id == run.id, PredictionTrip.vehicle_id == route_vehicle_id)
            .execution_options(populate_existing=True)
        ).all()
    lines_by: dict[str, list[PredictionShipmentLine]] = defaultdict(list)
    candidates_by: dict[str, list[PredictionMTCandidate]] = defaultdict(list)
    for line in lines:
        lines_by[line.prediction_shipment_id].append(line)
    for candidate in candidates:
        candidates_by[candidate.prediction_shipment_id].append(candidate)
    assignments_by = {assignment.prediction_shipment_id: assignment for assignment in assignments}
    trips_by = {trip.prediction_shipment_id: trip for trip in trips}
    mt_ids = {candidate.vehicle_id for candidate in candidates} | {trip.vehicle_id for trip in trips if trip.vehicle_id}
    mts = {row.mt_id: row for row in db.scalars(select(MasterMT).where(MasterMT.mt_id.in_(mt_ids))).all()} if mt_ids else {}
    spbu_ids = {line.spbu_id for line in lines}
    spbus = {row.spbu_id: row for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()} if spbu_ids else {}
    cluster_assignments = {
        row.spbu_id: row
        for row in (
            db.scalars(
                select(MLSPBUClusterAssignment).where(
                    MLSPBUClusterAssignment.model_id == run.model_id,
                    MLSPBUClusterAssignment.spbu_id.in_(spbu_ids),
                )
            ).all()
            if spbu_ids
            else []
        )
    }
    output_shipments = []
    output_trips = []
    for shipment in shipments:
        assignment = assignments_by.get(shipment.id)
        trip = trips_by.get(shipment.id)
        shipment_lines = sorted(lines_by[shipment.id], key=lambda line: (_iso(line.shipment_start_datetime) or "", line.loading_order_no))
        shipment_candidates = sorted(candidates_by[shipment.id], key=lambda row: (row.compatibility_status != "PASS", row.candidate_rank or 999999, -row.prediction_score))
        assigned_mt = mts.get(assignment.final_vehicle_id) if assignment and assignment.final_vehicle_id else None
        assigned_mt_profile = mt_compartment_profile(assigned_mt) if assigned_mt else None
        assignment_payload = {
            "id": assignment.id if assignment else None,
            "original_vehicle_id": assignment.original_vehicle_id if assignment else None,
            "original_prediction_score": assignment.original_assignment_score if assignment else None,
            "assigned_vehicle_id": assignment.final_vehicle_id if assignment else None,
            "assigned_vehicle_registration": (mts[assignment.final_vehicle_id].vehicle_registration or assignment.final_vehicle_id) if assignment and assignment.final_vehicle_id in mts else None,
            "assigned_vehicle_capacity_kl": assigned_mt_profile["capacity_kl"] if assigned_mt_profile else None,
            "assigned_vehicle_compartments": assigned_mt_profile["effective_compartments"] if assigned_mt_profile else None,
            "mt_assignment_score": assignment.final_assignment_score if assignment else None,
            "assignment_status": assignment.assignment_status if assignment else "UNASSIGNED",
            "unassigned_reason": assignment.unassigned_reason if assignment else "NO_MT_AVAILABLE_AT_REQUIRED_TIME",
            "override_reason": assignment.override_reason if assignment else None,
            "override_user": assignment.override_user if assignment else None,
            "override_timestamp": _iso(assignment.override_timestamp) if assignment else None,
        }
        line_payloads = [
            {
                "id": line.id,
                "loading_order_no": line.loading_order_no,
                "shipment_start_datetime": _iso(line.shipment_start_datetime),
                "spbu_id": line.spbu_id,
                "spbu_no": line.spbu_no,
                "spbu_name": spbus[line.spbu_id].spbu_name if line.spbu_id in spbus else None,
                "product_id": line.product_id,
                "product_name": line.product_name,
                "cluster_id": cluster_assignments[line.spbu_id].cluster_id if line.spbu_id in cluster_assignments else None,
                "cluster_number": (
                    int(cluster_assignments[line.spbu_id].cluster_id) + 1
                    if line.spbu_id in cluster_assignments and cluster_assignments[line.spbu_id].cluster_id is not None
                    else None
                ),
                "cluster_label": cluster_assignments[line.spbu_id].cluster_label if line.spbu_id in cluster_assignments else None,
                "order_quantity_kl": line.order_quantity_kl,
                "model_predicted_shipment_id": line.model_predicted_shipment_id,
            }
            for line in shipment_lines
        ]
        shipment_load = shipment_capacity(line_payloads)
        candidate_payloads = [
            {
                "id": candidate.id,
                "vehicle_id": candidate.vehicle_id,
                "vehicle_registration_no": (mts[candidate.vehicle_id].vehicle_registration or candidate.vehicle_id) if candidate.vehicle_id in mts else candidate.vehicle_id,
                "prediction_score": candidate.prediction_score,
                "compatibility_status": candidate.compatibility_status,
                "candidate_rank": candidate.candidate_rank,
                "exclusion_reason": candidate.exclusion_reason,
                "explanation": candidate.explanation,
                "capacity_kl": mt_compartment_profile(mts[candidate.vehicle_id])["capacity_kl"] if candidate.vehicle_id in mts else None,
                "number_of_compartments": mt_compartment_profile(mts[candidate.vehicle_id])["effective_compartments"] if candidate.vehicle_id in mts else None,
            }
            for candidate in shipment_candidates
        ]
        include_trip_geometry = bool(
            include_route_geometry
            and trip
            and (route_vehicle_id is None or trip.vehicle_id == route_vehicle_id)
        )
        trip_payload = _trip_payload(
            trip,
            shipment,
            assignment_payload,
            mts,
            include_route_geometry=include_trip_geometry,
        ) if trip else None
        output_shipments.append(
            {
                "id": shipment.id,
                "predicted_shipment_id": shipment.predicted_shipment_id,
                "planned_start_datetime": _iso(shipment.planned_start_datetime),
                "shift_id": shipment.shift_id,
                "shift": shipment.shift_name,
                "shipment_prediction_score": shipment.shipment_prediction_score,
                "shipment_confidence_level": shipment.confidence_level,
                "low_confidence": shipment.low_confidence,
                "is_manual_override": shipment.is_manual_override,
                "explanation": shipment.explanation,
                "total_order_kl": shipment_load["total_order_kl"],
                "required_compartments": shipment_load["required_compartments"],
                "compartment_unit_kl": shipment_load["compartment_unit_kl"],
                "lines": line_payloads,
                "assignment": assignment_payload,
                "trip": trip_payload,
                "candidates": candidate_payloads,
                "candidates_loaded": include_candidates and shipment.id in page_shipment_ids,
            }
        )
        if trip_payload:
            output_trips.append({**trip_payload, "lines": line_payloads, "candidates": candidate_payloads})

    assigned_trips = [trip for trip in output_trips if trip["vehicle_id"]]
    assigned_shipments = [item for item in output_shipments if item["assignment"]["assigned_vehicle_id"]]
    hourly_distribution = _hourly_distribution(assigned_shipments, depot)
    geographic_shipments = [
        shipment for shipment in assigned_shipments
        if route_vehicle_id is None or (shipment.get("trip") or {}).get("vehicle_id") == route_vehicle_id
    ]
    geographic_routes = _geographic_routes(
        geographic_shipments,
        depot,
        spbus,
        include_road_geometry=include_route_geometry,
    )
    mt_scores = [trip["mt_assignment_score"] for trip in assigned_trips if trip["mt_assignment_score"] is not None]
    summary_by_shift = []
    for summary_shift_id in sorted({item["shift_id"] for item in output_shipments}):
        rows = [item for item in output_shipments if item["shift_id"] == summary_shift_id]
        summary_by_shift.append(
            {
                "shift_id": summary_shift_id,
                "shift": rows[0]["shift"],
                "loading_orders": sum(len(item["lines"]) for item in rows),
                "total_order_kl": round(sum(line["order_quantity_kl"] or 0 for item in rows for line in item["lines"]), 3),
                "unique_spbu": len({line["spbu_id"] for item in rows for line in item["lines"]}),
                "predicted_shipments": len(rows),
                "assigned": sum(item["assignment"]["assigned_vehicle_id"] is not None for item in rows),
                "unassigned": sum(item["assignment"]["assigned_vehicle_id"] is None for item in rows),
            }
        )
    timeline: dict[str, list[dict]] = defaultdict(list)
    for trip in assigned_trips:
        timeline[trip["vehicle_id"]].append(
            {
                "trip_id": trip["trip_id"],
                "trip_number": trip["trip_number"],
                "shipment_id": trip["predicted_shipment_id"],
                "start": trip["predicted_departure_datetime"],
                "return": trip["estimated_return_datetime"],
                "next_available": trip["next_available_datetime"],
                "status": trip["assignment_status"],
            }
        )
    return {
        "id": run.id,
        "prediction_run_id": run.prediction_run_no,
        "status": run.status,
        "depot_id": run.depot_id,
        "depot": depot.depot_name if depot else run.depot_id,
        "model_id": run.model_id,
        "model": run.model_snapshot,
        "created_by": run.created_by,
        "created_at": _iso(run.created_at),
        "completed_at": _iso(run.completed_at),
        "error_code": run.error_code,
        "error_message": run.error_message,
        "parameters": run.parameter_snapshot,
        "routing_configuration": run.routing_configuration_snapshot,
        "routing_metrics": run.routing_metrics_snapshot,
        "validation": run.validation_snapshot,
        "durations_ms": {
            "validation": run.validation_duration_ms,
            "shipment_prediction": run.shipment_prediction_duration_ms,
            "mt_prediction": run.mt_prediction_duration_ms,
            "assignment_optimization": run.assignment_optimization_duration_ms,
            "total": run.total_prediction_duration_ms,
        },
        "summary": {
            "loading_orders": len(run.input_loading_order_snapshot),
            "total_order_kl": round(sum(row.get("order_quantity_kl") or 0 for row in run.input_loading_order_snapshot), 3),
            "unique_spbu": len({row["spbu_id"] for row in run.input_loading_order_snapshot}),
            "predicted_shipments": len(output_shipments),
            "total_trips": len(output_trips),
            "available_mt": len(run.input_mt_availability_snapshot),
            "assigned_shipments": len(assigned_trips),
            "assigned_loading_orders": sum(len(item["lines"]) for item in assigned_shipments),
            "assigned_order_kl": round(
                sum(line["order_quantity_kl"] or 0 for item in assigned_shipments for line in item["lines"]),
                3,
            ),
            "assigned_with_delay": sum(trip["assignment_status"] == "ASSIGNED_WITH_DELAY" for trip in output_trips),
            "unassigned_shipments": len(output_trips) - len(assigned_trips),
            "multi_trip_mt": sum(1 for rows in timeline.values() if len(rows) > 1),
            "fallback_trips": sum(bool(trip["fallback_used"]) for trip in assigned_trips),
            "average_shipment_confidence": round(sum(item["shipment_prediction_score"] for item in output_shipments) / len(output_shipments), 6) if output_shipments else 0,
            "average_mt_assignment_confidence": round(sum(mt_scores) / len(mt_scores), 6) if mt_scores else 0,
        },
        "summary_by_shift": summary_by_shift,
        "shipment_pagination": {
            "page": shipment_page,
            "page_size": shipment_page_size,
            "total": shipment_total,
            "total_pages": shipment_total_pages,
            "shift_id": shift_id,
        },
        "shipment_options": [
            {
                "id": shipment.id,
                "predicted_shipment_id": shipment.predicted_shipment_id,
                "shift_id": shipment.shift_id,
                "shift": shipment.shift_name,
                "spbus": list(
                    {
                        line.spbu_id: {
                            "spbu_id": line.spbu_id,
                            "spbu_no": line.spbu_no,
                            "cluster_id": cluster_assignments[line.spbu_id].cluster_id if line.spbu_id in cluster_assignments else None,
                            "cluster_number": (
                                int(cluster_assignments[line.spbu_id].cluster_id) + 1
                                if line.spbu_id in cluster_assignments and cluster_assignments[line.spbu_id].cluster_id is not None
                                else None
                            ),
                            "cluster_label": cluster_assignments[line.spbu_id].cluster_label if line.spbu_id in cluster_assignments else None,
                        }
                        for line in sorted(lines_by[shipment.id], key=lambda row: (row.spbu_no, row.loading_order_no))
                    }.values()
                ),
            }
            for shipment in shipments
        ],
        "shipments": [shipment for shipment in output_shipments if shipment["id"] in page_shipment_ids],
        "trips": output_trips,
        "hourly_distribution": hourly_distribution,
        "geographic_routes": geographic_routes,
        "mt_timeline": [
            {
                "vehicle_id": vehicle_id,
                "vehicle_registration_no": mts[vehicle_id].vehicle_registration or vehicle_id if vehicle_id in mts else vehicle_id,
                "trips": rows,
            }
            for vehicle_id, rows in sorted(timeline.items(), key=lambda item: (mts[item[0]].vehicle_registration if item[0] in mts else item[0]))
        ],
        "phase7_input": run.final_prediction_snapshot,
        "original_model_prediction": run.original_prediction_snapshot,
        "final_dispatch_prediction": run.final_prediction_snapshot,
    }


def _trip_payload(
    trip: PredictionTrip,
    shipment: PredictionShipment,
    assignment: dict,
    mts: dict[str, MasterMT],
    *,
    include_route_geometry: bool = False,
) -> dict:
    payload = {
        "id": trip.id,
        "trip_id": trip.trip_id,
        "trip_number": trip.trip_number,
        "predicted_shipment_id": shipment.predicted_shipment_id,
        "vehicle_id": trip.vehicle_id,
        "vehicle_registration_no": (mts[trip.vehicle_id].vehicle_registration or trip.vehicle_id) if trip.vehicle_id in mts else None,
        "planned_start_datetime": _iso(trip.planned_start_datetime),
        "predicted_departure_datetime": _iso(trip.predicted_departure_datetime),
        "delay_minutes": trip.delay_minutes,
        "estimated_visit_sequence": trip.estimated_visit_sequence,
        "routing_provider": trip.routing_provider,
        "routing_mode": trip.routing_mode,
        "routing_preference": trip.routing_preference,
        "large_vehicle_used": trip.large_vehicle_used,
        "route_distance_meters": trip.route_distance_meters,
        "route_duration_seconds": trip.route_duration_seconds,
        "static_duration_seconds": trip.static_duration_seconds,
        "service_duration_seconds": trip.service_duration_seconds,
        "service_time_source": trip.service_time_source,
        "turnaround_buffer_seconds": trip.turnaround_buffer_seconds,
        "total_cycle_duration_seconds": trip.total_cycle_duration_seconds,
        "estimated_return_datetime": _iso(trip.estimated_return_datetime),
        "next_available_datetime": _iso(trip.next_available_datetime),
        "shipment_prediction_score": shipment.shipment_prediction_score,
        "mt_assignment_score": assignment["mt_assignment_score"],
        "routing_confidence": trip.routing_confidence,
        "route_estimation_source": trip.route_estimation_source,
        "assignment_status": trip.assignment_status,
        "unassigned_reason": trip.unassigned_reason,
        "fallback_used": trip.fallback_used,
        "warning_codes": trip.warning_codes,
        "vehicle_profile_snapshot": trip.vehicle_profile_snapshot,
    }
    if include_route_geometry:
        payload["route_geometry"] = trip.route_geometry
        payload["route_geometry_source"] = trip.route_geometry_source
    return payload


def get_prediction_shipment_candidates(db: Session, run_id: str, shipment_id: str) -> dict:
    run = db.get(PredictionRun, run_id) or db.scalar(
        select(PredictionRun).where(PredictionRun.prediction_run_no == run_id)
    )
    shipment = db.get(PredictionShipment, shipment_id)
    if not run or not shipment or shipment.prediction_run_id != run.id:
        raise HTTPException(
            status_code=404,
            detail={"code": "PREDICTION_SHIPMENT_NOT_FOUND", "message": "Prediction shipment was not found."},
        )
    candidates = db.scalars(
        select(PredictionMTCandidate)
        .where(PredictionMTCandidate.prediction_shipment_id == shipment.id)
        .order_by(
            PredictionMTCandidate.compatibility_status.desc(),
            PredictionMTCandidate.candidate_rank,
            PredictionMTCandidate.prediction_score.desc(),
        )
    ).all()
    mt_ids = {candidate.vehicle_id for candidate in candidates}
    mts = {
        row.mt_id: row
        for row in db.scalars(select(MasterMT).where(MasterMT.mt_id.in_(mt_ids))).all()
    } if mt_ids else {}
    # Older runs did not save per-SPBU rule evidence. Keep their saved verdict
    # intact and attach a separately labelled evaluation of today's master data.
    spbu_ids = set(db.scalars(select(PredictionShipmentLine.spbu_id).where(PredictionShipmentLine.prediction_shipment_id == shipment.id)).all())
    spbus = {row.spbu_id: row for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()} if spbu_ids else {}
    mt_tags: dict[str, set[str]] = defaultdict(set)
    spbu_tags: dict[str, set[str]] = defaultdict(set)
    for entity_id, tag_id in db.execute(select(BridgeMTTag.mt_id, BridgeMTTag.tag_id).where(BridgeMTTag.mt_id.in_(mt_ids))).all() if mt_ids else []:
        mt_tags[entity_id].add(tag_id)
    for entity_id, tag_id in db.execute(select(BridgeSPBUTag.spbu_id, BridgeSPBUTag.tag_id).where(BridgeSPBUTag.spbu_id.in_(spbu_ids))).all() if spbu_ids else []:
        spbu_tags[entity_id].add(tag_id)
    tag_ids = set().union(*mt_tags.values(), *spbu_tags.values())
    tag_labels = {row.tag_id: row.tag_value for row in db.scalars(select(MasterTag).where(MasterTag.tag_id.in_(tag_ids))).all()} if tag_ids else {}
    payload = []
    for candidate in candidates:
        profile = mt_compartment_profile(mts[candidate.vehicle_id]) if candidate.vehicle_id in mts else None
        explanation = dict(candidate.explanation or {})
        if "master_checks" not in explanation:
            explanation["current_master_checks"] = [
                {
                    "spbu_id": spbu_id,
                    "spbu_code": spbus[spbu_id].spbu_code if spbu_id in spbus else spbu_id,
                    **evaluate_compatibility_entities(
                        mts.get(candidate.vehicle_id), spbus.get(spbu_id),
                        mt_tag_ids=mt_tags[candidate.vehicle_id], spbu_tag_ids=spbu_tags[spbu_id],
                        tag_labels=tag_labels,
                        vehicle_mode=(run.parameter_snapshot or {}).get("vehicle_compatibility_mode", PHASE6_VEHICLE_COMPATIBILITY_MODE),
                    ),
                }
                for spbu_id in sorted(spbu_ids)
            ]
        payload.append(
            {
                "id": candidate.id,
                "vehicle_id": candidate.vehicle_id,
                "vehicle_registration_no": (
                    mts[candidate.vehicle_id].vehicle_registration or candidate.vehicle_id
                ) if candidate.vehicle_id in mts else candidate.vehicle_id,
                "prediction_score": candidate.prediction_score,
                "compatibility_status": candidate.compatibility_status,
                "candidate_rank": candidate.candidate_rank,
                "exclusion_reason": candidate.exclusion_reason,
                "explanation": explanation,
                "capacity_kl": profile["capacity_kl"] if profile else None,
                "number_of_compartments": profile["effective_compartments"] if profile else None,
            }
        )
    return {
        "shipment_id": shipment.id,
        "predicted_shipment_id": shipment.predicted_shipment_id,
        "candidates": payload,
    }


def refresh_prediction_route_geometry(db: Session, run_id: str, vehicle_id: str) -> dict:
    """Backfill road-following Google geometry for one MT without rerunning assignment."""
    run = db.get(PredictionRun, run_id) or db.scalar(select(PredictionRun).where(PredictionRun.prediction_run_no == run_id))
    if not run:
        raise HTTPException(status_code=404, detail={"code": "PREDICTION_RUN_NOT_FOUND", "message": "Prediction run was not found."})
    trips = db.scalars(
        select(PredictionTrip)
        .where(PredictionTrip.prediction_run_id == run.id, PredictionTrip.vehicle_id == vehicle_id)
        .order_by(PredictionTrip.predicted_departure_datetime, PredictionTrip.trip_id)
    ).all()
    if not trips:
        raise HTTPException(status_code=404, detail={"code": "MT_ROUTE_NOT_FOUND", "message": "No assigned trip was found for this MT."})
    configuration = get_google_routes_configuration(db)
    if not configuration or not configuration.encrypted_api_key:
        raise HTTPException(
            status_code=409,
            detail={"code": "GOOGLE_ROUTES_NOT_CONFIGURED", "message": "Configure and test a Google Routes API key before loading road geometry."},
        )
    depot = db.get(MasterDepot, run.depot_id)
    mt = db.get(MasterMT, vehicle_id)
    if not depot or not mt:
        raise HTTPException(status_code=409, detail={"code": "ROUTE_MASTER_DATA_MISSING", "message": "Depot or MT master data is missing."})
    shipment_ids = [trip.prediction_shipment_id for trip in trips]
    lines = db.scalars(
        select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id.in_(shipment_ids))
    ).all()
    lines_by_shipment: dict[str, list[PredictionShipmentLine]] = defaultdict(list)
    for line in lines:
        lines_by_shipment[line.prediction_shipment_id].append(line)
    spbu_ids = {line.spbu_id for line in lines}
    spbus = {
        row.spbu_id: row
        for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()
    }
    routing = Phase6RouteEstimationService(db, configuration=configuration, model_id=run.model_id)
    if routing.client is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "GOOGLE_ROUTES_KEY_UNAVAILABLE", "message": "The stored Google Routes API key could not be used."},
        )
    refreshed_trip_count = 0
    road_geometry_trip_count = 0
    for trip in trips:
        shipment_spbus = [
            spbus[line.spbu_id]
            for line in lines_by_shipment[trip.prediction_shipment_id]
            if line.spbu_id in spbus
        ]
        if not shipment_spbus or not trip.predicted_departure_datetime:
            continue
        estimate = routing.estimate_trip(
            depot=depot,
            spbus=shipment_spbus,
            mt=mt,
            predicted_departure_datetime=trip.predicted_departure_datetime,
            max_exact_sequence_stops=int(run.parameter_snapshot.get("max_exact_sequence_stops", 4)),
            require_road_geometry=True,
        )
        trip.estimated_visit_sequence = estimate["estimated_visit_sequence_codes"]
        trip.route_geometry = estimate["route_geometry"]
        trip.route_geometry_source = estimate["route_geometry_source"]
        refreshed_trip_count += 1
        road_geometry_trip_count += estimate["route_geometry_source"] == "GOOGLE_ROUTES_GEOJSON"
    db.commit()
    payload = get_prediction_run(
        db,
        run.id,
        include_candidates=False,
        route_vehicle_id=vehicle_id,
        include_route_geometry=True,
    )
    return {
        "geographic_routes": payload["geographic_routes"],
        "refreshed_trip_count": refreshed_trip_count,
        "road_geometry_trip_count": road_geometry_trip_count,
    }


def override_assignment(db: Session, run_id: str, assignment_id: str, vehicle_id: str, reason: str | None, user_id: str) -> dict:
    run = db.get(PredictionRun, run_id)
    assignment = db.get(PredictionAssignment, assignment_id)
    if not run or not assignment:
        raise HTTPException(status_code=404, detail={"code": "ASSIGNMENT_NOT_FOUND", "message": "Prediction assignment was not found."})
    shipment = db.get(PredictionShipment, assignment.prediction_shipment_id)
    if not shipment or shipment.prediction_run_id != run.id:
        raise HTTPException(status_code=404, detail={"code": "ASSIGNMENT_NOT_FOUND", "message": "Assignment does not belong to this prediction run."})
    candidate = db.scalar(
        select(PredictionMTCandidate).where(
            PredictionMTCandidate.prediction_shipment_id == shipment.id,
            PredictionMTCandidate.vehicle_id == vehicle_id,
            PredictionMTCandidate.compatibility_status == "PASS",
        )
    )
    if not candidate:
        raise HTTPException(status_code=409, detail={"code": "MASTER_COMPATIBILITY_FAIL", "message": "Override MT is not compatible with every SPBU in the shipment."})
    assignment.final_vehicle_id = vehicle_id
    assignment.final_assignment_score = candidate.prediction_score
    assignment.assignment_status = "MANUAL_OVERRIDE"
    assignment.unassigned_reason = None
    assignment.override_reason = (reason or "").strip() or None
    assignment.override_user = user_id
    assignment.override_timestamp = datetime.now(timezone.utc)
    shipment.is_manual_override = True
    db.flush()
    _rolling_assign_and_persist(db, run, initial=False)
    db.commit()
    logger.info("manual_override_applied", extra={"prediction_run_id": run.prediction_run_no, "model_id": run.model_id, "depot_id": run.depot_id})
    return get_prediction_run(db, run.id, include_candidates=False)


def override_trip_assignment(db: Session, run_id: str, trip_id: str, vehicle_id: str, reason: str | None, user_id: str) -> dict:
    trip = db.get(PredictionTrip, trip_id) or db.scalar(
        select(PredictionTrip).where(PredictionTrip.prediction_run_id == run_id, PredictionTrip.trip_id == trip_id)
    )
    if not trip or trip.prediction_run_id != run_id:
        raise HTTPException(status_code=404, detail={"code": "TRIP_NOT_FOUND", "message": "Prediction trip was not found."})
    assignment = db.scalar(select(PredictionAssignment).where(PredictionAssignment.prediction_shipment_id == trip.prediction_shipment_id))
    if not assignment:
        raise HTTPException(status_code=404, detail={"code": "ASSIGNMENT_NOT_FOUND", "message": "Trip assignment was not found."})
    return override_assignment(db, run_id, assignment.id, vehicle_id, reason, user_id)


def _rebuild_candidates_and_timeline(db: Session, run: PredictionRun) -> None:
    shipments = db.scalars(select(PredictionShipment).where(PredictionShipment.prediction_run_id == run.id)).all()
    shipment_ids = [shipment.id for shipment in shipments]
    lines = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else []
    lines_by: dict[str, list[PredictionShipmentLine]] = defaultdict(list)
    for line in lines:
        lines_by[line.prediction_shipment_id].append(line)
    payload = [
        {
            "predicted_shipment_id": shipment.predicted_shipment_id,
            "shift_id": shipment.shift_id,
            "shift": shipment.shift_name,
            "planned_start_datetime": shipment.planned_start_datetime,
            "score": shipment.shipment_prediction_score,
            "lines": [
                {
                    "loading_order_no": line.loading_order_no,
                    "spbu_id": line.spbu_id,
                    "spbu_no": line.spbu_no,
                    "product_id": line.product_id,
                    "product_name": line.product_name,
                    "shipment_start_datetime": _iso(line.shipment_start_datetime),
                    "shift_id": shipment.shift_id,
                    "shift": shipment.shift_name,
                    "order_quantity_kl": line.order_quantity_kl,
                }
                for line in lines_by[shipment.id]
            ],
        }
        for shipment in shipments
    ]
    candidate_map = predict_mt_candidates(
        db,
        depot_id=run.depot_id,
        shipments=payload,
        availability=run.input_mt_availability_snapshot,
        vehicle_compatibility_mode=run.parameter_snapshot.get(
            "vehicle_compatibility_mode",
            PHASE6_VEHICLE_COMPATIBILITY_MODE,
        ),
        require_full_utilization=True,
    )
    if shipment_ids:
        db.execute(delete(PredictionMTCandidate).where(PredictionMTCandidate.prediction_shipment_id.in_(shipment_ids)))
    _persist_candidates(db, {shipment.predicted_shipment_id: shipment for shipment in shipments}, candidate_map)
    db.flush()
    _rolling_assign_and_persist(db, run, initial=False)


def adjust_shipment(
    db: Session,
    run_id: str,
    shipment_id: str,
    *,
    action: str,
    line_ids: list[str],
    target_shipment_id: str | None,
    user_id: str,
) -> dict:
    run = db.get(PredictionRun, run_id)
    source = db.get(PredictionShipment, shipment_id)
    if not run or not source or source.prediction_run_id != run.id:
        raise HTTPException(status_code=404, detail={"code": "PREDICTION_SHIPMENT_NOT_FOUND", "message": "Predicted shipment was not found."})
    action = action.upper()
    selected_lines = db.scalars(
        select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id == source.id, PredictionShipmentLine.id.in_(line_ids))
    ).all() if line_ids else []
    if action in {"MOVE_LINES", "CREATE_SHIPMENT", "SPLIT_SINGLE"} and not selected_lines:
        raise HTTPException(status_code=400, detail={"code": "INVALID_SHIPMENT_OVERRIDE", "message": "Select at least one Loading Order line."})
    if action == "MOVE_LINES":
        target = db.get(PredictionShipment, target_shipment_id)
        if not target or target.prediction_run_id != run.id or target.shift_id != source.shift_id or target.id == source.id:
            raise HTTPException(status_code=409, detail={"code": "CROSS_SHIFT_SHIPMENT", "message": "Target shipment must be a different shipment in the same derived shift."})
    elif action in {"CREATE_SHIPMENT", "SPLIT_SINGLE"}:
        if action == "SPLIT_SINGLE" and len(selected_lines) != 1:
            raise HTTPException(status_code=400, detail={"code": "INVALID_SHIPMENT_OVERRIDE", "message": "SPLIT_SINGLE requires exactly one line."})
        target = PredictionShipment(
            id=uuid.uuid4().hex,
            prediction_run_id=run.id,
            predicted_shipment_id=f"MAN-{source.shift_id.upper()}-{uuid.uuid4().hex[:6].upper()}",
            shift_id=source.shift_id,
            shift_name=source.shift_name,
            planned_start_datetime=max(_utc(line.shipment_start_datetime) for line in selected_lines),
            shipment_prediction_score=source.shipment_prediction_score,
            confidence_level=source.confidence_level,
            low_confidence=source.low_confidence,
            is_manual_override=True,
            explanation={"manual_adjustment": action, "adjusted_by": user_id, "model_score_reused_from_source": source.predicted_shipment_id},
        )
        db.add(target)
        db.flush()
    elif action == "COMBINE":
        target = db.get(PredictionShipment, target_shipment_id) if target_shipment_id else None
        if not target or target.prediction_run_id != run.id or target.shift_id != source.shift_id or target.id == source.id:
            raise HTTPException(status_code=409, detail={"code": "CROSS_SHIFT_SHIPMENT", "message": "Shipments may only be combined inside one derived shift."})
        selected_lines = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id == source.id)).all()
    else:
        raise HTTPException(status_code=400, detail={"code": "INVALID_SHIPMENT_OVERRIDE", "message": "Unsupported shipment override action."})
    existing_target_lines = db.scalars(
        select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id == target.id)
    ).all()
    projected_by_id = {line.id: line for line in existing_target_lines}
    projected_by_id.update({line.id: line for line in selected_lines})
    projected_lines = [{"order_quantity_kl": line.order_quantity_kl} for line in projected_by_id.values()]
    projected_capacity = shipment_capacity(projected_lines)
    maximum_compartments = int(run.parameter_snapshot.get("maximum_shipment_compartments", 4))
    if not projected_capacity["valid"] or projected_capacity["required_compartments"] > maximum_compartments:
        if action in {"CREATE_SHIPMENT", "SPLIT_SINGLE"}:
            db.delete(target)
            db.flush()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SHIPMENT_COMPARTMENT_LIMIT_EXCEEDED",
                "message": f"Shipment may use at most {maximum_compartments} compartments of 8 KL.",
            },
        )
    for line in selected_lines:
        line.prediction_shipment_id = target.id
    target.is_manual_override = True
    target.explanation = {**(target.explanation or {}), "manual_adjustment": action, "adjusted_by": user_id}
    db.flush()
    target_lines = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id == target.id)).all()
    target.planned_start_datetime = max(_utc(line.shipment_start_datetime) for line in target_lines)
    remaining = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id == source.id)).all()
    if remaining:
        source.planned_start_datetime = max(_utc(line.shipment_start_datetime) for line in remaining)
    else:
        db.execute(delete(PredictionMTCandidate).where(PredictionMTCandidate.prediction_shipment_id == source.id))
        db.execute(delete(PredictionAssignment).where(PredictionAssignment.prediction_shipment_id == source.id))
        db.execute(delete(PredictionTrip).where(PredictionTrip.prediction_shipment_id == source.id))
        db.delete(source)
    db.flush()
    _rebuild_candidates_and_timeline(db, run)
    db.commit()
    return get_prediction_run(db, run.id, include_candidates=False)


def duplicate_prediction_run(db: Session, run_id: str, *, model_id: str | None, created_by: str) -> dict:
    source = db.get(PredictionRun, run_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "PREDICTION_RUN_NOT_FOUND", "message": "Prediction run was not found."})

    def workbook_bytes(headers: list[str], rows: list[list]) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    lo_content = workbook_bytes(
        ["loading_order_no", "shipment_start_datetime", "spbu_no", "product", "order_quantity_kl"],
        [[row["loading_order_no"], row["shipment_start_datetime_local"], row["spbu_no"], row.get("product_name"), row.get("order_quantity_kl")] for row in source.input_loading_order_snapshot],
    )
    mt_content = workbook_bytes(
        ["vehicle_registration_no", "initial_available_datetime"],
        [[row["vehicle_registration_no"], row["initial_available_datetime_local"]] for row in source.input_mt_availability_snapshot],
    )
    return enqueue_prediction_run(
        db,
        depot_id=source.depot_id,
        model_id=model_id or source.model_id,
        loading_order_content=lo_content,
        loading_order_filename=f"rerun-{source.input_loading_order_filename}",
        availability_content=mt_content,
        availability_filename=f"rerun-{source.input_mt_availability_filename}",
        parameters=source.parameter_snapshot,
        created_by=created_by,
    )
