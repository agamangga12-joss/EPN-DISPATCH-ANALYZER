from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import (
    BridgeMTTag,
    BridgeSPBUTag,
    DataQualityIssue,
    DepotGeofence,
    DepotIdentifierAlias,
    FactLoadingOrderLine,
    FactShipment,
    FactShipmentSPBU,
    ImportAudit,
    MasterDepot,
    MasterMT,
    MasterProduct,
    MasterSPBU,
    MasterTag,
    MasterTagType,
    ProductAlias,
    SpbuGeofence,
    SpbuIdentifierAlias,
    StgGPSData,
    StgLoadingOrder,
    StgMT,
    StgSPBU,
    TagAlias,
)
from .master_data import consolidate_master, refresh_historical_travel_times, rebuild_shipment_membership
from .normalization import (
    clean_str,
    combine_datetime,
    dataframe_records,
    file_sha256,
    infer_tag_type,
    make_id,
    normalize_key,
    normalize_product,
    parse_coordinate,
    parse_mt_name,
    resolve_sheet_name,
    source_int,
    source_number,
    source_time,
    split_project_tags,
)

TAG_TYPES = {
    "PROGRAM": "Program",
    "ACCESS": "Access",
    "REGION": "Region",
    "GEOGRAPHY": "Geography",
    "PROJECT": "Project",
    "VEHICLE_CLASS": "Vehicle Class",
    "SPECIAL_RESTRICTION": "Special Restriction",
    "PRODUCT_COMPATIBILITY": "Product Compatibility",
    "UNKNOWN": "Unknown",
}


def row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if clean_str(value) is not None:
            return value
    return None


