import hashlib
from datetime import date, time

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class MasterRestrictedRoad(Base):
    __tablename__ = "master_restricted_road"

    restricted_road_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    # Confirmed GeoJSON LineString coordinates, in longitude/latitude order.
    geometry: Mapped[list] = mapped_column(JSON)
    direction: Mapped[str] = mapped_column(String(16), default="BOTH")
    forward_waypoints: Mapped[list] = mapped_column(JSON, default=list)
    reverse_waypoints: Mapped[list] = mapped_column(JSON, default=list)
    buffer_meters: Mapped[float] = mapped_column(Float, default=12)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportAudit(Base):
    __tablename__ = "import_audit"

    import_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(40), index=True)
    depot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_checksum: Mapped[str | None] = mapped_column(String(128))
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    uploaded_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploaded_by: Mapped[str | None] = mapped_column(String(120))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="STAGED")
    published_at = mapped_column(DateTime(timezone=True), nullable=True)
    mapping_version: Mapped[str] = mapped_column(String(40), default="phase0.v1")
    stored_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)


class StagingMixin:
    staging_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    import_id: Mapped[str] = mapped_column(String(64), ForeignKey("import_audit.import_id"), index=True)
    source_row_number: Mapped[int] = mapped_column(Integer)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    normalized_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(20), default="VALID")
    validation_messages: Mapped[list] = mapped_column(JSON, default=list)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class StgMT(StagingMixin, Base):
    __tablename__ = "stg_mt"


class StgSPBU(StagingMixin, Base):
    __tablename__ = "stg_spbu"


class StgLoadingOrder(StagingMixin, Base):
    __tablename__ = "stg_loading_order"


class StgGPSData(StagingMixin, Base):
    __tablename__ = "stg_gps_data"


class MasterDepot(Base):
    __tablename__ = "master_depot"

    depot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_code: Mapped[str | None] = mapped_column(String(80), unique=True)
    depot_name: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    region: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str | None] = mapped_column(String(80), default="Asia/Jakarta")
    operational_shifts: Mapped[list] = mapped_column(JSON, default=list)
    depot_operational_start = mapped_column(Time, nullable=False, default=lambda: time(0, 0))
    depot_operational_end = mapped_column(Time, nullable=False, default=lambda: time(23, 59))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class DepotIdentifierAlias(Base):
    __tablename__ = "depot_identifier_alias"

    depot_identifier_alias_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"))
    identifier_type: Mapped[str] = mapped_column(String(40))
    identifier_value: Mapped[str] = mapped_column(String(255))
    normalized_identifier: Mapped[str] = mapped_column(String(255), index=True)
    source_system: Mapped[str | None] = mapped_column(String(80))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class MasterTagType(Base):
    __tablename__ = "master_tag_type"

    tag_type_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    admin_editable: Mapped[bool] = mapped_column(Boolean, default=True)


class MasterTag(Base):
    __tablename__ = "master_tag"

    tag_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tag_type_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_tag_type.tag_type_id"))
    tag_value: Mapped[str] = mapped_column(String(255))
    normalized_tag: Mapped[str] = mapped_column(String(255), unique=True)
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class TagAlias(Base):
    __tablename__ = "tag_alias"

    tag_alias_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alias_value: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    canonical_tag_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_tag.tag_id"))
    source_domain: Mapped[str | None] = mapped_column(String(80))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class MasterMT(Base):
    __tablename__ = "master_mt"
    __table_args__ = (UniqueConstraint("depot_id", "vehicle_registration", name="uq_master_mt_depot_registration"),)

    mt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_mt_id: Mapped[str | None] = mapped_column(String(120))
    vehicle_name_raw: Mapped[str] = mapped_column(String(255))
    vehicle_registration: Mapped[str | None] = mapped_column(String(80), index=True)
    capacity_label: Mapped[str | None] = mapped_column(String(80))
    vehicle_type_tag: Mapped[int | None] = mapped_column(Integer)
    project_tag_raw: Mapped[str | None] = mapped_column(Text)
    number_of_compartments: Mapped[int | None] = mapped_column(Integer)
    depot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_depot.depot_id"))
    source_hub_id: Mapped[str | None] = mapped_column(String(120))
    assignee: Mapped[str | None] = mapped_column(String(255))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    vehicle_height_mm: Mapped[int | None] = mapped_column(Integer)
    vehicle_length_mm: Mapped[int | None] = mapped_column(Integer)
    vehicle_weight_kg: Mapped[int | None] = mapped_column(Integer)
    vehicle_width_mm: Mapped[int | None] = mapped_column(Integer)
    vehicle_axle_count: Mapped[int | None] = mapped_column(Integer)
    hazmat_category: Mapped[str | None] = mapped_column(Text)
    large_vehicle_profile_status: Mapped[str] = mapped_column(String(20), default="NOT_REQUIRED")
    effective_start_date = mapped_column(Date, nullable=True)
    effective_end_date = mapped_column(Date, nullable=True)
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class BridgeMTTag(Base):
    __tablename__ = "bridge_mt_tag"

    mt_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_tag.tag_id"), primary_key=True)
    source_import_id: Mapped[str | None] = mapped_column(String(64))


class MasterSPBU(Base):
    __tablename__ = "master_spbu"
    __table_args__ = (UniqueConstraint("primary_depot_id", "spbu_code", name="uq_master_spbu_depot_code"),)

    spbu_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spbu_code: Mapped[str] = mapped_column(String(120))
    spbu_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    source_coordinate: Mapped[str | None] = mapped_column(String(255))
    master_distance_km: Mapped[float | None] = mapped_column(Float)
    master_travel_time_min: Mapped[float | None] = mapped_column(Float)
    master_rth_min: Mapped[float | None] = mapped_column(Float)
    master_travel_time_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_type_tag: Mapped[int | None] = mapped_column(Integer)
    project_tag_raw: Mapped[str | None] = mapped_column(Text)
    primary_depot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_depot.depot_id"))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    official_window_start = mapped_column(Time, nullable=False, default=lambda: time(0, 0))
    official_window_end = mapped_column(Time, nullable=False, default=lambda: time(23, 59))
    effective_start_date = mapped_column(Date, nullable=True)
    effective_end_date = mapped_column(Date, nullable=True)
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class BridgeSPBUTag(Base):
    __tablename__ = "bridge_spbu_tag"

    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_tag.tag_id"), primary_key=True)
    source_import_id: Mapped[str | None] = mapped_column(String(64))


class DepartureShiftAnalysisConfig(Base):
    __tablename__ = "departure_shift_analysis_config"
    __table_args__ = (
        UniqueConstraint("depot_id", "normalized_name", name="uq_departure_shift_config_depot_name"),
        Index("ix_departure_shift_config_depot_created", "depot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    bucket_minutes: Mapped[int] = mapped_column(Integer)
    search: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_column: Mapped[str] = mapped_column(String(80), default="observation_count")
    sort_direction: Mapped[str] = mapped_column(String(10), default="desc")
    assignment_method: Mapped[str] = mapped_column(String(60))
    shift_config: Mapped[list] = mapped_column(JSON, default=list)
    ui_state: Mapped[dict] = mapped_column(JSON, default=dict)
    departure_analysis_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    shift_analysis_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PairingAnalysisConfig(Base):
    __tablename__ = "pairing_analysis_config"
    __table_args__ = (
        UniqueConstraint("depot_id", "normalized_name", name="uq_pairing_config_depot_name"),
        Index("ix_pairing_config_depot_created", "depot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"), nullable=True)
    search: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_column: Mapped[str] = mapped_column(String(80), default="evidence_strength")
    sort_direction: Mapped[str] = mapped_column(String(10), default="desc")
    ui_state: Mapped[dict] = mapped_column(JSON, default=dict)
    pairing_analysis_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AffinityAnalysisConfig(Base):
    __tablename__ = "affinity_analysis_config"
    __table_args__ = (
        UniqueConstraint("depot_id", "normalized_name", name="uq_affinity_config_depot_name"),
        Index("ix_affinity_config_depot_created", "depot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"), nullable=True)
    minimum_observations: Mapped[int] = mapped_column(Integer, default=1)
    confidence_filter: Mapped[str] = mapped_column(String(20), default="ALL")
    temporal_bucket: Mapped[str] = mapped_column(String(20), default="WEEKLY")
    recent_days: Mapped[int] = mapped_column(Integer, default=7)
    top_n: Mapped[int] = mapped_column(Integer, default=5)
    edge_metric: Mapped[str] = mapped_column(String(40), default="SHIPMENT_COUNT")
    selected_spbu_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), nullable=True)
    selected_mt_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), nullable=True)
    ui_state: Mapped[dict] = mapped_column(JSON, default=dict)
    affinity_analysis_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SpbuIdentifierAlias(Base):
    __tablename__ = "spbu_identifier_alias"

    spbu_identifier_alias_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    identifier_type: Mapped[str] = mapped_column(String(40))
    identifier_value: Mapped[str] = mapped_column(String(255))
    normalized_identifier: Mapped[str] = mapped_column(String(255), index=True)
    source_system: Mapped[str | None] = mapped_column(String(80))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class MasterProduct(Base):
    __tablename__ = "master_product"

    product_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_name: Mapped[str] = mapped_column(String(255))
    normalized_product: Mapped[str] = mapped_column(String(255), unique=True)
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductAlias(Base):
    __tablename__ = "product_alias"

    product_alias_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    alias_value: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    source_system: Mapped[str | None] = mapped_column(String(80))
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class MasterPersonnel(Base):
    __tablename__ = "master_personnel"

    personnel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_parent_id: Mapped[str | None] = mapped_column(String(120))
    name: Mapped[str | None] = mapped_column(String(255))
    nip: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40))
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class FactShipment(Base):
    __tablename__ = "fact_shipment"

    shipment_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_shipment_id: Mapped[str] = mapped_column(String(120), unique=True)
    operating_date = mapped_column(Date, nullable=True)
    area_id: Mapped[str | None] = mapped_column(String(80))
    area: Mapped[str | None] = mapped_column(String(120))
    depot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_depot.depot_id"))
    mt_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    vehicle_registration: Mapped[str | None] = mapped_column(String(80))
    vehicle_mapping_status: Mapped[str] = mapped_column(String(40), default="UNMATCHED")
    vehicle_type_tag_observed: Mapped[str | None] = mapped_column(String(80))
    project_tag_raw: Mapped[str | None] = mapped_column(Text)
    validation_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    gate_out_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    shipment_end_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(255))
    driver_nip: Mapped[str | None] = mapped_column(String(120))
    assistant_name: Mapped[str | None] = mapped_column(String(255))
    assistant_nip: Mapped[str | None] = mapped_column(String(120))
    driver_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_personnel.personnel_id"))
    assistant_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_personnel.personnel_id"))
    status: Mapped[str | None] = mapped_column(String(80))
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


