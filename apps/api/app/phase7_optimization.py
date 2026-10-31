from __future__ import annotations

import copy
import heapq
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from .phase7_constants import constraint_is_hard, constraint_is_soft, constraint_penalty, constraint_rule
from .phase7_timing import travel_time_matrix, trip_clock

try:  # The production image installs OR-Tools; this guard keeps diagnostics import-safe.
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    from ortools.sat.python import cp_model

    ORTOOLS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in incomplete host environments.
    pywrapcp = None
    routing_enums_pb2 = None
    cp_model = None
    ORTOOLS_AVAILABLE = False


def _utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _minutes_between(start: datetime, end: datetime) -> int:
    return max(0, math.ceil((_utc(end) - _utc(start)).total_seconds() / 60))


def _cp_sat_result_status(status: int, *, elapsed_seconds: float, time_limit_seconds: int) -> str:
    """Translate CP-SAT termination without calling UNKNOWN infeasible."""
    if status == cp_model.OPTIMAL:
        return "OPTIMAL"
    if status == cp_model.FEASIBLE:
        return "FEASIBLE"
    if status == cp_model.INFEASIBLE:
        return "INFEASIBLE"
    if status == cp_model.MODEL_INVALID:
        return "FAILED"
    if status == cp_model.UNKNOWN and elapsed_seconds >= max(0.01, time_limit_seconds * 0.95):
        return "TIMEOUT"
    return "UNKNOWN"


class CompartmentAssignmentService:
    """Assign complete LOs to compartments with one product per compartment."""

    @staticmethod
    def _fallback(loading_orders: list[dict], compartments: list[dict], parameters: dict) -> dict:
        if not compartments:
            if constraint_is_hard(parameters, "compartment_capacity") or constraint_is_hard(parameters, "compartment_product_separation"):
                return {"feasible": False, "assignments": [], "reason": "COMPARTMENT_INFEASIBLE", "engine": "DETERMINISTIC_FALLBACK", "constraint_violations": [], "penalty_cost": 0}
            compartments = [{"compartment_id": "UNASSIGNED", "capacity_kl": 0}]
        ordered = sorted(loading_orders, key=lambda row: (-float(row["volume_kl"]), str(row["loading_order_id"])))
        remaining = {str(row["compartment_id"]): float(row["capacity_kl"]) for row in compartments}
        products: dict[str, set[str]] = {str(row["compartment_id"]): set() for row in compartments}
        assignments: list[dict] = []
        violations: list[dict] = []
        for lo in ordered:
            product = str(lo.get("product_id") or "UNKNOWN")
            eligible = []
            for compartment in compartments:
                compartment_id = str(compartment["compartment_id"])
                capacity_violation = remaining[compartment_id] + 1e-9 < float(lo["volume_kl"])
                product_violation = bool(products[compartment_id] - {product})
                if capacity_violation and constraint_is_hard(parameters, "compartment_capacity"):
                    continue
                if product_violation and constraint_is_hard(parameters, "compartment_product_separation"):
                    continue
                incremental_penalty = (
                    constraint_penalty(parameters, "compartment_capacity") if capacity_violation else 0
                ) + (
                    constraint_penalty(parameters, "compartment_product_separation") if product_violation else 0
                )
                eligible.append((incremental_penalty, compartment))
            if not eligible:
                return {"feasible": False, "assignments": [], "reason": "COMPARTMENT_INFEASIBLE", "engine": "DETERMINISTIC_FALLBACK", "constraint_violations": violations, "penalty_cost": sum(row["penalty"] for row in violations)}
            _, compartment = min(
                eligible,
                key=lambda row: (
                    row[0],
                    remaining[str(row[1]["compartment_id"])] - float(lo["volume_kl"]),
                    str(row[1]["compartment_id"]),
                ),
            )
            compartment_id = str(compartment["compartment_id"])
            if remaining[compartment_id] + 1e-9 < float(lo["volume_kl"]) and constraint_is_soft(parameters, "compartment_capacity"):
                violations.append({"constraint_id": "compartment_capacity", "penalty": constraint_penalty(parameters, "compartment_capacity"), "entity": compartment_id})
            if products[compartment_id] - {product} and constraint_is_soft(parameters, "compartment_product_separation"):
                violations.append({"constraint_id": "compartment_product_separation", "penalty": constraint_penalty(parameters, "compartment_product_separation"), "entity": compartment_id})
            remaining[compartment_id] -= float(lo["volume_kl"])
            products[compartment_id].add(product)
            assignments.append({**lo, "compartment_id": compartment_id})
        return {"feasible": True, "assignments": assignments, "reason": None, "engine": "DETERMINISTIC_FALLBACK", "constraint_violations": violations, "penalty_cost": sum(row["penalty"] for row in violations)}

    def assign(self, loading_orders: list[dict], compartments: list[dict], *, parameters: dict | None = None, time_limit_seconds: int = 5) -> dict:
        parameters = parameters or {}
        if not loading_orders:
            return {"feasible": True, "assignments": [], "reason": None, "engine": "OR_TOOLS_CP_SAT", "constraint_violations": [], "penalty_cost": 0}
        if not compartments:
            if constraint_is_hard(parameters, "compartment_capacity") or constraint_is_hard(parameters, "compartment_product_separation"):
                return {"feasible": False, "assignments": [], "reason": "COMPARTMENT_INFEASIBLE", "engine": "OR_TOOLS_CP_SAT", "constraint_violations": [], "penalty_cost": 0}
            compartments = [{"compartment_id": "UNASSIGNED", "capacity_kl": 0}]
        if not ORTOOLS_AVAILABLE:
            return self._fallback(loading_orders, compartments, parameters)

        model = cp_model.CpModel()
        scale = 1000
        products = sorted({str(row.get("product_id") or "UNKNOWN") for row in loading_orders})
        total_volume = max(1, sum(round(float(row["volume_kl"]) * scale) for row in loading_orders))
        x: dict[tuple[int, int], Any] = {}
        y: dict[tuple[int, str], Any] = {}
        objective_terms: list[Any] = []
        capacity_violations: dict[int, Any] = {}
        product_violations: dict[int, Any] = {}
        for compartment_index, _ in enumerate(compartments):
            for product in products:
                y[compartment_index, product] = model.new_bool_var(f"product_{compartment_index}_{product}")
            product_count = sum(y[compartment_index, product] for product in products)
            if constraint_is_hard(parameters, "compartment_product_separation"):
                model.add(product_count <= 1)
            elif constraint_is_soft(parameters, "compartment_product_separation"):
                violation = model.new_bool_var(f"product_mix_violation_{compartment_index}")
                product_violations[compartment_index] = violation
                model.add(product_count <= 1 + len(products) * violation)
                model.add(product_count >= 2).only_enforce_if(violation)
                objective_terms.append(constraint_penalty(parameters, "compartment_product_separation") * violation)
        for lo_index, lo in enumerate(loading_orders):
            product = str(lo.get("product_id") or "UNKNOWN")
            for compartment_index, _ in enumerate(compartments):
                x[lo_index, compartment_index] = model.new_bool_var(f"lo_{lo_index}_compartment_{compartment_index}")
                model.add(x[lo_index, compartment_index] <= y[compartment_index, product])
            model.add(sum(x[lo_index, compartment_index] for compartment_index in range(len(compartments))) == 1)
        for compartment_index, compartment in enumerate(compartments):
            assigned_volume = sum(
                round(float(lo["volume_kl"]) * scale) * x[lo_index, compartment_index]
                for lo_index, lo in enumerate(loading_orders)
            )
            capacity = round(float(compartment["capacity_kl"]) * scale)
            if constraint_is_hard(parameters, "compartment_capacity"):
                model.add(assigned_volume <= capacity)
            elif constraint_is_soft(parameters, "compartment_capacity"):
                violation = model.new_bool_var(f"capacity_violation_{compartment_index}")
                capacity_violations[compartment_index] = violation
                model.add(assigned_volume <= capacity + total_volume * violation)
                model.add(assigned_volume >= capacity + 1).only_enforce_if(violation)
                objective_terms.append(constraint_penalty(parameters, "compartment_capacity") * violation)
        # Prefer fewer used compartments, then deterministic lower compartment indexes.
        model.minimize(
            sum((100 + compartment_index) * y[compartment_index, product] for compartment_index in range(len(compartments)) for product in products)
            + sum(objective_terms)
        )
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(max(1, time_limit_seconds))
        solver.parameters.num_search_workers = max(1, int(parameters.get("bay_cp_sat_workers", 8)))
        status = solver.solve(model)
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            return {"feasible": False, "assignments": [], "reason": "COMPARTMENT_INFEASIBLE", "engine": "OR_TOOLS_CP_SAT", "constraint_violations": [], "penalty_cost": 0}
        assignments = []
        for lo_index, lo in enumerate(loading_orders):
            compartment_index = next(
                index for index in range(len(compartments)) if solver.value(x[lo_index, index])
            )
            assignments.append({**lo, "compartment_id": str(compartments[compartment_index]["compartment_id"])})
        violations = [
            {"constraint_id": "compartment_capacity", "penalty": constraint_penalty(parameters, "compartment_capacity"), "entity": str(compartments[index]["compartment_id"])}
            for index, variable in capacity_violations.items() if solver.value(variable)
        ] + [
            {"constraint_id": "compartment_product_separation", "penalty": constraint_penalty(parameters, "compartment_product_separation"), "entity": str(compartments[index]["compartment_id"])}
            for index, variable in product_violations.items() if solver.value(variable)
        ]
        return {"feasible": True, "assignments": assignments, "reason": None, "engine": "OR_TOOLS_CP_SAT", "constraint_violations": violations, "penalty_cost": sum(row["penalty"] for row in violations)}


