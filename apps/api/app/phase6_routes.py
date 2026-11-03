from __future__ import annotations

import json
from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import MasterMT
from .phase6_auth import Phase6Actor, require_phase6_permission
from .phase6_capacity import mt_compartment_profile
from .phase6_demo import generate_demo_loading_orders, generate_demo_mt_availability
from .phase6_export import loading_order_template, loading_order_workbook, mt_availability_template, mt_availability_workbook, prediction_export, validation_report
from .phase6_service import (
    adjust_shipment,
    duplicate_prediction_run,
    enqueue_prediction_run,
    get_prediction_run,
    get_prediction_shipment_candidates,
    get_prediction_run_status,
    list_prediction_models,
    list_prediction_runs,
    override_assignment,
    override_trip_assignment,
    refresh_prediction_route_geometry,
)
from .phase6_validation import require_prediction_model, validate_loading_orders, validate_mt_availability


router = APIRouter(prefix="/api/v1/phase6", tags=["Phase 6 - Prediction and Assignment"])


class AssignmentOverrideRequest(BaseModel):
    vehicle_id: str
    override_reason: str | None = Field(default=None, max_length=2000)


class ShipmentOverrideRequest(BaseModel):
    action: str
    line_ids: list[str] = Field(default_factory=list)
    target_shipment_id: str | None = None


class RerunRequest(BaseModel):
    model_id: str | None = None


class RouteGeometryRequest(BaseModel):
    vehicle_id: str


class DemoLoadingOrderRequest(BaseModel):
    depot_id: str
    model_id: str
    total_order_kl: float = Field(gt=0, le=40000)
    loading_order_date: date


class DemoMTAvailabilityRequest(BaseModel):
    depot_id: str
    model_id: str
    total_capacity_kl: float = Field(gt=0, le=40000)
    random_availability: bool = False


class ManagedLoadingOrderRow(BaseModel):
    shift: str | None = Field(default=None, max_length=120)
    loading_order_no: str | None = Field(default=None, max_length=200)
    shipment_start_datetime: str | None = Field(default=None, max_length=100)
    spbu_no: str | None = Field(default=None, max_length=200)
    product: str | None = Field(default=None, max_length=255)
    order_quantity_kl: str | float | int | None = None


class ManagedLoadingOrderWorkbookRequest(BaseModel):
    rows: list[ManagedLoadingOrderRow] = Field(default_factory=list, max_length=10000)


class ManagedMTAvailabilityRow(BaseModel):
    vehicle_registration_no: str | None = Field(default=None, max_length=200)
    initial_available_datetime: str | None = Field(default=None, max_length=100)


class ManagedMTAvailabilityWorkbookRequest(BaseModel):
    rows: list[ManagedMTAvailabilityRow] = Field(default_factory=list, max_length=10000)


