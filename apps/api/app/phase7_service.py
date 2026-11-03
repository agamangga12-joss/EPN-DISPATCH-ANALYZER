from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.orm import Session

from .compatibility import evaluate_compatibility_entities
from .database import SessionLocal
from .google_routes import get_google_routes_configuration
from .models import (
    ActualBayState,
    ActualVehicleEvent,
    BridgeMTTag,
    BridgeSPBUTag,
    FactSPBUMTPair,
    FactSPBUPair,
    LOOperationalState,
    LoadingBayProductCompatibility,
    MasterDepot,
    MasterLoadingBay,
    MasterMT,
    MasterProduct,
    MasterSPBU,
    MasterTag,
    OperationalStateSnapshot,
    OptimizationBayAssignment,
    OptimizationBayOperation,
    OptimizationInitialQueue,
    OptimizationJob,
    OptimizationParameterProfile,
    OptimizationParameterSnapshot,
    OptimizationParameterValue,
    OptimizationRun,
    OptimizationVehicleCostRule,
    PredictionAssignment,
    PredictionRun,
    PredictionShipment,
    PredictionShipmentLine,
    PredictionTrip,
    ProductCompartmentLoadingDuration,
    RouteAPIRequestLog,
    RouteVersion,
    RouteVersionLOAssignment,
    RouteVersionStop,
    RouteVersionTrip,
    RouteVersionVehicleAssignment,
    VehicleOperationalState,
)
from .phase6_capacity import mt_compartment_profile
from .phase7_constants import (
    CONSTRAINT_DEFINITIONS,
    DEFAULT_PARAMETER_PROFILES,
    DEFAULT_PHASE7_PARAMETERS,
    JOB_STATUSES,
    LO_STATUSES,
    MT_STATUSES,
    constraint_is_hard,
    constraint_is_soft,
    constraint_limit_minutes,
    constraint_penalty,
    constraint_rule,
    effective_parameters,
)
from .phase7_matrix import RouteMatrixService
from .restricted_roads import RestrictedRoadRouter, RestrictedRoutingError, geometry_conflicts, restriction_snapshot, missing_detours
from .phase7_optimization import OptimizationCoordinatorService


logger = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _iso(value: datetime | date | time | None) -> str | None:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    return value.isoformat() if value else None


def _timezone(depot: MasterDepot | None) -> ZoneInfo:
    try:
        return ZoneInfo(depot.timezone if depot and depot.timezone else "Asia/Jakarta")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Jakarta")


def _optimization_reference_context(db: Session, job: OptimizationJob) -> tuple[datetime | None, datetime | None]:
    runs = db.scalars(
        select(OptimizationRun)
        .where(
            OptimizationRun.job_id == job.job_id,
            OptimizationRun.status == "COMPLETED",
        )
        .order_by(OptimizationRun.start_time, OptimizationRun.optimization_run_id)
    ).all()
    references = [
        (run, _utc(run.optimization_reference_time or run.start_time))
        for run in runs
        if run.optimization_reference_time or run.start_time
    ]
    initial_reference = next((reference for run, reference in references if run.run_type == "INITIAL"), None)
    latest_reference = references[-1][1] if references else None
    return initial_reference, latest_reference


def _normalize_optimization_reference_time(
    job: OptimizationJob,
    depot: MasterDepot | None,
    raw_value: datetime | str | None,
    *,
    reroute: bool,
    initial_reference_time: datetime | None = None,
    latest_reference_time: datetime | None = None,
) -> datetime:
    if raw_value is None or raw_value == "":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "OPTIMIZATION_REFERENCE_TIME_REQUIRED",
                "message": "Select the optimization date and time before starting Phase 7.",
            },
        )
    try:
        parsed = raw_value if isinstance(raw_value, datetime) else datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_OPTIMIZATION_REFERENCE_TIME", "message": "Optimization date and time is invalid."},
        ) from exc

    zone = _timezone(depot)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    local_reference = parsed.astimezone(zone)
    reference_utc = local_reference.astimezone(timezone.utc)

    if reroute:
        locked_date = (
            _utc(initial_reference_time).astimezone(zone).date()
            if initial_reference_time
            else job.operating_date
        )
        if local_reference.date() != locked_date:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "REROUTE_DATE_LOCKED",
                    "message": f"Re-optimization date is locked to the initial optimization date {locked_date.isoformat()}.",
                },
            )
        if latest_reference_time and reference_utc < _utc(latest_reference_time):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "OPTIMIZATION_TIME_BEFORE_LAST_RUN",
                    "message": "Re-optimization time cannot be earlier than the latest completed optimization time.",
                },
            )
    elif local_reference.date() != job.operating_date:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "OPTIMIZATION_DATE_MISMATCH",
                "message": f"Initial optimization date must match Job operating date {job.operating_date.isoformat()}.",
            },
        )

    return reference_utc


def _job_day(job: OptimizationJob, depot: MasterDepot) -> tuple[datetime, datetime, datetime]:
    zone = _timezone(depot)
    day_start = datetime.combine(job.operating_date, time.min, tzinfo=zone).astimezone(timezone.utc)
    operational_start = datetime.combine(job.operating_date, job.depot_operational_start, tzinfo=zone).astimezone(timezone.utc)
    operational_end = datetime.combine(job.operating_date, job.depot_operational_end, tzinfo=zone).astimezone(timezone.utc)
    if operational_end <= operational_start:
        operational_end += timedelta(days=1)
    return day_start, operational_start, operational_end


def _default_bay_state_reference_time(db: Session, job: OptimizationJob) -> datetime:
    """Use operational time, never the API server clock, for bay state."""
    _, latest_reference = _optimization_reference_context(db, job)
    if latest_reference:
        return latest_reference
    depot = db.get(MasterDepot, job.depot_id)
    assert depot is not None
    day_start, _, _ = _job_day(job, depot)
    return day_start


def _align_bay_state_reference_time(db: Session, job: OptimizationJob, reference_time: datetime) -> None:
    """Make saved actual bay/queue facts effective at the dispatcher's run time."""
    normalized = _utc(reference_time)
    db.execute(
        update(ActualBayState)
        .where(ActualBayState.job_id == job.job_id)
        .values(state_effective_at=normalized)
    )
    db.execute(
        update(OptimizationInitialQueue)
        .where(OptimizationInitialQueue.job_id == job.job_id)
        .values(state_effective_at=normalized)
    )


def _job_number(operating_date: date) -> str:
    return f"P7-JOB-{operating_date:%Y%m%d}-{uuid.uuid4().hex[:5].upper()}"


def _require_job(db: Session, job_id: str) -> OptimizationJob:
    job = db.get(OptimizationJob, job_id) or db.scalar(select(OptimizationJob).where(OptimizationJob.job_no == job_id))
    if not job:
        raise HTTPException(status_code=404, detail={"code": "PHASE7_JOB_NOT_FOUND", "message": "Phase 7 Job was not found."})
    return job


def _editable_job(db: Session, job_id: str) -> OptimizationJob:
    job = _require_job(db, job_id)
    job = db.scalar(select(OptimizationJob).where(OptimizationJob.job_id == job.job_id).with_for_update().execution_options(populate_existing=True))
    if job.status == "CALCULATING":
        raise HTTPException(409, detail={"code": "PHASE7_JOB_CALCULATING", "message": "Wait until optimization finishes before changing this Job."})
    return job


def job_lo_options(db: Session, job_id: str) -> list[dict]:
    job = _require_job(db, job_id)
    return [{"spbu_id": row.spbu_id, "spbu_code": row.spbu_code, "spbu_name": row.spbu_name}
            for row in db.scalars(select(MasterSPBU).where(MasterSPBU.primary_depot_id == job.depot_id, MasterSPBU.active_status == "ACTIVE").order_by(MasterSPBU.spbu_code)).all()]


def add_job_lo(db: Session, job_id: str, payload: dict, *, actor: str = "local-user") -> dict:
    job = _editable_job(db, job_id)
    if not job.source_prediction_run_id:
        raise HTTPException(422, detail={"code": "PREDICTION_RUN_REQUIRED", "message": "Load the Phase 6 source before adding an operational LO."})
    lo_id = str(payload["loading_order_id"]).strip()
    volume = float(payload["volume_kl"])
    if not lo_id or len(lo_id) > 120 or not math.isfinite(volume) or volume <= 0:
        raise HTTPException(422, detail={"code": "INVALID_LO", "message": "LO number and positive finite volume are required."})
    if db.scalar(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.loading_order_id == lo_id)):
        raise HTTPException(409, detail={"code": "DUPLICATE_LO", "message": "LO number already exists in this Job, including cancelled LO."})
    spbu = db.get(MasterSPBU, payload["spbu_id"])
    product = db.get(MasterProduct, payload["product_id"])
    if not spbu or spbu.primary_depot_id != job.depot_id or spbu.active_status != "ACTIVE":
        raise HTTPException(422, detail={"code": "INVALID_SPBU", "message": "Select an active SPBU belonging to this Job depot."})
    if not product or product.active_status != "ACTIVE":
        raise HTTPException(422, detail={"code": "INVALID_PRODUCT", "message": "Select an active master product."})
    db.add(LOOperationalState(lo_state_id=uuid.uuid4().hex, job_id=job.job_id, loading_order_id=lo_id,
        spbu_id=spbu.spbu_id, spbu_name_snapshot=spbu.spbu_name, product_id=product.product_id,
        product_name_snapshot=product.product_name, volume_kl=volume, depot_id=job.depot_id,
        operating_date=job.operating_date, source_prediction_run_id=job.source_prediction_run_id,
        status="PLANNED", frozen=False, updated_by=actor))
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ADDED", "loading_order_id": lo_id}


def cancel_job_los(db: Session, job_id: str, lo_ids: list[str], *, actor: str = "local-user") -> dict:
    job = _editable_job(db, job_id)
    rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id)).all()
    selected = {row.loading_order_id: row for row in rows if row.loading_order_id in lo_ids}
    if set(lo_ids) != set(selected):
        raise HTTPException(404, detail={"code": "LO_NOT_FOUND", "message": "One or more LO does not belong to this Job."})
    executed_trips = {(row.current_vehicle_id, row.current_trip_number) for row in rows if row.status in {"ONGOING", "DONE"} and row.current_vehicle_id and row.current_trip_number is not None}
    if any(row.status != "PLANNED" or row.frozen or (row.current_vehicle_id, row.current_trip_number) in executed_trips for row in selected.values()):
        raise HTTPException(409, detail={"code": "LO_LOCKED", "message": "Ongoing, completed, frozen LO or LO in an executed trip cannot be cancelled."})
    for row in selected.values():
        row.user_cancelled = True
        row.updated_by = actor
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "CANCELLED", "loading_order_ids": sorted(selected)}


def _job_mt_tags(db: Session, vehicles: list[VehicleOperationalState]) -> tuple[dict, dict]:
    ids = [row.mt_id for row in vehicles]
    tags, _, labels = _tags(db, ids, [])
    options = {row.mt_id: [{"tag_id": tag_id, "tag_value": labels[tag_id]} for tag_id in sorted(tags[row.mt_id], key=lambda key: labels[key])] for row in vehicles}
    for row in vehicles:
        tags[row.mt_id] -= set(row.disabled_tag_ids or [])
    return tags, options


def _require_version(db: Session, job: OptimizationJob, version_id: str | None = None) -> RouteVersion:
    route_version = None
    if version_id:
        route_version = db.get(RouteVersion, version_id)
        if not route_version and str(version_id).upper().startswith("V"):
            try:
                version_number = int(str(version_id)[1:])
            except ValueError:
                version_number = -1
            route_version = db.scalar(select(RouteVersion).where(RouteVersion.job_id == job.job_id, RouteVersion.version_number == version_number))
    elif job.current_route_version_id:
        route_version = db.get(RouteVersion, job.current_route_version_id)
    if not route_version or route_version.job_id != job.job_id:
        raise HTTPException(status_code=404, detail={"code": "ROUTE_VERSION_NOT_FOUND", "message": "Route version was not found for this Job."})
    return route_version


def _date_from_prediction_row(row: dict, depot: MasterDepot | None) -> date | None:
    value = row.get("shipment_start_datetime_local") or row.get("shipment_start_datetime")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(_timezone(depot))
    return parsed.date()


def ensure_default_parameter_profiles(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(OptimizationParameterProfile)):
        return
    for index, (name, description, overrides) in enumerate(DEFAULT_PARAMETER_PROFILES):
        profile_id = uuid.uuid4().hex
        db.add(
            OptimizationParameterProfile(
                profile_id=profile_id,
                profile_name=name,
                description=description,
                version=1,
                is_default=index == 0,
                is_active=True,
                created_by="system",
            )
        )
        parameters = effective_parameters(overrides)
        db.add(
            OptimizationParameterValue(
                parameter_value_id=uuid.uuid4().hex,
                profile_id=profile_id,
                parameter_key="parameters",
                parameter_value=parameters,
            )
        )
        for rule in parameters["vehicle_activation_cost_rules"]:
            db.add(
                OptimizationVehicleCostRule(
                    cost_rule_id=uuid.uuid4().hex,
                    profile_id=profile_id,
                    vehicle_class=rule.get("vehicle_class"),
                    vehicle_tag=rule.get("vehicle_tag"),
                    activation_cost=float(rule.get("activation_cost") or 0),
                    priority=int(rule.get("priority") or 0),
                )
            )
    db.commit()


def _profile_payload(db: Session, profile: OptimizationParameterProfile) -> dict:
    row = db.scalar(select(OptimizationParameterValue).where(OptimizationParameterValue.profile_id == profile.profile_id, OptimizationParameterValue.parameter_key == "parameters"))
    rules = db.scalars(select(OptimizationVehicleCostRule).where(OptimizationVehicleCostRule.profile_id == profile.profile_id).order_by(desc(OptimizationVehicleCostRule.priority))).all()
    parameters = effective_parameters(row.parameter_value if row else {})
    parameters["vehicle_activation_cost_rules"] = [
        {"vehicle_class": rule.vehicle_class, "vehicle_tag": rule.vehicle_tag, "activation_cost": rule.activation_cost, "priority": rule.priority}
        for rule in rules
    ] or parameters["vehicle_activation_cost_rules"]
    return {
        "profile_id": profile.profile_id,
        "profile_name": profile.profile_name,
        "description": profile.description,
        "version": profile.version,
        "created_by": profile.created_by,
        "created_at": _iso(profile.created_at),
        "updated_at": _iso(profile.updated_at),
        "is_default": profile.is_default,
        "is_active": profile.is_active,
        "parameters": parameters,
    }


def list_parameter_profiles(db: Session, *, include_inactive: bool = False) -> list[dict]:
    ensure_default_parameter_profiles(db)
    statement = select(OptimizationParameterProfile)
    if not include_inactive:
        statement = statement.where(OptimizationParameterProfile.is_active.is_(True))
    profiles = db.scalars(statement.order_by(OptimizationParameterProfile.profile_name, desc(OptimizationParameterProfile.version))).all()
    return [_profile_payload(db, profile) for profile in profiles]


def get_parameter_profile(db: Session, profile_id: str) -> dict:
    ensure_default_parameter_profiles(db)
    profile = db.get(OptimizationParameterProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail={"code": "PARAMETER_PROFILE_NOT_FOUND", "message": "Optimization parameter profile was not found."})
    return _profile_payload(db, profile)


def save_parameter_profile(db: Session, payload: dict, *, actor: str = "local-user", source_profile_id: str | None = None, save_as: bool = False) -> dict:
    ensure_default_parameter_profiles(db)
    parameters = effective_parameters(payload.get("parameters") or {})
    profile_name = str(payload.get("profile_name") or "").strip()
    description = str(payload.get("description") or "").strip() or None
    if source_profile_id and not save_as:
        source = db.get(OptimizationParameterProfile, source_profile_id)
        if not source:
            raise HTTPException(status_code=404, detail={"code": "PARAMETER_PROFILE_NOT_FOUND", "message": "Source profile was not found."})
        profile_name = profile_name or source.profile_name
        description = description or source.description
        version = max(db.scalars(select(OptimizationParameterProfile.version).where(OptimizationParameterProfile.profile_name == profile_name)).all() or [0]) + 1
        source.is_active = False
    else:
        if not profile_name:
            raise HTTPException(status_code=400, detail={"code": "PROFILE_NAME_REQUIRED", "message": "profile_name is required."})
        version = 1
        existing_versions = db.scalars(select(OptimizationParameterProfile.version).where(OptimizationParameterProfile.profile_name == profile_name)).all()
        if existing_versions:
            version = max(existing_versions) + 1
    profile = OptimizationParameterProfile(
        profile_id=uuid.uuid4().hex,
        profile_name=profile_name,
        description=description,
        version=version,
        created_by=actor,
        is_default=bool(payload.get("is_default", False)),
        is_active=True,
    )
    if profile.is_default:
        for old in db.scalars(select(OptimizationParameterProfile).where(OptimizationParameterProfile.is_default.is_(True))).all():
            old.is_default = False
    db.add(profile)
    db.flush()
    db.add(OptimizationParameterValue(parameter_value_id=uuid.uuid4().hex, profile_id=profile.profile_id, parameter_key="parameters", parameter_value=parameters))
    for rule in parameters.get("vehicle_activation_cost_rules") or []:
        db.add(
            OptimizationVehicleCostRule(
                cost_rule_id=uuid.uuid4().hex,
                profile_id=profile.profile_id,
                vehicle_class=rule.get("vehicle_class"),
                vehicle_tag=rule.get("vehicle_tag"),
                activation_cost=float(rule.get("activation_cost") or 0),
                priority=int(rule.get("priority") or 0),
            )
        )
    db.commit()
    return _profile_payload(db, profile)


def create_job(db: Session, payload: dict, *, actor: str = "local-user") -> dict:
    depot = db.get(MasterDepot, payload.get("depot_id"))
    if not depot:
        raise HTTPException(status_code=404, detail={"code": "DEPOT_NOT_FOUND", "message": "Selected depot was not found."})
    try:
        operating_date = date.fromisoformat(str(payload.get("operating_date")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_OPERATING_DATE", "message": "operating_date must be YYYY-MM-DD."}) from exc
    name = str(payload.get("job_name") or "").strip() or f"Optimization {depot.depot_name} {operating_date.isoformat()}"
    job = OptimizationJob(
        job_id=uuid.uuid4().hex,
        job_no=_job_number(operating_date),
        job_name=name,
        depot_id=depot.depot_id,
        operating_date=operating_date,
        depot_operational_start=depot.depot_operational_start,
        depot_operational_end=depot.depot_operational_end,
        status="DRAFT",
        created_by=actor,
    )
    db.add(job)
    db.commit()
    return get_job(db, job.job_id)


def list_jobs(db: Session, depot_id: str) -> list[dict]:
    if not depot_id:
        raise HTTPException(status_code=400, detail={"code": "DEPOT_REQUIRED", "message": "Select a depot before listing Phase 7 Jobs."})
    jobs = db.scalars(select(OptimizationJob).where(OptimizationJob.depot_id == depot_id).order_by(desc(OptimizationJob.updated_at))).all()
    return [_job_summary(db, job) for job in jobs]


def delete_job(db: Session, job_id: str) -> dict:
    job = _require_job(db, job_id)
    if job.status == "CALCULATING":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PHASE7_JOB_CALCULATING",
                "message": "Job cannot be deleted while optimization is calculating.",
            },
        )
    deleted = {"job_id": job.job_id, "job_no": job.job_no, "status": "DELETED"}
    # Provider request logs remain as audit evidence, detached from the Job
    # whose complete Phase 7 workspace is cascaded away.
    db.execute(update(RouteAPIRequestLog).where(RouteAPIRequestLog.job_id == job.job_id).values(job_id=None))
    db.delete(job)
    db.commit()
    return deleted


def _job_summary(db: Session, job: OptimizationJob) -> dict:
    depot = db.get(MasterDepot, job.depot_id)
    lo_rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(False))).all()
    mt_count = db.scalar(select(func.count()).select_from(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)) or 0
    version = db.get(RouteVersion, job.current_route_version_id) if job.current_route_version_id else None
    return {
        "job_id": job.job_id,
        "job_no": job.job_no,
        "job_name": job.job_name,
        "operating_date": job.operating_date.isoformat(),
        "depot_id": job.depot_id,
        "depot": depot.depot_name if depot else job.depot_id,
        "total_lo": len(lo_rows),
        "total_mt": int(mt_count),
        "current_route_version_id": job.current_route_version_id,
        "current_route_version": version.version_label if version else None,
        "status": job.status,
        "last_updated": _iso(job.updated_at),
        "source_prediction_run_id": job.source_prediction_run_id,
    }


def _job_kpis(db: Session, job: OptimizationJob) -> dict:
    rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(False))).all()
    statuses = Counter(row.status for row in rows)
    version = db.get(RouteVersion, job.current_route_version_id) if job.current_route_version_id else None
    summary = version.summary_snapshot if version else {}
    total_volume = sum(float(row.volume_kl or 0) for row in rows)
    delivered = sum(float(row.volume_kl or 0) for row in rows if row.status == "DONE")
    dropped = int(summary.get("dropped_lo") or 0)
    return {
        "total_lo": len(rows),
        "done_lo": statuses["DONE"],
        "ongoing_lo": statuses["ONGOING"],
        "planned_lo": statuses["PLANNED"],
        "dropped_lo": dropped,
        "used_mt": int(summary.get("used_mt") or 0),
        "total_trips": int(summary.get("total_trips") or 0),
        "delivered_kl": round(delivered, 3),
        "remaining_kl": round(max(0, total_volume - delivered), 3),
        "completion_pct": round(statuses["DONE"] / len(rows) * 100, 2) if rows else 0,
    }


