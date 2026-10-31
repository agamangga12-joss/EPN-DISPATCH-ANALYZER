from __future__ import annotations

import hashlib
import itertools
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .compatibility import evaluate_compatibility_entities
from .config import get_settings
from .models import (
    BridgeMTTag,
    BridgeSPBUTag,
    FactSPBUMTPair,
    MLBehavioralModel,
    MLModelArtifact,
    MLSPBUClusterAssignment,
    MasterDepot,
    MasterMT,
    MasterSPBU,
    MasterTag,
)
from .phase6_capacity import capacity_compatible, shipment_capacity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _routing_context(db: Session, model: MLBehavioralModel) -> dict:
    depot = db.get(MasterDepot, model.depot_id)
    spbus = db.scalars(
        select(MasterSPBU).where(
            MasterSPBU.primary_depot_id == model.depot_id,
            MasterSPBU.active_status == "ACTIVE",
        )
    ).all()
    return {
        "depot": {
            "latitude": float(depot.latitude) if depot and depot.latitude is not None else None,
            "longitude": float(depot.longitude) if depot and depot.longitude is not None else None,
        },
        "spbus": {
            spbu.spbu_id: {
                "latitude": float(spbu.latitude) if spbu.latitude is not None else None,
                "longitude": float(spbu.longitude) if spbu.longitude is not None else None,
                "master_distance_km": float(spbu.master_distance_km) if spbu.master_distance_km is not None else None,
            }
            for spbu in spbus
        },
        "source": "MASTER_DEPOT_AND_SPBU_COORDINATES",
    }


def load_model_inference_evidence(db: Session, model: MLBehavioralModel) -> dict:
    """Load and verify the immutable Phase 5 package used for inference."""
    artifact = db.scalar(
        select(MLModelArtifact).where(
            MLModelArtifact.model_id == model.model_id,
            MLModelArtifact.artifact_type == "JOBLIB_MODEL_PACKAGE",
        )
    )
    if artifact:
        path = (get_settings().ml_artifact_dir.resolve() / artifact.storage_uri).resolve()
        root = get_settings().ml_artifact_dir.resolve()
        if root not in path.parents or not path.exists() or _sha256(path) != artifact.checksum_sha256:
            raise HTTPException(status_code=500, detail={"code": "INFERENCE_FAILED", "message": "Phase 5 model artifact failed integrity verification."})
        try:
            import joblib

            bundle = joblib.load(path)
            return {
                "assignments": bundle.get("assignments", []),
                "cluster_profiles": bundle.get("cluster_profiles", []),
                "routing_context": _routing_context(db, model),
                "artifact_checksum": artifact.checksum_sha256,
                "artifact_source": "VERIFIED_JOBLIB_MODEL_PACKAGE",
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail={"code": "INFERENCE_FAILED", "message": "Phase 5 model artifact could not be loaded."}) from exc

    # Registry rows are the normalized persisted representation of the same saved
    # Phase 5 result and keep older development databases usable.
    rows = db.scalars(
        select(MLSPBUClusterAssignment)
        .where(MLSPBUClusterAssignment.model_id == model.model_id)
        .order_by(MLSPBUClusterAssignment.spbu_id)
    ).all()
    if not rows:
        raise HTTPException(status_code=500, detail={"code": "INFERENCE_FAILED", "message": "Selected model has no saved inference assignments."})
    return {
        "assignments": [
            {
                "spbu_id": row.spbu_id,
                "cluster_id": row.cluster_id,
                "membership_probability": row.membership_probability,
                "projection_confidence": row.projection_confidence,
                "cluster_assignment_type": row.cluster_assignment_type,
                "is_noise": row.is_noise,
                "dominant_shift": row.dominant_shift,
            }
            for row in rows
        ],
        "cluster_profiles": [],
        "routing_context": _routing_context(db, model),
        "artifact_checksum": None,
        "artifact_source": "NORMALIZED_MODEL_REGISTRY",
    }