def _excel_response(content: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/models")
def prediction_models(
    depot_id: str,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> list[dict]:
    return list_prediction_models(db, depot_id)


@router.get("/master-mt-availability")
def master_mt_availability(
    depot_id: str,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> list[dict]:
    rows = db.scalars(
        select(MasterMT)
        .where(MasterMT.depot_id == depot_id, MasterMT.active_status == "ACTIVE")
        .order_by(MasterMT.vehicle_registration)
    ).all()
    result = []
    for row in rows:
        profile = mt_compartment_profile(row)
        result.append(
            {
                "mt_id": row.mt_id,
                "vehicle_registration": row.vehicle_registration,
                "capacity_label": row.capacity_label,
                "vehicle_type_tag": row.vehicle_type_tag,
                "number_of_compartments": row.number_of_compartments,
                "depot_id": row.depot_id,
                "active_status": row.active_status,
                "phase6_eligible": profile["valid"],
                "phase6_failed_rules": profile["failed_rules"],
            }
        )
    return result


@router.get("/templates/loading-order")
def download_loading_order_template(
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> StreamingResponse:
    return _excel_response(loading_order_template(), "phase6-loading-order-template.xlsx")


@router.post("/loading-orders/workbook")
def create_managed_loading_order_workbook(
    request: ManagedLoadingOrderWorkbookRequest,
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> StreamingResponse:
    return _excel_response(
        loading_order_workbook([row.model_dump() for row in request.rows]),
        "phase6-managed-loading-orders.xlsx",
    )


@router.post("/mt-availability/workbook")
def create_managed_mt_availability_workbook(
    request: ManagedMTAvailabilityWorkbookRequest,
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> StreamingResponse:
    return _excel_response(
        mt_availability_workbook([row.model_dump() for row in request.rows]),
        "phase6-managed-mt-availability.xlsx",
    )


@router.post("/demo/loading-order")
def create_demo_loading_order_file(
    request: DemoLoadingOrderRequest,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> StreamingResponse:
    model = require_prediction_model(db, request.depot_id, request.model_id)
    content, filename = generate_demo_loading_orders(
        db,
        depot_id=request.depot_id,
        model=model,
        total_order_kl=request.total_order_kl,
        loading_order_date=request.loading_order_date,
    )
    return _excel_response(content, filename)


@router.post("/demo/mt-availability")
def create_demo_mt_availability_file(
    request: DemoMTAvailabilityRequest,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> StreamingResponse:
    model = require_prediction_model(db, request.depot_id, request.model_id)
    content, filename = generate_demo_mt_availability(
        db,
        depot_id=request.depot_id,
        model=model,
        total_capacity_kl=request.total_capacity_kl,
        random_availability=request.random_availability,
    )
    return _excel_response(content, filename)


@router.get("/templates/mt-availability")
def download_mt_availability_template(
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> StreamingResponse:
    return _excel_response(mt_availability_template(), "phase6-mt-availability-template.xlsx")


@router.get("/templates/mt-initial-availability")
def download_mt_initial_availability_template(
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> StreamingResponse:
    return _excel_response(mt_availability_template(), "phase6-mt-initial-availability-template.xlsx")


@router.post("/validate/loading-order")
async def validate_loading_order_file(
    depot_id: str = Form(...),
    model_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> dict:
    model = require_prediction_model(db, depot_id, model_id)
    return validate_loading_orders(db, depot_id=depot_id, model=model, content=await file.read(), file_name=file.filename or "loading-order.xlsx")


@router.post("/validate/mt-availability")
async def validate_mt_availability_file(
    depot_id: str = Form(...),
    model_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> dict:
    model = require_prediction_model(db, depot_id, model_id)
    return validate_mt_availability(db, depot_id=depot_id, model=model, content=await file.read(), file_name=file.filename or "mt-availability.xlsx")


@router.post("/validation-report")
async def download_validation_report(
    depot_id: str = Form(...),
    model_id: str = Form(...),
    loading_order_file: UploadFile = File(...),
    mt_availability_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> StreamingResponse:
    model = require_prediction_model(db, depot_id, model_id)
    lo = validate_loading_orders(db, depot_id=depot_id, model=model, content=await loading_order_file.read(), file_name=loading_order_file.filename or "loading-order.xlsx")
    mt = validate_mt_availability(db, depot_id=depot_id, model=model, content=await mt_availability_file.read(), file_name=mt_availability_file.filename or "mt-availability.xlsx")
    return _excel_response(validation_report([*lo["issues"], *mt["issues"]]), "phase6-validation-report.xlsx")


@router.post("/predictions", status_code=status.HTTP_202_ACCEPTED)
async def run_prediction(
    depot_id: str = Form(...),
    model_id: str = Form(...),
    parameters: str = Form(default="{}"),
    loading_order_file: UploadFile = File(...),
    mt_availability_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> dict:
    try:
        parsed_parameters = json.loads(parameters)
        if not isinstance(parsed_parameters, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAMETER", "message": "parameters must be a JSON object."}) from exc
    queued = enqueue_prediction_run(
        db,
        depot_id=depot_id,
        model_id=model_id,
        loading_order_content=await loading_order_file.read(),
        loading_order_filename=loading_order_file.filename or "loading-order.xlsx",
        availability_content=await mt_availability_file.read(),
        availability_filename=mt_availability_file.filename or "mt-availability.xlsx",
        parameters=parsed_parameters,
        created_by=actor.user_id,
    )
    return queued


@router.get("/predictions")
def prediction_history(
    depot_id: str | None = None,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> list[dict]:
    return list_prediction_runs(db, depot_id)


@router.get("/predictions/{run_id}/status")
def prediction_status(
    run_id: str,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> dict:
    return get_prediction_run_status(db, run_id)


@router.get("/predictions/{run_id}")
def prediction_detail(
    run_id: str,
    shipment_page: int = Query(default=1, ge=1),
    shipment_page_size: int = Query(default=25, ge=1, le=100),
    shift_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> dict:
    return get_prediction_run(
        db,
        run_id,
        shipment_page=shipment_page,
        shipment_page_size=shipment_page_size,
        shift_id=shift_id,
        include_candidates=False,
    )


@router.get("/predictions/{run_id}/shipments/{shipment_id}/candidates")
def prediction_shipment_candidates(
    run_id: str,
    shipment_id: str,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("view")),
) -> dict:
    return get_prediction_shipment_candidates(db, run_id, shipment_id)


@router.post("/predictions/{run_id}/recalculate", status_code=status.HTTP_202_ACCEPTED)
def rerun_prediction(
    run_id: str,
    request: RerunRequest,
    db: Session = Depends(get_db),
    actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> dict:
    return duplicate_prediction_run(db, run_id, model_id=request.model_id, created_by=actor.user_id)


@router.post("/predictions/{run_id}/route-geometry")
def load_prediction_route_geometry(
    run_id: str,
    request: RouteGeometryRequest,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("run")),
) -> dict:
    return refresh_prediction_route_geometry(db, run_id, request.vehicle_id)


@router.patch("/predictions/{run_id}/shipments/{shipment_id}")
def patch_shipment(
    run_id: str,
    shipment_id: str,
    request: ShipmentOverrideRequest,
    db: Session = Depends(get_db),
    actor: Phase6Actor = Depends(require_phase6_permission("override")),
) -> dict:
    return adjust_shipment(
        db,
        run_id,
        shipment_id,
        action=request.action,
        line_ids=request.line_ids,
        target_shipment_id=request.target_shipment_id,
        user_id=actor.user_id,
    )


@router.patch("/predictions/{run_id}/assignments/{assignment_id}")
def patch_assignment(
    run_id: str,
    assignment_id: str,
    request: AssignmentOverrideRequest,
    db: Session = Depends(get_db),
    actor: Phase6Actor = Depends(require_phase6_permission("override")),
) -> dict:
    return override_assignment(db, run_id, assignment_id, request.vehicle_id, request.override_reason, actor.user_id)


@router.patch("/predictions/{run_id}/trips/{trip_id}")
def patch_trip_assignment(
    run_id: str,
    trip_id: str,
    request: AssignmentOverrideRequest,
    db: Session = Depends(get_db),
    actor: Phase6Actor = Depends(require_phase6_permission("override")),
) -> dict:
    return override_trip_assignment(db, run_id, trip_id, request.vehicle_id, request.override_reason, actor.user_id)


@router.get("/predictions/{run_id}/export")
def export_prediction(
    run_id: str,
    db: Session = Depends(get_db),
    _actor: Phase6Actor = Depends(require_phase6_permission("export")),
) -> StreamingResponse:
    content, filename = prediction_export(db, run_id)
    return _excel_response(content, filename)