def get_job(db: Session, job_id: str) -> dict:
    job = _require_job(db, job_id)
    depot = db.get(MasterDepot, job.depot_id)
    initial_reference_time, latest_reference_time = _optimization_reference_context(db, job)
    current = db.get(RouteVersion, job.current_route_version_id) if job.current_route_version_id else None
    latest_run = db.scalar(
        select(OptimizationRun)
        .where(OptimizationRun.job_id == job.job_id)
        .order_by(desc(OptimizationRun.start_time))
        .limit(1)
    )
    optimization = None
    if latest_run:
        metadata = latest_run.solver_metadata or {}
        elapsed_ms = latest_run.solve_duration_ms or 0
        if latest_run.status == "RUNNING" and latest_run.start_time:
            elapsed_ms = round((datetime.now(timezone.utc) - _utc(latest_run.start_time)).total_seconds() * 1000)
        optimization = {
            "run_id": latest_run.optimization_run_id,
            "run_type": latest_run.run_type,
            "status": latest_run.status,
            "solver_status": latest_run.solver_status,
            "stage": metadata.get("stage") or latest_run.solver_status,
            "progress_pct": int(metadata.get("progress_pct") or 0),
            "elapsed_ms": elapsed_ms,
            "started_at": _iso(latest_run.start_time),
            "ended_at": _iso(latest_run.end_time),
            "optimization_reference_time": _iso(latest_run.optimization_reference_time or latest_run.start_time),
            "metadata": metadata,
            "error_code": latest_run.error_code,
            "error_message": latest_run.error_message,
        }
    if job.status == "CALCULATING" and (not latest_run or latest_run.status != "RUNNING"):
        optimization = {"run_id": "", "run_type": "REROUTE" if current else "INITIAL", "status": "QUEUED",
                        "solver_status": "PENDING", "stage": "QUEUED", "progress_pct": 0, "elapsed_ms": 0,
                        "started_at": None, "ended_at": None, "optimization_reference_time": None,
                        "metadata": {"execution_mode": "ISOLATED_PROCESS"}, "error_code": None, "error_message": None}
    return {
        **_job_summary(db, job),
        "header": {
            "job_id": job.job_no,
            "depot": depot.depot_name if depot else job.depot_id,
            "operating_date": job.operating_date.isoformat(),
            "source_phase6_run_id": _prediction_run_no(db, job.source_prediction_run_id),
            "current_route_version": current.version_label if current else None,
            "job_status": job.status,
        },
        "kpis": _job_kpis(db, job),
        "depot_operational_start": _iso(job.depot_operational_start),
        "depot_operational_end": _iso(job.depot_operational_end),
        "depot_timezone": _timezone(depot).key,
        "initial_optimization_reference_time": _iso(initial_reference_time),
        "latest_optimization_reference_time": _iso(latest_reference_time),
        "error_message": job.error_message,
        "optimization": optimization,
    }


def _prediction_run_no(db: Session, run_id: str | None) -> str | None:
    run = db.get(PredictionRun, run_id) if run_id else None
    return run.prediction_run_no if run else None


def list_prediction_runs_for_job(db: Session, job_id: str) -> list[dict]:
    job = _require_job(db, job_id)
    depot = db.get(MasterDepot, job.depot_id)
    runs = db.scalars(
        select(PredictionRun).where(PredictionRun.depot_id == job.depot_id, PredictionRun.status == "COMPLETED").order_by(desc(PredictionRun.completed_at))
    ).all()
    result = []
    for run in runs:
        dates = {_date_from_prediction_row(row, depot) for row in run.input_loading_order_snapshot or []}
        dates.discard(None)
        if dates and job.operating_date not in dates:
            continue
        shipment_count = db.scalar(select(func.count()).select_from(PredictionShipment).where(PredictionShipment.prediction_run_id == run.id)) or 0
        assignments = db.scalars(
            select(PredictionAssignment).join(PredictionShipment, PredictionShipment.id == PredictionAssignment.prediction_shipment_id).where(PredictionShipment.prediction_run_id == run.id)
        ).all()
        result.append(
            {
                "id": run.id,
                "run_id": run.prediction_run_no,
                "date": job.operating_date.isoformat(),
                "depot_id": run.depot_id,
                "depot": depot.depot_name if depot else run.depot_id,
                "total_lo": len(run.input_loading_order_snapshot or []),
                "predicted_shipment_count": int(shipment_count),
                "predicted_mt_count": len({row.final_vehicle_id for row in assignments if row.final_vehicle_id}),
                "model_id": run.model_id,
                "model_name": (run.model_snapshot or {}).get("model_name") or run.model_id,
                "saved_at": _iso(run.completed_at or run.created_at),
                "status": run.status,
            }
        )
    return result


def load_prediction_run(db: Session, job_id: str, run_id: str, *, actor: str = "local-user") -> dict:
    job = _editable_job(db, job_id)
    run = db.get(PredictionRun, run_id) or db.scalar(select(PredictionRun).where(PredictionRun.prediction_run_no == run_id))
    if not run or run.status != "COMPLETED":
        raise HTTPException(status_code=422, detail={"code": "INVALID_PHASE6_RUN", "message": "Select a completed/saved Phase 6 Prediction Run."})
    if run.depot_id != job.depot_id:
        raise HTTPException(status_code=422, detail={"code": "PHASE6_DEPOT_MISMATCH", "message": "Prediction Run depot does not match the Phase 7 Job depot."})
    depot = db.get(MasterDepot, job.depot_id)
    dates = {_date_from_prediction_row(row, depot) for row in run.input_loading_order_snapshot or []}
    dates.discard(None)
    if dates and job.operating_date not in dates:
        raise HTTPException(status_code=422, detail={"code": "PHASE6_DATE_MISMATCH", "message": "Prediction Run operating date does not match the Phase 7 Job."})
    existing = db.scalar(select(func.count()).select_from(LOOperationalState).where(LOOperationalState.job_id == job.job_id)) or 0
    if existing:
        if job.source_prediction_run_id == run.id:
            return get_job(db, job.job_id)
        raise HTTPException(status_code=409, detail={"code": "PHASE6_ALREADY_LOADED", "message": "This Job already has an immutable Phase 6 source. Create another Job to use a different run."})
    shipments = db.scalars(select(PredictionShipment).where(PredictionShipment.prediction_run_id == run.id)).all()
    shipment_ids = [row.id for row in shipments]
    lines = db.scalars(select(PredictionShipmentLine).where(PredictionShipmentLine.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else []
    assignments = db.scalars(select(PredictionAssignment).where(PredictionAssignment.prediction_shipment_id.in_(shipment_ids))).all() if shipment_ids else []
    shipment_by_id = {row.id: row for row in shipments}
    assignment_by_shipment = {row.prediction_shipment_id: row for row in assignments}
    lines_by_shipment: dict[str, list[PredictionShipmentLine]] = defaultdict(list)
    for line in lines:
        lines_by_shipment[line.prediction_shipment_id].append(line)
    spbu_ids = {line.spbu_id for line in lines}
    spbus = {row.spbu_id: row for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()} if spbu_ids else {}
    for line in lines:
        shipment = shipment_by_id[line.prediction_shipment_id]
        assignment = assignment_by_shipment.get(shipment.id)
        pairing = sorted({row.spbu_id for row in lines_by_shipment[shipment.id]})
        db.add(
            LOOperationalState(
                lo_state_id=uuid.uuid4().hex,
                job_id=job.job_id,
                loading_order_id=line.loading_order_no,
                spbu_id=line.spbu_id,
                spbu_name_snapshot=spbus[line.spbu_id].spbu_name if line.spbu_id in spbus else line.spbu_no,
                product_id=line.product_id,
                product_name_snapshot=line.product_name,
                volume_kl=float(line.order_quantity_kl or 0),
                depot_id=job.depot_id,
                operating_date=job.operating_date,
                source_prediction_run_id=run.id,
                phase6_predicted_shipment_id=shipment.predicted_shipment_id,
                phase6_predicted_vehicle_id=assignment.final_vehicle_id if assignment else None,
                phase6_predicted_spbu_pairing=pairing,
                phase6_shipment_confidence=shipment.shipment_prediction_score,
                phase6_vehicle_assignment_confidence=assignment.final_assignment_score if assignment else None,
                phase6_model_id=run.model_id,
                status="PLANNED",
                frozen=False,
                updated_by=actor,
            )
        )
    job.source_prediction_run_id = run.id
    job.status = "DRAFT"
    db.commit()
    return get_job(db, job.job_id)


def list_job_los(db: Session, job_id: str) -> list[dict]:
    job = _require_job(db, job_id)
    rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(False)).order_by(LOOperationalState.loading_order_id)).all()
    mt_ids = {row.phase6_predicted_vehicle_id for row in rows if row.phase6_predicted_vehicle_id} | {row.current_vehicle_id for row in rows if row.current_vehicle_id}
    mts = {row.mt_id: row for row in db.scalars(select(MasterMT).where(MasterMT.mt_id.in_(mt_ids))).all()} if mt_ids else {}
    system_eta_by_lo: dict[str, datetime] = {}
    if job.current_route_version_id:
        system_eta_by_lo = {
            loading_order_id: estimated_return_depot
            for loading_order_id, estimated_return_depot in db.execute(
                select(
                    RouteVersionLOAssignment.loading_order_id,
                    RouteVersionTrip.estimated_return_depot,
                )
                .join(
                    RouteVersionTrip,
                    RouteVersionTrip.route_version_trip_id == RouteVersionLOAssignment.route_version_trip_id,
                )
                .where(RouteVersionLOAssignment.route_version_id == job.current_route_version_id)
            ).all()
        }
    return [
        {
            "lo_state_id": row.lo_state_id,
            "loading_order_id": row.loading_order_id,
            "spbu_id": row.spbu_id,
            "spbu_name": row.spbu_name_snapshot,
            "product_id": row.product_id,
            "product_name": row.product_name_snapshot,
            "volume_kl": row.volume_kl,
            "phase6_shipment": row.phase6_predicted_shipment_id,
            "phase6_mt_id": row.phase6_predicted_vehicle_id,
            "phase6_mt": mts[row.phase6_predicted_vehicle_id].vehicle_registration if row.phase6_predicted_vehicle_id in mts else row.phase6_predicted_vehicle_id,
            "phase6_pairing": row.phase6_predicted_spbu_pairing,
            "shipment_confidence": row.phase6_shipment_confidence,
            "vehicle_assignment_confidence": row.phase6_vehicle_assignment_confidence,
            "current_mt_id": row.current_vehicle_id,
            "current_mt": mts[row.current_vehicle_id].vehicle_registration if row.current_vehicle_id in mts else row.current_vehicle_id,
            "current_trip": row.current_trip_number,
            "current_shipment": row.current_shipment_id,
            "current_compartment": row.current_compartment_id,
            "planned_gate_out": _iso(row.planned_gate_out),
            # This is intentionally resolved from the LO's exact trip instead
            # of VehicleOperationalState.system_eta_depot.  The latter is a
            # one-value MT summary, while a multi-trip LO needs the return ETA
            # of Trip 1, Trip 2, and so on independently.
            "system_eta_depot": _iso(system_eta_by_lo.get(row.loading_order_id)),
            "status": row.status,
            "frozen": row.frozen,
            "frozen_reason": row.frozen_reason,
        }
        for row in rows
    ]


def _sync_trip_dependencies(rows):
    for row in rows:
        if row.frozen_reason == "FROZEN_TRIP_DEPENDENCY":
            row.frozen, row.frozen_reason = False, None
    groups = {(row.current_vehicle_id, row.current_trip_number) for row in rows
              if not row.user_cancelled and row.frozen and row.current_vehicle_id and row.current_trip_number is not None}
    for row in rows:
        if not row.user_cancelled and row.status == "PLANNED" and not row.frozen and (row.current_vehicle_id, row.current_trip_number) in groups:
            row.frozen, row.frozen_reason = True, "FROZEN_TRIP_DEPENDENCY"


def release_lo_dependencies(db: Session, job_id: str, lo_ids: list[str], *, actor: str = "local-user", freeze_window: bool = False) -> dict:
    job = _editable_job(db, job_id)
    rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id)).all()
    _sync_trip_dependencies(rows)
    selected = {row.loading_order_id: row for row in rows if row.loading_order_id in lo_ids}
    if set(selected) != set(lo_ids):
        raise HTTPException(404, detail={"code": "LO_NOT_FOUND", "message": "LO does not belong to this Job."})
    reason = "FREEZE_WINDOW" if freeze_window else "FROZEN_TRIP_DEPENDENCY"
    if any(row.user_cancelled or row.status != "PLANNED" or row.frozen_reason != reason for row in selected.values()):
        raise HTTPException(409, detail={"code": "LO_FREEZE_WINDOW_RELEASE_NOT_ALLOWED" if freeze_window else "LO_DEPENDENCY_RELEASE_NOT_ALLOWED", "message": f"Only PLANNED LO frozen by {reason} can be released."})
    for row in selected.values():
        before = {"loading_order_id": row.loading_order_id, "vehicle_id": row.current_vehicle_id, "trip_number": row.current_trip_number,
                  "shipment_id": row.current_shipment_id, "compartment_id": row.current_compartment_id, "planned_gate_out": _iso(row.planned_gate_out)}
        db.add(ActualVehicleEvent(vehicle_event_id=uuid.uuid4().hex, job_id=job.job_id, mt_id=row.current_vehicle_id,
            event_type="LO_FREEZE_WINDOW_RELEASE" if freeze_window else "LO_DEPENDENCY_RELEASE", event_time=datetime.now(timezone.utc), source="USER", details={"before": {**before, "frozen_reason": reason}, "updated_by": actor}))
        row.current_vehicle_id = row.current_trip_number = row.current_shipment_id = row.current_compartment_id = row.planned_gate_out = None
        row.frozen, row.frozen_reason = False, None
        row.updated_by = actor
    _sync_trip_dependencies(rows)
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "RELEASED", "loading_order_ids": sorted(selected)}


def update_lo_statuses(db: Session, job_id: str, updates: list[dict], *, actor: str = "local-user", route_version_id: str | None = None) -> dict:
    job = _editable_job(db, job_id)
    rows = {row.loading_order_id: row for row in db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id)).all()}
    _sync_trip_dependencies(list(rows.values()))
    if route_version_id and route_version_id != job.current_route_version_id:
        raise HTTPException(409, detail={"code": "STALE_ROUTE_VERSION", "message": "Operational status can only be edited from the current Route Version."})
    if route_version_id:
        assignments = {item.loading_order_id: item for item in db.scalars(select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == route_version_id)).all()}
        expanded = {}
        for update in updates:
            lo_id = str(update.get("loading_order_id"))
            row, assignment = rows.get(lo_id), assignments.get(lo_id)
            if not row or not assignment:
                raise HTTPException(409, detail={"code": "LO_NOT_IN_ROUTE", "message": "LO does not belong to the selected Route Version."})
            if row.user_cancelled or not row.current_vehicle_id or row.current_trip_number is None or row.current_vehicle_id != assignment.vehicle_id or row.current_trip_number != assignment.trip_number or not assignment.route_version_trip_id:
                raise HTTPException(409, detail={"code": "LO_DETACHED_FROM_TRIP", "message": "This LO no longer belongs to this trip. Re-Optimize before updating its trip status."})
            members = [member for member in rows.values() if not member.user_cancelled
                       and member.current_vehicle_id == row.current_vehicle_id and member.current_trip_number == row.current_trip_number
                       and member.loading_order_id in assignments
                       and assignments[member.loading_order_id].route_version_trip_id == assignment.route_version_trip_id]
            for member in members:
                item = {**update, "loading_order_id": member.loading_order_id}
                previous = expanded.get(member.loading_order_id)
                if previous and str(previous.get("status")).upper() != str(item.get("status")).upper():
                    raise HTTPException(409, detail={"code": "CONFLICTING_TRIP_STATUS", "message": "All LO in one trip must receive the same operational status."})
                expanded[member.loading_order_id] = item
        updates = list(expanded.values())
    # Validate the whole batch before changing any status.
    for item in updates:
        row = rows.get(str(item.get("loading_order_id")))
        if not route_version_id and row and row.frozen_reason == "FROZEN_TRIP_DEPENDENCY":
            raise HTTPException(409, detail={"code": "LO_TRIP_DEPENDENCY_LOCKED", "message": "Release this LO trip dependency in LO Management before changing its status."})
        if route_version_id and not db.scalar(select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == route_version_id, RouteVersionLOAssignment.loading_order_id == str(item.get("loading_order_id")))):
            raise HTTPException(409, detail={"code": "LO_NOT_IN_ROUTE", "message": "LO does not belong to the selected Route Version."})
    changed = []
    for update in updates:
        row = rows.get(str(update.get("loading_order_id")))
        if not row:
            raise HTTPException(status_code=404, detail={"code": "LO_NOT_FOUND", "message": f"LO {update.get('loading_order_id')} was not found in this Job."})
        if row.user_cancelled:
            raise HTTPException(409, detail={"code": "LO_CANCELLED", "message": "Cancelled LO cannot receive operational status updates."})
        status = str(update.get("status") or "").upper()
        if status not in LO_STATUSES:
            raise HTTPException(status_code=400, detail={"code": "INVALID_LO_STATUS", "message": f"Unsupported LO status: {status}."})
        before = row.status
        row.status = status
        row.updated_by = actor
        if status == "ONGOING":
            row.frozen = True
            row.frozen_reason = "ONGOING"
            if update.get("actual_gate_out"):
                row.actual_gate_out = datetime.fromisoformat(str(update["actual_gate_out"]).replace("Z", "+00:00"))
        elif status == "DONE":
            row.frozen = True
            row.frozen_reason = "DONE"
            if update.get("actual_delivered_at"):
                row.actual_delivered_at = datetime.fromisoformat(str(update["actual_delivered_at"]).replace("Z", "+00:00"))
        else:
            row.frozen = False
            row.frozen_reason = None
        changed.append({"loading_order_id": row.loading_order_id, "before": before, "after": status})
    _sync_trip_dependencies(list(rows.values()))
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "APPLIED", "changed": changed, "job": get_job(db, job.job_id)}


def load_mt_from_master(db: Session, job_id: str, *, actor: str = "local-user") -> dict:
    job = _editable_job(db, job_id)
    mts = db.scalars(select(MasterMT).where(MasterMT.depot_id == job.depot_id, MasterMT.active_status == "ACTIVE").order_by(MasterMT.vehicle_registration)).all()
    existing = {row.mt_id: row for row in db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)).all()}
    mt_ids = [row.mt_id for row in mts]
    tags_by_mt: dict[str, list[str]] = defaultdict(list)
    if mt_ids:
        for mt_id, tag in db.execute(select(BridgeMTTag.mt_id, MasterTag.tag_value).join(MasterTag, MasterTag.tag_id == BridgeMTTag.tag_id).where(BridgeMTTag.mt_id.in_(mt_ids))).all():
            tags_by_mt[mt_id].append(tag)
    added = 0
    for mt in mts:
        if mt.mt_id in existing:
            continue
        profile = mt_compartment_profile(mt)
        compartment_count = int(profile["effective_compartments"] or 0)
        capacity = float(profile["capacity_kl"] or 0)
        compartment_capacity = capacity / compartment_count if compartment_count else 0
        compartments = [{"compartment_id": f"C{index}", "capacity_kl": compartment_capacity} for index in range(1, compartment_count + 1)]
        default_working_time_limit = constraint_limit_minutes(DEFAULT_PHASE7_PARAMETERS, "vehicle_working_time")
        db.add(
            VehicleOperationalState(
                vehicle_state_id=uuid.uuid4().hex,
                job_id=job.job_id,
                mt_id=mt.mt_id,
                registration_snapshot=mt.vehicle_registration,
                vehicle_class=mt.vehicle_type_tag,
                tag_snapshot=sorted(tags_by_mt[mt.mt_id]),
                capacity_kl=capacity,
                number_of_compartments=compartment_count,
                compartment_configuration=compartments,
                operational_status="PARKING_DEPOT",
                working_time_limit_minutes=default_working_time_limit,
                working_time_remaining_minutes=default_working_time_limit,
                updated_by=actor,
            )
        )
        added += 1
    db.commit()
    return {"loaded": added, "total": len(mts), "vehicles": list_job_vehicles(db, job.job_id)}


def list_job_vehicles(db: Session, job_id: str) -> list[dict]:
    job = _require_job(db, job_id)
    rows = db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id).order_by(VehicleOperationalState.registration_snapshot)).all()
    effective_tags, tag_options = _job_mt_tags(db, rows)
    lo_statuses_by_mt: dict[str, set[str]] = defaultdict(set)
    for mt_id, lo_status in db.execute(
        select(LOOperationalState.current_vehicle_id, LOOperationalState.status).where(
            LOOperationalState.job_id == job.job_id,
            LOOperationalState.current_vehicle_id.is_not(None),
        )
    ).all():
        lo_statuses_by_mt[str(mt_id)].add(str(lo_status).upper())

    ongoing_eta_by_mt: dict[str, tuple[int, datetime]] = {}
    if job.current_route_version_id:
        ongoing_trip_rows = db.execute(
            select(
                RouteVersionLOAssignment.vehicle_id,
                RouteVersionTrip.trip_number,
                RouteVersionTrip.estimated_return_depot,
            )
            .join(
                RouteVersionTrip,
                RouteVersionTrip.route_version_trip_id == RouteVersionLOAssignment.route_version_trip_id,
            )
            .join(
                LOOperationalState,
                LOOperationalState.loading_order_id == RouteVersionLOAssignment.loading_order_id,
            )
            .where(
                RouteVersionLOAssignment.route_version_id == job.current_route_version_id,
                LOOperationalState.job_id == job.job_id,
                LOOperationalState.status == "ONGOING",
            )
        ).all()
        for mt_id, trip_number, estimated_return_depot in ongoing_trip_rows:
            if estimated_return_depot is None:
                continue
            key = str(mt_id)
            candidate = (int(trip_number), estimated_return_depot)
            if key not in ongoing_eta_by_mt or candidate[0] > ongoing_eta_by_mt[key][0]:
                ongoing_eta_by_mt[key] = candidate

    def delivery_status(mt_id: str) -> str:
        statuses = lo_statuses_by_mt.get(mt_id, set())
        if "ONGOING" in statuses:
            return "ONGOING"
        if "DONE" in statuses:
            return "DONE"
        return "PLANNED"

    def displayed_system_eta(mt_id: str) -> datetime | None:
        if delivery_status(mt_id) != "ONGOING":
            return None
        ongoing = ongoing_eta_by_mt.get(mt_id)
        return ongoing[1] if ongoing else None

    return [
        {
            "vehicle_state_id": row.vehicle_state_id,
            "mt_id": row.mt_id,
            "registration": row.registration_snapshot,
            "vehicle_class": row.vehicle_class,
            "tags": [item["tag_value"] for item in tag_options[row.mt_id] if item["tag_id"] in effective_tags[row.mt_id]],
            "master_tags": tag_options[row.mt_id],
            "disabled_tag_ids": row.disabled_tag_ids or [],
            "capacity_kl": row.capacity_kl,
            "number_of_compartments": row.number_of_compartments,
            "compartments": row.compartment_configuration,
            "planned_eta_depot": _iso(row.planned_eta_depot),
            # MT Management shows a System ETA only while this physical MT has
            # an ONGOING LO. Resolve it from that LO's exact current-version
            # trip, so multi-trip MTs display the matching Trip 1/2/... return.
            "system_eta_depot": _iso(displayed_system_eta(row.mt_id)),
            "effective_eta_depot": _iso(row.planned_eta_depot or row.system_eta_depot),
            "operational_status": "READY_SIOD" if row.operational_status == "READY" else row.operational_status,
            "delivery_status": delivery_status(row.mt_id),
            "working_time_used": row.working_time_used_minutes,
            "working_time_remaining": row.working_time_remaining_minutes,
            "working_time_limit": row.working_time_limit_minutes,
        }
        for row in rows
    ]


