from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import get_db
from .phase7_constants import constraint_catalog
from .phase7_readiness import import_readiness, readiness_template
from .phase7_service import (
    create_job,
    add_job_lo,
    cancel_job_los,
    job_lo_options,
    delete_bay_configuration,
    delete_job,
    enqueue_optimization,
    get_actual_bay_state,
    get_bay_configuration,
    get_cost_analysis,
    get_dropped_lo,
    get_job,
    get_lo_comparison,
    get_map_road_geometry,
    get_map_route,
    get_parameter_profile,
    get_route_version,
    get_simulation_data,
    get_trip_details,
    list_job_los,
    list_job_vehicles,
    list_jobs,
    list_parameter_profiles,
    list_prediction_runs_for_job,
    list_route_versions,
    load_mt_from_master,
    load_prediction_run,
    run_optimization_background,
    save_parameter_profile,
    update_actual_bay_state,
    update_lo_statuses,
    release_lo_dependencies,
    update_vehicle_states,
    upsert_bay_configuration,
    validate_job,
)


router = APIRouter(prefix="/api/v1/phase7", tags=["Phase 7 - Dynamic Multi-Trip VRP and Bay Queue"])


class JobCreateRequest(BaseModel):
    depot_id: str
    operating_date: date
    job_name: str = Field(min_length=1, max_length=255)


class PredictionRunLoadRequest(BaseModel):
    run_id: str


class LOStatusUpdate(BaseModel):
    loading_order_id: str
    status: str
    actual_gate_out: datetime | None = None
    actual_delivered_at: datetime | None = None


class LOOperationalUpdateRequest(BaseModel):
    updates: list[LOStatusUpdate]
    route_version_id: str | None = None


class LOCreateRequest(BaseModel):
    loading_order_id: str = Field(min_length=1, max_length=120)
    spbu_id: str
    product_id: str
    volume_kl: float = Field(gt=0, allow_inf_nan=False)

class LOCancelRequest(BaseModel):
    loading_order_ids: list[str] = Field(min_length=1, max_length=5000)


class VehicleStateUpdate(BaseModel):
    mt_id: str
    disabled_tag_ids: list[str] | None = None
    planned_eta_depot: datetime | None = None
    operational_status: str | None = None
    working_time_limit_minutes: int | None = Field(default=None, ge=1, le=2880)


class VehicleOperationalUpdateRequest(BaseModel):
    updates: list[VehicleStateUpdate]


class BayConfigurationRow(BaseModel):
    bay_id: str
    bay_name: str
    all_products_allowed: bool = False
    allowed_products: list[str] = Field(default_factory=list)
    operational_start: str = "05:00"
    operational_end: str = "22:00"
    number_of_loading_arms: int = Field(default=1, ge=1, le=20)
    loading_mode: str = "SEQUENTIAL"
    active_status: str = "ACTIVE"


class LoadingDurationRow(BaseModel):
    product_id: str
    duration_minutes_per_compartment: int = Field(ge=1, le=1440)


class BayConfigurationRequest(BaseModel):
    bays: list[BayConfigurationRow]
    loading_durations: list[LoadingDurationRow]


class ActualBayStateRow(BaseModel):
    master_bay_id: str
    current_vehicle_id: str | None = None
    current_compartment_id: str | None = None
    current_product_id: str | None = None
    remaining_loading_minutes: int = Field(default=0, ge=0, le=1440)
    actual_queue_length: int = Field(default=0, ge=0, le=1000)
    state_effective_at: datetime | None = None


class InitialQueueRow(BaseModel):
    master_bay_id: str
    queue_position: int = Field(ge=1)
    vehicle_id: str
    compartment_id: str | None = None
    product_id: str | None = None
    estimated_loading_duration_minutes: int = Field(ge=1, le=1440)
    state_effective_at: datetime | None = None


class ActualBayStateRequest(BaseModel):
    states: list[ActualBayStateRow]
    queue: list[InitialQueueRow]


class ParameterProfileRequest(BaseModel):
    profile_name: str
    description: str | None = None
    parameters: dict = Field(default_factory=dict)
    is_default: bool = False


class MapRoadGeometryRequest(BaseModel):
    version_id: str
    vehicle_ids: list[str] = Field(min_length=1, max_length=25)
    trip_number: int | None = Field(default=None, ge=1)


class OptimizationRequest(BaseModel):
    profile_id: str | None = None
    parameters: dict = Field(default_factory=dict)
    current_time: datetime
    reason: str | None = Field(default=None, max_length=160)
    route_time_limit_confirmed: bool = False


