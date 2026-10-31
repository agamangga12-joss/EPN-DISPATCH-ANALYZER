from pathlib import Path
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.compatibility import evaluate_mt_spbu_compatibility
from app.import_jobs import claim_next_import, process_import
from app.importer import ImportProcessor
from app.models import (
    Base,
    BridgeMTTag,
    BridgeSPBUTag,
    DataQualityIssue,
    FactLoadingOrderLine,
    FactShipment,
    ImportAudit,
    MasterDepot,
    MasterMT,
    MasterProduct,
    MasterSPBU,
    StgLoadingOrder,
    StgMT,
    StgSPBU,
    MasterTag,
    MasterTagType,
)
from app.normalization import make_id
from app.tag_consistency import build_tag_consistency_payload

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DIR = ROOT / "example data"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session


def test_phase0_imports_real_workbooks(db_session) -> None:
    processor = ImportProcessor(db_session)
    processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
    processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")
    processor.import_loading_order(EXAMPLE_DIR / "masterdata_LO.xlsx")

    assert db_session.scalar(select(func.count()).select_from(MasterMT)) == 162
    assert db_session.scalar(select(func.count()).select_from(MasterSPBU)) == 583
    assert db_session.scalar(select(func.count()).select_from(FactLoadingOrderLine)) == 4462
    assert db_session.scalar(select(func.count()).select_from(FactLoadingOrderLine)) == db_session.scalar(
        select(func.count()).select_from(
            select(FactLoadingOrderLine.loading_order_number, FactLoadingOrderLine.source_depot_name).distinct().subquery()
        )
    )
    assert db_session.scalar(select(func.count()).select_from(FactShipment)) == 1876
    assert db_session.scalar(select(func.count()).select_from(StgMT)) == 162
    assert db_session.scalar(select(func.count()).select_from(StgSPBU)) == 583
    assert db_session.scalar(select(func.count()).select_from(StgLoadingOrder)) == 4462


def test_spbu_import_preserves_decimal_comma_coordinate(db_session, tmp_path) -> None:
    csv_path = tmp_path / "spbu_decimal_comma_coordinate.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Nama SPBU,Coordinate,Vehicle Type tag,Project tag",
                '11201199,"5,19182389869645 96,4368560343681",24,All In',
            ]
        ),
        encoding="utf-8",
    )

    processor = ImportProcessor(db_session)
    processor.import_master_spbu(csv_path, sheet_name="SPBU")

    spbu = db_session.scalar(select(MasterSPBU).where(MasterSPBU.spbu_code == "11201199"))
    assert spbu is not None
    assert spbu.source_coordinate == "5.19182389869645 96.4368560343681"
    assert spbu.latitude == 5.19182389869645
    assert spbu.longitude == 96.4368560343681


def test_loading_order_model_preserves_multi_product_shipments(db_session) -> None:
    processor = ImportProcessor(db_session)
    processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
    processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")
    processor.import_loading_order(EXAMPLE_DIR / "masterdata_LO.xlsx")

    shipment = db_session.scalar(select(FactShipment).where(FactShipment.source_shipment_id == "2678638"))
    assert shipment is not None
    assert shipment.shipment_id == "2678638"
    assert shipment.source_shipment_id == "2678638"
    lines = db_session.scalars(select(FactLoadingOrderLine).where(FactLoadingOrderLine.shipment_id == shipment.shipment_id)).all()
    assert len(lines) == 2
    assert len({line.loading_order_number for line in lines}) == 2
    assert {line.source_depot_name for line in lines} == {"FUEL TERMINAL MEDAN GROUP"}
    assert {line.source_product_name for line in lines} == {"PERTALITE", "BIOSOLAR B40"}
    assert {line.shipment_id for line in lines} == {"2678638"}
    assert all(line.loading_order_number != shipment.source_shipment_id for line in lines)


