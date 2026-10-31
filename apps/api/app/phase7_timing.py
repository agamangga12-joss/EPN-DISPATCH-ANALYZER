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
            event("SERVICE", service_seconds, index)
            departures.append(offset)
    return {"events": events, "arrival_offsets": arrivals, "departure_offsets": departures,
            "total_seconds": offset, "driving_seconds": driving, "refueling_seconds": fuel_seconds,
            "break_seconds": sum(e["end_offset_seconds"] - e["start_offset_seconds"] for e in events if e["kind"] == "BREAK"),
            "travel_time_mode": parameters.get("travel_time_mode", "AUTO"),
            "average_speed_kmh": parameters.get("average_speed_kmh") if parameters.get("travel_time_mode") == "MANUAL_SPEED" else None}
