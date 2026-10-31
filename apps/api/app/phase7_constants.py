from __future__ import annotations

import math


PHASE7_ALGORITHM_VERSION = "phase7.dynamic_multitrip_vrp_bay.v9"

JOB_STATUSES = {"DRAFT", "READY", "CALCULATING", "COMPLETED", "ACTIVE", "CLOSED", "FAILED"}
LO_STATUSES = {"PLANNED", "ONGOING", "DONE"}
MT_STATUSES = {"READY", "ON_TRIP", "RETURNING", "QUEUEING", "LOADING", "UNAVAILABLE"}
SOLVER_STATUSES = {"OPTIMAL", "FEASIBLE", "PARTIAL", "INFEASIBLE", "UNKNOWN", "TIMEOUT", "TIME_LIMIT", "FAILED"}
OBJECTIVES = {"MIN_TOTAL_COST", "MIN_TOTAL_DISTANCE", "MIN_TOTAL_OPERATING_TIME"}
CONSTRAINT_MODES = {"HARD", "SOFT"}
DROPPED_REASON_CODES = {
    "NO_COMPATIBLE_MT",
    "INSUFFICIENT_CAPACITY",
    "COMPARTMENT_INFEASIBLE",
    "VEHICLE_TIME_EXHAUSTED",
    "DEPOT_TIME_EXHAUSTED",
    "SPBU_TIME_WINDOW",
    "BAY_PRODUCT_CONSTRAINT",
    "BAY_CONGESTION",
    "BAY_WINDOW_EXHAUSTED",
    "POST_BAY_REASSIGNMENT_TIMEOUT",
    "NO_FEASIBLE_ROUTE",
    "RESTRICTED_ROAD_NO_ROUTE",
    "RESTRICTED_ROUTE_REVIEW_REQUIRED",
    "USER_CANCELLED",
    "UNSERVED_END_OF_DAY",
}