def _default_loading_order_id(context) -> str:
    values = context.get_current_parameters()
    depot_identity = values.get("depot_id") or values.get("source_depot_name") or "UNKNOWN_DEPOT"
    loading_order_number = values.get("loading_order_number") or "UNKNOWN_LO"
    digest = hashlib.sha1(f"{depot_identity}|{loading_order_number}".encode("utf-8")).hexdigest()[:24]
    return f"lo_{digest}"


class FactLoadingOrderLine(Base):
    __tablename__ = "fact_loading_order_line"
    __table_args__ = (UniqueConstraint("depot_id", "loading_order_number", name="uq_loading_order_depot_number"),)

    loading_order_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_loading_order_id)
    loading_order_number: Mapped[str] = mapped_column(String(120), index=True)
    depot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    source_depot_name: Mapped[str] = mapped_column(String(255))
    shipment_id: Mapped[str] = mapped_column(String(120), ForeignKey("fact_shipment.shipment_id"))
    spbu_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    spbu_mapping_status: Mapped[str] = mapped_column(String(40), default="UNMATCHED")
    source_spbu_code: Mapped[str | None] = mapped_column(String(120))
    shipto: Mapped[str | None] = mapped_column(String(120))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    source_product_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(80))
    source_distance_km: Mapped[float | None] = mapped_column(Float)
    actual_km: Mapped[float | None] = mapped_column(Float)
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class FactShipmentSPBU(Base):
    __tablename__ = "fact_shipment_spbu"

    shipment_id: Mapped[str] = mapped_column(String(120), ForeignKey("fact_shipment.shipment_id"), primary_key=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), primary_key=True)
    assignment_source: Mapped[str] = mapped_column(String(40), default="LO")
    source_import_id: Mapped[str | None] = mapped_column(String(64))


class FactGPSEvent(Base):
    __tablename__ = "fact_gps_event"

    gps_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mt_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    vehicle_registration: Mapped[str | None] = mapped_column(String(80))
    vehicle_mapping_status: Mapped[str] = mapped_column(String(40), default="UNMATCHED")
    source_device_id: Mapped[str | None] = mapped_column(String(120))
    event_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    speed: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    ignition_status: Mapped[str | None] = mapped_column(String(40))
    event_type: Mapped[str | None] = mapped_column(String(80))
    nearest_spbu_id: Mapped[str | None] = mapped_column(String(64))
    nearest_depot_id: Mapped[str | None] = mapped_column(String(64))
    distance_to_spbu_m: Mapped[float | None] = mapped_column(Float)
    distance_to_depot_m: Mapped[float | None] = mapped_column(Float)
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    raw_event_reference: Mapped[str | None] = mapped_column(String(255))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpbuGeofence(Base):
    __tablename__ = "spbu_geofence"

    spbu_geofence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    geofence_type: Mapped[str] = mapped_column(String(40), default="CIRCLE")
    radius_m: Mapped[float] = mapped_column(Float)
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    effective_start = mapped_column(Date, nullable=True)
    effective_end = mapped_column(Date, nullable=True)


class DepotGeofence(Base):
    __tablename__ = "depot_geofence"

    depot_geofence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"))
    geofence_type: Mapped[str] = mapped_column(String(40), default="CIRCLE")
    radius_m: Mapped[float] = mapped_column(Float)
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    effective_start = mapped_column(Date, nullable=True)
    effective_end = mapped_column(Date, nullable=True)


class FactSPBUVisit(Base):
    __tablename__ = "fact_spbu_visit"

    spbu_visit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mt_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    shipment_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("fact_shipment.shipment_id"))
    spbu_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    arrival_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    departure_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    dwell_minutes: Mapped[float | None] = mapped_column(Float)
    first_gps_event_id: Mapped[str | None] = mapped_column(String(64))
    last_gps_event_id: Mapped[str | None] = mapped_column(String(64))
    gps_event_count: Mapped[int | None] = mapped_column(Integer)
    min_distance_to_spbu_m: Mapped[float | None] = mapped_column(Float)
    visit_match_method: Mapped[str | None] = mapped_column(String(80))
    visit_confidence: Mapped[float | None] = mapped_column(Float)
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class FactShipmentStop(Base):
    __tablename__ = "fact_shipment_stop"

    shipment_stop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shipment_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("fact_shipment.shipment_id"))
    spbu_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    stop_sequence: Mapped[int | None] = mapped_column(Integer)
    arrival_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    departure_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    dwell_minutes: Mapped[float | None] = mapped_column(Float)
    sequence_source: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    sequence_confidence: Mapped[float | None] = mapped_column(Float)
    source_import_id: Mapped[str | None] = mapped_column(String(64))