def update_vehicle_states(db: Session, job_id: str, updates: list[dict], *, actor: str = "local-user") -> dict:
    job = _editable_job(db, job_id)
    rows = {row.mt_id: row for row in db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)).all()}
    _, tag_options = _job_mt_tags(db, list(rows.values()))
    # Validate all exclusions before applying any row in this batch.
    for update in updates:
        if "disabled_tag_ids" in update:
            valid = {item["tag_id"] for item in tag_options.get(str(update.get("mt_id")), [])}
            if update["disabled_tag_ids"] is None or not set(update["disabled_tag_ids"]) <= valid:
                raise HTTPException(422, detail={"code": "INVALID_MT_TAGS", "message": "Only this MT's master tags can be disabled."})
    changed = []
    for update in updates:
        row = rows.get(str(update.get("mt_id")))
        if not row:
            raise HTTPException(status_code=404, detail={"code": "MT_NOT_LOADED", "message": f"MT {update.get('mt_id')} is not loaded in this Job."})
        previous_disabled_tags = list(row.disabled_tag_ids or [])
        if "disabled_tag_ids" in update:
            previous_tags = list(row.disabled_tag_ids or [])
            row.disabled_tag_ids = sorted(set(update["disabled_tag_ids"]))
            if previous_tags != row.disabled_tag_ids:
                db.add(ActualVehicleEvent(vehicle_event_id=uuid.uuid4().hex, job_id=job.job_id, mt_id=row.mt_id,
                    event_type="TAG_UPDATE", event_time=datetime.now(timezone.utc), source="USER",
                    details={"before_disabled_tag_ids": previous_tags, "after_disabled_tag_ids": row.disabled_tag_ids, "updated_by": actor}))
            job.updated_at = datetime.now(timezone.utc)
        before = {"effective_eta_depot": _iso(row.effective_eta_depot), "operational_status": row.operational_status}
        if "planned_eta_depot" in update:
            row.planned_eta_depot = datetime.fromisoformat(str(update["planned_eta_depot"]).replace("Z", "+00:00")) if update["planned_eta_depot"] else None
        if "operational_status" in update:
            status = str(update["operational_status"]).strip().upper().replace(" ", "_")
            if status == "READY":
                status = "READY_SIOD"
            if status not in MT_STATUSES:
                raise HTTPException(status_code=400, detail={"code": "INVALID_MT_STATUS", "message": f"Unsupported MT status: {status}."})
            row.operational_status = status
        if "working_time_limit_minutes" in update:
            row.working_time_limit_minutes = max(1, int(update["working_time_limit_minutes"]))
            row.working_time_remaining_minutes = max(0, row.working_time_limit_minutes - row.working_time_used_minutes)
        # Planned ETA is the only user-maintained availability input. Keep the
        # legacy database column empty, but retain it in the schema so existing
        # installations do not need a destructive migration.
        row.user_eta_override = None
        row.effective_eta_depot = row.planned_eta_depot or row.system_eta_depot
        row.updated_by = actor
        after = {"effective_eta_depot": _iso(row.effective_eta_depot), "operational_status": row.operational_status}
        if before != after:
            changed.append({"mt_id": row.mt_id, "before": before, "after": after})
            if row.effective_eta_depot:
                db.add(ActualVehicleEvent(vehicle_event_id=uuid.uuid4().hex, job_id=job.job_id, mt_id=row.mt_id, event_type="ETA_DEPOT_UPDATE", event_time=row.effective_eta_depot, source="USER", details={"before": before, "after": after, "updated_by": actor}))
        if previous_disabled_tags != list(row.disabled_tag_ids or []):
            changed.append({"mt_id": row.mt_id, "before": {"disabled_tag_ids": previous_disabled_tags}, "after": {"disabled_tag_ids": row.disabled_tag_ids}})
    db.commit()
    return {"status": "APPLIED", "changed": changed, "vehicles": list_job_vehicles(db, job.job_id)}


def upsert_bay_configuration(db: Session, depot_id: str, bays: list[dict], durations: list[dict], *, actor: str = "local-user") -> dict:
    if not db.get(MasterDepot, depot_id):
        raise HTTPException(status_code=404, detail={"code": "DEPOT_NOT_FOUND", "message": "Depot was not found."})
    products = {row.product_id: row for row in db.scalars(select(MasterProduct)).all()}
    for payload in bays:
        bay_id = str(payload.get("bay_id") or "").strip()
        if not bay_id:
            raise HTTPException(status_code=400, detail={"code": "BAY_ID_REQUIRED", "message": "bay_id is required."})
        bay = db.scalar(select(MasterLoadingBay).where(MasterLoadingBay.depot_id == depot_id, MasterLoadingBay.bay_id == bay_id))
        if not bay:
            bay = MasterLoadingBay(master_bay_id=uuid.uuid4().hex, depot_id=depot_id, bay_id=bay_id, bay_name=str(payload.get("bay_name") or bay_id))
            db.add(bay)
            db.flush()
        bay.bay_name = str(payload.get("bay_name") or bay_id)
        bay.all_products_allowed = bool(payload.get("all_products_allowed", False))
        bay.operational_start = time.fromisoformat(str(payload.get("operational_start") or "05:00"))
        bay.operational_end = time.fromisoformat(str(payload.get("operational_end") or "22:00"))
        bay.number_of_loading_arms = max(1, int(payload.get("number_of_loading_arms") or 1))
        bay.loading_mode = str(payload.get("loading_mode") or "SEQUENTIAL").upper()
        bay.active_status = str(payload.get("active_status") or "ACTIVE").upper()
        db.execute(delete(LoadingBayProductCompatibility).where(LoadingBayProductCompatibility.master_bay_id == bay.master_bay_id))
        if not bay.all_products_allowed:
            for product_id in payload.get("allowed_products") or []:
                if product_id not in products:
                    raise HTTPException(status_code=422, detail={"code": "PRODUCT_NOT_FOUND", "message": f"Product {product_id} was not found."})
                db.add(LoadingBayProductCompatibility(master_bay_id=bay.master_bay_id, product_id=product_id))
    for payload in durations:
        product_id = str(payload.get("product_id") or "")
        if product_id not in products:
            raise HTTPException(status_code=422, detail={"code": "PRODUCT_NOT_FOUND", "message": f"Product {product_id} was not found."})
        row = db.scalar(select(ProductCompartmentLoadingDuration).where(ProductCompartmentLoadingDuration.depot_id == depot_id, ProductCompartmentLoadingDuration.product_id == product_id))
        if not row:
            row = ProductCompartmentLoadingDuration(loading_duration_id=uuid.uuid4().hex, depot_id=depot_id, product_id=product_id)
            db.add(row)
        row.duration_minutes_per_compartment = max(1, int(payload.get("duration_minutes_per_compartment") or 0))
        row.active_status = "ACTIVE"
    db.commit()
    return get_bay_configuration(db, depot_id)


def delete_bay_configuration(db: Session, depot_id: str, bay_id: str) -> dict:
    if not db.get(MasterDepot, depot_id):
        raise HTTPException(status_code=404, detail={"code": "DEPOT_NOT_FOUND", "message": "Depot was not found."})
    bay = db.scalar(
        select(MasterLoadingBay).where(
            MasterLoadingBay.depot_id == depot_id,
            (MasterLoadingBay.master_bay_id == bay_id) | (MasterLoadingBay.bay_id == bay_id),
            MasterLoadingBay.active_status != "DELETED",
        )
    )
    if not bay:
        raise HTTPException(status_code=404, detail={"code": "BAY_NOT_FOUND", "message": "Loading bay was not found."})
    bay.active_status = "DELETED"
    db.execute(delete(LoadingBayProductCompatibility).where(LoadingBayProductCompatibility.master_bay_id == bay.master_bay_id))
    db.execute(delete(ActualBayState).where(ActualBayState.master_bay_id == bay.master_bay_id))
    db.execute(delete(OptimizationInitialQueue).where(OptimizationInitialQueue.master_bay_id == bay.master_bay_id))
    db.commit()
    return {"master_bay_id": bay.master_bay_id, "bay_id": bay.bay_id, "status": "DELETED"}


def get_bay_configuration(db: Session, depot_id: str) -> dict:
    bays = db.scalars(select(MasterLoadingBay).where(MasterLoadingBay.depot_id == depot_id, MasterLoadingBay.active_status != "DELETED").order_by(MasterLoadingBay.bay_id)).all()
    bay_ids = [row.master_bay_id for row in bays]
    compat: dict[str, list[str]] = defaultdict(list)
    if bay_ids:
        for master_bay_id, product_id in db.execute(select(LoadingBayProductCompatibility.master_bay_id, LoadingBayProductCompatibility.product_id).where(LoadingBayProductCompatibility.master_bay_id.in_(bay_ids))).all():
            compat[master_bay_id].append(product_id)
    durations = db.scalars(select(ProductCompartmentLoadingDuration).where(ProductCompartmentLoadingDuration.depot_id == depot_id).order_by(ProductCompartmentLoadingDuration.product_id)).all()
    products = {row.product_id: row.product_name for row in db.scalars(select(MasterProduct)).all()}
    return {
        "depot_id": depot_id,
        "number_of_bays": len([row for row in bays if row.active_status == "ACTIVE"]),
        "bays": [
            {
                "master_bay_id": row.master_bay_id,
                "bay_id": row.bay_id,
                "bay_name": row.bay_name,
                "all_products_allowed": row.all_products_allowed,
                "allowed_products": compat[row.master_bay_id],
                "allowed_product_names": [products.get(product_id, product_id) for product_id in compat[row.master_bay_id]],
                "operational_start": _iso(row.operational_start),
                "operational_end": _iso(row.operational_end),
                "number_of_loading_arms": row.number_of_loading_arms,
                "loading_mode": row.loading_mode,
                "active_status": row.active_status,
            }
            for row in bays
        ],
        "loading_durations": [
            {"loading_duration_id": row.loading_duration_id, "product_id": row.product_id, "product_name": products.get(row.product_id), "duration_minutes_per_compartment": row.duration_minutes_per_compartment, "active_status": row.active_status}
            for row in durations
        ],
    }


def update_actual_bay_state(db: Session, job_id: str, states: list[dict], queue: list[dict], *, actor: str = "local-user") -> dict:
    job = _require_job(db, job_id)
    default_reference_time = _default_bay_state_reference_time(db, job)
    allowed_bays = {row.master_bay_id: row for row in db.scalars(select(MasterLoadingBay).where(MasterLoadingBay.depot_id == job.depot_id)).all()}
    for payload in states:
        bay_id = str(payload.get("master_bay_id") or "")
        if bay_id not in allowed_bays:
            raise HTTPException(status_code=422, detail={"code": "BAY_DEPOT_MISMATCH", "message": "Bay does not belong to the Job depot."})
        state = db.scalar(select(ActualBayState).where(ActualBayState.job_id == job.job_id, ActualBayState.master_bay_id == bay_id))
        if not state:
            state = ActualBayState(actual_bay_state_id=uuid.uuid4().hex, job_id=job.job_id, master_bay_id=bay_id, state_effective_at=default_reference_time)
            db.add(state)
        state.current_vehicle_id = payload.get("current_vehicle_id") or None
        state.current_compartment_id = payload.get("current_compartment_id") or None
        state.current_product_id = payload.get("current_product_id") or None
        state.remaining_loading_minutes = max(0, int(payload.get("remaining_loading_minutes") or 0))
        state.actual_queue_length = max(0, int(payload.get("actual_queue_length") or 0))
        state.state_effective_at = datetime.fromisoformat(str(payload["state_effective_at"]).replace("Z", "+00:00")) if payload.get("state_effective_at") else default_reference_time
        state.source = "USER"
        state.updated_by = actor
    # Queue replacement is an explicit actual-state update scoped to this Job.
    db.execute(delete(OptimizationInitialQueue).where(OptimizationInitialQueue.job_id == job.job_id))
    positions: set[tuple[str, int]] = set()
    for payload in queue:
        bay_id = str(payload.get("master_bay_id") or "")
        position = int(payload.get("queue_position") or 0)
        if bay_id not in allowed_bays or position < 1 or (bay_id, position) in positions:
            raise HTTPException(status_code=422, detail={"code": "INVALID_BAY_QUEUE", "message": "Queue bay/position is invalid or duplicated."})
        positions.add((bay_id, position))
        db.add(
            OptimizationInitialQueue(
                initial_queue_id=uuid.uuid4().hex,
                job_id=job.job_id,
                master_bay_id=bay_id,
                queue_position=position,
                vehicle_id=str(payload["vehicle_id"]),
                compartment_id=payload.get("compartment_id") or None,
                product_id=payload.get("product_id") or None,
                estimated_loading_duration_minutes=max(1, int(payload.get("estimated_loading_duration_minutes") or 1)),
                state_effective_at=datetime.fromisoformat(str(payload["state_effective_at"]).replace("Z", "+00:00")) if payload.get("state_effective_at") else default_reference_time,
            )
        )
    db.commit()
    return get_actual_bay_state(db, job.job_id)


def get_actual_bay_state(db: Session, job_id: str) -> dict:
    job = _require_job(db, job_id)
    config = get_bay_configuration(db, job.depot_id)
    states = db.scalars(select(ActualBayState).where(ActualBayState.job_id == job.job_id)).all()
    queues = db.scalars(select(OptimizationInitialQueue).where(OptimizationInitialQueue.job_id == job.job_id).order_by(OptimizationInitialQueue.master_bay_id, OptimizationInitialQueue.queue_position)).all()
    return {
        "configuration": config,
        "states": [
            {"actual_bay_state_id": row.actual_bay_state_id, "master_bay_id": row.master_bay_id, "current_vehicle_id": row.current_vehicle_id, "current_compartment_id": row.current_compartment_id, "current_product_id": row.current_product_id, "remaining_loading_minutes": row.remaining_loading_minutes, "actual_queue_length": row.actual_queue_length, "state_effective_at": _iso(row.state_effective_at), "source": row.source}
            for row in states
        ],
        "queue": [
            {"initial_queue_id": row.initial_queue_id, "master_bay_id": row.master_bay_id, "queue_position": row.queue_position, "vehicle_id": row.vehicle_id, "compartment_id": row.compartment_id, "product_id": row.product_id, "estimated_loading_duration_minutes": row.estimated_loading_duration_minutes, "state_effective_at": _iso(row.state_effective_at)}
            for row in queues
        ],
    }


def apply_freeze_rules(
    rows: list[LOOperationalState],
    *,
    current_time: datetime,
    freeze_window_minutes: int,
    parameters: dict | None = None,
) -> list[LOOperationalState]:
    parameters = effective_parameters(parameters or {})
    horizon = _utc(current_time) + timedelta(minutes=max(0, freeze_window_minutes))
    frozen_groups: set[tuple[str, int]] = set()
    for row in rows:
        setattr(row, "_soft_freeze_candidate", False)
        if row.status == "DONE":
            row.frozen, row.frozen_reason = True, "DONE"
        elif row.status == "ONGOING":
            row.frozen, row.frozen_reason = True, "ONGOING"
        elif row.status == "PLANNED" and row.planned_gate_out and _utc(row.planned_gate_out) <= horizon:
            if constraint_is_hard(parameters, "freeze_window"):
                row.frozen, row.frozen_reason = True, "FREEZE_WINDOW"
            else:
                row.frozen, row.frozen_reason = False, None
                setattr(row, "_soft_freeze_candidate", constraint_is_soft(parameters, "freeze_window"))
        else:
            row.frozen, row.frozen_reason = False, None
        if row.frozen and row.current_vehicle_id and row.current_trip_number is not None:
            frozen_groups.add((row.current_vehicle_id, row.current_trip_number))
    # A physical trip is an indivisible execution unit; when one LO in it is
    # frozen, retain every LO in the same current trip to avoid changing its load.
    for row in rows:
        if (row.current_vehicle_id, row.current_trip_number) in frozen_groups and not row.frozen:
            row.frozen, row.frozen_reason = True, "FROZEN_TRIP_DEPENDENCY"
    return rows


def _planned_eta_issues(
    vehicles: list[VehicleOperationalState],
    *,
    optimization_reference_time: datetime | None = None,
) -> tuple[list[VehicleOperationalState], list[VehicleOperationalState]]:
    missing = [row for row in vehicles if row.planned_eta_depot is None]
    before_reference = [
        row
        for row in vehicles
        if row.planned_eta_depot is not None
        and optimization_reference_time is not None
        and _utc(row.planned_eta_depot) < _utc(optimization_reference_time)
    ]
    return missing, before_reference


def route_time_limit_recommendation(
    lo_count: int,
    mt_count: int,
    configured_seconds: int,
) -> dict:
    """Return a conservative, explainable routing-search budget suggestion.

    This is intentionally a sizing heuristic, not a solver feasibility claim.
    LO count represents routing nodes while ceil(LO / MT) approximates the
    number of allocation decisions/search depth per available vehicle.  The
    result is rounded to 30-second operational increments.
    """
    normalized_lo_count = max(0, int(lo_count))
    normalized_mt_count = max(0, int(mt_count))
    lo_per_mt = math.ceil(normalized_lo_count / normalized_mt_count) if normalized_mt_count else normalized_lo_count
    raw_seconds = 15 + math.ceil(normalized_lo_count * 0.25) + (10 * lo_per_mt)
    recommended_seconds = max(30, min(3600, math.ceil(raw_seconds / 30) * 30))
    configured = max(1, int(configured_seconds))
    return {
        "lo_count": normalized_lo_count,
        "mt_count": normalized_mt_count,
        "estimated_lo_per_mt": lo_per_mt,
        "configured_seconds": configured,
        "recommended_minimum_seconds": recommended_seconds,
        "below_recommendation": configured < recommended_seconds,
        "requires_confirmation": configured < recommended_seconds,
        "calculation_basis": "round30(15 + 0.25 x LO + 10 x ceil(LO / MT))",
    }


