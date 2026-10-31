import csv
from datetime import date, datetime, timezone
from io import StringIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.import_jobs import process_import
from app.importer import ImportProcessor
from app.main import app, settings
from app.master_data import refresh_historical_travel_times
from app.models import Base, FactLoadingOrderLine, FactShipment, FactShipmentSPBU, ImportAudit, MasterDepot, MasterMT, MasterSPBU
from app.normalization import mt_capacity_kl


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([MasterDepot(depot_id="A", depot_name="Depot A", timezone="Asia/Jakarta", active_status="ACTIVE"),
                    MasterDepot(depot_id="B", depot_name="Depot B", timezone="Asia/Jakarta", active_status="ACTIVE")])
        db.commit()
        def session_override():
            yield db
        app.dependency_overrides[get_db] = session_override
        monkeypatch.setattr(settings, "import_upload_dir", tmp_path)
        yield db, TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def upload(client, domain, content, depot="A"):
    params = {"domain": domain, "sheet_name": "Sheet1"}
    if depot is not None:
        params["depot_id"] = depot
    return client.post("/api/v1/imports", params=params, files={"file": ("data.csv", content, "text/csv")})


def test_upload_captures_active_depot_and_overrides_file_depot(workspace):
    db, client = workspace
    response = upload(client, "MT", "vehicle_registration,vehicle_type_tag,depot_id\nBK1234AA,24,B\n")
    assert response.status_code == 202
    audit = db.get(ImportAudit, response.json()["import_id"])
    assert audit.depot_id == "A"
    process_import(db, audit.import_id)
    assert audit.status == "PUBLISHED"
    mt = db.scalar(select(MasterMT))
    assert mt.depot_id == "A"
    assert mt.vehicle_registration == mt.vehicle_name_raw == "BK1234AA"
    assert mt.vehicle_type_tag == 24
    assert mt.capacity_label == "24KL"
    assert client.get("/api/v1/imports?depot_id=B").json() == []


@pytest.mark.parametrize("depot", [None, "UNKNOWN"])
def test_upload_requires_existing_active_depot(workspace, depot):
    _, client = workspace
    assert upload(client, "SPBU", "spbu_code\n001\n", depot).status_code == 400


def test_templates_remove_redundant_input_columns(workspace):
    _, client = workspace
    removed = {"depot_id", "source_depot_name", "vehicle_name_raw", "capacity_label", "spbu_name", "city", "source_coordinate", "master_travel_time_min", "status", "source_distance_km", "area_id", "area", "operating_date", "shipto", "validation_date", "validation_time", "gate_out_date", "gate_out_time", "shipment_end_date", "shipment_end_time"}
    for domain in ("MOBIL_TANGKI", "SPBU", "LOADING_ORDER"):
        response = client.get(f"/api/v1/exports/template?domain={domain}&file_format=csv")
        assert response.status_code == 200
        headers = next(csv.reader(StringIO(response.text.lstrip("\ufeff"))))
        assert not removed.intersection(headers)
        workbook = client.get(f"/api/v1/exports/template?domain={domain}")
        assert workbook.status_code == 200


def test_consolidated_import_and_historical_rth(workspace):
    db, client = workspace
    for domain, data in [
        ("MT", "vehicle_registration,vehicle_type_tag\nBK1234AA,24\n"),
        ("SPBU", "spbu_code,address,latitude,longitude\n001,Medan,3.5,98.6\n002,Binjai,3.6,98.5\n"),
        ("LOADING_ORDER", "shipment_id,loading_order_number,vehicle_registration,source_spbu_code,source_product_name,quantity,validation_datetime,gate_out_datetime,shipment_end_datetime,actual_km\n"
         "S1,L1,BK1234AA,001,PERTALITE,8,2026-09-01 23:30:00,2026-09-02 00:00:00,2026-09-02 02:00:00,70\n"
         "S1,L2,BK1234AA,001,BIOSOLAR,8,2026-09-01 23:30:00,2026-09-02 00:00:00,2026-09-02 02:00:00,70\n"
         "S2,L3,BK1234AA,001,PERTALITE,8,2026-09-03 08:00:00,2026-09-03 09:00:00,2026-09-03 13:00:00,70\n"
         "MULTI,L4,BK1234AA,001,PERTALITE,8,2026-09-04 08:00:00,2026-09-04 09:00:00,2026-09-04 19:00:00,200\n"
         "MULTI,L5,BK1234AA,002,PERTALITE,8,2026-09-04 08:00:00,2026-09-04 09:00:00,2026-09-04 19:00:00,200\n")]:
        response = upload(client, domain, data)
        assert response.status_code == 202
        process_import(db, response.json()["import_id"])
        audit = db.get(ImportAudit, response.json()["import_id"])
        assert audit.status == "PUBLISHED", audit.error_message
    shipment = db.get(FactShipment, "S1")
    assert shipment.operating_date == date(2026, 9, 1)
    assert shipment.mt_id is not None
    spbu = db.scalar(select(MasterSPBU).where(MasterSPBU.spbu_code == "001"))
    assert spbu.spbu_name == spbu.spbu_code
    assert spbu.address == "Medan"
    assert spbu.master_rth_min == 180
    assert spbu.master_travel_time_min == 90
    assert spbu.master_travel_time_sample_count == 2
    other = db.scalar(select(MasterSPBU).where(MasterSPBU.spbu_code == "002"))
    assert other.master_travel_time_min is None
    assert other.master_travel_time_sample_count == 0
    assert len(db.scalars(select(FactShipmentSPBU).where(FactShipmentSPBU.shipment_id == "S1")).all()) == 1
    rows = client.get("/api/v1/master-crud/LOADING_ORDER?depot_id=A").json()["rows"]
    assert all(row["gate_out_datetime"] for row in rows)
    exported = client.get("/api/v1/exports/data?domain=LOADING_ORDER&depot_id=A&file_format=csv")
    exported_rows = list(csv.DictReader(StringIO(exported.text.lstrip("\ufeff"))))
    assert next(row for row in exported_rows if row["loading_order_number"] == "L1")["validation_datetime"].startswith("2026-09-01")
    assert "status" not in exported_rows[0]