class FactSPBUPair(Base):
    __tablename__ = "fact_spbu_pair"
    __table_args__ = (
        UniqueConstraint(
            "depot_id",
            "spbu_a_id",
            "spbu_b_id",
            "analysis_start_date",
            "analysis_end_date",
            "algorithm_version",
            name="uq_fact_spbu_pair_scope",
        ),
        Index("ix_fact_spbu_pair_depot_dates", "depot_id", "analysis_start_date", "analysis_end_date"),
        Index("ix_fact_spbu_pair_spbus", "spbu_a_id", "spbu_b_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    spbu_a_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    spbu_b_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    pair_count: Mapped[int] = mapped_column(Integer, default=0)
    shipment_a_count: Mapped[int] = mapped_column(Integer, default=0)
    shipment_b_count: Mapped[int] = mapped_column(Integer, default=0)
    total_shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    probability_b_given_a: Mapped[float] = mapped_column(Float, default=0.0)
    probability_a_given_b: Mapped[float] = mapped_column(Float, default=0.0)
    support: Mapped[float] = mapped_column(Float, default=0.0)
    lift: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_DATA")
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_start_date = mapped_column(Date, nullable=False)
    analysis_end_date = mapped_column(Date, nullable=False)
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    algorithm_version: Mapped[str] = mapped_column(String(80), default="pairing_v1")


class FactSPBUTransition(Base):
    __tablename__ = "fact_spbu_transition"
    __table_args__ = (
        UniqueConstraint(
            "depot_id",
            "from_spbu_id",
            "to_spbu_id",
            "analysis_start_date",
            "analysis_end_date",
            "algorithm_version",
            name="uq_fact_spbu_transition_scope",
        ),
        Index("ix_fact_spbu_transition_depot_dates", "depot_id", "analysis_start_date", "analysis_end_date"),
        Index("ix_fact_spbu_transition_spbus", "from_spbu_id", "to_spbu_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    from_spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    to_spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    transition_count: Mapped[int] = mapped_column(Integer, default=0)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    transition_probability: Mapped[float] = mapped_column(Float, default=0.0)
    analysis_start_date = mapped_column(Date, nullable=False)
    analysis_end_date = mapped_column(Date, nullable=False)
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_DATA")
    algorithm_version: Mapped[str] = mapped_column(String(80), default="spbu_transition.consecutive_v1")


class FactSPBUMTPair(Base):
    __tablename__ = "fact_spbu_mt_pair"
    __table_args__ = (
        UniqueConstraint(
            "depot_id",
            "spbu_id",
            "mt_id",
            "analysis_start_date",
            "analysis_end_date",
            "product_filter",
            "algorithm_version",
            name="uq_fact_spbu_mt_pair_scope",
        ),
        Index("ix_fact_spbu_mt_pair_depot_dates", "depot_id", "analysis_start_date", "analysis_end_date"),
        Index("ix_fact_spbu_mt_pair_entities", "spbu_id", "mt_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    mt_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    total_spbu_shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    total_mt_shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    probability_mt_given_spbu: Mapped[float] = mapped_column(Float, default=0.0)
    probability_spbu_given_mt: Mapped[float] = mapped_column(Float, default=0.0)
    first_observed = mapped_column(Date, nullable=False)
    last_observed = mapped_column(Date, nullable=False)
    operating_day_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(20), default="LOW")
    analysis_start_date = mapped_column(Date, nullable=False)
    analysis_end_date = mapped_column(Date, nullable=False)
    product_filter: Mapped[str] = mapped_column(String(120), default="ALL")
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    algorithm_version: Mapped[str] = mapped_column(String(80), default="spbu_mt_affinity.jsd_v1")


class FactSPBUMTProfile(Base):
    __tablename__ = "fact_spbu_mt_profile"
    __table_args__ = (
        UniqueConstraint(
            "depot_id",
            "spbu_id",
            "analysis_start_date",
            "analysis_end_date",
            "product_filter",
            "temporal_bucket",
            "algorithm_version",
            name="uq_fact_spbu_mt_profile_scope",
        ),
        Index("ix_fact_spbu_mt_profile_depot_dates", "depot_id", "analysis_start_date", "analysis_end_date"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    operating_day_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_mt_count: Mapped[int] = mapped_column(Integer, default=0)
    dominant_mt_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    dominant_mt_probability: Mapped[float] = mapped_column(Float, default=0.0)
    second_mt_probability: Mapped[float] = mapped_column(Float, default=0.0)
    top3_mt_share: Mapped[float] = mapped_column(Float, default=0.0)
    hhi: Mapped[float] = mapped_column(Float, default=0.0)
    normalized_hhi: Mapped[float] = mapped_column(Float, default=0.0)
    normalized_entropy: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_score: Mapped[float] = mapped_column(Float, default=0.0)
    variability_score: Mapped[float] = mapped_column(Float, default=0.0)
    dominant_mt_persistence: Mapped[float] = mapped_column(Float, default=0.0)
    temporal_stability_score: Mapped[float] = mapped_column(Float, default=0.0)
    pattern_shift_level: Mapped[str] = mapped_column(String(40), default="STABLE")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(20), default="LOW")
    analysis_start_date = mapped_column(Date, nullable=False)
    analysis_end_date = mapped_column(Date, nullable=False)
    product_filter: Mapped[str] = mapped_column(String(120), default="ALL")
    temporal_bucket: Mapped[str] = mapped_column(String(20), default="WEEKLY")
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    algorithm_version: Mapped[str] = mapped_column(String(80), default="spbu_mt_affinity.jsd_v1")


class FactSPBUMTTemporalProfile(Base):
    __tablename__ = "fact_spbu_mt_temporal_profile"
    __table_args__ = (
        UniqueConstraint(
            "depot_id",
            "spbu_id",
            "mt_id",
            "period_type",
            "period_start",
            "analysis_start_date",
            "analysis_end_date",
            "algorithm_version",
            name="uq_fact_spbu_mt_temporal_scope",
        ),
        Index("ix_fact_spbu_mt_temporal_depot_period", "depot_id", "period_type", "period_start"),
        Index("ix_fact_spbu_mt_temporal_entities", "spbu_id", "mt_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    mt_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    period_type: Mapped[str] = mapped_column(String(20))
    period_start = mapped_column(Date, nullable=False)
    period_end = mapped_column(Date, nullable=False)
    shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    total_spbu_shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    probability_mt_given_spbu: Mapped[float] = mapped_column(Float, default=0.0)
    is_dominant_mt: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_start_date = mapped_column(Date, nullable=False)
    analysis_end_date = mapped_column(Date, nullable=False)
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    algorithm_version: Mapped[str] = mapped_column(String(80), default="spbu_mt_affinity.jsd_v1")


class MLConcentrationAnalysisRun(Base):
    __tablename__ = "ml_concentration_analysis_run"
    __table_args__ = (
        Index("ix_ml_concentration_run_depot_dates", "depot_id", "baseline_start_date", "baseline_end_date"),
        Index("ix_ml_concentration_run_status_created", "status", "created_at"),
    )

    analysis_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    baseline_start_date = mapped_column(Date, nullable=False)
    baseline_end_date = mapped_column(Date, nullable=False)
    minimum_shipment_observation: Mapped[int] = mapped_column(Integer, default=10)
    algorithm_name: Mapped[str] = mapped_column(String(80), default="IsolationForest")
    algorithm_version: Mapped[str] = mapped_column(String(80), default="phase5.concentration.iforest.v1")
    algorithm_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    master_compatibility_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)


class MLConcentrationSavedAnalysis(Base):
    __tablename__ = "ml_concentration_saved_analysis"
    __table_args__ = (
        UniqueConstraint("depot_id", "normalized_name", name="uq_ml_concentration_saved_depot_name"),
        Index("ix_ml_concentration_saved_depot_created", "depot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    analysis_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ml_concentration_analysis_run.analysis_run_id", ondelete="CASCADE"), index=True
    )
    ui_state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MLSPBUConcentrationProfile(Base):
    __tablename__ = "ml_spbu_concentration_profile"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "spbu_id", name="uq_ml_concentration_profile_run_spbu"),
        Index("ix_ml_concentration_profile_run_score", "analysis_run_id", "concentration_anomaly_score"),
        Index("ix_ml_concentration_profile_depot_spbu", "depot_id", "spbu_id"),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ml_concentration_analysis_run.analysis_run_id", ondelete="CASCADE"), index=True
    )
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    shipment_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    compatible_mt_count: Mapped[int] = mapped_column(Integer, default=0)
    historically_used_mt_count: Mapped[int] = mapped_column(Integer, default=0)
    utilization_breadth: Mapped[float] = mapped_column(Float, default=0.0)
    dominant_mt_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    dominant_mt_share: Mapped[float] = mapped_column(Float, default=0.0)
    hhi: Mapped[float] = mapped_column(Float, default=0.0)
    entropy: Mapped[float] = mapped_column(Float, default=0.0)
    normalized_entropy: Mapped[float] = mapped_column(Float, default=0.0)
    raw_ml_anomaly_score: Mapped[float | None] = mapped_column(Float)
    concentration_anomaly_score: Mapped[float | None] = mapped_column(Float, index=True)
    concentration_classification: Mapped[str] = mapped_column(String(50), default="INSUFFICIENT_DATA")
    data_sufficiency_status: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_DATA")
    peer_statistics: Mapped[dict] = mapped_column(JSON, default=dict)
    mt_distribution: Mapped[list] = mapped_column(JSON, default=list)


class MLTrainingRun(Base):
    __tablename__ = "ml_training_run"
    __table_args__ = (
        Index("ix_ml_training_run_depot_dates", "depot_id", "training_start_date", "training_end_date"),
        Index("ix_ml_training_run_status_created", "status", "created_at"),
    )

    training_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    training_start_date = mapped_column(Date, nullable=False)
    training_end_date = mapped_column(Date, nullable=False)
    minimum_shipment_observation: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    training_configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    shift_definition_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    master_compatibility_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(80), default="phase5.behavioral.portable_n2v_umap_hdbscan.v2")
    library_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_temp_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)


class MLBehavioralModel(Base):
    __tablename__ = "ml_behavioral_model"
    __table_args__ = (
        UniqueConstraint("depot_id", "model_name", "model_version", name="uq_ml_behavioral_model_name_version"),
        Index("ix_ml_behavioral_model_depot_status", "depot_id", "model_status"),
        Index("ix_ml_behavioral_model_created", "created_at"),
    )

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(255), index=True)
    model_description: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[int] = mapped_column(Integer, default=1)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    source_training_run_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("ml_training_run.training_run_id"))
    training_start_date = mapped_column(Date, nullable=False)
    training_end_date = mapped_column(Date, nullable=False)
    training_shipment_count: Mapped[int] = mapped_column(Integer, default=0)
    training_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    total_covered_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    total_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    sufficient_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    marginal_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    insufficient_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    core_training_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    core_cluster_member_count: Mapped[int] = mapped_column(Integer, default=0)
    marginal_projected_count: Mapped[int] = mapped_column(Integer, default=0)
    marginal_unassigned_count: Mapped[int] = mapped_column(Integer, default=0)
    insufficient_unassigned_count: Mapped[int] = mapped_column(Integer, default=0)
    cold_start_covered_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    no_history_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    insufficient_history_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    minimum_shipment_observation: Mapped[int] = mapped_column(Integer, default=10)
    tag_feature_configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    tag_encoder_reference: Mapped[dict] = mapped_column(JSON, default=dict)
    shift_definition_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    feature_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    tag_weight: Mapped[float] = mapped_column(Float, default=0.30)
    shift_weight: Mapped[float] = mapped_column(Float, default=0.20)
    pairing_weight: Mapped[float] = mapped_column(Float, default=0.30)
    geographic_weight: Mapped[float] = mapped_column(Float, default=0.20)
    data_sufficiency_configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    geographic_proximity_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    geographic_configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    valid_coordinate_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_coordinate_count: Mapped[int] = mapped_column(Integer, default=0)
    geographic_coverage_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    projection_method: Mapped[str] = mapped_column(String(80), default="UMAP_NEAREST_CORE_CENTROID")
    projection_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    minimum_projection_confidence: Mapped[float] = mapped_column(Float, default=0.55)
    node2vec_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    umap_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    hdbscan_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    dependency_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    cluster_count: Mapped[int] = mapped_column(Integer, default=0)
    noise_spbu_count: Mapped[int] = mapped_column(Integer, default=0)
    average_membership_probability: Mapped[float] = mapped_column(Float, default=0.0)
    average_projection_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    algorithm_version: Mapped[str] = mapped_column(String(80), default="phase5.behavioral.portable_n2v_umap_hdbscan.v2")
    library_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    random_seed: Mapped[int] = mapped_column(Integer, default=42)
    model_status: Mapped[str] = mapped_column(String(30), default="SAVED", index=True)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MLModelArtifact(Base):
    __tablename__ = "ml_model_artifact"
    __table_args__ = (UniqueConstraint("model_id", "artifact_type", name="uq_ml_model_artifact_type"),)

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), ForeignKey("ml_behavioral_model.model_id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(60))
    storage_uri: Mapped[str] = mapped_column(Text)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class MLSPBUClusterAssignment(Base):
    __tablename__ = "ml_spbu_cluster_assignment"
    __table_args__ = (
        UniqueConstraint("model_id", "spbu_id", name="uq_ml_cluster_assignment_model_spbu"),
        Index("ix_ml_cluster_assignment_depot_spbu", "depot_id", "spbu_id"),
        Index("ix_ml_cluster_assignment_model_cluster", "model_id", "cluster_id"),
        Index("ix_ml_cluster_assignment_model_sufficiency", "model_id", "data_sufficiency_status"),
        Index("ix_ml_cluster_assignment_model_type", "model_id", "cluster_assignment_type"),
    )

    assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), ForeignKey("ml_behavioral_model.model_id", ondelete="CASCADE"), index=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer)
    cluster_label: Mapped[str] = mapped_column(String(120))
    membership_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False)
    shipment_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    operating_day_count: Mapped[int] = mapped_column(Integer, default=0)
    training_period_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    shift_observation_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    pairing_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    pairing_observation_strength: Mapped[float] = mapped_column(Float, default=0.0)
    last_operating_date = mapped_column(Date, nullable=True)
    recency_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_sufficiency_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_sufficiency_status: Mapped[str] = mapped_column(String(20), default="INSUFFICIENT", index=True)
    data_sufficiency_components: Mapped[dict] = mapped_column(JSON, default=dict)
    cluster_assignment_type: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_UNASSIGNED", index=True)
    projected_cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    projection_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    projection_status: Mapped[str] = mapped_column(String(30), default="UNASSIGNED")
    unassigned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    geographic_data_status: Mapped[str] = mapped_column(String(20), default="MISSING", index=True)
    geographic_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage_source: Mapped[str] = mapped_column(String(50), default="BEHAVIORAL_HISTORY")
    history_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    dominant_shift: Mapped[str | None] = mapped_column(String(120))
    key_tags: Mapped[list] = mapped_column(JSON, default=list)
    visualization_x: Mapped[float | None] = mapped_column(Float)
    visualization_y: Mapped[float | None] = mapped_column(Float)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class MLClusterProfile(Base):
    __tablename__ = "ml_cluster_profile"
    __table_args__ = (UniqueConstraint("model_id", "cluster_id", name="uq_ml_cluster_profile_model_cluster"),)

    cluster_profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), ForeignKey("ml_behavioral_model.model_id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[int] = mapped_column(Integer)
    cluster_label: Mapped[str] = mapped_column(String(120))
    cluster_size: Mapped[int] = mapped_column(Integer, default=0)
    historical_member_count: Mapped[int] = mapped_column(Integer, default=0)
    cold_start_member_count: Mapped[int] = mapped_column(Integer, default=0)
    projected_member_count: Mapped[int] = mapped_column(Integer, default=0)
    no_history_member_count: Mapped[int] = mapped_column(Integer, default=0)
    training_spbu_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    common_tags: Mapped[list] = mapped_column(JSON, default=list)
    shift_distribution: Mapped[list] = mapped_column(JSON, default=list)
    dominant_shift: Mapped[str | None] = mapped_column(String(120))
    top_internal_pairings: Mapped[list] = mapped_column(JSON, default=list)
    average_membership_probability: Mapped[float] = mapped_column(Float, default=0.0)
    low_confidence_member_count: Mapped[int] = mapped_column(Integer, default=0)


class PredictionRun(Base):
    __tablename__ = "prediction_run"
    __table_args__ = (
        Index("ix_prediction_run_depot_created", "depot_id", "created_at"),
        Index("ix_prediction_run_model_created", "model_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_run_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    model_id: Mapped[str] = mapped_column(String(64), ForeignKey("ml_behavioral_model.model_id"), index=True)
    model_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    input_loading_order_filename: Mapped[str] = mapped_column(String(255))
    input_mt_availability_filename: Mapped[str] = mapped_column(String(255))
    input_loading_order_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    input_mt_availability_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    validation_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    parameter_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    model_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    original_prediction_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    final_prediction_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    routing_configuration_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    routing_metrics_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(100))
    validation_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    shipment_prediction_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    mt_prediction_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    assignment_optimization_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_prediction_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class PredictionJob(Base):
    """Durable queue/lease state kept separate from the prediction transaction."""

    __tablename__ = "prediction_job"
    __table_args__ = (
        Index("ix_prediction_job_status_queued", "status", "queued_at"),
        Index("ix_prediction_job_lease", "status", "lease_expires_at"),
    )

    prediction_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_run.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    worker_id: Mapped[str | None] = mapped_column(String(160))
    lease_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    queued_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_recovered_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text)


class PredictionShipment(Base):
    __tablename__ = "prediction_shipment"
    __table_args__ = (
        UniqueConstraint("prediction_run_id", "predicted_shipment_id", name="uq_prediction_shipment_run_number"),
        Index("ix_prediction_shipment_run_shift", "prediction_run_id", "shift_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_run.id", ondelete="CASCADE"), index=True
    )
    predicted_shipment_id: Mapped[str] = mapped_column(String(120), index=True)
    shift_id: Mapped[str] = mapped_column(String(80), index=True)
    shift_name: Mapped[str] = mapped_column(String(120))
    planned_start_datetime = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    shipment_prediction_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(20), default="LOW")
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class PredictionShipmentLine(Base):
    __tablename__ = "prediction_shipment_line"
    __table_args__ = (
        UniqueConstraint("prediction_run_id", "loading_order_no", name="uq_prediction_line_run_lo"),
        Index("ix_prediction_line_shipment_spbu", "prediction_shipment_id", "spbu_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_run.id", ondelete="CASCADE"), index=True
    )
    prediction_shipment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_shipment.id", ondelete="CASCADE"), index=True
    )
    loading_order_no: Mapped[str] = mapped_column(String(120), index=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    spbu_no: Mapped[str] = mapped_column(String(120))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255))
    order_quantity_kl: Mapped[float | None] = mapped_column(Float)
    shipment_start_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    model_predicted_shipment_id: Mapped[str] = mapped_column(String(120))