def validate_job(db: Session, job_id: str, parameters: dict | None = None, *, reference_time: datetime | None = None) -> dict:
    job = _require_job(db, job_id)
    ensure_default_parameter_profiles(db)
    parameters = effective_parameters(parameters or {})
    messages: list[dict] = []
    def add(code: str, level: str, message: str) -> None:
        messages.append({"code": code, "level": level, "message": message})
    lo_rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(False))).all()
    depot = db.get(MasterDepot, job.depot_id)
    vehicles = db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)).all()
    road_snapshot = restriction_snapshot(db, job.depot_id, reference_time or _job_day(job, depot)[0]) if depot else {"roads": []}
    if road_snapshot["roads"]:
        if not RestrictedRoadRouter(db).enabled:
            add("GOOGLE_ROUTES_REQUIRED", "BLOCKED", "Restricted roads require a valid Google Routes API key in Google Maps Integration.")
        else:
            add("RESTRICTED_ROADS_ACTIVE", "WARNING", f"{len(road_snapshot['roads'])} restricted road(s) apply. Google Routes will verify geometry and use operator detour waypoints where needed.")
    incomplete_roads = missing_detours(road_snapshot["roads"])
    if incomplete_roads:
        add("RESTRICTED_DETOUR_REQUIRED", "BLOCKED", f"Complete alternative waypoints for {len(incomplete_roads)} active restricted road(s) in Master Restricted Roads.")
    optimizable_lo_count = sum(
        1
        for row in lo_rows
        if row.status == "PLANNED" and not row.frozen and not row.user_cancelled
    )
    available_mt_count = sum(1 for row in vehicles if row.operational_status != "UNAVAILABLE")
    route_limit = route_time_limit_recommendation(
        optimizable_lo_count,
        available_mt_count,
        int(parameters["route_optimization_time_limit"]),
    )
    bays = db.scalars(select(MasterLoadingBay).where(MasterLoadingBay.depot_id == job.depot_id, MasterLoadingBay.active_status == "ACTIVE")).all()
    durations = {row.product_id for row in db.scalars(select(ProductCompartmentLoadingDuration).where(ProductCompartmentLoadingDuration.depot_id == job.depot_id, ProductCompartmentLoadingDuration.active_status == "ACTIVE")).all()}
    if not job.source_prediction_run_id:
        add("PREDICTION_RUN_REQUIRED", "BLOCKED", "Load a completed Phase 6 Prediction Run by Run ID.")
    if not lo_rows:
        cancelled_count = db.scalar(select(func.count()).select_from(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(True))) or 0
        if cancelled_count:
            add("ALL_LO_CANCELLED", "WARNING", "All operational LO were cancelled. The next route version will contain no deliveries.")
        else:
            add("LO_REQUIRED", "BLOCKED", "No Phase 7 LO has been imported.")
    if not vehicles:
        add("MT_REQUIRED", "BLOCKED", "Load MT from the selected depot master data.")
    if not depot or depot.depot_operational_start is None or depot.depot_operational_end is None:
        add("DEPOT_OPERATING_WINDOW_REQUIRED", "BLOCKED", "Master Depot must contain both depot_operational_start and depot_operational_end.")
    if job.depot_operational_start is None or job.depot_operational_end is None:
        add("JOB_DEPOT_OPERATING_WINDOW_REQUIRED", "BLOCKED", "Phase 7 Job is missing its Depot operating-window snapshot.")
    missing_eta, _ = _planned_eta_issues(vehicles)
    if missing_eta:
        add("PLANNED_ETA_DEPOT_REQUIRED", "BLOCKED", f"Planned ETA Depot is required for all {len(missing_eta)} MT before optimization.")
    if any(not row.spbu_id or not db.get(MasterSPBU, row.spbu_id) for row in lo_rows):
        add("SPBU_MAPPING_REQUIRED", "BLOCKED", "One or more LO does not map to canonical SPBU master data.")
    missing_spbu_windows = {
        row.spbu_id
        for row in lo_rows
        if row.spbu_id
        and (spbu := db.get(MasterSPBU, row.spbu_id))
        and (spbu.official_window_start is None or spbu.official_window_end is None)
    }
    if missing_spbu_windows:
        add("SPBU_TIME_WINDOW_REQUIRED", "BLOCKED", f"Master SPBU is missing official_window_start or official_window_end for {len(missing_spbu_windows)} SPBU used by this Job.")
    if any(not row.product_id or not db.get(MasterProduct, row.product_id) for row in lo_rows):
        add("PRODUCT_MAPPING_REQUIRED", "BLOCKED", "One or more LO does not map to canonical product master data.")
    if any(row.vehicle_class is None for row in vehicles) and constraint_rule(parameters, "vehicle_compatibility").get("enabled", True):
        add("VEHICLE_CLASS_REQUIRED", "BLOCKED" if constraint_is_hard(parameters, "vehicle_compatibility") else "WARNING", "Vehicle class is missing on one or more loaded MT.")
    if lo_rows and vehicles:
        spbu_ids = sorted({row.spbu_id for row in lo_rows if row.spbu_id})
        mt_ids = [row.mt_id for row in vehicles]
        mt_tags, spbu_tags, tag_labels = _tags(db, mt_ids, spbu_ids)
        mt_tags, _ = _job_mt_tags(db, vehicles)
        master_mt = {mt_id: db.get(MasterMT, mt_id) for mt_id in mt_ids}
        master_spbu = {spbu_id: db.get(MasterSPBU, spbu_id) for spbu_id in spbu_ids}
        incompatible_los = []
        for lo in lo_rows:
            spbu = master_spbu.get(lo.spbu_id)
            if not spbu:
                continue
            compatible = any(
                vehicle.operational_status != "UNAVAILABLE"
                and master_mt.get(vehicle.mt_id) is not None
                and evaluate_compatibility_entities(
                    master_mt[vehicle.mt_id],
                    spbu,
                    mt_tag_ids=mt_tags[vehicle.mt_id],
                    spbu_tag_ids=spbu_tags[lo.spbu_id],
                    tag_labels=tag_labels,
                    product_id=lo.product_id,
                    vehicle_mode="MT_CAPACITY_LE_SPBU_LIMIT",
                )["compatible"]
                for vehicle in vehicles
            )
            if not compatible:
                incompatible_los.append(lo.loading_order_id)
        if incompatible_los and constraint_rule(parameters, "vehicle_compatibility").get("enabled", True):
            add("NO_COMPATIBLE_MT", "BLOCKED" if constraint_is_hard(parameters, "vehicle_compatibility") else "WARNING", f"No loaded active MT passes canonical vehicle-class/tag compatibility for {len(incompatible_los)} LO.")
    if any(not row.compartment_configuration or sum(float(item.get("capacity_kl") or 0) for item in row.compartment_configuration) + 1e-9 < row.capacity_kl for row in vehicles):
        compartment_hard = constraint_is_hard(parameters, "compartment_capacity") or constraint_is_hard(parameters, "compartment_product_separation")
        compartment_enabled = constraint_rule(parameters, "compartment_capacity").get("enabled", True) or constraint_rule(parameters, "compartment_product_separation").get("enabled", True)
        if compartment_enabled:
            add("COMPARTMENT_CONFIGURATION_INVALID", "BLOCKED" if compartment_hard else "WARNING", "MT compartment configuration is missing or does not cover total capacity.")
    if not bays:
        add("BAY_CONFIGURATION_REQUIRED", "BLOCKED", "Configure at least one active loading bay for the depot.")
    if bays and any(not bay.all_products_allowed and not db.scalar(select(func.count()).select_from(LoadingBayProductCompatibility).where(LoadingBayProductCompatibility.master_bay_id == bay.master_bay_id)) for bay in bays) and constraint_rule(parameters, "bay_product_compatibility").get("enabled", True):
        add("BAY_PRODUCT_COMPATIBILITY_REQUIRED", "BLOCKED" if constraint_is_hard(parameters, "bay_product_compatibility") else "WARNING", "Every restricted bay needs at least one allowed product.")
    required_products = {row.product_id for row in lo_rows if row.product_id}
    missing_durations = required_products - durations
    if missing_durations:
        add("LOADING_DURATION_REQUIRED", "BLOCKED", f"Per-compartment loading duration is missing for {len(missing_durations)} product(s).")
    active_profiles = db.scalars(select(OptimizationParameterProfile).where(OptimizationParameterProfile.is_active.is_(True))).all()
    if not active_profiles:
        add("PARAMETER_PROFILE_REQUIRED", "BLOCKED", "At least one valid active optimization parameter profile is required.")
    else:
        try:
            for profile in active_profiles:
                _profile_payload(db, profile)
        except (TypeError, ValueError) as exc:
            add("PARAMETER_PROFILE_INVALID", "BLOCKED", f"An active parameter profile is invalid: {exc}")
    routes_config = get_google_routes_configuration(db)
    if not routes_config or not routes_config.encrypted_api_key:
        add("GOOGLE_ROUTES_NOT_CONFIGURED", "WARNING", "Google Routes API is not configured; cached/master Haversine fallback will be used and marked in the audit.")
    if route_limit["below_recommendation"]:
        add(
            "ROUTE_TIME_LIMIT_BELOW_RECOMMENDATION",
            "WARNING",
            (
                f"Route Time Limit is {route_limit['configured_seconds']} seconds; the rough minimum for "
                f"{route_limit['lo_count']} optimizable LO and {route_limit['mt_count']} available MT is "
                f"{route_limit['recommended_minimum_seconds']} seconds. Increase the parameter or explicitly "
                "confirm the shorter search budget before optimization."
            ),
        )
    if not messages:
        add("VALIDATION_READY", "READY", "All pre-optimization requirements are complete.")
    status = "BLOCKED" if any(row["level"] == "BLOCKED" for row in messages) else "WARNING" if any(row["level"] == "WARNING" for row in messages) else "READY"
    job.status = "READY" if status in {"READY", "WARNING"} and job.status == "DRAFT" else job.status
    db.commit()
    return {
        "status": status,
        "messages": messages,
        "route_time_limit_recommendation": route_limit,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _tags(db: Session, mt_ids: list[str], spbu_ids: list[str]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    mt_tags: dict[str, set[str]] = defaultdict(set)
    spbu_tags: dict[str, set[str]] = defaultdict(set)
    tag_ids: set[str] = set()
    if mt_ids:
        for entity_id, tag_id in db.execute(select(BridgeMTTag.mt_id, BridgeMTTag.tag_id).where(BridgeMTTag.mt_id.in_(mt_ids))).all():
            mt_tags[entity_id].add(tag_id)
            tag_ids.add(tag_id)
    if spbu_ids:
        for entity_id, tag_id in db.execute(select(BridgeSPBUTag.spbu_id, BridgeSPBUTag.tag_id).where(BridgeSPBUTag.spbu_id.in_(spbu_ids))).all():
            spbu_tags[entity_id].add(tag_id)
            tag_ids.add(tag_id)
    labels = {row.tag_id: row.tag_value for row in db.scalars(select(MasterTag).where(MasterTag.tag_id.in_(tag_ids))).all()} if tag_ids else {}
    return mt_tags, spbu_tags, labels


def _solver_inputs(db: Session, job: OptimizationJob, parameters: dict, *, current_time: datetime, reroute: bool) -> dict:
    depot = db.get(MasterDepot, job.depot_id)
    assert depot is not None
    day_start, operational_start, operational_end = _job_day(job, depot)
    rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(False)).order_by(LOOperationalState.loading_order_id)).all()
    if reroute:
        apply_freeze_rules(
            rows,
            current_time=current_time,
            freeze_window_minutes=int(parameters["freeze_window_minutes"]),
            parameters=parameters,
        )
    else:
        for row in rows:
            row.frozen = row.status in {"ONGOING", "DONE"}
            row.frozen_reason = row.status if row.frozen else None
    vehicle_rows = db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)).all()
    working_time_limit = constraint_limit_minutes(parameters, "vehicle_working_time")
    for row in vehicle_rows:
        row.working_time_limit_minutes = working_time_limit
        # Pre-run validation guarantees this value exists and is not earlier
        # than the dispatcher-selected optimization reference time.
        row.effective_eta_depot = row.planned_eta_depot
    vehicle_by_id = {row.mt_id: row for row in vehicle_rows}

    # Executed/current trips are copied into the next immutable version.  A
    # future trip inside the hard freeze window is different: its assignment
    # and sequence remain locked, but it must pass through route/bay scheduling
    # again so the dispatcher-provided MT availability can recalculate time.
    executed_trip_keys = {
        (row.current_vehicle_id, int(row.current_trip_number))
        for row in rows
        if row.status in {"DONE", "ONGOING"}
        and row.current_vehicle_id
        and row.current_trip_number is not None
    }
    ongoing_trip_keys = {
        (row.current_vehicle_id, int(row.current_trip_number))
        for row in rows
        if row.status == "ONGOING"
        and row.current_vehicle_id
        and row.current_trip_number is not None
    }
    copy_frozen_loading_order_ids = {
        row.loading_order_id
        for row in rows
        if row.status in {"DONE", "ONGOING"}
        or (
            row.current_vehicle_id
            and row.current_trip_number is not None
            and (row.current_vehicle_id, int(row.current_trip_number)) in executed_trip_keys
        )
    }
    future_frozen_groups = {
        (row.current_vehicle_id, int(row.current_trip_number))
        for row in rows
        if row.frozen
        and row.status == "PLANNED"
        and row.current_vehicle_id
        and row.current_trip_number is not None
        and (row.current_vehicle_id, int(row.current_trip_number)) not in executed_trip_keys
    }
    departure_tolerance = int(parameters.get("departure_time_tolerance_minutes", 5))
    for vehicle_id, trip_number in future_frozen_groups:
        group_rows = [
            row for row in rows
            if row.current_vehicle_id == vehicle_id and row.current_trip_number == trip_number
        ]
        planned_gate_outs = [_utc(row.planned_gate_out) for row in group_rows if row.planned_gate_out]
        vehicle = vehicle_by_id.get(str(vehicle_id))
        actual_availability = _utc(vehicle.planned_eta_depot) if vehicle and vehicle.planned_eta_depot else None
        latest_allowed_arrival = (
            min(planned_gate_outs) + timedelta(minutes=departure_tolerance)
            if planned_gate_outs else None
        )
        mt_is_late = bool(
            vehicle is None
            or vehicle.operational_status == "UNAVAILABLE"
            or (actual_availability and latest_allowed_arrival and actual_availability > latest_allowed_arrival)
        )
        for row in group_rows:
            if mt_is_late:
                row.frozen = False
                row.frozen_reason = None
                setattr(row, "_reroute_release_reason", "MT_LATE")
            else:
                setattr(row, "_reroute_assignment_locked", True)

    # VehicleOperationalState is also used as the MT Management summary, but
    # a previous Route Version contains both executed and future work.  Only
    # DONE/ONGOING physical trips consume the retained working-time budget in
    # a reroute; future trips must be calculated again by the new solver run.
    retained_working_minutes_by_mt: dict[str, int] = defaultdict(int)
    if reroute and job.current_route_version_id and executed_trip_keys:
        current_trips = db.scalars(
            select(RouteVersionTrip).where(
                RouteVersionTrip.route_version_id == job.current_route_version_id
            )
        ).all()
        for trip in current_trips:
            trip_key = (trip.vehicle_id, int(trip.trip_number))
            if trip_key not in executed_trip_keys:
                continue
            effective_return = _utc(trip.estimated_return_depot)
            if trip_key in ongoing_trip_keys:
                vehicle = vehicle_by_id.get(trip.vehicle_id)
                if vehicle and vehicle.planned_eta_depot:
                    effective_return = max(_utc(vehicle.planned_eta_depot), _utc(trip.gate_out))
            working_start = trip.queue_start or trip.loading_start or trip.vehicle_ready_at_depot
            retained_working_minutes_by_mt[trip.vehicle_id] += max(
                0,
                round((effective_return - _utc(working_start)).total_seconds() / 60),
            )
    for row in vehicle_rows:
        row.working_time_used_minutes = retained_working_minutes_by_mt[row.mt_id]
        row.working_time_remaining_minutes = max(
            0,
            working_time_limit - row.working_time_used_minutes,
        )

    optimizable = [
        row for row in rows
        if row.status == "PLANNED"
        and (not row.frozen or bool(getattr(row, "_reroute_assignment_locked", False)))
        and not row.user_cancelled
    ]
    mts = {row.mt_id: db.get(MasterMT, row.mt_id) for row in vehicle_rows}
    spbu_ids = sorted({row.spbu_id for row in optimizable})
    spbus = {spbu_id: db.get(MasterSPBU, spbu_id) for spbu_id in spbu_ids}
    mt_tags, spbu_tags, labels = _tags(db, list(mts), spbu_ids)
    mt_tags, _ = _job_mt_tags(db, vehicle_rows)
    historical_affinity: dict[tuple[str, str], tuple[datetime, float]] = {}
    if spbu_ids and mts:
        for row in db.scalars(
            select(FactSPBUMTPair).where(
                FactSPBUMTPair.depot_id == job.depot_id,
                FactSPBUMTPair.spbu_id.in_(spbu_ids),
                FactSPBUMTPair.mt_id.in_(list(mts)),
                FactSPBUMTPair.analysis_end_date < job.operating_date,
            )
        ).all():
            key = (row.spbu_id, row.mt_id)
            calculated = _utc(row.calculated_at) if row.calculated_at else datetime.min.replace(tzinfo=timezone.utc)
            if key not in historical_affinity or calculated > historical_affinity[key][0]:
                historical_affinity[key] = (calculated, float(row.probability_mt_given_spbu or 0))
    historical_pairing: dict[tuple[str, str], tuple[datetime, float]] = {}
    if spbu_ids:
        for row in db.scalars(
            select(FactSPBUPair).where(
                FactSPBUPair.depot_id == job.depot_id,
                FactSPBUPair.spbu_a_id.in_(spbu_ids),
                FactSPBUPair.spbu_b_id.in_(spbu_ids),
                FactSPBUPair.analysis_end_date < job.operating_date,
            )
        ).all():
            key = tuple(sorted((row.spbu_a_id, row.spbu_b_id)))
            calculated = _utc(row.calculated_at) if row.calculated_at else datetime.min.replace(tzinfo=timezone.utc)
            if key not in historical_pairing or calculated > historical_pairing[key][0]:
                historical_pairing[key] = (calculated, float(row.support or 0))
    latest_assignment_by_lo: dict[str, RouteVersionLOAssignment] = {}
    current_bay_by_trip: dict[str, str] = {}
    if job.current_route_version_id:
        latest_assignment_by_lo = {
            row.loading_order_id: row
            for row in db.scalars(
                select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == job.current_route_version_id)
            ).all()
        }
        current_bay_by_trip = {
            row.route_version_trip_id: row.master_bay_id
            for row in db.scalars(
                select(OptimizationBayAssignment).where(
                    OptimizationBayAssignment.route_version_id == job.current_route_version_id
                )
            ).all()
        }
    # A frozen trip is copied into the next immutable version. New solver
    # rounds for the same physical MT must therefore continue after its highest
    # frozen trip number, otherwise the new version would contain duplicate
    # (vehicle, trip_number) identities.
    completed_trip_count_by_mt: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.loading_order_id in copy_frozen_loading_order_ids and row.current_vehicle_id and row.current_trip_number is not None:
            completed_trip_count_by_mt[row.current_vehicle_id] = max(
                completed_trip_count_by_mt[row.current_vehicle_id],
                int(row.current_trip_number),
            )
    lo_payload = []
    for matrix_node_index, row in enumerate(optimizable, start=1):
        spbu = spbus[row.spbu_id]
        allowed = []
        violations_by_vehicle: dict[str, list[str]] = {}
        for vehicle in vehicle_rows:
            mt = mts[vehicle.mt_id]
            compatibility = evaluate_compatibility_entities(
                mt,
                spbu,
                mt_tag_ids=mt_tags[vehicle.mt_id],
                spbu_tag_ids=spbu_tags[row.spbu_id],
                tag_labels=labels,
                product_id=row.product_id,
                vehicle_mode="MT_CAPACITY_LE_SPBU_LIMIT",
            )
            violations = []
            if not compatibility["compatible"]:
                violations.append("vehicle_compatibility")
            if float(vehicle.capacity_kl) + 1e-9 < float(row.volume_kl):
                violations.append("vehicle_capacity")
            if vehicle.operational_status == "UNAVAILABLE":
                violations.append("vehicle_availability")
            violations_by_vehicle[vehicle.mt_id] = violations
            if any(constraint_is_hard(parameters, constraint_id) for constraint_id in violations):
                continue
            allowed.append(vehicle.mt_id)
        if bool(getattr(row, "_reroute_assignment_locked", False)):
            # Preserve the hard freeze contract beyond the first route solve.
            # Post-bay repair consumes this same candidate list and therefore
            # must not silently reassign an on-time frozen trip to another MT.
            allowed = [row.current_vehicle_id] if row.current_vehicle_id in allowed else []
        start_minutes, end_minutes = None, None
        if spbu and spbu.official_window_start and spbu.official_window_end:
            zone = _timezone(depot)
            start = datetime.combine(job.operating_date, spbu.official_window_start, tzinfo=zone).astimezone(timezone.utc)
            end = datetime.combine(job.operating_date, spbu.official_window_end, tzinfo=zone).astimezone(timezone.utc)
            if end <= start:
                end += timedelta(days=1)
            start_minutes = max(0, round((start - day_start).total_seconds() / 60))
            end_minutes = max(start_minutes, round((end - day_start).total_seconds() / 60))
        lo_payload.append(
            {
                "matrix_node_index": matrix_node_index,
                "loading_order_id": row.loading_order_id,
                "spbu_id": row.spbu_id,
                "product_id": row.product_id,
                "product_name": row.product_name_snapshot,
                "volume_kl": row.volume_kl,
                "phase6_predicted_shipment_id": row.phase6_predicted_shipment_id,
                "phase6_predicted_vehicle_id": row.phase6_predicted_vehicle_id,
                "phase6_pairing": row.phase6_predicted_spbu_pairing,
                "historical_mt_affinity": {
                    mt_id: historical_affinity.get((row.spbu_id, mt_id), (datetime.min.replace(tzinfo=timezone.utc), 0))[1]
                    for mt_id in allowed
                },
                "historical_pairing_scores": {
                    other_spbu_id: historical_pairing.get(tuple(sorted((row.spbu_id, other_spbu_id))), (datetime.min.replace(tzinfo=timezone.utc), 0))[1]
                    for other_spbu_id in spbu_ids if other_spbu_id != row.spbu_id
                },
                "current_vehicle_id": row.current_vehicle_id,
                "current_trip_number": row.current_trip_number,
                "current_shipment_id": row.current_shipment_id,
                "current_stop_sequence": latest_assignment_by_lo[row.loading_order_id].stop_sequence if row.loading_order_id in latest_assignment_by_lo else None,
                "current_bay_id": current_bay_by_trip.get(latest_assignment_by_lo[row.loading_order_id].route_version_trip_id) if row.loading_order_id in latest_assignment_by_lo and latest_assignment_by_lo[row.loading_order_id].route_version_trip_id else None,
                "current_planned_gate_out_minutes": (
                    round((_utc(row.planned_gate_out) - day_start).total_seconds() / 60)
                    if row.planned_gate_out else None
                ),
                "allowed_vehicle_ids": allowed,
                "constraint_violations_by_vehicle": violations_by_vehicle,
                "time_window_start_minutes": start_minutes,
                "time_window_end_minutes": end_minutes,
                "mandatory": True,
                "user_cancelled": row.user_cancelled,
                "freeze_window_candidate": bool(getattr(row, "_soft_freeze_candidate", False)),
                "reroute_assignment_locked": bool(getattr(row, "_reroute_assignment_locked", False)),
                "reroute_release_reason": getattr(row, "_reroute_release_reason", None),
            }
        )
    vehicles = [
        {
            "mt_id": row.mt_id,
            "registration": row.registration_snapshot,
            "vehicle_class": row.vehicle_class,
            "tags": sorted(labels[tag_id] for tag_id in mt_tags[row.mt_id]),
            "capacity_kl": row.capacity_kl,
            "compartments": row.compartment_configuration,
            "availability_eta_depot": _utc(row.planned_eta_depot),
            "effective_eta_depot": _utc(row.planned_eta_depot),
            "optimization_reference_time": _utc(current_time),
            "depot_operational_start": operational_start,
            "operational_status": "READY_SIOD" if row.operational_status == "READY" else row.operational_status,
            "working_time_limit_minutes": row.working_time_limit_minutes,
            "working_time_used_minutes": row.working_time_used_minutes,
            "working_time_remaining_minutes": row.working_time_remaining_minutes,
            "completed_trip_count": completed_trip_count_by_mt[row.mt_id],
        }
        for row in vehicle_rows
    ]
    bay_config = get_bay_configuration(db, job.depot_id)
    bays = []
    zone = _timezone(depot)
    for row in bay_config["bays"]:
        if row["active_status"] != "ACTIVE":
            continue
        bay_open = datetime.combine(job.operating_date, time.fromisoformat(str(row["operational_start"])), tzinfo=zone).astimezone(timezone.utc)
        bay_close = datetime.combine(job.operating_date, time.fromisoformat(str(row["operational_end"])), tzinfo=zone).astimezone(timezone.utc)
        if bay_close <= bay_open:
            bay_close += timedelta(days=1)
        bays.append({
            "master_bay_id": row["master_bay_id"],
            "all_products_allowed": row["all_products_allowed"],
            "allowed_product_ids": row["allowed_products"],
            "number_of_loading_arms": row["number_of_loading_arms"],
            "loading_mode": row["loading_mode"],
            "operational_start_minutes": max(0, round((bay_open - day_start).total_seconds() / 60)),
            "operational_end_minutes": max(0, round((bay_close - day_start).total_seconds() / 60)),
        })
    actual = db.scalars(select(ActualBayState).where(ActualBayState.job_id == job.job_id)).all()
    queue = db.scalars(select(OptimizationInitialQueue).where(OptimizationInitialQueue.job_id == job.job_id)).all()
    spbu_reservations = []
    if job.current_route_version_id and ongoing_trip_keys:
        for trip in db.scalars(select(RouteVersionTrip).where(RouteVersionTrip.route_version_id == job.current_route_version_id)).all():
            if (trip.vehicle_id, int(trip.trip_number)) not in ongoing_trip_keys:
                continue
            active_ids = {row.loading_order_id for row in rows if row.current_vehicle_id == trip.vehicle_id and row.current_trip_number == trip.trip_number and row.status != "DONE"}
            visit_meta = {item["sequence"]: item for item in ((trip.cost_breakdown or {}).get("trip_timing") or {}).get("spbu_visits", [])}
            for stop in db.scalars(select(RouteVersionStop).where(RouteVersionStop.route_version_trip_id == trip.route_version_trip_id)).all():
                if not stop.spbu_id or not stop.arrival_time or not stop.departure_time or not (set(stop.loading_order_ids or []) & active_ids):
                    continue
                meta = visit_meta.get(stop.sequence_number)
                start = _utc(trip.gate_out) + timedelta(seconds=meta["unloading_start_offset_seconds"]) if meta else _utc(stop.arrival_time)
                end = _utc(stop.departure_time)
                if end > _utc(current_time):
                    spbu_reservations.append({"spbu_id": stop.spbu_id, "start_seconds": round((start-day_start).total_seconds()), "end_seconds": round((end-day_start).total_seconds()), "source_trip_id": trip.route_version_trip_id})
    return {
        "depot": depot,
        "spbu_reservations": spbu_reservations,
        "day_start": day_start,
        "operational_start": operational_start,
        "operational_end": operational_end,
        "all_lo_rows": rows,
        "loading_orders": lo_payload,
        "vehicles": vehicles,
        "spbus": spbus,
        "bays": bays,
        "actual_bay_states": [{"master_bay_id": row.master_bay_id, "state_effective_at": _utc(current_time), "remaining_loading_minutes": row.remaining_loading_minutes, "actual_queue_length": row.actual_queue_length, "current_vehicle_id": row.current_vehicle_id} for row in actual],
        "initial_queue": [{"master_bay_id": row.master_bay_id, "queue_position": row.queue_position, "vehicle_id": row.vehicle_id, "compartment_id": row.compartment_id, "product_id": row.product_id, "estimated_loading_duration_minutes": row.estimated_loading_duration_minutes, "state_effective_at": _utc(current_time)} for row in queue],
        "loading_durations": {row["product_id"]: row["duration_minutes_per_compartment"] for row in bay_config["loading_durations"] if row["active_status"] == "ACTIVE"},
        "route_warm_start_source": "CURRENT_ROUTE" if reroute and job.current_route_version_id else "PHASE6",
        "route_warm_start_version_id": job.current_route_version_id if reroute else None,
        "copy_frozen_loading_order_ids": sorted(copy_frozen_loading_order_ids),
    }


