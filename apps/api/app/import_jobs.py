from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .importer import ImportProcessor
from .models import ImportAudit


logger = logging.getLogger(__name__)


def claim_next_import(db: Session) -> str | None:
    audit = db.scalar(
        select(ImportAudit)
        .where(ImportAudit.status == "QUEUED", ImportAudit.stored_path.is_not(None))
        .order_by(ImportAudit.uploaded_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not audit:
        return None
    audit.status = "PROCESSING"
    audit.started_at = datetime.now(UTC)
    audit.attempt_count = (audit.attempt_count or 0) + 1
    audit.error_message = None
    import_id = audit.import_id
    db.commit()
    return import_id


def recover_interrupted_imports(db: Session) -> int:
    audits = db.scalars(select(ImportAudit).where(ImportAudit.status == "PROCESSING")).all()
    for audit in audits:
        audit.status = "QUEUED"
        audit.started_at = None
        audit.error_message = "Import worker restarted; the durable job was queued again."
    db.commit()
    return len(audits)


def process_import(db: Session, import_id: str) -> None:
    audit = db.get(ImportAudit, import_id)
    if not audit or not audit.stored_path:
        return
    path = Path(audit.stored_path)
    try:
        if not path.is_file():
            raise ValueError("Uploaded import file is no longer available.")
        processor = ImportProcessor(db, depot_id=audit.depot_id)
        if audit.domain == "MOBIL_TANGKI":
            processor.import_master_mt(
                path,
                audit.sheet_name or "Mobil Tangki",
                filename=audit.filename,
                existing_import_id=import_id,
                require_depot_id=True,
            )
        elif audit.domain == "SPBU":
            processor.import_master_spbu(
                path,
                audit.sheet_name or "SPBU",
                filename=audit.filename,
                existing_import_id=import_id,
                require_depot_id=True,
            )
        elif audit.domain == "LOADING_ORDER":
            processor.import_loading_order(
                path,
                audit.sheet_name or "Loading Orders",
                filename=audit.filename,
                existing_import_id=import_id,
                require_depot_id=True,
            )
        elif audit.domain == "GPS":
            processor.stage_gps_file(
                path,
                audit.sheet_name or "GPS",
                filename=audit.filename,
                existing_import_id=import_id,
            )
        else:
            raise ValueError(f"Asynchronous import is not supported for domain {audit.domain}.")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could_not_remove_completed_import_file import_id=%s path=%s", import_id, path)
    except Exception as exc:
        db.rollback()
        failed = db.get(ImportAudit, import_id)
        if failed:
            failed.status = "FAILED"
            failed.completed_at = datetime.now(UTC)
            failed.error_message = str(exc)[:4000]
            db.commit()
        logger.exception("import_job_failed import_id=%s", import_id)