class ValidationRequest(BaseModel):
    parameters: dict = Field(default_factory=dict)


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_phase7_job(request: JobCreateRequest, db: Session = Depends(get_db)) -> dict:
    return create_job(db, request.model_dump(mode="json"))


@router.get("/jobs")
def phase7_jobs(depot_id: str = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    return list_jobs(db, depot_id)


@router.get("/jobs/{job_id}")
def phase7_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    return get_job(db, job_id)


@router.delete("/jobs/{job_id}")
def phase7_delete_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    return delete_job(db, job_id)


@router.get("/jobs/{job_id}/prediction-runs")
def phase7_prediction_runs(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return list_prediction_runs_for_job(db, job_id)


@router.post("/jobs/{job_id}/prediction-run")
def phase7_load_prediction_run(job_id: str, request: PredictionRunLoadRequest, db: Session = Depends(get_db)) -> dict:
    return load_prediction_run(db, job_id, request.run_id)


@router.get("/jobs/{job_id}/loading-orders")
def phase7_loading_orders(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return list_job_los(db, job_id)


@router.get("/jobs/{job_id}/loading-orders/options")
def phase7_lo_options(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return job_lo_options(db, job_id)


@router.post("/jobs/{job_id}/loading-orders", status_code=201)
def phase7_add_lo(job_id: str, request: LOCreateRequest, db: Session = Depends(get_db)) -> dict:
    return add_job_lo(db, job_id, request.model_dump())


@router.post("/jobs/{job_id}/loading-orders/cancel")
def phase7_cancel_los(job_id: str, request: LOCancelRequest, db: Session = Depends(get_db)) -> dict:
    return cancel_job_los(db, job_id, request.loading_order_ids)


@router.patch("/jobs/{job_id}/loading-orders/status")
def phase7_update_loading_orders(job_id: str, request: LOOperationalUpdateRequest, db: Session = Depends(get_db)) -> dict:
    return update_lo_statuses(db, job_id, [row.model_dump(mode="json") for row in request.updates], route_version_id=request.route_version_id)


@router.post("/jobs/{job_id}/loading-orders/release-dependency")
def phase7_release_dependency(job_id: str, request: LOCancelRequest, db: Session = Depends(get_db)) -> dict:
    return release_lo_dependencies(db, job_id, request.loading_order_ids)


@router.post("/jobs/{job_id}/loading-orders/release-freeze-window")
def phase7_release_freeze_window(job_id: str, request: LOCancelRequest, db: Session = Depends(get_db)) -> dict:
    return release_lo_dependencies(db, job_id, request.loading_order_ids, freeze_window=True)


@router.post("/jobs/{job_id}/vehicles/load-master")
def phase7_load_master_mt(job_id: str, db: Session = Depends(get_db)) -> dict:
    return load_mt_from_master(db, job_id)


@router.get("/jobs/{job_id}/vehicles")
def phase7_vehicles(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return list_job_vehicles(db, job_id)


@router.patch("/jobs/{job_id}/vehicles")
def phase7_update_vehicles(job_id: str, request: VehicleOperationalUpdateRequest, db: Session = Depends(get_db)) -> dict:
    return update_vehicle_states(db, job_id, [row.model_dump(mode="json", exclude_unset=True) for row in request.updates])


@router.get("/jobs/{job_id}/vehicles/readiness/template")
def phase7_readiness_template(job_id: str, db: Session = Depends(get_db)) -> Response:
    return Response(readiness_template(db, job_id), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="MT_Readiness.xlsx"'})


@router.post("/jobs/{job_id}/vehicles/readiness/import")
def phase7_import_readiness(job_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    return import_readiness(db, job_id, file.file.read(), file.filename or "")


@router.get("/depots/{depot_id}/bays")
def phase7_bay_configuration(depot_id: str, db: Session = Depends(get_db)) -> dict:
    return get_bay_configuration(db, depot_id)


@router.put("/depots/{depot_id}/bays")
def phase7_save_bay_configuration(depot_id: str, request: BayConfigurationRequest, db: Session = Depends(get_db)) -> dict:
    return upsert_bay_configuration(
        db,
        depot_id,
        [row.model_dump(mode="json") for row in request.bays],
        [row.model_dump(mode="json") for row in request.loading_durations],
    )


@router.delete("/depots/{depot_id}/bays/{bay_id}")
def phase7_delete_bay_configuration(depot_id: str, bay_id: str, db: Session = Depends(get_db)) -> dict:
    return delete_bay_configuration(db, depot_id, bay_id)


@router.get("/jobs/{job_id}/bay-state")
def phase7_bay_state(job_id: str, db: Session = Depends(get_db)) -> dict:
    return get_actual_bay_state(db, job_id)


@router.put("/jobs/{job_id}/bay-state")
def phase7_update_bay_state(job_id: str, request: ActualBayStateRequest, db: Session = Depends(get_db)) -> dict:
    return update_actual_bay_state(
        db,
        job_id,
        [row.model_dump(mode="json") for row in request.states],
        [row.model_dump(mode="json") for row in request.queue],
    )


@router.get("/jobs/{job_id}/validation")
def phase7_validate_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    return validate_job(db, job_id)


@router.post("/jobs/{job_id}/validation")
def phase7_validate_job_parameters(job_id: str, request: ValidationRequest, db: Session = Depends(get_db)) -> dict:
    return validate_job(db, job_id, request.parameters)


@router.post("/jobs/{job_id}/optimize", status_code=status.HTTP_202_ACCEPTED)
def phase7_initial_optimization(job_id: str, request: OptimizationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    payload = request.model_dump(mode="json", exclude_none=True)
    accepted = enqueue_optimization(db, job_id, payload, reroute=False)
    background_tasks.add_task(run_optimization_background, job_id, payload, reroute=False)
    return accepted


@router.post("/jobs/{job_id}/reroute", status_code=status.HTTP_202_ACCEPTED)
def phase7_reroute(job_id: str, request: OptimizationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    payload = request.model_dump(mode="json", exclude_none=True)
    accepted = enqueue_optimization(db, job_id, payload, reroute=True)
    background_tasks.add_task(run_optimization_background, job_id, payload, reroute=True)
    return accepted


@router.get("/jobs/{job_id}/versions")
def phase7_route_versions(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return list_route_versions(db, job_id)


@router.get("/jobs/{job_id}/comparison")
def phase7_lo_comparison(
    job_id: str,
    source_a: str = Query(..., min_length=1),
    source_b: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict:
    return get_lo_comparison(db, job_id, source_a, source_b)


@router.get("/jobs/{job_id}/versions/{version_id}")
def phase7_route_version(job_id: str, version_id: str, db: Session = Depends(get_db)) -> dict:
    return get_route_version(db, job_id, version_id)


@router.get("/jobs/{job_id}/versions/{version_id}/trips/{trip_id}")
def phase7_trip(job_id: str, version_id: str, trip_id: str, db: Session = Depends(get_db)) -> dict:
    return get_trip_details(db, job_id, version_id, trip_id)


@router.get("/jobs/{job_id}/simulation")
def phase7_simulation(job_id: str, version_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return get_simulation_data(db, job_id, version_id)


@router.get("/jobs/{job_id}/map")
def phase7_map(job_id: str, version_id: str | None = None, vehicle_id: str | None = None, trip_number: int | None = None, db: Session = Depends(get_db)) -> dict:
    return get_map_route(db, job_id, version_id, vehicle_id=vehicle_id, trip_number=trip_number)


@router.post("/jobs/{job_id}/map/road-geometry")
def phase7_map_road_geometry(job_id: str, request: MapRoadGeometryRequest, db: Session = Depends(get_db)) -> dict:
    return get_map_road_geometry(
        db,
        job_id,
        request.version_id,
        vehicle_ids=request.vehicle_ids,
        trip_number=request.trip_number,
    )


@router.get("/jobs/{job_id}/cost-analysis")
def phase7_cost(job_id: str, version_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return get_cost_analysis(db, job_id, version_id)


@router.get("/jobs/{job_id}/dropped-loading-orders")
def phase7_dropped(job_id: str, version_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return get_dropped_lo(db, job_id, version_id)


@router.get("/parameter-profiles")
def phase7_parameter_profiles(include_inactive: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    return list_parameter_profiles(db, include_inactive=include_inactive)


@router.get("/constraint-catalog")
def phase7_constraint_catalog() -> list[dict]:
    return constraint_catalog()


@router.get("/parameter-profiles/{profile_id}")
def phase7_parameter_profile(profile_id: str, db: Session = Depends(get_db)) -> dict:
    return get_parameter_profile(db, profile_id)


@router.post("/parameter-profiles", status_code=status.HTTP_201_CREATED)
def phase7_save_as_parameter_profile(request: ParameterProfileRequest, db: Session = Depends(get_db)) -> dict:
    return save_parameter_profile(db, request.model_dump(mode="json"), save_as=True)


@router.put("/parameter-profiles/{profile_id}", status_code=status.HTTP_201_CREATED)
def phase7_save_parameter_profile(profile_id: str, request: ParameterProfileRequest, db: Session = Depends(get_db)) -> dict:
    return save_parameter_profile(db, request.model_dump(mode="json"), source_profile_id=profile_id, save_as=False)