def _state_snapshot(
    db: Session,
    job: OptimizationJob,
    *,
    reason: str,
    actor: str,
    optimization_reference_time: datetime,
    optimization_timezone: str,
) -> OperationalStateSnapshot:
    lo_rows = list_job_los(db, job.job_id)
    vehicle_rows = list_job_vehicles(db, job.job_id)
    bay = get_actual_bay_state(db, job.job_id)
    current_version = db.get(RouteVersion, job.current_route_version_id) if job.current_route_version_id else None
    audit_events = [
        {
            "event": "OPTIMIZATION_REFERENCE_TIME",
            "reference_time": _iso(optimization_reference_time),
            "timezone": optimization_timezone,
        }
    ]
    if current_version:
        updated_lo = [row for row in lo_rows if (db.get(LOOperationalState, row["lo_state_id"]).updated_at or current_version.created_at) > current_version.created_at]
        updated_vehicle = db.scalars(select(ActualVehicleEvent).where(ActualVehicleEvent.job_id == job.job_id, ActualVehicleEvent.created_at > current_version.created_at)).all()
        if updated_lo:
            counts = Counter(row["status"] for row in updated_lo)
            audit_events.extend({"event": "LO_STATUS_UPDATE", "status": status, "count": count} for status, count in counts.items())
        audit_events.extend({"event": row.event_type, "mt_id": row.mt_id, "details": row.details, "event_time": _iso(row.event_time)} for row in updated_vehicle)
    snapshot = OperationalStateSnapshot(
        state_snapshot_id=uuid.uuid4().hex,
        job_id=job.job_id,
        snapshot_reason=reason,
        captured_by=actor,
        lo_state_snapshot=lo_rows,
        vehicle_state_snapshot=vehicle_rows,
        bay_state_snapshot=bay["states"],
        queue_snapshot=bay["queue"],
        audit_events=audit_events,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _parameter_snapshot(db: Session, job: OptimizationJob, parameters: dict, profile_id: str | None, *, actor: str) -> OptimizationParameterSnapshot:
    profile = db.get(OptimizationParameterProfile, profile_id) if profile_id else None
    serialized = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    snapshot = OptimizationParameterSnapshot(
        parameter_snapshot_id=uuid.uuid4().hex,
        job_id=job.job_id,
        source_profile_id=profile.profile_id if profile else None,
        source_profile_version=profile.version if profile else None,
        effective_parameters=parameters,
        parameter_checksum=hashlib.sha256(serialized.encode()).hexdigest(),
        created_by=actor,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _cost_breakdown(result: dict, vehicles: list[dict], parameters: dict) -> dict:
    used_ids = {trip["vehicle_id"] for trip in result["trips"]}
    vehicle_map = {row["mt_id"]: row for row in vehicles}
    activation = sum(OptimizationCoordinatorService().vrp._vehicle_cost(parameters, vehicle_map[mt_id]) for mt_id in used_ids)
    distance = sum(trip["distance_meters"] for trip in result["trips"]) / 1000 * float(parameters["cost_per_km"])
    operating_hours = sum(trip["operating_minutes"] for trip in result["trips"]) / 60
    operating = operating_hours * float(parameters["cost_per_operating_hour"])
    queue = sum(int(trip.get("queue_minutes") or 0) + float(trip.get("spbu_queue_seconds",0))/60 for trip in result["trips"]) * float(parameters["queue_cost"])
    loading = sum(int(trip.get("loading_minutes") or 0) for trip in result["trips"]) * float(parameters["loading_cost"])
    overtime_minutes = sum(max(0, int(trip["operating_minutes"]) - int(vehicle_map[trip["vehicle_id"]]["working_time_remaining_minutes"])) for trip in result["trips"])
    overtime = overtime_minutes * float(parameters["overtime_cost"])
    unserved = len(result["dropped"]) * constraint_penalty(parameters, "serve_loading_order")
    explicit_constraint_penalties = sum(float(trip.get("constraint_penalty_cost") or 0) for trip in result["trips"])
    penalties = unserved + explicit_constraint_penalties
    total = activation + distance + operating + queue + loading + overtime + penalties
    total_kl = sum(float(row["volume_kl"]) for trip in result["trips"] for row in trip["lo_assignments"])
    total_distance_km = sum(trip["distance_meters"] for trip in result["trips"]) / 1000
    return {
        "vehicle_activation_cost": round(activation, 2),
        "distance_cost": round(distance, 2),
        "operating_time_cost": round(operating, 2),
        "queue_cost": round(queue, 2),
        "loading_cost": round(loading, 2),
        "overtime_cost": round(overtime, 2),
        "penalty_cost": round(penalties, 2),
        "total_cost": round(total, 2),
        "cost_per_mt": round(total / len(used_ids), 2) if used_ids else 0,
        "cost_per_trip": round(total / len(result["trips"]), 2) if result["trips"] else 0,
        "cost_per_km": round(total / total_distance_km, 2) if total_distance_km else 0,
        "cost_per_kl": round(total / total_kl, 2) if total_kl else 0,
        "cost_per_lo": round(total / sum(len(trip["lo_assignments"]) for trip in result["trips"]), 2) if result["trips"] else 0,
    }


def _trip_cost_breakdowns(result: dict, vehicles: list[dict], parameters: dict) -> dict[tuple[str, int], dict]:
    """Return auditable trip-level costs; dropped-LO penalties remain plan-level."""
    vehicle_map = {row["mt_id"]: row for row in vehicles}
    activated: set[str] = set()
    breakdowns: dict[tuple[str, int], dict] = {}
    for trip in sorted(result["trips"], key=lambda row: (row["vehicle_id"], row["trip_number"])):
        vehicle = vehicle_map[trip["vehicle_id"]]
        activation = 0.0
        if trip["vehicle_id"] not in activated:
            activation = float(OptimizationCoordinatorService().vrp._vehicle_cost(parameters, vehicle))
            activated.add(trip["vehicle_id"])
        distance = trip["distance_meters"] / 1000 * float(parameters["cost_per_km"])
        operating = trip["operating_minutes"] / 60 * float(parameters["cost_per_operating_hour"])
        queue = (int(trip.get("queue_minutes") or 0) + float(trip.get("spbu_queue_seconds",0))/60) * float(parameters["queue_cost"])
        loading = int(trip.get("loading_minutes") or 0) * float(parameters["loading_cost"])
        overtime_minutes = max(0, int(trip["operating_minutes"]) - int(vehicle["working_time_remaining_minutes"]))
        overtime = overtime_minutes * float(parameters["overtime_cost"])
        penalty = float(trip.get("constraint_penalty_cost") or 0)
        total = activation + distance + operating + queue + loading + overtime + penalty
        breakdowns[(trip["vehicle_id"], trip["trip_number"])] = {
            "vehicle_activation_cost": round(activation, 2),
            "distance_cost": round(distance, 2),
            "operating_time_cost": round(operating, 2),
            "queue_cost": round(queue, 2),
            "loading_cost": round(loading, 2),
            "overtime_cost": round(overtime, 2),
            "penalty_cost": round(penalty, 2),
            "constraint_violations": trip.get("constraint_violations") or [],
            "total_cost": round(total, 2),
        }
    return breakdowns


def _comparison(db: Session, job: OptimizationJob, result: dict, *, gate_out_tolerance_minutes: int = 5) -> dict:
    previous = db.get(RouteVersion, job.current_route_version_id) if job.current_route_version_id else None
    if not previous:
        return {"baseline": True, "plan_adherence_pct": 100.0, "vehicle_assignment_changes": 0, "shipment_changes": 0, "gate_out_variance_minutes": 0, "gate_out_changes": 0, "route_sequence_changes": 0}
    old = {row.loading_order_id: row for row in db.scalars(select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == previous.route_version_id)).all()}
    changes = 0
    shipment_changes = 0
    route_sequence_changes = 0
    gate_variance = []
    new_count = 0
    for trip in result["trips"]:
        sequence_by_lo = {
            row["loading_order_id"]: stop["sequence"]
            for stop in trip.get("stops") or []
            for row in stop.get("loading_orders") or [stop["loading_order"]]
        }
        for row in trip["lo_assignments"]:
            new_count += 1
            prior = old.get(row["loading_order_id"])
            changes += int(bool(prior and prior.vehicle_id != trip["vehicle_id"]))
            shipment_changes += int(bool(prior and prior.shipment_id != trip["shipment_id"]))
            route_sequence_changes += int(bool(prior and prior.stop_sequence != sequence_by_lo.get(row["loading_order_id"])))
            if prior and prior.planned_gate_out:
                gate_variance.append(abs((_utc(trip["gate_out"]) - _utc(prior.planned_gate_out)).total_seconds()) / 60)
    gate_out_changes = sum(value > gate_out_tolerance_minutes for value in gate_variance)
    change_units = changes + shipment_changes + route_sequence_changes + gate_out_changes
    return {
        "baseline": False,
        "compared_to": previous.version_label,
        "plan_adherence_pct": round(max(0, 1 - change_units / max(1, new_count * 4)) * 100, 2),
        "vehicle_assignment_changes": changes,
        "shipment_changes": shipment_changes,
        "gate_out_variance_minutes": round(sum(gate_variance) / len(gate_variance), 2) if gate_variance else 0,
        "gate_out_changes": gate_out_changes,
        "route_sequence_changes": route_sequence_changes,
    }


def _complete_vehicle_eta_state(
    state: VehicleOperationalState,
    *,
    reroute: bool,
    trips: list[RouteVersionTrip],
    ongoing_trip_keys: set[tuple[str, int]],
) -> datetime | None:
    """Publish the relevant route-version trip return and consume Planned ETA.

    Initial optimization publishes Trip 1. A reroute publishes the calculated
    return of the trip containing an ONGOING LO; when the MT has no ONGOING LO,
    it continues to publish Trip 1 from the new route version. Planned ETA is
    only a solver availability input and is never copied into System ETA.
    """
    calculated_trips = [trip for trip in trips if trip.estimated_return_depot is not None]
    ongoing_trips = [
        trip
        for trip in calculated_trips
        if reroute and (trip.vehicle_id, int(trip.trip_number)) in ongoing_trip_keys
    ]
    selected_trip = (
        max(ongoing_trips, key=lambda trip: (int(trip.trip_number), _utc(trip.gate_out)))
        if ongoing_trips
        else min(
            calculated_trips,
            key=lambda trip: (int(trip.trip_number), _utc(trip.gate_out)),
            default=None,
        )
    )
    system_eta = selected_trip.estimated_return_depot if selected_trip else None

    state.planned_eta_depot = None
    state.user_eta_override = None
    state.system_eta_depot = system_eta
    state.effective_eta_depot = state.system_eta_depot
    return system_eta


def _copy_frozen_plan(
    db: Session,
    job: OptimizationJob,
    version: RouteVersion,
    frozen_rows: list[LOOperationalState],
    *,
    ongoing_return_by_mt: dict[str, datetime] | None = None,
) -> tuple[list[RouteVersionTrip], set[str]]:
    if not job.current_route_version_id or not frozen_rows:
        return [], set()
    previous_assignments = {row.loading_order_id: row for row in db.scalars(select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == job.current_route_version_id)).all()}
    previous_trip_ids = {row.route_version_trip_id for lo in frozen_rows if (row := previous_assignments.get(lo.loading_order_id)) and row.route_version_trip_id}
    ongoing_trip_ids = {
        row.route_version_trip_id
        for lo in frozen_rows
        if lo.status == "ONGOING"
        and (row := previous_assignments.get(lo.loading_order_id))
        and row.route_version_trip_id
    }
    previous_trips = db.scalars(select(RouteVersionTrip).where(RouteVersionTrip.route_version_trip_id.in_(previous_trip_ids))).all() if previous_trip_ids else []
    retained = {row.loading_order_id: row for row in frozen_rows}
    trip_map: dict[str, RouteVersionTrip] = {}
    for old in previous_trips:
        estimated_return_depot = old.estimated_return_depot
        operating_minutes = old.operating_minutes
        cost_breakdown = dict(old.cost_breakdown or {})
        released_ids = sorted(lo_id for lo_id, assignment in previous_assignments.items()
                              if assignment.route_version_trip_id == old.route_version_trip_id and lo_id not in retained)
        if released_ids:
            cost_breakdown["released_loading_order_ids"] = released_ids
        actual_return = (ongoing_return_by_mt or {}).get(old.vehicle_id) if old.route_version_trip_id in ongoing_trip_ids else None
        if actual_return is not None:
            estimated_return_depot = max(_utc(actual_return), _utc(old.gate_out))
            working_start = old.queue_start or old.loading_start or old.vehicle_ready_at_depot
            operating_minutes = max(
                0,
                round((estimated_return_depot - _utc(working_start)).total_seconds() / 60),
            )
            cost_breakdown["actual_state_adjustment"] = {
                "source": "REROUTE_PLANNED_ETA_DEPOT",
                "previous_return_depot": _iso(old.estimated_return_depot),
                "effective_return_depot": _iso(estimated_return_depot),
            }
        new = RouteVersionTrip(
            route_version_trip_id=uuid.uuid4().hex, route_version_id=version.route_version_id, vehicle_id=old.vehicle_id,
            trip_number=old.trip_number, shipment_id=old.shipment_id, vehicle_ready_at_depot=old.vehicle_ready_at_depot,
            queue_start=old.queue_start, loading_start=old.loading_start, loading_finish=old.loading_finish, gate_out=old.gate_out,
            estimated_return_depot=estimated_return_depot, distance_meters=old.distance_meters, driving_seconds=old.driving_seconds,
            service_seconds=old.service_seconds, queue_minutes=old.queue_minutes, loading_minutes=old.loading_minutes,
            operating_minutes=operating_minutes, assignment_status="FROZEN", route_geometry=old.route_geometry,
            route_geometry_source=old.route_geometry_source, cost_breakdown=cost_breakdown,
        )
        db.add(new)
        # SessionLocal disables autoflush and these models use scalar FK ids
        # rather than ORM relationships. Materialize the parent trip before
        # any copied stop, LO assignment, or bay assignment can be flushed.
        db.flush()
        trip_map[old.route_version_trip_id] = new
        for stop in db.scalars(select(RouteVersionStop).where(RouteVersionStop.route_version_trip_id == old.route_version_trip_id)).all():
            kept_ids = [lo_id for lo_id in (stop.loading_order_ids or []) if lo_id in retained]
            removed_ids = set(stop.loading_order_ids or []) - set(kept_ids)
            # Preserve the executed stop's timing and geometry, but do not
            # claim that a manually released LO is still carried on this trip.
            db.add(RouteVersionStop(route_version_stop_id=uuid.uuid4().hex, route_version_trip_id=new.route_version_trip_id, sequence_number=stop.sequence_number, stop_type=stop.stop_type, spbu_id=stop.spbu_id, arrival_time=stop.arrival_time, departure_time=stop.departure_time, service_minutes=stop.service_minutes, distance_from_previous_meters=stop.distance_from_previous_meters, travel_from_previous_seconds=stop.travel_from_previous_seconds, loading_order_ids=kept_ids, products=sorted({retained[lo_id].product_id for lo_id in kept_ids if retained[lo_id].product_id}) if removed_ids else stop.products, volume_kl=sum(retained[lo_id].volume_kl for lo_id in kept_ids) if removed_ids else stop.volume_kl))
        old_bay = db.scalar(
            select(OptimizationBayAssignment).where(
                OptimizationBayAssignment.route_version_trip_id == old.route_version_trip_id
            )
        )
        if old_bay:
            new_bay = OptimizationBayAssignment(
                bay_assignment_id=uuid.uuid4().hex,
                route_version_id=version.route_version_id,
                route_version_trip_id=new.route_version_trip_id,
                master_bay_id=old_bay.master_bay_id,
                vehicle_ready_at_depot=old_bay.vehicle_ready_at_depot,
                queue_start=old_bay.queue_start,
                loading_start=old_bay.loading_start,
                loading_finish=old_bay.loading_finish,
                gate_out=old_bay.gate_out,
                queue_minutes=old_bay.queue_minutes,
                loading_minutes=old_bay.loading_minutes,
            )
            db.add(new_bay)
            # Bay operations have the same scalar-id dependency. Persist the
            # copied bay assignment before adding its operation rows.
            db.flush()
            for operation in db.scalars(
                select(OptimizationBayOperation).where(
                    OptimizationBayOperation.bay_assignment_id == old_bay.bay_assignment_id
                )
            ).all():
                db.add(
                    OptimizationBayOperation(
                        bay_operation_id=uuid.uuid4().hex,
                        bay_assignment_id=new_bay.bay_assignment_id,
                        master_bay_id=operation.master_bay_id,
                        compartment_id=operation.compartment_id,
                        product_id=operation.product_id,
                        loading_start=operation.loading_start,
                        loading_finish=operation.loading_finish,
                        duration_minutes=operation.duration_minutes,
                        loading_mode=operation.loading_mode,
                    )
                )
    copied_ids = set()
    for lo in frozen_rows:
        old = previous_assignments.get(lo.loading_order_id)
        if not old:
            continue
        copied_ids.add(lo.loading_order_id)
        new_trip = trip_map.get(old.route_version_trip_id)
        db.add(RouteVersionLOAssignment(route_version_lo_assignment_id=uuid.uuid4().hex, route_version_id=version.route_version_id, route_version_trip_id=new_trip.route_version_trip_id if new_trip else None, loading_order_id=old.loading_order_id, vehicle_id=old.vehicle_id, trip_number=old.trip_number, shipment_id=old.shipment_id, compartment_id=old.compartment_id, spbu_id=old.spbu_id, product_id=old.product_id, volume_kl=old.volume_kl, stop_sequence=old.stop_sequence, planned_gate_out=old.planned_gate_out, eta=old.eta, frozen=True, assignment_status=lo.status, dropped_reason_code=old.dropped_reason_code, dropped_reason_description=old.dropped_reason_description, phase6_deviation=old.phase6_deviation))
    # Keep the helper transactionally complete so downstream persistence does
    # not inherit unresolved child rows from the frozen-plan copy.
    db.flush()
    return list(trip_map.values()), copied_ids