class ImportProcessor:
    def __init__(self, db: Session, depot_id: str | None = None):
        self.db = db
        self.depot_id = depot_id

    def scope_rows(self, rows: list[dict]) -> list[dict]:
        if not self.depot_id:
            return rows
        depot = self.db.get(MasterDepot, self.depot_id)
        if not depot or depot.active_status != "ACTIVE":
            raise ValueError("Pilih depot aktif yang valid sebelum upload.")
        # Capture the upload context; source files cannot override this depot.
        return [{**row, "depot_id": depot.depot_id, "source_depot_name": depot.depot_name} for row in rows]

    @staticmethod
    def shipment_datetime(row: dict, field: str, date_keys: tuple, time_keys: tuple, depot: MasterDepot):
        value = row_value(row, field)
        if value is not None:
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed):
                raise ValueError(f"{field} harus berformat YYYY-MM-DD HH:MM:SS")
            result = parsed.to_pydatetime()
        else:
            result = combine_datetime(row_value(row, *date_keys), row_value(row, *time_keys))
        if result is not None and result.tzinfo is None:
            result = result.replace(tzinfo=ZoneInfo(depot.timezone or "Asia/Jakarta"))
        return result

    def upsert_active(self, model, primary_key: str, values: dict):
        record = self.db.get(model, primary_key)
        if record is None:
            record = model(**values)
            consolidate_master(record)
            self.db.add(record)
            return record
        for field, value in values.items():
            setattr(record, field, value)
        consolidate_master(record)
        return record

    def validate_required_columns(self, rows: list[dict[str, Any]], domain: str, required_columns: tuple[str, ...]) -> None:
        columns = set(rows[0].keys()) if rows else set()
        missing = [column for column in required_columns if column not in columns]
        if missing:
            raise ValueError(f"{domain} import columns do not match the selected domain. Missing columns: {', '.join(missing)}.")

    def validate_required_column_groups(
        self,
        rows: list[dict[str, Any]],
        domain: str,
        required_groups: tuple[tuple[str, ...], ...],
    ) -> None:
        columns = set(rows[0].keys()) if rows else set()
        missing = [aliases[0] for aliases in required_groups if not any(alias in columns for alias in aliases)]
        if missing:
            guidance = (
                " Buat Depot terlebih dahulu pada Master Data > Depot, lalu gunakan Depot ID yang dihasilkan sistem."
                if "depot_id" in missing
                else ""
            )
            raise ValueError(
                f"{domain} import columns do not match the selected domain. Missing columns: {', '.join(missing)}.{guidance}"
            )

    def validate_existing_depot_ids(self, rows: list[dict[str, Any]], domain: str) -> None:
        missing_rows = [index for index, row in enumerate(rows, start=2) if not clean_str(row.get("depot_id"))]
        supplied_ids = {clean_str(row.get("depot_id")) for row in rows if clean_str(row.get("depot_id"))}
        existing_ids = set(
            self.db.scalars(
                select(MasterDepot.depot_id).where(
                    MasterDepot.depot_id.in_(supplied_ids),
                    MasterDepot.active_status != "DELETED",
                )
            ).all()
        ) if supplied_ids else set()
        unknown_ids = sorted(supplied_ids - existing_ids)
        if not missing_rows and not unknown_ids:
            return
        problems: list[str] = []
        if missing_rows:
            preview = ", ".join(map(str, missing_rows[:10]))
            suffix = f" dan {len(missing_rows) - 10} baris lainnya" if len(missing_rows) > 10 else ""
            problems.append(f"depot_id kosong pada baris {preview}{suffix}")
        if unknown_ids:
            preview = ", ".join(unknown_ids[:10])
            suffix = f" dan {len(unknown_ids) - 10} ID lainnya" if len(unknown_ids) > 10 else ""
            problems.append(f"depot_id belum terdaftar atau sudah dihapus: {preview}{suffix}")
        raise ValueError(
            f"{domain} import gagal: {'; '.join(problems)}. "
            "Buat Depot terlebih dahulu pada Master Data > Depot, lalu gunakan Depot ID yang dihasilkan sistem."
        )

    def import_examples(self, example_dir: Path) -> dict[str, str]:
        results = {
            "mt": self.import_master_mt(example_dir / "master data MT.xlsx"),
            "spbu": self.import_master_spbu(example_dir / "master data spbu.xlsx"),
            "loading_order": self.import_loading_order(example_dir / "masterdata_LO.xlsx"),
        }
        self.ensure_geofences()
        self.db.commit()
        return results

    def create_import(
        self,
        domain: str,
        path: Path,
        sheet_name: str,
        uploaded_by: str = "system",
        filename: str | None = None,
        existing_import_id: str | None = None,
    ) -> ImportAudit:
        if existing_import_id:
            audit = self.db.get(ImportAudit, existing_import_id)
            if not audit:
                raise ValueError("Queued import audit was not found.")
            audit.status = "PROCESSING"
            audit.mapping_version = "phase0.v3"
            audit.started_at = audit.started_at or datetime.now(UTC)
            audit.error_message = None
            self.db.flush()
            return audit
        import_id = make_id("imp", domain, path.name, file_sha256(path), sheet_name, datetime.now(UTC).isoformat())
        audit = ImportAudit(
            import_id=import_id,
            domain=domain,
            filename=filename or path.name,
            file_checksum=file_sha256(path),
            sheet_name=sheet_name,
            uploaded_by=uploaded_by,
            status="STAGED",
            mapping_version="phase0.v3",
            depot_id=self.depot_id,
        )
        self.db.add(audit)
        self.db.flush()
        return audit

    def resolve_depot_reference(
        self,
        explicit_depot_id: Any,
        name: Any,
        code: Any,
        source_import_id: str,
        source_system: str,
        require_depot_id: bool,
    ) -> MasterDepot | None:
        depot_id = clean_str(explicit_depot_id)
        if depot_id:
            depot = self.db.get(MasterDepot, depot_id)
            if depot and depot.active_status != "DELETED":
                return depot
            return None
        if require_depot_id:
            return None
        return self.resolve_depot(name, code, source_import_id, source_system)

    def issue(self, entity_type: str, entity_id: str | None, import_id: str | None, rule_code: str, severity: str, description: str) -> None:
        self.db.merge(
            DataQualityIssue(
                issue_id=make_id("dqi", entity_type, entity_id, import_id, rule_code, description),
                entity_type=entity_type,
                entity_id=entity_id,
                source_import_id=import_id,
                rule_code=rule_code,
                severity=severity,
                description=description,
                status="OPEN",
            )
        )

    def ensure_tag_types(self) -> None:
        for code, name in TAG_TYPES.items():
            self.db.merge(MasterTagType(tag_type_id=make_id("tagtype", code), code=code, name=name, admin_editable=True))
        self.db.flush()

    def resolve_tag(self, value: str, source_domain: str) -> MasterTag:
        self.ensure_tag_types()
        normalized = normalize_key(value) or "UNKNOWN"
        alias = self.db.scalar(select(TagAlias).where(TagAlias.normalized_alias == normalized))
        if alias:
            tag = self.db.get(MasterTag, alias.canonical_tag_id)
            if tag:
                return tag
        tag_type_code = infer_tag_type(value)
        tag = MasterTag(
            tag_id=make_id("tag", normalized),
            tag_type_id=make_id("tagtype", tag_type_code),
            tag_value=value.strip(),
            normalized_tag=normalized,
            active_status="ACTIVE",
        )
        self.db.merge(tag)
        self.db.flush()
        aliases = {value}
        if normalized == "ALLIN":
            aliases.update({"All In", "ALL IN", "ALLIN"})
        seen_alias_ids: set[str] = set()
        for alias_value in aliases:
            alias_id = make_id("tagalias", normalize_key(alias_value), tag.tag_id, source_domain)
            if alias_id in seen_alias_ids:
                continue
            seen_alias_ids.add(alias_id)
            self.db.merge(
                TagAlias(
                    tag_alias_id=alias_id,
                    alias_value=alias_value,
                    normalized_alias=normalize_key(alias_value) or normalized,
                    canonical_tag_id=tag.tag_id,
                    source_domain=source_domain,
                )
            )
        return tag

    def resolve_depot(self, name: Any, code: Any, source_import_id: str, source_system: str) -> MasterDepot | None:
        depot_name = clean_str(name) or clean_str(code)
        if not depot_name:
            return None
        normalized_name = normalize_key(depot_name)
        depot_id = make_id("depot", normalized_name)
        depot = MasterDepot(depot_id=depot_id, depot_code=clean_str(code) or normalized_name, depot_name=depot_name, source_import_id=source_import_id)
        self.db.merge(depot)
        self.db.flush()
        for alias_type, alias_value in (("DEPOT_NAME", depot_name), ("DEPOT_CODE", clean_str(code))):
            if alias_value:
                self.db.merge(
                    DepotIdentifierAlias(
                        depot_identifier_alias_id=make_id("depotalias", depot_id, alias_type, alias_value),
                        depot_id=depot_id,
                        identifier_type=alias_type,
                        identifier_value=alias_value,
                        normalized_identifier=normalize_key(alias_value) or alias_value,
                        source_system=source_system,
                    )
                )
        return depot

    def import_master_mt(
        self,
        path: Path,
        sheet_name: str = "Mobil Tangki",
        filename: str | None = None,
        existing_import_id: str | None = None,
        require_depot_id: bool = False,
    ) -> str:
        actual_sheet_name = resolve_sheet_name(path, sheet_name, ("Mobil Tangki", "MOBIL_TANGKI"))
        audit = self.create_import("MOBIL_TANGKI", path, actual_sheet_name, filename=filename, existing_import_id=existing_import_id)
        rows = self.scope_rows(dataframe_records(path, actual_sheet_name))
        required_groups = (("depot_id",), ("vehicle_registration", "name", "vehicle_name_raw")) if require_depot_id else (("vehicle_registration", "name", "vehicle_name_raw"),)
        self.validate_required_column_groups(rows, "MOBIL_TANGKI", required_groups)
        if require_depot_id:
            self.validate_existing_depot_ids(rows, "MOBIL_TANGKI")
        valid = warnings = rejected = 0
        seen_registrations: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows, start=2):
            raw_name = clean_str(row_value(row, "vehicle_name_raw", "name"))
            parsed_registration, parsed_capacity, parse_messages = parse_mt_name(raw_name)
            registration = normalize_key(row_value(row, "vehicle_registration")) or parsed_registration
            capacity = clean_str(row_value(row, "capacity_label")) or parsed_capacity
            if registration and not raw_name:
                raw_name = registration
                parse_messages = []
            messages = list(parse_messages)
            if not registration:
                messages.append("missing normalized registration")
            depot = self.resolve_depot_reference(row.get("depot_id"), row.get("Depot"), None, audit.import_id, "MASTER_MT", require_depot_id)
            if not depot:
                messages.append("missing or unknown depot_id")
            identity = (depot.depot_id, registration) if depot and registration else None
            duplicate_identity = bool(identity and identity in seen_registrations)
            if duplicate_identity:
                messages.append("duplicate vehicle registration for depot_id in source import")
            if identity:
                seen_registrations.add(identity)
            normalized = {
                "source_mt_id": clean_str(row_value(row, "source_mt_id", "id")),
                "vehicle_name_raw": raw_name,
                "vehicle_registration": registration,
                "capacity_label": capacity,
                "vehicle_type_tag": source_int(row_value(row, "vehicle_type_tag", "vehicleType tag")),
                "project_tags": split_project_tags(row_value(row, "project_tag", "project_tag_raw")),
                "number_of_compartments": source_int(row_value(row, "number_of_compartments", "numberOfCompartments")),
                "depot_id": depot.depot_id if depot else None,
            }
            status = "REJECTED" if not registration or (require_depot_id and not depot) or duplicate_identity else "WARNING" if messages else "VALID"
            rejected += int(status == "REJECTED")
            warnings += int(status == "WARNING")
            valid += int(status == "VALID")
            self.db.add(StgMT(staging_id=make_id("stgmt", audit.import_id, row_number), import_id=audit.import_id, source_row_number=row_number, raw_payload=row, normalized_payload=normalized, validation_status=status, validation_messages=messages))
            if messages:
                self.issue("MT", registration, audit.import_id, "MT_NAME_PARSE", "WARNING", "; ".join(messages))
            if status == "REJECTED":
                continue
            mt_id = (
                make_id("mt", depot.depot_id, registration)
                if depot
                else make_id("mt", registration or raw_name or row_number)
            )
            self.upsert_active(
                MasterMT,
                mt_id,
                {
                    "mt_id": mt_id,
                    "source_mt_id": clean_str(row_value(row, "source_mt_id", "id")),
                    "vehicle_name_raw": raw_name or "",
                    "vehicle_registration": registration,
                    "capacity_label": capacity,
                    "vehicle_type_tag": source_int(row_value(row, "vehicle_type_tag", "vehicleType tag")),
                    "project_tag_raw": clean_str(row_value(row, "project_tag", "project_tag_raw")),
                    "number_of_compartments": source_int(row_value(row, "number_of_compartments", "numberOfCompartments")),
                    "depot_id": depot.depot_id if depot else None,
                    "source_hub_id": clean_str(row_value(row, "source_hub_id", "hubId")),
                    "assignee": clean_str(row.get("assignee")),
                    "active_status": clean_str(row.get("active_status")) or "ACTIVE",
                    "source_import_id": audit.import_id,
                },
            )
            self.db.flush()
            project_type_id = make_id("tagtype", "PROJECT")
            self.db.execute(
                delete(BridgeMTTag).where(
                    BridgeMTTag.mt_id == mt_id,
                    BridgeMTTag.tag_id.in_(select(MasterTag.tag_id).where(MasterTag.tag_type_id == project_type_id)),
                )
            )
            for tag_value in split_project_tags(row_value(row, "project_tag", "project_tag_raw")):
                tag = self.resolve_tag(tag_value, "MASTER_MT")
                self.db.merge(BridgeMTTag(mt_id=mt_id, tag_id=tag.tag_id, source_import_id=audit.import_id))
        audit.total_rows = len(rows)
        audit.valid_rows = valid
        audit.warning_rows = warnings
        audit.rejected_rows = rejected
        audit.processed_rows = len(rows)
        if audit.domain in {"SPBU", "LOADING_ORDER"}:
            refresh_historical_travel_times(self.db, self.depot_id)
        audit.status = "PUBLISHED"
        audit.published_at = datetime.now(UTC)
        audit.completed_at = audit.published_at
        self.db.commit()
        return audit.import_id

    def import_master_spbu(
        self,
        path: Path,
        sheet_name: str = "Lembaga Penyalur",
        filename: str | None = None,
        existing_import_id: str | None = None,
        require_depot_id: bool = False,
    ) -> str:
        actual_sheet_name = resolve_sheet_name(path, sheet_name, ("SPBU", "Lembaga Penyalur"))
        audit = self.create_import("SPBU", path, actual_sheet_name, filename=filename, existing_import_id=existing_import_id)
        rows = self.scope_rows(dataframe_records(path, actual_sheet_name))
        required_groups = (("depot_id",), ("spbu_code", "Nama SPBU")) if require_depot_id else (("spbu_code", "Nama SPBU"),)
        self.validate_required_column_groups(rows, "SPBU", required_groups)
        if require_depot_id:
            self.validate_existing_depot_ids(rows, "SPBU")
        valid = warnings = rejected = 0
        seen_codes: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows, start=2):
            code = clean_str(row_value(row, "spbu_code", "Nama SPBU"))
            source_coordinate = clean_str(row_value(row, "source_coordinate", "Coordinate"))
            lat = source_number(row.get("latitude"))
            lon = source_number(row.get("longitude"))
            parsed_lat, parsed_lon, coordinate_messages = parse_coordinate(source_coordinate)
            if lat is None:
                lat = parsed_lat
            if lon is None:
                lon = parsed_lon
            if lat is not None and lon is not None:
                coordinate_messages = []
            messages = list(coordinate_messages)
            if not code:
                messages.append("missing SPBU code")
            depot = self.resolve_depot_reference(row.get("depot_id"), row.get("Depot"), None, audit.import_id, "MASTER_SPBU", require_depot_id)
            if not depot:
                messages.append("missing or unknown depot_id")
            identity = (depot.depot_id, code) if depot and code else None
            duplicate_identity = bool(identity and identity in seen_codes)
            if duplicate_identity:
                messages.append("duplicate SPBU code for depot_id in source import")
            if identity:
                seen_codes.add(identity)
            normalized = {
                "spbu_code": code,
                "latitude": lat,
                "longitude": lon,
                "vehicle_type_tag": source_int(row_value(row, "vehicle_type_tag", "Vehicle Type tag")),
                "project_tags": split_project_tags(row_value(row, "project_tag", "project_tag_raw", "Project tag")),
                "depot_id": depot.depot_id if depot else None,
                "official_window_start": source_time(row_value(row, "official_window_start", "Official Window Start"), time(0, 0)).isoformat(timespec="minutes"),
                "official_window_end": source_time(row_value(row, "official_window_end", "Official Window End"), time(23, 59)).isoformat(timespec="minutes"),
            }
            status = "REJECTED" if not code or (require_depot_id and not depot) or duplicate_identity else "WARNING" if messages else "VALID"
            rejected += int(status == "REJECTED")
            warnings += int(status == "WARNING")
            valid += int(status == "VALID")
            self.db.add(StgSPBU(staging_id=make_id("stgspbu", audit.import_id, row_number), import_id=audit.import_id, source_row_number=row_number, raw_payload=row, normalized_payload=normalized, validation_status=status, validation_messages=messages))
            if messages:
                self.issue("SPBU", code, audit.import_id, "SPBU_SOURCE_VALIDATION", "WARNING", "; ".join(messages))
            if status == "REJECTED":
                continue
            spbu_id = make_id("spbu", depot.depot_id, code) if depot else make_id("spbu", code)
            self.upsert_active(
                MasterSPBU,
                spbu_id,
                {
                    "spbu_id": spbu_id,
                    "spbu_code": code,
                    "spbu_name": clean_str(row.get("spbu_name")) or code,
                    "address": clean_str(row_value(row, "address", "Address")),
                    "city": clean_str(row_value(row, "city", "Kota")),
                    "latitude": lat,
                    "longitude": lon,
                    "source_coordinate": source_coordinate,
                    "master_distance_km": source_number(row_value(row, "master_distance_km", "jarak_km")),
                    "master_travel_time_min": None,
                    "vehicle_type_tag": source_int(row_value(row, "vehicle_type_tag", "Vehicle Type tag")),
                    "project_tag_raw": clean_str(row_value(row, "project_tag", "project_tag_raw", "Project tag")),
                    "primary_depot_id": depot.depot_id if depot else None,
                    "active_status": clean_str(row.get("active_status")) or "ACTIVE",
                    "official_window_start": source_time(row_value(row, "official_window_start", "Official Window Start"), time(0, 0)),
                    "official_window_end": source_time(row_value(row, "official_window_end", "Official Window End"), time(23, 59)),
                    "source_import_id": audit.import_id,
                },
            )
            self.db.flush()
            project_type_id = make_id("tagtype", "PROJECT")
            self.db.execute(
                delete(BridgeSPBUTag).where(
                    BridgeSPBUTag.spbu_id == spbu_id,
                    BridgeSPBUTag.tag_id.in_(select(MasterTag.tag_id).where(MasterTag.tag_type_id == project_type_id)),
                )
            )
            self.db.merge(SpbuIdentifierAlias(spbu_identifier_alias_id=make_id("spbualias", spbu_id, "SPBU_CODE", code), spbu_id=spbu_id, identifier_type="SPBU_CODE", identifier_value=code, normalized_identifier=normalize_key(code) or code, source_system="MASTER_SPBU"))
            for tag_value in split_project_tags(row_value(row, "project_tag", "project_tag_raw", "Project tag")):
                tag = self.resolve_tag(tag_value, "MASTER_SPBU")
                self.db.merge(BridgeSPBUTag(spbu_id=spbu_id, tag_id=tag.tag_id, source_import_id=audit.import_id))
        audit.total_rows = len(rows)
        audit.valid_rows = valid
        audit.warning_rows = warnings
        audit.rejected_rows = rejected
        audit.processed_rows = len(rows)
        if audit.domain in {"SPBU", "LOADING_ORDER"}:
            refresh_historical_travel_times(self.db, self.depot_id)
        audit.status = "PUBLISHED"
        audit.published_at = datetime.now(UTC)
        audit.completed_at = audit.published_at
        self.db.commit()
        return audit.import_id

    def resolve_product(self, raw_product: Any, source_import_id: str) -> MasterProduct | None:
        product_name = clean_str(raw_product)
        normalized = normalize_product(raw_product)
        if not product_name or not normalized:
            return None
        product_id = make_id("product", normalized)
        self.db.merge(MasterProduct(product_id=product_id, product_name=product_name, normalized_product=normalized, source_import_id=source_import_id))
        self.db.flush()
        self.db.merge(ProductAlias(product_alias_id=make_id("productalias", normalized, "LO"), product_id=product_id, alias_value=product_name, normalized_alias=normalized, source_system="LO"))
        return self.db.get(MasterProduct, product_id) or MasterProduct(product_id=product_id, product_name=product_name, normalized_product=normalized)

    def import_loading_order(
        self,
        path: Path,
        sheet_name: str = "Data Medan Mei",
        filename: str | None = None,
        existing_import_id: str | None = None,
        require_depot_id: bool = False,
    ) -> str:
        actual_sheet_name = resolve_sheet_name(path, sheet_name, ("Historikal Shipment", "Data Medan Mei", "Loading Orders", "LOADING_ORDER"))
        audit = self.create_import("LOADING_ORDER", path, actual_sheet_name, filename=filename, existing_import_id=existing_import_id)
        rows = self.scope_rows(dataframe_records(path, actual_sheet_name))
        required_groups = (
            (("depot_id",), ("shipment_id",), ("loading_order_number",))
            if require_depot_id
            else (("shipment_id",), ("loading_order_number",), ("source_depot_name", "tbbm"))
        )
        self.validate_required_column_groups(rows, "LOADING_ORDER", required_groups)
        if require_depot_id:
            self.validate_existing_depot_ids(rows, "LOADING_ORDER")
        lo_depot_counts = Counter(
            (clean_str(row.get("loading_order_number")), clean_str(row.get("depot_id")) or clean_str(row_value(row, "source_depot_name", "tbbm")))
            for row in rows
            if clean_str(row.get("loading_order_number")) and (clean_str(row.get("depot_id")) or clean_str(row_value(row, "source_depot_name", "tbbm")))
        )
        by_shipment: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row_number, row in enumerate(rows, start=2):
            source_shipment_id = clean_str(row.get("shipment_id")) or f"row-{row_number}"
            by_shipment[source_shipment_id].append({"row_number": row_number, "row": row})
        mt_by_registration = {
            (mt.depot_id, mt.vehicle_registration): mt
            for mt in self.db.scalars(select(MasterMT)).all()
            if mt.depot_id and mt.vehicle_registration
        }
        spbu_by_code = {
            (spbu.primary_depot_id, spbu.spbu_code): spbu
            for spbu in self.db.scalars(select(MasterSPBU)).all()
            if spbu.primary_depot_id
        }
        valid = warnings = rejected = 0
        for source_shipment_id, grouped in by_shipment.items():
            first = grouped[0]["row"]
            registrations = {
                normalize_key(row_value(item["row"], "vehicle_registration", "nopol"))
                for item in grouped
                if normalize_key(row_value(item["row"], "vehicle_registration", "nopol"))
            }
            vehicle_registration = next(iter(registrations)) if registrations else None
            messages: list[str] = []
            if len(registrations) > 1:
                messages.append("shipment contains multiple nopol values")
            depot = self.resolve_depot_reference(
                first.get("depot_id"),
                row_value(first, "source_depot_name", "tbbm"),
                row_value(first, "depot_code", "kode_depot"),
                audit.import_id,
                "LO",
                require_depot_id,
            )
            mt = mt_by_registration.get((depot.depot_id, vehicle_registration)) if depot and vehicle_registration else None
            vehicle_status = "MATCHED" if mt else "UNMATCHED"
            if not mt:
                messages.append("unknown MT")
            if not depot:
                messages.append("unknown depot_id")
                for item in grouped:
                    row = item["row"]
                    row_number = item["row_number"]
                    lo_number = clean_str(row.get("loading_order_number"))
                    self.db.add(
                        StgLoadingOrder(
                            staging_id=make_id("stglo", audit.import_id, row_number),
                            import_id=audit.import_id,
                            source_row_number=row_number,
                            raw_payload=row,
                            normalized_payload={
                                "loading_order_id": None,
                                "depot_id": clean_str(row.get("depot_id")),
                                "shipment_id": source_shipment_id,
                                "source_depot_name": clean_str(row_value(row, "source_depot_name", "tbbm")),
                            },
                            validation_status="REJECTED",
                            validation_messages=["depot_id must reference an active Master Depot"],
                        )
                    )
                    self.issue(
                        "LO_LINE",
                        lo_number or f"row-{row_number}",
                        audit.import_id,
                        "UNKNOWN_DEPOT_ID",
                        "SEVERE",
                        "depot_id must reference an active Master Depot.",
                    )
                    rejected += 1
                continue
            validation_dt = self.shipment_datetime(first, "validation_datetime", ("validation_date", "date_validasi", "operating_date", "date"), ("validation_time", "Jam Validasi"), depot)
            gate_out_dt = self.shipment_datetime(first, "gate_out_datetime", ("gate_out_date", "date_gate_out"), ("gate_out_time", "Jam_gateout"), depot)
            end_dt = self.shipment_datetime(first, "shipment_end_datetime", ("shipment_end_date", "date_end_shipment"), ("shipment_end_time", "jam_end_shipment"), depot)
            driver_name = clean_str(row_value(first, "driver_name", "supir"))
            driver_nip = clean_str(row_value(first, "driver_nip", "nip_supir"))
            assistant_name = clean_str(row_value(first, "assistant_name", "kernet"))
            assistant_nip = clean_str(row_value(first, "assistant_nip", "nip_kernet"))
            if gate_out_dt and end_dt and end_dt < gate_out_dt:
                messages.append("shipment_end before gate_out")
            if validation_dt and gate_out_dt and gate_out_dt < validation_dt:
                messages.append("gate_out before validation")
            for keys, label in (
                (("driver_name", "supir"), "driver name"),
                (("driver_nip", "nip_supir"), "driver NIP"),
                (("assistant_name", "kernet"), "assistant name"),
                (("assistant_nip", "nip_kernet"), "assistant NIP"),
            ):
                values = {clean_str(row_value(item["row"], *keys)) for item in grouped if clean_str(row_value(item["row"], *keys))}
                if len(values) > 1:
                    messages.append(f"shipment contains multiple {label} values")
            end_values = {
                value
                for value in (
                    self.shipment_datetime(item["row"], "shipment_end_datetime", ("shipment_end_date", "date_end_shipment"), ("shipment_end_time", "jam_end_shipment"), depot)
                    for item in grouped
                )
                if value
            }
            if len(end_values) > 1:
                messages.append("shipment contains multiple endshipment values")
            shipment_pk = source_shipment_id
            existing = self.db.get(FactShipment, shipment_pk)
            if existing and existing.depot_id != depot.depot_id:
                raise ValueError(f"Shipment ID {source_shipment_id} sudah digunakan depot lain; gunakan ID shipment yang unik.")
            self.db.merge(
                FactShipment(
                    shipment_id=shipment_pk,
                    source_shipment_id=source_shipment_id,
                    operating_date=validation_dt.astimezone(ZoneInfo(depot.timezone or "Asia/Jakarta")).date() if validation_dt else None,
                    area_id=clean_str(first.get("area_id")),
                    area=clean_str(first.get("area")),
                    depot_id=depot.depot_id if depot else None,
                    mt_id=mt.mt_id if mt else None,
                    vehicle_registration=vehicle_registration,
                    vehicle_mapping_status=vehicle_status,
                    vehicle_type_tag_observed=clean_str(row_value(first, "vehicle_type_tag", "Vehicle Type tag")),
                    project_tag_raw=clean_str(row_value(first, "project_tag", "Project tag")),
                    validation_datetime=validation_dt,
                    gate_out_datetime=gate_out_dt,
                    shipment_end_datetime=end_dt,
                    driver_name=driver_name,
                    driver_nip=driver_nip,
                    assistant_name=assistant_name,
                    assistant_nip=assistant_nip,
                    status=clean_str(first.get("status")),
                    source_import_id=audit.import_id,
                )
            )
            self.db.flush()
            if messages:
                self.issue("SHIPMENT", source_shipment_id, audit.import_id, "LO_SHIPMENT_VALIDATION", "SEVERE" if len(registrations) > 1 else "WARNING", "; ".join(messages))
            for item in grouped:
                row = item["row"]
                row_number = item["row_number"]
                lo_number = clean_str(row.get("loading_order_number"))
                source_depot_name = depot.depot_name
                spbu_code = clean_str(row_value(row, "source_spbu_code", "spbu_code", "nama_spbu"))
                spbu = spbu_by_code.get((depot.depot_id, spbu_code)) if depot and spbu_code else None
                source_product_name = row_value(row, "source_product_name", "product_name", "produk")
                product = self.resolve_product(source_product_name, audit.import_id)
                row_messages = []
                row_rejected = False
                if not lo_number:
                    row_rejected = True
                    row_messages.append("missing loading_order_number")
                    self.issue("LO_LINE", f"row-{row_number}", audit.import_id, "MISSING_LOADING_ORDER_NUMBER", "SEVERE", "Loading order number is required as the canonical primary key.")
                if not source_depot_name:
                    row_rejected = True
                    row_messages.append("missing tbbm")
                    self.issue("LO_LINE", lo_number or f"row-{row_number}", audit.import_id, "MISSING_TBBM", "SEVERE", "Depot name tbbm is required because loading-order uniqueness is scoped by depot.")
                elif lo_depot_counts[(lo_number, clean_str(row.get("depot_id")) or source_depot_name)] > 1:
                    row_rejected = True
                    row_messages.append("duplicate loading_order_number for tbbm")
                    self.issue("LO_LINE", lo_number, audit.import_id, "DUPLICATE_LOADING_ORDER_NUMBER_DEPOT", "SEVERE", "Loading order number must be unique within the same tbbm/depot.")
                if not spbu:
                    row_messages.append("unknown SPBU")
                    self.issue("LO_LINE", lo_number, audit.import_id, "UNKNOWN_SPBU", "WARNING", f"LO SPBU {spbu_code} is not in master_spbu")
                if source_number(row.get("quantity")) is None or (source_number(row.get("quantity")) or 0) <= 0:
                    row_messages.append("invalid quantity")
                normalized = {
                    "loading_order_id": make_id("lo", depot.depot_id, lo_number) if depot and lo_number else None,
                    "depot_id": depot.depot_id if depot else None,
                    "shipment_id": source_shipment_id,
                    "source_depot_name": source_depot_name,
                    "vehicle_registration": vehicle_registration,
                    "vehicle_mapping_status": vehicle_status,
                    "spbu_code": spbu_code,
                    "spbu_mapping_status": "MATCHED" if spbu else "UNMATCHED",
                    "product": normalize_product(source_product_name),
                    "quantity": source_number(row.get("quantity")),
                }
                status = "REJECTED" if row_rejected else "WARNING" if row_messages or messages else "VALID"
                rejected += int(status == "REJECTED")
                warnings += int(status == "WARNING")
                valid += int(status == "VALID")
                self.db.add(StgLoadingOrder(staging_id=make_id("stglo", audit.import_id, row_number), import_id=audit.import_id, source_row_number=row_number, raw_payload=row, normalized_payload=normalized, validation_status=status, validation_messages=row_messages + messages))
                if row_rejected:
                    continue
                self.db.merge(
                    FactLoadingOrderLine(
                        loading_order_id=make_id("lo", depot.depot_id, lo_number),
                        loading_order_number=lo_number,
                        depot_id=depot.depot_id,
                        source_depot_name=source_depot_name,
                        shipment_id=shipment_pk,
                        spbu_id=spbu.spbu_id if spbu else None,
                        spbu_mapping_status="MATCHED" if spbu else "UNMATCHED",
                        source_spbu_code=spbu_code,
                        shipto=clean_str(row.get("shipto")),
                        product_id=product.product_id if product else None,
                        source_product_name=clean_str(source_product_name),
                        quantity=source_number(row.get("quantity")),
                        status=clean_str(row.get("status")),
                        source_distance_km=source_number(row_value(row, "actual_km", "km_aktual", "source_distance_km", "jarak_spbu")),
                        actual_km=source_number(row_value(row, "actual_km", "km_aktual", "source_distance_km", "jarak_spbu")),
                        source_import_id=audit.import_id,
                    )
                )
                if spbu:
                    self.db.merge(FactShipmentSPBU(shipment_id=shipment_pk, spbu_id=spbu.spbu_id, assignment_source="LO", source_import_id=audit.import_id))
                    shipto = clean_str(row.get("shipto"))
                    if shipto:
                        self.db.merge(SpbuIdentifierAlias(spbu_identifier_alias_id=make_id("spbualias", spbu.spbu_id, "SHIPTO", shipto), spbu_id=spbu.spbu_id, identifier_type="SHIPTO", identifier_value=shipto, normalized_identifier=normalize_key(shipto) or shipto, source_system="LO"))
        rebuild_shipment_membership(self.db, by_shipment.keys())
        audit.total_rows = len(rows)
        audit.valid_rows = valid
        audit.warning_rows = warnings
        audit.rejected_rows = rejected
        audit.processed_rows = len(rows)
        if audit.domain in {"SPBU", "LOADING_ORDER"}:
            refresh_historical_travel_times(self.db, self.depot_id)
        audit.status = "PUBLISHED"
        audit.published_at = datetime.now(UTC)
        audit.completed_at = audit.published_at
        self.db.commit()
        return audit.import_id

    def stage_gps_file(
        self,
        path: Path,
        sheet_name: str,
        filename: str | None = None,
        existing_import_id: str | None = None,
    ) -> str:
        actual_sheet_name = resolve_sheet_name(path, sheet_name, ("GPS", "GPS Data"))
        audit = self.create_import("GPS", path, actual_sheet_name, filename=filename, existing_import_id=existing_import_id)
        rows = self.scope_rows(dataframe_records(path, actual_sheet_name))
        self.validate_required_columns(rows, "GPS", ("vehicle_registration", "event_datetime"))
        for row_number, row in enumerate(rows, start=2):
            self.db.add(StgGPSData(staging_id=make_id("stggps", audit.import_id, row_number), import_id=audit.import_id, source_row_number=row_number, raw_payload=row, normalized_payload={}, validation_status="PENDING_MAPPING", validation_messages=["GPS physical schema requires source mapping review"]))
        audit.total_rows = len(rows)
        audit.processed_rows = len(rows)
        audit.status = "STAGED"
        audit.completed_at = datetime.now(UTC)
        self.db.commit()
        return audit.import_id

    def ensure_geofences(self) -> None:
        for spbu in self.db.scalars(select(MasterSPBU).where(MasterSPBU.latitude.is_not(None), MasterSPBU.longitude.is_not(None))).all():
            self.db.merge(SpbuGeofence(spbu_geofence_id=make_id("spbugeofence", spbu.spbu_id), spbu_id=spbu.spbu_id, radius_m=125.0))
        for depot in self.db.scalars(select(MasterDepot)).all():
            self.db.merge(DepotGeofence(depot_geofence_id=make_id("depotgeofence", depot.depot_id), depot_id=depot.depot_id, radius_m=300.0))

    def summary(self) -> dict[str, int]:
        tables = {
            "imports": ImportAudit,
            "mt": MasterMT,
            "spbu": MasterSPBU,
            "depots": MasterDepot,
            "products": MasterProduct,
            "tags": MasterTag,
            "tag_types": MasterTagType,
            "loading_order_lines": FactLoadingOrderLine,
            "shipments": FactShipment,
            "gps_events": StgGPSData,
            "gps_visits": SpbuGeofence,
            "data_quality_issues": DataQualityIssue,
        }
        return {name: self.db.scalar(select(func.count()).select_from(model)) or 0 for name, model in tables.items()}