# Every item in this catalog is intentionally configurable.  Solver/data
# integrity invariants (for example one persisted assignment row per LO) are
# not exposed as business constraints and therefore cannot be disabled.
CONSTRAINT_DEFINITIONS: dict[str, dict] = {
    "vehicle_compatibility": {
        "label": "MT–SPBU Compatibility",
        "category": "ROUTING",
        "description": "Vehicle class, canonical tag, and depot-compatible MT selection.",
        "default_mode": "HARD",
        "default_penalty": 2_000_000.0,
    },
    "vehicle_capacity": {
        "label": "Vehicle Capacity",
        "category": "ROUTING",
        "description": "Total LO volume assigned to one MT trip must fit the MT capacity.",
        "default_mode": "HARD",
        "default_penalty": 2_000_000.0,
    },
    "compartment_capacity": {
        "label": "Compartment Capacity",
        "category": "COMPARTMENT",
        "description": "Volume placed in a compartment must not exceed its capacity.",
        "default_mode": "HARD",
        "default_penalty": 2_000_000.0,
    },
    "compartment_product_separation": {
        "label": "One Product per Compartment",
        "category": "COMPARTMENT",
        "description": "A compartment cannot mix more than one product.",
        "default_mode": "HARD",
        "default_penalty": 2_000_000.0,
    },
    "vehicle_availability": {
        "label": "MT Availability / ETA",
        "category": "TIME",
        "description": "An MT may not depart before its effective depot ETA.",
        "default_mode": "HARD",
        "default_penalty": 1_000_000.0,
    },
    "vehicle_working_time": {
        "label": "MT Working Time",
        "category": "TIME",
        "description": "MT working time runs from vehicle use/queue/loading through route completion and return to depot.",
        "default_mode": "HARD",
        "default_penalty": 500_000.0,
        "default_limit_minutes": 720,
        "legacy_penalty": "overtime_penalty",
    },
    "spbu_time_window": {
        "label": "SPBU Receiving Window",
        "category": "TIME",
        "description": "Arrival must be within the official SPBU receiving window.",
        "default_mode": "HARD",
        "default_penalty": 250_000.0,
        "legacy_penalty": "late_penalty",
    },
    "depot_operating_window": {
        "label": "Depot Operating Window",
        "category": "TIME",
        "description": "Bay loading and gate-out must stay inside depot operating hours; MT return is governed by working time.",
        "default_mode": "HARD",
        "default_penalty": 500_000.0,
        "legacy_penalty": "overtime_penalty",
    },
    "freeze_window": {
        "label": "Reroute Freeze Window",
        "category": "REROUTE",
        "description": "Near-term PLANNED trips retain their current operational assignment.",
        "default_mode": "HARD",
        "default_penalty": 200_000.0,
        "legacy_penalty": "plan_change_penalty",
    },
    "bay_product_compatibility": {
        "label": "Bay Product Compatibility",
        "category": "BAY",
        "description": "Every trip product must be allowed by the selected loading bay.",
        "default_mode": "HARD",
        "default_penalty": 1_000_000.0,
    },
    "bay_operating_window": {
        "label": "Bay Operating Window",
        "category": "BAY",
        "description": "Loading and gate-out must stay inside the selected bay operating hours.",
        "default_mode": "HARD",
        "default_penalty": 500_000.0,
    },
    "bay_actual_queue": {
        "label": "Actual Bay Occupancy & Queue",
        "category": "BAY",
        "description": "New loading starts after actual occupancy and physical queue reservations.",
        "default_mode": "HARD",
        "default_penalty": 25_000.0,
        "legacy_penalty": "bay_queue_penalty",
    },
    "bay_no_overlap": {
        "label": "Bay No Overlap",
        "category": "BAY",
        "description": "One bay cannot load overlapping trips.",
        "default_mode": "HARD",
        "default_penalty": 1_000_000.0,
    },
    "bay_change_stability": {
        "label": "Previous Bay Stability",
        "category": "REROUTE",
        "description": "Retain the loading bay used by the current Phase 7 trip when feasible.",
        "default_mode": "SOFT",
        "default_penalty": 25_000.0,
        "legacy_penalty": "bay_change_penalty",
    },
    "serve_loading_order": {
        "label": "Serve Loading Order",
        "category": "SERVICE",
        "description": "Avoid leaving an eligible LO unserved.",
        "default_mode": "SOFT",
        "default_penalty": 10_000_000.0,
        "legacy_penalty": "unserved_penalty",
    },
    "phase6_vehicle_preference": {
        "label": "Phase 6 Vehicle Preference",
        "category": "PREFERENCE",
        "description": "Retain the MT predicted by the immutable Phase 6 warm start.",
        "default_mode": "SOFT",
        "default_penalty": 250_000.0,
        "legacy_penalty": "phase6_vehicle_change_penalty",
    },
    "phase6_shipment_preference": {
        "label": "Phase 6 Shipment Preference",
        "category": "PREFERENCE",
        "description": "Retain Phase 6 shipment grouping where feasible.",
        "default_mode": "SOFT",
        "default_penalty": 150_000.0,
        "legacy_penalty": "phase6_shipment_change_penalty",
    },
    "historical_pairing_preference": {
        "label": "Historical SPBU Pairing",
        "category": "PREFERENCE",
        "description": "Prefer SPBU combinations supported by Phase 3 history.",
        "default_mode": "SOFT",
        "default_penalty": 25_000.0,
        "legacy_penalty": "historical_pairing_penalty",
    },
    "historical_mt_affinity_preference": {
        "label": "Historical MT Affinity",
        "category": "PREFERENCE",
        "description": "Prefer MT–SPBU assignments supported by Phase 4 history.",
        "default_mode": "SOFT",
        "default_penalty": 25_000.0,
        "legacy_penalty": "historical_mt_affinity_penalty",
    },
    "previous_vehicle_stability": {
        "label": "Previous Vehicle Stability",
        "category": "REROUTE",
        "description": "Retain the current Phase 7 MT assignment during reroute.",
        "default_mode": "SOFT",
        "default_penalty": 150_000.0,
        "legacy_penalty": "vehicle_reassignment_penalty",
    },
    "previous_shipment_stability": {
        "label": "Previous Shipment Stability",
        "category": "REROUTE",
        "description": "Retain the current Phase 7 shipment grouping during reroute.",
        "default_mode": "SOFT",
        "default_penalty": 100_000.0,
        "legacy_penalty": "shipment_change_penalty",
    },
    "route_sequence_stability": {
        "label": "Route Sequence Stability",
        "category": "REROUTE",
        "description": "Avoid reversing the current stop sequence during reroute.",
        "default_mode": "SOFT",
        "default_penalty": 50_000.0,
        "legacy_penalty": "route_sequence_change_penalty",
    },
    "gateout_stability": {
        "label": "Gate-Out Stability",
        "category": "REROUTE",
        "description": "Keep the new gate-out close to the current operational plan.",
        "default_mode": "SOFT",
        "default_penalty": 50_000.0,
        "legacy_penalty": "gateout_change_penalty",
    },
}