class PredictionMTCandidate(Base):
    __tablename__ = "prediction_mt_candidate"
    __table_args__ = (
        UniqueConstraint("prediction_shipment_id", "vehicle_id", name="uq_prediction_candidate_shipment_vehicle"),
        Index("ix_prediction_candidate_shipment_rank", "prediction_shipment_id", "candidate_rank"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_shipment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_shipment.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    prediction_score: Mapped[float] = mapped_column(Float, default=0.0)
    compatibility_status: Mapped[str] = mapped_column(String(20))
    candidate_rank: Mapped[int | None] = mapped_column(Integer)
    exclusion_reason: Mapped[str | None] = mapped_column(String(120))
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)


class PredictionAssignment(Base):
    __tablename__ = "prediction_assignment"
    __table_args__ = (UniqueConstraint("prediction_shipment_id", name="uq_prediction_assignment_shipment"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_shipment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_shipment.id", ondelete="CASCADE"), index=True
    )
    original_vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    original_assignment_score: Mapped[float | None] = mapped_column(Float)
    final_vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    final_assignment_score: Mapped[float | None] = mapped_column(Float)
    assignment_status: Mapped[str] = mapped_column(String(40), default="UNASSIGNED")
    unassigned_reason: Mapped[str | None] = mapped_column(String(80))
    override_reason: Mapped[str | None] = mapped_column(Text)
    override_user: Mapped[str | None] = mapped_column(String(120))
    override_timestamp = mapped_column(DateTime(timezone=True), nullable=True)


class PredictionTrip(Base):
    __tablename__ = "prediction_trip"
    __table_args__ = (
        UniqueConstraint("prediction_shipment_id", name="uq_prediction_trip_shipment"),
        UniqueConstraint("prediction_run_id", "trip_id", name="uq_prediction_trip_run_number"),
        Index("ix_prediction_trip_vehicle_departure", "vehicle_id", "predicted_departure_datetime"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_run.id", ondelete="CASCADE"), index=True
    )
    prediction_shipment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("prediction_shipment.id", ondelete="CASCADE"), index=True
    )
    trip_id: Mapped[str] = mapped_column(String(120), index=True)
    trip_number: Mapped[int | None] = mapped_column(Integer)
    vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    planned_start_datetime = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    predicted_departure_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    estimated_visit_sequence: Mapped[list] = mapped_column(JSON, default=list)
    routing_provider: Mapped[str | None] = mapped_column(String(80))
    routing_mode: Mapped[str | None] = mapped_column(String(40))
    routing_preference: Mapped[str | None] = mapped_column(String(40))
    large_vehicle_used: Mapped[bool] = mapped_column(Boolean, default=False)
    route_distance_meters: Mapped[int | None] = mapped_column(Integer)
    route_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    static_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    service_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    turnaround_buffer_seconds: Mapped[int | None] = mapped_column(Integer)
    total_cycle_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    estimated_return_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    next_available_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    routing_confidence: Mapped[str | None] = mapped_column(String(20))
    route_estimation_source: Mapped[str | None] = mapped_column(String(80))
    route_geometry: Mapped[list] = mapped_column(JSON, default=list)
    route_geometry_source: Mapped[str | None] = mapped_column(String(80))
    service_time_source: Mapped[str | None] = mapped_column(String(80))
    assignment_status: Mapped[str] = mapped_column(String(40), default="UNASSIGNED")
    unassigned_reason: Mapped[str | None] = mapped_column(String(120))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    warning_codes: Mapped[list] = mapped_column(JSON, default=list)
    vehicle_profile_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class GoogleRoutesConfiguration(Base):
    __tablename__ = "google_routes_configuration"

    configuration_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    key_fingerprint: Mapped[str | None] = mapped_column(String(64))
    masked_api_key: Mapped[str | None] = mapped_column(String(40))
    connection_status: Mapped[str] = mapped_column(String(40), default="NOT_CONFIGURED")
    truck_routing_status: Mapped[str] = mapped_column(String(40), default="DISABLED_FOR_INDONESIA")
    routing_mode: Mapped[str] = mapped_column(String(20), default="DRIVE")
    routing_preference: Mapped[str] = mapped_column(String(40), default="TRAFFIC_AWARE")
    fallback_policy: Mapped[str] = mapped_column(String(50), default="NOT_APPLICABLE")
    cache_ttl_minutes: Mapped[int] = mapped_column(Integer, default=60)
    departure_time_bucket_minutes: Mapped[int] = mapped_column(Integer, default=15)
    default_depot_processing_minutes: Mapped[int] = mapped_column(Integer, default=30)
    default_spbu_service_minutes: Mapped[int] = mapped_column(Integer, default=45)
    default_return_processing_minutes: Mapped[int] = mapped_column(Integer, default=15)
    default_turnaround_buffer_minutes: Mapped[int] = mapped_column(Integer, default=30)
    default_route_duration_minutes: Mapped[int] = mapped_column(Integer, default=120)
    configuration_version: Mapped[int] = mapped_column(Integer, default=1)
    last_test_result: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RouteEstimationCache(Base):
    __tablename__ = "route_estimation_cache"
    __table_args__ = (
        Index("ix_route_cache_expires", "expires_at"),
        Index("ix_route_cache_locations_mode", "origin_location_id", "destination_location_id", "routing_mode"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    origin_location_id: Mapped[str] = mapped_column(String(120))
    destination_location_id: Mapped[str] = mapped_column(String(120))
    origin_latitude: Mapped[float] = mapped_column(Float)
    origin_longitude: Mapped[float] = mapped_column(Float)
    destination_latitude: Mapped[float] = mapped_column(Float)
    destination_longitude: Mapped[float] = mapped_column(Float)
    departure_time_bucket = mapped_column(DateTime(timezone=True), nullable=True)
    vehicle_profile_hash: Mapped[str] = mapped_column(String(64))
    routing_mode: Mapped[str] = mapped_column(String(40))
    routing_preference: Mapped[str] = mapped_column(String(40))
    distance_meters: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    static_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    provider_source: Mapped[str] = mapped_column(String(80))
    response_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issue"

    issue_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    source_import_id: Mapped[str | None] = mapped_column(String(64))
    rule_code: Mapped[str] = mapped_column(String(120))
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="OPEN")
    detected_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at = mapped_column(DateTime(timezone=True), nullable=True)


# Phase 7 intentionally keeps operational optimization state separate from the
# immutable Phase 6 prediction tables above.  JSON columns are used for exact
# solver/configuration snapshots, while the relational result tables support
# dispatcher drill-down and version-to-version comparison.
class OptimizationJob(Base):
    __tablename__ = "optimization_job"
    __table_args__ = (
        Index("ix_optimization_job_depot_date", "depot_id", "operating_date"),
        Index("ix_optimization_job_depot_status", "depot_id", "status"),
    )

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_no: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    job_name: Mapped[str] = mapped_column(String(255))
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    operating_date = mapped_column(Date, nullable=False, index=True)
    source_prediction_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("prediction_run.id"), nullable=True, index=True
    )
    current_route_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    depot_operational_start = mapped_column(Time, nullable=False, default=lambda: time(0, 0))
    depot_operational_end = mapped_column(Time, nullable=False, default=lambda: time(23, 59))
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)


class OperationalStateSnapshot(Base):
    __tablename__ = "operational_state_snapshot"

    state_snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True
    )
    snapshot_reason: Mapped[str] = mapped_column(String(80))
    captured_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    captured_by: Mapped[str] = mapped_column(String(120), default="local-user")
    lo_state_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    vehicle_state_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    bay_state_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    queue_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    audit_events: Mapped[list] = mapped_column(JSON, default=list)