def confidence_level(score: float, parameters: dict) -> str:
    if score >= float(parameters["high_confidence_threshold"]):
        return "HIGH"
    if score >= float(parameters["medium_confidence_threshold"]):
        return "MEDIUM"
    return "LOW"


def _phase5_assignment_confidence(assignment: dict | None) -> float:
    if not assignment:
        return 0.0
    membership = assignment.get("membership_probability")
    if membership is not None:
        return max(0.0, float(membership))
    projection = assignment.get("projection_confidence")
    if assignment.get("cluster_assignment_type") == "MARGINAL_PROJECTED" and projection is not None:
        return max(0.0, float(projection))
    return 0.0


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    latitude_1, longitude_1 = map(math.radians, first)
    latitude_2, longitude_2 = map(math.radians, second)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1
    value = math.sin(delta_latitude / 2) ** 2 + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    return 6_371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def _route_feasibility(
    rows: list[dict],
    group: frozenset[int],
    routing_context: dict,
    *,
    maximum_detour_ratio: float,
) -> dict:
    depot = routing_context.get("depot") or {}
    depot_coordinates = (
        (float(depot["latitude"]), float(depot["longitude"]))
        if depot.get("latitude") is not None and depot.get("longitude") is not None
        else None
    )
    unique_spbu_ids = list(dict.fromkeys(rows[index]["spbu_id"] for index in sorted(group)))
    spbu_context = routing_context.get("spbus") or {}
    coordinates = []
    for spbu_id in unique_spbu_ids:
        point = spbu_context.get(spbu_id) or {}
        if point.get("latitude") is None or point.get("longitude") is None:
            return {
                "route_feasible": True,
                "route_score": 0.5,
                "route_detour_ratio": None,
                "approximate_route_km": None,
                "route_evidence_source": "MISSING_MASTER_COORDINATE_NEUTRAL_SCORE",
            }
        coordinates.append((spbu_id, (float(point["latitude"]), float(point["longitude"]))))
    if not depot_coordinates or not coordinates:
        return {
            "route_feasible": True,
            "route_score": 0.5,
            "route_detour_ratio": None,
            "approximate_route_km": None,
            "route_evidence_source": "MISSING_DEPOT_COORDINATE_NEUTRAL_SCORE",
        }
    ordered = sorted(coordinates, key=lambda item: (_haversine_km(depot_coordinates, item[1]), item[0]))
    route_km = 0.0
    previous = depot_coordinates
    for _spbu_id, coordinate in ordered:
        route_km += _haversine_km(previous, coordinate)
        previous = coordinate
    route_km += _haversine_km(previous, depot_coordinates)
    farthest_km = max(_haversine_km(depot_coordinates, coordinate) for _spbu_id, coordinate in ordered)
    detour_ratio = route_km / max(0.001, farthest_km * 2)
    route_score = max(0.0, min(1.0, (maximum_detour_ratio - detour_ratio) / max(0.001, maximum_detour_ratio - 1.0)))
    return {
        "route_feasible": detour_ratio <= maximum_detour_ratio,
        "route_score": round(route_score, 6),
        "route_detour_ratio": round(detour_ratio, 6),
        "approximate_route_km": round(route_km, 3),
        "route_evidence_source": "MASTER_COORDINATE_NEAREST_TO_FARTHEST_APPROXIMATION",
    }