def test_loading_order_number_can_repeat_across_depots(db_session, tmp_path) -> None:
    csv_path = tmp_path / "lo_duplicate_number_different_depot.csv"
    csv_path.write_text(
        "\n".join(
            [
                "shipment_id,loading_order_number,tbbm,kode_depot,nopol,nama_spbu,produk,quantity,status",
                "SHP-A,LO-001,DEPOT A,DA,B1234AA,SPBU-A,PERTALITE,1000,OPEN",
                "SHP-B,LO-001,DEPOT B,DB,B1234AA,SPBU-B,PERTALITE,2000,OPEN",
            ]
        ),
        encoding="utf-8",
    )

    processor = ImportProcessor(db_session)
    processor.import_loading_order(csv_path)

    lines = db_session.scalars(select(FactLoadingOrderLine).where(FactLoadingOrderLine.loading_order_number == "LO-001")).all()
    assert len(lines) == 2
    assert {line.source_depot_name for line in lines} == {"DEPOT A", "DEPOT B"}


def test_v2_import_identity_and_tags_are_scoped_by_depot(db_session, tmp_path) -> None:
    db_session.add_all(
        [
            MasterDepot(depot_id="DEPOT-A", depot_code="DA", depot_name="Depot A", active_status="ACTIVE"),
            MasterDepot(depot_id="DEPOT-B", depot_code="DB", depot_name="Depot B", active_status="ACTIVE"),
        ]
    )
    db_session.commit()
    processor = ImportProcessor(db_session)

    mt_path = tmp_path / "mt.csv"
    mt_path.write_text(
        "depot_id,vehicle_registration,vehicle_name_raw,capacity_label,project_tag\n"
        "DEPOT-A,B9067WFU,B9067WFU - 24 KL,24KL,All In\n"
        "DEPOT-B,B9067WFU,B9067WFU - 24 KL,24KL,Singkil\n",
        encoding="utf-8",
    )
    processor.import_master_mt(mt_path, require_depot_id=True)
    mts = db_session.scalars(select(MasterMT).where(MasterMT.vehicle_registration == "B9067WFU")).all()
    assert {mt.mt_id for mt in mts} == {
        make_id("mt", "DEPOT-A", "B9067WFU"),
        make_id("mt", "DEPOT-B", "B9067WFU"),
    }

    mt_update_path = tmp_path / "mt_update.csv"
    mt_update_path.write_text(
        'depot_id,vehicle_registration,vehicle_name_raw,project_tag\nDEPOT-A,B9067WFU,B9067WFU - 24 KL,"NON-PTO,Gunung"\n',
        encoding="utf-8",
    )
    processor.import_master_mt(mt_update_path, require_depot_id=True)
    depot_a_mt_id = make_id("mt", "DEPOT-A", "B9067WFU")
    depot_a_tags = set(
        db_session.scalars(
            select(MasterTag.tag_value)
            .join(BridgeMTTag, BridgeMTTag.tag_id == MasterTag.tag_id)
            .where(BridgeMTTag.mt_id == depot_a_mt_id)
        ).all()
    )
    assert depot_a_tags == {"NON-PTO", "Gunung"}

    spbu_path = tmp_path / "spbu.csv"
    spbu_path.write_text(
        "depot_id,spbu_code,spbu_name,project_tag\nDEPOT-A,SPBU-01,SPBU A,Gunung\nDEPOT-B,SPBU-01,SPBU B,Singkil\n",
        encoding="utf-8",
    )
    processor.import_master_spbu(spbu_path, require_depot_id=True)
    spbus = db_session.scalars(select(MasterSPBU).where(MasterSPBU.spbu_code == "SPBU-01")).all()
    assert {spbu.spbu_id for spbu in spbus} == {
        make_id("spbu", "DEPOT-A", "SPBU-01"),
        make_id("spbu", "DEPOT-B", "SPBU-01"),
    }

    lo_path = tmp_path / "lo.csv"
    lo_path.write_text(
        "depot_id,shipment_id,loading_order_number,source_depot_name,vehicle_registration,source_spbu_code,source_product_name,quantity\n"
        "DEPOT-A,SHP-A,LO-001,Depot A,B9067WFU,SPBU-01,PERTALITE,8\n"
        "DEPOT-B,SHP-B,LO-001,Depot B,B9067WFU,SPBU-01,PERTALITE,8\n",
        encoding="utf-8",
    )
    processor.import_loading_order(lo_path, require_depot_id=True)
    lines = db_session.scalars(select(FactLoadingOrderLine).where(FactLoadingOrderLine.loading_order_number == "LO-001")).all()
    assert {line.loading_order_id for line in lines} == {
        make_id("lo", "DEPOT-A", "LO-001"),
        make_id("lo", "DEPOT-B", "LO-001"),
    }