class OptimizationParameterProfile(Base):
    __tablename__ = "optimization_parameter_profile"
    __table_args__ = (
        UniqueConstraint("profile_name", "version", name="uq_optimization_parameter_profile_name_version"),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class OptimizationParameterValue(Base):
    __tablename__ = "optimization_parameter_value"
    __table_args__ = (
        UniqueConstraint("profile_id", "parameter_key", name="uq_optimization_parameter_value_key"),
    )

    parameter_value_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_parameter_profile.profile_id", ondelete="CASCADE"), index=True
    )
    parameter_key: Mapped[str] = mapped_column(String(120))
    parameter_value: Mapped[dict] = mapped_column(JSON, default=dict)


class OptimizationVehicleCostRule(Base):
    __tablename__ = "optimization_vehicle_cost_rule"

    cost_rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_parameter_profile.profile_id", ondelete="CASCADE"), index=True
    )
    vehicle_class: Mapped[int | None] = mapped_column(Integer)
    vehicle_tag: Mapped[str | None] = mapped_column(String(160))
    activation_cost: Mapped[float] = mapped_column(Float, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class OptimizationParameterSnapshot(Base):
    __tablename__ = "optimization_parameter_snapshot"

    parameter_snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True
    )
    source_profile_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("optimization_parameter_profile.profile_id"))
    source_profile_version: Mapped[int | None] = mapped_column(Integer)
    effective_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    parameter_checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")