def _group_metrics(
    rows: list[dict],
    group: frozenset[int],
    edge_explanations: dict[frozenset[int], dict],
    routing_context: dict,
    *,
    maximum_gap_seconds: int,
    maximum_compartments: int,
    maximum_detour_ratio: float,
) -> dict:
    capacity = shipment_capacity([rows[index] for index in sorted(group)])
    pair_keys = [frozenset(pair) for pair in itertools.combinations(sorted(group), 2)]
    observed = [edge_explanations[pair] for pair in pair_keys if pair in edge_explanations]
    pair_coverage = len(observed) / len(pair_keys) if pair_keys else 1.0
    model_score = sum(float(item["normalized_model_score"]) for item in observed) / len(observed) if observed else 0.0
    datetimes = [datetime.fromisoformat(rows[index]["shipment_start_datetime"]) for index in group]
    span_seconds = (max(datetimes) - min(datetimes)).total_seconds() if len(datetimes) > 1 else 0.0
    time_score = 1.0 if maximum_gap_seconds <= 0 else max(0.0, 1.0 - span_seconds / maximum_gap_seconds)
    route = _route_feasibility(
        rows,
        group,
        routing_context,
        maximum_detour_ratio=maximum_detour_ratio,
    )
    distinct_spbu_count = len({rows[index]["spbu_id"] for index in group})
    optimizer_value = (
        1_000.0 * (len(group) - 1)
        + 25.0 * distinct_spbu_count
        + 20.0 * model_score
        + 15.0 * time_score
        + 15.0 * float(route["route_score"])
        + 5.0 * pair_coverage
        + 5.0 * (float(capacity["required_compartments"]) / maximum_compartments)
    )
    return {
        "capacity_valid": bool(capacity["valid"] and capacity["required_compartments"] <= maximum_compartments),
        "required_compartments": int(capacity["required_compartments"]),
        "model_score": round(model_score, 6),
        "pair_coverage": round(pair_coverage, 6),
        "time_span_minutes": round(span_seconds / 60, 3),
        "time_score": round(time_score, 6),
        "distinct_spbu_count": distinct_spbu_count,
        "optimizer_value": round(optimizer_value, 6),
        **route,
    }


def _optimized_capacity_time_route_groups(
    rows: list[dict],
    edge_explanations: dict[frozenset[int], dict],
    routing_context: dict,
    *,
    minimum_score: float,
    maximum_gap_seconds: int,
    maximum_compartments: int,
    maximum_detour_ratio: float,
    target_compartments: int | None = None,
    group_feasibility: Callable[[list[dict]], bool] | None = None,
) -> tuple[list[list[int]], dict[frozenset[int], dict], str]:
    """Select disjoint multi-LO groups through binary set-packing optimization.

    Connected groups may use indirect model evidence; every pair no longer has
    to form a complete clique. Capacity, group score, time span, distinct SPBU,
    and an approximate nearest-to-farthest depot route are evaluated together.
    """
    adjacency: dict[int, set[int]] = defaultdict(set)
    for edge in edge_explanations:
        left, right = tuple(edge)
        adjacency[left].add(right)
        adjacency[right].add(left)

    candidate_metrics: dict[frozenset[int], dict] = {}
    selectable_groups: set[frozenset[int]] = set()
    beam_width = 48
    for seed in range(len(rows)):
        frontier = [frozenset((seed,))]
        for _target_size in range(2, maximum_compartments + 1):
            expanded: set[frozenset[int]] = set()
            for group in frontier:
                neighbors = sorted(
                    {
                        neighbor
                        for member in group
                        for neighbor in adjacency.get(member, set())
                        if neighbor not in group and neighbor > seed
                    }
                )
                for neighbor in neighbors:
                    combined = frozenset((*group, neighbor))
                    if min(combined) != seed:
                        continue
                    metrics = _group_metrics(
                        rows,
                        combined,
                        edge_explanations,
                        routing_context,
                        maximum_gap_seconds=maximum_gap_seconds,
                        maximum_compartments=maximum_compartments,
                        maximum_detour_ratio=maximum_detour_ratio,
                    )
                    if (
                        not metrics["capacity_valid"]
                        or not metrics["route_feasible"]
                        or metrics["time_span_minutes"] * 60 > maximum_gap_seconds
                        or metrics["model_score"] < minimum_score
                    ):
                        continue
                    candidate_metrics[combined] = metrics
                    expanded.add(combined)
                    is_target_capacity = (
                        target_compartments is None
                        or metrics["required_compartments"] == target_compartments
                    )
                    operationally_feasible = bool(
                        is_target_capacity
                        and (
                            group_feasibility is None
                            or group_feasibility([rows[index] for index in sorted(combined)])
                        )
                    )
                    metrics["operational_mt_feasible"] = operationally_feasible
                    if operationally_feasible:
                        selectable_groups.add(combined)
            frontier = sorted(
                expanded,
                key=lambda group: (-candidate_metrics[group]["optimizer_value"], tuple(sorted(group))),
            )[:beam_width]
            if not frontier:
                break

    candidates = sorted(
        selectable_groups,
        key=lambda group: (-candidate_metrics[group]["optimizer_value"], tuple(sorted(group))),
    )[:10_000]
    selected: list[frozenset[int]] = []
    method = "SCIPY_MILP_SET_PACKING"
    if candidates:
        try:
            import numpy as np
            from scipy.optimize import Bounds, LinearConstraint, milp
            from scipy.sparse import coo_array

            row_indices = []
            column_indices = []
            values = []
            for column, group in enumerate(candidates):
                for row in group:
                    row_indices.append(row)
                    column_indices.append(column)
                    values.append(1.0)
            matrix = coo_array((values, (row_indices, column_indices)), shape=(len(rows), len(candidates))).tocsc()
            result = milp(
                c=-np.asarray([candidate_metrics[group]["optimizer_value"] for group in candidates]),
                integrality=np.ones(len(candidates)),
                bounds=Bounds(0, 1),
                constraints=LinearConstraint(matrix, 0, 1),
                options={"time_limit": 5.0, "mip_rel_gap": 0.001},
            )
            if result.x is not None:
                selected = [group for index, group in enumerate(candidates) if result.x[index] >= 0.5]
            else:
                raise RuntimeError("MILP returned no feasible selection")
        except Exception:
            method = "DETERMINISTIC_GREEDY_SET_PACKING_FALLBACK"
            occupied: set[int] = set()
            for group in candidates:
                if occupied.isdisjoint(group):
                    selected.append(group)
                    occupied.update(group)

    occupied = {index for group in selected for index in group}
    groups = [sorted(group) for group in selected]
    groups.extend([[index] for index in range(len(rows)) if index not in occupied])
    return groups, candidate_metrics, method


