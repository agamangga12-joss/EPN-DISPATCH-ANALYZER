from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from io import BytesIO

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MasterDepot, OptimizationJob, VehicleOperationalState
from .phase7_constants import MT_STATUSES
from .phase7_service import _require_job, _timezone, update_vehicle_states

HEADERS = ("MT REGISTRATION", "OPERATIONAL STATUS", "PLANNED ETA DEPOT")


def _registration(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def readiness_template(db: Session, job_id: str) -> bytes:
    job = _require_job(db, job_id)
    zone = _timezone(db.get(MasterDepot, job.depot_id))
    vehicles = db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id).order_by(VehicleOperationalState.registration_snapshot, VehicleOperationalState.mt_id)).all()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "MT Readiness"
    sheet.append(HEADERS)
    for row in vehicles:
        eta = row.planned_eta_depot
        local_eta = (eta if eta.tzinfo else eta.replace(tzinfo=timezone.utc)).astimezone(zone).replace(tzinfo=None) if eta else None
        sheet.append([row.registration_snapshot or row.mt_id, row.operational_status, local_eta])
        sheet.cell(sheet.max_row, 1).data_type = "s"
        sheet.cell(sheet.max_row, 1).number_format = "@"
        sheet.cell(sheet.max_row, 3).number_format = "yyyy-mm-dd hh:mm:ss"
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="173B50")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in (("A", 26), ("B", 25), ("C", 30)):
        sheet.column_dimensions[column].width = width
    status_validation = DataValidation(type="list", formula1='"' + ",".join(sorted(MT_STATUSES)) + '"', allow_blank=True)
    status_validation.errorTitle = "Status tidak valid"
    status_validation.error = "Pilih status dari dropdown."
    status_validation.showErrorMessage = True
    status_validation.errorStyle = "stop"
    sheet.add_data_validation(status_validation)
    status_validation.add(f"B2:B{max(2, len(vehicles) + 1)}")
    guide = workbook.create_sheet("Petunjuk")
    for line in [
        "MT Readiness — " + job.job_no,
        "MT REGISTRATION otomatis diisi untuk seluruh MT yang sudah dimuat pada Job ini, seluruh halaman.",
        "OPERATIONAL STATUS: " + ", ".join(sorted(MT_STATUSES)),
        "READY = aktif/siap; UNAVAILABLE = tidak tersedia. Status lain mengikuti status operasional pada tabel.",
        f"PLANNED ETA DEPOT: tanggal dan jam zona waktu depot ({zone.key}).",
        "Gunakan sel tanggal Excel atau teks YYYY-MM-DD HH:MM:SS, contoh 2026-10-08 07:30:00.",
        "Kolom status dan ETA diisi dengan nilai tersimpan saat template diunduh; kolom kosong tidak mengubah nilai.",
        "Hapus baris MT yang tidak ingin diperbarui. Registrasi harus ada pada Job ini dan tidak boleh duplikat.",
        "Jika satu baris salah, seluruh upload dibatalkan. Formula Excel tidak didukung; gunakan nilai langsung.",
        "Upload langsung menyimpan perubahan ke MT Management; tidak perlu Apply MT Update lagi.",
    ]:
        guide.append([line])
        guide.cell(guide.max_row, 1).data_type = "s"
    guide.column_dimensions["A"].width = 115
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _eta(value: object, zone) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", value.strip()):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("Gunakan tanggal dan jam Excel atau YYYY-MM-DD HH:MM:SS.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc).isoformat()