@pytest.mark.parametrize(
    ("domain", "content"),
    [
        ("MOBIL_TANGKI", "depot_id,vehicle_registration\nDEPOT-UNKNOWN,B1234AA\n"),
        ("SPBU", "depot_id,spbu_code\nDEPOT-UNKNOWN,SPBU-01\n"),
        (
            "LOADING_ORDER",
            "depot_id,shipment_id,loading_order_number,source_depot_name\n"
            "DEPOT-UNKNOWN,SHP-01,LO-01,Unknown Depot\n",
        ),
    ],
)
def test_v2_import_rejects_unknown_depot_id(db_session, tmp_path, domain, content) -> None:
    csv_path = tmp_path / f"{domain.lower()}_unknown_depot.csv"
    csv_path.write_text(content, encoding="utf-8")
    processor = ImportProcessor(db_session)

    with pytest.raises(ValueError, match="Buat Depot terlebih dahulu") as exc_info:
        if domain == "MOBIL_TANGKI":
            processor.import_master_mt(csv_path, require_depot_id=True)
        elif domain == "SPBU":
            processor.import_master_spbu(csv_path, require_depot_id=True)
        else:
            processor.import_loading_order(csv_path, require_depot_id=True)

    assert "DEPOT-UNKNOWN" in str(exc_info.value)
    assert db_session.scalar(select(func.count()).select_from(MasterDepot)) == 0


def test_v2_import_rejects_blank_depot_id(db_session, tmp_path) -> None:
    csv_path = tmp_path / "mt_blank_depot.csv"
    csv_path.write_text("depot_id,vehicle_registration\n,B1234AA\n", encoding="utf-8")

    with pytest.raises(ValueError, match="depot_id kosong pada baris 2") as exc_info:
        ImportProcessor(db_session).import_master_mt(csv_path, require_depot_id=True)

    assert "Master Data > Depot" in str(exc_info.value)


def test_durable_import_job_is_claimed_and_published(db_session, tmp_path) -> None:
    db_session.add(MasterDepot(depot_id="DEPOT-JOB", depot_code="DJ", depot_name="Depot Job", active_status="ACTIVE"))
    csv_path = tmp_path / "queued_mt.csv"
    csv_path.write_text(
        "depot_id,name,project_tag\nDEPOT-JOB,BJOB123 - 16 KL,Job Tag\n",
        encoding="utf-8",
    )
    audit = ImportAudit(
        import_id="imp_durable_test",
        domain="MOBIL_TANGKI",
        filename=csv_path.name,
        sheet_name="Mobil Tangki",
        stored_path=str(csv_path),
        status="QUEUED",
        mapping_version="phase0.v2",
    )
    db_session.add(audit)
    db_session.commit()

    assert claim_next_import(db_session) == audit.import_id
    assert db_session.get(ImportAudit, audit.import_id).status == "PROCESSING"
    process_import(db_session, audit.import_id)

    published = db_session.get(ImportAudit, audit.import_id)
    assert published.status == "PUBLISHED"
    assert published.processed_rows == 1
    assert published.completed_at is not None
    assert db_session.get(MasterMT, make_id("mt", "DEPOT-JOB", "BJOB123")) is not None
    assert not csv_path.exists()