def default_constraint_rules() -> dict[str, dict]:
    return {
        constraint_id: {
            "enabled": True,
            "mode": definition["default_mode"],
            "penalty": float(definition["default_penalty"]),
            **({"limit_minutes": int(definition["default_limit_minutes"])} if definition.get("default_limit_minutes") is not None else {}),
        }
        for constraint_id, definition in CONSTRAINT_DEFINITIONS.items()
    }


def constraint_catalog() -> list[dict]:
    return [
        {"constraint_id": constraint_id, **definition}
        for constraint_id, definition in CONSTRAINT_DEFINITIONS.items()
    ]


def constraint_rule(parameters: dict, constraint_id: str) -> dict:
    return (parameters.get("constraint_rules") or default_constraint_rules()).get(
        constraint_id,
        default_constraint_rules()[constraint_id],
    )


def constraint_is_hard(parameters: dict, constraint_id: str) -> bool:
    rule = constraint_rule(parameters, constraint_id)
    return bool(rule.get("enabled", True)) and rule.get("mode") == "HARD"


def constraint_is_soft(parameters: dict, constraint_id: str) -> bool:
    rule = constraint_rule(parameters, constraint_id)
    return bool(rule.get("enabled", True)) and rule.get("mode") == "SOFT"


def constraint_penalty(parameters: dict, constraint_id: str) -> int:
    rule = constraint_rule(parameters, constraint_id)
    if not bool(rule.get("enabled", True)) or rule.get("mode") != "SOFT":
        return 0
    return max(0, round(float(rule.get("penalty") or 0)))


def constraint_limit_minutes(parameters: dict, constraint_id: str) -> int:
    rule = constraint_rule(parameters, constraint_id)
    definition = CONSTRAINT_DEFINITIONS[constraint_id]
    return max(1, int(rule.get("limit_minutes") or definition.get("default_limit_minutes") or 1))


DEFAULT_PHASE7_PARAMETERS: dict = {
    "objective": "MIN_TOTAL_COST",
    "freeze_window_minutes": 60,
    "reoptimization_interval_minutes": 60,
    # ``optimization_time_limit`` remains as a legacy profile field. New and
    # normalized profiles use separate route and bay budgets so one engine
    # cannot consume the other engine's search time.
    "optimization_time_limit": 30,
    "route_optimization_time_limit": 30,
    "bay_optimization_time_limit": 30,
    "bay_scheduler_strategy": "FIFO_BALANCED",
    "bay_cp_sat_workers": 8,
    "max_coordination_iterations": 5,
    "departure_time_tolerance_minutes": 5,
    "return_time_tolerance_minutes": 5,
    "maximum_trips_per_mt": 6,
    "mt_turnaround_buffer_minutes": 30,
    "travel_time_mode": "AUTO",
    "average_speed_kmh": 35.0,
    "refueling_minutes": 40,
    "driving_break_interval_minutes": 240,
    "driving_break_minutes": 30,
    "default_spbu_service_minutes": 30,
    "cost_per_km": 10_000.0,
    "cost_per_operating_hour": 50_000.0,
    "queue_cost": 1_000.0,
    "loading_cost": 1_000.0,
    "overtime_cost": 5_000.0,
    "unserved_penalty": 10_000_000.0,
    "late_penalty": 250_000.0,
    "overtime_penalty": 500_000.0,
    "phase6_vehicle_change_penalty": 250_000.0,
    "phase6_shipment_change_penalty": 150_000.0,
    "historical_pairing_penalty": 25_000.0,
    "historical_mt_affinity_penalty": 25_000.0,
    "plan_change_penalty": 200_000.0,
    "vehicle_reassignment_penalty": 150_000.0,
    "shipment_change_penalty": 100_000.0,
    "route_sequence_change_penalty": 50_000.0,
    "gateout_change_penalty": 50_000.0,
    "bay_queue_penalty": 25_000.0,
    "bay_change_penalty": 25_000.0,
    "route_vehicle_mode": "GENERAL_VEHICLE",
    "traffic_aware": True,
    "route_matrix_cache_enabled": True,
    "route_matrix_cache_ttl_minutes": 60,
    "route_matrix_time_limit_seconds": 90,
    "restricted_matrix_time_limit_seconds": 900,
    "restricted_matrix_workers": 4,
    "route_matrix_google_element_budget": 2500,
    "route_geometry_time_limit_seconds": 120,
    "route_geometry_google_request_budget": 500,
    "gate_process_time": 5,
    "loading_mode": "SEQUENTIAL",
    "constraint_rules": default_constraint_rules(),
    "vehicle_activation_cost_rules": [
        {"vehicle_class": 8, "vehicle_tag": None, "activation_cost": 500_000.0, "priority": 10},
        {"vehicle_class": 16, "vehicle_tag": None, "activation_cost": 700_000.0, "priority": 10},
        {"vehicle_class": 24, "vehicle_tag": None, "activation_cost": 900_000.0, "priority": 10},
        {"vehicle_class": 32, "vehicle_tag": None, "activation_cost": 1_100_000.0, "priority": 10},
    ],
}


