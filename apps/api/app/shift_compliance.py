"""Operational shift deadlines, independent of model departure profiles."""
from datetime import datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo
from fastapi import HTTPException


def validate_operational_shifts(value):
    if isinstance(value, str):
        try:
            value = json.loads(value or "[]")
        except ValueError:
            raise HTTPException(422, detail="Invalid depot shift configuration")
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 24:
        raise HTTPException(422, detail="Depot shifts must be a list of at most 24 shifts")
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict):
            raise HTTPException(422, detail="Invalid shift row")
        code = str(row.get("shift_id") or "").strip()
        name = str(row.get("name") or code).strip()
        try:
            start = time.fromisoformat(str(row.get("start_time", "")))
            end = time.fromisoformat(str(row.get("end_time", "")))
            if start.tzinfo or end.tzinfo or start.second or end.second or start.microsecond or end.microsecond:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, detail="Shift start and end must use HH:MM")
        keys = {code.casefold(), name.casefold()}
        if not code or not name or len(code) > 80 or len(name) > 120 or keys & seen or start == end:
            raise HTTPException(422, detail="Shift IDs/names must be unique and times must differ")
        seen.update(keys)
        result.append({"shift_id": code, "name": name, "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M")})
    return result


def resolve_shift(shifts, value):
    key = str(value or "").strip().casefold()
    return next((row for row in shifts if key in {row["shift_id"].casefold(), row["name"].casefold()}), None)


def shift_deadline(operating_date, shift, timezone_name):
    start = time.fromisoformat(shift["start_time"])
    end = time.fromisoformat(shift["end_time"])
    day = operating_date + timedelta(days=int(end < start))
    return datetime.combine(day, end, tzinfo=ZoneInfo(timezone_name or "Asia/Jakarta")).astimezone(timezone.utc)
