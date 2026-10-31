from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import MasterDepot, MasterRestrictedRoad
from .google_routes import GoogleRoutesError
from .restricted_roads import RestrictedRoadRouter, road_payload, missing_detours

router = APIRouter(prefix="/api/v1/depots/{depot_id}/restricted-roads", tags=["Restricted Roads"])


class RoadCoordinates(BaseModel):
    coordinates: list[list[float]] = Field(min_length=2, max_length=27)

    @model_validator(mode="after")
    def validate_coordinates(self):
        for p in self.coordinates:
            if len(p) != 2 or not all(math.isfinite(v) for v in p) or not (-180 <= p[0] <= 180 and -85 <= p[1] <= 85):
                raise ValueError("Coordinates must be [longitude, latitude] with valid finite values (latitude -85..85).")
        if any(a == b for a, b in zip(self.coordinates, self.coordinates[1:])):
            raise ValueError("Consecutive points must be different.")
        return self


class RoadWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)
    geometry: list[list[float]] = Field(min_length=2, max_length=10000)
    geometry_confirmed: bool
    direction: Literal["BOTH", "FORWARD", "REVERSE"] = "BOTH"
    forward_waypoints: list[list[float]] = Field(default_factory=list, max_length=25)
    reverse_waypoints: list[list[float]] = Field(default_factory=list, max_length=25)
    buffer_meters: float = Field(default=12, ge=2, le=100, allow_inf_nan=False)
    active: bool = True
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_road(self):
        self.name, self.reason = self.name.strip(), self.reason.strip()
        if not self.name or not self.reason:
            raise ValueError("Name and reason are required.")
        if not self.geometry_confirmed:
            raise ValueError("Review the actual road geometry on the map before confirming.")
        # Use the same validation without the waypoint-count limit.
        for p in [*self.geometry, *self.forward_waypoints, *self.reverse_waypoints]:
            if len(p) != 2 or not all(math.isfinite(v) for v in p) or not (-180 <= p[0] <= 180 and -85 <= p[1] <= 85):
                raise ValueError("Invalid GeoJSON road coordinates.")
        if all(p == self.geometry[0] for p in self.geometry):
            raise ValueError("Road must contain distinct points.")
        if self.active and missing_detours([{"restricted_road_id": "draft", **self.model_dump()}]):
            raise ValueError("Ordered alternative waypoints are required for every applicable direction of an active road.")
        for value in (self.valid_from, self.valid_until):
            if value and value.tzinfo is None:
                raise ValueError("Validity dates must include a timezone offset.")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from.")
        return self


def require_depot(db, depot_id):
    depot = db.get(MasterDepot, depot_id)
    if not depot:
        raise HTTPException(404, "Depot not found.")
    return depot


@router.get("")
def list_roads(depot_id: str, db: Session = Depends(get_db)):
    require_depot(db, depot_id)
    rows = db.scalars(select(MasterRestrictedRoad).where(MasterRestrictedRoad.depot_id == depot_id)
                      .order_by(MasterRestrictedRoad.name, MasterRestrictedRoad.restricted_road_id)).all()
    payloads = [road_payload(row) for row in rows]
    return {"roads": payloads, "router_configured": RestrictedRoadRouter(db).enabled,
            "scope": "ALL_MT_DIRECTIONAL", "missing_detour_ids": missing_detours([p for p in payloads if p["active"]])}


@router.post("/preview")
def preview_road(depot_id: str, request: RoadCoordinates, db: Session = Depends(get_db)):
    require_depot(db, depot_id)
    try:
        restricted_router = RestrictedRoadRouter(db)
        if not restricted_router.enabled:
            raise HTTPException(503, "Configure Google Routes in Google Maps Integration to preview road geometry, or confirm manually drawn geometry.")
        points = request.coordinates
        route = restricted_router.client.compute_route(origin=(points[0][1], points[0][0]), destination=(points[-1][1], points[-1][0]),
            intermediates=[(p[1], p[0]) for p in points[1:-1]] or None,
            departure_datetime=None, routing_mode="DRIVE", routing_preference="TRAFFIC_UNAWARE", via_intermediates=True, high_quality=True)
    except GoogleRoutesError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})
    if not route["route_geometry"]:
        raise HTTPException(422, "No connected road was found between the selected points.")
    return {"geometry": [[p["longitude"], p["latitude"]] for p in route["route_geometry"]],
            "distance_meters": route["distance_meters"], "requires_confirmation": True}


def save_road(db, depot_id, request, row=None):
    require_depot(db, depot_id)
    values = request.model_dump(exclude={"geometry_confirmed", "revision"})
    if row:
        if request.revision != row.revision:
            raise HTTPException(409, "Road changed since it was opened. Reload before saving.")
        row.revision += 1
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = MasterRestrictedRoad(restricted_road_id=uuid.uuid4().hex, depot_id=depot_id, revision=1, **values)
        db.add(row)
    db.commit()
    db.refresh(row)
    return road_payload(row)


@router.post("", status_code=201)
def create_road(depot_id: str, request: RoadWrite, db: Session = Depends(get_db)):
    return save_road(db, depot_id, request)


@router.put("/{road_id}")
def update_road(depot_id: str, road_id: str, request: RoadWrite, db: Session = Depends(get_db)):
    row = db.scalar(select(MasterRestrictedRoad).where(MasterRestrictedRoad.restricted_road_id == road_id,
                    MasterRestrictedRoad.depot_id == depot_id).with_for_update())
    if not row:
        raise HTTPException(404, "Restricted road not found in this depot.")
    return save_road(db, depot_id, request, row)
