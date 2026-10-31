from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.departure_intelligence import circular_stats, shift_for_minute, validate_shift_config
from app.importer import ImportProcessor
from app.main import IMPORT_TEMPLATE_COLUMNS, app
from app.models import Base, FactLoadingOrderLine, FactShipment, FactShipmentSPBU, ImportAudit, MasterDepot, MasterMT, MasterProduct, MasterSPBU, MasterTag

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DIR = ROOT / "example data"


def test_health_endpoint() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_manual_depot_creation_generates_id_and_depot_sync_is_disabled() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/master-crud/DEPOT",
            json={"depot_code": "TMD", "depot_name": "TEST MANUAL DEPOT"},
        )
        assert created.status_code == 200
        depot_id = created.json()["record"]["depot_id"]
        assert depot_id.startswith("depot_")

        listed = client.get(
            "/api/v1/master-crud/DEPOT",
            params={"search": depot_id, "search_column": "depot_id"},
        )
        assert listed.status_code == 200
        assert listed.json()["rows"][0]["depot_id"] == depot_id

        sync = client.post("/api/v1/master-crud/DEPOT/sync")
        assert sync.status_code == 400
        assert "managed manually" in sync.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_spbu_crud_backfills_lat_long_from_source_coordinate() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            MasterSPBU(
                spbu_id="spbu_coordinate_backfill",
                spbu_code="11201199",
                spbu_name="11201199",
                source_coordinate="5,19182389869645 96,4368560343681",
                latitude=None,
                longitude=None,
                active_status="ACTIVE",
            )
        )
        session.commit()

    def override_db():
        with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/master-crud/SPBU", params={"search": "11201199", "search_column": "spbu_code"})
        assert response.status_code == 200
        row = response.json()["rows"][0]
        assert row["source_coordinate"] == "5,19182389869645 96,4368560343681"
        assert row["latitude"] == 5.19182389869645
        assert row["longitude"] == 96.4368560343681

        with Session() as session:
            spbu = session.get(MasterSPBU, "spbu_coordinate_backfill")
            assert spbu.latitude == 5.19182389869645
            assert spbu.longitude == 96.4368560343681
    finally:
        app.dependency_overrides.clear()


def test_departure_circular_stats_handle_midnight_cluster() -> None:
    stats = circular_stats([23 * 60 + 30, 23 * 60 + 50, 5, 20, 35])
    assert stats["p50"] in {5, 1445 % 1440}
    assert stats["iqr_minutes"] < 60
    assert stats["crosses_midnight"] is True
    assert [stats["min_linear"], stats["p25_linear"], stats["p50_linear"], stats["p75_linear"], stats["max_linear"]] == sorted(
        [stats["min_linear"], stats["p25_linear"], stats["p50_linear"], stats["p75_linear"], stats["max_linear"]]
    )
    assert stats["p50_linear"] > 1440


def test_shift_config_boundaries_and_validation() -> None:
    shifts = validate_shift_config(
        [
            {"shift_id": "s1", "name": "Shift 1", "start_time": "00:00", "end_time": "05:59"},
            {"shift_id": "s2", "name": "Shift 2", "start_time": "06:00", "end_time": "11:59"},
            {"shift_id": "s3", "name": "Shift 3", "start_time": "12:00", "end_time": "17:59"},
            {"shift_id": "s4", "name": "Shift 4", "start_time": "18:00", "end_time": "23:59"},
        ]
    )
    assert shift_for_minute(5 * 60 + 59, shifts)["shift_id"] == "s1"
    assert shift_for_minute(6 * 60, shifts)["shift_id"] == "s2"

    try:
        validate_shift_config(
            [
                {"shift_id": "s1", "name": "Shift 1", "start_time": "00:00", "end_time": "07:00"},
                {"shift_id": "s2", "name": "Shift 2", "start_time": "06:00", "end_time": "12:00"},
            ]
        )
    except Exception as exc:
        assert "overlap" in str(exc).lower()
    else:
        raise AssertionError("overlapping shift ranges should be rejected")