def predict_shipments(
    loading_orders: list[dict], model: MLBehavioralModel, evidence: dict, parameters: dict
) -> list[dict]:
    assignments = {row["spbu_id"]: row for row in evidence["assignments"]}
    pairing_by_codes: dict[frozenset[str], float] = {}
    for profile in evidence.get("cluster_profiles", []):
        for pair in profile.get("inference_internal_pairings") or profile.get("top_internal_pairings", []):
            pairing_by_codes[frozenset((str(pair["spbu_a_code"]), str(pair["spbu_b_code"])))] = float(pair["pairing_strength"])
    raw_weights = {**{"tag": 0.4, "shift": 0.25, "pairing": 0.35}, **(model.feature_weights or {})}
    behavioral_total = sum(float(raw_weights[key]) for key in ("tag", "shift", "pairing")) or 1.0
    weights = {key: float(raw_weights[key]) / behavioral_total for key in ("tag", "shift", "pairing")}
    by_shift: dict[str, list[dict]] = defaultdict(list)
    for row in loading_orders:
        by_shift[row["shift_id"]].append(row)
    shipments: list[dict] = []
    minimum = float(parameters["minimum_prediction_confidence"])
    maximum_gap_seconds = int(parameters.get("maximum_pairing_time_gap_minutes", 90)) * 60
    maximum_compartments = int(parameters.get("maximum_shipment_compartments", 4))
    maximum_detour_ratio = float(parameters.get("maximum_group_route_detour_ratio", 2.0))
    target_compartments = parameters.get("target_shipment_compartments")
    target_compartments = int(target_compartments) if target_compartments is not None else None
    group_feasibility = parameters.get("_group_feasibility")
    routing_context = evidence.get("routing_context") or {}
    for shift_id in sorted(by_shift):
        rows = sorted(by_shift[shift_id], key=lambda row: (row["shipment_start_datetime"], row["spbu_no"], row["loading_order_no"]))
        edge_explanations: dict[frozenset[int], dict] = {}
        for left in range(len(rows)):
            for right in range(left + 1, len(rows)):
                first_datetime = datetime.fromisoformat(rows[left]["shipment_start_datetime"])
                second_datetime = datetime.fromisoformat(rows[right]["shipment_start_datetime"])
                time_gap_seconds = abs((second_datetime - first_datetime).total_seconds())
                if time_gap_seconds > maximum_gap_seconds:
                    continue
                first, second = assignments.get(rows[left]["spbu_id"]), assignments.get(rows[right]["spbu_id"])
                if not first or not second or first.get("is_noise") or second.get("is_noise") or first.get("cluster_id") != second.get("cluster_id"):
                    continue
                cluster_match = math.sqrt(_phase5_assignment_confidence(first) * _phase5_assignment_confidence(second))
                shift_match = (
                    float((first.get("dominant_shift") == rows[left]["shift"]) + (second.get("dominant_shift") == rows[right]["shift"])) / 2.0
                )
                historical_pairing = pairing_by_codes.get(frozenset((rows[left]["spbu_no"], rows[right]["spbu_no"])), 0.0)
                score = round(
                    weights["tag"] * cluster_match + weights["shift"] * shift_match + weights["pairing"] * historical_pairing,
                    6,
                )
                if score >= minimum:
                    edge_explanations[frozenset((left, right))] = {
                        "cluster_match": "same cluster",
                        "cluster_membership_component": round(cluster_match, 6),
                        "historical_pairing_strength": historical_pairing,
                        "shift_match": round(shift_match, 6),
                        "feature_weights": weights,
                        "normalized_model_score": score,
                        "pairing_time_gap_minutes": round(time_gap_seconds / 60, 3),
                        "maximum_pairing_time_gap_minutes": maximum_gap_seconds // 60,
                    }
        groups, group_metrics, optimizer_method = _optimized_capacity_time_route_groups(
            rows,
            edge_explanations,
            routing_context,
            minimum_score=minimum,
            maximum_gap_seconds=maximum_gap_seconds,
            maximum_compartments=maximum_compartments,
            maximum_detour_ratio=maximum_detour_ratio,
            target_compartments=target_compartments,
            group_feasibility=group_feasibility,
        )
        groups.sort(key=lambda group: (max(rows[index]["shipment_start_datetime"] for index in group), min(rows[index]["loading_order_no"] for index in group)))
        for number, group in enumerate(groups, start=1):
            selected_rows = [rows[index] for index in group]
            planned_start = max(datetime.fromisoformat(row["shipment_start_datetime"]) for row in selected_rows)
            if len(group) > 1:
                pair_evidence = []
                for left, right in itertools.combinations(group, 2):
                    edge = edge_explanations.get(frozenset((left, right)))
                    pair_evidence.append(
                        {
                            "loading_order_a": rows[left]["loading_order_no"],
                            "loading_order_b": rows[right]["loading_order_no"],
                            "evidence_status": "DIRECT_ELIGIBLE_PAIR" if edge else "INDIRECT_CONNECTED_GROUP",
                            **(edge or {"normalized_model_score": None}),
                        }
                    )
                metrics = group_metrics[frozenset(group)]
                score = float(metrics["model_score"])
                explanation = {
                    "grouping_method": "CAPACITY_TIME_ROUTE_SET_PACKING",
                    "optimizer_method": optimizer_method,
                    "normalized_model_score": score,
                    "group_optimization": metrics,
                    "pair_evidence": pair_evidence,
                }
            else:
                assignment = assignments.get(selected_rows[0]["spbu_id"])
                score = round(_phase5_assignment_confidence(assignment), 6)
                if not assignment:
                    model_coverage = "UNSEEN_SPBU"
                elif assignment.get("is_noise"):
                    model_coverage = "NOISE_SPBU"
                else:
                    model_coverage = assignment.get("coverage_source", "BEHAVIORAL_HISTORY")
                explanation = {
                    "single_spbu_reason": "No capacity-, score-, time-, and route-feasible optimized grouping was selected.",
                    "cluster_membership_probability": score if assignment else None,
                    "model_coverage": model_coverage,
                }
            capacity = shipment_capacity(selected_rows)
            shipment_number = f"PRED-{shift_id.upper()}-{number:03d}"
            shipments.append(
                {
                    "predicted_shipment_id": shipment_number,
                    "shift_id": shift_id,
                    "shift": selected_rows[0]["shift"],
                    "planned_start_datetime": planned_start,
                    "score": score,
                    "confidence_level": confidence_level(score, parameters),
                    "low_confidence": score < minimum,
                    "lines": selected_rows,
                    "explanation": {
                        **explanation,
                        "loading_order_count": capacity["loading_order_count"],
                        "total_order_kl": capacity["total_order_kl"],
                        "required_compartments": capacity["required_compartments"],
                        "compartment_unit_kl": capacity["compartment_unit_kl"],
                        "maximum_shipment_compartments": maximum_compartments,
                        "model_id": model.model_id,
                        "model_version": model.model_version,
                    },
                }
            )
    shipments.sort(key=lambda shipment: (shipment["planned_start_datetime"], shipment["predicted_shipment_id"]))
    for number, shipment in enumerate(shipments, start=1):
        shipment["predicted_shipment_id"] = f"PRED-SHIP-{number:04d}"
    return shipments