def _summary(result: dict, all_rows: list[LOOperationalState], frozen_trips: list[RouteVersionTrip], cost: dict) -> dict:
    trips = result["trips"]
    all_trips_count = len(trips) + len(frozen_trips)
    used = {trip["vehicle_id"] for trip in trips} | {trip.vehicle_id for trip in frozen_trips}
    trip_counts = Counter([trip["vehicle_id"] for trip in trips] + [trip.vehicle_id for trip in frozen_trips])
    queue_minutes = [int(trip.get("queue_minutes") or 0) for trip in trips] + [trip.queue_minutes for trip in frozen_trips]
    total_distance = sum(int(trip["distance_meters"]) for trip in trips) + sum(trip.distance_meters for trip in frozen_trips)
    total_operating = sum(int(trip["operating_minutes"]) for trip in trips) + sum(trip.operating_minutes for trip in frozen_trips)
    total_kl = sum(float(row.volume_kl) for row in all_rows)
    planned_kl = sum(float(row["volume_kl"]) for trip in trips for row in trip["lo_assignments"])
    return {
        "total_lo": len(all_rows),
        "done_lo": sum(row.status == "DONE" for row in all_rows),
        "ongoing_lo": sum(row.status == "ONGOING" for row in all_rows),
        "planned_lo": sum(row.status == "PLANNED" for row in all_rows),
        "dropped_lo": len(result["dropped"]),
        "delivered_kl": round(sum(float(row.volume_kl) for row in all_rows if row.status == "DONE"), 3),
        "remaining_kl": round(sum(float(row.volume_kl) for row in all_rows if row.status != "DONE"), 3),
        "planned_kl": round(planned_kl, 3),
        "used_mt": len(used),
        "total_trips": all_trips_count,
        "average_trips_per_mt": round(all_trips_count / len(used), 2) if used else 0,
        "max_trips_per_mt": max(trip_counts.values(), default=0),
        "mt_with_1_trip": sum(value == 1 for value in trip_counts.values()),
        "mt_with_2_trips": sum(value == 2 for value in trip_counts.values()),
        "mt_with_3_plus_trips": sum(value >= 3 for value in trip_counts.values()),
        "fleet_utilization_pct": 0,
        "average_queue_minutes": round(sum(queue_minutes) / len(queue_minutes), 2) if queue_minutes else 0,
        "maximum_queue_minutes": max(queue_minutes, default=0),
        "total_distance_meters": total_distance,
        "spbu_queue_minutes": round((sum(float(trip.get("spbu_queue_seconds",0)) for trip in trips)+sum(float(((trip.cost_breakdown or {}).get("trip_timing") or {}).get("spbu_queue_seconds",0)) for trip in frozen_trips))/60,2),
        "total_travel_time_seconds": sum(int(trip["driving_seconds"]) for trip in trips) + sum(trip.driving_seconds for trip in frozen_trips),
        "total_operating_minutes": total_operating,
        "average_trip_duration_minutes": round(total_operating / all_trips_count, 2) if all_trips_count else 0,
        "total_cost": cost["total_cost"],
        "cost_per_kl": cost["cost_per_kl"],
        "cost_per_trip": cost["cost_per_trip"],
        "total_volume_kl": round(total_kl, 3),
    }


def _set_optimization_stage(
    db: Session,
    run: OptimizationRun,
    *,
    stage: str,
    progress_pct: int,
    metadata: dict | None = None,
    commit: bool = True,
) -> None:
    run.solver_metadata = {
        **(run.solver_metadata or {}),
        **(metadata or {}),
        "stage": stage,
        "progress_pct": max(0, min(100, int(progress_pct))),
        "stage_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if commit:
        db.commit()
    else:
        db.flush()


def recover_interrupted_phase7_optimizations(db: Session) -> int:
    """Fail in-process optimization rows left behind by an API restart."""
    now = datetime.now(timezone.utc)
    runs = db.scalars(select(OptimizationRun).where(OptimizationRun.status == "RUNNING")).all()
    recovered_job_ids: set[str] = set()
    for run in runs:
        run.status = "FAILED"
        run.solver_status = "FAILED"
        run.end_time = now
        run.solve_duration_ms = round((now - _utc(run.start_time)).total_seconds() * 1000) if run.start_time else 0
        run.error_code = "PHASE7_PROCESS_INTERRUPTED"
        run.error_message = "The API process stopped before Phase 7 optimization completed. Retry the optimization."
        _set_optimization_stage(db, run, stage="INTERRUPTED", progress_pct=100, commit=False)
        recovered_job_ids.add(run.job_id)
    calculating_jobs = db.scalars(select(OptimizationJob).where(OptimizationJob.status == "CALCULATING")).all()
    for job in calculating_jobs:
        job.status = "FAILED"
        job.error_message = "The previous Phase 7 optimization was interrupted by an API restart. Retry the optimization."
        recovered_job_ids.add(job.job_id)
    if runs or calculating_jobs:
        db.commit()
    return len(recovered_job_ids)


def _prepare_optimization(
    db: Session,
    job_id: str,
    payload: dict,
    *,
    reroute: bool,
    allow_calculating: bool = False,
    lock_job: bool = False,
) -> dict:
    if lock_job:
        job = db.scalar(
            select(OptimizationJob)
            .where(OptimizationJob.job_id == job_id)
            .with_for_update()
        )
        if not job:
            job = db.scalar(
                select(OptimizationJob)
                .where(OptimizationJob.job_no == job_id)
                .with_for_update()
            )
        if not job:
            raise HTTPException(status_code=404, detail={"code": "PHASE7_JOB_NOT_FOUND", "message": "Phase 7 Job was not found."})
    else:
        job = _require_job(db, job_id)
    if job.status == "CALCULATING" and not allow_calculating:
        raise HTTPException(status_code=409, detail={"code": "OPTIMIZATION_ALREADY_RUNNING", "message": "This Job is already calculating."})
    if not reroute and job.current_route_version_id:
        raise HTTPException(status_code=409, detail={"code": "INITIAL_OPTIMIZATION_ALREADY_COMPLETED", "message": "Initial optimization already exists. Use Re-Optimize Now to create the next immutable version."})
    if reroute and not job.current_route_version_id:
        raise HTTPException(status_code=409, detail={"code": "INITIAL_PLAN_REQUIRED", "message": "Run initial optimization before rerouting."})
    depot = db.get(MasterDepot, job.depot_id)
    initial_reference_time, latest_reference_time = _optimization_reference_context(db, job)
    current_time = _normalize_optimization_reference_time(
        job,
        depot,
        payload.get("current_time"),
        reroute=reroute,
        initial_reference_time=initial_reference_time,
        latest_reference_time=latest_reference_time,
    )
    current_lo_rows = db.scalars(select(LOOperationalState).where(LOOperationalState.job_id == job.job_id, LOOperationalState.user_cancelled.is_(False))).all()
    if current_lo_rows and all(row.status == "DONE" for row in current_lo_rows):
        job.status = "CLOSED"
        job.closed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={"code": "ALL_LO_DONE", "message": "All LO are DONE. The Job is closed and no new operational plan was created."},
        )
    vehicle_rows = db.scalars(
        select(VehicleOperationalState)
        .where(VehicleOperationalState.job_id == job.job_id)
        .order_by(VehicleOperationalState.registration_snapshot, VehicleOperationalState.mt_id)
    ).all()
    missing_planned_eta, early_planned_eta = _planned_eta_issues(
        vehicle_rows,
        optimization_reference_time=current_time,
    )
    if missing_planned_eta or early_planned_eta:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PLANNED_ETA_DEPOT_INVALID",
                "message": (
                    "Every MT must have Planned ETA Depot at or after the selected optimization time. "
                    "A Planned ETA equal to the optimization time is valid."
                ),
                "optimization_reference_time": _iso(current_time),
                "missing_mt": [
                    {"mt_id": row.mt_id, "registration": row.registration_snapshot}
                    for row in missing_planned_eta
                ],
                "before_optimization_mt": [
                    {
                        "mt_id": row.mt_id,
                        "registration": row.registration_snapshot,
                        "planned_eta_depot": _iso(row.planned_eta_depot),
                    }
                    for row in early_planned_eta
                ],
            },
        )
    profile_id = payload.get("profile_id")
    profile_parameters = get_parameter_profile(db, profile_id)["parameters"] if profile_id else DEFAULT_PHASE7_PARAMETERS
    try:
        parameters = effective_parameters({**profile_parameters, **(payload.get("parameters") or {})})
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PHASE7_PARAMETER", "message": str(exc)}) from exc
    # This snapshot is server-owned; request/profile data cannot disable it.
    parameters["restricted_roads"] = restriction_snapshot(db, job.depot_id, current_time)
    road_router = RestrictedRoadRouter(db)
    parameters["restricted_routing_provider"] = {"provider": "GOOGLE_RESTRICTED_WAYPOINTS", "configuration_version": road_router.configuration_version, "max_attempts_per_pair": road_router.MAX_ATTEMPTS}
    if parameters["restricted_roads"]["roads"] and not road_router.enabled:
        raise HTTPException(status_code=422, detail={"code": "GOOGLE_ROUTES_REQUIRED", "message": "Configure a valid Google Routes API key in Google Maps Integration."})
    validation = validate_job(db, job.job_id, parameters, reference_time=current_time)
    if validation["status"] == "BLOCKED":
        raise HTTPException(status_code=422, detail={"code": "JOB_VALIDATION_BLOCKED", "message": "Phase 7 Job validation is blocked.", "validation": validation})
    route_limit = validation.get("route_time_limit_recommendation") or route_time_limit_recommendation(
        sum(
            1
            for row in current_lo_rows
            if row.status == "PLANNED" and not row.frozen and not row.user_cancelled
        ),
        sum(1 for row in vehicle_rows if row.operational_status != "UNAVAILABLE"),
        int(parameters["route_optimization_time_limit"]),
    )
    if route_limit["requires_confirmation"] and not bool(payload.get("route_time_limit_confirmed")):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ROUTE_TIME_LIMIT_CONFIRMATION_REQUIRED",
                "message": (
                    "Route Time Limit is below the rough minimum calculated from the current LO and MT workload. "
                    "Increase the parameter or explicitly confirm the shorter budget."
                ),
                "route_time_limit_recommendation": route_limit,
            },
        )
    reason = str(payload.get("reason") or ("Reroute" if reroute else "Initial Plan"))
    return {
        "job": job,
        "depot": depot,
        "current_time": current_time,
        "profile_id": profile_id,
        "parameters": parameters,
        "reason": reason,
        "route_time_limit_recommendation": route_limit,
        "route_time_limit_confirmed": bool(payload.get("route_time_limit_confirmed")),
    }


def enqueue_optimization(db: Session, job_id: str, payload: dict, *, reroute: bool) -> dict:
    """Validate and reserve one Job before returning HTTP 202 to the UI."""
    prepared = _prepare_optimization(db, job_id, payload, reroute=reroute, lock_job=True)
    job = prepared["job"]
    _align_bay_state_reference_time(db, job, prepared["current_time"])
    reserved = db.execute(update(OptimizationJob).where(OptimizationJob.job_id == job.job_id, OptimizationJob.status != "CALCULATING").values(status="CALCULATING", error_message=None))
    if reserved.rowcount != 1:
        db.rollback()
        raise HTTPException(409, detail={"code": "OPTIMIZATION_ALREADY_RUNNING", "message": "This Job is already calculating."})
    db.commit()
    return {
        "job_id": job.job_id,
        "job_no": job.job_no,
        "status": job.status,
        "run_type": "REROUTE" if reroute else "INITIAL",
        "optimization_reference_time": _iso(prepared["current_time"]),
        "route_time_limit_recommendation": prepared["route_time_limit_recommendation"],
        "route_time_limit_confirmed": prepared["route_time_limit_confirmed"],
        "message": "Phase 7 optimization was accepted and will continue in the background.",
    }


