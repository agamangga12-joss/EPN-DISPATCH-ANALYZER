from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from math import floor
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .models import BridgeSPBUTag, DepartureShiftAnalysisConfig, FactGPSEvent, FactLoadingOrderLine, FactShipment, FactShipmentSPBU, MasterDepot, MasterMT, MasterSPBU, MasterTag
from .normalization import clean_str, make_id, normalize_key


ALGORITHM_VERSION = "departure_profile.circular_gap_v1"
SHIFT_ASSIGNMENT_ALGORITHM_VERSION = "shift_assignment.descriptive_v1"
GPS_SOURCE_TYPES = {"DEPOT_EXIT", "DEPOT_GEOFENCE_EXIT", "ACTUAL_DEPOT_EXIT", "GPS_DEPOT_EXIT"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHIFT_ASSIGNMENT_METHODS = {"DOMINANT_SHIFT", "MEDIAN_BASED", "HYBRID_CONFIDENCE_AWARE"}
SHIFT_CONFIDENCE_FACTORS = {"HIGH": 1.0, "MEDIUM": 0.8, "LOW": 0.6}
SHIFT_HYBRID_WEIGHTS = {
    "historical_shift_share": 0.40,
    "preferred_window_overlap": 0.25,
    "median_alignment": 0.20,
    "peak_alignment": 0.15,
}
SHIFT_STATUS_THRESHOLDS = {
    "minimum_observations": 5,
    "dominant_clear_share": 60.0,
    "dominant_clear_gap": 15.0,
    "dominant_moderate_share": 45.0,
    "dominant_ambiguous_gap": 10.0,
    "hybrid_clear_score": 60.0,
    "hybrid_clear_gap": 15.0,
    "hybrid_moderate_score": 45.0,
    "hybrid_moderate_gap": 8.0,
}


def list_saved_shift_analysis_configs(db: Session, depot_id: str | None = None, limit: int = 10, offset: int = 0) -> dict:
    filters = []
    if depot_id:
        filters.append(DepartureShiftAnalysisConfig.depot_id == depot_id)
    total = db.scalar(select(func.count()).select_from(DepartureShiftAnalysisConfig).where(*filters)) or 0
    rows = db.scalars(
        select(DepartureShiftAnalysisConfig)
        .where(*filters)
        .order_by(desc(DepartureShiftAnalysisConfig.updated_at), desc(DepartureShiftAnalysisConfig.created_at))
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    ).all()
    depot_ids = sorted({row.depot_id for row in rows})
    depot_names = {
        depot.depot_id: depot.depot_name
        for depot in db.scalars(select(MasterDepot).where(MasterDepot.depot_id.in_(depot_ids))).all()
    } if depot_ids else {}
    return {
        "total": total,
        "limit": max(1, min(limit, 100)),
        "offset": max(0, offset),
        "rows": [serialize_saved_shift_analysis_config(row, depot_names.get(row.depot_id), include_snapshots=False) for row in rows],
    }


def get_saved_shift_analysis_config(db: Session, config_id: str) -> dict:
    config = db.get(DepartureShiftAnalysisConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Saved shift analysis configuration not found.")
    depot = db.get(MasterDepot, config.depot_id)
    return serialize_saved_shift_analysis_config(config, depot.depot_name if depot else None, include_snapshots=True)


def save_shift_analysis_config(db: Session, payload: dict) -> dict:
    name = clean_str(payload.get("name"))
    if not name:
        raise HTTPException(status_code=400, detail="Configuration name is required.")
    normalized_name = normalize_key(name)
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Configuration name is invalid.")

    departure_snapshot = payload.get("departure_analysis_snapshot") or {}
    shift_snapshot = payload.get("shift_analysis_snapshot") or {}
    if not departure_snapshot or not shift_snapshot:
        raise HTTPException(status_code=400, detail="Departure analysis and shift analysis snapshots are required.")

    filters = shift_snapshot.get("effective_filters") or departure_snapshot.get("effective_filters") or {}
    depot_id = clean_str(payload.get("depot_id")) or clean_str(filters.get("depot_id"))
    if not depot_id or not db.get(MasterDepot, depot_id):
        raise HTTPException(status_code=400, detail="A valid depot is required.")

    start_date = parse_date_from_payload(payload.get("start_date") or filters.get("start_date"), "start_date")
    end_date = parse_date_from_payload(payload.get("end_date") or filters.get("end_date"), "end_date")
    bucket_minutes = int(payload.get("bucket_minutes") or filters.get("bucket_minutes") or 30)
    assignment_method = clean_str(payload.get("assignment_method")) or clean_str(shift_snapshot.get("assignment_method"))
    if not assignment_method:
        raise HTTPException(status_code=400, detail="Assignment method is required.")

    existing = db.scalar(
        select(DepartureShiftAnalysisConfig).where(
            DepartureShiftAnalysisConfig.depot_id == depot_id,
            DepartureShiftAnalysisConfig.normalized_name == normalized_name,
        )
    )
    config = existing or DepartureShiftAnalysisConfig(
        id=make_id("dep_shift_cfg", depot_id, normalized_name, utc_now_label()),
        name=name,
        normalized_name=normalized_name,
        depot_id=depot_id,
    )
    config.name = name
    config.start_date = start_date
    config.end_date = end_date
    config.bucket_minutes = bucket_minutes
    config.search = clean_str(payload.get("search")) or clean_str(filters.get("search"))
    config.sort_column = clean_str(payload.get("sort_column")) or clean_str(filters.get("sort_column")) or "observation_count"
    config.sort_direction = clean_str(payload.get("sort_direction")) or clean_str(filters.get("sort_direction")) or "desc"
    config.assignment_method = assignment_method
    config.shift_config = payload.get("shift_config") or shift_snapshot.get("shift_config") or []
    config.ui_state = payload.get("ui_state") or {}
    config.departure_analysis_snapshot = departure_snapshot
    config.shift_analysis_snapshot = shift_snapshot
    config.updated_at = datetime.now(timezone.utc)
    db.add(config)
    db.commit()
    db.refresh(config)
    depot = db.get(MasterDepot, depot_id)
    return serialize_saved_shift_analysis_config(config, depot.depot_name if depot else None, include_snapshots=True)


def delete_saved_shift_analysis_config(db: Session, config_id: str) -> dict:
    config = db.get(DepartureShiftAnalysisConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Saved shift analysis configuration not found.")
    db.delete(config)
    db.commit()
    return {"status": "DELETED", "id": config_id}


def parse_date_from_payload(value: object, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} is required.")
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be YYYY-MM-DD.") from exc


def serialize_saved_shift_analysis_config(config: DepartureShiftAnalysisConfig, depot_name: str | None, include_snapshots: bool) -> dict:
    departure_summary = (config.departure_analysis_snapshot or {}).get("summary") or {}
    shift_summary = (config.shift_analysis_snapshot or {}).get("summary") or {}
    row = {
        "id": config.id,
        "name": config.name,
        "depot_id": config.depot_id,
        "depot_name": depot_name,
        "start_date": config.start_date.isoformat(),
        "end_date": config.end_date.isoformat(),
        "bucket_minutes": config.bucket_minutes,
        "search": config.search or "",
        "sort_column": config.sort_column,
        "sort_direction": config.sort_direction,
        "assignment_method": config.assignment_method,
        "assignment_method_label": shift_assignment_label(config.assignment_method),
        "shift_count": len(config.shift_config or []),
        "profile_count": departure_summary.get("profile_count", 0),
        "observation_count": departure_summary.get("observation_count", 0),
        "assigned_profile_count": shift_summary.get("profile_count", 0),
        "created_by": config.created_by,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
    if include_snapshots:
        row.update(
            {
                "shift_config": config.shift_config or [],
                "ui_state": config.ui_state or {},
                "departure_analysis_snapshot": config.departure_analysis_snapshot or {},
                "shift_analysis_snapshot": config.shift_analysis_snapshot or {},
            }
        )
    return row


def build_departure_intelligence_payload(
    db: Session,
    depot_id: str,
    start_date: date,
    end_date: date,
    bucket_minutes: int = 30,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    sort_column: str = "observation_count",
    sort_direction: str = "desc",
    confidence_level: str | None = None,
    spbu_ids: list[str] | None = None,
    profile_search: str | None = None,
) -> dict:
    if bucket_minutes not in {30, 60}:
        raise HTTPException(status_code=400, detail="bucket_minutes must be 30 or 60.")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date.")
    depot = db.get(MasterDepot, depot_id)
    if not depot:
        raise HTTPException(status_code=404, detail="Depot not found.")

    raw_rows = load_departure_rows(db, depot_id, start_date, end_date, search)
    gps_lookup = load_gps_departure_lookup(db, depot_id, raw_rows)
    quantity_lookup = load_quantity_lookup(db, raw_rows)
    observations = build_observations(raw_rows, gps_lookup, quantity_lookup)
    valid_observations = [row for row in observations if row["departure_datetime_used"]]

    all_profiles = build_profiles(valid_observations, bucket_minutes)
    attach_spbu_tags(db, all_profiles)
    all_profiles = sort_profiles(all_profiles, sort_column, sort_direction)
    profiles = filter_departure_profiles(all_profiles, confidence_level, spbu_ids, profile_search)
    total = len(profiles)
    visible_profiles = profiles[offset : offset + limit]

    return {
        "phase": 2,
        "page_name": "Depot Departure Time Intelligence",
        "algorithm_version": ALGORITHM_VERSION,
        "effective_filters": {
            "depot_id": depot.depot_id,
            "depot_name": depot.depot_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "bucket_minutes": bucket_minutes,
            "search": search or "",
            "sort_column": sort_column,
            "sort_direction": "desc" if sort_direction == "desc" else "asc",
            "confidence_level": confidence_level or "ALL",
            "spbu_ids": spbu_ids or [],
            "profile_search": profile_search or "",
        },
        "summary": build_summary(observations, valid_observations, all_profiles),
        "distribution": build_distribution(valid_observations, bucket_minutes),
        "weekday_heatmap": build_weekday_heatmap(valid_observations, bucket_minutes),
        "box_plot": build_box_plot(visible_profiles),
        "profiles": visible_profiles,
        "total": total,
        "limit": limit,
        "offset": offset,
        "observations": build_observation_sample(valid_observations, visible_profiles),
        "notes": [
            "The unit of analysis is unique shipment_id + spbu_id.",
            "departure_datetime_used prefers a reliable GPS depot-exit event when available, otherwise LO gate-out.",
            "Preferred Historical Departure Window is descriptive and uses circular-time P20-P80 bounds.",
        ],
    }


def build_departure_date_availability(db: Session, depot_id: str) -> dict:
    depot = db.get(MasterDepot, depot_id)
    if not depot:
        raise HTTPException(status_code=404, detail="Depot not found.")
    rows = db.execute(
        select(FactShipment.operating_date, func.count())
        .where(
            FactShipment.depot_id == depot_id,
            FactShipment.operating_date.is_not(None),
            FactShipment.gate_out_datetime.is_not(None),
        )
        .group_by(FactShipment.operating_date)
        .order_by(FactShipment.operating_date)
    ).all()
    dates = [{"date": operating_date.isoformat(), "shipment_count": count} for operating_date, count in rows]
    return {
        "depot_id": depot.depot_id,
        "depot_name": depot.depot_name,
        "available_dates": [item["date"] for item in dates],
        "dates": dates,
        "min_date": dates[0]["date"] if dates else None,
        "max_date": dates[-1]["date"] if dates else None,
    }


def build_shift_intelligence_payload(
    db: Session,
    depot_id: str,
    start_date: date,
    end_date: date,
    shifts: list[dict],
    assignment_method: str,
    bucket_minutes: int = 30,
    search: str | None = None,
    sort_column: str = "observation_count",
    sort_direction: str = "desc",
) -> dict:
    if bucket_minutes not in {30, 60}:
        raise HTTPException(status_code=400, detail="bucket_minutes must be 30 or 60.")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date.")
    method = assignment_method.upper()
    if method not in SHIFT_ASSIGNMENT_METHODS:
        raise HTTPException(status_code=400, detail="assignment_method must be DOMINANT_SHIFT, MEDIAN_BASED, or HYBRID_CONFIDENCE_AWARE.")
    depot = db.get(MasterDepot, depot_id)
    if not depot:
        raise HTTPException(status_code=404, detail="Depot not found.")
    shift_config = validate_shift_config(shifts)

    raw_rows = load_departure_rows(db, depot_id, start_date, end_date, search)
    gps_lookup = load_gps_departure_lookup(db, depot_id, raw_rows)
    quantity_lookup = load_quantity_lookup(db, raw_rows)
    observations = build_observations(raw_rows, gps_lookup, quantity_lookup)
    valid_observations = [row for row in observations if row["departure_datetime_used"]]
    profiles = sort_profiles(build_profiles(valid_observations, bucket_minutes), sort_column, sort_direction)
    observations_by_spbu: dict[str, list[dict]] = defaultdict(list)
    for row in valid_observations:
        observations_by_spbu[row["spbu_id"]].append(row)

    rows = [
        build_shift_profile(profile, observations_by_spbu.get(profile["spbu_id"], []), shift_config, method, start_date, end_date)
        for profile in profiles
    ]
    rows = sort_shift_profiles(rows, sort_column, sort_direction)

    return {
        "phase": 2,
        "section": "Operational Shift Intelligence",
        "assignment_method": method,
        "assignment_method_label": shift_assignment_label(method),
        "algorithm_version": SHIFT_ASSIGNMENT_ALGORITHM_VERSION,
        "departure_profile_algorithm_version": ALGORITHM_VERSION,
        "shift_assignment_algorithm_version": SHIFT_ASSIGNMENT_ALGORITHM_VERSION,
        "effective_filters": {
            "depot_id": depot.depot_id,
            "depot_name": depot.depot_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "bucket_minutes": bucket_minutes,
            "search": search or "",
            "sort_column": sort_column,
            "sort_direction": "desc" if sort_direction == "desc" else "asc",
        },
        "shift_config_id": shift_config_id(depot_id, shift_config),
        "shift_config": shift_config,
        "summary": build_shift_summary(rows, shift_config),
        "rows": rows,
        "heatmap": build_shift_affinity_heatmap(rows, shift_config),
        "traceability": {
            "depot_id": depot.depot_id,
            "source_period_start": start_date.isoformat(),
            "source_period_end": end_date.isoformat(),
            "calculated_at": utc_now_label(),
            "algorithm_version": SHIFT_ASSIGNMENT_ALGORITHM_VERSION,
        },
        "notes": [
            "Operational Shift Intelligence is descriptive historical classification, not dispatch scheduling.",
            "Shift affinity percentages always use the raw historical distribution, regardless of assignment method.",
            "The unit of analysis remains unique shipment_id + spbu_id using the same departure_datetime_used as Phase 2 profiles.",
        ],
    }


def load_departure_rows(db: Session, depot_id: str, start_date: date, end_date: date, search: str | None) -> list:
    stmt = (
        select(FactShipmentSPBU, FactShipment, MasterSPBU, MasterDepot, MasterMT)
        .join(FactShipment, FactShipment.shipment_id == FactShipmentSPBU.shipment_id)
        .join(MasterSPBU, MasterSPBU.spbu_id == FactShipmentSPBU.spbu_id)
        .join(MasterDepot, MasterDepot.depot_id == FactShipment.depot_id)
        .outerjoin(MasterMT, MasterMT.mt_id == FactShipment.mt_id)
        .where(
            FactShipment.depot_id == depot_id,
            FactShipment.operating_date >= start_date,
            FactShipment.operating_date <= end_date,
        )
        .order_by(FactShipment.operating_date, FactShipment.source_shipment_id, MasterSPBU.spbu_code)
    )
    if search and search.strip():
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            func.lower(MasterSPBU.spbu_code).like(pattern)
            | func.lower(MasterSPBU.spbu_name).like(pattern)
            | func.lower(FactShipment.source_shipment_id).like(pattern)
        )
    return db.execute(stmt).all()


def load_gps_departure_lookup(db: Session, depot_id: str, rows: list) -> dict[str, datetime]:
    vehicle_dates: dict[str, set[date]] = defaultdict(set)
    shipments_by_vehicle: dict[str, list[FactShipment]] = defaultdict(list)
    for _, shipment, _, _, _ in rows:
        if shipment.vehicle_registration and shipment.operating_date:
            vehicle_dates[shipment.vehicle_registration].add(shipment.operating_date)
            shipments_by_vehicle[shipment.vehicle_registration].append(shipment)
    if not vehicle_dates:
        return {}

    vehicles = list(vehicle_dates)
    gps_events = db.scalars(
        select(FactGPSEvent).where(
            FactGPSEvent.vehicle_registration.in_(vehicles),
            FactGPSEvent.nearest_depot_id == depot_id,
            FactGPSEvent.event_datetime.is_not(None),
            FactGPSEvent.event_type.in_(GPS_SOURCE_TYPES),
        )
    ).all()
    events_by_vehicle: dict[str, list[FactGPSEvent]] = defaultdict(list)
    for event in gps_events:
        if event.vehicle_registration and event.event_datetime and event.event_datetime.date() in vehicle_dates.get(event.vehicle_registration, set()):
            events_by_vehicle[event.vehicle_registration].append(event)

    lookup: dict[str, datetime] = {}
    for vehicle_registration, shipments in shipments_by_vehicle.items():
        events = sorted(events_by_vehicle.get(vehicle_registration, []), key=lambda item: item.event_datetime)
        if not events:
            continue
        for shipment in shipments:
            candidates = [event for event in events if event.event_datetime.date() == shipment.operating_date]
            if shipment.gate_out_datetime:
                candidates = [
                    event
                    for event in candidates
                    if abs((event.event_datetime - shipment.gate_out_datetime).total_seconds()) <= 6 * 60 * 60
                ]
                candidates.sort(key=lambda event: abs((event.event_datetime - shipment.gate_out_datetime).total_seconds()))
            if candidates:
                lookup[shipment.shipment_id] = candidates[0].event_datetime
    return lookup


def load_quantity_lookup(db: Session, rows: list) -> dict[tuple[str, str], dict]:
    keys = {(shipment_spbu.shipment_id, shipment_spbu.spbu_id) for shipment_spbu, *_ in rows}
    if not keys:
        return {}
    shipment_ids = {shipment_id for shipment_id, _ in keys}
    line_rows = db.execute(
        select(FactLoadingOrderLine, FactShipment)
        .join(FactShipment, FactShipment.shipment_id == FactLoadingOrderLine.shipment_id)
        .where(FactLoadingOrderLine.shipment_id.in_(shipment_ids))
    ).all()
    lookup: dict[tuple[str, str], dict] = defaultdict(lambda: {"quantity": 0.0, "products": set()})
    for line, shipment in line_rows:
        if not line.spbu_id:
            continue
        key = (shipment.shipment_id, line.spbu_id)
        if key not in keys:
            continue
        lookup[key]["quantity"] += float(line.quantity or 0)
        if line.source_product_name:
            lookup[key]["products"].add(line.source_product_name)
    return lookup


def build_observations(rows: list, gps_lookup: dict[str, datetime], quantity_lookup: dict[tuple[str, str], dict]) -> list[dict]:
    observations = []
    seen: set[tuple[str, str]] = set()
    for shipment_spbu, shipment, spbu, depot, mt in rows:
        key = (shipment.shipment_id, spbu.spbu_id)
        if key in seen:
            continue
        seen.add(key)
        zone = ZoneInfo(depot.timezone or "Asia/Jakarta")
        def local_time(value):
            if value is None:
                return None
            return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)
        gps_dt = local_time(gps_lookup.get(shipment.shipment_id))
        lo_dt = local_time(shipment.gate_out_datetime)
        used_dt = gps_dt or lo_dt
        source = "GPS" if gps_dt else "LO_GATE_OUT" if lo_dt else None
        quantity = quantity_lookup.get(key, {"quantity": 0.0, "products": set()})
        observations.append(
            {
                "observation_id": f"{shipment.shipment_id}:{spbu.spbu_id}",
                "shipment_id": shipment.shipment_id,
                "source_shipment_id": shipment.source_shipment_id,
                "spbu_id": spbu.spbu_id,
                "spbu_code": spbu.spbu_code,
                "spbu_name": spbu.spbu_name,
                "depot_id": depot.depot_id,
                "depot_name": depot.depot_name,
                "operation_date": shipment.operating_date.isoformat() if shipment.operating_date else None,
                "vehicle_id": shipment.mt_id,
                "vehicle_registration": shipment.vehicle_registration,
                "vehicle_type_tag": mt.vehicle_type_tag if mt else None,
                "project_tag_raw": shipment.project_tag_raw,
                "loading_order_gate_out_datetime": lo_dt.isoformat() if lo_dt else None,
                "gps_actual_depot_exit_datetime": gps_dt.isoformat() if gps_dt else None,
                "departure_datetime_used": used_dt.isoformat() if used_dt else None,
                "departure_time_source": source,
                "departure_minute": minute_of_day(used_dt) if used_dt else None,
                "day_of_week": DAY_NAMES[used_dt.weekday()] if used_dt else None,
                "is_weekend": used_dt.weekday() >= 5 if used_dt else None,
                "gps_vs_lo_difference_minutes": round((gps_dt - lo_dt).total_seconds() / 60, 1) if gps_dt and lo_dt else None,
                "quantity": quantity["quantity"],
                "products": sorted(quantity["products"]),
                "assignment_source": shipment_spbu.assignment_source,
            }
        )
    return observations


def build_summary(observations: list[dict], valid_observations: list[dict], profiles: list[dict]) -> dict:
    shipment_ids = {row["shipment_id"] for row in valid_observations}
    vehicles = {row["vehicle_registration"] for row in valid_observations if row["vehicle_registration"]}
    spbus = {row["spbu_id"] for row in valid_observations}
    gps_rows = [row for row in observations if row["gps_actual_depot_exit_datetime"]]
    lo_rows = [row for row in observations if row["loading_order_gate_out_datetime"]]
    diff_values = [row["gps_vs_lo_difference_minutes"] for row in observations if row["gps_vs_lo_difference_minutes"] is not None]
    high = sum(1 for row in profiles if row["confidence_level"] == "HIGH")
    medium = sum(1 for row in profiles if row["confidence_level"] == "MEDIUM")
    return {
        "observation_count": len(valid_observations),
        "profile_count": len(profiles),
        "shipment_count": len(shipment_ids),
        "spbu_count": len(spbus),
        "vehicle_count": len(vehicles),
        "quantity_dispatched": round(sum(float(row["quantity"] or 0) for row in valid_observations), 2),
        "gps_timestamp_coverage_pct": percentage(len(gps_rows), len(observations)),
        "lo_gate_out_coverage_pct": percentage(len(lo_rows), len(observations)),
        "gps_observation_count": len(gps_rows),
        "lo_gate_out_observation_count": len(lo_rows),
        "missing_timestamp_count": sum(1 for row in observations if not row["departure_datetime_used"]),
        "invalid_timestamp_count": 0,
        "avg_gps_vs_lo_difference_minutes": round(sum(diff_values) / len(diff_values), 1) if diff_values else None,
        "high_confidence_profiles": high,
        "medium_confidence_profiles": medium,
        "low_confidence_profiles": max(0, len(profiles) - high - medium),
    }


def build_profiles(observations: list[dict], bucket_minutes: int) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in observations:
        grouped[row["spbu_id"]].append(row)
    profiles = []
    for spbu_id, rows in grouped.items():
        minutes = [int(row["departure_minute"]) for row in rows if row["departure_minute"] is not None]
        if not minutes:
            continue
        stats = circular_stats(minutes)
        source_counts = Counter(row["departure_time_source"] for row in rows)
        peak_bucket_start, peak_bucket_count = peak_bucket(minutes, bucket_minutes)
        shipment_ids = {row["shipment_id"] for row in rows}
        vehicles = {row["vehicle_registration"] for row in rows if row["vehicle_registration"]}
        confidence_score, confidence_level = confidence(stats["iqr_minutes"], len(minutes))
        profiles.append(
            {
                "spbu_id": spbu_id,
                "spbu_code": rows[0]["spbu_code"],
                "spbu_name": rows[0]["spbu_name"],
                "depot_id": rows[0]["depot_id"],
                "depot_name": rows[0]["depot_name"],
                "observation_count": len(minutes),
                "shipment_count": len(shipment_ids),
                "vehicle_count": len(vehicles),
                "quantity_dispatched": round(sum(float(row["quantity"] or 0) for row in rows), 2),
                "p20": minute_label(stats["p20"]),
                "p25": minute_label(stats["p25"]),
                "p50": minute_label(stats["p50"]),
                "p75": minute_label(stats["p75"]),
                "p80": minute_label(stats["p80"]),
                "p90": minute_label(stats["p90"]),
                "p95": minute_label(stats["p95"]),
                "p20_minutes": stats["p20"],
                "p25_minutes": stats["p25"],
                "p50_minutes": stats["p50"],
                "p75_minutes": stats["p75"],
                "p80_minutes": stats["p80"],
                "p90_minutes": stats["p90"],
                "p95_minutes": stats["p95"],
                "min": minute_label(stats["min"]),
                "max": minute_label(stats["max"]),
                "crosses_midnight": stats["crosses_midnight"],
                "peak_departure_time": minute_label((peak_bucket_start + bucket_minutes / 2) % 1440),
                "peak_departure_minutes": (peak_bucket_start + bucket_minutes / 2) % 1440,
                "peak_departure_bucket": bucket_label(peak_bucket_start, bucket_minutes),
                "peak_bucket_count": peak_bucket_count,
                "preferred_historical_departure_window": f"{minute_label(stats['p20'])}-{minute_label(stats['p80'])}",
                "dispersion_minutes_iqr": round(stats["iqr_minutes"], 1),
                "robust_spread_minutes_p20_p80": round(stats["p80_linear"] - stats["p20_linear"], 1),
                "outlier_count": stats["outlier_count"],
                "confidence_score": confidence_score,
                "confidence_level": confidence_level,
                "departure_time_source_counts": dict(source_counts),
                "algorithm_version": ALGORITHM_VERSION,
                "box_plot_minutes": [stats["min_linear"], stats["p25_linear"], stats["p50_linear"], stats["p75_linear"], stats["max_linear"]],
            }
        )
    return profiles


def sort_profiles(profiles: list[dict], sort_column: str, sort_direction: str) -> list[dict]:
    sort_keys = {
        "spbu_code": lambda item: item.get("spbu_code") or "",
        "preferred_historical_departure_window": lambda item: item.get("p20_minutes") or 0,
        "peak_departure_time": lambda item: item.get("peak_departure_minutes") or 0,
        "p50": lambda item: item.get("p50_minutes") or 0,
        "p80": lambda item: item.get("p80_minutes") or 0,
        "p90": lambda item: item.get("p90_minutes") or 0,
        "p95": lambda item: item.get("p95_minutes") or 0,
        "observation_count": lambda item: item.get("observation_count") or 0,
        "dispersion_minutes_iqr": lambda item: item.get("dispersion_minutes_iqr") or 0,
        "confidence_score": lambda item: item.get("confidence_score") or 0,
    }
    key_fn = sort_keys.get(sort_column, sort_keys["observation_count"])
    reverse = sort_direction == "desc"
    return sorted(profiles, key=lambda item: (key_fn(item), item.get("spbu_code") or item.get("spbu_id") or ""), reverse=reverse)


def attach_spbu_tags(db: Session, profiles: list[dict]) -> None:
    spbu_ids = sorted({profile["spbu_id"] for profile in profiles})
    if not spbu_ids:
        return
    rows = db.execute(
        select(BridgeSPBUTag.spbu_id, MasterTag.tag_value)
        .join(MasterTag, MasterTag.tag_id == BridgeSPBUTag.tag_id)
        .where(BridgeSPBUTag.spbu_id.in_(spbu_ids), MasterTag.active_status != "DELETED")
        .order_by(BridgeSPBUTag.spbu_id, MasterTag.tag_value)
    ).all()
    tags_by_spbu: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for spbu_id, tag_value in rows:
        key = (spbu_id, tag_value)
        if key in seen:
            continue
        seen.add(key)
        tags_by_spbu[spbu_id].append(tag_value)
    for profile in profiles:
        profile["spbu_tags"] = tags_by_spbu.get(profile["spbu_id"], [])


def filter_departure_profiles(profiles: list[dict], confidence_level: str | None, spbu_ids: list[str] | None, profile_search: str | None = None) -> list[dict]:
    filtered = profiles
    if confidence_level and confidence_level.upper() in {"HIGH", "MEDIUM", "LOW"}:
        target_level = confidence_level.upper()
        filtered = [profile for profile in filtered if profile.get("confidence_level") == target_level]
    if spbu_ids is not None:
        allowed_spbu_ids = {spbu_id for spbu_id in spbu_ids if spbu_id}
        filtered = [profile for profile in filtered if profile.get("spbu_id") in allowed_spbu_ids]
    if profile_search and profile_search.strip():
        query = profile_search.strip().lower()
        filtered = [
            profile
            for profile in filtered
            if query in (profile.get("spbu_code") or "").lower()
            or query in (profile.get("spbu_name") or "").lower()
            or any(query in str(tag).lower() for tag in profile.get("spbu_tags", []))
        ]
    return filtered


def validate_shift_config(shifts: list[dict]) -> list[dict]:
    if not shifts:
        raise HTTPException(status_code=400, detail="At least one operational shift is required.")
    if len(shifts) > 12:
        raise HTTPException(status_code=400, detail="At most 12 operational shifts are supported.")

    names: set[str] = set()
    covered = [None] * 1440
    normalized_shifts = []
    for index, raw_shift in enumerate(shifts):
        name = str(raw_shift.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"Shift {index + 1} must have a name.")
        normalized_name = name.lower()
        if normalized_name in names:
            raise HTTPException(status_code=400, detail=f"Duplicate shift name: {name}.")
        names.add(normalized_name)
        start_time = str(raw_shift.get("start_time") or "")
        end_time = str(raw_shift.get("end_time") or "")
        start_minute = parse_shift_time(start_time, f"{name} start_time")
        end_minute = parse_shift_time(end_time, f"{name} end_time")
        segments = shift_segments(start_minute, end_minute)
        shift_id = str(raw_shift.get("shift_id") or f"shift_{index + 1}").strip() or f"shift_{index + 1}"
        for segment_start, segment_end in segments:
            for minute in range(segment_start, segment_end):
                if covered[minute] is not None:
                    overlap = normalized_shifts[int(covered[minute])]["name"]
                    raise HTTPException(status_code=400, detail=f"Shift ranges overlap around {minute_label(minute)}: {overlap} and {name}.")
                covered[minute] = len(normalized_shifts)
        normalized_shifts.append(
            {
                "shift_id": shift_id,
                "name": name,
                "order": index + 1,
                "start_time": minute_label(start_minute),
                "end_time": minute_label(end_minute),
                "start_minute": start_minute,
                "end_minute": end_minute,
                "segments": [{"start_minute": segment_start, "end_exclusive_minute": segment_end} for segment_start, segment_end in segments],
            }
        )

    gap_minute = next((minute for minute, owner in enumerate(covered) if owner is None), None)
    if gap_minute is not None:
        raise HTTPException(status_code=400, detail=f"Shift ranges must cover the full 24-hour day. Gap starts at {minute_label(gap_minute)}.")
    return normalized_shifts


def parse_shift_time(value: str, field_name: str) -> int:
    parts = value.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise HTTPException(status_code=400, detail=f"{field_name} must use HH:MM format.")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid time between 00:00 and 23:59.")
    return hour * 60 + minute


def shift_segments(start_minute: int, end_minute: int) -> list[tuple[int, int]]:
    end_exclusive = end_minute + 1
    if start_minute <= end_minute:
        return [(start_minute, end_exclusive)]
    return [(start_minute, 1440), (0, end_exclusive)]


def shift_config_id(depot_id: str, shift_config: list[dict]) -> str:
    signature = "|".join(f"{item['order']}:{item['name']}:{item['start_time']}:{item['end_time']}" for item in shift_config)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return f"{depot_id}:{digest}"


def build_shift_profile(profile: dict, observations: list[dict], shift_config: list[dict], method: str, start_date: date, end_date: date) -> dict:
    distribution = build_shift_distribution(observations, shift_config)
    if method == "DOMINANT_SHIFT":
        assignment = assign_dominant_shift(distribution, profile)
    elif method == "MEDIAN_BASED":
        assignment = assign_median_based_shift(distribution, profile, shift_config)
    else:
        assignment = assign_hybrid_shift(distribution, profile, shift_config)
    return {
        "depot_id": profile["depot_id"],
        "spbu_id": profile["spbu_id"],
        "spbu_code": profile["spbu_code"],
        "spbu_name": profile["spbu_name"],
        "shift_config_id": shift_config_id(profile["depot_id"], shift_config),
        "assignment_method": method,
        "primary_shift_id": assignment["primary_shift_id"],
        "primary_shift_name": assignment["primary_shift_name"],
        "primary_shift_share": assignment["primary_shift_share"],
        "primary_shift_score": assignment["primary_shift_score"],
        "secondary_shift_id": assignment["secondary_shift_id"],
        "secondary_shift_name": assignment["secondary_shift_name"],
        "secondary_shift_share": assignment["secondary_shift_share"],
        "secondary_shift_score": assignment["secondary_shift_score"],
        "primary_secondary_gap": assignment["primary_secondary_gap"],
        "assignment_score": assignment["assignment_score"],
        "assignment_status": assignment["assignment_status"],
        "assignment_confidence": assignment["assignment_confidence"],
        "leading_shift_ids": assignment["leading_shift_ids"],
        "leading_shift_names": assignment["leading_shift_names"],
        "shift_distribution": assignment.get("scored_distribution") or distribution,
        "observation_count": profile["observation_count"],
        "median_departure": profile["p50"],
        "median_departure_minutes": profile["p50_minutes"],
        "peak_departure_time": profile["peak_departure_time"],
        "peak_departure_minutes": profile["peak_departure_minutes"],
        "preferred_historical_departure_window": profile["preferred_historical_departure_window"],
        "confidence_score": profile["confidence_score"],
        "confidence_level": profile["confidence_level"],
        "source_period_start": start_date.isoformat(),
        "source_period_end": end_date.isoformat(),
        "calculated_at": utc_now_label(),
        "algorithm_version": SHIFT_ASSIGNMENT_ALGORITHM_VERSION,
    }


def build_shift_distribution(observations: list[dict], shift_config: list[dict]) -> list[dict]:
    total = len(observations)
    counts = Counter(shift_for_minute(int(row["departure_minute"]), shift_config)["shift_id"] for row in observations if row["departure_minute"] is not None)
    return [
        {
            "shift_id": shift["shift_id"],
            "shift_name": shift["name"],
            "shift_order": shift["order"],
            "start_time": shift["start_time"],
            "end_time": shift["end_time"],
            "observation_count": counts.get(shift["shift_id"], 0),
            "share_pct": percentage(counts.get(shift["shift_id"], 0), total),
            "score": None,
        }
        for shift in shift_config
    ]


def assign_dominant_shift(distribution: list[dict], profile: dict) -> dict:
    ranked = rank_shift_values(distribution, "share_pct")
    primary = ranked[0]
    secondary = ranked[1] if len(ranked) > 1 else empty_shift_value()
    gap = round(primary["share_pct"] - secondary["share_pct"], 1)
    leading = [item for item in ranked if item["share_pct"] == primary["share_pct"]]
    status = assignment_status_from_share(profile["observation_count"], primary["share_pct"], gap)
    if len(leading) > 1 and status != "INSUFFICIENT_DATA":
        status = "AMBIGUOUS"
    return assignment_payload(primary, secondary, gap, primary["share_pct"], status, leading)


def assign_median_based_shift(distribution: list[dict], profile: dict, shift_config: list[dict]) -> dict:
    median_shift = shift_for_minute(int(round(profile["p50_minutes"])), shift_config)
    ranked = rank_shift_values(distribution, "share_pct")
    primary = next((item for item in distribution if item["shift_id"] == median_shift["shift_id"]), ranked[0])
    secondary = next((item for item in ranked if item["shift_id"] != primary["shift_id"]), empty_shift_value())
    gap = round(primary["share_pct"] - secondary["share_pct"], 1)
    status = assignment_status_from_share(profile["observation_count"], primary["share_pct"], gap)
    return assignment_payload(primary, secondary, gap, primary["share_pct"], status, [primary])


def assign_hybrid_shift(distribution: list[dict], profile: dict, shift_config: list[dict]) -> dict:
    confidence_factor = SHIFT_CONFIDENCE_FACTORS.get(profile["confidence_level"], 0.6)
    scored = []
    for item in distribution:
        shift = next(config for config in shift_config if config["shift_id"] == item["shift_id"])
        score = (
            SHIFT_HYBRID_WEIGHTS["historical_shift_share"] * (item["share_pct"] / 100)
            + SHIFT_HYBRID_WEIGHTS["preferred_window_overlap"] * preferred_window_overlap(profile, shift)
            + SHIFT_HYBRID_WEIGHTS["median_alignment"] * minute_alignment(profile["p50_minutes"], shift)
            + SHIFT_HYBRID_WEIGHTS["peak_alignment"] * minute_alignment(profile["peak_departure_minutes"], shift)
        ) * confidence_factor
        scored.append({**item, "score": round(score * 100, 1)})
    ranked = rank_shift_values(scored, "score")
    primary = ranked[0]
    secondary = ranked[1] if len(ranked) > 1 else empty_shift_value()
    gap = round((primary.get("score") or 0) - (secondary.get("score") or 0), 1)
    status = assignment_status_from_score(profile["observation_count"], primary.get("score") or 0, gap)
    if profile["confidence_level"] == "LOW" and status == "CLEAR":
        status = "MODERATE"
    return assignment_payload(primary, secondary, gap, primary.get("score") or 0, status, [primary], scored)


def assignment_status_from_share(observation_count: int, primary_share: float, gap: float) -> str:
    if observation_count < SHIFT_STATUS_THRESHOLDS["minimum_observations"]:
        return "INSUFFICIENT_DATA"
    if primary_share >= SHIFT_STATUS_THRESHOLDS["dominant_clear_share"] and gap >= SHIFT_STATUS_THRESHOLDS["dominant_clear_gap"]:
        return "CLEAR"
    if primary_share < SHIFT_STATUS_THRESHOLDS["dominant_moderate_share"] or gap < SHIFT_STATUS_THRESHOLDS["dominant_ambiguous_gap"]:
        return "AMBIGUOUS"
    return "MODERATE"


def assignment_status_from_score(observation_count: int, primary_score: float, gap: float) -> str:
    if observation_count < SHIFT_STATUS_THRESHOLDS["minimum_observations"]:
        return "INSUFFICIENT_DATA"
    if primary_score >= SHIFT_STATUS_THRESHOLDS["hybrid_clear_score"] and gap >= SHIFT_STATUS_THRESHOLDS["hybrid_clear_gap"]:
        return "CLEAR"
    if primary_score >= SHIFT_STATUS_THRESHOLDS["hybrid_moderate_score"] and gap >= SHIFT_STATUS_THRESHOLDS["hybrid_moderate_gap"]:
        return "MODERATE"
    return "AMBIGUOUS"


def assignment_payload(primary: dict, secondary: dict, gap: float, score: float, status: str, leading: list[dict], scored_distribution: list[dict] | None = None) -> dict:
    distribution_by_id = {item["shift_id"]: item for item in scored_distribution or []}
    return {
        "primary_shift_id": primary.get("shift_id"),
        "primary_shift_name": primary.get("shift_name"),
        "primary_shift_share": primary.get("share_pct", 0),
        "primary_shift_score": distribution_by_id.get(primary.get("shift_id"), primary).get("score"),
        "secondary_shift_id": secondary.get("shift_id"),
        "secondary_shift_name": secondary.get("shift_name"),
        "secondary_shift_share": secondary.get("share_pct", 0),
        "secondary_shift_score": distribution_by_id.get(secondary.get("shift_id"), secondary).get("score"),
        "primary_secondary_gap": gap,
        "assignment_score": round(score, 1),
        "assignment_status": status,
        "assignment_confidence": status,
        "leading_shift_ids": [item["shift_id"] for item in leading],
        "leading_shift_names": [item["shift_name"] for item in leading],
        "scored_distribution": scored_distribution,
    }


def empty_shift_value() -> dict:
    return {"shift_id": None, "shift_name": None, "share_pct": 0, "score": 0}


def rank_shift_values(distribution: list[dict], key: str) -> list[dict]:
    return sorted(distribution, key=lambda item: (-(item.get(key) or 0), item.get("shift_order") or 0, item.get("shift_name") or ""))


def shift_for_minute(minute: int, shift_config: list[dict]) -> dict:
    normalized = minute % 1440
    for shift in shift_config:
        for segment in shift["segments"]:
            if segment["start_minute"] <= normalized < segment["end_exclusive_minute"]:
                return shift
    raise HTTPException(status_code=500, detail=f"No operational shift found for minute {minute_label(normalized)}.")


def minute_alignment(minute: float, shift: dict) -> float:
    return 1.0 if any(segment["start_minute"] <= minute % 1440 < segment["end_exclusive_minute"] for segment in shift["segments"]) else 0.0


def preferred_window_overlap(profile: dict, shift: dict) -> float:
    start = float(profile["p20_minutes"])
    end = float(profile["p80_minutes"])
    window_segments = circular_range_segments(start, end)
    duration = sum(segment_end - segment_start for segment_start, segment_end in window_segments)
    if duration <= 0:
        return minute_alignment(profile["p50_minutes"], shift)
    overlap = 0.0
    shift_segment_tuples = [(segment["start_minute"], segment["end_exclusive_minute"]) for segment in shift["segments"]]
    for window_start, window_end in window_segments:
        for shift_start, shift_end in shift_segment_tuples:
            overlap += max(0.0, min(window_end, shift_end) - max(window_start, shift_start))
    return min(1.0, overlap / duration)


def circular_range_segments(start: float, end: float) -> list[tuple[float, float]]:
    start = start % 1440
    end = end % 1440
    if start < end:
        return [(start, end)]
    if start > end:
        return [(start, 1440.0), (0.0, end)]
    return [(start, start + 1.0)]


def build_shift_summary(rows: list[dict], shift_config: list[dict]) -> dict:
    assigned_by_shift = Counter(row["primary_shift_id"] for row in rows if row["assignment_status"] not in {"AMBIGUOUS", "INSUFFICIENT_DATA"})
    statuses = Counter(row["assignment_status"] for row in rows)
    return {
        "profile_count": len(rows),
        "observation_count": sum(row["observation_count"] for row in rows),
        "assigned_by_shift": [
            {
                "shift_id": shift["shift_id"],
                "shift_name": shift["name"],
                "spbu_count": assigned_by_shift.get(shift["shift_id"], 0),
            }
            for shift in shift_config
        ],
        "status_counts": {
            "CLEAR": statuses.get("CLEAR", 0),
            "MODERATE": statuses.get("MODERATE", 0),
            "AMBIGUOUS": statuses.get("AMBIGUOUS", 0),
            "INSUFFICIENT_DATA": statuses.get("INSUFFICIENT_DATA", 0),
        },
    }


def build_shift_affinity_heatmap(rows: list[dict], shift_config: list[dict]) -> dict:
    return {
        "x_axis": [shift["name"] for shift in shift_config],
        "y_axis": [row["spbu_code"] for row in rows],
        "data": [
            [shift_index, row_index, distribution["share_pct"], distribution["observation_count"], row["observation_count"]]
            for row_index, row in enumerate(rows)
            for shift_index, distribution in enumerate(row["shift_distribution"])
        ],
    }


def sort_shift_profiles(rows: list[dict], sort_column: str, sort_direction: str) -> list[dict]:
    sort_keys = {
        "spbu_code": lambda item: item.get("spbu_code") or "",
        "primary_shift_share": lambda item: item.get("primary_shift_share") or 0,
        "p50": lambda item: item.get("median_departure_minutes") or 0,
        "confidence_score": lambda item: item.get("confidence_score") or 0,
        "observation_count": lambda item: item.get("observation_count") or 0,
    }
    key_fn = sort_keys.get(sort_column, sort_keys["observation_count"])
    return sorted(rows, key=lambda item: (key_fn(item), item.get("spbu_code") or ""), reverse=sort_direction == "desc")


def shift_assignment_label(method: str) -> str:
    return {
        "DOMINANT_SHIFT": "Dominant Shift",
        "MEDIAN_BASED": "Median-Based",
        "HYBRID_CONFIDENCE_AWARE": "Hybrid / Confidence-Aware",
    }.get(method, method)


def circular_stats(minutes: list[int]) -> dict:
    values = unwrap_circular_minutes(minutes)
    return {
        **percentile_bundle(values),
        "min": normalize_minute(values[0]),
        "max": normalize_minute(values[-1]),
        "min_linear": values[0],
        "max_linear": values[-1],
        "crosses_midnight": values[-1] >= 1440,
        "outlier_count": outlier_count(values),
    }


def unwrap_circular_minutes(minutes: list[int]) -> list[float]:
    sorted_minutes = sorted(float(minute % 1440) for minute in minutes)
    if len(sorted_minutes) <= 1:
        return sorted_minutes
    gaps = []
    for index, value in enumerate(sorted_minutes):
        next_value = sorted_minutes[(index + 1) % len(sorted_minutes)]
        if index == len(sorted_minutes) - 1:
            next_value += 1440
        gaps.append(next_value - value)
    cut_index = gaps.index(max(gaps))
    start = sorted_minutes[(cut_index + 1) % len(sorted_minutes)]
    unwrapped = [value if value >= start else value + 1440 for value in sorted_minutes]
    return sorted(unwrapped)


def percentile_bundle(values: list[float]) -> dict:
    p20 = percentile(values, 20)
    p25 = percentile(values, 25)
    p50 = percentile(values, 50)
    p75 = percentile(values, 75)
    p80 = percentile(values, 80)
    p90 = percentile(values, 90)
    p95 = percentile(values, 95)
    return {
        "p20": normalize_minute(p20),
        "p25": normalize_minute(p25),
        "p50": normalize_minute(p50),
        "p75": normalize_minute(p75),
        "p80": normalize_minute(p80),
        "p90": normalize_minute(p90),
        "p95": normalize_minute(p95),
        "p20_linear": p20,
        "p25_linear": p25,
        "p50_linear": p50,
        "p75_linear": p75,
        "p80_linear": p80,
        "p90_linear": p90,
        "p95_linear": p95,
        "iqr_minutes": max(0, p75 - p25),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * pct / 100
    lower = floor(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def outlier_count(values: list[float]) -> int:
    if len(values) < 4:
        return 0
    p25 = percentile(values, 25)
    p75 = percentile(values, 75)
    iqr = p75 - p25
    low = p25 - 1.5 * iqr
    high = p75 + 1.5 * iqr
    return sum(1 for value in values if value < low or value > high)


def confidence(iqr_minutes: float, count: int) -> tuple[int, str]:
    sample_score = min(1.0, count / 30) * 70
    spread_score = max(0.0, 1.0 - min(iqr_minutes, 360) / 360) * 30
    score = round(sample_score + spread_score)
    if count >= 30 and iqr_minutes <= 180:
        return score, "HIGH"
    if count >= 10 and iqr_minutes <= 360:
        return score, "MEDIUM"
    return score, "LOW"


def build_distribution(observations: list[dict], bucket_minutes: int) -> list[dict]:
    buckets: dict[int, dict] = {}
    for row in observations:
        bucket_start = int(row["departure_minute"] // bucket_minutes * bucket_minutes)
        bucket = buckets.setdefault(bucket_start, {"shipments": set(), "vehicles": set(), "quantity": 0.0, "value": 0})
        bucket["value"] += 1
        bucket["shipments"].add(row["shipment_id"])
        if row["vehicle_registration"]:
            bucket["vehicles"].add(row["vehicle_registration"])
        bucket["quantity"] += float(row["quantity"] or 0)
    return [
        {
            "name": bucket_label(start, bucket_minutes),
            "bucket_start": minute_label(start),
            "bucket_end": minute_label((start + bucket_minutes) % 1440),
            "value": bucket.get("value", 0),
            "shipments": len(bucket.get("shipments", set())),
            "vehicles": len(bucket.get("vehicles", set())),
            "quantity": round(bucket.get("quantity", 0), 2),
        }
        for start, bucket in sorted(buckets.items())
    ]


def build_weekday_heatmap(observations: list[dict], bucket_minutes: int) -> dict:
    bucket_count = 1440 // bucket_minutes
    x_axis = [bucket_label(index * bucket_minutes, bucket_minutes) for index in range(bucket_count)]
    y_axis = DAY_NAMES
    counts: dict[tuple[int, int], int] = Counter()
    for row in observations:
        if not row["departure_datetime_used"]:
            continue
        departure_dt = datetime.fromisoformat(row["departure_datetime_used"])
        x_index = int(row["departure_minute"] // bucket_minutes)
        y_index = departure_dt.weekday()
        counts[(x_index, y_index)] += 1
    return {
        "x_axis": x_axis,
        "y_axis": y_axis,
        "data": [[x, y, value] for (x, y), value in sorted(counts.items())],
    }


def build_box_plot(profiles: list[dict]) -> dict:
    return {
        "categories": [profile["spbu_code"] for profile in profiles],
        "data": [profile["box_plot_minutes"] for profile in profiles],
    }


def build_observation_sample(observations: list[dict], profiles: list[dict]) -> list[dict]:
    profile_spbus = [profile["spbu_id"] for profile in profiles]
    observations_by_spbu: dict[str, list[dict]] = defaultdict(list)
    for row in observations:
        if row["spbu_id"] in profile_spbus:
            observations_by_spbu[row["spbu_id"]].append(row)

    sample = []
    for spbu_id in profile_spbus:
        rows = sorted(observations_by_spbu.get(spbu_id, []), key=lambda row: (row["operation_date"] or "", row["source_shipment_id"]))
        sample.extend(rows[:30])
    return sample


def peak_bucket(minutes: list[int], bucket_minutes: int) -> tuple[int, int]:
    buckets = Counter(int(minute // bucket_minutes * bucket_minutes) for minute in minutes)
    bucket_start, count = sorted(buckets.items(), key=lambda item: (-item[1], item[0]))[0]
    return bucket_start, count


def minute_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def normalize_minute(value: float) -> float:
    return value % 1440


def minute_label(value: float) -> str:
    minute = int(round(value)) % 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def bucket_label(start: int, bucket_minutes: int) -> str:
    return f"{minute_label(start)}-{minute_label((start + bucket_minutes) % 1440)}"


def percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100 / denominator, 1)


def utc_now_label() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