class RouteVersion(Base):
    __tablename__ = "route_version"
    __table_args__ = (
        UniqueConstraint("job_id", "version_number", name="uq_route_version_job_number"),
        Index("ix_route_version_job_created", "job_id", "created_at"),
    )

    route_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str] = mapped_column(String(80))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    reason: Mapped[str] = mapped_column(String(160))
    state_snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("operational_state_snapshot.state_snapshot_id"))
    parameter_snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("optimization_parameter_snapshot.parameter_snapshot_id"))
    objective: Mapped[str] = mapped_column(String(60))
    solver_status: Mapped[str] = mapped_column(String(30))
    objective_value: Mapped[float | None] = mapped_column(Float)
    first_gate_out = mapped_column(DateTime(timezone=True), nullable=True)
    last_gate_out = mapped_column(DateTime(timezone=True), nullable=True)
    depot_dispatch_span_minutes: Mapped[int] = mapped_column(Integer, default=0)
    summary_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    comparison_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class OptimizationRun(Base):
    __tablename__ = "optimization_run"
    __table_args__ = (Index("ix_optimization_run_job_started", "job_id", "start_time"),)

    optimization_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True
    )
    run_type: Mapped[str] = mapped_column(String(30), default="INITIAL")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    route_version_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("route_version.route_version_id"))
    state_snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("operational_state_snapshot.state_snapshot_id"))
    parameter_snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("optimization_parameter_snapshot.parameter_snapshot_id"))
    optimization_reference_time = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    start_time = mapped_column(DateTime(timezone=True), nullable=True)
    end_time = mapped_column(DateTime(timezone=True), nullable=True)
    solve_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    solver_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    objective: Mapped[str] = mapped_column(String(60))
    objective_value: Mapped[float | None] = mapped_column(Float)
    coordination_iterations: Mapped[int] = mapped_column(Integer, default=0)
    solver_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class LOOperationalState(Base):
    __tablename__ = "lo_operational_state"
    __table_args__ = (
        UniqueConstraint("job_id", "loading_order_id", name="uq_lo_operational_state_job_lo"),
        Index("ix_lo_operational_state_job_status", "job_id", "status"),
    )

    lo_state_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True
    )
    loading_order_id: Mapped[str] = mapped_column(String(120), index=True)
    shift_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shift_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shift_gate_out_deadline = mapped_column(DateTime(timezone=True), nullable=True)
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    spbu_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    product_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    volume_kl: Mapped[float] = mapped_column(Float)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    operating_date = mapped_column(Date, nullable=False)
    source_prediction_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("prediction_run.id"))
    phase6_predicted_shipment_id: Mapped[str | None] = mapped_column(String(120), index=True)
    phase6_predicted_vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    phase6_predicted_spbu_pairing: Mapped[list] = mapped_column(JSON, default=list)
    phase6_shipment_confidence: Mapped[float | None] = mapped_column(Float)
    phase6_vehicle_assignment_confidence: Mapped[float | None] = mapped_column(Float)
    phase6_model_id: Mapped[str | None] = mapped_column(String(64))
    current_vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    current_trip_number: Mapped[int | None] = mapped_column(Integer)
    current_shipment_id: Mapped[str | None] = mapped_column(String(120))
    current_compartment_id: Mapped[str | None] = mapped_column(String(80))
    planned_gate_out = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    frozen_reason: Mapped[str | None] = mapped_column(String(80))
    actual_gate_out = mapped_column(DateTime(timezone=True), nullable=True)
    actual_delivered_at = mapped_column(DateTime(timezone=True), nullable=True)
    user_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(120))


class VehicleOperationalState(Base):
    __tablename__ = "vehicle_operational_state"
    __table_args__ = (
        UniqueConstraint("job_id", "mt_id", name="uq_vehicle_operational_state_job_mt"),
        Index("ix_vehicle_operational_state_job_status", "job_id", "operational_status"),
    )

    vehicle_state_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True
    )
    mt_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    registration_snapshot: Mapped[str | None] = mapped_column(String(80))
    vehicle_class: Mapped[int | None] = mapped_column(Integer)
    tag_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    disabled_tag_ids: Mapped[list] = mapped_column(JSON, default=list)
    capacity_kl: Mapped[float] = mapped_column(Float, default=0)
    number_of_compartments: Mapped[int] = mapped_column(Integer, default=0)
    compartment_configuration: Mapped[list] = mapped_column(JSON, default=list)
    planned_eta_depot = mapped_column(DateTime(timezone=True), nullable=True)
    system_eta_depot = mapped_column(DateTime(timezone=True), nullable=True)
    user_eta_override = mapped_column(DateTime(timezone=True), nullable=True)
    effective_eta_depot = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    operational_status: Mapped[str] = mapped_column(String(30), default="PARKING_DEPOT")
    working_time_limit_minutes: Mapped[int] = mapped_column(Integer, default=720)
    working_time_used_minutes: Mapped[int] = mapped_column(Integer, default=0)
    working_time_remaining_minutes: Mapped[int] = mapped_column(Integer, default=720)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(120))


class ActualVehicleEvent(Base):
    __tablename__ = "actual_vehicle_event"

    vehicle_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True)
    mt_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    event_time = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="USER")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class MasterLoadingBay(Base):
    __tablename__ = "master_loading_bay"
    __table_args__ = (UniqueConstraint("depot_id", "bay_id", name="uq_master_loading_bay_depot_bay"),)

    master_bay_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    bay_id: Mapped[str] = mapped_column(String(80), index=True)
    bay_name: Mapped[str] = mapped_column(String(160))
    all_products_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    operational_start = mapped_column(Time, nullable=False, default=lambda: time(5, 0))
    operational_end = mapped_column(Time, nullable=False, default=lambda: time(22, 0))
    number_of_loading_arms: Mapped[int] = mapped_column(Integer, default=1)
    loading_mode: Mapped[str] = mapped_column(String(20), default="SEQUENTIAL")
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LoadingBayProductCompatibility(Base):
    __tablename__ = "loading_bay_product_compatibility"

    master_bay_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("master_loading_bay.master_bay_id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_product.product_id"), primary_key=True)


class ProductCompartmentLoadingDuration(Base):
    __tablename__ = "product_compartment_loading_duration"
    __table_args__ = (
        UniqueConstraint("depot_id", "product_id", name="uq_product_compartment_loading_duration"),
    )

    loading_duration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_product.product_id"), index=True)
    duration_minutes_per_compartment: Mapped[int] = mapped_column(Integer)
    active_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class ActualBayState(Base):
    __tablename__ = "actual_bay_state"
    __table_args__ = (UniqueConstraint("job_id", "master_bay_id", name="uq_actual_bay_state_job_bay"),)

    actual_bay_state_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True)
    master_bay_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_loading_bay.master_bay_id"), index=True)
    current_vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    current_compartment_id: Mapped[str | None] = mapped_column(String(80))
    current_product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    remaining_loading_minutes: Mapped[int] = mapped_column(Integer, default=0)
    actual_queue_length: Mapped[int] = mapped_column(Integer, default=0)
    state_effective_at = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="USER")
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(120))


class OptimizationInitialQueue(Base):
    __tablename__ = "optimization_initial_queue"
    __table_args__ = (
        UniqueConstraint("job_id", "master_bay_id", "queue_position", name="uq_optimization_initial_queue_position"),
    )

    initial_queue_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("optimization_job.job_id", ondelete="CASCADE"), index=True)
    master_bay_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_loading_bay.master_bay_id"), index=True)
    queue_position: Mapped[int] = mapped_column(Integer)
    vehicle_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    compartment_id: Mapped[str | None] = mapped_column(String(80))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    estimated_loading_duration_minutes: Mapped[int] = mapped_column(Integer)
    state_effective_at = mapped_column(DateTime(timezone=True), nullable=False)


class RouteVersionTrip(Base):
    __tablename__ = "route_version_trip"
    __table_args__ = (
        UniqueConstraint("route_version_id", "vehicle_id", "trip_number", name="uq_route_version_trip_vehicle_number"),
        Index("ix_route_version_trip_gate_out", "route_version_id", "gate_out"),
    )

    route_version_trip_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("route_version.route_version_id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    trip_number: Mapped[int] = mapped_column(Integer)
    shipment_id: Mapped[str] = mapped_column(String(120), index=True)
    vehicle_ready_at_depot = mapped_column(DateTime(timezone=True), nullable=False)
    queue_start = mapped_column(DateTime(timezone=True), nullable=True)
    loading_start = mapped_column(DateTime(timezone=True), nullable=True)
    loading_finish = mapped_column(DateTime(timezone=True), nullable=True)
    gate_out = mapped_column(DateTime(timezone=True), nullable=False)
    estimated_return_depot = mapped_column(DateTime(timezone=True), nullable=False)
    distance_meters: Mapped[int] = mapped_column(Integer, default=0)
    driving_seconds: Mapped[int] = mapped_column(Integer, default=0)
    service_seconds: Mapped[int] = mapped_column(Integer, default=0)
    queue_minutes: Mapped[int] = mapped_column(Integer, default=0)
    loading_minutes: Mapped[int] = mapped_column(Integer, default=0)
    operating_minutes: Mapped[int] = mapped_column(Integer, default=0)
    assignment_status: Mapped[str] = mapped_column(String(30), default="PLANNED")
    route_geometry: Mapped[list] = mapped_column(JSON, default=list)
    route_geometry_source: Mapped[str | None] = mapped_column(String(80))
    cost_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)