DEFAULT_PARAMETER_PROFILES = (
    ("Balanced Default", "Balanced cost, route, historical adherence, and plan stability.", {}),
    ("Cost Efficiency", "Prioritize total cost while retaining every hard constraint.", {"objective": "MIN_TOTAL_COST"}),
    ("High Historical Adherence", "Apply stronger Phase 6 and historical soft preferences.", {"phase6_vehicle_change_penalty": 750_000.0, "phase6_shipment_change_penalty": 500_000.0}),
    ("Peak Operation", "Shorter solve cycle and stronger gate-out stability during peak hours.", {"reoptimization_interval_minutes": 30, "gateout_change_penalty": 250_000.0}),
    ("High Bay Congestion", "Increase queue and bay-change penalties.", {"queue_cost": 5_000.0, "bay_queue_penalty": 250_000.0, "bay_change_penalty": 100_000.0}),
)


def effective_parameters(overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    parameters = {**DEFAULT_PHASE7_PARAMETERS, **overrides}
    legacy_time_limit = int(parameters.get("optimization_time_limit", 30))
    # Old saved profiles only contain ``optimization_time_limit``. Preserve
    # their operational meaning while exposing independent limits from now on.
    if "route_optimization_time_limit" not in overrides:
        parameters["route_optimization_time_limit"] = legacy_time_limit
    if "bay_optimization_time_limit" not in overrides:
        parameters["bay_optimization_time_limit"] = legacy_time_limit
    # Removed legacy duplicate: the MT work limit now lives only on the
    # vehicle_working_time constraint rule.
    parameters.pop("default_vehicle_working_time_minutes", None)
    supplied_rules = overrides.get("constraint_rules") or {}
    if not isinstance(supplied_rules, dict):
        raise ValueError("constraint_rules must be an object keyed by constraint id")
    unknown = sorted(set(supplied_rules) - set(CONSTRAINT_DEFINITIONS))
    if unknown:
        raise ValueError(f"Unsupported Phase 7 constraint: {', '.join(unknown)}")
    rules = default_constraint_rules()
    legacy_penalty_values = {
        definition["legacy_penalty"]: parameters.get(definition["legacy_penalty"])
        for definition in CONSTRAINT_DEFINITIONS.values()
        if definition.get("legacy_penalty")
    }
    for constraint_id, definition in CONSTRAINT_DEFINITIONS.items():
        supplied = supplied_rules.get(constraint_id) or {}
        if not isinstance(supplied, dict):
            raise ValueError(f"constraint_rules.{constraint_id} must be an object")
        mode = str(supplied.get("mode", rules[constraint_id]["mode"])).upper()
        if mode not in CONSTRAINT_MODES:
            raise ValueError(f"constraint_rules.{constraint_id}.mode must be HARD or SOFT")
        legacy_key = definition.get("legacy_penalty")
        penalty = supplied.get(
            "penalty",
            legacy_penalty_values.get(legacy_key, rules[constraint_id]["penalty"]) if legacy_key else rules[constraint_id]["penalty"],
        )
        penalty = float(penalty)
        if not math.isfinite(penalty) or penalty < 0:
            raise ValueError(f"constraint_rules.{constraint_id}.penalty must be a non-negative finite number")
        rules[constraint_id] = {
            "enabled": bool(supplied.get("enabled", rules[constraint_id]["enabled"])),
            "mode": mode,
            "penalty": penalty,
            **(
                {"limit_minutes": int(supplied.get("limit_minutes", rules[constraint_id]["limit_minutes"]))}
                if "limit_minutes" in rules[constraint_id]
                else {}
            ),
        }
        if "limit_minutes" in rules[constraint_id] and not 1 <= int(rules[constraint_id]["limit_minutes"]) <= 2880:
            raise ValueError(f"constraint_rules.{constraint_id}.limit_minutes must be between 1 and 2880")
        if legacy_key:
            parameters[legacy_key] = penalty
    parameters["constraint_rules"] = rules
    if parameters["objective"] not in OBJECTIVES:
        raise ValueError(f"Unsupported Phase 7 objective: {parameters['objective']}")
    if str(parameters.get("route_vehicle_mode", "GENERAL_VEHICLE")).upper() not in {"GENERAL_VEHICLE", "TRUCK"}:
        raise ValueError("route_vehicle_mode must be GENERAL_VEHICLE or TRUCK")
    parameters["route_vehicle_mode"] = str(parameters["route_vehicle_mode"]).upper()
    parameters["loading_mode"] = str(parameters.get("loading_mode", "SEQUENTIAL")).upper()
    if parameters["loading_mode"] not in {"SEQUENTIAL", "PARALLEL"}:
        raise ValueError("loading_mode must be SEQUENTIAL or PARALLEL")
    parameters["bay_scheduler_strategy"] = str(
        parameters.get("bay_scheduler_strategy", "FIFO_BALANCED")
    ).upper()
    if parameters["bay_scheduler_strategy"] not in {"FIFO_BALANCED", "CP_SAT"}:
        raise ValueError("bay_scheduler_strategy must be FIFO_BALANCED or CP_SAT")
    if parameters["travel_time_mode"] not in {"AUTO", "MANUAL_SPEED"}:
        raise ValueError("travel_time_mode must be AUTO or MANUAL_SPEED")
    speed = float(parameters["average_speed_kmh"])
    if not math.isfinite(speed) or not 1 <= speed <= 150:
        raise ValueError("average_speed_kmh must be between 1 and 150")
    parameters["average_speed_kmh"] = speed
    integer_bounds = {
        "refueling_minutes": (0, 1440),
        "driving_break_interval_minutes": (1, 1440),
        "driving_break_minutes": (0, 1440),
        "freeze_window_minutes": (0, 1440),
        "reoptimization_interval_minutes": (1, 1440),
        "optimization_time_limit": (1, 3600),
        "route_optimization_time_limit": (1, 3600),
        "bay_optimization_time_limit": (1, 3600),
        "bay_cp_sat_workers": (1, 64),
        "max_coordination_iterations": (1, 20),
        "departure_time_tolerance_minutes": (0, 240),
        "return_time_tolerance_minutes": (0, 240),
        "maximum_trips_per_mt": (1, 20),
        "mt_turnaround_buffer_minutes": (0, 1440),
        "default_spbu_service_minutes": (0, 1440),
        "gate_process_time": (0, 240),
        "route_matrix_cache_ttl_minutes": (1, 10080),
        "route_matrix_time_limit_seconds": (1, 900),
        "restricted_matrix_time_limit_seconds": (1, 3600),
        "restricted_matrix_workers": (1, 16),
        "route_matrix_google_element_budget": (0, 3000),
        "route_geometry_time_limit_seconds": (0, 300),
        "route_geometry_google_request_budget": (0, 500),
    }
    for key, (minimum, maximum) in integer_bounds.items():
        value = int(parameters[key])
        if not minimum <= value <= maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}")
        parameters[key] = value
    return parameters
