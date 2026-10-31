from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BridgeMTTag, BridgeSPBUTag, MasterMT, MasterSPBU, MasterTag


def evaluate_compatibility_entities(
    mt: MasterMT | None,
    spbu: MasterSPBU | None,
    *,
    mt_tag_ids: set[str] | None = None,
    spbu_tag_ids: set[str] | None = None,
    tag_labels: dict[str, str] | None = None,
    product_id: str | None = None,
    vehicle_mode: str = "MT_CAPACITY_LE_SPBU_LIMIT",
) -> dict:
    """Apply the canonical MT-SPBU rules to already-loaded master entities.

    Both the single-pair API and Phase 5's depot matrix call this function.  Keeping
    the rule evaluation here prevents the readiness gate from developing a second,
    subtly different definition of master compatibility.
    """
    if not mt or not spbu:
        return {
            "compatible": False,
            "vehicle_type_check": "UNKNOWN",
            "project_tag_check": "UNKNOWN",
            "product_check": "NOT_AVAILABLE",
            "depot_check": "UNKNOWN",
            "matched_tags": [],
            "failed_rules": ["MT_OR_SPBU_NOT_FOUND"],
            "warnings": [],
            "explanation": "MT or SPBU does not exist in canonical master data.",
        }

    failed_rules: list[str] = []
    warnings: list[str] = []

    if vehicle_mode == "EXACT_MATCH":
        vehicle_ok = bool(mt.vehicle_type_tag and spbu.vehicle_type_tag and str(mt.vehicle_type_tag) == str(spbu.vehicle_type_tag))
        vehicle_check = "PASS" if vehicle_ok else "FAIL"
    elif vehicle_mode == "MT_CAPACITY_LE_SPBU_LIMIT":
        try:
            vehicle_ok = float(mt.vehicle_type_tag or 0) <= float(spbu.vehicle_type_tag or 0)
        except (TypeError, ValueError):
            vehicle_ok = False
        vehicle_check = "PASS" if vehicle_ok else "FAIL"
    else:
        vehicle_ok = False
        vehicle_check = "UNKNOWN_MODE"
        warnings.append(f"Unsupported vehicle compatibility mode: {vehicle_mode}")
    if not vehicle_ok:
        failed_rules.append("VEHICLE_TYPE")

    effective_mt_tags = mt_tag_ids or set()
    effective_spbu_tags = spbu_tag_ids or set()
    missing_spbu_required_tags = effective_spbu_tags - effective_mt_tags
    project_ok = len(missing_spbu_required_tags) == 0
    if not project_ok:
        failed_rules.append("PROJECT_TAGS")
    labels = tag_labels or {}
    matched_tags = [labels.get(tag_id, tag_id) for tag_id in sorted(effective_mt_tags & effective_spbu_tags)]

    if mt.depot_id and spbu.primary_depot_id:
        depot_ok = mt.depot_id == spbu.primary_depot_id
        depot_check = "PASS" if depot_ok else "FAIL"
        if not depot_ok:
            failed_rules.append("DEPOT")
    else:
        depot_check = "INSUFFICIENT_DATA"
        warnings.append("Depot is missing on MT or SPBU.")

    product_check = "NOT_AVAILABLE" if product_id is None else "INSUFFICIENT_DATA"
    if product_id:
        warnings.append("Product compatibility rules are configured but no explicit product rule table exists yet.")

    compatible = vehicle_ok and project_ok and depot_check in {"PASS", "INSUFFICIENT_DATA"}
    explanation = "Compatible by active Phase 0 master rules." if compatible else f"Incompatible by: {', '.join(failed_rules)}."
    return {
        "compatible": compatible,
        "vehicle_type_check": vehicle_check,
        "project_tag_check": "PASS" if project_ok else "FAIL",
        "product_check": product_check,
        "depot_check": depot_check,
        "matched_tags": matched_tags,
        "mt_vehicle_class": mt.vehicle_type_tag,
        "spbu_vehicle_class": spbu.vehicle_type_tag,
        "vehicle_mode": vehicle_mode,
        "required_tags": [labels.get(tag_id, tag_id) for tag_id in sorted(effective_spbu_tags)],
        "available_tags": [labels.get(tag_id, tag_id) for tag_id in sorted(effective_mt_tags)],
        "missing_tags": [labels.get(tag_id, tag_id) for tag_id in sorted(missing_spbu_required_tags)],
        "failed_rules": failed_rules,
        "warnings": warnings,
        "explanation": explanation,
    }