class RouteVersionStop(Base):
    __tablename__ = "route_version_stop"
    __table_args__ = (
        UniqueConstraint("route_version_trip_id", "sequence_number", name="uq_route_version_stop_sequence"),
    )

    route_version_stop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_version_trip_id: Mapped[str] = mapped_column(String(64), ForeignKey("route_version_trip.route_version_trip_id", ondelete="CASCADE"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    stop_type: Mapped[str] = mapped_column(String(30), default="SPBU")
    spbu_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    arrival_time = mapped_column(DateTime(timezone=True), nullable=True)
    departure_time = mapped_column(DateTime(timezone=True), nullable=True)
    service_minutes: Mapped[int] = mapped_column(Integer, default=0)
    distance_from_previous_meters: Mapped[int] = mapped_column(Integer, default=0)
    travel_from_previous_seconds: Mapped[int] = mapped_column(Integer, default=0)
    loading_order_ids: Mapped[list] = mapped_column(JSON, default=list)
    products: Mapped[list] = mapped_column(JSON, default=list)
    volume_kl: Mapped[float] = mapped_column(Float, default=0)


class RouteVersionLOAssignment(Base):
    __tablename__ = "route_version_lo_assignment"
    __table_args__ = (
        UniqueConstraint("route_version_id", "loading_order_id", name="uq_route_version_lo_assignment"),
        Index("ix_route_version_lo_status", "route_version_id", "assignment_status"),
    )

    route_version_lo_assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("route_version.route_version_id", ondelete="CASCADE"), index=True)
    route_version_trip_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("route_version_trip.route_version_trip_id", ondelete="CASCADE"), index=True)
    loading_order_id: Mapped[str] = mapped_column(String(120), index=True)
    vehicle_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_mt.mt_id"))
    trip_number: Mapped[int | None] = mapped_column(Integer)
    shipment_id: Mapped[str | None] = mapped_column(String(120))
    compartment_id: Mapped[str | None] = mapped_column(String(80))
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    volume_kl: Mapped[float] = mapped_column(Float)
    stop_sequence: Mapped[int | None] = mapped_column(Integer)
    planned_gate_out = mapped_column(DateTime(timezone=True), nullable=True)
    eta = mapped_column(DateTime(timezone=True), nullable=True)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    assignment_status: Mapped[str] = mapped_column(String(30), default="PLANNED")
    dropped_reason_code: Mapped[str | None] = mapped_column(String(80))
    dropped_reason_description: Mapped[str | None] = mapped_column(Text)
    phase6_deviation: Mapped[dict] = mapped_column(JSON, default=dict)


class RouteVersionVehicleAssignment(Base):
    __tablename__ = "route_version_vehicle_assignment"
    __table_args__ = (
        UniqueConstraint("route_version_id", "vehicle_id", name="uq_route_version_vehicle_assignment"),
    )

    route_version_vehicle_assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("route_version.route_version_id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    trip_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_kl: Mapped[float] = mapped_column(Float, default=0)
    total_distance_meters: Mapped[int] = mapped_column(Integer, default=0)
    total_operating_minutes: Mapped[int] = mapped_column(Integer, default=0)
    working_time_remaining_minutes: Mapped[int] = mapped_column(Integer, default=0)
    activation_cost: Mapped[float] = mapped_column(Float, default=0)
    system_eta_depot = mapped_column(DateTime(timezone=True), nullable=True)


class OptimizationBayAssignment(Base):
    __tablename__ = "optimization_bay_assignment"

    bay_assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("route_version.route_version_id", ondelete="CASCADE"), index=True)
    route_version_trip_id: Mapped[str] = mapped_column(String(64), ForeignKey("route_version_trip.route_version_trip_id", ondelete="CASCADE"), unique=True)
    master_bay_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_loading_bay.master_bay_id"), index=True)
    vehicle_ready_at_depot = mapped_column(DateTime(timezone=True), nullable=False)
    queue_start = mapped_column(DateTime(timezone=True), nullable=False)
    loading_start = mapped_column(DateTime(timezone=True), nullable=False)
    loading_finish = mapped_column(DateTime(timezone=True), nullable=False)
    gate_out = mapped_column(DateTime(timezone=True), nullable=False)
    queue_minutes: Mapped[int] = mapped_column(Integer, default=0)
    loading_minutes: Mapped[int] = mapped_column(Integer, default=0)


class OptimizationBayOperation(Base):
    __tablename__ = "optimization_bay_operation"
    __table_args__ = (
        Index("ix_optimization_bay_operation_bay_start", "master_bay_id", "loading_start"),
    )

    bay_operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bay_assignment_id: Mapped[str] = mapped_column(String(64), ForeignKey("optimization_bay_assignment.bay_assignment_id", ondelete="CASCADE"), index=True)
    master_bay_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_loading_bay.master_bay_id"), index=True)
    compartment_id: Mapped[str] = mapped_column(String(80))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    loading_start = mapped_column(DateTime(timezone=True), nullable=False)
    loading_finish = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    loading_mode: Mapped[str] = mapped_column(String(20), default="SEQUENTIAL")


class RouteMatrixCache(Base):
    __tablename__ = "route_matrix_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_phase7_route_matrix_cache_key"),
        Index("ix_phase7_route_matrix_cache_expiry", "expires_at"),
    )

    route_matrix_cache_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(128), index=True)
    origin_location_id: Mapped[str] = mapped_column(String(120))
    destination_location_id: Mapped[str] = mapped_column(String(120))
    departure_time_bucket = mapped_column(DateTime(timezone=True), nullable=True)
    route_vehicle_mode: Mapped[str] = mapped_column(String(30), default="GENERAL_VEHICLE")
    traffic_aware: Mapped[bool] = mapped_column(Boolean, default=True)
    distance_meters: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    route_polyline: Mapped[str | None] = mapped_column(Text)
    route_geometry: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(60), default="GOOGLE_ROUTES")
    response_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)


class RouteAPIRequestLog(Base):
    __tablename__ = "route_api_request_log"

    request_log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("optimization_job.job_id"), index=True)
    request_type: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(60), default="GOOGLE_ROUTES")
    request_fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    requested_pair_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


# Phase 9 persists immutable, read-only evaluations. Source identifiers are
# lineage snapshots rather than foreign keys so deleting an operational Phase 7
# workspace never destroys or blocks retained evaluation evidence.
class RouteAlignmentEvaluationRun(Base):
    __tablename__ = "route_alignment_evaluation_run"
    __table_args__ = (
        UniqueConstraint(
            "route_version_id",
            "source_bundle_checksum",
            "algorithm_version",
            name="uq_route_alignment_run_source",
        ),
        Index("ix_route_alignment_run_depot_created", "depot_id", "created_at"),
        Index("ix_route_alignment_run_route", "route_version_id", "created_at"),
    )

    evaluation_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_run_no: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    route_version_id: Mapped[str] = mapped_column(String(64), index=True)
    operating_date = mapped_column(Date, nullable=False, index=True)
    source_prediction_run_id: Mapped[str] = mapped_column(String(64), index=True)
    phase5_model_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PREPARING", index=True)
    source_bundle_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    source_bundle_checksum: Mapped[str] = mapped_column(String(64), index=True)
    summary_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    data_quality_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class RouteAlignmentEvaluationRow(Base):
    __tablename__ = "route_alignment_evaluation_row"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "route_version_lo_assignment_id",
            name="uq_route_alignment_row_assignment",
        ),
        Index("ix_route_alignment_row_run_gate", "evaluation_run_id", "planned_gate_out"),
        Index("ix_route_alignment_row_run_trip", "evaluation_run_id", "route_version_trip_id"),
        Index("ix_route_alignment_row_run_spbu", "evaluation_run_id", "spbu_id"),
    )

    evaluation_row_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("route_alignment_evaluation_run.evaluation_run_id", ondelete="CASCADE"),
        index=True,
    )
    route_version_lo_assignment_id: Mapped[str] = mapped_column(String(64))
    route_version_trip_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    loading_order_id: Mapped[str] = mapped_column(String(120), index=True)
    shipment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    trip_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignment_status: Mapped[str] = mapped_column(String(30), index=True)
    planned_gate_out = mapped_column(DateTime(timezone=True), nullable=True)
    spbu_id: Mapped[str] = mapped_column(String(64), index=True)
    spbu_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    spbu_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    volume_kl: Mapped[float] = mapped_column(Float, default=0.0)
    vehicle_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    vehicle_registration: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cluster_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cluster_assignment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    route_shift_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    route_shift_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cluster_cohesion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cluster_cohesion_status: Mapped[str] = mapped_column(String(40), default="NOT_EVALUATED")
    cluster_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    shift_alignment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    shift_alignment_status: Mapped[str] = mapped_column(String(40), default="NOT_EVALUATED")
    shift_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    spbu_pairing_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spbu_pairing_status: Mapped[str] = mapped_column(String(40), default="NOT_EVALUATED")
    pairing_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    mt_affinity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    mt_affinity_status: Mapped[str] = mapped_column(String(40), default="NOT_EVALUATED")
    mt_affinity_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    evaluable_category_count: Mapped[int] = mapped_column(Integer, default=0)
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class RouteAlignmentPairEvidence(Base):
    __tablename__ = "route_alignment_pair_evidence"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "route_version_trip_id",
            "spbu_a_id",
            "spbu_b_id",
            name="uq_route_alignment_pair_trip",
        ),
        Index("ix_route_alignment_pair_run_trip", "evaluation_run_id", "route_version_trip_id"),
    )

    pair_evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("route_alignment_evaluation_run.evaluation_run_id", ondelete="CASCADE"),
        index=True,
    )
    route_version_trip_id: Mapped[str] = mapped_column(String(64))
    spbu_a_id: Mapped[str] = mapped_column(String(64))
    spbu_b_id: Mapped[str] = mapped_column(String(64))
    cluster_a_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cluster_b_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    same_cluster: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    probability_b_given_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_a_given_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    symmetric_pairing_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pair_count: Mapped[int] = mapped_column(Integer, default=0)
    shipment_a_count: Mapped[int] = mapped_column(Integer, default=0)
    shipment_b_count: Mapped[int] = mapped_column(Integer, default=0)
    support: Mapped[float] = mapped_column(Float, default=0.0)
    lift: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_DATA")
    evidence_status: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_EVIDENCE")
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