def import_readiness(db: Session, job_id: str, content: bytes, filename: str) -> dict:
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(422, detail={"code": "INVALID_READINESS_FILE", "message": "Gunakan file Excel .xlsx sesuai template MT Readiness."})
    try:
        workbook = load_workbook(BytesIO(content), data_only=False, read_only=True)
    except Exception as exc:
        raise HTTPException(422, detail={"code": "INVALID_READINESS_FILE", "message": "File Excel tidak dapat dibaca. Gunakan template MT Readiness .xlsx."}) from exc
    try:
        job = _require_job(db, job_id)
        # Use the same job lock as optimization enqueue so readiness cannot
        # change while an optimization is taking its input snapshot.
        job = db.scalar(select(OptimizationJob).where(OptimizationJob.job_id == job.job_id).with_for_update().execution_options(populate_existing=True))
        if job.status == "CALCULATING":
            raise HTTPException(409, detail={"code": "PHASE7_JOB_CALCULATING", "message": "MT Readiness tidak dapat diimport saat Job sedang menghitung optimasi."})
        zone = _timezone(db.get(MasterDepot, job.depot_id))
        vehicles = db.scalars(select(VehicleOperationalState).where(VehicleOperationalState.job_id == job.job_id)).all()
        by_registration = defaultdict(list)
        for vehicle in vehicles:
            by_registration[_registration(vehicle.registration_snapshot or vehicle.mt_id)].append(vehicle)
        sheet = workbook["MT Readiness"] if "MT Readiness" in workbook.sheetnames else workbook.active
        rows = sheet.iter_rows()
        header_cells = next(rows, ())
        headers = [re.sub(r"[_\s]+", " ", str(cell.value or "").strip()).upper() for cell in header_cells]
        if any(headers.count(name) != 1 for name in HEADERS):
            raise HTTPException(422, detail={"code": "INVALID_READINESS_HEADERS", "message": "Header wajib (masing-masing satu kolom): " + ", ".join(HEADERS) + ". Gunakan template MT Readiness."})
        indexes = [headers.index(name) for name in HEADERS]
        errors, updates, seen = [], [], set()
        skipped = 0
        for number, cells in enumerate(rows, start=2):
            selected = [cells[index] if index < len(cells) else None for index in indexes]
            values = [cell.value if cell else None for cell in selected]
            if all(value is None or str(value).strip() == "" for value in values):
                continue
            registration, status, eta = values
            key = _registration(registration)
            issues = []
            if any(cell and cell.data_type == "f" for cell in selected):
                issues.append("Formula tidak didukung; gunakan nilai langsung.")
            if not key:
                issues.append("MT REGISTRATION wajib diisi.")
            elif key in seen:
                issues.append(f"Registrasi {registration} duplikat.")
            elif not by_registration.get(key):
                issues.append(f"Registrasi {registration} tidak ada pada MT Management Job ini.")
            elif len(by_registration[key]) != 1:
                issues.append(f"Registrasi {registration} merujuk ke lebih dari satu MT pada Job ini.")
            seen.add(key)
            update = {"mt_id": by_registration[key][0].mt_id} if len(by_registration.get(key, [])) == 1 else {}
            if status is not None and str(status).strip():
                normalized_status = str(status).strip().upper()
                if normalized_status not in MT_STATUSES:
                    issues.append(f"Status {status} tidak valid. Pilih: {', '.join(sorted(MT_STATUSES))}.")
                else:
                    update["operational_status"] = normalized_status
            if eta is not None and str(eta).strip():
                try:
                    update["planned_eta_depot"] = _eta(eta, zone)
                except (ValueError, OverflowError, TypeError):
                    issues.append("PLANNED ETA DEPOT tidak valid; gunakan tanggal dan jam Excel atau YYYY-MM-DD HH:MM:SS.")
            if issues:
                errors.append({"row": number, "registration": str(registration or ""), "message": " ".join(issues)})
            elif len(update) > 1:
                updates.append(update)
            else:
                skipped += 1
        if errors:
            message = "Upload dibatalkan; belum ada MT yang diubah. " + " ".join(f"Baris {error['row']}: {error['message']}" for error in errors[:20])
            if len(errors) > 20:
                message += f" Ada {len(errors) - 20} baris salah lainnya."
            raise HTTPException(422, detail={"code": "INVALID_MT_READINESS", "message": message, "errors": errors})
        if not updates:
            raise HTTPException(422, detail={"code": "EMPTY_MT_READINESS", "message": "Tidak ada status atau Planned ETA Depot yang diisi untuk diperbarui."})
        result = update_vehicle_states(db, job.job_id, updates, actor="excel-readiness-import")
        return {**result, "imported_count": len(updates), "skipped_count": skipped, "applied_updates": updates}
    finally:
        workbook.close()
