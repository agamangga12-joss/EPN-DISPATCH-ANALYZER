from __future__ import annotations

import hashlib
import math
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import String, case, cast, desc, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from .config import get_settings
from .departure_intelligence import validate_shift_config
from .models import (
    BridgeMTTag,
    DepartureShiftAnalysisConfig,
    FactLoadingOrderLine,
    FactShipment,
    IntegrationAPILog,
    IntegrationClient,
    IntegrationDatasetVersion,
    MLBehavioralModel,
    ManualDispatchJob,
    ManualDispatchTrip,
    ManualDispatchVehicle,
    MasterDepot,
    MasterMT,
    MasterTag,
    OptimizationJob,
    PredictionRun,
    RouteVersion,
    RouteVersionTrip,
    VehicleOperationalState,
)
from .phase10_adapters import (
    Phase7RouteAdapter,
    Phase8RouteAdapter,
    aware_utc,
    depot_timezone,
    local_datetime,
    route_adapter,
    route_detail,
)
from .phase10_auth import (
    DEFAULT_CLIENT_CODE,
    INTEGRATION_NAME,
    IntegrationAPIError,
    generate_integration_token,
    hash_integration_token,
    token_hint,
)


DATASET_NAMES = (
    "terminals",
    "vehicles",
    "historical_operations",
    "route_results",
    "shift_configuration",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timezone_for_name(name: str | None) -> ZoneInfo:
    default_name = get_settings().phase10_default_timezone
    try:
        return ZoneInfo(name or default_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Jakarta")


def total_pages(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


def mark_record_count(request, count: int) -> None:
    request.state.record_count = int(count)


def _latest(*values: datetime | None) -> datetime | None:
    aware = [aware_utc(value) for value in values if value is not None]
    return max(aware) if aware else None


def _dataset_source(db: Session, dataset_name: str) -> tuple[int, datetime | None, date | None]:
    if dataset_name == "terminals":
        count, updated = db.execute(select(func.count(), func.max(MasterDepot.updated_at))).one()
        return int(count or 0), aware_utc(updated), None
    if dataset_name == "vehicles":
        count, updated = db.execute(select(func.count(), func.max(MasterMT.updated_at))).one()
        return int(count or 0), aware_utc(updated), None
    if dataset_name == "historical_operations":
        count, updated, data_until = db.execute(
            select(func.count(), func.max(FactShipment.created_at), func.max(FactShipment.operating_date))
        ).one()
        return int(count or 0), aware_utc(updated), data_until
    if dataset_name == "route_results":
        p7_count, p7_updated = db.execute(select(func.count(), func.max(RouteVersion.created_at))).one()
        p8_count, p8_updated = db.execute(select(func.count(), func.max(ManualDispatchJob.updated_at))).one()
        return int(p7_count or 0) + int(p8_count or 0), _latest(p7_updated, p8_updated), None
    if dataset_name == "shift_configuration":
        saved_count, saved_updated = db.execute(
            select(func.count(), func.max(DepartureShiftAnalysisConfig.updated_at))
        ).one()
        model_count, model_updated = db.execute(
            select(func.count(), func.max(MLBehavioralModel.updated_at)).where(MLBehavioralModel.shift_definition_snapshot.is_not(None))
        ).one()
        return int(saved_count or 0) + int(model_count or 0), _latest(saved_updated, model_updated), None
    raise ValueError(f"Unsupported dataset: {dataset_name}")


def dataset_version(db: Session, dataset_name: str, *, persist: bool = True) -> dict:
    count, updated, data_until = _dataset_source(db, dataset_name)
    signature = f"{dataset_name}|{count}|{updated.isoformat() if updated else '-'}|{data_until or '-'}"
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10].upper()
    version_date = (updated or utc_now()).astimezone(timezone.utc).strftime("%Y%m%d")
    value = f"{version_date}-{count:05d}-{digest}"
    if persist:
        entity = db.scalar(
            select(IntegrationDatasetVersion).where(
                IntegrationDatasetVersion.integration_name == INTEGRATION_NAME,
                IntegrationDatasetVersion.dataset_name == dataset_name,
            )
        )
        if not entity:
            entity = IntegrationDatasetVersion(
                id=uuid.uuid4().hex,
                integration_name=INTEGRATION_NAME,
                dataset_name=dataset_name,
                data_version=value,
                last_updated_at=updated,
            )
        entity.data_version = value
        entity.last_updated_at = updated
        entity.updated_at = utc_now()
        db.add(entity)
    payload: dict[str, Any] = {"data_version": value, "last_updated_at": updated}
    if dataset_name == "historical_operations":
        payload["data_until"] = data_until
    return payload


def metadata(db: Session) -> dict:
    datasets = {name: dataset_version(db, name) for name in DATASET_NAMES}
    db.commit()
    return {
        "system": "dispatcher-optimizer",
        "integration": INTEGRATION_NAME,
        "api_version": "v1",
        "server_time": utc_now().astimezone(timezone_for_name(None)),
        "datasets": datasets,
    }


def terminal_record(row: MasterDepot) -> dict:
    updated = aware_utc(row.updated_at or row.created_at)
    return {
        "terminal_id": row.depot_id,
        "terminal_code": row.depot_code,
        "terminal_name": row.depot_name,
        "terminal_type": None,
        "address": None,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "timezone": row.timezone or get_settings().phase10_default_timezone,
        "active": (row.active_status or "").upper() == "ACTIVE",
        "updated_at": local_datetime(updated, row),
    }


def list_terminals(
    db: Session,
    *,
    active: bool | None,
    updated_since: datetime | None,
    page: int,
    page_size: int,
) -> dict:
    conditions = []
    if active is not None:
        conditions.append(
            func.upper(MasterDepot.active_status) == "ACTIVE"
            if active else func.upper(MasterDepot.active_status) != "ACTIVE"
        )
    if updated_since is not None:
        conditions.append(MasterDepot.updated_at >= aware_utc(updated_since))
    base = select(MasterDepot)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(MasterDepot.depot_name, MasterDepot.depot_id).offset((page - 1) * page_size).limit(page_size)).all()
    version = dataset_version(db, "terminals")
    db.commit()
    return {
        "data_version": version["data_version"],
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "total_pages": total_pages(total, page_size),
        "records": [terminal_record(row) for row in rows],
    }


def get_terminal(db: Session, terminal_id: str) -> dict:
    row = db.get(MasterDepot, terminal_id)
    if not row:
        raise IntegrationAPIError(404, "NOT_FOUND", "Terminal was not found.")
    return terminal_record(row)


def _capacity(row: MasterMT) -> float | None:
    if row.vehicle_type_tag is not None:
        return float(row.vehicle_type_tag)
    if row.capacity_label:
        digits = "".join(char for char in row.capacity_label.replace(",", ".") if char.isdigit() or char == ".")
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return None


def _vehicle_context(db: Session, vehicle_ids: list[str]) -> tuple[dict[str, list[str]], dict[str, VehicleOperationalState]]:
    tags: dict[str, list[str]] = {vehicle_id: [] for vehicle_id in vehicle_ids}
    if vehicle_ids:
        for mt_id, value in db.execute(
            select(BridgeMTTag.mt_id, MasterTag.tag_value)
            .join(MasterTag, MasterTag.tag_id == BridgeMTTag.tag_id)
            .where(BridgeMTTag.mt_id.in_(vehicle_ids), MasterTag.active_status == "ACTIVE")
            .order_by(BridgeMTTag.mt_id, MasterTag.tag_value)
        ).all():
            tags[str(mt_id)].append(str(value))
    states: dict[str, VehicleOperationalState] = {}
    if vehicle_ids:
        for state in db.scalars(
            select(VehicleOperationalState)
            .where(VehicleOperationalState.mt_id.in_(vehicle_ids))
            .order_by(desc(VehicleOperationalState.updated_at))
        ).all():
            states.setdefault(state.mt_id, state)
    return tags, states


def vehicle_record(row: MasterMT, tags: list[str], state: VehicleOperationalState | None) -> dict:
    active = (row.active_status or "").upper() == "ACTIVE"
    raw_status = (state.operational_status if state else "UNKNOWN").upper()
    if not active or raw_status in {"UNAVAILABLE", "MAINTENANCE", "OUT_OF_SERVICE", "INACTIVE"}:
        operational_status = "UNAVAILABLE"
    elif state and raw_status in {"AVAILABLE", "READY", "IDLE"}:
        operational_status = "AVAILABLE"
    else:
        operational_status = "UNKNOWN"
    capacity = _capacity(row)
    compartment_count = row.number_of_compartments
    compartments = []
    if state and state.compartment_configuration:
        for index, item in enumerate(state.compartment_configuration, start=1):
            if not isinstance(item, dict):
                continue
            compartment_number = item.get("compartment_no") or item.get("number") or index
            compartment_capacity = item.get("capacity_kl")
            compartments.append({
                "compartment_no": int(compartment_number),
                "capacity_kl": float(compartment_capacity) if compartment_capacity is not None else None,
            })
    updated = _latest(row.updated_at or row.created_at, state.updated_at if state else None)
    depot = None
    return {
        "mt_id": row.mt_id,
        "terminal_id": row.depot_id,
        "vehicle_code": row.source_mt_id,
        "vehicle_number": row.vehicle_registration,
        "vehicle_class": f"{row.vehicle_type_tag}KL" if row.vehicle_type_tag is not None else row.capacity_label,
        "capacity_kl": capacity,
        "compartment_count": compartment_count,
        "compartments": compartments,
        "vehicle_tags": tags,
        "vehicle_status": row.active_status,
        "operational_status": operational_status,
        "active": active,
        "updated_at": aware_utc(updated),
    }


def list_vehicles(
    db: Session,
    *,
    terminal_id: str | None,
    active: bool | None,
    vehicle_status: str | None,
    updated_since: datetime | None,
    page: int,
    page_size: int,
) -> dict:
    conditions = []
    if terminal_id:
        conditions.append(MasterMT.depot_id == terminal_id)
    if active is not None:
        conditions.append(
            func.upper(MasterMT.active_status) == "ACTIVE"
            if active else func.upper(MasterMT.active_status) != "ACTIVE"
        )
    if vehicle_status:
        conditions.append(func.upper(MasterMT.active_status) == vehicle_status.upper())
    if updated_since is not None:
        conditions.append(MasterMT.updated_at >= aware_utc(updated_since))
    base = select(MasterMT)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(MasterMT.vehicle_registration, MasterMT.mt_id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    tags, states = _vehicle_context(db, [row.mt_id for row in rows])
    version = dataset_version(db, "vehicles")
    db.commit()
    return {
        "data_version": version["data_version"],
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "total_pages": total_pages(total, page_size),
        "records": [vehicle_record(row, tags.get(row.mt_id, []), states.get(row.mt_id)) for row in rows],
    }


def get_vehicle(db: Session, mt_id: str) -> dict:
    row = db.get(MasterMT, mt_id)
    if not row:
        raise IntegrationAPIError(404, "NOT_FOUND", "Vehicle was not found.")
    tags, states = _vehicle_context(db, [mt_id])
    return vehicle_record(row, tags.get(mt_id, []), states.get(mt_id))


def list_historical_operations(
    db: Session,
    *,
    terminal_id: str,
    date_from: date,
    date_to: date,
    mt_id: str | None,
    updated_since: datetime | None,
    page: int,
    page_size: int,
) -> dict:
    if date_from > date_to:
        raise IntegrationAPIError(400, "INVALID_DATE_RANGE", "date_from must not be greater than date_to")
    conditions = [
        FactShipment.depot_id == terminal_id,
        FactShipment.operating_date >= date_from,
        FactShipment.operating_date <= date_to,
    ]
    if mt_id:
        conditions.append(FactShipment.mt_id == mt_id)
    if updated_since:
        timestamp = aware_utc(updated_since)
        conditions.append(
            or_(
                FactShipment.created_at >= timestamp,
                exists(
                    select(literal(1)).where(
                        FactLoadingOrderLine.shipment_id == FactShipment.shipment_id,
                        FactLoadingOrderLine.created_at >= timestamp,
                    )
                ),
            )
        )
    base = select(FactShipment).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    shipments = db.scalars(
        base.order_by(FactShipment.operating_date, FactShipment.shipment_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    shipment_ids = [row.shipment_id for row in shipments]
    lo_rows = db.scalars(
        select(FactLoadingOrderLine)
        .where(FactLoadingOrderLine.shipment_id.in_(shipment_ids))
        .order_by(FactLoadingOrderLine.shipment_id, FactLoadingOrderLine.loading_order_number)
    ).all() if shipment_ids else []
    los_by_shipment: dict[str, list[FactLoadingOrderLine]] = {}
    for row in lo_rows:
        los_by_shipment.setdefault(row.shipment_id, []).append(row)
    depots = {row.depot_id: row for row in db.scalars(select(MasterDepot).where(MasterDepot.depot_id.in_({row.depot_id for row in shipments if row.depot_id}))).all()} if shipments else {}
    records = []
    for shipment in shipments:
        depot = depots.get(shipment.depot_id)
        lines = los_by_shipment.get(shipment.shipment_id, [])
        spbus = []
        for line in lines:
            if line.spbu_id and line.spbu_id not in spbus:
                spbus.append(line.spbu_id)
        gate_out = local_datetime(shipment.gate_out_datetime, depot)
        returned = local_datetime(shipment.shipment_end_datetime, depot)
        duration = None
        if gate_out and returned and returned >= gate_out:
            duration = round((returned - gate_out).total_seconds() / 60)
        updated = _latest(shipment.created_at, *[line.created_at for line in lines])
        records.append({
            "operation_date": shipment.operating_date,
            "terminal_id": shipment.depot_id,
            "mt_id": shipment.mt_id,
            "vehicle_number": shipment.vehicle_registration,
            "shipment_id": shipment.shipment_id,
            "trip_id": f"TRIP:{shipment.shipment_id}",
            "trip_number": 1,
            "gate_out_at": gate_out,
            "returned_to_depot_at": returned,
            "trip_duration_minutes": duration,
            "total_volume_kl": round(sum(float(line.quantity or 0) for line in lines), 3),
            "spbu_count": len(spbus),
            "spbu_ids": spbus,
            "loading_orders": [line.loading_order_number for line in lines],
            "amt1_id": None,
            "amt2_id": None,
            "updated_at": local_datetime(updated, depot),
        })
    version = dataset_version(db, "historical_operations")
    db.commit()
    return {
        "data_version": version["data_version"],
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "total_pages": total_pages(total, page_size),
        "records": records,
    }


def list_routes(
    db: Session,
    *,
    operation_date: date,
    terminal_id: str | None,
    route_source: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> dict:
    p7_trip_counts = (
        select(RouteVersionTrip.route_version_id.label("route_key"), func.count().label("trip_count"), func.count(func.distinct(RouteVersionTrip.vehicle_id)).label("vehicle_count"))
        .group_by(RouteVersionTrip.route_version_id)
        .subquery()
    )
    p8_trip_counts = (
        select(ManualDispatchVehicle.dispatch_job_id.label("route_key"), func.count(ManualDispatchTrip.id).label("trip_count"), func.count(func.distinct(ManualDispatchVehicle.id)).label("vehicle_count"))
        .outerjoin(ManualDispatchTrip, ManualDispatchTrip.dispatch_vehicle_id == ManualDispatchVehicle.id)
        .group_by(ManualDispatchVehicle.dispatch_job_id)
        .subquery()
    )
    p7_status = case(
        (RouteVersion.solver_status.in_(["OPTIMAL", "FEASIBLE", "PARTIAL"]), "COMPLETED"),
        else_=func.upper(RouteVersion.solver_status),
    )
    p8_status = case(
        (ManualDispatchJob.status == "FINALIZED", "COMPLETED"),
        else_=func.upper(ManualDispatchJob.status),
    )
    p7 = (
        select(
            (literal("P7:") + cast(RouteVersion.route_version_id, String)).label("route_id"),
            literal("PHASE_7").label("route_source"),
            RouteVersion.version_label.label("route_version"),
            OptimizationJob.operating_date.label("operation_date"),
            OptimizationJob.depot_id.label("terminal_id"),
            OptimizationJob.job_id.label("job_id"),
            (OptimizationJob.job_name + literal(" · ") + RouteVersion.version_label).label("route_name"),
            p7_status.label("status"),
            func.coalesce(p7_trip_counts.c.vehicle_count, 0).label("vehicle_count"),
            func.coalesce(p7_trip_counts.c.trip_count, 0).label("trip_count"),
            RouteVersion.created_at.label("created_at"),
            RouteVersion.created_at.label("updated_at"),
            MasterDepot.timezone.label("timezone"),
        )
        .join(OptimizationJob, OptimizationJob.job_id == RouteVersion.job_id)
        .outerjoin(p7_trip_counts, p7_trip_counts.c.route_key == RouteVersion.route_version_id)
        .outerjoin(MasterDepot, MasterDepot.depot_id == OptimizationJob.depot_id)
        .where(OptimizationJob.operating_date == operation_date)
    )
    p8 = (
        select(
            (literal("P8:") + cast(ManualDispatchJob.id, String)).label("route_id"),
            literal("PHASE_8").label("route_source"),
            (literal("R") + cast(ManualDispatchJob.dispatch_version, String)).label("route_version"),
            ManualDispatchJob.operational_date.label("operation_date"),
            ManualDispatchJob.depot_id.label("terminal_id"),
            ManualDispatchJob.job_id.label("job_id"),
            ManualDispatchJob.job_name.label("route_name"),
            p8_status.label("status"),
            func.coalesce(p8_trip_counts.c.vehicle_count, 0).label("vehicle_count"),
            func.coalesce(p8_trip_counts.c.trip_count, 0).label("trip_count"),
            ManualDispatchJob.created_at.label("created_at"),
            ManualDispatchJob.updated_at.label("updated_at"),
            MasterDepot.timezone.label("timezone"),
        )
        .outerjoin(p8_trip_counts, p8_trip_counts.c.route_key == ManualDispatchJob.id)
        .outerjoin(MasterDepot, MasterDepot.depot_id == ManualDispatchJob.depot_id)
        .where(ManualDispatchJob.operational_date == operation_date)
    )
    if terminal_id:
        p7 = p7.where(OptimizationJob.depot_id == terminal_id)
        p8 = p8.where(ManualDispatchJob.depot_id == terminal_id)
    if route_source == "PHASE_7":
        combined = p7.subquery()
    elif route_source == "PHASE_8":
        combined = p8.subquery()
    else:
        combined = union_all(p7, p8).subquery()
    query = select(combined)
    if status:
        query = query.where(combined.c.status == status.upper())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(desc(combined.c.updated_at), combined.c.route_source, combined.c.route_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings().all()
    records = []
    for row in rows:
        zone = timezone_for_name(row["timezone"])
        created = aware_utc(row["created_at"])
        updated = aware_utc(row["updated_at"])
        records.append({key: row[key] for key in (
            "route_id", "route_source", "route_version", "operation_date", "terminal_id", "job_id", "route_name", "status", "vehicle_count", "trip_count"
        )} | {
            "created_at": created.astimezone(zone) if created else datetime.combine(operation_date, time.min, tzinfo=zone),
            "updated_at": updated.astimezone(zone) if updated else datetime.combine(operation_date, time.min, tzinfo=zone),
        })
    version = dataset_version(db, "route_results")
    db.commit()
    return {
        "data_version": version["data_version"],
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "total_pages": total_pages(total, page_size),
        "records": records,
    }


def get_route(db: Session, route_id: str) -> dict:
    return route_detail(db, route_id)


def route_vehicles(db: Session, route_id: str, page: int, page_size: int) -> dict:
    detail = route_detail(db, route_id)
    vehicles = detail["vehicles"]
    start = (page - 1) * page_size
    records = [
        {
            "mt_id": row["mt_id"],
            "vehicle_number": row["vehicle_number"],
            "capacity_kl": row["capacity_kl"],
            "initial_available_at": row["initial_available_at"],
            "trip_count": row["trip_count"],
        }
        for row in vehicles[start:start + page_size]
    ]
    return {
        "route_id": route_id,
        "page": page,
        "page_size": page_size,
        "total_records": len(vehicles),
        "total_pages": total_pages(len(vehicles), page_size),
        "records": records,
    }


def _model_for_route(db: Session, route_id: str) -> MLBehavioralModel | None:
    adapter, internal_id = route_adapter(route_id)
    run_id = None
    if adapter is Phase7RouteAdapter:
        version = db.get(RouteVersion, internal_id)
        job = db.get(OptimizationJob, version.job_id) if version else None
        run_id = job.source_prediction_run_id if job else None
    else:
        job = Phase8RouteAdapter._job(db, str(internal_id))
        run_id = job.source_run_id
        if not run_id and job.source_job_id:
            source_job = db.get(OptimizationJob, job.source_job_id)
            run_id = source_job.source_prediction_run_id if source_job else None
    run = db.get(PredictionRun, run_id) if run_id else None
    return db.get(MLBehavioralModel, run.model_id) if run else None


def authoritative_shift_config(
    db: Session,
    terminal_id: str,
    operation_date: date,
    *,
    route_id: str | None = None,
) -> tuple[list[dict], str | None]:
    model = _model_for_route(db, route_id) if route_id else None
    if model and model.depot_id == terminal_id and model.shift_definition_snapshot:
        raw = model.shift_definition_snapshot
        source = f"PHASE_5_MODEL:{model.model_id}"
    else:
        saved = db.scalar(
            select(DepartureShiftAnalysisConfig)
            .where(
                DepartureShiftAnalysisConfig.depot_id == terminal_id,
                DepartureShiftAnalysisConfig.start_date <= operation_date,
                DepartureShiftAnalysisConfig.end_date >= operation_date,
            )
            .order_by(desc(DepartureShiftAnalysisConfig.updated_at))
        )
        if saved and saved.shift_config:
            raw = saved.shift_config
            source = f"PHASE_2_SAVED_CONFIG:{saved.id}"
        else:
            model = db.scalar(
                select(MLBehavioralModel)
                .where(MLBehavioralModel.depot_id == terminal_id)
                .order_by(desc(MLBehavioralModel.updated_at), desc(MLBehavioralModel.created_at))
            )
            raw = model.shift_definition_snapshot if model else []
            source = f"PHASE_5_MODEL:{model.model_id}" if model and raw else None
    if not raw:
        return [], None
    try:
        return validate_shift_config(raw), source
    except HTTPException as exc:
        raise IntegrationAPIError(422, "VALIDATION_ERROR", f"Authoritative shift configuration is invalid: {exc.detail}") from exc


def shift_records(db: Session, terminal_id: str, operation_date: date, *, route_id: str | None = None) -> dict:
    depot = db.get(MasterDepot, terminal_id)
    if not depot:
        raise IntegrationAPIError(404, "NOT_FOUND", "Terminal was not found.")
    shifts, source = authoritative_shift_config(db, terminal_id, operation_date, route_id=route_id)
    zone = depot_timezone(depot)
    records = []
    for shift in shifts:
        start_at = datetime.combine(operation_date, time.fromisoformat(shift["start_time"]), tzinfo=zone)
        end_time = time.fromisoformat(shift["end_time"]).replace(second=59)
        end_at = datetime.combine(operation_date, end_time, tzinfo=zone)
        if end_at < start_at:
            end_at += timedelta(days=1)
        records.append({
            "shift_id": shift["shift_id"],
            "shift_name": shift["name"],
            "start_at": start_at,
            "end_at": end_at,
        })
    version = dataset_version(db, "shift_configuration")
    db.commit()
    return {
        "operation_date": operation_date,
        "terminal_id": terminal_id,
        "data_version": version["data_version"],
        "source": source,
        "records": records,
    }


def calculate_vehicle_availability(vehicle: dict, reference: datetime) -> dict:
    reference_utc = aware_utc(reference)
    initial = aware_utc(vehicle.get("initial_available_at"))
    trips = sorted(vehicle.get("trips") or [], key=lambda row: (aware_utc(row.get("departure_at")) or datetime.max.replace(tzinfo=timezone.utc), row.get("trip_number") or 0))
    invalid = [row for row in trips if row.get("timeline_status") != "VALID"]
    for previous, current in zip(trips, trips[1:]):
        if aware_utc(current.get("departure_at")) < aware_utc(previous.get("return_to_depot_at")):
            invalid.append(current)
    if invalid:
        return {
            "mt_id": vehicle["mt_id"],
            "vehicle_number": vehicle.get("vehicle_number"),
            "capacity_kl": vehicle.get("capacity_kl"),
            "availability_status": "UNKNOWN",
            "availability_reason": "Vehicle timeline is incomplete or invalid for the selected route.",
            "active_trip_id": None,
            "available_at": None,
            "next_available_at": None,
            "next_trip_id": None,
            "next_departure_at": None,
            "handover_window_minutes": None,
        }
    if initial is None:
        return {
            "mt_id": vehicle["mt_id"],
            "vehicle_number": vehicle.get("vehicle_number"),
            "capacity_kl": vehicle.get("capacity_kl"),
            "availability_status": "UNKNOWN",
            "availability_reason": "The selected route has no authoritative initial availability timestamp for this vehicle.",
            "active_trip_id": None,
            "available_at": None,
            "next_available_at": None,
            "next_trip_id": None,
            "next_departure_at": None,
            "handover_window_minutes": None,
        }
    explicit_status = str(vehicle.get("operational_status") or "").upper()
    if explicit_status in {"UNAVAILABLE", "MAINTENANCE", "OUT_OF_SERVICE", "INACTIVE", "BLOCKED"}:
        return {
            "mt_id": vehicle["mt_id"],
            "vehicle_number": vehicle.get("vehicle_number"),
            "capacity_kl": vehicle.get("capacity_kl"),
            "availability_status": "UNAVAILABLE",
            "availability_reason": f"Selected-route vehicle state is {explicit_status}.",
            "active_trip_id": None,
            "available_at": None,
            "next_available_at": initial.astimezone(reference.tzinfo or timezone.utc) if initial > reference_utc else None,
            "next_trip_id": None,
            "next_departure_at": None,
            "handover_window_minutes": None,
        }
    active = next(
        (
            row for row in trips
            if aware_utc(row.get("departure_at")) <= reference_utc < aware_utc(row.get("return_to_depot_at"))
        ),
        None,
    )
    if active:
        active_return = aware_utc(active["return_to_depot_at"])
        upcoming = next((row for row in trips if aware_utc(row["departure_at"]) >= active_return and row["trip_id"] != active["trip_id"]), None)
        next_departure = aware_utc(upcoming["departure_at"]) if upcoming else None
        status = "ON_TRIP"
        reason = f"Vehicle is on Trip {active['trip_number']} at the reference time."
        next_available = active_return
        active_trip_id = active["trip_id"]
        next_trip_id = upcoming["trip_id"] if upcoming else None
    elif initial > reference_utc:
        upcoming = next((row for row in trips if aware_utc(row["departure_at"]) >= initial), None)
        next_departure = aware_utc(upcoming["departure_at"]) if upcoming else None
        status = "UNAVAILABLE"
        reason = "Vehicle is not yet available at the depot at the reference time."
        next_available = initial
        active_trip_id = None
        next_trip_id = upcoming["trip_id"] if upcoming else None
    else:
        upcoming = next((row for row in trips if aware_utc(row["departure_at"]) > reference_utc), None)
        next_departure = aware_utc(upcoming["departure_at"]) if upcoming else None
        status = "AVAILABLE"
        reason = "Vehicle is at the depot at the reference time."
        next_available = reference_utc
        active_trip_id = None
        next_trip_id = upcoming["trip_id"] if upcoming else None
    past_returns = [aware_utc(row["return_to_depot_at"]) for row in trips if aware_utc(row["return_to_depot_at"]) <= reference_utc]
    available_at = max([initial, *past_returns]) if initial else (max(past_returns) if past_returns else None)
    if active:
        available_at = max([value for value in [initial, *past_returns] if value is not None], default=None)
    window = None
    if next_available is not None and next_departure is not None and next_departure >= next_available:
        window = round((next_departure - next_available).total_seconds() / 60)
    output_zone = reference.tzinfo or timezone.utc
    localize = lambda value: value.astimezone(output_zone) if value else None
    return {
        "mt_id": vehicle["mt_id"],
        "vehicle_number": vehicle.get("vehicle_number"),
        "capacity_kl": vehicle.get("capacity_kl"),
        "availability_status": status,
        "availability_reason": reason,
        "active_trip_id": active_trip_id,
        "available_at": localize(available_at),
        "next_available_at": localize(next_available),
        "next_trip_id": next_trip_id,
        "next_departure_at": localize(next_departure),
        "handover_window_minutes": window,
    }


def availability_after(db: Session, route_id: str, reference: datetime) -> dict:
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise IntegrationAPIError(422, "VALIDATION_ERROR", "timestamp must include an ISO-8601 timezone offset.")
    detail = route_detail(db, route_id)
    records = [calculate_vehicle_availability(vehicle, reference) for vehicle in detail["vehicles"]]
    return {
        "route_id": route_id,
        "route_source": detail["route_source"],
        "operation_date": detail["operation_date"],
        "terminal_id": detail["terminal_id"],
        "reference_at": reference,
        "records": records,
    }


def shift_availability(db: Session, route_id: str, shift_id: str | None) -> dict:
    detail = route_detail(db, route_id)
    shifts = shift_records(db, detail["terminal_id"], detail["operation_date"], route_id=route_id)["records"]
    if not shifts:
        raise IntegrationAPIError(422, "SHIFT_CONFIGURATION_NOT_FOUND", "No authoritative shift configuration is available for the selected route.")
    if shift_id:
        shifts = [row for row in shifts if row["shift_id"] == shift_id]
        if not shifts:
            raise IntegrationAPIError(404, "NOT_FOUND", "Shift was not found in the selected route configuration.")
    result = []
    for shift in shifts:
        records = [calculate_vehicle_availability(vehicle, shift["start_at"]) for vehicle in detail["vehicles"]]
        available = [row for row in records if row["availability_status"] == "AVAILABLE"]
        result.append({
            "shift_id": shift["shift_id"],
            "shift_name": shift["shift_name"],
            "shift_start_at": shift["start_at"],
            "available_mt_count": len(available),
            "available_capacity_kl": round(sum(float(row["capacity_kl"] or 0) for row in available), 3),
            "vehicles": records,
        })
    return {
        "route_id": route_id,
        "route_source": detail["route_source"],
        "operation_date": detail["operation_date"],
        "terminal_id": detail["terminal_id"],
        "shifts": result,
    }


def ensure_default_client(db: Session, *, created_by: str = "local-user") -> IntegrationClient:
    client = db.scalar(
        select(IntegrationClient).where(
            IntegrationClient.integration_name == INTEGRATION_NAME,
            IntegrationClient.client_code == DEFAULT_CLIENT_CODE,
        )
    )
    if not client:
        client = IntegrationClient(
            id=uuid.uuid4().hex,
            integration_name=INTEGRATION_NAME,
            client_name="AMT Scheduler",
            client_code=DEFAULT_CLIENT_CODE,
            active=True,
            permissions=["read"],
            created_by=created_by,
        )
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


def regenerate_credential(db: Session, *, actor: str) -> dict:
    client = ensure_default_client(db, created_by=actor)
    token = generate_integration_token()
    now = utc_now()
    client.token_hash = hash_integration_token(token)
    client.token_hint = token_hint(token)
    client.token_created_at = now
    client.active = True
    db.commit()
    return {
        "client_id": client.id,
        "client_name": client.client_name,
        "client_code": client.client_code,
        "bearer_token": token,
        "token_hint": client.token_hint,
        "created_at": now,
    }


def console_access(db: Session, base_url: str) -> dict:
    client = ensure_default_client(db)
    return {
        "base_url": base_url.rstrip("/"),
        "authentication_type": "Bearer token",
        "client_id": client.id,
        "client_name": client.client_name,
        "client_code": client.client_code,
        "active": client.active,
        "has_credential": bool(client.token_hash),
        "token_masked": "••••••••••••••••" if client.token_hash else "Not generated",
        "token_hint": client.token_hint,
        "token_created_at": aware_utc(client.token_created_at),
        "last_used_at": aware_utc(client.last_used_at),
        "permissions": client.permissions or [],
    }


def console_overview(db: Session, base_url: str) -> dict:
    client = ensure_default_client(db)
    datasets = {name: dataset_version(db, name) for name in DATASET_NAMES}
    zone = timezone_for_name(None)
    day_start_local = datetime.combine(utc_now().astimezone(zone).date(), time.min, tzinfo=zone)
    day_start = day_start_local.astimezone(timezone.utc)
    base_logs = select(IntegrationAPILog).where(IntegrationAPILog.integration_name == INTEGRATION_NAME)
    last = db.scalar(base_logs.order_by(desc(IntegrationAPILog.requested_at)).limit(1))
    last_success = db.scalar(
        base_logs.where(IntegrationAPILog.response_status.between(200, 299)).order_by(desc(IntegrationAPILog.requested_at)).limit(1)
    )
    today_count = db.scalar(select(func.count()).select_from(IntegrationAPILog).where(
        IntegrationAPILog.integration_name == INTEGRATION_NAME,
        IntegrationAPILog.requested_at >= day_start,
    )) or 0
    success_count = db.scalar(select(func.count()).select_from(IntegrationAPILog).where(
        IntegrationAPILog.integration_name == INTEGRATION_NAME,
        IntegrationAPILog.requested_at >= day_start,
        IntegrationAPILog.response_status.between(200, 299),
    )) or 0
    average_ms = db.scalar(select(func.avg(IntegrationAPILog.response_time_ms)).where(
        IntegrationAPILog.integration_name == INTEGRATION_NAME,
        IntegrationAPILog.requested_at >= day_start,
    ))
    db.commit()
    return {
        "connector_status": "READY" if client.active and client.token_hash else "CREDENTIAL_REQUIRED",
        "api_version": "v1",
        "base_url": base_url.rstrip("/"),
        "authentication_mode": "Bearer token (SHA-256 hash at rest)",
        "datasets": datasets,
        "last_api_request": aware_utc(last.requested_at) if last else None,
        "last_successful_request": aware_utc(last_success.requested_at) if last_success else None,
        "requests_today": int(today_count),
        "success_rate": round(success_count * 100 / today_count, 1) if today_count else 0.0,
        "average_response_time_ms": round(float(average_ms), 1) if average_ms is not None else 0.0,
    }


def list_api_logs(
    db: Session,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    response_status: int | None,
    endpoint: str | None,
    client_id: str | None,
    page: int,
    page_size: int,
) -> dict:
    conditions = [IntegrationAPILog.integration_name == INTEGRATION_NAME]
    if date_from:
        conditions.append(IntegrationAPILog.requested_at >= aware_utc(date_from))
    if date_to:
        conditions.append(IntegrationAPILog.requested_at <= aware_utc(date_to))
    if response_status is not None:
        conditions.append(IntegrationAPILog.response_status == response_status)
    if endpoint:
        conditions.append(IntegrationAPILog.endpoint.ilike(f"%{endpoint.strip()}%"))
    if client_id:
        conditions.append(IntegrationAPILog.client_id == client_id)
    total = db.scalar(select(func.count()).select_from(IntegrationAPILog).where(*conditions)) or 0
    rows = db.scalars(
        select(IntegrationAPILog).where(*conditions).order_by(desc(IntegrationAPILog.requested_at)).offset((page - 1) * page_size).limit(page_size)
    ).all()
    client_ids = {row.client_id for row in rows if row.client_id}
    clients = {row.id: row.client_code for row in db.scalars(select(IntegrationClient).where(IntegrationClient.id.in_(client_ids))).all()} if client_ids else {}
    return {
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "total_pages": total_pages(total, page_size),
        "records": [{
            "id": row.id,
            "request_id": row.request_id,
            "client_id": row.client_id,
            "client": clients.get(row.client_id, "ANONYMOUS"),
            "timestamp": aware_utc(row.requested_at),
            "method": row.http_method,
            "endpoint": row.endpoint,
            "response_status": row.response_status,
            "response_time_ms": row.response_time_ms,
            "record_count": row.record_count,
            "error_code": row.error_code,
        } for row in rows],
    }


def api_log_detail(db: Session, log_id: str) -> dict:
    row = db.get(IntegrationAPILog, log_id)
    if not row or row.integration_name != INTEGRATION_NAME:
        raise IntegrationAPIError(404, "NOT_FOUND", "API log was not found.")
    client = db.get(IntegrationClient, row.client_id) if row.client_id else None
    return {
        "id": row.id,
        "request_id": row.request_id,
        "client_id": row.client_id,
        "client": client.client_code if client else "ANONYMOUS",
        "timestamp": aware_utc(row.requested_at),
        "method": row.http_method,
        "endpoint": row.endpoint,
        "query_parameters": row.query_params or {},
        "response_status": row.response_status,
        "response_time_ms": row.response_time_ms,
        "record_count": row.record_count,
        "ip": row.ip_address,
        "error_code": row.error_code,
        "error_message": row.error_message,
    }