class VRPOptimizationService:
    """OR-Tools Routing solver wrapped in a physical-vehicle multi-trip loop."""

    def __init__(self) -> None:
        self.compartments = CompartmentAssignmentService()

    @staticmethod
    def _vehicle_cost(parameters: dict, vehicle: dict) -> int:
        rules = sorted(
            parameters.get("vehicle_activation_cost_rules") or [],
            key=lambda rule: (int(rule.get("priority") or 0), bool(rule.get("vehicle_tag"))),
            reverse=True,
        )
        tags = set(vehicle.get("tags") or [])
        for rule in rules:
            class_matches = rule.get("vehicle_class") in {None, vehicle.get("vehicle_class")}
            tag_matches = not rule.get("vehicle_tag") or rule["vehicle_tag"] in tags
            if class_matches and tag_matches:
                return round(float(rule.get("activation_cost") or 0))
        return 0

    @staticmethod
    def _fallback_round(
        remaining: list[dict], vehicles: list[dict], distance_matrix: list[list[int]], time_matrix: list[list[int]],
        day_start: datetime, parameters: dict,
    ) -> tuple[list[dict], set[int], str, float]:
        routes: list[dict] = []
        served: set[int] = set()
        for vehicle_index, vehicle in enumerate(vehicles):
            capacity = float(vehicle["capacity_kl"])
            allowed = [
                index for index, row in enumerate(remaining, start=1)
                if index not in served and vehicle["mt_id"] in set(row.get("allowed_vehicle_ids") or [])
            ]
            allowed.sort(key=lambda node: (remaining[node - 1].get("phase6_predicted_vehicle_id") != vehicle["mt_id"], node))
            selected = []
            used = 0.0
            for node in allowed:
                volume = float(remaining[node - 1]["volume_kl"])
                previous = selected[-1] if selected else 0
                if time_matrix[previous][node] >= 1_000_000_000 or time_matrix[node][0] >= 1_000_000_000:
                    continue
                if not constraint_is_hard(parameters, "vehicle_capacity") or used + volume <= capacity + 1e-9:
                    selected.append(node)
                    used += volume
            if selected:
                served.update(selected)
                reference_minutes = _minutes_between(day_start, vehicle.get("optimization_reference_time") or day_start)
                availability_minutes = _minutes_between(day_start, vehicle.get("availability_eta_depot") or vehicle["effective_eta_depot"])
                depot_open_minutes = _minutes_between(day_start, vehicle.get("depot_operational_start") or day_start)
                start_minutes = max(
                    reference_minutes,
                    availability_minutes if constraint_is_hard(parameters, "vehicle_availability") else 0,
                    depot_open_minutes if constraint_is_hard(parameters, "depot_operating_window") else 0,
                )
                routes.append({"vehicle_index": vehicle_index, "node_indices": selected, "start_minutes": start_minutes})
        return routes, served, "FEASIBLE", 0.0

    @staticmethod
    def _build_warm_routes(
        remaining: list[dict],
        vehicles: list[dict],
        *,
        source: str,
    ) -> tuple[list[list[int]], int]:
        """Build the per-round seed without turning it into a hard plan.

        Initial optimization follows the immutable Phase 6 MT preference.
        Reroute follows the next not-yet-executed trip from the current Route
        Version for each physical MT. Later current-version trips are seeded in
        later multi-trip rounds after completed_trip_count advances.
        """
        source = str(source or "PHASE6").upper()
        mt_index_by_id = {str(vehicle["mt_id"]): index for index, vehicle in enumerate(vehicles)}
        candidates: list[list[tuple[int, str, int]]] = [[] for _ in vehicles]
        for node, lo in enumerate(remaining, start=1):
            if source == "CURRENT_ROUTE":
                vehicle_id = lo.get("current_vehicle_id")
                trip_number = lo.get("current_trip_number")
                if vehicle_id not in mt_index_by_id or trip_number is None:
                    continue
                vehicle_index = mt_index_by_id[str(vehicle_id)]
                expected_trip = int(vehicles[vehicle_index].get("completed_trip_count") or 0) + 1
                if int(trip_number) != expected_trip:
                    continue
                sequence = int(lo.get("current_stop_sequence") or 0)
            else:
                vehicle_id = lo.get("phase6_predicted_vehicle_id")
                if vehicle_id not in mt_index_by_id:
                    continue
                vehicle_index = mt_index_by_id[str(vehicle_id)]
                sequence = node
            if str(vehicle_id) not in {str(mt_id) for mt_id in lo.get("allowed_vehicle_ids") or []}:
                continue
            candidates[vehicle_index].append((sequence, str(lo["loading_order_id"]), node))
        routes = [
            [node for _, _, node in sorted(vehicle_rows)]
            for vehicle_rows in candidates
        ]
        return routes, sum(len(route) for route in routes)

    def _solve_round(
        self,
        *,
        remaining: list[dict],
        vehicles: list[dict],
        distance_matrix: list[list[int]],
        time_matrix: list[list[int]],
        day_start: datetime,
        depot_close_minutes: int,
        parameters: dict,
    ) -> tuple[list[dict], set[int], str, float]:
        if constraint_is_hard(parameters, "serve_loading_order") and any(
            time_matrix[0][node] >= 1_000_000_000 or time_matrix[node][0] >= 1_000_000_000
            for node in range(1, len(remaining) + 1)
        ):
            return [], set(), "INFEASIBLE", 0.0
        if not ORTOOLS_AVAILABLE:
            return self._fallback_round(remaining, vehicles, distance_matrix, time_matrix, day_start, parameters)
        manager = pywrapcp.RoutingIndexManager(len(remaining) + 1, len(vehicles), 0)
        routing = pywrapcp.RoutingModel(manager)
        # Restricted-road no-route pairs are structural exclusions, independent
        # of dispatcher HARD/SOFT time/capacity settings. Include every physical
        # vehicle's separate start/end depot index, while retaining drop loops.
        forbidden_pairs = [(i, j) for i, row in enumerate(time_matrix) for j, value in enumerate(row)
                           if i != j and value >= 1_000_000_000]
        if forbidden_pairs:
            from_indexes, to_indexes = defaultdict(list), defaultdict(list)
            for index in range(routing.Size() + len(vehicles)):
                to_indexes[manager.IndexToNode(index)].append(index)
                if index < routing.Size():
                    from_indexes[manager.IndexToNode(index)].append(index)
            for source, target in forbidden_pairs:
                for source_index in from_indexes[source]:
                    for target_index in to_indexes[target]:
                        routing.NextVar(source_index).RemoveValue(target_index)
        service_minutes = int(parameters.get("default_spbu_service_minutes", 30))

        def minute_callback(from_index: int, to_index: int) -> int:
            source = manager.IndexToNode(from_index)
            target = manager.IndexToNode(to_index)
            return math.ceil(time_matrix[source][target] / 60) + (service_minutes if source else (int(parameters.get("refueling_minutes", 0)) if target else 0))

        minute_index = routing.RegisterTransitCallback(minute_callback)
        # Depot operating hours govern loading/gate-out, not the vehicle's
        # eventual return.  Keep enough route horizon after depot close for a
        # dispatched MT to finish its delivery and return, while the bay model
        # remains responsible for the actual gate-out cutoff.
        maximum_working_minutes = max(
            (int(vehicle.get("working_time_remaining_minutes") or 0) for vehicle in vehicles),
            default=0,
        )
        time_horizon = max(depot_close_minutes + max(24 * 60, maximum_working_minutes), 1)
        routing.AddDimension(minute_index, 24 * 60, time_horizon, False, "Time")
        time_dimension = routing.GetDimensionOrDie("Time")

        # A zero-slack driving dimension excludes service, refueling and waiting.
        # Break counts depend on cumulative driving on the chosen route, not on
        # elapsed wall time or separate arc rounding. Starts reset every trip.
        break_minutes = int(parameters.get("driving_break_minutes", 0))
        if break_minutes:
            def driving_callback(from_index, to_index):
                return int(time_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])
            driving_index = routing.RegisterTransitCallback(driving_callback)
            routing.AddDimension(driving_index, 0, time_horizon * 60, True, "Driving")
            driving = routing.GetDimensionOrDie("Driving")
            cp = routing.solver()
            interval = int(parameters.get("driving_break_interval_minutes", 240)) * 60
            indexes = range(manager.GetNumberOfIndices())
            drive_vars = [driving.CumulVar(i) for i in indexes]
            break_counts = [cp.Max(value - 1, 0) // interval for value in drive_vars]
            for index in range(routing.Size()):
                next_breaks = cp.Element(break_counts, routing.NextVar(index))
                # The Time dimension already enforces next = current + transit
                # + slack. Express breaks as required slack, avoiding two extra
                # N-wide Element constraints per node and a second time model.
                cp.Add(time_dimension.SlackVar(index) >= (next_breaks - break_counts[index]) * break_minutes)

        def demand_callback(index: int) -> int:
            node = manager.IndexToNode(index)
            return 0 if node == 0 else round(float(remaining[node - 1]["volume_kl"]) * 1000)

        demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
        demand_scale = 1000
        total_demand = max(1, sum(round(float(row["volume_kl"]) * demand_scale) for row in remaining))
        vehicle_capacities = [
            round(float(vehicle["capacity_kl"]) * demand_scale)
            if constraint_is_hard(parameters, "vehicle_capacity")
            else total_demand
            for vehicle in vehicles
        ]
        routing.AddDimensionWithVehicleCapacity(
            demand_index,
            0,
            vehicle_capacities,
            True,
            "Capacity",
        )
        capacity_dimension = routing.GetDimensionOrDie("Capacity")

        objective = parameters["objective"]
        use_elapsed_cost = bool(parameters.get("refueling_minutes", 0) or parameters.get("driving_break_minutes", 0))
        for vehicle_index, vehicle in enumerate(vehicles):
            def cost_callback(from_index: int, to_index: int, vehicle_index: int = vehicle_index) -> int:
                source = manager.IndexToNode(from_index)
                target = manager.IndexToNode(to_index)
                if objective == "MIN_TOTAL_DISTANCE":
                    base = distance_matrix[source][target]
                elif objective == "MIN_TOTAL_OPERATING_TIME":
                    base = 0 if use_elapsed_cost else math.ceil(time_matrix[source][target] / 60) * 1000
                else:
                    base = round(
                        distance_matrix[source][target] / 1000 * float(parameters["cost_per_km"])
                        + (0 if use_elapsed_cost else time_matrix[source][target] / 3600 * float(parameters["cost_per_operating_hour"]))
                    )
                if target:
                    target_lo = remaining[target - 1]
                    vehicle_id = vehicles[vehicle_index]["mt_id"]
                    for constraint_id in (target_lo.get("constraint_violations_by_vehicle") or {}).get(vehicle_id, []):
                        base += constraint_penalty(parameters, constraint_id)
                    preferred = target_lo.get("phase6_predicted_vehicle_id")
                    if preferred and preferred != vehicles[vehicle_index]["mt_id"]:
                        base += constraint_penalty(parameters, "phase6_vehicle_preference")
                    current_vehicle = target_lo.get("current_vehicle_id")
                    if current_vehicle and current_vehicle != vehicles[vehicle_index]["mt_id"]:
                        base += constraint_penalty(parameters, "previous_vehicle_stability")
                        if target_lo.get("freeze_window_candidate"):
                            base += constraint_penalty(parameters, "freeze_window")
                    affinity = float((target_lo.get("historical_mt_affinity") or {}).get(vehicles[vehicle_index]["mt_id"], 0))
                    base += round((1 - affinity) * constraint_penalty(parameters, "historical_mt_affinity_preference"))
                    previous_gate_out = target_lo.get("current_planned_gate_out_minutes")
                    if previous_gate_out is not None:
                        available = _minutes_between(day_start, vehicles[vehicle_index]["effective_eta_depot"])
                        if abs(int(previous_gate_out) - available) > int(parameters.get("departure_time_tolerance_minutes", 5)):
                            base += constraint_penalty(parameters, "gateout_stability")
                if source and target:
                    source_lo = remaining[source - 1]
                    target_lo = remaining[target - 1]
                    if source_lo.get("phase6_predicted_shipment_id") != target_lo.get("phase6_predicted_shipment_id"):
                        base += constraint_penalty(parameters, "phase6_shipment_preference")
                    if source_lo.get("current_shipment_id") and source_lo.get("current_shipment_id") != target_lo.get("current_shipment_id"):
                        base += constraint_penalty(parameters, "previous_shipment_stability")
                    pairing_score = float((source_lo.get("historical_pairing_scores") or {}).get(target_lo.get("spbu_id"), 0))
                    base += round((1 - pairing_score) * constraint_penalty(parameters, "historical_pairing_preference"))
                    source_sequence = source_lo.get("current_stop_sequence")
                    target_sequence = target_lo.get("current_stop_sequence")
                    if source_sequence is not None and target_sequence is not None and int(source_sequence) >= int(target_sequence):
                        base += constraint_penalty(parameters, "route_sequence_stability")
                return max(0, int(base))

            cost_index = routing.RegisterTransitCallback(cost_callback)
            routing.SetArcCostEvaluatorOfVehicle(cost_index, vehicle_index)
            routing.SetFixedCostOfVehicle(self._vehicle_cost(parameters, vehicle), vehicle_index)
            if use_elapsed_cost and objective != "MIN_TOTAL_DISTANCE":
                # Charge elapsed route time once, including fuel, breaks and
                # service. Drive-time costs are removed from the arc evaluator.
                coefficient = 1000 if objective == "MIN_TOTAL_OPERATING_TIME" else max(0, round(float(parameters["cost_per_operating_hour"]) / 60))
                time_dimension.SetSpanCostCoefficientForVehicle(coefficient, vehicle_index)
            reference_minutes = _minutes_between(day_start, vehicle.get("optimization_reference_time") or day_start)
            available_minutes = _minutes_between(day_start, vehicle.get("availability_eta_depot") or vehicle["effective_eta_depot"])
            depot_open_minutes = _minutes_between(day_start, vehicle.get("depot_operational_start") or day_start)
            start_minimum = max(
                reference_minutes,
                available_minutes if constraint_is_hard(parameters, "vehicle_availability") else 0,
                depot_open_minutes if constraint_is_hard(parameters, "depot_operating_window") else 0,
            )
            maximum_start = (
                depot_close_minutes
                if constraint_is_hard(parameters, "depot_operating_window")
                else time_horizon
            )
            time_dimension.CumulVar(routing.Start(vehicle_index)).SetRange(start_minimum, maximum_start)
            time_dimension.CumulVar(routing.End(vehicle_index)).SetRange(start_minimum, time_horizon)
            if constraint_is_hard(parameters, "vehicle_working_time"):
                time_dimension.SetSpanUpperBoundForVehicle(int(vehicle["working_time_remaining_minutes"]), vehicle_index)
            elif constraint_is_soft(parameters, "vehicle_working_time"):
                time_dimension.SetSoftSpanUpperBoundForVehicle(
                    pywrapcp.BoundCost(
                        int(vehicle["working_time_remaining_minutes"]),
                        max(1, constraint_penalty(parameters, "vehicle_working_time")),
                    ),
                    vehicle_index,
                )
            soft_start_bounds = []
            if constraint_is_soft(parameters, "vehicle_availability") and available_minutes > start_minimum:
                soft_start_bounds.append((available_minutes, constraint_penalty(parameters, "vehicle_availability")))
            if constraint_is_soft(parameters, "depot_operating_window") and depot_open_minutes > start_minimum:
                soft_start_bounds.append((depot_open_minutes, constraint_penalty(parameters, "depot_operating_window")))
            if soft_start_bounds:
                soft_bound = max(bound for bound, _ in soft_start_bounds)
                soft_penalty = sum(penalty for bound, penalty in soft_start_bounds if bound == soft_bound)
                time_dimension.SetCumulVarSoftLowerBound(routing.Start(vehicle_index), soft_bound, max(1, soft_penalty))
            soft_gate_out_bounds = []
            if constraint_is_soft(parameters, "depot_operating_window"):
                soft_gate_out_bounds.append((depot_close_minutes, constraint_penalty(parameters, "depot_operating_window")))
            if soft_gate_out_bounds:
                soft_bound = min(bound for bound, _ in soft_gate_out_bounds)
                soft_penalty = sum(penalty for bound, penalty in soft_gate_out_bounds if bound == soft_bound)
                # Routing.Start is the preliminary dispatch time. Bay CP-SAT
                # later replaces it with the authoritative loading/gate-out.
                time_dimension.SetCumulVarSoftUpperBound(routing.Start(vehicle_index), soft_bound, max(1, soft_penalty))
            if constraint_is_soft(parameters, "vehicle_capacity"):
                capacity_dimension.SetCumulVarSoftUpperBound(
                    routing.End(vehicle_index),
                    round(float(vehicle["capacity_kl"]) * demand_scale),
                    max(1, round(constraint_penalty(parameters, "vehicle_capacity") / demand_scale)),
                )

        mt_index_by_id = {vehicle["mt_id"]: index for index, vehicle in enumerate(vehicles)}
        locked_nodes_by_trip: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for node, lo in enumerate(remaining, start=1):
            index = manager.NodeToIndex(node)
            allowed = [mt_index_by_id[mt_id] for mt_id in lo.get("allowed_vehicle_ids") or [] if mt_id in mt_index_by_id]
            preferred = lo.get("phase6_predicted_vehicle_id")
            if constraint_is_hard(parameters, "phase6_vehicle_preference") and preferred in mt_index_by_id:
                allowed = [vehicle_index for vehicle_index in allowed if vehicle_index == mt_index_by_id[preferred]]
            current_vehicle = lo.get("current_vehicle_id")
            current_trip_number = lo.get("current_trip_number")
            reroute_locked = bool(lo.get("reroute_assignment_locked"))
            locked_for_this_round = False
            if reroute_locked and current_vehicle in mt_index_by_id and current_trip_number is not None:
                current_vehicle_index = mt_index_by_id[current_vehicle]
                expected_trip_number = int(vehicles[current_vehicle_index].get("completed_trip_count") or 0) + 1
                locked_for_this_round = int(current_trip_number) == expected_trip_number
                allowed = [current_vehicle_index] if locked_for_this_round else []
            if constraint_is_hard(parameters, "previous_vehicle_stability") and current_vehicle in mt_index_by_id:
                allowed = [vehicle_index for vehicle_index in allowed if vehicle_index == mt_index_by_id[current_vehicle]]
            if constraint_is_hard(parameters, "historical_mt_affinity_preference") and allowed:
                affinity = lo.get("historical_mt_affinity") or {}
                best = max((float(affinity.get(vehicles[vehicle_index]["mt_id"], 0)) for vehicle_index in allowed), default=0)
                if best > 0:
                    allowed = [vehicle_index for vehicle_index in allowed if float(affinity.get(vehicles[vehicle_index]["mt_id"], 0)) == best]
            if allowed:
                routing.SetAllowedVehiclesForIndex(allowed, index)
            else:
                # An empty compatibility intersection means explicitly
                # unserved; OR-Tools otherwise interprets an omitted vehicle
                # restriction as "all vehicles allowed".
                routing.ActiveVar(index).SetValue(0)
            if reroute_locked and not locked_for_this_round:
                # Preserve a later V1/V2 trip for the corresponding later
                # physical multi-trip round instead of merging it early.
                routing.ActiveVar(index).SetValue(0)
            elif reroute_locked:
                routing.ActiveVar(index).SetValue(1)
                locked_nodes_by_trip[(str(current_vehicle), int(current_trip_number))].append(
                    (int(lo.get("current_stop_sequence") or 0), index)
                )
            elif constraint_is_hard(parameters, "serve_loading_order"):
                routing.ActiveVar(index).SetValue(1)
            else:
                routing.AddDisjunction([index], constraint_penalty(parameters, "serve_loading_order"))
            if lo.get("time_window_start_minutes") is not None and lo.get("time_window_end_minutes") is not None:
                start = int(lo["time_window_start_minutes"])
                end = int(lo["time_window_end_minutes"])
                if constraint_is_hard(parameters, "spbu_time_window"):
                    time_dimension.CumulVar(index).SetRange(start, end)
                elif constraint_is_soft(parameters, "spbu_time_window"):
                    time_dimension.SetCumulVarSoftLowerBound(index, start, constraint_penalty(parameters, "spbu_time_window"))
                    time_dimension.SetCumulVarSoftUpperBound(index, end, constraint_penalty(parameters, "spbu_time_window"))

        # Hard-freeze retains the relative V1/V2 stop sequence while allowing
        # actual availability and the bay scheduler to recalculate timestamps.
        for locked_nodes in locked_nodes_by_trip.values():
            by_sequence: dict[int, list[int]] = defaultdict(list)
            for sequence, index in locked_nodes:
                by_sequence[sequence].append(index)
            ordered_sequences = sorted(by_sequence)
            for source_sequence, target_sequence in zip(ordered_sequences, ordered_sequences[1:]):
                for source_index in by_sequence[source_sequence]:
                    for target_index in by_sequence[target_sequence]:
                        routing.solver().Add(
                            time_dimension.CumulVar(source_index) <= time_dimension.CumulVar(target_index)
                        )

        for grouping_constraint, grouping_key in (
            ("phase6_shipment_preference", "phase6_predicted_shipment_id"),
            ("previous_shipment_stability", "current_shipment_id"),
        ):
            if not constraint_is_hard(parameters, grouping_constraint):
                continue
            grouped_nodes: dict[str, list[int]] = defaultdict(list)
            for node, lo in enumerate(remaining, start=1):
                if lo.get(grouping_key):
                    grouped_nodes[str(lo[grouping_key])].append(node)
            for nodes in grouped_nodes.values():
                anchor = manager.NodeToIndex(nodes[0])
                for node in nodes[1:]:
                    index = manager.NodeToIndex(node)
                    routing.solver().Add(routing.ActiveVar(anchor) == routing.ActiveVar(index))
                    routing.solver().Add(routing.VehicleVar(anchor) == routing.VehicleVar(index))

        if constraint_is_hard(parameters, "historical_pairing_preference") or constraint_is_hard(parameters, "route_sequence_stability"):
            for source_node, source_lo in enumerate(remaining, start=1):
                source_index = manager.NodeToIndex(source_node)
                for target_node, target_lo in enumerate(remaining, start=1):
                    if source_node == target_node:
                        continue
                    disallowed = False
                    if constraint_is_hard(parameters, "historical_pairing_preference") and source_lo.get("spbu_id") != target_lo.get("spbu_id"):
                        disallowed = float((source_lo.get("historical_pairing_scores") or {}).get(target_lo.get("spbu_id"), 0)) <= 0
                    if constraint_is_hard(parameters, "route_sequence_stability"):
                        source_sequence = source_lo.get("current_stop_sequence")
                        target_sequence = target_lo.get("current_stop_sequence")
                        disallowed = disallowed or (
                            source_sequence is not None and target_sequence is not None and int(source_sequence) >= int(target_sequence)
                        )
                    if disallowed:
                        routing.NextVar(source_index).RemoveValue(manager.NodeToIndex(target_node))

        search = pywrapcp.DefaultRoutingSearchParameters()
        search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        search.time_limit.FromSeconds(
            int(parameters.get("route_round_time_limit", parameters.get("route_optimization_time_limit", 30)))
        )
        search.log_search = False

        warm_routes, _ = self._build_warm_routes(
            remaining,
            vehicles,
            source=str(parameters.get("route_warm_start_source") or "PHASE6"),
        )
        warm_assignment = routing.ReadAssignmentFromRoutes(warm_routes, True) if any(warm_routes) else None
        solution = routing.SolveFromAssignmentWithParameters(warm_assignment, search) if warm_assignment else routing.SolveWithParameters(search)
        if solution is None:
            routing_status = routing.status()
            if routing_status == getattr(routing_enums_pb2.RoutingSearchStatus, "ROUTING_FAIL_TIMEOUT", None):
                solver_status = "TIMEOUT"
            elif routing_status == routing_enums_pb2.RoutingSearchStatus.ROUTING_NOT_SOLVED:
                solver_status = "UNKNOWN"
            else:
                solver_status = "INFEASIBLE"
            return [], set(), solver_status, 0.0
        routes: list[dict] = []
        served: set[int] = set()
        for vehicle_index in range(len(vehicles)):
            index = routing.Start(vehicle_index)
            nodes: list[int] = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node:
                    nodes.append(node)
                    served.add(node)
                index = solution.Value(routing.NextVar(index))
            if nodes:
                routes.append({"vehicle_index": vehicle_index, "node_indices": nodes, "start_minutes": solution.Value(time_dimension.CumulVar(routing.Start(vehicle_index)))})
        status = "OPTIMAL" if routing.status() == routing_enums_pb2.RoutingSearchStatus.ROUTING_OPTIMAL else "FEASIBLE"
        return routes, served, status, float(solution.ObjectiveValue())

    def solve(
        self,
        *,
        loading_orders: list[dict],
        vehicles: list[dict],
        distance_matrix: list[list[int]],
        time_matrix: list[list[int]],
        day_start: datetime,
        depot_close: datetime,
        parameters: dict,
    ) -> dict:
        time_matrix = travel_time_matrix(distance_matrix, time_matrix, parameters)
        solve_started = perf_counter()
        solve_time_limit = max(1, int(parameters.get("route_optimization_time_limit", parameters.get("optimization_time_limit", 30))))
        solve_deadline = solve_started + solve_time_limit
        time_limit_reached = False
        remaining = [dict(row) for row in loading_orders]
        # Matrices are indexed to the original loading-order list.  Every round
        # builds the corresponding depot + remaining-node submatrix.
        original_index = {str(row["loading_order_id"]): index for index, row in enumerate(loading_orders, start=1)}
        vehicle_state = {row["mt_id"]: dict(row) for row in vehicles}
        trips: list[dict] = []
        dropped: list[dict] = []
        solver_statuses: list[str] = []
        warm_start_rounds: list[dict] = []
        objective_value = 0.0
        depot_close_minutes = _minutes_between(day_start, depot_close)
        max_trips = int(parameters.get("maximum_trips_per_mt", 6))
        turnaround_buffer = timedelta(
            minutes=max(0, int(parameters.get("mt_turnaround_buffer_minutes", 30)))
        )

        for trip_round in range(1, max_trips + 1):
            if not remaining:
                break
            remaining_budget = solve_deadline - perf_counter()
            if remaining_budget <= 0:
                time_limit_reached = True
                break
            remaining_seconds = max(1, math.ceil(remaining_budget))
            remaining_rounds = max(1, max_trips - trip_round + 1)
            # Reserve search time for later physical-trip rounds. Previously
            # round 1 could consume the entire route budget and prevent the
            # multi-trip loop from ever starting round 2.
            round_time_limit = max(1, remaining_seconds // remaining_rounds)
            active_vehicles = [
                row for row in vehicle_state.values()
                if (row.get("operational_status") != "UNAVAILABLE" or not constraint_is_hard(parameters, "vehicle_availability"))
                and row.get("effective_eta_depot") is not None
                and (
                    _utc(row["effective_eta_depot"]) < _utc(depot_close)
                    or not constraint_is_hard(parameters, "vehicle_availability")
                    or not constraint_is_hard(parameters, "depot_operating_window")
                )
                and (
                    int(row.get("working_time_remaining_minutes") or 0) > 0
                    or not constraint_is_hard(parameters, "vehicle_working_time")
                )
            ]
            if not active_vehicles:
                break
            matrix_indexes = [0, *[original_index[str(row["loading_order_id"])] for row in remaining]]
            round_distance = [[distance_matrix[i][j] for j in matrix_indexes] for i in matrix_indexes]
            round_time = [[time_matrix[i][j] for j in matrix_indexes] for i in matrix_indexes]
            warm_routes, warm_seeded_lo_count = self._build_warm_routes(
                remaining,
                active_vehicles,
                source=str(parameters.get("route_warm_start_source") or "PHASE6"),
            )
            warm_start_rounds.append({
                "round": trip_round,
                "source": str(parameters.get("route_warm_start_source") or "PHASE6").upper(),
                "seeded_lo_count": warm_seeded_lo_count,
                "seeded_vehicle_count": sum(bool(route) for route in warm_routes),
            })
            raw_routes, _, status, round_objective = self._solve_round(
                remaining=remaining,
                vehicles=active_vehicles,
                distance_matrix=round_distance,
                time_matrix=round_time,
                day_start=day_start,
                depot_close_minutes=depot_close_minutes,
                parameters={**parameters, "route_round_time_limit": round_time_limit},
            )
            solver_statuses.append(status)
            objective_value += round_objective
            if not raw_routes:
                break
            accepted_ids: set[str] = set()
            for raw_route in raw_routes:
                vehicle = active_vehicles[raw_route["vehicle_index"]]
                route_los = [remaining[node - 1] for node in raw_route["node_indices"]]
                compartment_seconds = max(1, min(5, math.ceil(solve_deadline - perf_counter())))
                compartment_result = self.compartments.assign(
                    route_los, vehicle.get("compartments") or [], parameters=parameters, time_limit_seconds=compartment_seconds
                )
                if not compartment_result["feasible"]:
                    for lo in route_los:
                        dropped.append({**lo, "reason_code": "COMPARTMENT_INFEASIBLE", "reason_description": "LO product volumes cannot be placed into this MT without mixing products inside a compartment."})
                        accepted_ids.add(str(lo["loading_order_id"]))
                    continue
                ready = _utc(day_start) + timedelta(minutes=int(raw_route.get("start_minutes") or 0))
                grouped_stops: list[tuple[int, list[dict]]] = []
                grouped_index: dict[str, int] = {}
                for lo in route_los:
                    spbu_id = str(lo["spbu_id"])
                    if spbu_id in grouped_index:
                        grouped_stops[grouped_index[spbu_id]][1].append(lo)
                    else:
                        grouped_index[spbu_id] = len(grouped_stops)
                        grouped_stops.append((original_index[str(lo["loading_order_id"])], [lo]))
                previous = 0
                leg_times = []
                for node, _ in grouped_stops:
                    leg_times.append(int(time_matrix[previous][node]))
                    previous = node
                leg_times.append(int(time_matrix[previous][0]))
                earliest_arrivals = [
                    max(0, int(stop_los[0].get("time_window_start_minutes") or 0) * 60 - int((ready - _utc(day_start)).total_seconds()))
                    if constraint_is_hard(parameters, "spbu_time_window") else 0
                    for _, stop_los in grouped_stops
                ]
                timing = trip_clock(leg_times, int(parameters.get("default_spbu_service_minutes", 30)) * 60, parameters, earliest_arrivals)
                previous = 0
                drive_seconds = 0
                stops = []
                arrival = ready
                for sequence, (node, stop_los) in enumerate(grouped_stops, start=1):
                    leg_seconds = int(time_matrix[previous][node])
                    drive_seconds += leg_seconds
                    arrival = ready + timedelta(seconds=timing["arrival_offsets"][sequence - 1])
                    departure = ready + timedelta(seconds=timing["departure_offsets"][sequence - 1])
                    stops.append({"sequence": sequence, "loading_order": stop_los[0], "loading_orders": stop_los, "arrival": arrival, "departure": departure, "leg_seconds": leg_seconds, "leg_distance_meters": int(distance_matrix[previous][node])})
                    arrival = departure
                    previous = node
                return_seconds = int(time_matrix[previous][0])
                drive_seconds += return_seconds
                preliminary_return = ready + timedelta(seconds=timing["total_seconds"])
                distance_meters = sum(int(stop["leg_distance_meters"]) for stop in stops) + int(distance_matrix[previous][0])
                operating_minutes = _minutes_between(ready, preliminary_return)
                if (
                    constraint_is_hard(parameters, "depot_operating_window") and ready > _utc(depot_close)
                ) or (
                    constraint_is_hard(parameters, "vehicle_working_time") and operating_minutes > int(vehicle["working_time_remaining_minutes"])
                ):
                    # The time dimension normally prevents this; retain an explicit
                    # guard for fallback matrices and post-compartment validation.
                    continue
                if constraint_is_hard(parameters, "spbu_time_window") and any(
                    stop["loading_order"].get("time_window_start_minutes") is not None
                    and stop["loading_order"].get("time_window_end_minutes") is not None
                    and not int(stop["loading_order"]["time_window_start_minutes"]) <= _minutes_between(day_start, stop["arrival"]) <= int(stop["loading_order"]["time_window_end_minutes"])
                    for stop in stops):
                    continue
                constraint_violations = list(compartment_result.get("constraint_violations") or [])
                selected_volume = sum(float(lo["volume_kl"]) for lo in route_los)
                if selected_volume > float(vehicle["capacity_kl"]) + 1e-9 and constraint_is_soft(parameters, "vehicle_capacity"):
                    constraint_violations.append({"constraint_id": "vehicle_capacity", "penalty": constraint_penalty(parameters, "vehicle_capacity"), "entity": vehicle["mt_id"]})
                if ready < _utc(vehicle.get("availability_eta_depot") or vehicle["effective_eta_depot"]) and constraint_is_soft(parameters, "vehicle_availability"):
                    constraint_violations.append({"constraint_id": "vehicle_availability", "penalty": constraint_penalty(parameters, "vehicle_availability"), "entity": vehicle["mt_id"]})
                if ready < _utc(vehicle.get("depot_operational_start") or day_start) and constraint_is_soft(parameters, "depot_operating_window"):
                    constraint_violations.append({"constraint_id": "depot_operating_window", "penalty": constraint_penalty(parameters, "depot_operating_window"), "entity": vehicle["mt_id"]})
                if operating_minutes > int(vehicle["working_time_remaining_minutes"]) and constraint_is_soft(parameters, "vehicle_working_time"):
                    constraint_violations.append({"constraint_id": "vehicle_working_time", "penalty": constraint_penalty(parameters, "vehicle_working_time"), "entity": vehicle["mt_id"]})
                if ready > _utc(depot_close) and constraint_is_soft(parameters, "depot_operating_window"):
                    constraint_violations.append({"constraint_id": "depot_operating_window", "penalty": constraint_penalty(parameters, "depot_operating_window"), "entity": vehicle["mt_id"]})
                for lo in route_los:
                    for constraint_id in (lo.get("constraint_violations_by_vehicle") or {}).get(vehicle["mt_id"], []):
                        if constraint_is_soft(parameters, constraint_id):
                            constraint_violations.append({"constraint_id": constraint_id, "penalty": constraint_penalty(parameters, constraint_id), "entity": lo["loading_order_id"]})
                    if lo.get("phase6_predicted_vehicle_id") and lo["phase6_predicted_vehicle_id"] != vehicle["mt_id"] and constraint_is_soft(parameters, "phase6_vehicle_preference"):
                        constraint_violations.append({"constraint_id": "phase6_vehicle_preference", "penalty": constraint_penalty(parameters, "phase6_vehicle_preference"), "entity": lo["loading_order_id"]})
                    if lo.get("current_vehicle_id") and lo["current_vehicle_id"] != vehicle["mt_id"] and constraint_is_soft(parameters, "previous_vehicle_stability"):
                        constraint_violations.append({"constraint_id": "previous_vehicle_stability", "penalty": constraint_penalty(parameters, "previous_vehicle_stability"), "entity": lo["loading_order_id"]})
                    if lo.get("freeze_window_candidate") and lo.get("current_vehicle_id") != vehicle["mt_id"] and constraint_is_soft(parameters, "freeze_window"):
                        constraint_violations.append({"constraint_id": "freeze_window", "penalty": constraint_penalty(parameters, "freeze_window"), "entity": lo["loading_order_id"]})
                    affinity = float((lo.get("historical_mt_affinity") or {}).get(vehicle["mt_id"], 0))
                    if affinity < 1 and constraint_is_soft(parameters, "historical_mt_affinity_preference"):
                        constraint_violations.append({"constraint_id": "historical_mt_affinity_preference", "penalty": round((1 - affinity) * constraint_penalty(parameters, "historical_mt_affinity_preference")), "entity": lo["loading_order_id"]})
                for source_lo, target_lo in zip(route_los, route_los[1:]):
                    if source_lo.get("phase6_predicted_shipment_id") != target_lo.get("phase6_predicted_shipment_id") and constraint_is_soft(parameters, "phase6_shipment_preference"):
                        constraint_violations.append({"constraint_id": "phase6_shipment_preference", "penalty": constraint_penalty(parameters, "phase6_shipment_preference"), "entity": f"{source_lo['loading_order_id']}->{target_lo['loading_order_id']}"})
                    if source_lo.get("current_shipment_id") and source_lo.get("current_shipment_id") != target_lo.get("current_shipment_id") and constraint_is_soft(parameters, "previous_shipment_stability"):
                        constraint_violations.append({"constraint_id": "previous_shipment_stability", "penalty": constraint_penalty(parameters, "previous_shipment_stability"), "entity": f"{source_lo['loading_order_id']}->{target_lo['loading_order_id']}"})
                    pairing_score = float((source_lo.get("historical_pairing_scores") or {}).get(target_lo.get("spbu_id"), 0))
                    if pairing_score < 1 and constraint_is_soft(parameters, "historical_pairing_preference"):
                        constraint_violations.append({"constraint_id": "historical_pairing_preference", "penalty": round((1 - pairing_score) * constraint_penalty(parameters, "historical_pairing_preference")), "entity": f"{source_lo['loading_order_id']}->{target_lo['loading_order_id']}"})
                    source_sequence = source_lo.get("current_stop_sequence")
                    target_sequence = target_lo.get("current_stop_sequence")
                    if source_sequence is not None and target_sequence is not None and int(source_sequence) >= int(target_sequence) and constraint_is_soft(parameters, "route_sequence_stability"):
                        constraint_violations.append({"constraint_id": "route_sequence_stability", "penalty": constraint_penalty(parameters, "route_sequence_stability"), "entity": f"{source_lo['loading_order_id']}->{target_lo['loading_order_id']}"})
                for stop in stops:
                    lo = stop["loading_order"]
                    start = lo.get("time_window_start_minutes")
                    end = lo.get("time_window_end_minutes")
                    arrival_minutes = _minutes_between(day_start, stop["arrival"])
                    if start is not None and end is not None and not int(start) <= arrival_minutes <= int(end) and constraint_is_soft(parameters, "spbu_time_window"):
                        constraint_violations.append({"constraint_id": "spbu_time_window", "penalty": constraint_penalty(parameters, "spbu_time_window"), "entity": lo["loading_order_id"]})
                trip_number = int(vehicle.get("completed_trip_count") or 0) + 1
                trip = {
                    "vehicle_id": vehicle["mt_id"],
                    "trip_number": trip_number,
                    "shipment_id": f"P7-SHIP-{vehicle['mt_id']}-{trip_number:02d}",
                    "vehicle_ready_at_depot": ready,
                    "preliminary_gate_out": ready,
                    "gate_out": ready,
                    "estimated_return_depot": preliminary_return,
                    "distance_meters": distance_meters,
                    "driving_seconds": drive_seconds,
                    "trip_timing": timing,
                    "service_seconds": len(stops) * int(parameters.get("default_spbu_service_minutes", 30)) * 60,
                    "operating_minutes": operating_minutes,
                    "stops": stops,
                    "lo_assignments": compartment_result["assignments"],
                    "compartment_engine": compartment_result["engine"],
                    "constraint_violations": constraint_violations,
                    "constraint_penalty_cost": sum(float(row.get("penalty") or 0) for row in constraint_violations),
                    "working_time_remaining_before_trip": int(vehicle["working_time_remaining_minutes"]),
                }
                trips.append(trip)
                accepted_ids.update(str(lo["loading_order_id"]) for lo in route_los)
                state = vehicle_state[vehicle["mt_id"]]
                next_vehicle_ready_at_depot = preliminary_return + turnaround_buffer
                state["effective_eta_depot"] = next_vehicle_ready_at_depot
                state["availability_eta_depot"] = next_vehicle_ready_at_depot
                state["completed_trip_count"] = trip_number
                state["working_time_used_minutes"] = int(state.get("working_time_used_minutes") or 0) + operating_minutes
                state["working_time_remaining_minutes"] = int(state.get("working_time_remaining_minutes") or 0) - operating_minutes
            if not accepted_ids:
                break
            remaining = [row for row in remaining if str(row["loading_order_id"]) not in accepted_ids]

        for lo in remaining:
            if lo.get("user_cancelled"):
                code = "USER_CANCELLED"
                description = "LO was cancelled by the dispatcher and is excluded from routing."
            elif (time_matrix[0][original_index[str(lo["loading_order_id"])]] >= 1_000_000_000
                  or time_matrix[original_index[str(lo["loading_order_id"])]][0] >= 1_000_000_000):
                code = "RESTRICTED_ROUTE_REVIEW_REQUIRED"
                description = "Configured Google waypoint candidates did not yield a permitted route. Review the detour; other road alternatives may still exist."
            elif not lo.get("allowed_vehicle_ids"):
                code = "NO_COMPATIBLE_MT"
                description = "No active depot MT passes vehicle-class and master-tag compatibility for this SPBU."
            elif all(float(vehicle_state[mt_id]["capacity_kl"]) + 1e-9 < float(lo["volume_kl"]) for mt_id in lo["allowed_vehicle_ids"] if mt_id in vehicle_state):
                code = "INSUFFICIENT_CAPACITY"
                description = "All compatible MT have less total capacity than the LO volume."
            elif all(_utc(vehicle_state[mt_id]["effective_eta_depot"]) >= _utc(depot_close) for mt_id in lo["allowed_vehicle_ids"] if mt_id in vehicle_state):
                code = "DEPOT_TIME_EXHAUSTED"
                description = "All compatible MT become available after the depot gate-out operating limit."
            else:
                code = "NO_FEASIBLE_ROUTE"
                description = "No route satisfies the remaining capacity, working-time, time-window, and depot constraints."
            dropped.append({**lo, "reason_code": code, "reason_description": description})
        if trips and dropped:
            final_status = "PARTIAL"
        elif trips:
            final_status = "OPTIMAL" if solver_statuses and all(status == "OPTIMAL" for status in solver_statuses) else "FEASIBLE"
        else:
            terminal_status = next(
                (status for status in reversed(solver_statuses) if status in {"TIMEOUT", "UNKNOWN"}),
                None,
            )
            final_status = terminal_status or "INFEASIBLE"
        return {
            "solver_status": final_status,
            "objective_value": objective_value,
            "trips": trips,
            "dropped": dropped,
            "vehicle_state": list(vehicle_state.values()),
            "solver_metadata": {
                "engine": "OR_TOOLS_ROUTING" if ORTOOLS_AVAILABLE else "DETERMINISTIC_FALLBACK",
                "round_statuses": solver_statuses,
                "multi_trip_rounds": max((trip["trip_number"] for trip in trips), default=0),
                "route_time_limit_seconds": solve_time_limit,
                "time_limit_seconds": solve_time_limit,
                "route_time_limit_reached": time_limit_reached,
                "time_limit_reached": time_limit_reached,
                "duration_ms": round((perf_counter() - solve_started) * 1000),
                "route_warm_start_source": str(parameters.get("route_warm_start_source") or "PHASE6").upper(),
                "route_warm_start_version_id": parameters.get("route_warm_start_version_id"),
                "warm_start_rounds": warm_start_rounds,
                "constraint_violation_count": sum(len(trip.get("constraint_violations") or []) for trip in trips),
                "constraint_penalty_cost": sum(float(trip.get("constraint_penalty_cost") or 0) for trip in trips),
            },
        }


class BayQueueOptimizationService:
    """Operational FIFO scheduler with an opt-in legacy CP-SAT strategy."""

    @staticmethod
    def loading_minutes(trip: dict, durations: dict[str, int], *, loading_mode: str, arms: int = 1, parameters: dict | None = None) -> int:
        parameters = parameters or {}
        products_by_compartment: dict[str, set[str]] = defaultdict(set)
        for assignment in trip.get("lo_assignments") or []:
            compartment = str(assignment["compartment_id"])
            product = str(assignment.get("product_id") or "UNKNOWN")
            products_by_compartment[compartment].add(product)
            if len(products_by_compartment[compartment]) > 1 and constraint_is_hard(parameters, "compartment_product_separation"):
                raise ValueError("ONE_COMPARTMENT_ONE_PRODUCT")
        values = [
            sum(int(durations.get(product, 0)) for product in products)
            for products in products_by_compartment.values()
        ]
        if not values or any(value <= 0 for value in values):
            raise ValueError("MISSING_LOADING_DURATION")
        if loading_mode == "PARALLEL":
            return max(max(values), math.ceil(sum(values) / max(1, arms)))
        return sum(values)

    def schedule(
        self,
        *,
        trips: list[dict],
        bays: list[dict],
        actual_states: list[dict],
        initial_queue: list[dict],
        loading_durations: dict[str, int],
        day_start: datetime,
        depot_close: datetime,
        parameters: dict,
    ) -> dict:
        strategy = str(parameters.get("bay_scheduler_strategy") or "FIFO_BALANCED").upper()
        if strategy == "CP_SAT":
            return self._cp_sat_schedule(
                trips=trips,
                bays=bays,
                actual_states=actual_states,
                initial_queue=initial_queue,
                loading_durations=loading_durations,
                day_start=day_start,
                depot_close=depot_close,
                parameters=parameters,
            )
        return self._fifo_balanced_schedule(
            trips=trips,
            bays=bays,
            actual_states=actual_states,
            initial_queue=initial_queue,
            loading_durations=loading_durations,
            day_start=day_start,
            depot_close=depot_close,
            parameters=parameters,
        )

    def _fifo_balanced_schedule(
        self,
        *,
        trips: list[dict],
        bays: list[dict],
        actual_states: list[dict],
        initial_queue: list[dict],
        loading_durations: dict[str, int],
        day_start: datetime,
        depot_close: datetime,
        parameters: dict,
    ) -> dict:
        """Assign ready MT trips FIFO to the earliest compatible balanced bay."""
        schedule_started = perf_counter()
        turnaround_buffer = timedelta(
            minutes=max(0, int(parameters.get("mt_turnaround_buffer_minutes", 30)))
        )
        if not trips:
            return {
                "solver_status": "FEASIBLE",
                "assignments": [],
                "dropped_trip_indexes": [],
                "dropped_trip_reasons": {},
                "engine": "FIFO_BALANCED",
                "raw_solver_status": "DETERMINISTIC",
                "num_search_workers": 0,
                "time_limit_reached": False,
                "duration_ms": 0,
                "scheduler_metadata": {
                    "strategy": "FIFO_BALANCED",
                    "trip_count": 0,
                    "bay_count": len(bays),
                    "candidate_evaluation_count": 0,
                },
            }

        active_bays = [
            dict(bay) for bay in bays
            if str(bay.get("active_status") or "ACTIVE").upper() == "ACTIVE"
        ]
        if not active_bays:
            dropped = list(range(len(trips)))
            return {
                "solver_status": "INFEASIBLE",
                "assignments": [],
                "dropped_trip_indexes": dropped,
                "dropped_trip_reasons": {index: "BAY_PRODUCT_CONSTRAINT" for index in dropped},
                "engine": "FIFO_BALANCED",
                "raw_solver_status": "DETERMINISTIC",
                "num_search_workers": 0,
                "time_limit_reached": False,
                "duration_ms": round((perf_counter() - schedule_started) * 1000),
                "scheduler_metadata": {
                    "strategy": "FIFO_BALANCED",
                    "trip_count": len(trips),
                    "bay_count": 0,
                    "candidate_evaluation_count": 0,
                },
            }

        state_by_bay = {str(row["master_bay_id"]): row for row in actual_states}
        queue_by_bay: dict[str, list[dict]] = defaultdict(list)
        for row in initial_queue:
            queue_by_bay[str(row["master_bay_id"])].append(row)
        reference_time = min((_utc(trip["vehicle_ready_at_depot"]) for trip in trips), default=_utc(day_start))
        bay_state: dict[str, dict] = {}
        for bay in active_bays:
            bay_id = str(bay["master_bay_id"])
            actual = state_by_bay.get(bay_id)
            queue_rows = sorted(queue_by_bay[bay_id], key=lambda row: int(row.get("queue_position") or 0))
            bay_open = _utc(day_start) + timedelta(minutes=int(bay.get("operational_start_minutes") or 0))
            available_at = max(reference_time, bay_open)
            if actual:
                available_at = max(
                    available_at,
                    _utc(actual.get("state_effective_at") or reference_time)
                    + timedelta(minutes=int(actual.get("remaining_loading_minutes") or 0)),
                )
            for queue_row in queue_rows:
                if queue_row.get("state_effective_at"):
                    available_at = max(available_at, _utc(queue_row["state_effective_at"]))
                available_at += timedelta(minutes=int(queue_row.get("estimated_loading_duration_minutes") or 0))
            bay_state[bay_id] = {
                "available_at": available_at,
                "assigned_trip_count": 0,
                "assigned_loading_minutes": 0,
                "initial_queue_count": len(queue_rows),
            }

        trips_by_vehicle: dict[str, list[int]] = defaultdict(list)
        for trip_index, trip in enumerate(trips):
            trips_by_vehicle[str(trip.get("vehicle_id") or "")].append(trip_index)
        for indexes in trips_by_vehicle.values():
            indexes.sort(key=lambda index: (int(trips[index].get("trip_number") or 0), index))

        trip_position_by_vehicle: dict[str, int] = {vehicle_id: 0 for vehicle_id in trips_by_vehicle}
        ready_heap: list[tuple[datetime, datetime, int, str, str, int]] = []

        def push_trip(trip_index: int, ready_at: datetime) -> None:
            trip = trips[trip_index]
            lo_identity = min(
                (str(row.get("loading_order_id") or "") for row in trip.get("lo_assignments") or []),
                default="",
            )
            heapq.heappush(
                ready_heap,
                (
                    _utc(ready_at),
                    _utc(trip.get("preliminary_gate_out") or trip.get("gate_out") or ready_at),
                    int(trip.get("trip_number") or 0),
                    str(trip.get("vehicle_id") or ""),
                    lo_identity,
                    trip_index,
                ),
            )

        for vehicle_id, indexes in trips_by_vehicle.items():
            first_index = indexes[0]
            push_trip(first_index, _utc(trips[first_index]["vehicle_ready_at_depot"]))

        assignments: list[dict] = []
        dropped: list[int] = []
        dropped_reasons: dict[int, str] = {}
        candidate_evaluation_count = 0
        fifo_sequence = 0
        total_bay_workload_before = sum(
            max(0, _minutes_between(reference_time, state["available_at"]))
            for state in bay_state.values()
        )

        while ready_heap:
            ready_at, _, _, vehicle_id, _, trip_index = heapq.heappop(ready_heap)
            trip = trips[trip_index]
            trip_products = {
                str(row.get("product_id") or "UNKNOWN")
                for row in trip.get("lo_assignments") or []
            }
            current_bays = {
                str(row["current_bay_id"])
                for row in trip.get("lo_assignments") or []
                if row.get("current_bay_id")
            }
            candidates: list[tuple[tuple, dict]] = []
            structurally_eligible = False
            window_exhausted = False
            eligible_bay_ids: list[str] = []

            for bay in active_bays:
                candidate_evaluation_count += 1
                bay_id = str(bay["master_bay_id"])
                allowed_products = set(str(value) for value in bay.get("allowed_product_ids") or [])
                product_violation = not bool(bay.get("all_products_allowed")) and not trip_products.issubset(allowed_products)
                if product_violation and constraint_is_hard(parameters, "bay_product_compatibility"):
                    continue
                bay_change_violation = bool(current_bays) and bay_id not in current_bays
                if bay_change_violation and constraint_is_hard(parameters, "bay_change_stability"):
                    continue
                try:
                    loading_minutes = self.loading_minutes(
                        trip,
                        loading_durations,
                        loading_mode=str(bay.get("loading_mode") or parameters.get("loading_mode", "SEQUENTIAL")),
                        arms=int(bay.get("number_of_loading_arms") or 1),
                        parameters=parameters,
                    )
                except ValueError:
                    continue
                structurally_eligible = True
                eligible_bay_ids.append(bay_id)
                state = bay_state[bay_id]
                bay_open = _utc(day_start) + timedelta(minutes=int(bay.get("operational_start_minutes") or 0))
                bay_close = _utc(day_start) + timedelta(
                    minutes=int(bay.get("operational_end_minutes") or _minutes_between(day_start, depot_close))
                )
                start = ready_at
                if constraint_rule(parameters, "bay_operating_window").get("enabled", True):
                    start = max(start, bay_open)
                if constraint_rule(parameters, "bay_actual_queue").get("enabled", True) or constraint_rule(parameters, "bay_no_overlap").get("enabled", True):
                    start = max(start, _utc(state["available_at"]))
                finish = start + timedelta(minutes=loading_minutes)
                gate_out = finish + timedelta(minutes=int(parameters.get("gate_process_time", 5)))
                if (
                    constraint_is_hard(parameters, "bay_operating_window") and gate_out > bay_close
                ) or (
                    constraint_is_hard(parameters, "depot_operating_window") and gate_out > _utc(depot_close)
                ):
                    window_exhausted = True
                    continue

                violations: list[dict] = []
                if product_violation and constraint_is_soft(parameters, "bay_product_compatibility"):
                    violations.append({
                        "constraint_id": "bay_product_compatibility",
                        "penalty": constraint_penalty(parameters, "bay_product_compatibility"),
                        "entity": bay_id,
                    })
                if bay_change_violation and constraint_is_soft(parameters, "bay_change_stability"):
                    violations.append({
                        "constraint_id": "bay_change_stability",
                        "penalty": constraint_penalty(parameters, "bay_change_stability"),
                        "entity": bay_id,
                    })
                if gate_out > bay_close and constraint_is_soft(parameters, "bay_operating_window"):
                    violations.append({
                        "constraint_id": "bay_operating_window",
                        "penalty": constraint_penalty(parameters, "bay_operating_window"),
                        "entity": bay_id,
                    })
                if gate_out > _utc(depot_close) and constraint_is_soft(parameters, "depot_operating_window"):
                    violations.append({
                        "constraint_id": "depot_operating_window",
                        "penalty": constraint_penalty(parameters, "depot_operating_window"),
                        "entity": bay_id,
                    })
                penalty_cost = sum(float(row.get("penalty") or 0) for row in violations)
                flexibility = 1_000_000 if bay.get("all_products_allowed") else len(allowed_products)
                projected_workload = int(state["assigned_loading_minutes"]) + loading_minutes
                score = (
                    penalty_cost,
                    gate_out,
                    projected_workload,
                    int(state["assigned_trip_count"]),
                    flexibility,
                    str(bay.get("bay_id") or bay_id),
                    bay_id,
                )
                candidates.append((score, {
                    "bay": bay,
                    "loading_start": start,
                    "loading_finish": finish,
                    "gate_out": gate_out,
                    "loading_minutes": loading_minutes,
                    "violations": violations,
                }))

            if not candidates:
                reason = "BAY_WINDOW_EXHAUSTED" if structurally_eligible and window_exhausted else "BAY_PRODUCT_CONSTRAINT"
                dropped.append(trip_index)
                dropped_reasons[trip_index] = reason
                # Preserve physical trip order: a later trip cannot use the MT
                # when an earlier trip never loaded/gated out.
                indexes = trips_by_vehicle[vehicle_id]
                position = trip_position_by_vehicle[vehicle_id]
                for later_index in indexes[position + 1:]:
                    if later_index not in dropped:
                        dropped.append(later_index)
                        dropped_reasons[later_index] = "BAY_CONGESTION"
                trip_position_by_vehicle[vehicle_id] = len(indexes)
                continue

            _, selected = min(candidates, key=lambda row: row[0])
            bay = selected["bay"]
            bay_id = str(bay["master_bay_id"])
            state = bay_state[bay_id]
            fifo_sequence += 1
            queue_position = int(state["initial_queue_count"]) + int(state["assigned_trip_count"]) + 1
            workload_before = int(state["assigned_loading_minutes"])
            state["available_at"] = selected["loading_finish"]
            state["assigned_trip_count"] = int(state["assigned_trip_count"]) + 1
            state["assigned_loading_minutes"] = workload_before + int(selected["loading_minutes"])
            assignments.append({
                "trip_index": trip_index,
                "master_bay_id": bay_id,
                "vehicle_ready_at_depot": ready_at,
                # A ready MT may remain parked until it is operationally
                # released to the selected bay. Future system-planned work
                # therefore starts at queue entry/loading readiness, not at
                # its passive availability ETA.
                "queue_start": selected["loading_start"],
                "loading_start": selected["loading_start"],
                "loading_finish": selected["loading_finish"],
                "gate_out": selected["gate_out"],
                "queue_minutes": 0,
                "loading_minutes": int(selected["loading_minutes"]),
                "constraint_violations": selected["violations"],
                "fifo_sequence": fifo_sequence,
                "bay_queue_position": queue_position,
                "eligible_bay_ids": sorted(set(eligible_bay_ids)),
                "bay_workload_minutes_before": workload_before,
                "bay_workload_minutes_after": int(state["assigned_loading_minutes"]),
                "selection_reason": "EARLIEST_COMPATIBLE_BALANCED_GATE_OUT",
            })

            original_gate_out = _utc(trip.get("gate_out") or ready_at)
            original_return = _utc(trip.get("estimated_return_depot") or original_gate_out)
            actual_return = selected["gate_out"] + max(timedelta(0), original_return - original_gate_out)
            indexes = trips_by_vehicle[vehicle_id]
            position = trip_position_by_vehicle[vehicle_id]
            next_position = position + 1
            trip_position_by_vehicle[vehicle_id] = next_position
            if next_position < len(indexes):
                next_index = indexes[next_position]
                next_ready = max(
                    _utc(trips[next_index]["vehicle_ready_at_depot"]),
                    actual_return + turnaround_buffer,
                )
                push_trip(next_index, next_ready)

        dropped = sorted(set(dropped))
        if dropped and constraint_is_hard(parameters, "serve_loading_order"):
            blocking_reason = dropped_reasons.get(dropped[0], "BAY_CONGESTION")
            assignments = []
            dropped = list(range(len(trips)))
            dropped_reasons = {index: blocking_reason for index in dropped}
            solver_status = "INFEASIBLE"
        elif assignments and dropped:
            solver_status = "PARTIAL"
        else:
            solver_status = "FEASIBLE" if assignments else "INFEASIBLE"
        workload_by_bay = {
            bay_id: {
                "assigned_trip_count": int(state["assigned_trip_count"]),
                "assigned_loading_minutes": int(state["assigned_loading_minutes"]),
                "initial_queue_count": int(state["initial_queue_count"]),
                "available_at": _utc(state["available_at"]).isoformat(),
            }
            for bay_id, state in bay_state.items()
        }
        return {
            "solver_status": solver_status,
            "assignments": assignments,
            "dropped_trip_indexes": dropped,
            "dropped_trip_reasons": dropped_reasons,
            "engine": "FIFO_BALANCED",
            "raw_solver_status": "DETERMINISTIC",
            "time_limit_seconds": 0,
            "time_limit_reached": False,
            "num_search_workers": 0,
            "duration_ms": round((perf_counter() - schedule_started) * 1000),
            "scheduler_metadata": {
                "strategy": "FIFO_BALANCED",
                "trip_count": len(trips),
                "bay_count": len(active_bays),
                "candidate_evaluation_count": candidate_evaluation_count,
                "initial_blocked_workload_minutes": total_bay_workload_before,
                "workload_by_bay": workload_by_bay,
            },
        }

    def _cp_sat_schedule(
        self,
        *,
        trips: list[dict],
        bays: list[dict],
        actual_states: list[dict],
        initial_queue: list[dict],
        loading_durations: dict[str, int],
        day_start: datetime,
        depot_close: datetime,
        parameters: dict,
    ) -> dict:
        if not trips:
            return {"solver_status": "FEASIBLE", "assignments": [], "dropped_trip_indexes": [], "dropped_trip_reasons": {}, "engine": "OR_TOOLS_CP_SAT"}
        if not ORTOOLS_AVAILABLE:
            return self._fallback_schedule(
                trips=trips, bays=bays, actual_states=actual_states, initial_queue=initial_queue,
                loading_durations=loading_durations, day_start=day_start, depot_close=depot_close, parameters=parameters,
            )
        depot_close_minutes = max(1, _minutes_between(day_start, depot_close))
        horizon = depot_close_minutes if constraint_is_hard(parameters, "depot_operating_window") else depot_close_minutes + 24 * 60
        state_by_bay = {row["master_bay_id"]: row for row in actual_states}
        queue_by_bay: dict[str, list[dict]] = defaultdict(list)
        for row in initial_queue:
            queue_by_bay[row["master_bay_id"]].append(row)
        blocked_until: dict[str, int] = {}
        for bay in bays:
            bay_id = bay["master_bay_id"]
            state = state_by_bay.get(bay_id)
            relevant_queue = sorted(queue_by_bay[bay_id], key=lambda row: row["queue_position"])
            trip_ready_floor = min(
                (_minutes_between(day_start, trip["vehicle_ready_at_depot"]) for trip in trips),
                default=0,
            )
            queue_effective_floor = min(
                (
                    _minutes_between(day_start, row["state_effective_at"])
                    for row in relevant_queue
                    if row.get("state_effective_at")
                ),
                default=trip_ready_floor,
            )
            blocked = max(trip_ready_floor, queue_effective_floor)
            if state:
                blocked = max(blocked, _minutes_between(day_start, state["state_effective_at"]) + int(state.get("remaining_loading_minutes") or 0))
            blocked += sum(int(row.get("estimated_loading_duration_minutes") or 0) for row in relevant_queue)
            blocked_until[bay_id] = blocked

        model = cp_model.CpModel()
        starts: dict[int, Any] = {}
        ends: dict[int, Any] = {}
        served: dict[int, Any] = {}
        presences: dict[tuple[int, int], Any] = {}
        intervals_by_bay: dict[int, list[Any]] = defaultdict(list)
        duration_by_trip_bay: dict[tuple[int, int], int] = {}
        eligible_by_trip: dict[int, list[int]] = defaultdict(list)
        objective_terms: list[Any] = []
        violation_vars: dict[tuple[str, int, int | None], Any] = {}
        gate_process = int(parameters.get("gate_process_time", 5))
        for trip_index, trip in enumerate(trips):
            served[trip_index] = model.new_bool_var(f"trip_{trip_index}_served")
            starts[trip_index] = model.new_int_var(0, horizon, f"trip_{trip_index}_start")
            ends[trip_index] = model.new_int_var(0, horizon, f"trip_{trip_index}_end")
            ready = _minutes_between(day_start, trip["vehicle_ready_at_depot"])
            # An omitted soft-service trip must not make the whole model
            # infeasible merely because its MT becomes ready after depot close.
            # Readiness is operationally relevant only when the trip is served.
            model.add(starts[trip_index] >= ready).only_enforce_if(served[trip_index])
            trip_products = {str(row.get("product_id") or "UNKNOWN") for row in trip.get("lo_assignments") or []}
            current_bays = {str(row["current_bay_id"]) for row in trip.get("lo_assignments") or [] if row.get("current_bay_id")}
            for bay_index, bay in enumerate(bays):
                allowed_products = set(bay.get("allowed_product_ids") or [])
                product_violation = not bay.get("all_products_allowed") and not trip_products.issubset(allowed_products)
                if product_violation and constraint_is_hard(parameters, "bay_product_compatibility"):
                    continue
                bay_change_violation = bool(current_bays) and bay["master_bay_id"] not in current_bays
                if bay_change_violation and constraint_is_hard(parameters, "bay_change_stability"):
                    continue
                try:
                    duration = self.loading_minutes(
                        trip,
                        loading_durations,
                        loading_mode=str(bay.get("loading_mode") or parameters.get("loading_mode", "SEQUENTIAL")),
                        arms=int(bay.get("number_of_loading_arms") or 1),
                        parameters=parameters,
                    )
                except ValueError:
                    continue
                presence = model.new_bool_var(f"trip_{trip_index}_bay_{bay_index}")
                interval = model.new_optional_interval_var(starts[trip_index], duration, ends[trip_index], presence, f"interval_{trip_index}_{bay_index}")
                presences[trip_index, bay_index] = presence
                intervals_by_bay[bay_index].append(interval)
                duration_by_trip_bay[trip_index, bay_index] = duration
                eligible_by_trip[trip_index].append(bay_index)
                bay_open = int(bay.get("operational_start_minutes") or 0)
                bay_close = int(bay.get("operational_end_minutes") or horizon)
                if constraint_is_hard(parameters, "bay_operating_window"):
                    model.add(starts[trip_index] >= bay_open).only_enforce_if(presence)
                    model.add(ends[trip_index] + gate_process <= bay_close).only_enforce_if(presence)
                elif constraint_is_soft(parameters, "bay_operating_window"):
                    if bay_open > 0:
                        early_violation = model.new_bool_var(f"bay_open_violation_{trip_index}_{bay_index}")
                        model.add(starts[trip_index] >= bay_open - horizon * early_violation).only_enforce_if(presence)
                        model.add(starts[trip_index] <= bay_open - 1).only_enforce_if(early_violation)
                        model.add(early_violation <= presence)
                        objective_terms.append(constraint_penalty(parameters, "bay_operating_window") * early_violation)
                        violation_vars["bay_operating_window:open", trip_index, bay_index] = early_violation
                    close_violation = model.new_bool_var(f"bay_close_violation_{trip_index}_{bay_index}")
                    model.add(ends[trip_index] + gate_process <= bay_close + horizon * close_violation).only_enforce_if(presence)
                    model.add(ends[trip_index] + gate_process >= bay_close + 1).only_enforce_if(close_violation)
                    model.add(close_violation <= presence)
                    objective_terms.append(constraint_penalty(parameters, "bay_operating_window") * close_violation)
                    violation_vars["bay_operating_window:close", trip_index, bay_index] = close_violation
                if product_violation and constraint_is_soft(parameters, "bay_product_compatibility"):
                    objective_terms.append(constraint_penalty(parameters, "bay_product_compatibility") * presence)
                    violation_vars["bay_product_compatibility", trip_index, bay_index] = presence
                if bay_change_violation and constraint_is_soft(parameters, "bay_change_stability"):
                    objective_terms.append(constraint_penalty(parameters, "bay_change_stability") * presence)
                    violation_vars["bay_change_stability", trip_index, bay_index] = presence
                blocked = blocked_until[bay["master_bay_id"]]
                if constraint_is_hard(parameters, "bay_actual_queue"):
                    model.add(starts[trip_index] >= blocked).only_enforce_if(presence)
                elif constraint_is_soft(parameters, "bay_actual_queue"):
                    violation = model.new_bool_var(f"actual_queue_violation_{trip_index}_{bay_index}")
                    model.add(starts[trip_index] >= blocked - horizon * violation).only_enforce_if(presence)
                    model.add(violation <= presence)
                    if blocked > 0:
                        model.add(starts[trip_index] <= blocked - 1).only_enforce_if(violation)
                    else:
                        model.add(violation == 0)
                    objective_terms.append(constraint_penalty(parameters, "bay_actual_queue") * violation)
                    violation_vars["bay_actual_queue", trip_index, bay_index] = violation
            if eligible_by_trip[trip_index]:
                model.add(
                    sum(presences[trip_index, bay_index] for bay_index in eligible_by_trip[trip_index])
                    == served[trip_index]
                )
            else:
                model.add(served[trip_index] == 0)
            if constraint_is_hard(parameters, "serve_loading_order"):
                model.add(served[trip_index] == 1)
            elif constraint_is_soft(parameters, "serve_loading_order"):
                lo_count = max(1, len(trip.get("lo_assignments") or []))
                objective_terms.append(
                    constraint_penalty(parameters, "serve_loading_order") * lo_count * (1 - served[trip_index])
                )
            if constraint_is_hard(parameters, "depot_operating_window"):
                model.add(ends[trip_index] + gate_process <= depot_close_minutes).only_enforce_if(served[trip_index])
            elif constraint_is_soft(parameters, "depot_operating_window"):
                violation = model.new_bool_var(f"depot_window_violation_{trip_index}")
                model.add(ends[trip_index] + gate_process <= depot_close_minutes + horizon * violation)
                model.add(ends[trip_index] + gate_process >= depot_close_minutes + 1).only_enforce_if(violation)
                model.add(violation <= served[trip_index])
                objective_terms.append(constraint_penalty(parameters, "depot_operating_window") * violation)
                violation_vars["depot_operating_window", trip_index, None] = violation
        # Later trips of one physical MT cannot be kept if an earlier trip is
        # omitted from the loading sequence.
        trip_indexes_by_vehicle: dict[str, list[int]] = defaultdict(list)
        for trip_index, trip in enumerate(trips):
            trip_indexes_by_vehicle[str(trip.get("vehicle_id") or "")].append(trip_index)
        for indexes in trip_indexes_by_vehicle.values():
            indexes.sort(key=lambda index: int(trips[index].get("trip_number") or index + 1))
            for previous, current in zip(indexes, indexes[1:]):
                model.add(served[current] <= served[previous])
        if constraint_is_hard(parameters, "bay_no_overlap"):
            for intervals in intervals_by_bay.values():
                model.add_no_overlap(intervals)
        elif constraint_is_soft(parameters, "bay_no_overlap"):
            for bay_index in intervals_by_bay:
                trip_indexes = [trip_index for trip_index in range(len(trips)) if (trip_index, bay_index) in presences]
                for offset, left in enumerate(trip_indexes):
                    for right in trip_indexes[offset + 1:]:
                        left_before = model.new_bool_var(f"bay_{bay_index}_{left}_before_{right}")
                        right_before = model.new_bool_var(f"bay_{bay_index}_{right}_before_{left}")
                        violation = model.new_bool_var(f"bay_overlap_violation_{bay_index}_{left}_{right}")
                        model.add(ends[left] <= starts[right]).only_enforce_if(left_before)
                        model.add(ends[right] <= starts[left]).only_enforce_if(right_before)
                        model.add(starts[left] <= ends[right] - 1).only_enforce_if(violation)
                        model.add(starts[right] <= ends[left] - 1).only_enforce_if(violation)
                        model.add(left_before <= presences[left, bay_index])
                        model.add(right_before <= presences[right, bay_index])
                        model.add(violation <= presences[left, bay_index])
                        model.add(violation <= presences[right, bay_index])
                        model.add(left_before + right_before + violation >= presences[left, bay_index] + presences[right, bay_index] - 1)
                        objective_terms.append(constraint_penalty(parameters, "bay_no_overlap") * violation)
                        violation_vars["bay_no_overlap", left, right * 10_000 + bay_index] = violation
        schedulable = [index for index in range(len(trips)) if eligible_by_trip[index]]
        if not schedulable:
            dropped = list(range(len(trips)))
            return {
                "solver_status": "INFEASIBLE",
                "assignments": [],
                "dropped_trip_indexes": dropped,
                "dropped_trip_reasons": {index: "BAY_PRODUCT_CONSTRAINT" for index in dropped},
                "engine": "OR_TOOLS_CP_SAT",
            }
        model.minimize(sum(ends[index] for index in schedulable) + sum(objective_terms))
        solver = cp_model.CpSolver()
        time_limit_seconds = max(1, int(parameters.get("bay_optimization_time_limit", parameters.get("optimization_time_limit", 30))))
        worker_count = max(1, int(parameters.get("bay_cp_sat_workers", 8)))
        solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = worker_count
        solve_started = perf_counter()
        status = solver.solve(model)
        solve_elapsed = perf_counter() - solve_started
        translated_status = _cp_sat_result_status(
            status,
            elapsed_seconds=solve_elapsed,
            time_limit_seconds=time_limit_seconds,
        )
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            dropped = list(range(len(trips))) if translated_status == "INFEASIBLE" else []
            return {
                "solver_status": translated_status,
                "assignments": [],
                "dropped_trip_indexes": dropped,
                "dropped_trip_reasons": {
                    index: ("BAY_PRODUCT_CONSTRAINT" if not eligible_by_trip[index] else "BAY_CONGESTION")
                    for index in dropped
                },
                "engine": "OR_TOOLS_CP_SAT",
                "raw_solver_status": solver.status_name(status),
                "time_limit_seconds": time_limit_seconds,
                "time_limit_reached": translated_status == "TIMEOUT",
                "num_search_workers": worker_count,
                "duration_ms": round(solve_elapsed * 1000),
            }
        assignments = []
        for trip_index in schedulable:
            if not solver.value(served[trip_index]):
                continue
            bay_index = next(index for index in eligible_by_trip[trip_index] if solver.value(presences[trip_index, index]))
            trip = trips[trip_index]
            start_minutes = solver.value(starts[trip_index])
            finish_minutes = solver.value(ends[trip_index])
            ready_minutes = _minutes_between(day_start, trip["vehicle_ready_at_depot"])
            assignments.append(
                {
                    "trip_index": trip_index,
                    "master_bay_id": bays[bay_index]["master_bay_id"],
                    "vehicle_ready_at_depot": _utc(trip["vehicle_ready_at_depot"]),
                    "queue_start": _utc(trip["vehicle_ready_at_depot"]),
                    "loading_start": _utc(day_start) + timedelta(minutes=start_minutes),
                    "loading_finish": _utc(day_start) + timedelta(minutes=finish_minutes),
                    "gate_out": _utc(day_start) + timedelta(minutes=finish_minutes + gate_process),
                    "queue_minutes": max(0, start_minutes - ready_minutes),
                    "loading_minutes": duration_by_trip_bay[trip_index, bay_index],
                    "constraint_violations": [
                        {"constraint_id": constraint_id.split(":", 1)[0], "penalty": constraint_penalty(parameters, constraint_id.split(":", 1)[0]), "entity": bays[bay_index]["master_bay_id"]}
                        for (constraint_id, indexed_trip, indexed_bay), variable in violation_vars.items()
                        if indexed_trip == trip_index
                        and solver.value(variable)
                        and (indexed_bay in {None, bay_index} or constraint_id == "bay_no_overlap")
                    ],
                }
            )
        served_indexes = {row["trip_index"] for row in assignments}
        dropped = [index for index in range(len(trips)) if index not in served_indexes]
        dropped_reasons = {
            index: ("BAY_PRODUCT_CONSTRAINT" if not eligible_by_trip[index] else "BAY_CONGESTION")
            for index in dropped
        }
        return {
            "solver_status": "PARTIAL" if assignments and dropped else translated_status,
            "assignments": assignments,
            "dropped_trip_indexes": dropped,
            "dropped_trip_reasons": dropped_reasons,
            "engine": "OR_TOOLS_CP_SAT",
            "raw_solver_status": solver.status_name(status),
            "time_limit_seconds": time_limit_seconds,
            "time_limit_reached": False,
            "num_search_workers": worker_count,
            "duration_ms": round(solve_elapsed * 1000),
        }

    def _fallback_schedule(
        self, *, trips: list[dict], bays: list[dict], actual_states: list[dict], initial_queue: list[dict],
        loading_durations: dict[str, int], day_start: datetime, depot_close: datetime, parameters: dict,
    ) -> dict:
        state_by_bay = {row["master_bay_id"]: row for row in actual_states}
        available: dict[str, datetime] = {}
        trip_ready_floor = min((_utc(trip["vehicle_ready_at_depot"]) for trip in trips), default=_utc(day_start))
        for bay in bays:
            state = state_by_bay.get(bay["master_bay_id"])
            queue_rows = [row for row in initial_queue if row["master_bay_id"] == bay["master_bay_id"]]
            queue_effective_floor = min(
                (_utc(row["state_effective_at"]) for row in queue_rows if row.get("state_effective_at")),
                default=trip_ready_floor,
            )
            value = max(trip_ready_floor, queue_effective_floor)
            if state:
                value = max(value, _utc(state["state_effective_at"]) + timedelta(minutes=int(state.get("remaining_loading_minutes") or 0)))
            value += timedelta(minutes=sum(int(row.get("estimated_loading_duration_minutes") or 0) for row in queue_rows))
            available[bay["master_bay_id"]] = value
        assignments, dropped = [], []
        dropped_reasons: dict[int, str] = {}
        for trip_index, trip in sorted(enumerate(trips), key=lambda item: _utc(item[1]["vehicle_ready_at_depot"])):
            products = {str(row.get("product_id") or "UNKNOWN") for row in trip.get("lo_assignments") or []}
            current_bays = {str(row["current_bay_id"]) for row in trip.get("lo_assignments") or [] if row.get("current_bay_id")}
            candidates = []
            structurally_eligible = False
            for bay in bays:
                product_violation = not bay.get("all_products_allowed") and not products.issubset(set(bay.get("allowed_product_ids") or []))
                if product_violation and constraint_is_hard(parameters, "bay_product_compatibility"):
                    continue
                bay_change_violation = bool(current_bays) and bay["master_bay_id"] not in current_bays
                if bay_change_violation and constraint_is_hard(parameters, "bay_change_stability"):
                    continue
                try:
                    duration = self.loading_minutes(trip, loading_durations, loading_mode=str(bay.get("loading_mode") or "SEQUENTIAL"), arms=int(bay.get("number_of_loading_arms") or 1), parameters=parameters)
                except ValueError:
                    continue
                structurally_eligible = True
                ready = _utc(trip["vehicle_ready_at_depot"])
                blocked = available[bay["master_bay_id"]]
                bay_open = _utc(day_start) + timedelta(minutes=int(bay.get("operational_start_minutes") or 0))
                bay_close = _utc(day_start) + timedelta(minutes=int(bay.get("operational_end_minutes") or _minutes_between(day_start, depot_close)))
                if constraint_is_hard(parameters, "bay_actual_queue") or constraint_is_hard(parameters, "bay_no_overlap"):
                    start = max(ready, blocked)
                else:
                    start = ready
                if constraint_is_hard(parameters, "bay_operating_window"):
                    start = max(start, bay_open)
                violations = []
                if product_violation and constraint_is_soft(parameters, "bay_product_compatibility"):
                    violations.append({"constraint_id": "bay_product_compatibility", "penalty": constraint_penalty(parameters, "bay_product_compatibility"), "entity": bay["master_bay_id"]})
                if bay_change_violation and constraint_is_soft(parameters, "bay_change_stability"):
                    violations.append({"constraint_id": "bay_change_stability", "penalty": constraint_penalty(parameters, "bay_change_stability"), "entity": bay["master_bay_id"]})
                if start < blocked and constraint_is_soft(parameters, "bay_actual_queue"):
                    violations.append({"constraint_id": "bay_actual_queue", "penalty": constraint_penalty(parameters, "bay_actual_queue"), "entity": bay["master_bay_id"]})
                if start < blocked and constraint_is_soft(parameters, "bay_no_overlap"):
                    violations.append({"constraint_id": "bay_no_overlap", "penalty": constraint_penalty(parameters, "bay_no_overlap"), "entity": bay["master_bay_id"]})
                if start < bay_open and constraint_is_soft(parameters, "bay_operating_window"):
                    violations.append({"constraint_id": "bay_operating_window", "penalty": constraint_penalty(parameters, "bay_operating_window"), "entity": bay["master_bay_id"]})
                candidate_gate_out = start + timedelta(minutes=duration + int(parameters.get("gate_process_time", 5)))
                if candidate_gate_out > bay_close and constraint_is_hard(parameters, "bay_operating_window"):
                    continue
                if candidate_gate_out > bay_close and constraint_is_soft(parameters, "bay_operating_window"):
                    violations.append({"constraint_id": "bay_operating_window", "penalty": constraint_penalty(parameters, "bay_operating_window"), "entity": bay["master_bay_id"]})
                candidates.append((sum(float(row["penalty"]) for row in violations), start, bay, duration, violations))
            if not candidates:
                dropped.append(trip_index)
                dropped_reasons[trip_index] = "BAY_CONGESTION" if structurally_eligible else "BAY_PRODUCT_CONSTRAINT"
                continue
            _, start, bay, duration, violations = min(candidates, key=lambda row: (row[0], row[1], row[2]["master_bay_id"]))
            finish = start + timedelta(minutes=duration)
            gate_out = finish + timedelta(minutes=int(parameters.get("gate_process_time", 5)))
            if gate_out > _utc(depot_close) and constraint_is_hard(parameters, "depot_operating_window"):
                dropped.append(trip_index)
                dropped_reasons[trip_index] = "BAY_CONGESTION"
                continue
            if gate_out > _utc(depot_close) and constraint_is_soft(parameters, "depot_operating_window"):
                violations.append({"constraint_id": "depot_operating_window", "penalty": constraint_penalty(parameters, "depot_operating_window"), "entity": bay["master_bay_id"]})
            ready = _utc(trip["vehicle_ready_at_depot"])
            if constraint_rule(parameters, "bay_no_overlap").get("enabled", True):
                available[bay["master_bay_id"]] = max(available[bay["master_bay_id"]], finish)
            assignments.append({"trip_index": trip_index, "master_bay_id": bay["master_bay_id"], "vehicle_ready_at_depot": ready, "queue_start": ready, "loading_start": start, "loading_finish": finish, "gate_out": gate_out, "queue_minutes": _minutes_between(ready, start), "loading_minutes": duration, "constraint_violations": violations})
        if dropped and constraint_is_hard(parameters, "serve_loading_order"):
            assignments = []
            dropped = list(range(len(trips)))
            dropped_reasons = {
                index: dropped_reasons.get(index, "BAY_CONGESTION")
                for index in dropped
            }
            solver_status = "INFEASIBLE"
        elif assignments and dropped:
            solver_status = "PARTIAL"
        else:
            solver_status = "FEASIBLE" if assignments else "INFEASIBLE"
        return {
            "solver_status": solver_status,
            "assignments": assignments,
            "dropped_trip_indexes": dropped,
            "dropped_trip_reasons": dropped_reasons,
            "engine": "DETERMINISTIC_FALLBACK",
            "num_search_workers": 0,
            "time_limit_reached": False,
        }


class OptimizationCoordinatorService:
    def __init__(self) -> None:
        self.vrp = VRPOptimizationService()
        self.bay = BayQueueOptimizationService()

    def _schedule_bays(
        self,
        *,
        trips: list[dict],
        bays: list[dict],
        actual_bay_states: list[dict],
        initial_queue: list[dict],
        loading_durations: dict[str, int],
        day_start: datetime,
        depot_close: datetime,
        parameters: dict,
        deadline: float,
    ) -> tuple[dict, int, bool]:
        """Schedule every retained/retried trip together so bay intervals remain global."""
        previous_gateouts: list[datetime] = []
        time_limit_reached = False
        iterations = 0
        result = {
            "solver_status": "FEASIBLE",
            "assignments": [],
            "dropped_trip_indexes": [],
            "dropped_trip_reasons": {},
            "engine": str(parameters.get("bay_scheduler_strategy") or "FIFO_BALANCED"),
        }
        scheduler_strategy = str(parameters.get("bay_scheduler_strategy") or "FIFO_BALANCED").upper()
        turnaround_buffer = timedelta(
            minutes=max(0, int(parameters.get("mt_turnaround_buffer_minutes", 30)))
        )
        # FIFO_BALANCED propagates the actual return of each physical MT to its
        # next trip inside one event-driven pass. CP-SAT retains the legacy
        # iterative route/bay coordination behavior.
        max_iterations = 1 if scheduler_strategy == "FIFO_BALANCED" else int(parameters.get("max_coordination_iterations", 5))
        for iterations in range(1, max_iterations + 1):
            remaining_budget = deadline - perf_counter()
            if remaining_budget <= 0:
                time_limit_reached = True
                break
            remaining_seconds = max(1, math.ceil(remaining_budget))
            remaining_iterations = max(1, max_iterations - iterations + 1)
            iteration_time_limit = max(1, remaining_seconds // remaining_iterations)
            last_return: dict[str, datetime] = {}
            for trip in sorted(trips, key=lambda row: (row["vehicle_id"], row["trip_number"])):
                if trip["vehicle_id"] in last_return:
                    trip["vehicle_ready_at_depot"] = max(
                        _utc(trip["vehicle_ready_at_depot"]),
                        last_return[trip["vehicle_id"]],
                    )
                last_return[trip["vehicle_id"]] = (
                    _utc(trip["estimated_return_depot"]) + turnaround_buffer
                )
            result = self.bay.schedule(
                trips=trips,
                bays=bays,
                actual_states=actual_bay_states,
                initial_queue=initial_queue,
                loading_durations=loading_durations,
                day_start=day_start,
                depot_close=depot_close,
                parameters={**parameters, "bay_optimization_time_limit": iteration_time_limit},
            )
            assignment_by_trip = {row["trip_index"]: row for row in result["assignments"]}
            current_gateouts: list[datetime] = []
            for trip_index, trip in enumerate(trips):
                schedule = assignment_by_trip.get(trip_index)
                if not schedule:
                    continue
                route_violations = list(trip.get("constraint_violations") or [])
                bay_violations = list(schedule.get("constraint_violations") or [])
                shift = _utc(schedule["gate_out"]) - _utc(trip["gate_out"])
                trip.update({key: value for key, value in schedule.items() if key != "constraint_violations"})
                trip["constraint_violations"] = [*route_violations, *bay_violations]
                trip["constraint_penalty_cost"] = sum(
                    float(row.get("penalty") or 0) for row in trip["constraint_violations"]
                )
                trip["estimated_return_depot"] = _utc(trip["estimated_return_depot"]) + shift
                trip["working_start_at"] = _utc(
                    trip.get("queue_start") or trip.get("loading_start") or trip["vehicle_ready_at_depot"]
                )
                trip["operating_minutes"] = _minutes_between(
                    trip["working_start_at"], trip["estimated_return_depot"]
                )
                current_gateouts.append(_utc(trip["gate_out"]))
            if previous_gateouts and len(previous_gateouts) == len(current_gateouts):
                delta = max(
                    (
                        abs((current - previous).total_seconds()) / 60
                        for current, previous in zip(current_gateouts, previous_gateouts, strict=True)
                    ),
                    default=0,
                )
                if delta <= float(parameters.get("departure_time_tolerance_minutes", 5)):
                    break
            previous_gateouts = current_gateouts
            if result["solver_status"] in {"TIMEOUT", "UNKNOWN", "FAILED", "INFEASIBLE"}:
                time_limit_reached = result["solver_status"] == "TIMEOUT"
                break
        return result, iterations, time_limit_reached

    @staticmethod
    def _post_bay_failures(
        *,
        trips: list[dict],
        bay_result: dict,
        vehicles: list[dict],
        parameters: dict,
        day_start: datetime,
    ) -> tuple[set[int], dict[int, tuple[str, str]], set[int]]:
        """Apply hard checks after authoritative bay shifts and identify retryable trips."""
        dropped = set(bay_result.get("dropped_trip_indexes") or [])
        bay_drop_reason_codes = {
            int(index): reason
            for index, reason in (bay_result.get("dropped_trip_reasons") or {}).items()
        }
        reason_descriptions = {
            "BAY_PRODUCT_CONSTRAINT": "No eligible loading bay satisfies the active hard product, loading-duration, or bay-stability constraints.",
            "BAY_CONGESTION": "The bay scheduler omitted this otherwise eligible trip because available bay capacity/time was insufficient relative to the Serve Loading Order penalty.",
            "BAY_WINDOW_EXHAUSTED": "Every compatible FIFO bay would gate this trip out after the active bay or depot operating window.",
        }
        reasons = {
            index: (
                bay_drop_reason_codes.get(index, "BAY_CONGESTION"),
                reason_descriptions[bay_drop_reason_codes.get(index, "BAY_CONGESTION")],
            )
            for index in dropped
        }
        retryable_failures: set[int] = {
            index
            for index, reason_code in bay_drop_reason_codes.items()
            if reason_code in {"BAY_WINDOW_EXHAUSTED", "BAY_CONGESTION", "BAY_PRODUCT_CONSTRAINT"}
        }
        tolerance = int(parameters.get("departure_time_tolerance_minutes", 5))
        working_limit = {row["mt_id"]: int(row["working_time_limit_minutes"]) for row in vehicles}
        cumulative_working = {row["mt_id"]: int(row.get("working_time_used_minutes") or 0) for row in vehicles}
        ordered_indexes = sorted(
            range(len(trips)),
            key=lambda index: (trips[index]["vehicle_id"], int(trips[index]["trip_number"])),
        )
        for trip_index in ordered_indexes:
            trip = trips[trip_index]
            if trip_index in dropped:
                continue
            vehicle_id = trip["vehicle_id"]
            projected = cumulative_working.get(vehicle_id, 0) + int(trip["operating_minutes"])
            if projected > working_limit.get(vehicle_id, 0):
                if constraint_is_hard(parameters, "vehicle_working_time"):
                    dropped.add(trip_index)
                    retryable_failures.add(trip_index)
                    reasons[trip_index] = (
                        "VEHICLE_TIME_EXHAUSTED",
                        "The assigned MT exceeded its hard working-time limit after bay scheduling; alternative compatible MT will be attempted before final drop.",
                    )
                    continue
                if constraint_is_soft(parameters, "vehicle_working_time") and not any(
                    row.get("constraint_id") == "vehicle_working_time"
                    for row in trip.get("constraint_violations") or []
                ):
                    trip.setdefault("constraint_violations", []).append({
                        "constraint_id": "vehicle_working_time",
                        "penalty": constraint_penalty(parameters, "vehicle_working_time"),
                        "entity": vehicle_id,
                    })
            cumulative_working[vehicle_id] = projected
            previous_gateouts = [
                int(lo["current_planned_gate_out_minutes"])
                for lo in trip.get("lo_assignments") or []
                if lo.get("current_planned_gate_out_minutes") is not None
            ]
            trip["constraint_penalty_cost"] = sum(
                float(row.get("penalty") or 0) for row in trip.get("constraint_violations") or []
            )
            if not previous_gateouts:
                continue
            new_gateout = _minutes_between(day_start, trip["gate_out"])
            if all(abs(new_gateout - previous) <= tolerance for previous in previous_gateouts):
                continue
            if constraint_is_hard(parameters, "gateout_stability"):
                dropped.add(trip_index)
                reasons[trip_index] = (
                    "NO_FEASIBLE_ROUTE",
                    "Trip would violate the active hard gate-out stability constraint.",
                )
            elif constraint_is_soft(parameters, "gateout_stability"):
                trip.setdefault("constraint_violations", []).append({
                    "constraint_id": "gateout_stability",
                    "penalty": constraint_penalty(parameters, "gateout_stability"),
                    "entity": vehicle_id,
                })
            if constraint_is_soft(parameters, "freeze_window") and any(
                lo.get("freeze_window_candidate") for lo in trip.get("lo_assignments") or []
            ):
                trip.setdefault("constraint_violations", []).append({
                    "constraint_id": "freeze_window",
                    "penalty": constraint_penalty(parameters, "freeze_window"),
                    "entity": vehicle_id,
                })
            trip["constraint_penalty_cost"] = sum(
                float(row.get("penalty") or 0) for row in trip.get("constraint_violations") or []
            )
        return dropped, reasons, retryable_failures

    @staticmethod
    def _vehicles_after_retained_trips(vehicles: list[dict], trips: list[dict]) -> list[dict]:
        """Build retry availability/working state from trips that survived post-bay checks."""
        by_vehicle: dict[str, list[dict]] = defaultdict(list)
        for trip in trips:
            by_vehicle[trip["vehicle_id"]].append(trip)
        retry_vehicles: list[dict] = []
        for source in vehicles:
            vehicle = dict(source)
            retained = sorted(by_vehicle.get(vehicle["mt_id"], []), key=lambda row: int(row["trip_number"]))
            used = int(source.get("working_time_used_minutes") or 0) + sum(
                int(trip.get("operating_minutes") or 0) for trip in retained
            )
            limit = int(source.get("working_time_limit_minutes") or 0)
            vehicle["working_time_used_minutes"] = used
            vehicle["working_time_remaining_minutes"] = max(0, limit - used)
            vehicle["completed_trip_count"] = max(
                [int(source.get("completed_trip_count") or 0), *[int(trip["trip_number"]) for trip in retained]],
            )
            if retained:
                latest_return = max(_utc(trip["estimated_return_depot"]) for trip in retained)
                vehicle["availability_eta_depot"] = latest_return
                vehicle["effective_eta_depot"] = latest_return
            retry_vehicles.append(vehicle)
        return retry_vehicles

    @staticmethod
    def _retry_matrix(
        loading_orders: list[dict],
        retry_orders: list[dict],
        distance_matrix: list[list[int]],
        time_matrix: list[list[int]],
    ) -> tuple[list[list[int]], list[list[int]]]:
        original_index = {
            str(row["loading_order_id"]): index
            for index, row in enumerate(loading_orders, start=1)
        }
        indexes = [0, *[original_index[str(row["loading_order_id"])] for row in retry_orders]]
        return (
            [[distance_matrix[source][target] for target in indexes] for source in indexes],
            [[time_matrix[source][target] for target in indexes] for source in indexes],
        )

    def optimize(
        self,
        *,
        loading_orders: list[dict],
        vehicles: list[dict],
        distance_matrix: list[list[int]],
        time_matrix: list[list[int]],
        bays: list[dict],
        actual_bay_states: list[dict],
        initial_queue: list[dict],
        loading_durations: dict[str, int],
        day_start: datetime,
        depot_close: datetime,
        parameters: dict,
    ) -> dict:
        vrp_result = self.vrp.solve(
            loading_orders=loading_orders,
            vehicles=vehicles,
            distance_matrix=distance_matrix,
            time_matrix=time_matrix,
            day_start=day_start,
            depot_close=depot_close,
            parameters=parameters,
        )
        coordination_started = perf_counter()
        coordination_time_limit = max(1, int(parameters.get("bay_optimization_time_limit", parameters.get("optimization_time_limit", 30))))
        coordination_deadline = coordination_started + coordination_time_limit
        coordination_time_limit_reached = False
        trips = vrp_result["trips"]
        bay_result, iterations, coordination_time_limit_reached = self._schedule_bays(
            trips=trips,
            bays=bays,
            actual_bay_states=actual_bay_states,
            initial_queue=initial_queue,
            loading_durations=loading_durations,
            day_start=day_start,
            depot_close=depot_close,
            parameters=parameters,
            deadline=coordination_deadline,
        )
        bay_time_used_seconds = perf_counter() - coordination_started
        total_coordination_iterations = iterations

        terminal_bay_status = bay_result.get("solver_status") if bay_result.get("solver_status") in {"TIMEOUT", "UNKNOWN", "FAILED"} else None
        terminal_solver_status = terminal_bay_status or (
            vrp_result.get("solver_status")
            if vrp_result.get("solver_status") in {"TIMEOUT", "UNKNOWN", "FAILED"}
            else None
        )
        if terminal_bay_status and not bay_result.get("assignments"):
            bay_result["dropped_trip_indexes"] = list(range(len(trips)))
            bay_result["dropped_trip_reasons"] = {
                index: "BAY_CONGESTION" for index in range(len(trips))
            }
        bay_dropped, hard_drop_reasons, retryable_failures = self._post_bay_failures(
            trips=trips,
            bay_result=bay_result,
            vehicles=vehicles,
            parameters=parameters,
            day_start=day_start,
        )
        dropped_by_lo = {
            str(row["loading_order_id"]): dict(row)
            for row in vrp_result.get("dropped") or []
        }
        failed_vehicle_ids_by_lo: dict[str, set[str]] = defaultdict(set)
        post_bay_reassignment_attempts = 0
        post_bay_reassigned_lo_ids: set[str] = set()
        post_bay_reassignment_exhausted_lo_ids: set[str] = set()
        post_bay_reassignment_timeout_lo_ids: set[str] = set()
        post_bay_final_drop_groups: set[tuple[str, ...]] = set()
        post_bay_route_statuses: list[str] = []
        post_bay_candidate_audit: list[dict] = []
        post_bay_split_group_count = 0
        route_retry_time_limit = max(
            1,
            int(parameters.get("route_optimization_time_limit", parameters.get("optimization_time_limit", 30))),
        )
        route_retry_time_used_seconds = 0.0

        def record_post_bay_drop(lo: dict, *, reason_code: str, reason_description: str) -> None:
            loading_order_id = str(lo["loading_order_id"])
            cleaned = {key: value for key, value in lo.items() if key != "compartment_id"}
            dropped_by_lo[loading_order_id] = {
                **cleaned,
                "reason_code": reason_code,
                "reason_description": reason_description,
            }

        # A route remains preliminary until FIFO bay scheduling validates it.
        # Return every retryable post-bay failure to an isolated physical-trip
        # repair queue. Each group is tested against one compatible MT at a
        # time, then globally re-scheduled with retained trips. This prevents
        # one infeasible retry group from forcing all other retry LO to drop.
        pending_groups: list[dict] = []
        retained_trips: list[dict] = []
        for trip_index, trip in enumerate(trips):
            if trip_index not in bay_dropped:
                retained_trips.append(trip)
                continue
            reason_code, reason_description = hard_drop_reasons.get(
                trip_index,
                ("NO_FEASIBLE_ROUTE", "Trip violates an active hard post-bay constraint."),
            )
            orders = [
                {key: value for key, value in assignment.items() if key != "compartment_id"}
                for assignment in trip.get("lo_assignments") or []
            ]
            if trip_index in retryable_failures and orders:
                for order in orders:
                    failed_vehicle_ids_by_lo[str(order["loading_order_id"])].add(str(trip["vehicle_id"]))
                pending_groups.append({
                    "orders": orders,
                    "original_reason_code": reason_code,
                    "original_reason_description": reason_description,
                    "failed_vehicle_id": str(trip["vehicle_id"]),
                })
                continue
            group_ids = tuple(sorted(str(order["loading_order_id"]) for order in orders))
            if group_ids:
                post_bay_final_drop_groups.add(group_ids)
            for order in orders:
                record_post_bay_drop(order, reason_code=reason_code, reason_description=reason_description)
        trips = retained_trips
        bay_dropped = set()
        hard_drop_reasons = {}
        retryable_failures = set()

        while pending_groups:
            pending = pending_groups.pop(0)
            retry_orders = list(pending["orders"])
            group_ids = tuple(sorted(str(order["loading_order_id"]) for order in retry_orders))
            split_blocked = (
                (
                    constraint_is_hard(parameters, "phase6_shipment_preference")
                    and any(order.get("phase6_predicted_shipment_id") for order in retry_orders)
                )
                or (
                    constraint_is_hard(parameters, "previous_shipment_stability")
                    and any(order.get("current_shipment_id") for order in retry_orders)
                )
                or (
                    constraint_is_hard(parameters, "freeze_window")
                    and any(order.get("freeze_window_candidate") for order in retry_orders)
                )
            )
            retry_vehicles = self._vehicles_after_retained_trips(vehicles, trips)
            retry_vehicle_by_id = {str(row["mt_id"]): row for row in retry_vehicles}
            allowed_sets = [
                {
                    str(mt_id)
                    for mt_id in order.get("allowed_vehicle_ids") or []
                    if str(mt_id) not in failed_vehicle_ids_by_lo[str(order["loading_order_id"])]
                }
                for order in retry_orders
            ]
            candidate_ids = set.intersection(*allowed_sets) if allowed_sets else set()
            candidate_ids &= set(retry_vehicle_by_id)
            candidate_rows = [retry_vehicle_by_id[mt_id] for mt_id in candidate_ids]
            candidate_rows.sort(key=lambda row: (
                1 if int(row.get("working_time_used_minutes") or 0) > 0 or int(row.get("completed_trip_count") or 0) > 0 else 0,
                _utc(row.get("effective_eta_depot") or row.get("availability_eta_depot") or day_start),
                -int(row.get("working_time_remaining_minutes") or 0),
                str(row["mt_id"]),
            ))
            group_candidate_reasons: list[str] = []
            group_timed_out = False
            accepted = False

            for candidate in candidate_rows:
                candidate_id = str(candidate["mt_id"])
                audit = {
                    "loading_order_ids": list(group_ids),
                    "candidate_mt_id": candidate_id,
                    "available_at": _utc(candidate.get("effective_eta_depot") or candidate.get("availability_eta_depot") or day_start).isoformat(),
                    "working_time_remaining_minutes": int(candidate.get("working_time_remaining_minutes") or 0),
                    "status": "REJECTED",
                    "reason_code": None,
                }
                if (
                    constraint_is_hard(parameters, "vehicle_capacity")
                    and candidate.get("capacity_kl") is not None
                    and sum(float(order["volume_kl"]) for order in retry_orders) > float(candidate["capacity_kl"]) + 1e-9
                ):
                    audit["reason_code"] = "INSUFFICIENT_CAPACITY"
                    group_candidate_reasons.append("INSUFFICIENT_CAPACITY")
                    post_bay_candidate_audit.append(audit)
                    continue
                if (
                    constraint_is_hard(parameters, "vehicle_working_time")
                    and int(candidate.get("working_time_remaining_minutes") or 0) <= 0
                ):
                    audit["reason_code"] = "VEHICLE_TIME_EXHAUSTED"
                    group_candidate_reasons.append("VEHICLE_TIME_EXHAUSTED")
                    post_bay_candidate_audit.append(audit)
                    continue

                remaining_route_retry_seconds = route_retry_time_limit - route_retry_time_used_seconds
                remaining_bay_seconds = coordination_time_limit - bay_time_used_seconds
                if remaining_route_retry_seconds <= 0 or remaining_bay_seconds <= 0:
                    group_timed_out = True
                    coordination_time_limit_reached = coordination_time_limit_reached or remaining_bay_seconds <= 0
                    audit["reason_code"] = "POST_BAY_REASSIGNMENT_TIMEOUT"
                    post_bay_candidate_audit.append(audit)
                    break

                candidate_orders = [
                    {**order, "allowed_vehicle_ids": [candidate_id]}
                    for order in retry_orders
                ]
                retry_distance_matrix, retry_time_matrix = self._retry_matrix(
                    loading_orders,
                    candidate_orders,
                    distance_matrix,
                    time_matrix,
                )
                retry_constraint_rules = {
                    key: dict(value)
                    for key, value in (parameters.get("constraint_rules") or {}).items()
                }
                retry_constraint_rules["serve_loading_order"] = {
                    **retry_constraint_rules.get("serve_loading_order", {}),
                    "enabled": True,
                    "mode": "HARD",
                }
                candidate_time_limit = max(1, min(5, math.ceil(remaining_route_retry_seconds)))
                retry_parameters = {
                    **parameters,
                    "constraint_rules": retry_constraint_rules,
                    "maximum_trips_per_mt": 1,
                    "route_optimization_time_limit": candidate_time_limit,
                }
                route_retry_started = perf_counter()
                retry_result = self.vrp.solve(
                    loading_orders=candidate_orders,
                    vehicles=[candidate],
                    distance_matrix=retry_distance_matrix,
                    time_matrix=retry_time_matrix,
                    day_start=day_start,
                    depot_close=depot_close,
                    parameters=retry_parameters,
                )
                route_retry_time_used_seconds += perf_counter() - route_retry_started
                post_bay_reassignment_attempts += 1
                retry_status = str(retry_result.get("solver_status") or "UNKNOWN")
                post_bay_route_statuses.append(retry_status)
                retry_trips = list(retry_result.get("trips") or [])
                reassigned_ids = {
                    str(order["loading_order_id"])
                    for retry_trip in retry_trips
                    for order in retry_trip.get("lo_assignments") or []
                }
                if retry_status in {"TIMEOUT", "UNKNOWN", "FAILED"}:
                    group_timed_out = True
                    audit["reason_code"] = "POST_BAY_REASSIGNMENT_TIMEOUT"
                    post_bay_candidate_audit.append(audit)
                    continue
                if reassigned_ids != set(group_ids):
                    reason_code = str((retry_result.get("dropped") or [{}])[0].get("reason_code") or "NO_FEASIBLE_ROUTE")
                    audit["reason_code"] = reason_code
                    group_candidate_reasons.append(reason_code)
                    post_bay_candidate_audit.append(audit)
                    continue

                trial_trips = copy.deepcopy([*trips, *retry_trips])
                bay_eval_rules = {
                    key: dict(value)
                    for key, value in (parameters.get("constraint_rules") or {}).items()
                }
                bay_eval_rules["serve_loading_order"] = {
                    **bay_eval_rules.get("serve_loading_order", {}),
                    "enabled": True,
                    "mode": "SOFT",
                }
                bay_eval_parameters = {**parameters, "constraint_rules": bay_eval_rules}
                bay_retry_started = perf_counter()
                trial_bay_result, retry_iterations, retry_bay_time_limit_reached = self._schedule_bays(
                    trips=trial_trips,
                    bays=bays,
                    actual_bay_states=actual_bay_states,
                    initial_queue=initial_queue,
                    loading_durations=loading_durations,
                    day_start=day_start,
                    depot_close=depot_close,
                    parameters=bay_eval_parameters,
                    deadline=bay_retry_started + remaining_bay_seconds,
                )
                bay_time_used_seconds += perf_counter() - bay_retry_started
                total_coordination_iterations += retry_iterations
                coordination_time_limit_reached = coordination_time_limit_reached or retry_bay_time_limit_reached
                trial_dropped, trial_reasons, _ = self._post_bay_failures(
                    trips=trial_trips,
                    bay_result=trial_bay_result,
                    vehicles=vehicles,
                    parameters=bay_eval_parameters,
                    day_start=day_start,
                )
                if trial_bay_result.get("solver_status") in {"TIMEOUT", "UNKNOWN", "FAILED"}:
                    group_timed_out = True
                    audit["reason_code"] = "POST_BAY_REASSIGNMENT_TIMEOUT"
                    post_bay_candidate_audit.append(audit)
                    continue
                if trial_dropped:
                    candidate_start_index = len(trips)
                    candidate_failures = [index for index in trial_dropped if index >= candidate_start_index]
                    if candidate_failures:
                        reason_code = trial_reasons.get(candidate_failures[0], ("NO_FEASIBLE_ROUTE", ""))[0]
                    else:
                        reason_code = "BAY_CONGESTION"
                    audit["reason_code"] = reason_code
                    group_candidate_reasons.append(reason_code)
                    post_bay_candidate_audit.append(audit)
                    continue

                trips = trial_trips
                bay_result = trial_bay_result
                vrp_result["objective_value"] = float(vrp_result.get("objective_value") or 0) + float(
                    retry_result.get("objective_value") or 0
                )
                post_bay_reassigned_lo_ids.update(reassigned_ids)
                for loading_order_id in reassigned_ids:
                    dropped_by_lo.pop(loading_order_id, None)
                audit["status"] = "ACCEPTED"
                audit["reason_code"] = "REASSIGNED"
                post_bay_candidate_audit.append(audit)
                accepted = True
                break

            if accepted:
                continue
            if len(retry_orders) > 1 and not split_blocked:
                post_bay_split_group_count += 1
                pending_groups[0:0] = [
                    {
                        "orders": [order],
                        "original_reason_code": pending["original_reason_code"],
                        "original_reason_description": pending["original_reason_description"],
                        "failed_vehicle_id": pending["failed_vehicle_id"],
                    }
                    for order in retry_orders
                ]
                continue

            if group_timed_out:
                final_reason_code = "POST_BAY_REASSIGNMENT_TIMEOUT"
                final_description = (
                    "Post-bay repair exhausted its route or bay budget before every compatible MT candidate "
                    "could be proven infeasible. Review the candidate audit and increase Route Time Limit."
                )
                terminal_solver_status = terminal_solver_status or "TIMEOUT"
                post_bay_reassignment_timeout_lo_ids.update(group_ids)
            elif group_candidate_reasons and all(reason == "VEHICLE_TIME_EXHAUSTED" for reason in group_candidate_reasons):
                final_reason_code = "VEHICLE_TIME_EXHAUSTED"
                final_description = "Every compatible alternative MT failed its actual retained working-time limit after FIFO bay scheduling."
                post_bay_reassignment_exhausted_lo_ids.update(group_ids)
            elif "BAY_WINDOW_EXHAUSTED" in group_candidate_reasons:
                final_reason_code = "BAY_WINDOW_EXHAUSTED"
                final_description = "Every compatible alternative MT was tested, but each FIFO loading/gate-out exceeded an active bay or depot window."
                post_bay_reassignment_exhausted_lo_ids.update(group_ids)
            elif "BAY_PRODUCT_CONSTRAINT" in group_candidate_reasons:
                final_reason_code = "BAY_PRODUCT_CONSTRAINT"
                final_description = "Every compatible alternative MT was tested, but no eligible bay could load this LO product composition."
                post_bay_reassignment_exhausted_lo_ids.update(group_ids)
            else:
                final_reason_code = str(pending["original_reason_code"] or "NO_FEASIBLE_ROUTE")
                final_description = (
                    f"All {len(candidate_rows)} remaining compatible MT candidates were evaluated individually "
                    "against retained working time, route, compartment, and global FIFO bay scheduling; none was feasible."
                )
                post_bay_reassignment_exhausted_lo_ids.update(group_ids)
            post_bay_final_drop_groups.add(group_ids)
            for order in retry_orders:
                record_post_bay_drop(
                    order,
                    reason_code=final_reason_code,
                    reason_description=final_description,
                )

        if bay_dropped:
            kept, extra_dropped = [], []
            for index, trip in enumerate(trips):
                if index not in bay_dropped:
                    kept.append(trip)
                    continue
                reason_code, reason_description = hard_drop_reasons.get(index, ("NO_FEASIBLE_ROUTE", "Trip violates an active hard constraint."))
                group_ids = tuple(sorted(str(lo["loading_order_id"]) for lo in trip.get("lo_assignments") or []))
                if group_ids:
                    post_bay_final_drop_groups.add(group_ids)
                for lo in trip.get("lo_assignments") or []:
                    extra_dropped.append({**lo, "reason_code": reason_code, "reason_description": reason_description})
            trips = kept
            for lo in extra_dropped:
                record_post_bay_drop(
                    lo,
                    reason_code=lo["reason_code"],
                    reason_description=lo["reason_description"],
                )
        vrp_result["dropped"] = list(dropped_by_lo.values())
        if trips and vrp_result["dropped"]:
            solver_status = "PARTIAL"
        elif trips:
            solver_status = "FEASIBLE"
        elif terminal_solver_status:
            solver_status = terminal_solver_status
        else:
            solver_status = "INFEASIBLE"
        final_violation_count = sum(len(trip.get("constraint_violations") or []) for trip in trips)
        final_constraint_penalty = sum(float(trip.get("constraint_penalty_cost") or 0) for trip in trips)
        return {
            **vrp_result,
            "trips": trips,
            "solver_status": solver_status,
            "coordination_iterations": total_coordination_iterations,
            "solver_metadata": {
                **vrp_result["solver_metadata"],
                "bay_engine": bay_result["engine"],
                "bay_scheduler_strategy": str(parameters.get("bay_scheduler_strategy") or "FIFO_BALANCED"),
                "bay_scheduler_metadata": bay_result.get("scheduler_metadata") or {},
                "bay_solver_status": bay_result["solver_status"],
                "bay_raw_solver_status": bay_result.get("raw_solver_status"),
                "bay_time_limit_seconds": coordination_time_limit,
                "bay_time_limit_reached": bool(bay_result.get("time_limit_reached") or coordination_time_limit_reached),
                "bay_cp_sat_workers": bay_result.get("num_search_workers", parameters.get("bay_cp_sat_workers", 8)),
                "bay_served_trip_count": len(trips),
                "bay_dropped_trip_count": len(post_bay_final_drop_groups),
                "coordination_time_limit_reached": coordination_time_limit_reached,
                "coordination_duration_ms": round((perf_counter() - coordination_started) * 1000),
                "post_bay_reassignment_attempts": post_bay_reassignment_attempts,
                "post_bay_reassigned_lo_count": len(post_bay_reassigned_lo_ids - set(dropped_by_lo)),
                "post_bay_reassignment_exhausted_lo_count": len(post_bay_reassignment_exhausted_lo_ids),
                "post_bay_reassignment_timeout_lo_count": len(post_bay_reassignment_timeout_lo_ids),
                "post_bay_reassignment_route_statuses": post_bay_route_statuses,
                "post_bay_route_time_limit_seconds": route_retry_time_limit,
                "post_bay_route_time_used_ms": round(route_retry_time_used_seconds * 1000),
                "post_bay_split_group_count": post_bay_split_group_count,
                "post_bay_candidate_evaluation_count": len(post_bay_candidate_audit),
                "post_bay_candidate_audit": post_bay_candidate_audit,
                "vehicle_working_time_start_basis": "SYSTEM_PLANNED_QUEUE_ENTRY",
                "constraint_violation_count": final_violation_count,
                "constraint_penalty_cost": final_constraint_penalty,
            },
        }