def evaluate_mt_spbu_compatibility(
    db: Session,
    mt_id: str,
    spbu_id: str,
    product_id: str | None = None,
    vehicle_mode: str = "MT_CAPACITY_LE_SPBU_LIMIT",
) -> dict:
    mt = db.get(MasterMT, mt_id)
    spbu = db.get(MasterSPBU, spbu_id)
    mt_tag_ids = {row[0] for row in db.execute(select(BridgeMTTag.tag_id).where(BridgeMTTag.mt_id == mt_id)).all()}
    spbu_tag_ids = {row[0] for row in db.execute(select(BridgeSPBUTag.tag_id).where(BridgeSPBUTag.spbu_id == spbu_id)).all()}
    matched_tag_ids = sorted(mt_tag_ids & spbu_tag_ids)
    tags = db.scalars(select(MasterTag).where(MasterTag.tag_id.in_(matched_tag_ids))).all() if matched_tag_ids else []
    return evaluate_compatibility_entities(
        mt,
        spbu,
        mt_tag_ids=mt_tag_ids,
        spbu_tag_ids=spbu_tag_ids,
        tag_labels={tag.tag_id: tag.tag_value for tag in tags},
        product_id=product_id,
        vehicle_mode=vehicle_mode,
    )


def build_depot_compatibility_matrix(
    db: Session,
    depot_id: str,
    *,
    vehicle_mode: str = "MT_CAPACITY_LE_SPBU_LIMIT",
    issue_limit: int = 25,
) -> dict:
    """Evaluate the active master assignment space for one depot in batched form."""
    mts = db.scalars(
        select(MasterMT).where(MasterMT.depot_id == depot_id, MasterMT.active_status == "ACTIVE").order_by(MasterMT.mt_id)
    ).all()
    spbus = db.scalars(
        select(MasterSPBU).where(MasterSPBU.primary_depot_id == depot_id, MasterSPBU.active_status == "ACTIVE").order_by(MasterSPBU.spbu_id)
    ).all()
    mt_ids = [mt.mt_id for mt in mts]
    spbu_ids = [spbu.spbu_id for spbu in spbus]
    mt_tags: dict[str, set[str]] = defaultdict(set)
    spbu_tags: dict[str, set[str]] = defaultdict(set)
    if mt_ids:
        for entity_id, tag_id in db.execute(select(BridgeMTTag.mt_id, BridgeMTTag.tag_id).where(BridgeMTTag.mt_id.in_(mt_ids))).all():
            mt_tags[entity_id].add(tag_id)
    if spbu_ids:
        for entity_id, tag_id in db.execute(select(BridgeSPBUTag.spbu_id, BridgeSPBUTag.tag_id).where(BridgeSPBUTag.spbu_id.in_(spbu_ids))).all():
            spbu_tags[entity_id].add(tag_id)
    all_tag_ids = sorted({tag_id for values in mt_tags.values() for tag_id in values} | {tag_id for values in spbu_tags.values() for tag_id in values})
    tag_labels = {
        tag.tag_id: tag.tag_value
        for tag in (db.scalars(select(MasterTag).where(MasterTag.tag_id.in_(all_tag_ids))).all() if all_tag_ids else [])
    }

    compatible_by_spbu: dict[str, list[str]] = defaultdict(list)
    issue_examples: list[dict] = []
    failure_counts: dict[str, int] = defaultdict(int)
    passed = 0
    total = len(mts) * len(spbus)
    for spbu in spbus:
        for mt in mts:
            result = evaluate_compatibility_entities(
                mt,
                spbu,
                mt_tag_ids=mt_tags.get(mt.mt_id, set()),
                spbu_tag_ids=spbu_tags.get(spbu.spbu_id, set()),
                tag_labels=tag_labels,
                vehicle_mode=vehicle_mode,
            )
            if result["compatible"]:
                passed += 1
                compatible_by_spbu[spbu.spbu_id].append(mt.mt_id)
                continue
            for rule in result["failed_rules"]:
                failure_counts[rule] += 1
            if len(issue_examples) < issue_limit:
                issue_examples.append(
                    {
                        "mt_id": mt.mt_id,
                        "vehicle_registration": mt.vehicle_registration,
                        "spbu_id": spbu.spbu_id,
                        "spbu_code": spbu.spbu_code,
                        "failed_rules": result["failed_rules"],
                        "explanation": result["explanation"],
                    }
                )
    percentage = round(100.0 * passed / total, 2) if total else 0.0
    return {
        "depot_id": depot_id,
        "active_mt_count": len(mts),
        "active_spbu_count": len(spbus),
        "evaluated_pair_count": total,
        "passed_pair_count": passed,
        "failed_pair_count": total - passed,
        "master_compatibility_pass_percentage": percentage,
        "is_ready": bool(total) and passed == total,
        "compatible_mt_ids_by_spbu": dict(compatible_by_spbu),
        "failure_counts": dict(sorted(failure_counts.items())),
        "issue_examples": issue_examples,
        "vehicle_compatibility_mode": vehicle_mode,
        "rule_source": "app.compatibility.evaluate_compatibility_entities",
    }