def test_crud_single_source_and_recalculate_on_historical_edit(workspace):
    db, client = workspace
    mt = client.post("/api/v1/master-crud/MOBIL_TANGKI", json={"depot_id": "A", "vehicle_registration": "BK 12 AA", "vehicle_type_tag": 24})
    assert mt.status_code == 200, mt.text
    spbu = client.post("/api/v1/master-crud/SPBU", json={"primary_depot_id": "A", "spbu_code": "001", "latitude": 3, "longitude": 98, "master_travel_time_min": 999})
    assert spbu.status_code == 200, spbu.text
    assert spbu.json()["record"]["master_travel_time_min"] is None
    payload = {"depot_id": "A", "shipment_id": "S1", "loading_order_number": "L1", "vehicle_registration": "BK12AA", "source_spbu_code": "001", "source_product_name": "PERTALITE", "quantity": 8, "validation_datetime": "2026-09-01 08:00:00", "gate_out_datetime": "2026-09-01 09:00:00", "shipment_end_datetime": "2026-09-01 11:00:00", "actual_km": 80}
    response = client.post("/api/v1/master-crud/LOADING_ORDER", json=payload)
    assert response.status_code == 200, response.text
    record_id = response.json()["record"]["crud_record_id"]
    master = db.get(MasterSPBU, spbu.json()["record"]["spbu_id"])
    assert master.master_travel_time_min == 60
    response = client.put(f"/api/v1/master-crud/LOADING_ORDER/{record_id}", json={**payload, "shipment_end_datetime": "2026-09-01 13:00:00"})
    assert response.status_code == 200, response.text
    assert master.master_travel_time_min == 120
    assert client.put(f"/api/v1/master-crud/LOADING_ORDER/{record_id}", json={**payload, "depot_id": "B"}).status_code == 400
    db.rollback()
    assert client.delete(f"/api/v1/master-crud/LOADING_ORDER/{record_id}").status_code == 200
    assert master.master_travel_time_min is None
    assert not db.scalars(select(FactShipmentSPBU)).all()


def test_vehicle_class_is_authoritative_for_capacity():
    assert mt_capacity_kl("16KL", 24) == 24
    assert mt_capacity_kl("16KL", None) == 16


def test_departure_observations_use_depot_timezone_after_postgres_utc_roundtrip():
    from app.departure_intelligence import build_observations
    depot = MasterDepot(depot_id="A", depot_name="Depot A", timezone="Asia/Jakarta")
    shipment = FactShipment(shipment_id="S", depot_id="A", operating_date=date(2026, 9, 2), gate_out_datetime=datetime(2026, 9, 1, 18, 30, tzinfo=timezone.utc))
    spbu = MasterSPBU(spbu_id="P", spbu_code="001")
    link = FactShipmentSPBU(shipment_id="S", spbu_id="P", assignment_source="LO")
    row = build_observations([(link, shipment, spbu, depot, None)], {}, {})[0]
    assert row["departure_minute"] == 90
    assert row["day_of_week"] == "Wednesday"
    assert row["departure_datetime_used"] == "2026-09-02T01:30:00+07:00"
