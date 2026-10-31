import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.google_routes import GoogleRoutesClient, GoogleRoutesError
from app.restricted_roads import RestrictedRoadRouter, RestrictedRoutingError, UNREACHABLE, geometry_conflicts

ROAD = {"restricted_road_id": "R1", "geometry": [[0, -0.1], [0, 0.1]], "buffer_meters": 12,
        "direction": "BOTH", "forward_waypoints": [[-1, -1], [1, -1]], "reverse_waypoints": [[1, -1], [-1, -1]]}
DIRECT = [[-1, 0], [1, 0]]
DETOUR = [[-1, 0], [-1, -1], [1, -1], [1, 0]]


def response(points, distance=1000, duration=100):
    return {"distance_meters": distance, "duration_seconds": duration,
            "route_geometry": [{"longitude": x, "latitude": y} for x, y in points]}


def client_with_responses(responses):
    calls = []
    def compute_route(**kwargs):
        calls.append(kwargs)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item
    return SimpleNamespace(compute_route=compute_route), calls


def test_normal_route_is_checked_before_detour_and_uses_original_metrics_when_safe():
    client, calls = client_with_responses([response(DETOUR, 1900, 250)])
    result = RestrictedRoadRouter(client=client).route(DIRECT, [ROAD])
    assert len(calls) == 1
    assert calls[0]["intermediates"] is None
    assert result["distance_meters"] == 1900
    assert result["metadata"]["detours"] == []


def test_google_retry_uses_ordered_pass_through_points_and_detour_metrics():
    client, calls = client_with_responses([response(DIRECT), response(DETOUR, 1900, 250)])
    departure = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = RestrictedRoadRouter(client=client).route(DIRECT, [ROAD], departure=departure)
    assert len(calls) == 2
    assert calls[1]["intermediates"] == [(-1, -1), (-1, 1)]  # client takes latitude, longitude
    assert calls[1]["via_intermediates"] and calls[1]["high_quality"]
    assert calls[1]["departure_datetime"] == departure
    assert calls[1]["routing_preference"] == "TRAFFIC_AWARE"
    assert result["distance_meters"] == 1900 and result["duration_seconds"] == 250
    assert result["provider"] == "GOOGLE_RESTRICTED_WAYPOINTS"
    assert result["metadata"]["request_count"] == 2
    assert result["metadata"]["via_waypoints"] == ROAD["forward_waypoints"]


def test_reverse_direction_uses_independent_reverse_waypoint_order():
    road = {**ROAD, "geometry": [[-0.1, 0], [0.1, 0]], "reverse_waypoints": [[0.2, 0.5], [-0.2, 0.5]]}
    client, calls = client_with_responses([response(list(reversed(DIRECT))), response([[1, 0], [1, 1], [-1, 1], [-1, 0]])])
    result = RestrictedRoadRouter(client=client).route(list(reversed(DIRECT)), [road])
    assert calls[1]["intermediates"] == [(0.5, 0.2), (0.5, -0.2)]
    assert result["metadata"]["detours"][0]["direction"] == "REVERSE"


def test_one_direction_restriction_does_not_block_opposite_travel():
    road = {**ROAD, "geometry": [[-0.1, 0], [0.1, 0]], "direction": "FORWARD"}
    client, calls = client_with_responses([response(list(reversed(DIRECT)))])
    result = RestrictedRoadRouter(client=client).route(list(reversed(DIRECT)), [road])
    assert len(calls) == 1
    assert not geometry_conflicts(result["route_geometry"], [road])


