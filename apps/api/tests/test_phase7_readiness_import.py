from datetime import date, datetime, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, MasterDepot, MasterMT, OptimizationJob, VehicleOperationalState

BASE = "/api/v1/phase7/jobs/J/vehicles/readiness"
HEADERS = ["MT REGISTRATION", "OPERATIONAL STATUS", "PLANNED ETA DEPOT"]
ORIGINAL_ETA = datetime(2026, 10, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def workspace():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(MasterDepot(depot_id="D", depot_name="Depot", timezone="Asia/Makassar"))
        db.add(OptimizationJob(job_id="J", job_no="JOB", job_name="Job", depot_id="D", operating_date=date(2026, 10, 8)))
        db.add(OptimizationJob(job_id="OTHER", job_no="OTHER", job_name="Other", depot_id="D", operating_date=date(2026, 10, 8)))
        for index in range(3):
            db.add(MasterMT(mt_id=f"M{index}", vehicle_name_raw=f"MT{index}", depot_id="D"))
            db.add(VehicleOperationalState(vehicle_state_id=f"V{index}", job_id="J", mt_id=f"M{index}", registration_snapshot=f"B100{index}AA", capacity_kl=8, number_of_compartments=1, compartment_configuration=[], planned_eta_depot=ORIGINAL_ETA, operational_status="READY", working_time_used_minutes=60, working_time_remaining_minutes=540, working_time_limit_minutes=600))
        db.add(VehicleOperationalState(vehicle_state_id="OTHER", job_id="OTHER", mt_id="M0", registration_snapshot="OTHER-REG", capacity_kl=8, number_of_compartments=1, compartment_configuration=[]))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app), db
        finally:
            app.dependency_overrides.clear()
    engine.dispose()


def excel(rows, headers=HEADERS):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def upload(client, content):
    return client.post(BASE + "/import", files={"file": ("readiness.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def assert_unchanged(db):
    db.expire_all()
    for index in range(3):
        row = db.get(VehicleOperationalState, f"V{index}")
        assert row.operational_status == "READY"
        assert row.planned_eta_depot.replace(tzinfo=timezone.utc) == ORIGINAL_ETA


def test_template_contains_all_job_mt_current_values_status_dropdown_and_depot_local_eta(workspace):
    client, db = workspace
    for index in range(3, 105):
        db.add(MasterMT(mt_id=f"M{index}", vehicle_name_raw=f"MT{index}", depot_id="D"))
        db.add(VehicleOperationalState(vehicle_state_id=f"V{index}", job_id="J", mt_id=f"M{index}", registration_snapshot=f"B{index}AA", capacity_kl=8, number_of_compartments=1, compartment_configuration=[]))
    db.commit()
    response = client.get(BASE + "/template")
    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content))
    sheet = workbook["MT Readiness"]
    assert [cell.value for cell in sheet[1]] == HEADERS
    assert sheet.max_row == 106
    assert "OTHER-REG" not in [row[0].value for row in sheet.iter_rows(min_row=2)]
    row = next(row for row in sheet.iter_rows(min_row=2) if row[0].value == "B1000AA")
    assert row[0].data_type == "s"
    assert row[1].value == "READY"
    assert row[2].value == datetime(2026, 10, 8, 8)
    assert "UNAVAILABLE" in sheet.data_validations.dataValidation[0].formula1
    assert any("Asia/Makassar" in str(row[0].value) for row in workbook["Petunjuk"].iter_rows())
    workbook.close()


def test_import_updates_matched_mt_uses_depot_timezone_preserves_blank_and_other_fields(workspace):
    client, db = workspace
    response = upload(client, excel([
        ["b 1000 aa", "unavailable", None],
        ["B1001AA", None, datetime(2026, 10, 8, 9, 30)],
        [None, None, None],
        ["B1002AA", None, None],
    ]))
    assert response.status_code == 200, response.text
    assert response.json()["imported_count"] == 2
    assert response.json()["skipped_count"] == 1
    db.expire_all()
    assert db.get(VehicleOperationalState, "V0").operational_status == "UNAVAILABLE"
    assert db.get(VehicleOperationalState, "V0").planned_eta_depot.replace(tzinfo=timezone.utc) == ORIGINAL_ETA
    row = db.get(VehicleOperationalState, "V1")
    assert row.operational_status == "READY"
    assert row.planned_eta_depot.replace(tzinfo=timezone.utc) == datetime(2026, 10, 8, 1, 30, tzinfo=timezone.utc)
    assert row.working_time_used_minutes == 60
    assert row.working_time_remaining_minutes == 540
    assert row.working_time_limit_minutes == 600
    assert row.updated_by == "excel-readiness-import"
    assert db.get(VehicleOperationalState, "V2").planned_eta_depot.replace(tzinfo=timezone.utc) == ORIGINAL_ETA


@pytest.mark.parametrize("invalid_row", [
    ["OTHER-REG", "READY", None],
    ["B1001AA", "ACTIVE", None],
    ["B1001AA", None, "2026-10-08"],
    ["B1001AA", None, "2026-02-30 08:00:00"],
    ["B1001AA", "=A2", None],
    [None, "READY", None],
    ["B1000AA", "READY", None],
])
def test_invalid_row_rejects_entire_file_with_row_number(workspace, invalid_row):
    client, db = workspace
    response = upload(client, excel([["B1000AA", "UNAVAILABLE", "2026-10-08 10:00:00"], invalid_row]))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["errors"][0]["row"] == 3
    assert "Baris 3" in response.json()["detail"]["message"]
    assert_unchanged(db)


def test_import_reordered_headers_and_explicit_timezone(workspace):
    client, db = workspace
    response = upload(client, excel([["2026-10-08T09:00:00+07:00", "RETURNING", "B1000AA"]], headers=list(reversed(HEADERS))))
    assert response.status_code == 200, response.text
    db.expire_all()
    row = db.get(VehicleOperationalState, "V0")
    assert row.planned_eta_depot.replace(tzinfo=timezone.utc) == datetime(2026, 10, 8, 2, tzinfo=timezone.utc)
    assert row.operational_status == "RETURNING"


def test_template_roundtrip_keeps_utc_eta(workspace):
    client, db = workspace
    response = upload(client, client.get(BASE + "/template").content)
    assert response.status_code == 200, response.text
    assert response.json()["imported_count"] == 3
    assert_unchanged(db)


def test_import_is_blocked_when_job_is_calculating(workspace):
    client, db = workspace
    db.get(OptimizationJob, "J").status = "CALCULATING"
    db.commit()
    response = upload(client, excel([["B1000AA", "UNAVAILABLE", "2026-10-08 10:00:00"]]))
    assert response.status_code == 409
    assert_unchanged(db)


@pytest.mark.parametrize("content", [b"invalid workbook", excel([], headers=["Wrong"]), excel([["B1000AA", None, None]])])
def test_invalid_or_empty_workbook_is_rejected(workspace, content):
    client, db = workspace
    response = upload(client, content)
    assert response.status_code == 422
    assert_unchanged(db)
