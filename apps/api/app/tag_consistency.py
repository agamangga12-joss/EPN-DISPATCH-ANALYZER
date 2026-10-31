from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    BridgeMTTag,
    BridgeSPBUTag,
    FactLoadingOrderLine,
    FactShipment,
    MasterDepot,
    MasterMT,
    MasterProduct,
    MasterSPBU,
    MasterTag,
    MasterTagType,
    SpbuIdentifierAlias,
)
from .normalization import clean_str, normalize_key

VEHICLE_CLASS_TAG_TYPE = "VEHICLE_CLASS"
DATA_ISSUE_STATUSES = {"MT_NOT_FOUND", "SPBU_NOT_FOUND", "MT_TAG_INCOMPLETE", "SPBU_TAG_INCOMPLETE", "DATA_ERROR"}


def encode_analysis_id(loading_order_number: str, source_depot_name: str) -> str:
    payload = json.dumps([loading_order_number, source_depot_name], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_analysis_id(analysis_id: str) -> tuple[str, str]:
    padded = analysis_id + "=" * (-len(analysis_id) % 4)
    values = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("Invalid analysis id.")
    return str(values[0]), str(values[1])


def build_tag_consistency_payload(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    depot_id: str | None = None,
    spbu: str | None = None,
    vehicle: str | None = None,
    tag_type: str | None = None,
    overall_status: str | None = None,
    product_id: str | None = None,
    vehicle_class: int | None = None,
    search: str | None = None,
    sort_column: str = "loading_order_date",
    sort_direction: str = "desc",
    limit: int | None = 25,
    offset: int = 0,
) -> dict:
    latest_date = latest_loading_order_date(db, depot_id=depot_id)
    effective_start = start_date
    effective_end = end_date
    if not effective_start and not effective_end and latest_date:
        effective_start = latest_date
        effective_end = latest_date

    rows = load_assignment_rows(
        db,
        start_date=effective_start,
        end_date=effective_end,
        depot_id=depot_id,
        spbu=spbu,
        vehicle=vehicle,
        product_id=product_id,
        vehicle_class=vehicle_class,
    )
    analyses = evaluate_assignment_rows(db, rows)
    analyses = apply_analysis_filters(analyses, tag_type=tag_type, overall_status=overall_status, search=search)
    summary = summarize_analyses(analyses)
    sorted_analyses = sort_analyses(analyses, sort_column, sort_direction)
    limit = max(1, min(limit, 500)) if limit is not None else None
    offset = max(0, offset)
    return {
        "latest_loading_order_date": latest_date.isoformat() if latest_date else None,
        "defaulted_to_latest_date": start_date is None and end_date is None and latest_date is not None,
        "effective_filters": {
            "start_date": effective_start.isoformat() if effective_start else None,
            "end_date": effective_end.isoformat() if effective_end else None,
            "depot_id": depot_id,
            "spbu": spbu,
            "vehicle": vehicle,
            "tag_type": tag_type,
            "overall_status": overall_status,
            "product_id": product_id,
            "vehicle_class": vehicle_class,
            "search": search,
        },
        "summary": summary,
        "total": len(sorted_analyses),
        "limit": limit,
        "offset": offset,
        "rows": sorted_analyses[offset : offset + limit] if limit is not None else sorted_analyses,
    }


def get_tag_consistency_detail(db: Session, analysis_id: str) -> dict | None:
    try:
        loading_order_number, source_depot_name = decode_analysis_id(analysis_id)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    rows = load_assignment_rows(
        db,
        loading_order_number=loading_order_number,
        source_depot_name=source_depot_name,
    )
    analyses = evaluate_assignment_rows(db, rows)
    return analyses[0] if analyses else None


def latest_loading_order_date(db: Session, depot_id: str | None = None) -> date | None:
    stmt = select(func.max(FactShipment.operating_date)).select_from(FactLoadingOrderLine).join(FactShipment, FactShipment.shipment_id == FactLoadingOrderLine.shipment_id)
    if depot_id:
        stmt = stmt.where(FactShipment.depot_id == depot_id)
    return db.scalar(stmt)


def load_assignment_rows(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    depot_id: str | None = None,
    spbu: str | None = None,
    vehicle: str | None = None,
    product_id: str | None = None,
    vehicle_class: int | None = None,
    loading_order_number: str | None = None,
    source_depot_name: str | None = None,
) -> list[tuple[FactLoadingOrderLine, FactShipment | None, MasterMT | None, MasterSPBU | None, MasterDepot | None, MasterProduct | None]]:
    stmt = (
        select(FactLoadingOrderLine, FactShipment, MasterMT, MasterSPBU, MasterDepot, MasterProduct)
        .select_from(FactLoadingOrderLine)
        .outerjoin(FactShipment, FactShipment.shipment_id == FactLoadingOrderLine.shipment_id)
        .outerjoin(MasterMT, MasterMT.mt_id == FactShipment.mt_id)
        .outerjoin(MasterSPBU, MasterSPBU.spbu_id == FactLoadingOrderLine.spbu_id)
        .outerjoin(MasterDepot, MasterDepot.depot_id == FactShipment.depot_id)
        .outerjoin(MasterProduct, MasterProduct.product_id == FactLoadingOrderLine.product_id)
    )
    filters = []
    if start_date:
        filters.append(FactShipment.operating_date >= start_date)
    if end_date:
        filters.append(FactShipment.operating_date <= end_date)
    if depot_id:
        filters.append(FactShipment.depot_id == depot_id)
    if product_id:
        filters.append(FactLoadingOrderLine.product_id == product_id)
    if vehicle_class is not None:
        filters.append(MasterMT.vehicle_type_tag == vehicle_class)
    if loading_order_number and source_depot_name:
        filters.extend([FactLoadingOrderLine.loading_order_number == loading_order_number, FactLoadingOrderLine.source_depot_name == source_depot_name])
    spbu_text = clean_str(spbu)
    if spbu_text:
        normalized_spbu = normalize_key(spbu_text)
        filters.append(
            or_(
                FactLoadingOrderLine.source_spbu_code.ilike(f"%{spbu_text}%"),
                FactLoadingOrderLine.shipto.ilike(f"%{spbu_text}%"),
                MasterSPBU.spbu_code.ilike(f"%{spbu_text}%"),
                MasterSPBU.spbu_name.ilike(f"%{spbu_text}%"),
                MasterSPBU.spbu_id.in_(
                    select(SpbuIdentifierAlias.spbu_id).where(SpbuIdentifierAlias.normalized_identifier.ilike(f"%{normalized_spbu or spbu_text}%"))
                ),
            )
        )
    vehicle_text = clean_str(vehicle)
    if vehicle_text:
        normalized_vehicle = normalize_key(vehicle_text) or vehicle_text
        filters.append(
            or_(
                FactShipment.vehicle_registration.ilike(f"%{vehicle_text}%"),
                MasterMT.vehicle_registration.ilike(f"%{vehicle_text}%"),
                func.upper(FactShipment.vehicle_registration).like(f"%{normalized_vehicle}%"),
                func.upper(MasterMT.vehicle_registration).like(f"%{normalized_vehicle}%"),
            )
        )
    if filters:
        stmt = stmt.where(*filters)
    return db.execute(stmt).all()


def evaluate_assignment_rows(
    db: Session,
    rows: list[tuple[FactLoadingOrderLine, FactShipment | None, MasterMT | None, MasterSPBU | None, MasterDepot | None, MasterProduct | None]],
) -> list[dict]:
    mt_ids = sorted({mt.mt_id for _, _, mt, _, _, _ in rows if mt})
    spbu_ids = sorted({spbu.spbu_id for _, _, _, spbu, _, _ in rows if spbu})
    tag_types = tag_type_lookup(db)
    mt_tags = grouped_entity_tags(db, BridgeMTTag, BridgeMTTag.mt_id, mt_ids, tag_types)
    spbu_tags = grouped_entity_tags(db, BridgeSPBUTag, BridgeSPBUTag.spbu_id, spbu_ids, tag_types)
    analyses = []
    analyzed_at = datetime.now(timezone.utc).isoformat()
    for line, shipment, mt, spbu, depot, product in rows:
        mt = mt or resolve_mt_from_shipment(db, shipment)
        spbu = spbu or resolve_spbu_from_line(db, line)
        details: list[dict] = []
        if not mt:
            overall_status = "MT_NOT_FOUND"
            reason = f"Vehicle {shipment.vehicle_registration if shipment else None} from Loading Order is not found in Master MT."
        elif not spbu:
            overall_status = "SPBU_NOT_FOUND"
            reason = f"SPBU {line.source_spbu_code or line.shipto} from Loading Order is not found in Master SPBU."
        else:
            details = evaluate_mt_spbu_tags(mt, spbu, mt_tags.get(mt.mt_id, {}), spbu_tags.get(spbu.spbu_id, {}), tag_types)
            overall_status, reason = overall_status_from_details(details)
        mismatch_count = sum(1 for detail in details if detail["result"] == "MISMATCH")
        data_issue_count = sum(1 for detail in details if detail["result"] in DATA_ISSUE_STATUSES)
        analyses.append(
            {
                "analysis_id": encode_analysis_id(line.loading_order_number, line.source_depot_name),
                "loading_order_id": encode_analysis_id(line.loading_order_number, line.source_depot_name),
                "loading_order_number": line.loading_order_number,
                "loading_order_date": shipment.operating_date.isoformat() if shipment and shipment.operating_date else None,
                "vehicle_registration": (shipment.vehicle_registration if shipment else None) or (mt.vehicle_registration if mt else None),
                "mt_id": mt.mt_id if mt else None,
                "mt_name": mt.vehicle_name_raw if mt else None,
                "mt_vehicle_class": mt.vehicle_type_tag if mt else None,
                "spbu_id": spbu.spbu_id if spbu else line.spbu_id,
                "spbu_name": spbu.spbu_name if spbu else line.source_spbu_code,
                "spbu_code": spbu.spbu_code if spbu else line.source_spbu_code,
                "spbu_vehicle_class": spbu.vehicle_type_tag if spbu else None,
                "depot": depot.depot_name if depot else line.source_depot_name,
                "depot_id": depot.depot_id if depot else None,
                "product_id": product.product_id if product else line.product_id,
                "product_name": product.product_name if product else line.source_product_name,
                "overall_status": overall_status,
                "overall_group": overall_group(overall_status),
                "mismatch_count": mismatch_count,
                "data_issue_count": data_issue_count,
                "vehicle_class_result": vehicle_class_result(details),
                "tag_match_result": "MISMATCH" if mismatch_count else "MATCH" if overall_status == "MATCH" else overall_status,
                "primary_reason": reason,
                "details": details,
                "analyzed_at": analyzed_at,
            }
        )
    return analyses


def resolve_mt_from_shipment(db: Session, shipment: FactShipment | None) -> MasterMT | None:
    if not shipment:
        return None
    if shipment.mt_id:
        mt = db.get(MasterMT, shipment.mt_id)
        if mt:
            return mt
    normalized = normalize_key(shipment.vehicle_registration)
    if not normalized:
        return None
    return db.scalar(select(MasterMT).where(func.upper(MasterMT.vehicle_registration) == normalized))


def resolve_spbu_from_line(db: Session, line: FactLoadingOrderLine) -> MasterSPBU | None:
    if line.spbu_id:
        spbu = db.get(MasterSPBU, line.spbu_id)
        if spbu:
            return spbu
    normalized_values = [normalize_key(line.source_spbu_code), normalize_key(line.shipto)]
    normalized_values = [value for value in normalized_values if value]
    if not normalized_values:
        return None
    alias_spbu_id = db.scalar(select(SpbuIdentifierAlias.spbu_id).where(SpbuIdentifierAlias.normalized_identifier.in_(normalized_values)).limit(1))
    if alias_spbu_id:
        return db.get(MasterSPBU, alias_spbu_id)
    return db.scalar(select(MasterSPBU).where(func.upper(MasterSPBU.spbu_code).in_(normalized_values)).limit(1))


def tag_type_lookup(db: Session) -> dict[str, MasterTagType]:
    return {tag_type.tag_type_id: tag_type for tag_type in db.scalars(select(MasterTagType)).all()}


def grouped_entity_tags(db: Session, bridge_model: Any, entity_column: Any, entity_ids: list[str], tag_types: dict[str, MasterTagType]) -> dict[str, dict[str, dict[str, str]]]:
    grouped: dict[str, dict[str, dict[str, str]]] = {entity_id: {} for entity_id in entity_ids}
    if not entity_ids:
        return grouped
    rows = db.execute(
        select(entity_column, MasterTag.tag_type_id, MasterTag.tag_value, MasterTag.normalized_tag)
        .select_from(bridge_model)
        .join(MasterTag, MasterTag.tag_id == bridge_model.tag_id)
        .where(entity_column.in_(entity_ids), MasterTag.active_status != "DELETED")
    ).all()
    for entity_id, tag_type_id, tag_value, normalized_tag in rows:
        tag_type = tag_types.get(tag_type_id)
        if not tag_type or tag_type.code == VEHICLE_CLASS_TAG_TYPE:
            continue
        normalized = normalized_tag or normalize_key(tag_value)
        if not normalized:
            continue
        grouped.setdefault(entity_id, {}).setdefault(tag_type.code, {})[normalized] = tag_value
    return grouped


def evaluate_mt_spbu_tags(
    mt: MasterMT,
    spbu: MasterSPBU,
    mt_tags: dict[str, dict[str, str]],
    spbu_tags: dict[str, dict[str, str]],
    tag_types: dict[str, MasterTagType],
) -> list[dict]:
    details = [evaluate_vehicle_class(mt.vehicle_type_tag, spbu.vehicle_type_tag, tag_types)]
    tag_type_codes = sorted(set(mt_tags) | set(spbu_tags), key=lambda code: tag_type_name_by_code(tag_types, code))
    for tag_type_code in tag_type_codes:
        required = spbu_tags.get(tag_type_code, {})
        available = mt_tags.get(tag_type_code, {})
        missing_keys = sorted(set(required) - set(available), key=lambda key: required[key])
        extra_keys = sorted(set(available) - set(required), key=lambda key: available[key])
        if not required:
            result = "MATCH"
            reason = "No SPBU requirement for this tag type."
        elif not available:
            result = "MT_TAG_INCOMPLETE"
            reason = f"MT has no {tag_type_name_by_code(tag_types, tag_type_code)} tags while SPBU has requirements."
        elif missing_keys:
            result = "MISMATCH"
            reason = f"Missing required tag(s): {', '.join(required[key] for key in missing_keys)}."
        else:
            result = "MATCH"
            reason = "All SPBU required tags are available on MT."
        details.append(
            {
                "tag_type": tag_type_code,
                "tag_type_name": tag_type_name_by_code(tag_types, tag_type_code),
                "matching_rule": "GENERIC_TAG_SUBSET",
                "spbu_required_tags": sorted(required.values()),
                "mt_available_tags": sorted(available.values()),
                "missing_tags": [required[key] for key in missing_keys],
                "extra_mt_tags": [available[key] for key in extra_keys],
                "result": result,
                "reason": reason,
            }
        )
    return details


def evaluate_vehicle_class(mt_class: Any, spbu_class: Any, tag_types: dict[str, MasterTagType]) -> dict:
    mt_number = numeric_vehicle_class(mt_class)
    spbu_number = numeric_vehicle_class(spbu_class)
    if mt_class is None:
        result = "MT_TAG_INCOMPLETE"
        reason = "MT vehicle class is missing."
    elif spbu_class is None:
        result = "SPBU_TAG_INCOMPLETE"
        reason = "SPBU maximum vehicle class is missing."
    elif mt_number is None or spbu_number is None:
        result = "DATA_ERROR"
        reason = "Vehicle class cannot be parsed as a number."
    elif mt_number <= spbu_number:
        result = "MATCH"
        reason = f"{mt_number:g} <= {spbu_number:g}."
    else:
        result = "MISMATCH"
        reason = f"MT vehicle class {mt_number:g} exceeds SPBU maximum {spbu_number:g}."
    return {
        "tag_type": VEHICLE_CLASS_TAG_TYPE,
        "tag_type_name": tag_type_name_by_code(tag_types, VEHICLE_CLASS_TAG_TYPE),
        "matching_rule": "VEHICLE_CLASS_MAX",
        "spbu_required_tags": [str(spbu_class)] if spbu_class is not None else [],
        "mt_available_tags": [str(mt_class)] if mt_class is not None else [],
        "missing_tags": [],
        "extra_mt_tags": [],
        "result": result,
        "reason": reason,
        "rule_expression": f"{mt_number:g} <= {spbu_number:g}" if mt_number is not None and spbu_number is not None else None,
    }


def numeric_vehicle_class(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tag_type_name_by_code(tag_types: dict[str, MasterTagType], code: str) -> str:
    for tag_type in tag_types.values():
        if tag_type.code == code:
            return tag_type.name
    return code.replace("_", " ").title()


def overall_status_from_details(details: list[dict]) -> tuple[str, str]:
    for status in ("DATA_ERROR", "SPBU_TAG_INCOMPLETE", "MT_TAG_INCOMPLETE"):
        detail = next((item for item in details if item["result"] == status), None)
        if detail:
            return status, f"{detail['tag_type_name']}: {detail['reason']}"
    mismatch = next((item for item in details if item["result"] == "MISMATCH"), None)
    if mismatch:
        return "MISMATCH", f"{mismatch['tag_type_name']}: {mismatch['reason']}"
    return "MATCH", "All MT capabilities satisfy SPBU requirements."


def vehicle_class_result(details: list[dict]) -> str:
    vehicle_detail = next((detail for detail in details if detail["tag_type"] == VEHICLE_CLASS_TAG_TYPE), None)
    return vehicle_detail["result"] if vehicle_detail else "DATA_ERROR"


def overall_group(status: str) -> str:
    if status == "MATCH":
        return "MATCH"
    if status == "MISMATCH":
        return "MISMATCH"
    return "DATA_ISSUE"


def apply_analysis_filters(analyses: list[dict], *, tag_type: str | None, overall_status: str | None, search: str | None) -> list[dict]:
    filtered = analyses
    normalized_tag_type = clean_str(tag_type)
    if normalized_tag_type and normalized_tag_type != "ALL":
        filtered = [analysis for analysis in filtered if any(detail["tag_type"] == normalized_tag_type for detail in analysis["details"])]
    normalized_status = clean_str(overall_status)
    if normalized_status and normalized_status != "ALL":
        if normalized_status == "DATA_ISSUE":
            filtered = [analysis for analysis in filtered if analysis["overall_status"] in DATA_ISSUE_STATUSES]
        else:
            filtered = [analysis for analysis in filtered if analysis["overall_status"] == normalized_status]
    normalized_search = normalize_key(search)
    if normalized_search:
        filtered = [
            analysis
            for analysis in filtered
            if normalized_search
            in normalize_key(
                " ".join(
                    str(analysis.get(key) or "")
                    for key in ("loading_order_number", "vehicle_registration", "spbu_name", "spbu_code", "depot", "product_name", "primary_reason")
                )
            )
        ]
    return filtered


def summarize_analyses(analyses: list[dict]) -> dict:
    status_counts = Counter(analysis["overall_status"] for analysis in analyses)
    matched = status_counts["MATCH"]
    mismatch = status_counts["MISMATCH"]
    data_issues = sum(count for status, count in status_counts.items() if status in DATA_ISSUE_STATUSES)
    analyzable = matched + mismatch
    mismatch_by_tag_type = Counter()
    mismatch_by_tag_value = Counter()
    data_quality_summary = Counter()
    daily = defaultdict(lambda: {"matched": 0, "mismatch": 0})
    spbu_counts = defaultdict(lambda: {"spbu": "", "total_assignment": 0, "mismatch": 0})
    mt_counts = defaultdict(lambda: {"vehicle_registration": "", "total_assignment": 0, "mismatch": 0})
    for analysis in analyses:
        if analysis["overall_status"] in DATA_ISSUE_STATUSES:
            data_quality_summary[analysis["overall_status"]] += 1
        for detail in analysis["details"]:
            if detail["result"] == "MISMATCH":
                mismatch_by_tag_type[detail["tag_type_name"]] += 1
                for tag_value in missing_tag_values_for_summary(detail):
                    mismatch_by_tag_value[tag_value] += 1
            elif detail["result"] in DATA_ISSUE_STATUSES and analysis["overall_status"] not in DATA_ISSUE_STATUSES:
                data_quality_summary[detail["result"]] += 1
        if analysis["overall_status"] in {"MATCH", "MISMATCH"} and analysis["loading_order_date"]:
            bucket = daily[analysis["loading_order_date"]]
            bucket["matched" if analysis["overall_status"] == "MATCH" else "mismatch"] += 1
        spbu_key = analysis["spbu_id"] or analysis["spbu_code"] or "UNKNOWN"
        spbu_counts[spbu_key]["spbu"] = analysis["spbu_code"] or analysis["spbu_name"] or "UNKNOWN"
        spbu_counts[spbu_key]["total_assignment"] += 1
        spbu_counts[spbu_key]["mismatch"] += int(analysis["overall_status"] == "MISMATCH")
        mt_key = analysis["mt_id"] or analysis["vehicle_registration"] or "UNKNOWN"
        mt_counts[mt_key]["vehicle_registration"] = analysis["vehicle_registration"] or "UNKNOWN"
        mt_counts[mt_key]["total_assignment"] += 1
        mt_counts[mt_key]["mismatch"] += int(analysis["overall_status"] == "MISMATCH")
    return {
        "total_lo_assignments": len(analyses),
        "matched": matched,
        "mismatch": mismatch,
        "data_issues": data_issues,
        "analyzable_lo": analyzable,
        "consistency_rate": round((matched / analyzable) * 100, 2) if analyzable else 0,
        "status_counts": dict(status_counts),
        "mismatch_by_tag_type": [{"name": name, "value": value} for name, value in mismatch_by_tag_type.most_common()],
        "mismatch_by_tag_value": [{"name": name, "value": value} for name, value in mismatch_by_tag_value.most_common(20)],
        "daily_consistency_rate": [
            {
                "name": day,
                "value": round((values["matched"] / (values["matched"] + values["mismatch"])) * 100, 2) if values["matched"] + values["mismatch"] else 0,
            }
            for day, values in sorted(daily.items())
        ],
        "top_spbu_mismatch": ranked_mismatch_rows(spbu_counts.values(), "spbu"),
        "top_mt_mismatch": ranked_mismatch_rows(mt_counts.values(), "vehicle_registration"),
        "data_quality_summary": [{"name": name, "value": value} for name, value in data_quality_summary.most_common()],
    }


def missing_tag_values_for_summary(detail: dict) -> list[str]:
    if detail["missing_tags"]:
        return [str(tag) for tag in detail["missing_tags"] if tag]
    if detail["tag_type"] == VEHICLE_CLASS_TAG_TYPE and detail["spbu_required_tags"]:
        return [f"Vehicle Class > Max {detail['spbu_required_tags'][0]}"]
    return []


def ranked_mismatch_rows(rows: Any, label_key: str) -> list[dict]:
    ranked = []
    for row in rows:
        total = row["total_assignment"]
        mismatch = row["mismatch"]
        ranked.append({**row, "mismatch_rate": round((mismatch / total) * 100, 2) if total else 0})
    return sorted(ranked, key=lambda item: (item["mismatch"], item["mismatch_rate"], item[label_key]), reverse=True)


def sort_analyses(analyses: list[dict], sort_column: str, sort_direction: str) -> list[dict]:
    allowed = {
        "loading_order_date",
        "loading_order_number",
        "vehicle_registration",
        "spbu_name",
        "depot",
        "overall_status",
        "mismatch_count",
        "data_issue_count",
    }
    column = sort_column if sort_column in allowed else "loading_order_date"
    reverse = sort_direction.lower() == "desc"
    return sorted(analyses, key=lambda item: (item.get(column) is None, item.get(column) or ""), reverse=reverse)