def test_detour_is_rechecked_against_other_roads_and_new_waypoints_can_be_inserted_between_old_points():
    road2 = {**ROAD, "restricted_road_id": "R2", "geometry": [[0, -1.1], [0, -0.9]],
             "forward_waypoints": [[-0.1, -1.3], [0.1, -1.3]]}
    final = [[-1, 0], [-1, -1], [-0.1, -1.3], [0.1, -1.3], [1, -1], [1, 0]]
    client, calls = client_with_responses([response(DIRECT), response(DETOUR), response(final, 2500, 350)])
    result = RestrictedRoadRouter(client=client).route(DIRECT, [ROAD, road2])
    assert len(calls) == 3
    assert calls[2]["intermediates"] == [(-1, -1), (-1.3, -0.1), (-1.3, 0.1), (-1, 1)]
    assert result["distance_meters"] == 2500
    assert {g["road_id"] for g in result["metadata"]["detours"]} == {"R1", "R2"}


def test_repeated_violation_requires_review_without_claiming_no_road_exists():
    client, calls = client_with_responses([response(DIRECT)])
    result = RestrictedRoadRouter(client=client).route(DIRECT, [ROAD])
    assert len(calls) == 2
    assert result["duration_seconds"] == UNREACHABLE
    assert result["metadata"]["review_required"] is True
    assert "does not prove" in result["metadata"]["message"]


@pytest.mark.parametrize("code", ["GOOGLE_REQUEST_TIMEOUT", "GOOGLE_CONNECTION_ERROR", "GOOGLE_PERMISSION_DENIED"])
def test_provider_failures_are_not_classified_as_no_route_or_fallback(code):
    client, _ = client_with_responses([GoogleRoutesError(code, "Provider unavailable")])
    with pytest.raises(RestrictedRoutingError) as error:
        RestrictedRoadRouter(client=client).route(DIRECT, [ROAD])
    assert error.value.code == code


def test_request_budget_is_enforced_before_retry():
    client, calls = client_with_responses([response(DIRECT)])
    with pytest.raises(RestrictedRoutingError) as error:
        RestrictedRoadRouter(client=client).route(DIRECT, [ROAD], request_budget=1)
    assert error.value.code == "RESTRICTED_GOOGLE_REQUEST_BUDGET"
    assert len(calls) == 1


def test_waypoint_limit_is_bounded_and_requires_operator_review():
    road = {**ROAD, "forward_waypoints": [[-1, -1]] * 26}
    client, calls = client_with_responses([response(DIRECT)])
    result = RestrictedRoadRouter(client=client).route(DIRECT, [road])
    assert len(calls) == 1
    assert result["metadata"]["reason"] == "WAYPOINT_LIMIT"


def test_real_google_client_serializes_via_high_quality_and_departure():
    def transport(request):
        body = json.loads(request.content)
        assert body["polylineQuality"] == "HIGH_QUALITY"
        assert body["intermediates"][0]["via"] is True
        assert "via" not in body["origin"] and "via" not in body["destination"]
        assert body["departureTime"].startswith("2030-01-01")
        return httpx.Response(200, json={"routes": [{"distanceMeters": 1900, "duration": "250s",
            "polyline": {"geoJsonLinestring": {"coordinates": DETOUR}}}]})
    client = GoogleRoutesClient("test", transport=httpx.MockTransport(transport))
    result = client.compute_route(origin=(0, -1), destination=(0, 1), intermediates=[(-1, -1)],
        departure_datetime=datetime(2030, 1, 1, tzinfo=timezone.utc), routing_mode="DRIVE",
        routing_preference="TRAFFIC_AWARE", via_intermediates=True, high_quality=True)
    assert result["distance_meters"] == 1900


def test_google_key_and_complete_waypoints_are_required():
    with pytest.raises(RestrictedRoutingError) as error:
        RestrictedRoadRouter().route(DIRECT, [ROAD])
    assert error.value.code == "GOOGLE_ROUTES_REQUIRED"
    client, calls = client_with_responses([response(DETOUR)])
    with pytest.raises(RestrictedRoutingError) as error:
        RestrictedRoadRouter(client=client).route(DIRECT, [{**ROAD, "reverse_waypoints": []}])
    assert error.value.code == "RESTRICTED_DETOUR_REQUIRED"
    assert calls == []