def test_dashboard_counts_match_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        processor = ImportProcessor(session)
        processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
        processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")
        processor.import_loading_order(EXAMPLE_DIR / "masterdata_LO.xlsx")

    def override_db():
        with Session() as test_session:
            yield test_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.get("/api/v1/foundation/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_mt"] == 162
    assert payload["total_spbu"] == 583
    assert payload["total_loading_order_lines"] == 4462
    assert payload["total_shipments"] == 1876
    with Session() as session:
        session.add(MasterMT(mt_id="mt_deleted_chart", vehicle_name_raw="DELETED-MT", vehicle_registration="DELETEDMT", active_status="DELETED"))
        session.add(MasterSPBU(spbu_id="spbu_deleted_chart", spbu_code="DELETEDSPBU", active_status="DELETED"))
        session.commit()
    charts = client.get("/api/v1/foundation/charts")
    assert charts.status_code == 200
    chart_payload = charts.json()
    assert chart_payload["spbu_per_shipment_distribution"]
    assert all(row["name"] != "UNKNOWN" for row in chart_payload["mt_by_vehicle_type_tag"])
    assert all(row["name"] != "UNKNOWN" for row in chart_payload["spbu_by_vehicle_type_tag"])

    imports = client.get("/api/v1/imports")
    assert imports.status_code == 200
    import_rows = imports.json()
    assert 0 < len(import_rows) <= 8
    assert all(row["uploaded_at"] for row in import_rows)

    template = client.get("/api/v1/exports/template?domain=MOBIL_TANGKI&file_format=csv")
    assert template.status_code == 200
    assert template.text.lstrip("\ufeff").startswith("vehicle_registration,")
    assert "depot_id" not in template.text
    assert "vehicle_type_tag" in template.text
    assert "vehicle_registration" in template.text
    assert "vehicle_name_raw" not in template.text
    assert "source_mt_id" not in template.text
    assert "source_hub_id" not in template.text
    assert "assignee" not in template.text
    for template_domain in ("SPBU", "LOADING_ORDER"):
        domain_template = client.get(f"/api/v1/exports/template?domain={template_domain}&file_format=csv")
        assert domain_template.status_code == 200
        actual_header = domain_template.text.lstrip("\ufeff").splitlines()[0]
        assert actual_header == ",".join(IMPORT_TEMPLATE_COLUMNS[template_domain])

    with Session() as session:
        depot = session.query(MasterDepot).order_by(MasterDepot.depot_name).first()
    exported = client.get(f"/api/v1/exports/data?domain=SPBU&depot_id={depot.depot_id}&file_format=csv")
    assert exported.status_code == 200
    assert "spbu_code" in exported.text
    assert "depot_id" not in exported.text.splitlines()[0]
    with (EXAMPLE_DIR / "template_spbu.xlsx").open("rb") as handle:
        upload_template_spbu = client.post(
            f"/api/v1/imports?domain=SPBU&sheet_name=Lembaga%20Penyalur&depot_id={depot.depot_id}",
            files={"file": ("template_spbu.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert upload_template_spbu.status_code == 202
    uploaded_import_id = upload_template_spbu.json()["import_id"]
    imports_payload = client.get("/api/v1/imports").json()
    uploaded_audit = next(item for item in imports_payload if item["import_id"] == uploaded_import_id)
    assert uploaded_audit["sheet_name"] == "Lembaga Penyalur"
    assert uploaded_audit["status"] == "QUEUED"
    with (EXAMPLE_DIR / "template_spbu.xlsx").open("rb") as handle:
        wrong_domain_upload = client.post(
            f"/api/v1/imports?domain=MOBIL_TANGKI&sheet_name=SPBU&depot_id={depot.depot_id}",
            files={"file": ("template_spbu.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert wrong_domain_upload.status_code == 202
    wrong_import_id = wrong_domain_upload.json()["import_id"]
    with Session() as session:
        for queued_import_id in (uploaded_import_id, wrong_import_id):
            queued = session.get(ImportAudit, queued_import_id)
            assert queued is not None
            assert queued.status == "QUEUED"
            if queued.stored_path:
                Path(queued.stored_path).unlink(missing_ok=True)

    with Session() as session:
        expected_mt = session.query(MasterMT).filter(MasterMT.depot_id == depot.depot_id).count()
        expected_spbu = session.query(MasterSPBU).filter(MasterSPBU.primary_depot_id == depot.depot_id).count()
        expected_shipments = session.query(FactShipment).filter(FactShipment.depot_id == depot.depot_id).count()
        expected_loading_orders = (
            session.query(FactLoadingOrderLine)
            .join(FactShipment, FactShipment.shipment_id == FactLoadingOrderLine.shipment_id)
            .filter(FactShipment.depot_id == depot.depot_id)
            .count()
        )
        sample_loading_order = (
            session.query(FactLoadingOrderLine)
            .join(FactShipment, FactShipment.shipment_id == FactLoadingOrderLine.shipment_id)
            .filter(FactShipment.depot_id == depot.depot_id, FactShipment.validation_datetime.isnot(None))
            .order_by(FactLoadingOrderLine.loading_order_number)
            .first()
        )
        sample_loading_order_vehicle_registration = (
            session.query(FactShipment.vehicle_registration)
            .filter(FactShipment.shipment_id == sample_loading_order.shipment_id)
            .scalar()
        )
        sample_loading_order_validation_datetime = (
            session.query(FactShipment.validation_datetime)
            .filter(FactShipment.shipment_id == sample_loading_order.shipment_id)
            .scalar()
        )
        sample_loading_order_driver_name = (
            session.query(FactShipment.driver_name)
            .filter(FactShipment.depot_id == depot.depot_id, FactShipment.driver_name.isnot(None))
            .order_by(FactShipment.source_shipment_id)
            .first()
        )
        sample_loading_order_end_datetime = (
            session.query(FactShipment.shipment_end_datetime)
            .filter(FactShipment.depot_id == depot.depot_id, FactShipment.shipment_end_datetime.isnot(None))
            .order_by(FactShipment.source_shipment_id)
            .first()
        )
        sample_spbu = session.query(MasterSPBU).filter(MasterSPBU.primary_depot_id == depot.depot_id, MasterSPBU.city.isnot(None)).first()
    sample_loading_order_driver_name = sample_loading_order_driver_name[0] if sample_loading_order_driver_name else None
    sample_loading_order_end_datetime = sample_loading_order_end_datetime[0] if sample_loading_order_end_datetime else None
    assert sample_loading_order_driver_name
    assert sample_loading_order_end_datetime
    filtered = client.get(f"/api/v1/foundation/overview?depot_id={depot.depot_id}")
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total_depot"] == 1
    assert filtered_payload["total_mt"] == expected_mt
    assert filtered_payload["total_spbu"] == expected_spbu
    assert filtered_payload["total_shipments"] == expected_shipments

    filtered_charts = client.get(f"/api/v1/foundation/charts?depot_id={depot.depot_id}")
    assert filtered_charts.status_code == 200
    assert "mt_by_vehicle_type_tag" in filtered_charts.json()

    available_dates = client.get(f"/api/v1/departure-intelligence/available-dates?depot_id={depot.depot_id}")
    assert available_dates.status_code == 200
    available_dates_payload = available_dates.json()
    assert available_dates_payload["available_dates"]
    assert available_dates_payload["min_date"] <= available_dates_payload["max_date"]

    with Session() as session:
        date_range = (
            session.query(func.min(FactShipment.operating_date), func.max(FactShipment.operating_date))
            .filter(FactShipment.depot_id == depot.depot_id, FactShipment.gate_out_datetime.isnot(None))
            .first()
        )
        expected_departure_observations = (
            session.query(FactShipmentSPBU.shipment_id, FactShipmentSPBU.spbu_id)
            .join(FactShipment, FactShipment.shipment_id == FactShipmentSPBU.shipment_id)
            .filter(
                FactShipment.depot_id == depot.depot_id,
                FactShipment.operating_date >= date_range[0],
                FactShipment.operating_date <= date_range[1],
                FactShipment.gate_out_datetime.isnot(None),
            )
            .distinct()
            .count()
        )
    departure = client.get(
        f"/api/v1/departure-intelligence/analysis?depot_id={depot.depot_id}&start_date={date_range[0]}&end_date={date_range[1]}&bucket_minutes=30"
    )
    assert departure.status_code == 200
    departure_payload = departure.json()
    assert departure_payload["page_name"] == "Depot Departure Time Intelligence"
    assert departure_payload["algorithm_version"] == "departure_profile.circular_gap_v1"
    assert departure_payload["summary"]["observation_count"] == expected_departure_observations
    assert departure_payload["summary"]["lo_gate_out_coverage_pct"] > 0
    assert departure_payload["profiles"]
    assert departure_payload["distribution"]
    assert departure_payload["weekday_heatmap"]["x_axis"]
    assert departure_payload["profiles"][0]["preferred_historical_departure_window"]
    assert all("spbu_tags" in profile for profile in departure_payload["profiles"])
    sampled_spbu_ids = {row["spbu_id"] for row in departure_payload["observations"]}
    assert all(profile["spbu_id"] in sampled_spbu_ids for profile in departure_payload["profiles"])
    tagged_profile = next((profile for profile in departure_payload["profiles"] if profile["spbu_tags"]), None)
    if tagged_profile:
        departure_tag_filter = client.get(
            f"/api/v1/departure-intelligence/analysis?depot_id={depot.depot_id}&start_date={date_range[0]}&end_date={date_range[1]}&bucket_minutes=30&profile_search={quote(tagged_profile['spbu_tags'][0])}"
        )
        assert departure_tag_filter.status_code == 200
        assert all(tagged_profile["spbu_tags"][0] in row["spbu_tags"] for row in departure_tag_filter.json()["profiles"])
    departure_spbu_sort = client.get(
        f"/api/v1/departure-intelligence/analysis?depot_id={depot.depot_id}&start_date={date_range[0]}&end_date={date_range[1]}&bucket_minutes=30&limit=10&sort_column=spbu_code&sort_direction=asc"
    )
    assert departure_spbu_sort.status_code == 200
    sorted_departure_codes = [row["spbu_code"] for row in departure_spbu_sort.json()["profiles"]]
    assert sorted_departure_codes == sorted(sorted_departure_codes)
    shift_config = [
        {"shift_id": "s1", "name": "Shift 1", "start_time": "00:00", "end_time": "05:59"},
        {"shift_id": "s2", "name": "Shift 2", "start_time": "06:00", "end_time": "11:59"},
        {"shift_id": "s3", "name": "Shift 3", "start_time": "12:00", "end_time": "17:59"},
        {"shift_id": "s4", "name": "Shift 4", "start_time": "18:00", "end_time": "23:59"},
    ]
    shift_response = client.post(
        "/api/v1/departure-intelligence/shift-analysis",
        json={
            "depot_id": depot.depot_id,
            "start_date": str(date_range[0]),
            "end_date": str(date_range[1]),
            "bucket_minutes": 30,
            "shifts": shift_config,
            "assignment_method": "DOMINANT_SHIFT",
            "sort_column": "spbu_code",
            "sort_direction": "asc",
        },
    )
    assert shift_response.status_code == 200
    shift_payload = shift_response.json()
    assert shift_payload["section"] == "Operational Shift Intelligence"
    assert shift_payload["assignment_method"] == "DOMINANT_SHIFT"
    assert shift_payload["summary"]["profile_count"] == departure_payload["summary"]["profile_count"]
    assert shift_payload["heatmap"]["x_axis"] == ["Shift 1", "Shift 2", "Shift 3", "Shift 4"]
    assert shift_payload["rows"]
    first_shift_row = shift_payload["rows"][0]
    assert sum(item["observation_count"] for item in first_shift_row["shift_distribution"]) == first_shift_row["observation_count"]
    assert round(sum(item["share_pct"] for item in first_shift_row["shift_distribution"])) in {99, 100, 101}
    hybrid_response = client.post(
        "/api/v1/departure-intelligence/shift-analysis",
        json={
            "depot_id": depot.depot_id,
            "start_date": str(date_range[0]),
            "end_date": str(date_range[1]),
            "bucket_minutes": 30,
            "shifts": shift_config,
            "assignment_method": "HYBRID_CONFIDENCE_AWARE",
        },
    )
    assert hybrid_response.status_code == 200
    assert hybrid_response.json()["rows"][0]["shift_distribution"][0]["score"] is not None
    save_response = client.post(
        "/api/v1/departure-intelligence/saved-shift-configurations",
        json={
            "name": "Medan baseline shifts",
            "depot_id": depot.depot_id,
            "start_date": str(date_range[0]),
            "end_date": str(date_range[1]),
            "bucket_minutes": 30,
            "assignment_method": "DOMINANT_SHIFT",
            "shift_config": shift_config,
            "ui_state": {"departure_limit": 25, "departure_offset": 0},
            "departure_analysis_snapshot": departure_payload,
            "shift_analysis_snapshot": shift_payload,
        },
    )
    assert save_response.status_code == 200
    saved_config = save_response.json()
    assert saved_config["name"] == "Medan baseline shifts"
    assert saved_config["shift_config"] == shift_config
    assert saved_config["departure_analysis_snapshot"]["page_name"] == "Depot Departure Time Intelligence"
    list_saved = client.get(f"/api/v1/departure-intelligence/saved-shift-configurations?depot_id={depot.depot_id}")
    assert list_saved.status_code == 200
    assert list_saved.json()["total"] == 1
    load_saved = client.get(f"/api/v1/departure-intelligence/saved-shift-configurations/{saved_config['id']}")
    assert load_saved.status_code == 200
    assert load_saved.json()["shift_analysis_snapshot"]["section"] == "Operational Shift Intelligence"
    delete_saved = client.delete(f"/api/v1/departure-intelligence/saved-shift-configurations/{saved_config['id']}")
    assert delete_saved.status_code == 200
    assert delete_saved.json()["status"] == "DELETED"
    invalid_shift_response = client.post(
        "/api/v1/departure-intelligence/shift-analysis",
        json={
            "depot_id": depot.depot_id,
            "start_date": str(date_range[0]),
            "end_date": str(date_range[1]),
            "bucket_minutes": 30,
            "shifts": [
                {"shift_id": "s1", "name": "Shift 1", "start_time": "00:00", "end_time": "07:00"},
                {"shift_id": "s2", "name": "Shift 2", "start_time": "06:00", "end_time": "23:59"},
            ],
            "assignment_method": "DOMINANT_SHIFT",
        },
    )
    assert invalid_shift_response.status_code == 400

    crud_list = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&search=SPBU&search_column=spbu_code")
    assert crud_list.status_code == 200
    crud_payload = crud_list.json()
    assert crud_payload["limit"] == 10
    assert len(crud_payload["rows"]) <= 10
    assert crud_payload["total"] <= expected_spbu
    spbu_sort_desc = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&sort_column=spbu_code&sort_direction=desc")
    assert spbu_sort_desc.status_code == 200
    spbu_codes = [row["spbu_code"] for row in spbu_sort_desc.json()["rows"]]
    assert spbu_codes == sorted(spbu_codes, reverse=True)
    for sort_column in ("address", "master_distance_km", "master_rth_min", "master_travel_time_min", "master_travel_time_sample_count"):
        spbu_visible_column_sort = client.get(
            f"/api/v1/master-crud/SPBU?limit=10&offset=0&sort_column={sort_column}&sort_direction=asc"
        )
        assert spbu_visible_column_sort.status_code == 200
        assert spbu_visible_column_sort.json()["total"] > 0
    spbu_tag_sort = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&sort_column=tag_project&sort_direction=asc")
    assert spbu_tag_sort.status_code == 200
    spbu_project_tags = [row["tag_project"] for row in spbu_tag_sort.json()["rows"] if row.get("tag_project")]
    assert spbu_project_tags == sorted(spbu_project_tags)
    address_update = client.put(f"/api/v1/master-crud/SPBU/{sample_spbu.spbu_id}", json={"address": "Alamat pengujian pencarian CRUD"})
    assert address_update.status_code == 200
    assert address_update.json()["record"]["city"] == "Alamat pengujian pencarian CRUD"
    sample_city = quote("Alamat pengujian pencarian CRUD")
    column_scoped_search = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&search={sample_city}&search_column=city")
    assert column_scoped_search.status_code == 200
    assert column_scoped_search.json()["total"] > 0
    wrong_column_search = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&search={sample_city}&search_column=spbu_code")
    assert wrong_column_search.status_code == 200
    assert wrong_column_search.json()["total"] == 0
    crud_all = client.get(f"/api/v1/master-crud/SPBU?limit=10000&offset=0&depot_id={depot.depot_id}")
    assert crud_all.status_code == 200
    spbu_rows = crud_all.json()["rows"]
    assert len(spbu_rows) == expected_spbu
    assert "tag_project" in spbu_rows[0]
    assert "tag_vehicle_class" in spbu_rows[0]
    assert all(row["tag_vehicle_class"] == row["vehicle_type_tag"] for row in spbu_rows)
    assert all(isinstance(row["tag_vehicle_class"], int) for row in spbu_rows if row.get("tag_vehicle_class") is not None)
    assert any("," in row["tag_project"] for row in spbu_rows if row.get("tag_project"))
    spbu_vehicle_class_search = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&search=32&search_column=tag_vehicle_class")
    assert spbu_vehicle_class_search.status_code == 200
    assert spbu_vehicle_class_search.json()["total"] > 0
    spbu_tag_search = client.get(f"/api/v1/master-crud/SPBU?limit=10&offset=0&depot_id={depot.depot_id}&search=Darat&search_column=tag_project")
    assert spbu_tag_search.status_code == 200
    assert spbu_tag_search.json()["total"] > 0
    update_spbu_tags = client.put(f"/api/v1/master-crud/SPBU/{sample_spbu.spbu_id}", json={"tag_project": "CRUD SPBU Tag, Darat"})
    assert update_spbu_tags.status_code == 200
    assert "CRUD SPBU Tag" in update_spbu_tags.json()["record"]["tag_project"]
    spbu_crud_tag_search = client.get("/api/v1/master-crud/SPBU?limit=10&offset=0&search=CRUD%20SPBU%20Tag&search_column=tag_project")
    assert spbu_crud_tag_search.status_code == 200
    assert spbu_crud_tag_search.json()["total"] > 0
    mt_with_tags = client.get("/api/v1/master-crud/MOBIL_TANGKI?limit=10000&offset=0")
    assert mt_with_tags.status_code == 200
    mt_rows = mt_with_tags.json()["rows"]
    assert "tag_project" in mt_rows[0]
    assert "tag_vehicle_class" in mt_rows[0]
    assert all(row["tag_vehicle_class"] == row["vehicle_type_tag"] for row in mt_rows)
    assert all(isinstance(row["tag_vehicle_class"], int) for row in mt_rows if row.get("tag_vehicle_class") is not None)
    assert any("," in row["tag_project"] for row in mt_rows if row.get("tag_project"))
    mt_depot_sort = client.get("/api/v1/master-crud/MOBIL_TANGKI?limit=10&offset=0&sort_column=depot_id&sort_direction=asc")
    assert mt_depot_sort.status_code == 200
    assert mt_depot_sort.json()["total"] > 0
    mt_vehicle_class_search = client.get("/api/v1/master-crud/MOBIL_TANGKI?limit=10&offset=0&search=24&search_column=tag_vehicle_class")
    assert mt_vehicle_class_search.status_code == 200
    assert mt_vehicle_class_search.json()["total"] > 0
    mt_tag_search = client.get("/api/v1/master-crud/MOBIL_TANGKI?limit=10&offset=0&search=Poltaplus&search_column=tag_project")
    assert mt_tag_search.status_code == 200
    assert mt_tag_search.json()["total"] > 0
    update_mt_tags = client.put(f"/api/v1/master-crud/MOBIL_TANGKI/{mt_rows[0]['mt_id']}", json={"tag_project": "CRUD MT Tag, All In"})
    assert update_mt_tags.status_code == 200
    assert "CRUD MT Tag" in update_mt_tags.json()["record"]["tag_project"]
    mt_crud_tag_search = client.get("/api/v1/master-crud/MOBIL_TANGKI?limit=10&offset=0&search=CRUD%20MT%20Tag&search_column=tag_project")
    assert mt_crud_tag_search.status_code == 200
    assert mt_crud_tag_search.json()["total"] > 0
    crud_loading_orders = client.get(f"/api/v1/master-crud/LOADING_ORDER?limit=10&offset=0&depot_id={depot.depot_id}")
    assert crud_loading_orders.status_code == 200
    lo_payload = crud_loading_orders.json()
    assert lo_payload["limit"] == 10
    assert lo_payload["total"] == expected_loading_orders
    assert len(lo_payload["rows"]) <= 10
    assert lo_payload["rows"][0]["loading_order_number"]
    assert "vehicle_registration" in lo_payload["rows"][0]
    assert "validation_datetime" in lo_payload["rows"][0]
    assert "validation_date" in lo_payload["rows"][0]
    assert "validation_time" in lo_payload["rows"][0]
    assert "driver_name" in lo_payload["rows"][0]
    assert "driver_nip" in lo_payload["rows"][0]
    assert "assistant_name" in lo_payload["rows"][0]
    assert "assistant_nip" in lo_payload["rows"][0]
    assert "shipment_end_datetime" in lo_payload["rows"][0]
    assert "shipment_end_date" in lo_payload["rows"][0]
    assert "shipment_end_time" in lo_payload["rows"][0]
    assert any(row["vehicle_registration"] for row in lo_payload["rows"])
    assert any(row["validation_date"] for row in lo_payload["rows"])
    assert any(row["validation_time"] for row in lo_payload["rows"])
    crud_loading_order_search = client.get(f"/api/v1/master-crud/LOADING_ORDER?search={sample_loading_order.loading_order_number}&search_column=loading_order_number")
    assert crud_loading_order_search.status_code == 200
    assert crud_loading_order_search.json()["total"] == 1
    crud_loading_order_vehicle_search = client.get(f"/api/v1/master-crud/LOADING_ORDER?search={sample_loading_order_vehicle_registration}&search_column=vehicle_registration")
    assert crud_loading_order_vehicle_search.status_code == 200
    assert crud_loading_order_vehicle_search.json()["total"] > 0
    crud_loading_order_vehicle_sort = client.get("/api/v1/master-crud/LOADING_ORDER?limit=10&offset=0&sort_column=vehicle_registration&sort_direction=desc")
    assert crud_loading_order_vehicle_sort.status_code == 200
    lo_vehicle_registrations = [row["vehicle_registration"] for row in crud_loading_order_vehicle_sort.json()["rows"]]
    assert lo_vehicle_registrations == sorted(lo_vehicle_registrations, reverse=True)
    crud_loading_order_depot_sort = client.get("/api/v1/master-crud/LOADING_ORDER?limit=10&offset=0&sort_column=depot_id&sort_direction=asc")
    assert crud_loading_order_depot_sort.status_code == 200
    assert crud_loading_order_depot_sort.json()["total"] > 0
    crud_loading_order_validation_search = client.get(f"/api/v1/master-crud/LOADING_ORDER?search={sample_loading_order_validation_datetime.date().isoformat()}&search_column=validation_date")
    assert crud_loading_order_validation_search.status_code == 200
    assert crud_loading_order_validation_search.json()["total"] > 0
    crud_loading_order_driver_search = client.get(f"/api/v1/master-crud/LOADING_ORDER?search={quote(sample_loading_order_driver_name)}&search_column=driver_name")
    assert crud_loading_order_driver_search.status_code == 200
    assert crud_loading_order_driver_search.json()["total"] > 0
    crud_loading_order_end_search = client.get(f"/api/v1/master-crud/LOADING_ORDER?search={sample_loading_order_end_datetime.date().isoformat()}&search_column=shipment_end_date")
    assert crud_loading_order_end_search.status_code == 200
    assert crud_loading_order_end_search.json()["total"] > 0

    create_product = client.post("/api/v1/master-crud/PRODUCT", json={"product_name": "TEST PRODUCT CRUD"})
    assert create_product.status_code == 200
    product_id = create_product.json()["record"]["product_id"]
    update_product = client.put(f"/api/v1/master-crud/PRODUCT/{product_id}", json={"product_name": "TEST PRODUCT CRUD UPDATED", "active_status": "INACTIVE"})
    assert update_product.status_code == 200
    assert update_product.json()["record"]["active_status"] == "INACTIVE"
    delete_product = client.delete(f"/api/v1/master-crud/PRODUCT/{product_id}")
    assert delete_product.status_code == 200
    deleted_product_list = client.get("/api/v1/master-crud/PRODUCT?search=TEST%20PRODUCT%20CRUD%20UPDATED&search_column=product_name")
    assert deleted_product_list.status_code == 200
    assert deleted_product_list.json()["total"] == 0
    recreate_product = client.post("/api/v1/master-crud/PRODUCT", json={"product_name": "TEST PRODUCT CRUD UPDATED"})
    assert recreate_product.status_code == 200
    assert recreate_product.json()["record"]["product_id"] == product_id
    assert recreate_product.json()["record"]["active_status"] == "ACTIVE"

    create_mt = client.post(
        "/api/v1/master-crud/MOBIL_TANGKI",
        json={"depot_id": depot.depot_id, "vehicle_name_raw": "BTESTCRUD-16KL", "vehicle_registration": "BTESTCRUD", "capacity_label": "16KL", "vehicle_type_tag": "16"},
    )
    assert create_mt.status_code == 200
    mt_id = create_mt.json()["record"]["mt_id"]
    assert create_mt.json()["record"]["tag_vehicle_class"] == 16
    delete_mt = client.delete(f"/api/v1/master-crud/MOBIL_TANGKI/{mt_id}")
    assert delete_mt.status_code == 200
    deleted_mt_list = client.get("/api/v1/master-crud/MOBIL_TANGKI?search=BTESTCRUD&search_column=vehicle_registration")
    assert deleted_mt_list.status_code == 200
    assert deleted_mt_list.json()["total"] == 0
    recreate_mt = client.post(
        "/api/v1/master-crud/MOBIL_TANGKI",
        json={"depot_id": depot.depot_id, "vehicle_name_raw": "BTESTCRUD-24KL", "vehicle_registration": "BTESTCRUD", "capacity_label": "24KL", "vehicle_type_tag": "24"},
    )
    assert recreate_mt.status_code == 200
    assert recreate_mt.json()["record"]["mt_id"] == mt_id
    assert recreate_mt.json()["record"]["active_status"] == "ACTIVE"
    assert recreate_mt.json()["record"]["capacity_label"] == "24KL"
    with Session() as session:
        sync_depot = session.query(MasterDepot).filter(MasterDepot.depot_id == depot.depot_id).first()
        sync_product = session.query(MasterProduct).filter(MasterProduct.product_name != "TEST PRODUCT CRUD UPDATED").first()
        sync_tag = session.query(MasterTag).first()
        sync_depot_id = sync_depot.depot_id
        sync_product_id = sync_product.product_id
        sync_tag_id = sync_tag.tag_id
        session.add(
            FactShipment(
                shipment_id="sync_deleted_source_shipment",
                source_shipment_id="sync_deleted_source_shipment",
                depot_id=depot.depot_id,
            )
        )
        session.add(
            FactLoadingOrderLine(
                loading_order_number="SYNC-DELETED-SOURCE-LO",
                source_depot_name="SYNC DELETED SOURCE DEPOT",
                shipment_id="sync_deleted_source_shipment",
                source_product_name="SYNC DELETED SOURCE PRODUCT",
                status="DELETED",
            )
        )
        session.add(
            FactLoadingOrderLine(
                loading_order_number="SYNC-ACTIVE-SOURCE-ALIAS-LO",
                source_depot_name="SYNC ACTIVE SOURCE ALIAS",
                shipment_id="sync_deleted_source_shipment",
                status="ACTIVE",
            )
        )
        session.add(
            MasterMT(
                mt_id="sync_deleted_source_mt",
                vehicle_name_raw="SYNC DELETED SOURCE MT",
                project_tag_raw="SYNC DELETED SOURCE TAG",
                active_status="DELETED",
            )
        )
        session.add(
            MasterSPBU(
                spbu_id="sync_deleted_source_spbu",
                spbu_code="SYNC_DELETED_SOURCE_SPBU",
                project_tag_raw="SYNC DELETED SOURCE TAG",
                active_status="DELETED",
            )
        )
        session.commit()

    assert client.delete(f"/api/v1/master-crud/DEPOT/{sync_depot_id}").status_code == 200
    depot_sync = client.post("/api/v1/master-crud/DEPOT/sync")
    assert depot_sync.status_code == 400
    assert "managed manually" in depot_sync.json()["detail"]
    listed_depots_after_sync = client.get("/api/v1/master/depots")
    assert listed_depots_after_sync.status_code == 200
    assert all(row["depot_id"] != sync_depot_id for row in listed_depots_after_sync.json())

    assert client.delete(f"/api/v1/master-crud/PRODUCT/{sync_product_id}").status_code == 200
    product_sync = client.post("/api/v1/master-crud/PRODUCT/sync")
    assert product_sync.status_code == 200
    assert product_sync.json()["reactivated"] >= 1
    listed_products_after_sync = client.get("/api/v1/master/products")
    assert listed_products_after_sync.status_code == 200
    assert any(row["product_id"] == sync_product_id for row in listed_products_after_sync.json())

    assert client.delete(f"/api/v1/master-crud/TAG/{sync_tag_id}").status_code == 200
    tag_sync = client.post("/api/v1/master-crud/TAG/sync")
    assert tag_sync.status_code == 200
    assert tag_sync.json()["reactivated"] >= 1
    listed_tags_after_sync = client.get("/api/v1/master/tags")
    assert listed_tags_after_sync.status_code == 200
    assert any(row["tag_id"] == sync_tag_id for row in listed_tags_after_sync.json())

    with Session() as session:
        deleted_product = session.get(MasterProduct, product_id)
        synced_depot = session.get(MasterDepot, sync_depot_id)
        synced_product = session.get(MasterProduct, sync_product_id)
        synced_tag = session.get(MasterTag, sync_tag_id)
        deleted_source_depot = session.query(MasterDepot).filter(MasterDepot.depot_name == "SYNC DELETED SOURCE DEPOT").first()
        active_source_alias_depot = session.query(MasterDepot).filter(MasterDepot.depot_name == "SYNC ACTIVE SOURCE ALIAS").first()
        deleted_source_product = session.query(MasterProduct).filter(MasterProduct.product_name == "SYNC DELETED SOURCE PRODUCT").first()
        deleted_source_tag = session.query(MasterTag).filter(MasterTag.tag_value == "SYNC DELETED SOURCE TAG").first()
    assert deleted_product.active_status == "ACTIVE"
    assert synced_depot.active_status == "DELETED"
    assert synced_product.active_status == "ACTIVE"
    assert synced_tag.active_status == "ACTIVE"
    assert deleted_source_depot is None
    assert active_source_alias_depot is None
    assert deleted_source_product is None
    assert deleted_source_tag is None
    app.dependency_overrides.clear()