def run_optimization(
    db: Session,
    job_id: str,
    payload: dict,
    *,
    reroute: bool,
    actor: str = "local-user",
    accepted: bool = False,
) -> dict:
    prepared = _prepare_optimization(
        db,
        job_id,
        payload,
        reroute=reroute,
        allow_calculating=accepted,
    )
    job = prepared["job"]
    depot = prepared["depot"]
    current_time = prepared["current_time"]
    profile_id = prepared["profile_id"]
    parameters = prepared["parameters"]
    reason = prepared["reason"]
    route_limit = prepared["route_time_limit_recommendation"]
    route_limit_confirmed = prepared["route_time_limit_confirmed"]
    _align_bay_state_reference_time(db, job, current_time)
    job.status = "CALCULATING"
    job.error_message = None
    db.commit()
    started = perf_counter()
    optimization_run = None
    try:
        inputs = _solver_inputs(db, job, parameters, current_time=current_time, reroute=reroute)
        parameters["_spbu_reservations"] = inputs.get("spbu_reservations", [])
        parameters.pop("_spbu_first_stop_penalties", None)
        state_snapshot = _state_snapshot(
            db,
            job,
            reason=reason,
            actor=actor,
            optimization_reference_time=current_time,
            optimization_timezone=_timezone(depot).key,
        )
        parameter_snapshot = _parameter_snapshot(db, job, parameters, profile_id, actor=actor)
        optimization_run = OptimizationRun(
            optimization_run_id=uuid.uuid4().hex,
            job_id=job.job_id,
            run_type="REROUTE" if reroute else "INITIAL",
            status="RUNNING",
            state_snapshot_id=state_snapshot.state_snapshot_id,
            parameter_snapshot_id=parameter_snapshot.parameter_snapshot_id,
            optimization_reference_time=current_time,
            start_time=datetime.now(timezone.utc),
            solver_status="PENDING",
            objective=parameters["objective"],
            solver_metadata={
                "stage": "BUILDING_MATRIX",
                "progress_pct": 5,
                "optimization_reference_time": _iso(current_time),
                "optimization_timezone": _timezone(depot).key,
                "restricted_roads": parameters.get("restricted_roads"),
                "route_time_limit_recommendation": route_limit,
                "route_time_limit_confirmed": route_limit_confirmed,
                "route_warm_start_source": inputs["route_warm_start_source"],
                "route_warm_start_version_id": inputs["route_warm_start_version_id"],
                "constraint_summary": {
                    constraint_id: {
                        **constraint_rule(parameters, constraint_id),
                        "effective_penalty": constraint_penalty(parameters, constraint_id),
                    }
                    for constraint_id in CONSTRAINT_DEFINITIONS
                },
            },
        )
        db.add(optimization_run)
        db.flush()
        # Persist the audit snapshots and RUNNING row before any external route
        # call or solver work. A later rollback can then record a durable FAILED
        # outcome instead of losing the run that failed.
        db.commit()
        matrix_service = RouteMatrixService(db, job_id=job.job_id)

        def update_matrix_progress(progress: dict) -> None:
            total_pairs = max(1, int(progress.get("total_unique_pairs") or 0))
            completed_pairs = int(progress.get("completed_unique_pairs") or 0)
            matrix_progress = 5 + round(35 * completed_pairs / total_pairs)
            _set_optimization_stage(
                db,
                optimization_run,
                stage="BUILDING_MATRIX",
                progress_pct=matrix_progress,
                metadata={"route_matrix_progress": progress},
            )

        matrix = matrix_service.build(
            depot=inputs["depot"], loading_orders=inputs["loading_orders"], spbus=inputs["spbus"], departure=max(current_time, inputs["operational_start"]), parameters=parameters,
            progress_callback=update_matrix_progress,
        ) if inputs["loading_orders"] else {"distance_matrix": [[0]], "time_matrix": [[0]], "geometry": {}, "metadata": {"location_count": 1, "pair_count": 0, "cache_hit_count": 0, "google_request_count": 0}}
        # Matrix/cache work is a durable checkpoint. A later solver or result
        # persistence failure must not force the next retry to rebuild it.
        _set_optimization_stage(
            db,
            optimization_run,
            stage="SOLVING_ROUTES",
            progress_pct=45,
            metadata={"route_matrix": matrix["metadata"]},
        )
        solver_parameters = {
            **parameters,
            "route_warm_start_source": inputs["route_warm_start_source"],
            "route_warm_start_version_id": inputs["route_warm_start_version_id"],
        }
        result = OptimizationCoordinatorService().optimize(
            loading_orders=inputs["loading_orders"], vehicles=inputs["vehicles"], distance_matrix=matrix["distance_matrix"],
            time_matrix=matrix["time_matrix"], bays=inputs["bays"], actual_bay_states=inputs["actual_bay_states"],
            initial_queue=inputs["initial_queue"], loading_durations=inputs["loading_durations"], day_start=inputs["day_start"],
            depot_close=inputs["operational_end"], parameters=solver_parameters,
        )
        _set_optimization_stage(
            db,
            optimization_run,
            stage="PERSISTING_RESULT",
            progress_pct=85,
            metadata={"solver": result.get("solver_metadata") or {}},
        )
        end_of_day = _utc(current_time) >= _utc(inputs["operational_end"])
        if end_of_day:
            for row in result["dropped"]:
                row["reason_code"] = "UNSERVED_END_OF_DAY"
                row["reason_description"] = "LO remains unserved because the depot operating time has ended; classify it as DROPPED or CARRY_OVER in the next operational workflow."
        if not inputs["loading_orders"]:
            result["solver_status"] = "FEASIBLE"
        version_number = (db.scalar(select(func.max(RouteVersion.version_number)).where(RouteVersion.job_id == job.job_id)) or 0) + 1
        comparison = _comparison(
            db,
            job,
            result,
            gate_out_tolerance_minutes=int(parameters.get("departure_time_tolerance_minutes", 5)),
        )
        costs = _cost_breakdown(result, inputs["vehicles"], parameters)
        trip_costs = _trip_cost_breakdowns(result, inputs["vehicles"], parameters)
        route_version = RouteVersion(
            route_version_id=uuid.uuid4().hex,
            job_id=job.job_id,
            version_number=version_number,
            version_label=f"V{version_number}",
            created_by=actor,
            reason=reason,
            state_snapshot_id=state_snapshot.state_snapshot_id,
            parameter_snapshot_id=parameter_snapshot.parameter_snapshot_id,
            objective=parameters["objective"],
            solver_status=result["solver_status"],
            objective_value=result["objective_value"],
            cost_snapshot=costs,
            comparison_snapshot=comparison,
        )
        db.add(route_version)
        db.flush()
        copy_frozen_ids = set(inputs["copy_frozen_loading_order_ids"])
        frozen_rows = [row for row in inputs["all_lo_rows"] if row.loading_order_id in copy_frozen_ids]
        ongoing_return_by_mt = {
            row["mt_id"]: row["availability_eta_depot"]
            for row in inputs["vehicles"]
            if row.get("availability_eta_depot") is not None
        }
        frozen_trips, copied_frozen_ids = _copy_frozen_plan(
            db,
            job,
            route_version,
            frozen_rows,
            ongoing_return_by_mt=ongoing_return_by_mt,
        )
        persisted_trips: list[RouteVersionTrip] = []
        roads = parameters.get("restricted_roads", {}).get("roads", [])
        restriction_events = []
        active_frozen_trips = {(row.current_vehicle_id, row.current_trip_number) for row in frozen_rows if row.status != "DONE"}
        for frozen_trip in frozen_trips:
            if (frozen_trip.vehicle_id, frozen_trip.trip_number) not in active_frozen_trips or not roads:
                continue
            conflicts = geometry_conflicts(frozen_trip.route_geometry or [], roads)
            if conflicts or frozen_trip.route_geometry_source not in {"GRAPHHOPPER_RESTRICTED", "GOOGLE_RESTRICTED_WAYPOINTS"}:
                restriction_events.append({"event": "FROZEN_TRIP_RESTRICTION_REVIEW_REQUIRED",
                    "vehicle_id": frozen_trip.vehicle_id, "trip_number": frozen_trip.trip_number,
                    "restricted_road_ids": conflicts,
                    "message": "Frozen/current work was preserved. Review this trip against current road restrictions."})
        if restriction_events:
            state_snapshot.audit_events = [*(state_snapshot.audit_events or []), *restriction_events]
        geometry_started = perf_counter()
        geometry_request_budget = int(parameters.get("route_geometry_google_request_budget", 500))
        geometry_time_limit = int(parameters.get("route_geometry_time_limit_seconds", 120))
        geometry_google_requests = 0
        geometry_cache_hits = 0
        for trip in result["trips"]:
            if roads and _utc(trip["estimated_return_depot"]) > datetime.fromisoformat(parameters["restricted_roads"]["horizon_end"]):
                raise RestrictedRoutingError("RESTRICTED_HORIZON_EXCEEDED", "Trip exceeds the 48-hour restricted-road planning horizon.")
            if roads:
                trip_costs[(trip["vehicle_id"], trip["trip_number"])]["restricted_roads"] = {
                    "checksum": parameters["restricted_roads"]["checksum"], "verified": True,
                    "road_ids": [road["restricted_road_id"] for road in roads],
                }
            ordered_spbus = [
                inputs["spbus"][stop["loading_order"]["spbu_id"]]
                for stop in trip["stops"]
                if stop["loading_order"]["spbu_id"] in inputs["spbus"]
            ]
            geometry = matrix_service.build_route_geometry(
                depot=inputs["depot"],
                ordered_spbus=ordered_spbus,
                departure=trip["gate_out"],
                parameters={
                    **parameters,
                    "route_geometry_google_request_budget": max(0, geometry_request_budget - geometry_google_requests),
                    "route_geometry_time_limit_seconds": max(0, round(geometry_time_limit - (perf_counter() - geometry_started))),
                },
            )
            if roads:
                trip_costs[(trip["vehicle_id"], trip["trip_number"])]["restricted_legs"] = geometry.get("restricted_legs", [])
            geometry_google_requests += int(geometry.get("google_request_count") or 0)
            geometry_cache_hits += int(geometry.get("cache_hit_count") or 0)
            trip_costs[(trip["vehicle_id"], trip["trip_number"])]["trip_timing"] = trip.get("trip_timing", {})
            entity = RouteVersionTrip(
                route_version_trip_id=uuid.uuid4().hex, route_version_id=route_version.route_version_id, vehicle_id=trip["vehicle_id"], trip_number=trip["trip_number"], shipment_id=trip["shipment_id"],
                vehicle_ready_at_depot=trip["vehicle_ready_at_depot"], queue_start=trip.get("queue_start"), loading_start=trip.get("loading_start"), loading_finish=trip.get("loading_finish"), gate_out=trip["gate_out"],
                estimated_return_depot=trip["estimated_return_depot"], distance_meters=trip["distance_meters"], driving_seconds=trip["driving_seconds"], service_seconds=trip["service_seconds"],
                queue_minutes=int(trip.get("queue_minutes") or 0), loading_minutes=int(trip.get("loading_minutes") or 0), operating_minutes=trip["operating_minutes"], assignment_status="PLANNED",
                route_geometry=geometry["route_geometry"], route_geometry_source=geometry["route_geometry_source"], cost_breakdown=trip_costs[(trip["vehicle_id"], trip["trip_number"])],
            )
            db.add(entity)
            db.flush()
            persisted_trips.append(entity)
            lo_by_id = {row["loading_order_id"]: row for row in trip["lo_assignments"]}
            for stop in trip["stops"]:
                stop_los = stop.get("loading_orders") or [stop["loading_order"]]
                db.add(RouteVersionStop(route_version_stop_id=uuid.uuid4().hex, route_version_trip_id=entity.route_version_trip_id, sequence_number=stop["sequence"], stop_type="SPBU", spbu_id=stop["loading_order"]["spbu_id"], arrival_time=stop["arrival"] + (_utc(trip["gate_out"]) - _utc(trip["preliminary_gate_out"])), departure_time=stop["departure"] + (_utc(trip["gate_out"]) - _utc(trip["preliminary_gate_out"])), service_minutes=round((stop["departure"] - stop.get("unloading_start", stop["arrival"])).total_seconds() / 60), distance_from_previous_meters=stop["leg_distance_meters"], travel_from_previous_seconds=stop["leg_seconds"], loading_order_ids=[lo["loading_order_id"] for lo in stop_los], products=sorted({lo.get("product_id") for lo in stop_los if lo.get("product_id")}), volume_kl=sum(float(lo["volume_kl"]) for lo in stop_los)))
                for lo in stop_los:
                    assignment = lo_by_id[lo["loading_order_id"]]
                    phase6_deviation = {"vehicle_changed": bool(lo.get("phase6_predicted_vehicle_id") and lo["phase6_predicted_vehicle_id"] != trip["vehicle_id"]), "shipment_changed": bool(lo.get("phase6_predicted_shipment_id") and lo["phase6_predicted_shipment_id"] != trip["shipment_id"])}
                    db.add(RouteVersionLOAssignment(route_version_lo_assignment_id=uuid.uuid4().hex, route_version_id=route_version.route_version_id, route_version_trip_id=entity.route_version_trip_id, loading_order_id=lo["loading_order_id"], vehicle_id=trip["vehicle_id"], trip_number=trip["trip_number"], shipment_id=trip["shipment_id"], compartment_id=assignment["compartment_id"], spbu_id=lo["spbu_id"], product_id=lo.get("product_id"), volume_kl=lo["volume_kl"], stop_sequence=stop["sequence"], planned_gate_out=trip["gate_out"], eta=stop["arrival"] + (_utc(trip["gate_out"]) - _utc(trip["preliminary_gate_out"])), frozen=bool(lo.get("reroute_assignment_locked", False)), assignment_status="PLANNED", phase6_deviation=phase6_deviation))
                    state = next(row for row in inputs["all_lo_rows"] if row.loading_order_id == lo["loading_order_id"])
                    state.current_vehicle_id = trip["vehicle_id"]
                    state.current_trip_number = trip["trip_number"]
                    state.current_shipment_id = trip["shipment_id"]
                    state.current_compartment_id = assignment["compartment_id"]
                    state.planned_gate_out = trip["gate_out"]
            if trip.get("master_bay_id"):
                bay_assignment = OptimizationBayAssignment(bay_assignment_id=uuid.uuid4().hex, route_version_id=route_version.route_version_id, route_version_trip_id=entity.route_version_trip_id, master_bay_id=trip["master_bay_id"], vehicle_ready_at_depot=trip["vehicle_ready_at_depot"], queue_start=trip["queue_start"], loading_start=trip["loading_start"], loading_finish=trip["loading_finish"], gate_out=trip["gate_out"], queue_minutes=trip["queue_minutes"], loading_minutes=trip["loading_minutes"])
                db.add(bay_assignment)
                db.flush()
                compartment_products = sorted({(row["compartment_id"], row.get("product_id")) for row in trip["lo_assignments"]})
                operation_start = trip["loading_start"]
                for compartment_id, product_id in compartment_products:
                    duration = int(inputs["loading_durations"].get(product_id, 0))
                    operation_finish = operation_start + timedelta(minutes=duration)
                    db.add(OptimizationBayOperation(bay_operation_id=uuid.uuid4().hex, bay_assignment_id=bay_assignment.bay_assignment_id, master_bay_id=trip["master_bay_id"], compartment_id=compartment_id, product_id=product_id, loading_start=operation_start, loading_finish=operation_finish, duration_minutes=duration, loading_mode=parameters["loading_mode"]))
                    if parameters["loading_mode"] == "SEQUENTIAL":
                        operation_start = operation_finish
        for row in result["dropped"]:
            db.add(RouteVersionLOAssignment(route_version_lo_assignment_id=uuid.uuid4().hex, route_version_id=route_version.route_version_id, loading_order_id=row["loading_order_id"], vehicle_id=None, trip_number=None, shipment_id=None, compartment_id=None, spbu_id=row["spbu_id"], product_id=row.get("product_id"), volume_kl=row["volume_kl"], frozen=False, assignment_status="DROPPED", dropped_reason_code=row["reason_code"], dropped_reason_description=row["reason_description"], phase6_deviation={}))
            state = next((item for item in inputs["all_lo_rows"] if item.loading_order_id == row["loading_order_id"]), None)
            if state:
                state.current_vehicle_id = None
                state.current_trip_number = None
                state.current_shipment_id = None
                state.current_compartment_id = None
                state.planned_gate_out = None
        all_version_trips = [*frozen_trips, *persisted_trips]
        trips_by_vehicle: dict[str, list[RouteVersionTrip]] = defaultdict(list)
        for trip in all_version_trips:
            trips_by_vehicle[trip.vehicle_id].append(trip)
        ongoing_trip_keys = {
            (row.current_vehicle_id, int(row.current_trip_number))
            for row in inputs["all_lo_rows"]
            if row.status == "ONGOING"
            and row.current_vehicle_id
            and row.current_trip_number is not None
        }
        executed_trip_keys = {
            (row.current_vehicle_id, int(row.current_trip_number))
            for row in inputs["all_lo_rows"]
            if row.status in {"DONE", "ONGOING"}
            and row.current_vehicle_id
            and row.current_trip_number is not None
        }
        vehicle_rows = {row.mt_id: row for row in db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)).all()}
        for mt_id, state in vehicle_rows.items():
            mt_trips = trips_by_vehicle[mt_id]
            delivered = sum(assignment.volume_kl for assignment in db.scalars(select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == route_version.route_version_id, RouteVersionLOAssignment.vehicle_id == mt_id, RouteVersionLOAssignment.assignment_status != "DROPPED")).all())
            system_eta = _complete_vehicle_eta_state(
                state,
                reroute=reroute,
                trips=mt_trips,
                ongoing_trip_keys=ongoing_trip_keys,
            )
            planned_operating_minutes = sum(trip.operating_minutes for trip in mt_trips)
            used_minutes = sum(
                trip.operating_minutes
                for trip in mt_trips
                if (trip.vehicle_id, int(trip.trip_number)) in executed_trip_keys
            )
            state.working_time_used_minutes = used_minutes
            state.working_time_remaining_minutes = max(0, state.working_time_limit_minutes - state.working_time_used_minutes)
            db.add(RouteVersionVehicleAssignment(route_version_vehicle_assignment_id=uuid.uuid4().hex, route_version_id=route_version.route_version_id, vehicle_id=mt_id, used=bool(mt_trips), trip_count=len(mt_trips), delivered_kl=delivered, total_distance_meters=sum(trip.distance_meters for trip in mt_trips), total_operating_minutes=planned_operating_minutes, working_time_remaining_minutes=state.working_time_remaining_minutes, activation_cost=OptimizationCoordinatorService().vrp._vehicle_cost(parameters, next((row for row in inputs["vehicles"] if row["mt_id"] == mt_id), {"vehicle_class": state.vehicle_class, "tags": state.tag_snapshot})), system_eta_depot=system_eta))
        gateouts = [trip.gate_out for trip in all_version_trips]
        loading_starts = [trip.loading_start for trip in all_version_trips if trip.loading_start]
        route_version.first_gate_out = min(gateouts) if gateouts else None
        route_version.last_gate_out = max(gateouts) if gateouts else None
        depot_operation_start = min(loading_starts) if loading_starts else route_version.first_gate_out
        route_version.depot_dispatch_span_minutes = round((route_version.last_gate_out - depot_operation_start).total_seconds() / 60) if depot_operation_start and route_version.last_gate_out else 0
        route_version.summary_snapshot = _summary(result, inputs["all_lo_rows"], frozen_trips, costs)
        bay_assignments = db.scalars(
            select(OptimizationBayAssignment).where(
                OptimizationBayAssignment.route_version_id == route_version.route_version_id
            )
        ).all()
        bay_load = Counter()
        for assignment in bay_assignments:
            bay_load[assignment.master_bay_id] += assignment.loading_minutes + assignment.queue_minutes
        operating_span_minutes = max(1, round((_utc(inputs["operational_end"]) - _utc(inputs["operational_start"])).total_seconds() / 60))
        bay_capacity_minutes = len(inputs["bays"]) * operating_span_minutes
        total_loading_minutes = sum(assignment.loading_minutes for assignment in bay_assignments)
        queue_length = max(
            len(inputs["initial_queue"]),
            sum(int(row.get("actual_queue_length") or 0) for row in inputs["actual_bay_states"]),
        )
        total_mt = len(inputs["vehicles"])
        available_mt = sum(row.get("operational_status") != "UNAVAILABLE" for row in inputs["vehicles"])
        total_lo = len(inputs["all_lo_rows"])
        route_version.summary_snapshot.update(
            {
                "completion_pct": round(route_version.summary_snapshot["done_lo"] / total_lo * 100, 2) if total_lo else 0,
                "available_mt": available_mt,
                "unused_mt": max(0, total_mt - route_version.summary_snapshot["used_mt"]),
                "fleet_utilization_pct": round(route_version.summary_snapshot["used_mt"] / total_mt * 100, 2) if total_mt else 0,
                "working_time_used_minutes": sum(state.working_time_used_minutes for state in vehicle_rows.values()),
                "working_time_remaining_minutes": sum(state.working_time_remaining_minutes for state in vehicle_rows.values()),
                "average_turnaround_minutes": route_version.summary_snapshot["average_trip_duration_minutes"],
                "queue_length": queue_length,
                "bay_utilization_pct": round(total_loading_minutes / bay_capacity_minutes * 100, 2) if bay_capacity_minutes else 0,
                "bay_idle_minutes": max(0, bay_capacity_minutes - total_loading_minutes),
                "loading_throughput_kl_per_hour": round(route_version.summary_snapshot["planned_kl"] / (total_loading_minutes / 60), 2) if total_loading_minutes else 0,
                "bay_bottleneck": max(bay_load, key=bay_load.get) if bay_load else None,
                "activation_cost": costs["vehicle_activation_cost"],
                "distance_cost": costs["distance_cost"],
                "reroute_number": version_number - 1,
                "lo_reassigned": comparison["vehicle_assignment_changes"],
                "shipment_regrouped": comparison["shipment_changes"],
                "mt_assignment_changes": comparison["vehicle_assignment_changes"],
                "gate_out_changes": comparison["gate_out_changes"],
                "plan_stability_pct": comparison["plan_adherence_pct"],
            }
        )
        optimization_run.route_version_id = route_version.route_version_id
        optimization_run.status = "COMPLETED"
        optimization_run.solver_status = result["solver_status"]
        optimization_run.objective_value = result["objective_value"]
        optimization_run.coordination_iterations = result["coordination_iterations"]
        optimization_run.solver_metadata = {
            **(optimization_run.solver_metadata or {}),
            **result["solver_metadata"],
            "solver": result["solver_metadata"],
            "route_matrix": matrix["metadata"],
            "route_geometry": {
                "google_request_count": geometry_google_requests,
                "cache_hit_count": geometry_cache_hits,
                "request_budget": geometry_request_budget,
                "duration_ms": round((perf_counter() - geometry_started) * 1000),
            },
            "stage": "COMPLETED",
            "progress_pct": 100,
            "stage_updated_at": datetime.now(timezone.utc).isoformat(),
        }
        optimization_run.end_time = datetime.now(timezone.utc)
        optimization_run.solve_duration_ms = round((perf_counter() - started) * 1000)
        job.current_route_version_id = route_version.route_version_id
        job.status = "CLOSED" if end_of_day else "ACTIVE"
        job.closed_at = datetime.now(timezone.utc) if end_of_day else None
        db.commit()
        return get_route_version(db, job.job_id, route_version.route_version_id)
    except Exception as exc:
        db.rollback()
        job = _require_job(db, job_id)
        job.status = "FAILED"
        job.error_message = str(exc)
        if optimization_run:
            run = db.get(OptimizationRun, optimization_run.optimization_run_id)
            if run:
                run.status = "FAILED"
                run.solver_status = "FAILED"
                run.end_time = datetime.now(timezone.utc)
                run.solve_duration_ms = round((perf_counter() - started) * 1000)
                run.error_code = exc.code if isinstance(exc, RestrictedRoutingError) else "PHASE7_OPTIMIZATION_FAILED"
                run.error_message = str(exc)
                run.solver_metadata = {
                    **(run.solver_metadata or {}),
                    "stage": "FAILED",
                    "progress_pct": 100,
                    "stage_updated_at": datetime.now(timezone.utc).isoformat(),
                }
        db.commit()
        logger.exception("Phase 7 optimization failed for job %s", job_id)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail={"code": "PHASE7_OPTIMIZATION_FAILED", "message": str(exc)}) from exc


def _run_optimization_session(job_id: str, payload: dict, *, reroute: bool, actor: str = "local-user") -> None:
    """Run an accepted optimization with an independent database session."""
    with SessionLocal() as db:
        try:
            run_optimization(db, job_id, payload, reroute=reroute, actor=actor, accepted=True)
        except Exception as exc:  # the worker must persist a terminal state instead of leaking CALCULATING
            db.rollback()
            job = db.get(OptimizationJob, job_id)
            if job and job.status == "CALCULATING":
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail)
                else:
                    message = str(detail)
                job.status = "FAILED"
                job.error_message = message
                db.commit()
            logger.exception("Phase 7 background optimization terminated for job %s", job_id)


def run_optimization_background(job_id: str, payload: dict, *, reroute: bool, actor: str = "local-user") -> None:
    # Never run native solver code in the API interpreter: it can retain the
    # GIL even when FastAPI dispatches a background task to a thread.
    from .phase7_worker import supervise_optimization
    supervise_optimization(job_id, payload, reroute=reroute, actor=actor)


def list_route_versions(db: Session, job_id: str) -> list[dict]:
    job = _require_job(db, job_id)
    rows = db.scalars(select(RouteVersion).where(RouteVersion.job_id == job.job_id).order_by(desc(RouteVersion.version_number))).all()
    runs_by_version = {
        run.route_version_id: run
        for run in db.scalars(
            select(OptimizationRun).where(
                OptimizationRun.job_id == job.job_id,
                OptimizationRun.route_version_id.is_not(None),
            )
        ).all()
        if run.route_version_id
    }
    return [{"route_version_id": row.route_version_id, "version_number": row.version_number, "version_label": row.version_label, "created_at": _iso(row.created_at), "created_by": row.created_by, "reason": row.reason, "objective": row.objective, "solver_status": row.solver_status, "objective_value": row.objective_value, "optimization_reference_time": _iso(runs_by_version[row.route_version_id].optimization_reference_time or runs_by_version[row.route_version_id].start_time) if row.route_version_id in runs_by_version else None, "state_snapshot_id": row.state_snapshot_id, "parameter_snapshot_id": row.parameter_snapshot_id, "summary": row.summary_snapshot, "comparison": row.comparison_snapshot} for row in rows]


def _comparison_source_descriptors(db: Session, job: OptimizationJob) -> list[dict]:
    sources: list[dict] = []
    if job.source_prediction_run_id:
        prediction_run = db.get(PredictionRun, job.source_prediction_run_id)
        if prediction_run:
            sources.append(
                {
                    "source_id": "PHASE6",
                    "source_type": "PHASE6",
                    "label": f"Phase 6 · {prediction_run.prediction_run_no}",
                    "prediction_run_id": prediction_run.id,
                    "prediction_run_no": prediction_run.prediction_run_no,
                    "version_number": None,
                    "version_label": None,
                    "created_at": _iso(prediction_run.completed_at or prediction_run.created_at),
                }
            )
    versions = db.scalars(
        select(RouteVersion)
        .where(RouteVersion.job_id == job.job_id)
        .order_by(RouteVersion.version_number)
    ).all()
    sources.extend(
        {
            "source_id": version.route_version_id,
            "source_type": "PHASE7",
            "label": f"Phase 7 · {version.version_label}",
            "prediction_run_id": None,
            "prediction_run_no": None,
            "version_number": version.version_number,
            "version_label": version.version_label,
            "created_at": _iso(version.created_at),
        }
        for version in versions
    )
    return sources


def _phase6_comparison_rows(db: Session, job: OptimizationJob) -> dict[str, dict]:
    if not job.source_prediction_run_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "PHASE6_SOURCE_NOT_LOADED", "message": "Load and lock a Phase 6 Prediction Run before comparing it."},
        )
    shipments = db.scalars(
        select(PredictionShipment).where(PredictionShipment.prediction_run_id == job.source_prediction_run_id)
    ).all()
    shipment_ids = [shipment.id for shipment in shipments]
    lines = db.scalars(
        select(PredictionShipmentLine)
        .where(PredictionShipmentLine.prediction_run_id == job.source_prediction_run_id)
        .order_by(PredictionShipmentLine.loading_order_no)
    ).all()
    assignments = {
        row.prediction_shipment_id: row
        for row in db.scalars(
            select(PredictionAssignment).where(PredictionAssignment.prediction_shipment_id.in_(shipment_ids))
        ).all()
    } if shipment_ids else {}
    trips = {
        row.prediction_shipment_id: row
        for row in db.scalars(
            select(PredictionTrip).where(PredictionTrip.prediction_run_id == job.source_prediction_run_id)
        ).all()
    }
    vehicles = {row.mt_id: row for row in db.scalars(select(MasterMT)).all()}
    spbu_ids = {row.spbu_id for row in lines}
    spbus = {
        row.spbu_id: row
        for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()
    } if spbu_ids else {}
    product_ids = {row.product_id for row in lines if row.product_id}
    products = {
        row.product_id: row
        for row in db.scalars(select(MasterProduct).where(MasterProduct.product_id.in_(product_ids))).all()
    } if product_ids else {}
    shipment_numbers = {shipment.id: shipment.predicted_shipment_id for shipment in shipments}
    result: dict[str, dict] = {}
    for line in lines:
        assignment = assignments.get(line.prediction_shipment_id)
        trip = trips.get(line.prediction_shipment_id)
        vehicle_id = (trip.vehicle_id if trip else None) or (assignment.final_vehicle_id if assignment else None)
        status = (trip.assignment_status if trip else None) or (assignment.assignment_status if assignment else None) or "UNASSIGNED"
        result[line.loading_order_no] = {
            "loading_order_id": line.loading_order_no,
            "spbu_id": line.spbu_id,
            "spbu_name": spbus[line.spbu_id].spbu_name if line.spbu_id in spbus else line.spbu_no or line.spbu_id,
            "product_id": line.product_id,
            "product_name": products[line.product_id].product_name if line.product_id in products else line.product_name or line.product_id,
            "volume_kl": float(line.order_quantity_kl or 0),
            "present": True,
            "mt_id": vehicle_id,
            "mt_registration": vehicles[vehicle_id].vehicle_registration if vehicle_id in vehicles else vehicle_id,
            "trip_number": trip.trip_number if trip else None,
            "shipment_id": shipment_numbers.get(line.prediction_shipment_id),
            "gate_out": trip.predicted_departure_datetime if trip else None,
            "eta_depot": trip.estimated_return_datetime if trip else None,
            "status": status,
            "dropped_reason_code": assignment.unassigned_reason if assignment else None,
        }
    return result


def _route_version_comparison_rows(db: Session, job: OptimizationJob, version_id: str) -> dict[str, dict]:
    version = db.get(RouteVersion, version_id)
    if version is None or version.job_id != job.job_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPARISON_SOURCE_NOT_FOUND", "message": "The selected Phase 7 route version does not belong to this Job."},
        )
    assignments = db.scalars(
        select(RouteVersionLOAssignment)
        .where(RouteVersionLOAssignment.route_version_id == version.route_version_id)
        .order_by(RouteVersionLOAssignment.loading_order_id)
    ).all()
    trip_ids = {row.route_version_trip_id for row in assignments if row.route_version_trip_id}
    trips = {
        row.route_version_trip_id: row
        for row in db.scalars(select(RouteVersionTrip).where(RouteVersionTrip.route_version_trip_id.in_(trip_ids))).all()
    } if trip_ids else {}
    vehicles = {row.mt_id: row for row in db.scalars(select(MasterMT)).all()}
    spbu_ids = {row.spbu_id for row in assignments}
    spbus = {
        row.spbu_id: row
        for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()
    } if spbu_ids else {}
    product_ids = {row.product_id for row in assignments if row.product_id}
    products = {
        row.product_id: row
        for row in db.scalars(select(MasterProduct).where(MasterProduct.product_id.in_(product_ids))).all()
    } if product_ids else {}
    result: dict[str, dict] = {}
    for assignment in assignments:
        trip = trips.get(assignment.route_version_trip_id) if assignment.route_version_trip_id else None
        vehicle_id = assignment.vehicle_id or (trip.vehicle_id if trip else None)
        result[assignment.loading_order_id] = {
            "loading_order_id": assignment.loading_order_id,
            "spbu_id": assignment.spbu_id,
            "spbu_name": spbus[assignment.spbu_id].spbu_name if assignment.spbu_id in spbus else assignment.spbu_id,
            "product_id": assignment.product_id,
            "product_name": products[assignment.product_id].product_name if assignment.product_id in products else assignment.product_id,
            "volume_kl": float(assignment.volume_kl or 0),
            "present": True,
            "mt_id": vehicle_id,
            "mt_registration": vehicles[vehicle_id].vehicle_registration if vehicle_id in vehicles else vehicle_id,
            "trip_number": assignment.trip_number or (trip.trip_number if trip else None),
            "shipment_id": assignment.shipment_id or (trip.shipment_id if trip else None),
            "gate_out": assignment.planned_gate_out or (trip.gate_out if trip else None),
            "eta_depot": trip.estimated_return_depot if trip else None,
            "status": assignment.assignment_status,
            "dropped_reason_code": assignment.dropped_reason_code,
        }
    return result


def _comparison_side_payload(row: dict | None) -> dict:
    if row is None:
        return {
            "present": False,
            "mt_id": None,
            "mt_registration": None,
            "trip_number": None,
            "shipment_id": None,
            "gate_out": None,
            "eta_depot": None,
            "status": "NOT_PRESENT",
            "dropped_reason_code": None,
        }
    return {
        "present": True,
        "mt_id": row["mt_id"],
        "mt_registration": row["mt_registration"],
        "trip_number": row["trip_number"],
        "shipment_id": row["shipment_id"],
        "gate_out": _iso(row["gate_out"]),
        "eta_depot": _iso(row["eta_depot"]),
        "status": row["status"],
        "dropped_reason_code": row["dropped_reason_code"],
    }