def predict_mt_candidates(
    db: Session,
    *,
    depot_id: str,
    shipments: list[dict],
    availability: list[dict],
    vehicle_compatibility_mode: str,
    require_full_utilization: bool = True,
) -> dict[str, list[dict]]:
    vehicle_ids = sorted({row["vehicle_id"] for row in availability})
    spbu_ids = sorted({line["spbu_id"] for shipment in shipments for line in shipment["lines"]})
    mts = {row.mt_id: row for row in (db.scalars(select(MasterMT).where(MasterMT.mt_id.in_(vehicle_ids))).all() if vehicle_ids else [])}
    spbus = {row.spbu_id: row for row in (db.scalars(select(MasterSPBU).where(MasterSPBU.spbu_id.in_(spbu_ids))).all() if spbu_ids else [])}
    mt_tags: dict[str, set[str]] = defaultdict(set)
    spbu_tags: dict[str, set[str]] = defaultdict(set)
    if vehicle_ids:
        for vehicle_id, tag_id in db.execute(select(BridgeMTTag.mt_id, BridgeMTTag.tag_id).where(BridgeMTTag.mt_id.in_(vehicle_ids))).all():
            mt_tags[vehicle_id].add(tag_id)
    if spbu_ids:
        for spbu_id, tag_id in db.execute(select(BridgeSPBUTag.spbu_id, BridgeSPBUTag.tag_id).where(BridgeSPBUTag.spbu_id.in_(spbu_ids))).all():
            spbu_tags[spbu_id].add(tag_id)

    tag_ids = set().union(*mt_tags.values(), *spbu_tags.values())
    tag_labels = {row.tag_id: row.tag_value for row in db.scalars(select(MasterTag).where(MasterTag.tag_id.in_(tag_ids))).all()} if tag_ids else {}

    affinity_rows = db.scalars(
        select(FactSPBUMTPair).where(
            FactSPBUMTPair.depot_id == depot_id,
            FactSPBUMTPair.spbu_id.in_(spbu_ids),
            FactSPBUMTPair.mt_id.in_(vehicle_ids),
        )
    ).all() if spbu_ids and vehicle_ids else []
    latest_affinity: dict[tuple[str, str], FactSPBUMTPair] = {}
    spbu_totals: dict[str, int] = defaultdict(int)
    for row in sorted(affinity_rows, key=lambda item: (item.analysis_end_date, str(item.calculated_at or ""))):
        latest_affinity[(row.spbu_id, row.mt_id)] = row
        spbu_totals[row.spbu_id] = max(spbu_totals[row.spbu_id], row.total_spbu_shipment_count)

    result: dict[str, list[dict]] = {}
    for shipment in shipments:
        candidates = []
        for vehicle_id in vehicle_ids:
            mt = mts[vehicle_id]
            capacity_check = capacity_compatible(
                shipment["lines"],
                mt,
                require_full_utilization=require_full_utilization,
            )
            checks = [
                evaluate_compatibility_entities(
                    mt,
                    spbus[line["spbu_id"]],
                    mt_tag_ids=mt_tags.get(vehicle_id, set()),
                    spbu_tag_ids=spbu_tags.get(line["spbu_id"], set()),
                    vehicle_mode=vehicle_compatibility_mode,
                    tag_labels=tag_labels,
                )
                for line in shipment["lines"]
            ]
            master_compatible = all(check["compatible"] for check in checks)
            compatible = master_compatible and capacity_check["compatible"]
            affinity_components = []
            evidence_confidence = []
            for line in shipment["lines"]:
                affinity = latest_affinity.get((line["spbu_id"], vehicle_id))
                total = spbu_totals.get(line["spbu_id"], 0)
                # Laplace smoothing is deterministic and avoids inventing a high
                # affinity when a compatible vehicle has no historical use.
                affinity_components.append(((affinity.shipment_count if affinity else 0) + 1) / (total + max(1, len(vehicle_ids))))
                evidence_confidence.append(float(affinity.confidence_score) / 100.0 if affinity else 0.0)
            prediction_score = round(sum(affinity_components) / len(affinity_components), 6)
            failed_rules = sorted(
                {rule for check in checks for rule in check["failed_rules"]}
                | set(capacity_check["failed_rules"])
            )
            if not capacity_check["compatible"]:
                exclusion_reason = "CAPACITY_COMPARTMENT_MISMATCH"
            elif not master_compatible:
                exclusion_reason = "MASTER_COMPATIBILITY_FAIL"
            else:
                exclusion_reason = None
            candidates.append(
                {
                    "vehicle_id": vehicle_id,
                    "vehicle_registration_no": mt.vehicle_registration or mt.mt_id,
                    "prediction_score": prediction_score,
                    "compatibility_status": "PASS" if compatible else "FAIL",
                    "candidate_rank": None,
                    "exclusion_reason": exclusion_reason,
                    "explanation": {
                        "historical_mt_affinity": round(sum(affinity_components) / len(affinity_components), 6),
                        "historical_evidence_confidence": round(sum(evidence_confidence) / len(evidence_confidence), 6),
                        "score_method": "mean Laplace-smoothed Phase 4 P(MT|SPBU)",
                        "master_compatibility": "PASS" if master_compatible else "FAIL",
                        "master_checks": [
                            {"spbu_id": line["spbu_id"], "spbu_code": spbus[line["spbu_id"]].spbu_code, **check}
                            for line, check in zip(shipment["lines"], checks)
                        ],
                        "capacity_compatibility": "PASS" if capacity_check["compatible"] else "FAIL",
                        "capacity_policy": capacity_check["utilization_policy"],
                        "shipment_total_kl": capacity_check["shipment"]["total_order_kl"],
                        "shipment_required_compartments": capacity_check["shipment"]["required_compartments"],
                        "mt_capacity_kl": capacity_check["vehicle"]["capacity_kl"],
                        "mt_number_of_compartments": capacity_check["vehicle"]["effective_compartments"],
                        "mt_compartment_source": capacity_check["vehicle"]["compartment_source"],
                        "failed_rules": failed_rules,
                        "availability": "Evaluated dynamically by rolling vehicle state.",
                        "initial_available_datetime": next(
                            row["initial_available_datetime"] for row in availability if row["vehicle_id"] == vehicle_id
                        ),
                    },
                }
            )
        compatible_rows = sorted(
            (candidate for candidate in candidates if candidate["compatibility_status"] == "PASS"),
            key=lambda candidate: (-candidate["prediction_score"], candidate["vehicle_registration_no"]),
        )
        for rank, candidate in enumerate(compatible_rows, start=1):
            candidate["candidate_rank"] = rank
        result[shipment["predicted_shipment_id"]] = candidates
    return result