# Phase 8 is a mutable, versioned working snapshot. It references Phase 6/7
# through lineage values only and never owns or changes source records.
class ManualDispatchJob(Base):
    __tablename__ = "manual_dispatch_job"
    __table_args__ = (
        Index("ix_manual_dispatch_job_depot_date", "depot_id", "operational_date"),
        Index("ix_manual_dispatch_job_status_updated", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    job_name: Mapped[str] = mapped_column(String(255))
    depot_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_depot.depot_id"), index=True)
    operational_date = mapped_column(Date, nullable=False, index=True)
    source_phase: Mapped[str] = mapped_column(String(20))
    source_job_id: Mapped[str] = mapped_column(String(64), index=True)
    source_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_route_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_route_version: Mapped[str] = mapped_column(String(80))
    source_created_at = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_version: Mapped[int] = mapped_column(Integer, default=1)
    parent_dispatch_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("manual_dispatch_job.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    configuration_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    source_lineage_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finalized_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    finalized_at = mapped_column(DateTime(timezone=True), nullable=True)


class ManualDispatchVehicle(Base):
    __tablename__ = "manual_dispatch_vehicle"
    __table_args__ = (UniqueConstraint("dispatch_job_id", "mt_id", name="uq_manual_dispatch_vehicle_job_mt"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dispatch_job_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_job.id", ondelete="CASCADE"), index=True)
    mt_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_mt.mt_id"), index=True)
    vehicle_registration: Mapped[str | None] = mapped_column(String(80))
    vehicle_class: Mapped[int | None] = mapped_column(Integer)
    capacity_kl: Mapped[float] = mapped_column(Float, default=0)
    mt_tags: Mapped[list] = mapped_column(JSON, default=list)
    number_of_compartments: Mapped[int] = mapped_column(Integer, default=0)
    compartment_configuration: Mapped[list] = mapped_column(JSON, default=list)
    initial_available_datetime = mapped_column(DateTime(timezone=True), nullable=False)
    last_available_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="IDLE")


class ManualDispatchLoadingOrder(Base):
    __tablename__ = "manual_dispatch_loading_order"
    __table_args__ = (
        UniqueConstraint("dispatch_job_id", "lo_id", name="uq_manual_dispatch_scope_job_lo"),
        Index("ix_manual_dispatch_scope_status", "dispatch_job_id", "assignment_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dispatch_job_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_job.id", ondelete="CASCADE"), index=True)
    lo_id: Mapped[str] = mapped_column(String(120), index=True)
    lo_number: Mapped[str] = mapped_column(String(120))
    spbu_id: Mapped[str] = mapped_column(String(64), ForeignKey("master_spbu.spbu_id"), index=True)
    spbu_number: Mapped[str | None] = mapped_column(String(120))
    spbu_name: Mapped[str | None] = mapped_column(String(255))
    product_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("master_product.product_id"))
    product_name: Mapped[str | None] = mapped_column(String(255))
    volume_kl: Mapped[float] = mapped_column(Float)
    cluster_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cluster_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shift_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shift_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    spbu_tags: Mapped[list] = mapped_column(JSON, default=list)
    assignment_status: Mapped[str] = mapped_column(String(30), default="UNASSIGNED", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    source_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManualDispatchTrip(Base):
    __tablename__ = "manual_dispatch_trip"
    __table_args__ = (
        UniqueConstraint("dispatch_vehicle_id", "trip_sequence", name="uq_manual_dispatch_trip_sequence"),
        Index("ix_manual_dispatch_trip_departure", "dispatch_vehicle_id", "departure_datetime"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dispatch_vehicle_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_vehicle.id", ondelete="CASCADE"), index=True)
    trip_sequence: Mapped[int] = mapped_column(Integer)
    available_before_trip_datetime = mapped_column(DateTime(timezone=True), nullable=False)
    departure_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_return_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    turnaround_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    available_after_trip_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    distance_meter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    travel_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    operational_buffer_seconds: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_volume_kl: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    route_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    route_response_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    route_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_geometry: Mapped[list] = mapped_column(JSON, default=list)
    route_calculated_at = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ManualDispatchTripLO(Base):
    __tablename__ = "manual_dispatch_trip_lo"
    __table_args__ = (
        UniqueConstraint("dispatch_job_id", "manual_dispatch_lo_id", name="uq_manual_dispatch_lo_assignment"),
        Index("ix_manual_dispatch_trip_lo_trip_stop", "trip_id", "stop_sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dispatch_job_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_job.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_trip.id", ondelete="CASCADE"), index=True)
    manual_dispatch_lo_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_loading_order.id", ondelete="CASCADE"), index=True)
    stop_sequence: Mapped[int] = mapped_column(Integer)
    estimated_arrival_datetime = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManualDispatchRouteLeg(Base):
    __tablename__ = "manual_dispatch_route_leg"
    __table_args__ = (UniqueConstraint("trip_id", "leg_sequence", name="uq_manual_dispatch_route_leg_sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_trip.id", ondelete="CASCADE"), index=True)
    leg_sequence: Mapped[int] = mapped_column(Integer)
    origin_type: Mapped[str] = mapped_column(String(30))
    origin_id: Mapped[str] = mapped_column(String(120))
    destination_type: Mapped[str] = mapped_column(String(30))
    destination_id: Mapped[str] = mapped_column(String(120))
    origin_lat: Mapped[float] = mapped_column(Float)
    origin_lng: Mapped[float] = mapped_column(Float)
    destination_lat: Mapped[float] = mapped_column(Float)
    destination_lng: Mapped[float] = mapped_column(Float)
    distance_meter: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    traffic_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route_provider: Mapped[str] = mapped_column(String(80))
    request_timestamp = mapped_column(DateTime(timezone=True), nullable=False)
    response_status: Mapped[str] = mapped_column(String(80))
    calculated_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManualDispatchAuditLog(Base):
    __tablename__ = "manual_dispatch_audit_log"
    __table_args__ = (Index("ix_manual_dispatch_audit_job_created", "dispatch_job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dispatch_job_id: Mapped[str] = mapped_column(String(64), ForeignKey("manual_dispatch_job.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(120))
    old_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    new_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# Phase 10 owns integration credentials, logical synchronization versions, and
# an audit trail only. Operational/master records remain owned by their
# canonical Phase 0/7/8 tables and are exposed through read adapters.
class IntegrationClient(Base):
    __tablename__ = "integration_client"
    __table_args__ = (
        UniqueConstraint("integration_name", "client_code", name="uq_integration_client_name_code"),
        Index("ix_integration_client_active", "integration_name", "active"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    integration_name: Mapped[str] = mapped_column(String(80), index=True)
    client_name: Mapped[str] = mapped_column(String(160))
    client_code: Mapped[str] = mapped_column(String(80), index=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    token_hint: Mapped[str | None] = mapped_column(String(24), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[list] = mapped_column(JSON, default=lambda: ["read"])
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    token_created_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), default="local-user")


class IntegrationDatasetVersion(Base):
    __tablename__ = "integration_dataset_version"
    __table_args__ = (
        UniqueConstraint("integration_name", "dataset_name", name="uq_integration_dataset_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    integration_name: Mapped[str] = mapped_column(String(80), index=True)
    dataset_name: Mapped[str] = mapped_column(String(80), index=True)
    data_version: Mapped[str] = mapped_column(String(80))
    last_updated_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IntegrationAPILog(Base):
    __tablename__ = "integration_api_log"
    __table_args__ = (
        Index("ix_integration_api_log_requested", "integration_name", "requested_at"),
        Index("ix_integration_api_log_status", "integration_name", "response_status"),
        Index("ix_integration_api_log_client_requested", "client_id", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    integration_name: Mapped[str] = mapped_column(String(80), index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("integration_client.id"), nullable=True, index=True)
    http_method: Mapped[str] = mapped_column(String(12))
    endpoint: Mapped[str] = mapped_column(String(500), index=True)
    query_params: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_at = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    response_status: Mapped[int] = mapped_column(Integer, index=True)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