def test_loading_order_import_stores_personnel_on_shipment(db_session, tmp_path) -> None:
    csv_path = tmp_path / "lo_shipment_personnel.csv"
    csv_path.write_text(
        "\n".join(
            [
                "shipment_id,loading_order_number,tbbm,kode_depot,nopol,nama_spbu,produk,quantity,status,supir,nip_supir,kernet,nip_kernet,date_end_shipment,jam_end_shipment",
                "SHP-PERSONNEL,LO-PERSONNEL-1,DEPOT A,DA,B1234AA,SPBU-A,PERTALITE,8,Terkirim,Driver A,DRV001,Kernet A,KRN001,2026-08-13,05:16:41",
                "SHP-PERSONNEL,LO-PERSONNEL-2,DEPOT A,DA,B1234AA,SPBU-B,BIOSOLAR B50,8,Terkirim,Driver A,DRV001,Kernet A,KRN001,2026-08-13,05:16:41",
            ]
        ),
        encoding="utf-8",
    )

    processor = ImportProcessor(db_session)
    processor.import_loading_order(csv_path)

    shipment = db_session.get(FactShipment, "SHP-PERSONNEL")
    assert shipment is not None
    assert shipment.driver_name == "Driver A"
    assert shipment.driver_nip == "DRV001"
    assert shipment.assistant_name == "Kernet A"
    assert shipment.assistant_nip == "KRN001"
    assert shipment.shipment_end_datetime.date().isoformat() == "2026-08-13"
    assert shipment.shipment_end_datetime.time().replace(microsecond=0).isoformat() == "05:16:41"


def test_product_names_with_commas_are_single_products(db_session) -> None:
    processor = ImportProcessor(db_session)
    processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
    processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")
    processor.import_loading_order(EXAMPLE_DIR / "masterdata_LO.xlsx")

    products = {product.product_name for product in db_session.scalars(select(MasterProduct)).all()}
    assert "PERTAMAX,BULK" in products
    assert "PERTAMAX TURBO, BULK" in products
    assert "BULK" not in products


def test_tag_links_and_aliases_are_built(db_session) -> None:
    processor = ImportProcessor(db_session)
    processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
    processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")
    processor.import_loading_order(EXAMPLE_DIR / "masterdata_LO.xlsx")

    assert db_session.scalar(select(func.count()).select_from(BridgeMTTag)) > 0
    assert db_session.scalar(select(func.count()).select_from(BridgeSPBUTag)) > 0


def test_mapping_statuses_and_quality_issues_are_visible(db_session) -> None:
    processor = ImportProcessor(db_session)
    processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
    processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")
    processor.import_loading_order(EXAMPLE_DIR / "masterdata_LO.xlsx")

    matched_mt = db_session.scalar(select(func.count()).select_from(FactShipment).where(FactShipment.vehicle_mapping_status == "MATCHED"))
    unmatched_mt = db_session.scalar(select(func.count()).select_from(FactShipment).where(FactShipment.vehicle_mapping_status == "UNMATCHED"))
    assert matched_mt + unmatched_mt == 1876
    assert unmatched_mt > 0
    assert db_session.scalar(select(func.count()).select_from(DataQualityIssue)) > 0


def test_compatibility_explanation_is_structured(db_session) -> None:
    processor = ImportProcessor(db_session)
    processor.import_master_mt(EXAMPLE_DIR / "master data MT.xlsx")
    processor.import_master_spbu(EXAMPLE_DIR / "master data spbu.xlsx")

    mt = db_session.scalar(select(MasterMT))
    spbu = db_session.scalar(select(MasterSPBU))
    result = evaluate_mt_spbu_compatibility(db_session, mt.mt_id, spbu.spbu_id)
    assert set(result) >= {"compatible", "vehicle_type_check", "project_tag_check", "failed_rules", "explanation"}


