from sqlalchemy import select

from app.models import BridgeMTTag, BridgeSPBUTag, MasterTag, PredictionMTCandidate
from app.phase6_inference import predict_mt_candidates
from app.phase6_service import get_prediction_shipment_candidates
from test_phase6_prediction_assignment import make_session, run_prediction, seed


def test_candidate_snapshot_identifies_missing_tag_despite_partial_overlap_and_capacity_failure():
    Session = make_session()
    with Session() as db:
        seed(db)
        db.add_all([
            MasterTag(tag_id="COMMON", tag_value="Common access", normalized_tag="COMMON"),
            MasterTag(tag_id="REQUIRED", tag_value="Special access", normalized_tag="REQUIRED"),
        ])
        db.commit()
        db.add_all([
            BridgeMTTag(mt_id="T1", tag_id="COMMON"),
            BridgeSPBUTag(spbu_id="A", tag_id="COMMON"),
            BridgeSPBUTag(spbu_id="A", tag_id="REQUIRED"),
        ])
        db.commit()
        result = predict_mt_candidates(
            db, depot_id="D1",
            shipments=[{"predicted_shipment_id": "S1", "lines": [{"spbu_id": "A", "order_quantity_kl": 16}]}],
            availability=[{"vehicle_id": "T1", "initial_available_datetime": "2026-08-22T00:00:00Z"}],
            vehicle_compatibility_mode="MT_CAPACITY_LE_SPBU_LIMIT",
        )["S1"][0]
        assert result["compatibility_status"] == "FAIL"
        explanation = result["explanation"]
        assert explanation["failed_rules"] == ["PROJECT_TAGS", "SHIPMENT_MT_CAPACITY_MISMATCH"]
        check = explanation["master_checks"][0]
        assert check["spbu_code"] == "SPBU-A"
        assert check["matched_tags"] == ["Common access"]
        assert check["available_tags"] == ["Common access"]
        assert check["missing_tags"] == ["Special access"]
        assert check["required_tags"] == ["Common access", "Special access"]
        assert check["mt_vehicle_class"] == 8
        assert check["spbu_vehicle_class"] == 8
        assert explanation["mt_capacity_kl"] == 8
        assert explanation["shipment_total_kl"] == 16


def test_saved_evidence_survives_master_changes_and_legacy_checks_are_separate():
    Session = make_session()
    with Session() as db:
        seed(db)
        result = run_prediction(
            db, [["LO1", "2026-08-22 09:00:00", "SPBU-A"]],
            [["B1001AA", "2026-08-22 08:00:00"]],
        )
        shipment_id = result["shipments"][0]["id"]
        candidate = db.scalar(select(PredictionMTCandidate).where(PredictionMTCandidate.prediction_shipment_id == shipment_id))
        assert candidate.explanation["master_checks"][0]["missing_tags"] == []
        db.add(MasterTag(tag_id="NEW", tag_value="New restriction", normalized_tag="NEW"))
        db.commit()
        db.add(BridgeSPBUTag(spbu_id="A", tag_id="NEW"))
        db.commit()
        payload = get_prediction_shipment_candidates(db, result["id"], shipment_id)["candidates"][0]
        assert payload["explanation"]["master_checks"][0]["missing_tags"] == []
        assert "current_master_checks" not in payload["explanation"]

        candidate.explanation = {key: value for key, value in candidate.explanation.items() if key != "master_checks"}
        db.commit()
        payload = get_prediction_shipment_candidates(db, result["id"], shipment_id)["candidates"][0]
        assert payload["compatibility_status"] == "PASS"
        assert payload["explanation"]["master_compatibility"] == "PASS"
        assert payload["explanation"]["current_master_checks"][0]["missing_tags"] == ["New restriction"]
        assert payload["explanation"]["current_master_checks"][0]["compatible"] is False
        db.refresh(candidate)
        assert "current_master_checks" not in candidate.explanation
