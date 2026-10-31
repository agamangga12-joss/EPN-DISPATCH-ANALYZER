"""Canonical master values and historical round-trip estimates."""

from collections import defaultdict
from statistics import median

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import FactLoadingOrderLine, FactShipment, FactShipmentSPBU, MasterMT, MasterSPBU
from .normalization import mt_capacity_kl


def consolidate_master(record) -> None:
    # Legacy columns remain as compatibility mirrors for existing integrations.
    if isinstance(record, MasterMT):
        record.vehicle_name_raw = record.vehicle_registration or record.vehicle_name_raw
        capacity = mt_capacity_kl(record.capacity_label, record.vehicle_type_tag)
        if capacity is not None and float(capacity).is_integer():
            record.vehicle_type_tag = int(capacity)
        record.capacity_label = f"{capacity:g}KL" if capacity is not None else None
    elif isinstance(record, MasterSPBU):
        record.spbu_name = record.spbu_code
        record.address = record.address or record.city
        record.city = record.address
        record.source_coordinate = (
            f"{record.latitude} {record.longitude}"
            if record.latitude is not None and record.longitude is not None else None
        )


def refresh_historical_travel_times(db: Session, depot_id: str | None = None) -> None:
    """Use distinct single-SPBU shipments; repeated product lines count once.

    RTH includes service/waiting time: half of RTH is a historical one-leg
    estimate, not an observed drive-only duration. Missing evidence stays NULL.
    """
    db.flush()
    single_stop = (
        select(
            FactLoadingOrderLine.shipment_id.label("shipment_id"),
            func.min(FactLoadingOrderLine.spbu_id).label("spbu_id"),
        )
        .where((FactLoadingOrderLine.status.is_(None)) | (FactLoadingOrderLine.status != "DELETED"))
        .group_by(FactLoadingOrderLine.shipment_id)
        .having(
            func.count(func.distinct(FactLoadingOrderLine.spbu_id)) == 1,
            func.count(FactLoadingOrderLine.spbu_id) == func.count(),
        )
        .subquery()
    )
    statement = (
        select(single_stop.c.spbu_id, FactShipment.gate_out_datetime, FactShipment.shipment_end_datetime)
        .join(FactShipment, FactShipment.shipment_id == single_stop.c.shipment_id)
        .join(MasterSPBU, MasterSPBU.spbu_id == single_stop.c.spbu_id)
        .where(
            FactShipment.depot_id == MasterSPBU.primary_depot_id,
            FactShipment.gate_out_datetime.is_not(None),
            FactShipment.shipment_end_datetime > FactShipment.gate_out_datetime,
        )
    )
    masters = select(MasterSPBU)
    if depot_id:
        statement = statement.where(FactShipment.depot_id == depot_id)
        masters = masters.where(MasterSPBU.primary_depot_id == depot_id)
    samples: dict[str, list[float]] = defaultdict(list)
    for spbu_id, gate_out, shipment_end in db.execute(statement):
        samples[spbu_id].append((shipment_end - gate_out).total_seconds() / 60)
    for spbu in db.scalars(masters):
        values = samples.get(spbu.spbu_id, [])
        spbu.master_rth_min = float(median(values)) if values else None
        spbu.master_travel_time_min = spbu.master_rth_min / 2 if values else None
        spbu.master_travel_time_sample_count = len(values)


def rebuild_shipment_membership(db: Session, shipment_ids) -> None:
    db.flush()
    ids = set(shipment_ids)
    if not ids:
        return
    db.execute(delete(FactShipmentSPBU).where(FactShipmentSPBU.shipment_id.in_(ids)))
    members = db.execute(
        select(FactLoadingOrderLine.shipment_id, FactLoadingOrderLine.spbu_id)
        .where(FactLoadingOrderLine.shipment_id.in_(ids), FactLoadingOrderLine.spbu_id.is_not(None),
               (FactLoadingOrderLine.status.is_(None)) | (FactLoadingOrderLine.status != "DELETED"))
        .distinct()
    )
    for shipment_id, spbu_id in members:
        db.add(FactShipmentSPBU(shipment_id=shipment_id, spbu_id=spbu_id, assignment_source="LO"))
