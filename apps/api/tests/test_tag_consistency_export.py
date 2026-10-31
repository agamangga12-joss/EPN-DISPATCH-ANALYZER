from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, FactLoadingOrderLine, FactShipment, MasterDepot, MasterMT, MasterProduct, MasterSPBU


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            MasterDepot(depot_id="A", depot_name="Depot A", active_status="ACTIVE"),
            MasterDepot(depot_id="B", depot_name="Depot B", active_status="ACTIVE"),
            MasterMT(mt_id="MT", depot_id="A", vehicle_name_raw="=TEST", vehicle_registration="=TEST", vehicle_type_tag=24),
            MasterSPBU(spbu_id="S", primary_depot_id="A", spbu_code="00001", vehicle_type_tag=16),
            MasterSPBU(spbu_id="MATCH", primary_depot_id="A", spbu_code="00002", vehicle_type_tag=32),
            MasterProduct(product_id="P", product_name="PERTALITE", normalized_product="PERTALITE"),
        ])
        for shipment_id, depot_id, day in [("A", "A", 8), ("OLD", "A", 7), ("B", "B", 8)]:
            db.add(FactShipment(shipment_id=shipment_id, source_shipment_id=shipment_id, depot_id=depot_id, operating_date=date(2026, 10, day), mt_id="MT", vehicle_registration="=TEST"))
        for index in range(503):
            db.add(FactLoadingOrderLine(loading_order_id=f"ID{index}", loading_order_number=f"L{index:04}", source_depot_name="Depot A", depot_id="A", shipment_id="A", spbu_id="S", product_id="P"))
        for shipment_id in ("OLD", "B"):
            db.add(FactLoadingOrderLine(loading_order_id=shipment_id, loading_order_number=shipment_id, source_depot_name=shipment_id, shipment_id=shipment_id, spbu_id="S", product_id="P"))
        db.add(FactLoadingOrderLine(loading_order_id="MATCH", loading_order_number="MATCH", source_depot_name="Depot A", shipment_id="A", spbu_id="MATCH", product_id="P"))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
    engine.dispose()


def workbook(client, params):
    response = client.get("/api/v1/tag-consistency/analysis", params={**params, "export_excel": True})
    assert response.status_code == 200, response.text[:200] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert '.xlsx"' in response.headers["content-disposition"]
    return load_workbook(BytesIO(response.content))["Main Analysis Table"]


def test_export_all_matching_rows_beyond_page_limit_with_sort_and_text_identifiers(client):
    params = {"depot_id": "A", "overall_status": "MISMATCH", "sort_column": "loading_order_number", "sort_direction": "desc", "limit": 25, "offset": 25}
    table = client.get("/api/v1/tag-consistency/analysis", params=params).json()
    assert table["total"] == 503
    assert len(table["rows"]) == 25
    sheet = workbook(client, params)
    assert sheet.max_row == 504
    assert [cell.value for cell in sheet[1]] == ["Date", "Loading Order", "Vehicle Registration", "SPBU", "Depot", "Overall Status", "Vehicle Class Result", "Tag Match Result", "Issue / Reason"]
    assert sheet["B2"].value == "L0502"
    assert sheet["B504"].value == "L0000"
    assert sheet["C2"].value == "=TEST" and sheet["C2"].data_type == "s"
    assert sheet["D2"].value == "00001"
    assert sheet["I27"].value == table["rows"][0]["primary_reason"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:I504"


def test_export_uses_all_analysis_filters_and_handles_empty_results(client):
    params = {"depot_id": "A", "start_date": "2026-10-08", "end_date": "2026-10-08", "spbu": "00001", "vehicle": "TEST", "vehicle_class": 24, "product_id": "P", "tag_type": "VEHICLE_CLASS", "overall_status": "MISMATCH", "search": "L050", "sort_column": "loading_order_number", "sort_direction": "asc"}
    table = client.get("/api/v1/tag-consistency/analysis", params=params).json()
    sheet = workbook(client, params)
    assert table["total"] == 3
    assert [row[1].value for row in list(sheet.rows)[1:]] == [row["loading_order_number"] for row in table["rows"]]
    assert workbook(client, {**params, "search": "NO-SUCH-ORDER"}).max_row == 1
    assert client.get("/api/v1/tag-consistency/analysis", params={"export_excel": True, "start_date": "invalid"}).status_code == 400
