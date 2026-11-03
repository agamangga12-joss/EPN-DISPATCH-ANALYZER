"""Travel policy and per-trip driving clock (never shared across trips)."""
import math

UNREACHABLE = 1_000_000_000


def travel_time_matrix(distances, durations, parameters):
    if parameters.get("travel_time_mode", "AUTO") != "MANUAL_SPEED":
        return durations
    speed = float(parameters["average_speed_kmh"])
    return [[UNREACHABLE if durations[i][j] >= UNREACHABLE else math.ceil(distance * 3.6 / speed)
             for j, distance in enumerate(row)] for i, row in enumerate(distances)]


def trip_clock(legs, service_seconds, parameters, minimum_arrival_offsets=None):
    """legs includes return to depot; offsets are relative to gate-out.

    A break is required before further driving after reaching the interval.
    No break is inserted at the final depot arrival. Service never resets the
    driving clock. Each invocation starts a fresh physical trip.
    """
    interval = max(1, int(parameters.get("driving_break_interval_minutes", 240))) * 60
    break_seconds = max(0, int(parameters.get("driving_break_minutes", 0))) * 60
    fuel_seconds = max(0, int(parameters.get("refueling_minutes", 0))) * 60
    offset, driving, since_break = 0, 0, 0
    events, arrivals, departures = [], [], []
    def event(kind, seconds, leg=None):
        nonlocal offset
        if seconds:
            events.append({"kind": kind, "start_offset_seconds": offset, "end_offset_seconds": offset + seconds, "leg": leg})
            offset += seconds
    event("REFUELING", fuel_seconds)
    for index, duration in enumerate(legs):
        remaining = int(duration)
        while remaining > 0:
            if since_break == interval:
                event("BREAK", break_seconds, index)
                since_break = 0
            step = min(remaining, interval - since_break)
            event("DRIVING", step, index)
            since_break += step
            driving += step
            remaining -= step
        if index < len(legs) - 1:
            if minimum_arrival_offsets:
                event("WAITING", max(0, int(minimum_arrival_offsets[index] or 0) - offset), index)
            arrivals.append(offset)
            duration = service_seconds[index] if isinstance(service_seconds, (list, tuple)) else service_seconds
            event("SERVICE", duration, index)
            departures.append(offset)
    return {"events": events, "arrival_offsets": arrivals, "departure_offsets": departures,
            "total_seconds": offset, "driving_seconds": driving, "refueling_seconds": fuel_seconds,
            "break_seconds": sum(e["end_offset_seconds"] - e["start_offset_seconds"] for e in events if e["kind"] == "BREAK"),
            "travel_time_mode": parameters.get("travel_time_mode", "AUTO"),
            "average_speed_kmh": parameters.get("average_speed_kmh") if parameters.get("travel_time_mode") == "MANUAL_SPEED" else None}


def spbu_stop_service(assignments, parameters):
    """One administration per visit, sequential discharge per distinct assigned compartment."""
    compartments = {str(row["compartment_id"]) for row in assignments if row.get("compartment_id") is not None}
    administration = int(parameters.get("default_spbu_service_minutes", 30)) * 60
    discharge = len(compartments) * int(parameters.get("discharge_minutes_per_compartment", 15)) * 60
    return {"administration_seconds": administration, "discharge_seconds": discharge,
            "unloaded_compartment_count": len(compartments), "service_seconds": administration + discharge}


def pairing_distance_violations(orders, distance_matrix, parameters):
    from .phase7_constants import constraint_rule
    rule = constraint_rule(parameters, "spbu_pairing_distance")
    if not rule.get("enabled", True):
        return []
    nodes = {}
    for order in orders:
        nodes.setdefault(str(order["spbu_id"]), int(order["matrix_node_index"]))
    pairs = []
    ids = sorted(nodes)
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            a, b = nodes[left], nodes[right]
            distance = max(distance_matrix[a][b], distance_matrix[b][a]) / 1000
            excess = max(0.0, distance - float(rule.get("limit_km", 20)))
            if excess:
                pairs.append({"constraint_id": "spbu_pairing_distance", "entity": f"{left}|{right}",
                              "spbu_ids": [left, right], "distance_km": distance, "excess_km": excess,
                              "penalty": round(excess * float(rule["penalty"])) if rule["mode"] == "SOFT" else 0})
    return pairs