def _comparison_delta_minutes(left: datetime | None, right: datetime | None) -> int | None:
    if left is None or right is None:
        return None
    return round((_utc(right) - _utc(left)).total_seconds() / 60)


def get_lo_comparison(db: Session, job_id: str, source_a: str, source_b: str) -> dict:
    job = _require_job(db, job_id)
    if source_a == source_b:
        raise HTTPException(
            status_code=422,
            detail={"code": "COMPARISON_SOURCE_DUPLICATE", "message": "LO List A and LO List B must be different."},
        )
    descriptors = _comparison_source_descriptors(db, job)
    descriptors_by_id = {row["source_id"]: row for row in descriptors}
    missing = [source for source in (source_a, source_b) if source not in descriptors_by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPARISON_SOURCE_NOT_FOUND", "message": f"Comparison source was not found: {', '.join(missing)}."},
        )

    def load(source_id: str) -> dict[str, dict]:
        return _phase6_comparison_rows(db, job) if source_id == "PHASE6" else _route_version_comparison_rows(db, job, source_id)

    rows_a = load(source_a)
    rows_b = load(source_b)
    all_loading_orders = sorted(set(rows_a) | set(rows_b))
    output_rows: list[dict] = []
    same_mt_count = 0
    changed_mt_count = 0
    gate_out_deltas: list[int] = []
    eta_depot_deltas: list[int] = []
    for loading_order_id in all_loading_orders:
        row_a = rows_a.get(loading_order_id)
        row_b = rows_b.get(loading_order_id)
        both_assigned = bool(row_a and row_b and row_a["mt_id"] and row_b["mt_id"])
        mt_changed = bool(both_assigned and row_a["mt_id"] != row_b["mt_id"])
        if both_assigned:
            if mt_changed:
                changed_mt_count += 1
            else:
                same_mt_count += 1
        gate_out_delta = _comparison_delta_minutes(row_a.get("gate_out") if row_a else None, row_b.get("gate_out") if row_b else None)
        eta_depot_delta = _comparison_delta_minutes(row_a.get("eta_depot") if row_a else None, row_b.get("eta_depot") if row_b else None)
        if gate_out_delta is not None and gate_out_delta != 0:
            gate_out_deltas.append(gate_out_delta)
        if eta_depot_delta is not None and eta_depot_delta != 0:
            eta_depot_deltas.append(eta_depot_delta)
        identity = row_a or row_b or {}
        output_rows.append(
            {
                "loading_order_id": loading_order_id,
                "spbu_id": identity.get("spbu_id"),
                "spbu_name": identity.get("spbu_name"),
                "product_id": identity.get("product_id"),
                "product_name": identity.get("product_name"),
                "volume_kl": identity.get("volume_kl", 0),
                "a": _comparison_side_payload(row_a),
                "b": _comparison_side_payload(row_b),
                "mt_changed": mt_changed,
                "gate_out_delta_minutes": gate_out_delta,
                "eta_depot_delta_minutes": eta_depot_delta,
            }
        )

    def assigned_count(rows: dict[str, dict]) -> int:
        return sum(1 for row in rows.values() if row["mt_id"] and row["status"] not in {"DROPPED", "UNASSIGNED"})

    assigned_a = assigned_count(rows_a)
    assigned_b = assigned_count(rows_b)
    comparable_mt = same_mt_count + changed_mt_count
    summary = {
        "total_lo_a": len(rows_a),
        "total_lo_b": len(rows_b),
        "union_lo_count": len(all_loading_orders),
        "common_lo_count": len(set(rows_a) & set(rows_b)),
        "only_a_count": len(set(rows_a) - set(rows_b)),
        "only_b_count": len(set(rows_b) - set(rows_a)),
        "assigned_lo_a": assigned_a,
        "assigned_lo_b": assigned_b,
        "dropped_or_unassigned_a": len(rows_a) - assigned_a,
        "dropped_or_unassigned_b": len(rows_b) - assigned_b,
        "same_mt_count": same_mt_count,
        "changed_mt_count": changed_mt_count,
        "comparable_mt_count": comparable_mt,
        "mt_change_pct": round(changed_mt_count / comparable_mt * 100, 2) if comparable_mt else 0,
        "gate_out_changed_count": len(gate_out_deltas),
        "average_abs_gate_out_delta_minutes": round(sum(abs(value) for value in gate_out_deltas) / len(gate_out_deltas), 2) if gate_out_deltas else 0,
        "eta_depot_changed_count": len(eta_depot_deltas),
        "average_abs_eta_depot_delta_minutes": round(sum(abs(value) for value in eta_depot_deltas) / len(eta_depot_deltas), 2) if eta_depot_deltas else 0,
    }
    return {
        "job_id": job.job_id,
        "available_sources": descriptors,
        "source_a": descriptors_by_id[source_a],
        "source_b": descriptors_by_id[source_b],
        "summary": summary,
        "rows": output_rows,
    }


def _spbu_stop_metadata(trip, sequence):
    meta = next((item for item in ((trip.cost_breakdown or {}).get("trip_timing") or {}).get("spbu_visits", []) if item["sequence"] == sequence), None)
    if not meta:
        return {"spbu_queue_seconds": 0, "unloading_start_time": None}
    return {"spbu_queue_seconds": meta["queue_seconds"], "unloading_start_time": _iso(_utc(trip.gate_out)+timedelta(seconds=meta["unloading_start_offset_seconds"]))}


def get_route_version(db: Session, job_id: str, version_id: str | None = None) -> dict:
    job = _require_job(db, job_id)
    version = _require_version(db, job, version_id)
    trips = db.scalars(select(RouteVersionTrip).where(RouteVersionTrip.route_version_id == version.route_version_id).order_by(RouteVersionTrip.gate_out, RouteVersionTrip.vehicle_id, RouteVersionTrip.trip_number)).all()
    trip_ids = [row.route_version_trip_id for row in trips]
    stops = db.scalars(select(RouteVersionStop).where(RouteVersionStop.route_version_trip_id.in_(trip_ids)).order_by(RouteVersionStop.route_version_trip_id, RouteVersionStop.sequence_number)).all() if trip_ids else []
    assignments = db.scalars(select(RouteVersionLOAssignment).where(RouteVersionLOAssignment.route_version_id == version.route_version_id).order_by(RouteVersionLOAssignment.loading_order_id)).all()
    bays = db.scalars(select(OptimizationBayAssignment).where(OptimizationBayAssignment.route_version_id == version.route_version_id)).all()
    vehicles = {row.mt_id: row for row in db.scalars(select(MasterMT)).all()}
    spbu_ids = {row.spbu_id for row in assignments}
    spbus = {row.spbu_id: row for row in db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all()} if spbu_ids else {}
    product_ids = {row.product_id for row in assignments if row.product_id}
    products = {row.product_id: row for row in db.scalars(select(MasterProduct).where(MasterProduct.product_id.in_(product_ids))).all()} if product_ids else {}
    stops_by_trip: dict[str, list[RouteVersionStop]] = defaultdict(list)
    assignments_by_trip: dict[str, list[RouteVersionLOAssignment]] = defaultdict(list)
    for row in stops:
        stops_by_trip[row.route_version_trip_id].append(row)
    for row in assignments:
        if row.route_version_trip_id:
            assignments_by_trip[row.route_version_trip_id].append(row)
    bay_by_trip = {row.route_version_trip_id: row for row in bays}
    trip_payload = []
    for trip in trips:
        trip_payload.append({"route_version_trip_id": trip.route_version_trip_id, "vehicle_id": trip.vehicle_id, "registration": vehicles[trip.vehicle_id].vehicle_registration if trip.vehicle_id in vehicles else trip.vehicle_id, "trip_number": trip.trip_number, "shipment_id": trip.shipment_id, "vehicle_ready_at_depot": _iso(trip.vehicle_ready_at_depot), "queue_start": _iso(trip.queue_start), "loading_start": _iso(trip.loading_start), "loading_finish": _iso(trip.loading_finish), "gate_out": _iso(trip.gate_out), "return_depot": _iso(trip.estimated_return_depot), "distance_meters": trip.distance_meters, "travel_time_seconds": trip.driving_seconds, "service_seconds": trip.service_seconds, "trip_timing": (trip.cost_breakdown or {}).get("trip_timing"), "queue_minutes": trip.queue_minutes, "loading_minutes": trip.loading_minutes, "operating_minutes": trip.operating_minutes, "assignment_status": trip.assignment_status, "route_geometry": trip.route_geometry, "route_geometry_source": trip.route_geometry_source, "cost_breakdown": trip.cost_breakdown or {}, "bay_assignment": {"master_bay_id": bay_by_trip[trip.route_version_trip_id].master_bay_id, "queue_minutes": bay_by_trip[trip.route_version_trip_id].queue_minutes} if trip.route_version_trip_id in bay_by_trip else None, "stops": [{**_spbu_stop_metadata(trip, row.sequence_number), "sequence": row.sequence_number, "spbu_id": row.spbu_id, "spbu_name": spbus[row.spbu_id].spbu_name if row.spbu_id in spbus else row.spbu_id, "latitude": float(spbus[row.spbu_id].latitude) if row.spbu_id in spbus and spbus[row.spbu_id].latitude is not None else None, "longitude": float(spbus[row.spbu_id].longitude) if row.spbu_id in spbus and spbus[row.spbu_id].longitude is not None else None, "arrival_time": _iso(row.arrival_time), "departure_time": _iso(row.departure_time), "service_minutes": row.service_minutes, "distance_from_previous_meters": row.distance_from_previous_meters, "travel_from_previous_seconds": row.travel_from_previous_seconds, "loading_order_ids": row.loading_order_ids or [], "products": row.products or [], "product_names": [products[product_id].product_name if product_id in products else product_id for product_id in (row.products or []) if product_id], "volume_kl": row.volume_kl} for row in stops_by_trip[trip.route_version_trip_id]], "loading_orders": [{"loading_order_id": row.loading_order_id, "spbu_id": row.spbu_id, "spbu_name": spbus[row.spbu_id].spbu_name if row.spbu_id in spbus else row.spbu_id, "product_id": row.product_id, "product_name": products[row.product_id].product_name if row.product_id in products else row.product_id, "volume_kl": row.volume_kl, "compartment_id": row.compartment_id, "stop_sequence": row.stop_sequence, "eta": _iso(row.eta), "frozen": row.frozen, "status": row.assignment_status, "phase6_deviation": row.phase6_deviation} for row in assignments_by_trip[trip.route_version_trip_id]]})
    dropped = [{"loading_order_id": row.loading_order_id, "spbu_id": row.spbu_id, "spbu": spbus[row.spbu_id].spbu_name if row.spbu_id in spbus else row.spbu_id, "product_id": row.product_id, "product_name": products[row.product_id].product_name if row.product_id in products else row.product_id, "volume_kl": row.volume_kl, "reason_code": row.dropped_reason_code, "reason_description": row.dropped_reason_description, "route_version": version.version_label} for row in assignments if row.assignment_status == "DROPPED"]
    snapshot = db.get(OperationalStateSnapshot, version.state_snapshot_id)
    parameters = db.get(OptimizationParameterSnapshot, version.parameter_snapshot_id)
    optimization_run = db.scalar(select(OptimizationRun).where(OptimizationRun.route_version_id == version.route_version_id))
    first_loading_start = min((trip.loading_start for trip in trips if trip.loading_start), default=None)
    saved_roads = (parameters.effective_parameters if parameters else {}).get("restricted_roads", {})
    road_reference = (optimization_run.optimization_reference_time or optimization_run.start_time) if optimization_run else _job_day(job, db.get(MasterDepot, job.depot_id))[0]
    current_roads = restriction_snapshot(db, job.depot_id, road_reference)
    restriction_status = {
        "snapshot": saved_roads,
        "changed_since_optimization": saved_roads.get("checksum", hashlib.sha256(b"[]").hexdigest()) != current_roads["checksum"],
        "frozen_trip_warnings": [event for event in (snapshot.audit_events or []) if event.get("event") == "FROZEN_TRIP_RESTRICTION_REVIEW_REQUIRED"] if snapshot else [],
    }
    depot_operation_span_minutes = (
        round((version.last_gate_out - first_loading_start).total_seconds() / 60)
        if first_loading_start and version.last_gate_out
        else version.depot_dispatch_span_minutes
    )
    return {"route_version_id": version.route_version_id, "version_number": version.version_number, "version_label": version.version_label, "created_at": _iso(version.created_at), "created_by": version.created_by, "reason": version.reason, "objective": version.objective, "solver_status": version.solver_status, "objective_value": version.objective_value, "optimization_reference_time": _iso(optimization_run.optimization_reference_time or optimization_run.start_time) if optimization_run else None, "first_loading_start": _iso(first_loading_start), "first_gate_out": _iso(version.first_gate_out), "last_gate_out": _iso(version.last_gate_out), "depot_dispatch_span_minutes": depot_operation_span_minutes, "summary": version.summary_snapshot, "cost": version.cost_snapshot, "comparison": version.comparison_snapshot, "audit_events": snapshot.audit_events if snapshot else [], "parameter_snapshot": parameters.effective_parameters if parameters else {}, "parameter_checksum": parameters.parameter_checksum if parameters else None, "restriction_status": restriction_status, "trips": trip_payload, "dropped_lo": dropped}


def get_trip_details(db: Session, job_id: str, version_id: str, trip_id: str) -> dict:
    payload = get_route_version(db, job_id, version_id)
    for trip in payload["trips"]:
        if trip["route_version_trip_id"] == trip_id:
            return trip
    raise HTTPException(status_code=404, detail={"code": "TRIP_NOT_FOUND", "message": "Trip was not found in this route version."})


def get_simulation_data(db: Session, job_id: str, version_id: str | None = None) -> dict:
    version = get_route_version(db, job_id, version_id)
    hourly: dict[str, dict] = defaultdict(lambda: {"gate_out_kl": 0.0, "returning_mt": 0, "returning_capacity_kl": 0.0})
    vehicle_states = {row["mt_id"]: row for row in list_job_vehicles(db, job_id)}
    for trip in version["trips"]:
        gate_hour = _utc(datetime.fromisoformat(trip["gate_out"])).replace(minute=0, second=0, microsecond=0).isoformat()
        hourly[gate_hour]["gate_out_kl"] += sum(float(row["volume_kl"]) for row in trip["loading_orders"])
        return_hour = _utc(datetime.fromisoformat(trip["return_depot"])).replace(minute=0, second=0, microsecond=0).isoformat()
        hourly[return_hour]["returning_mt"] += 1
        hourly[return_hour]["returning_capacity_kl"] += float(vehicle_states.get(trip["vehicle_id"], {}).get("capacity_kl") or 0)
    cumulative = 0.0
    rows = []
    for hour in sorted(hourly):
        cumulative += hourly[hour]["gate_out_kl"]
        rows.append({"hour": hour, **hourly[hour], "cumulative_gate_out_kl": round(cumulative, 3)})
    return {"route_version_id": version["route_version_id"], "version_label": version["version_label"], "hourly": rows, "kpis": version["summary"], "first_loading_start": version["first_loading_start"], "first_gate_out": version["first_gate_out"], "last_gate_out": version["last_gate_out"], "depot_dispatch_span_minutes": version["depot_dispatch_span_minutes"]}


def get_map_route(db: Session, job_id: str, version_id: str | None = None, *, vehicle_id: str | None = None, trip_number: int | None = None) -> dict:
    job = _require_job(db, job_id)
    depot = db.get(MasterDepot, job.depot_id)
    version = get_route_version(db, job_id, version_id)
    trips = [trip for trip in version["trips"] if (not vehicle_id or trip["vehicle_id"] == vehicle_id) and (trip_number is None or trip["trip_number"] == trip_number)]
    return {"route_version_id": version["route_version_id"], "version_label": version["version_label"], "depot": {"depot_id": depot.depot_id if depot else None, "name": depot.depot_name if depot else None, "latitude": depot.latitude if depot else None, "longitude": depot.longitude if depot else None}, "trips": trips, "provider_role": "Google Routes supplies road matrix/geometry only; OR-Tools produces the optimized plan."}


def get_map_road_geometry(
    db: Session,
    job_id: str,
    version_id: str,
    *,
    vehicle_ids: list[str],
    trip_number: int | None = None,
) -> dict:
    """Hydrate page-scoped display geometry without mutating the route version."""
    job = _require_job(db, job_id)
    depot = db.get(MasterDepot, job.depot_id)
    if depot is None:
        raise HTTPException(status_code=404, detail={"code": "DEPOT_NOT_FOUND", "message": "Job depot was not found."})
    if not vehicle_ids:
        raise HTTPException(status_code=422, detail={"code": "VEHICLE_SCOPE_REQUIRED", "message": "At least one MT is required for map geometry."})
    if len(set(vehicle_ids)) > 25:
        raise HTTPException(status_code=422, detail={"code": "MAP_PAGE_TOO_LARGE", "message": "Road geometry can hydrate at most 25 MT per request."})

    version = get_route_version(db, job_id, version_id)
    vehicle_scope = set(vehicle_ids)
    trips = [
        trip for trip in version["trips"]
        if trip["vehicle_id"] in vehicle_scope and (trip_number is None or trip["trip_number"] == trip_number)
    ]
    if len(trips) > 60:
        raise HTTPException(status_code=422, detail={"code": "MAP_TRIP_SCOPE_TOO_LARGE", "message": "Road geometry can hydrate at most 60 trips per request."})

    matrix_service = RouteMatrixService(db, job_id=job_id)
    response_trips = []
    cache_hits = 0
    external_requests = 0
    road_count = 0
    error_codes: set[str] = set()
    started = perf_counter()
    for trip in trips:
        if trip["route_geometry_source"] in {"GRAPHHOPPER_RESTRICTED", "GOOGLE_RESTRICTED_WAYPOINTS"}:
            # Preserve the exact matrix-selected road evidence of this version.
            # Never hydrate it from a current Google/OSRM route or newer rules.
            response_trips.append({"route_version_trip_id": trip["route_version_trip_id"],
                "vehicle_id": trip["vehicle_id"], "trip_number": trip["trip_number"],
                "route_geometry": trip["route_geometry"], "route_geometry_source": trip["route_geometry_source"],
                "road_geometry": True, "cache_hit": True, "error_codes": []})
            road_count += 1
            cache_hits += 1
            continue
        ordered_spbus = []
        for stop in sorted(trip["stops"], key=lambda row: int(row["sequence"])):
            spbu = db.get(MasterSPBU, stop["spbu_id"])
            if spbu:
                ordered_spbus.append(spbu)
        geometry = matrix_service.build_map_road_geometry(
            depot=depot,
            ordered_spbus=ordered_spbus,
            departure=datetime.fromisoformat(trip["gate_out"]),
        )
        cache_hits += int(bool(geometry.get("cache_hit")))
        external_requests += int(geometry.get("external_request_count") or 0)
        error_codes.update(str(code) for code in geometry.get("error_codes") or [])
        road_geometry = bool(geometry.get("road_geometry") and len(geometry.get("route_geometry") or []) >= 2)
        road_count += int(road_geometry)
        response_trips.append({
            "route_version_trip_id": trip["route_version_trip_id"],
            "vehicle_id": trip["vehicle_id"],
            "trip_number": trip["trip_number"],
            "route_geometry": geometry.get("route_geometry") if road_geometry else trip["route_geometry"],
            "route_geometry_source": geometry.get("route_geometry_source") if road_geometry else trip["route_geometry_source"],
            "road_geometry": road_geometry,
            "cache_hit": bool(geometry.get("cache_hit")),
            "error_codes": geometry.get("error_codes") or [],
        })

    fingerprint = hashlib.sha256(
        json.dumps({"version_id": version_id, "vehicle_ids": sorted(vehicle_scope), "trip_number": trip_number}, sort_keys=True).encode()
    ).hexdigest()
    db.add(RouteAPIRequestLog(
        request_log_id=uuid.uuid4().hex,
        job_id=job_id,
        request_type="PHASE7_MAP_ROAD_GEOMETRY",
        provider="ROAD_GEOMETRY_CACHE_GOOGLE_OSRM",
        request_fingerprint=fingerprint,
        requested_pair_count=len(trips),
        cache_hit_count=cache_hits,
        duration_ms=round((perf_counter() - started) * 1000),
        success=road_count == len(trips),
        error_message=",".join(sorted(error_codes)) or None,
    ))
    db.commit()
    return {
        "route_version_id": version["route_version_id"],
        "version_label": version["version_label"],
        "status": "ROAD_GEOMETRY" if road_count == len(trips) else "PARTIAL_ROAD_GEOMETRY",
        "requested_trip_count": len(trips),
        "road_geometry_trip_count": road_count,
        "cache_hit_count": cache_hits,
        "external_request_count": external_requests,
        "error_codes": sorted(error_codes),
        "trips": response_trips,
        "provider_role": "OR-Tools keeps assignment and stop order immutable; Google/history/OSRM only hydrate page-scoped road geometry for display.",
    }


def get_cost_analysis(db: Session, job_id: str, version_id: str | None = None) -> dict:
    version = get_route_version(db, job_id, version_id)
    by_mt: dict[str, dict] = defaultdict(lambda: {"trips": 0, "distance_meters": 0, "operating_minutes": 0, "volume_kl": 0.0})
    by_trip = []
    for trip in version["trips"]:
        volume = sum(float(row["volume_kl"]) for row in trip["loading_orders"])
        row = by_mt[trip["vehicle_id"]]
        row["trips"] += 1
        row["distance_meters"] += trip["distance_meters"]
        row["operating_minutes"] += trip["operating_minutes"]
        row["volume_kl"] += volume
        by_trip.append({"vehicle_id": trip["vehicle_id"], "trip_number": trip["trip_number"], "distance_meters": trip["distance_meters"], "operating_minutes": trip["operating_minutes"], "volume_kl": volume})
    return {"route_version_id": version["route_version_id"], "version_label": version["version_label"], "summary": version["cost"], "per_mt": [{"vehicle_id": key, **value} for key, value in by_mt.items()], "per_trip": by_trip}


def get_dropped_lo(db: Session, job_id: str, version_id: str | None = None) -> dict:
    version = get_route_version(db, job_id, version_id)
    return {"route_version_id": version["route_version_id"], "version_label": version["version_label"], "total": len(version["dropped_lo"]), "rows": version["dropped_lo"]}