def test_tag_consistency_uses_vehicle_class_limit_and_tag_subset(db_session) -> None:
    project_type_id = make_id("tagtype", "PROJECT")
    vehicle_type_id = make_id("tagtype", "VEHICLE_CLASS")
    db_session.add_all(
        [
            MasterTagType(tag_type_id=project_type_id, code="PROJECT", name="Project"),
            MasterTagType(tag_type_id=vehicle_type_id, code="VEHICLE_CLASS", name="Vehicle Class"),
            MasterMT(mt_id="mt_small", vehicle_name_raw="B 9123 ABC-16KL", vehicle_registration="B9123ABC", vehicle_type_tag=16),
            MasterMT(mt_id="mt_large", vehicle_name_raw="B 9999 ABC-32KL", vehicle_registration="B9999ABC", vehicle_type_tag=32),
            MasterMT(mt_id="mt_missing_project", vehicle_name_raw="B 1111 ABC-16KL", vehicle_registration="B1111ABC", vehicle_type_tag=16),
            MasterSPBU(spbu_id="spbu_24", spbu_code="74.951.01", spbu_name="74.951.01", vehicle_type_tag=24),
        ]
    )
    tags = {
        "ALLIN": MasterTag(tag_id="tag_allin", tag_type_id=project_type_id, tag_value="ALL IN", normalized_tag="ALLIN"),
        "GUNUNG": MasterTag(tag_id="tag_gunung", tag_type_id=project_type_id, tag_value="GUNUNG", normalized_tag="GUNUNG"),
        "KOTA": MasterTag(tag_id="tag_kota", tag_type_id=project_type_id, tag_value="KOTA", normalized_tag="KOTA"),
    }
    db_session.add_all(tags.values())
    db_session.add_all(
        [
            BridgeSPBUTag(spbu_id="spbu_24", tag_id="tag_allin"),
            BridgeSPBUTag(spbu_id="spbu_24", tag_id="tag_gunung"),
            BridgeMTTag(mt_id="mt_small", tag_id="tag_allin"),
            BridgeMTTag(mt_id="mt_small", tag_id="tag_gunung"),
            BridgeMTTag(mt_id="mt_small", tag_id="tag_kota"),
            BridgeMTTag(mt_id="mt_large", tag_id="tag_allin"),
            BridgeMTTag(mt_id="mt_large", tag_id="tag_gunung"),
            BridgeMTTag(mt_id="mt_missing_project", tag_id="tag_allin"),
        ]
    )
    db_session.add_all(
        [
            FactShipment(shipment_id="shipment_match", source_shipment_id="shipment_match", operating_date=date(2026, 8, 12), mt_id="mt_small", vehicle_registration="b 9123 abc", vehicle_mapping_status="MATCHED"),
            FactShipment(shipment_id="shipment_vehicle_mismatch", source_shipment_id="shipment_vehicle_mismatch", operating_date=date(2026, 8, 12), mt_id="mt_large", vehicle_registration="B9999ABC", vehicle_mapping_status="MATCHED"),
            FactShipment(shipment_id="shipment_tag_mismatch", source_shipment_id="shipment_tag_mismatch", operating_date=date(2026, 8, 12), mt_id="mt_missing_project", vehicle_registration="B1111ABC", vehicle_mapping_status="MATCHED"),
            FactLoadingOrderLine(loading_order_number="LO-MATCH", source_depot_name="DEPOT", shipment_id="shipment_match", spbu_id="spbu_24", spbu_mapping_status="MATCHED"),
            FactLoadingOrderLine(loading_order_number="LO-VEHICLE-MISMATCH", source_depot_name="DEPOT", shipment_id="shipment_vehicle_mismatch", spbu_id="spbu_24", spbu_mapping_status="MATCHED"),
            FactLoadingOrderLine(loading_order_number="LO-TAG-MISMATCH", source_depot_name="DEPOT", shipment_id="shipment_tag_mismatch", spbu_id="spbu_24", spbu_mapping_status="MATCHED"),
        ]
    )
    db_session.commit()

    payload = build_tag_consistency_payload(db_session)
    rows = {row["loading_order_number"]: row for row in payload["rows"]}

    assert rows["LO-MATCH"]["overall_status"] == "MATCH"
    assert rows["LO-MATCH"]["details"][0]["reason"] == "16 <= 24."
    assert rows["LO-VEHICLE-MISMATCH"]["overall_status"] == "MISMATCH"
    assert rows["LO-VEHICLE-MISMATCH"]["vehicle_class_result"] == "MISMATCH"
    assert rows["LO-TAG-MISMATCH"]["overall_status"] == "MISMATCH"
    project_detail = next(detail for detail in rows["LO-TAG-MISMATCH"]["details"] if detail["tag_type"] == "PROJECT")
    assert project_detail["missing_tags"] == ["GUNUNG"]
    assert payload["summary"]["matched"] == 1
    assert payload["summary"]["mismatch"] == 2
    assert {"name": "Project", "value": 1} in payload["summary"]["mismatch_by_tag_type"]
    assert {"name": "GUNUNG", "value": 1} in payload["summary"]["mismatch_by_tag_value"]
    assert {"name": "Vehicle Class > Max 24", "value": 1} in payload["summary"]["mismatch_by_tag_value"]
