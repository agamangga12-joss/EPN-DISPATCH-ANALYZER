# Agreed SPBU administration and discharge timing

Status: implemented in Phase 7 algorithm v15. Existing immutable route versions retain their original timing.

- SPBU Service Time means administration time per SPBU visit (example: 30 minutes).
- Discharge Time is a separate configurable duration per compartment unloaded at that SPBU (example/default proposed: 15 minutes).
- Compartment discharge is sequential, never parallel within one MT.
- Count compartments actually unloaded at the stop from compartment assignments, not all vehicle compartments or the LO count by assumption.
- Administration and discharge are sequential and both occupy an SPBU service slot.
- Stop duration excluding queue = administration + unloaded compartment count * discharge time per compartment.
- Service starts at the later of vehicle arrival and service-slot availability. Queue time is service start minus arrival.
- Example with one slot: MT A arrives 08:00 with 2 compartments, administration 08:00-08:30, discharge 08:30-09:00, leaves 09:00. MT B arrives 08:20 with 1 compartment, queues 40 minutes, administration 09:00-09:30, discharge 09:30-09:45, leaves 09:45.
- With multiple service slots, separate MT may be served concurrently up to SPBU capacity; discharge within each MT remains sequential.
- Updated stop durations must propagate to routing, SPBU queue/capacity scheduling, receiving-window checks, next-stop ETA, depot return, MT working time, and subsequent trips.


## Implemented parameters and audit

- `default_spbu_service_minutes`: administration minutes per visit; default 30.
- `discharge_minutes_per_compartment`: sequential discharge minutes per distinct compartment unloaded at that stop; default 15; configurable 0-1440.
- Trip timing records total administration/discharge seconds and per-stop component/count details. Total service time includes both; queue remains separate.
- Canonical Phase 6 LO has one 8 KL compartment. Routing uses per-LO discharge as a preliminary time estimate; authoritative physical stop timing uses actual compartment assignment, deduplicated per stop.
- Receiving-window entry is checked once for a physical visit; sequential discharge of another LO at that SPBU does not create a new visit.

## SPBU Pairing Distance

`constraint_rules.spbu_pairing_distance` exposes `enabled`, `mode`, `limit_km`, and `penalty`. Default: SOFT, 20 km, 1000 objective points per excess km. The limit is user-configurable, positive and at most 20000 km; decimal km are supported.

For every unique unordered SPBU pair in a physical trip, use the larger of the two directional road distances in the route matrix. This conservative choice handles one-way roads. Depot legs and repeated LO at the same SPBU do not add pairs. All pairs are examined, including non-adjacent stops such as A-C in A-B-C.

HARD forbids co-assignment to a trip for every pair above the limit. SOFT contributes `round(max(0, pair_distance_km - limit_km) * penalty)` per unique pair. DISABLED ignores distance. These solver penalties are included in normal constraint violation reporting; historical pairing remains a separate rule. A per-vehicle Routing dimension prices the sum of unique pair penalties during search, and final physical trip validation/audit uses the same distance and rounding policy.

No database migration is required: parameters are stored in existing JSON profiles/snapshots. New solves merge the new defaults; existing route versions are not recalculated automatically.
