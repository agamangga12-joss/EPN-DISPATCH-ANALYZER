# Restricted roads with Google Routes and operator detour waypoints

Phase 7 keeps OR-Tools for MT assignment, SPBU sequence, multi-trip coordination
and bay scheduling. Google Routes supplies the road paths, distance and duration.
GraphHopper and `.osm.pbf` are no longer required. Restricted roads are entered
manually and scoped to each depot, including travel between SPBU locations.

## Operator workflow

1. Open **Data Foundation ? Restricted Roads**, or its link in Master Data.
2. Enter a road name, reason and two reference coordinates: start and end of the
   forbidden street. The coordinate editor uses `latitude, longitude` per line;
   the API stores GeoJSON `[longitude, latitude]` arrays.
3. Select **Preview ruas jalan** to obtain the actual road shape from Google.
   Add reference points if needed to identify a curved street or a branch.
   Alternatively draw the confirmed shape manually with sufficient points.
   Two reference coordinates must not be assumed to define a straight road.
4. Inspect the red corridor and its width. A wide corridor can cover parallel
   roads, junctions and flyovers. Restrictions are geometric, not elevation-aware.
5. Choose **BOTH**, **FORWARD** (start ? end), or **REVERSE** (end ? start).
6. Enter one or more ordered detour waypoints for each applicable direction.
   Forward and reverse lists are separate. The optional copy/reverse button is
   an explicit operator choice; review one-way streets before confirming it.
   Each direction permits at most 25 waypoints. Click the map after selecting
   the appropriate input target to append points. Green and orange points show
   the two detour orders; connecting lines are guides, not computed road routes.
7. Optionally enter validity timestamps with timezone offsets. Empty timestamps
   mean no date boundary. Review the road shape and detours, confirm, and save.
8. Run Initial Optimization or Re-Optimize to apply changes to a new version.
   Existing versions retain their original geometry, metrics and rule snapshots.

The existing conservative temporal policy remains: restrictions active at any
point during the next 48 hours from the optimization reference apply throughout
that plan. Plans extending beyond that horizon are rejected. All MT in the depot
share these rules; per-vehicle-class road restrictions are not implemented.

## Road calculation before OR-Tools

For each directed unique depot/SPBU pair:

1. Request a normal high-quality road route using Google `ComputeRoutes`.
2. Check its geometry, including access from the requested endpoints, against
   every applicable restriction. Direction is inferred from movement along the
   local road segment. Ambiguous perpendicular crossings are conservative.
3. If the path is safe, retain its distance, duration and exact geometry.
4. Otherwise insert the stored detour waypoints for the violated direction as
   ordered `via: true` intermediate points. They are pass-through locations and
   never become additional SPBU stops, service operations or LO assignments.
5. Request a new route and check it against **all** rules again. A new bypass may
   encounter another restricted street; its points can be inserted between
   existing bypass points while retaining the stored relative order.
6. Stop after at most eight logical Google calls per pair. The complete request
   may contain no more than 25 intermediate waypoints. Cycles and repeated
   violations require operator review.

No `ComputeRouteMatrix` result is used as evidence of restricted-road compliance:
that endpoint does not supply the full road geometry needed for this check.
Duplicate LO destinations reuse the same directed pair. Verified results are
cached by restriction checksum (including direction and waypoint lists), Google
configuration version, endpoints, coordinates and departure-time bucket.

The geometry checker uses an immutable bounding-box tree over the full restricted
road segments. Each complete route-segment bounding box selects candidates, then
the original precise polygon/direction tests run on those candidates. Road and
route polylines are not simplified to gain speed; sparse crossings remain checked.

Uncached pairs are processed by a bounded pool, with all SQL/cache writes kept on
the coordinator thread. The parameter profile exposes
`restricted_matrix_workers` (default 4, range 1–16) and
`restricted_matrix_time_limit_seconds` (default 900, range 1–3,600). This dedicated
limit replaces the general 90-second matrix limit only for restricted-road builds;
the OR-Tools route-search time limit remains a separate setting. The existing
Google request budget is shared atomically across workers and detour retries.
Completed verified pairs are checkpointed, including when another pair fails;
progress heartbeats expose completed/active pairs, elapsed time and geometry-check
time. A timed-out build stops scheduling new pairs and drains its bounded in-flight
requests before reporting failure.

OR-Tools consumes the selected verified distances and travel times. Final trip
geometry concatenates those exact matrix paths rather than recomputing a new
Google route that could select another street. Detour evidence is copied into
trip cost/audit metadata; parameter snapshots retain complete restriction facts.
Lazy map hydration does not replace these paths. Old GraphHopper versions remain
readable as historical evidence but are never used to build new Google matrices.

## Failure handling and Google configuration

Configure a valid API key through **Google Maps Integration** and enable the
Google Routes API. No local routing service, Java heap or downloaded map is
needed. `install.cmd` installs the application without downloading OSM data.
A new installation can be opened before the API key is entered; optimization
with active restrictions requires that configuration and complete detour lists.
Obsolete `RESTRICTED_ROUTING_*` environment variables are ignored.

- `GOOGLE_ROUTES_REQUIRED`: the Google client/key is not configured or decryptable.
- `RESTRICTED_DETOUR_REQUIRED`: active road records lack required detour points.
- `RESTRICTED_ROUTE_REVIEW_REQUIRED`: configured Google waypoint candidates did
  not yield a permitted route. This does **not** establish that no alternative
  road exists in the real world. The relevant pair is structurally excluded from
  the solver, independently of configurable HARD/SOFT time or capacity rules.
- Provider authentication, billing, quota, timeout and network failures fail the
  calculation with an explicit error, preserving the previous current version.
  No unrestricted Google, OSRM or Haversine fallback is accepted for these pairs.
- The matrix time and Google request budgets bound external work. Detour retries
  count toward the request budget. Increase matrix limits for larger scenarios;
  a budget failure must not be presented as a physically unreachable road.

Traffic-aware requests retain Google travel duration. As in the existing Google
client, historical reference times cannot request past live traffic and omit the
past departure timestamp. Actual `departure_time_sent` is retained in evidence.

Frozen/current trips are preserved. Intersections or unverified old geometry
produce a dispatcher review event. A conflict can lie on an already travelled
part of a frozen trip, so the dispatcher must assess it rather than the system
silently replacing ongoing work.

## Upgrade from the previous design

Migration `0033_restricted_road_waypoints` adds direction and two waypoint lists
without deleting road records or route versions. Existing road records start with
empty detour lists. Complete their waypoints (or deactivate obsolete rules) before
optimizing. The master page identifies active incomplete records.

Old routing data directories and Docker volumes are not deleted by an upgrade.
They are no longer mounted or required. A previously running standalone
GraphHopper container may be stopped; its data need not be removed.

References: [Google intermediate waypoints](https://developers.google.com/maps/documentation/routes/intermed_waypoints),
[Waypoint via semantics](https://developers.google.com/maps/documentation/routes/reference/rest/v2/Waypoint).
