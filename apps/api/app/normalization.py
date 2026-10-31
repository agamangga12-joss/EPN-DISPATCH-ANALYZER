from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


def make_id(prefix: str, *parts: Any) -> str:
    joined = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return clean_value(value.item())
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    return value


def clean_str(value: Any) -> str | None:
    value = clean_value(value)
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text or None


def normalize_key(value: Any) -> str | None:
    text = clean_str(value)
    if not text:
        return None
    return re.sub(r"[^A-Z0-9]+", "", text.upper())


def source_number(value: Any) -> float | None:
    value = clean_value(value)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_int(value: Any) -> int | None:
    number = source_number(value)
    return int(number) if number is not None and float(number).is_integer() else None


def source_time(value: Any, default: time | None = None) -> time | None:
    """Normalize Excel/JSON time values to a minute-precision SQL time."""
    value = clean_value(value)
    if value is None or value == "":
        return default
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    text = str(value).strip()
    try:
        return time.fromisoformat(text).replace(second=0, microsecond=0)
    except ValueError:
        try:
            return datetime.fromisoformat(text).time().replace(second=0, microsecond=0)
        except ValueError:
            return default


def mt_capacity_kl(capacity_label: Any, vehicle_type_tag: Any) -> float | None:
    """Resolve an MT capacity in KL from canonical master fields.

    The numeric vehicle class is authoritative. The old label is accepted only
    as a fallback for records imported before the consolidated master format.
    """
    capacity = source_number(vehicle_type_tag)
    if capacity is not None and math.isfinite(capacity) and capacity > 0:
        return capacity
    label = clean_str(capacity_label)
    if label:
        match = re.search(r"([0-9]+(?:[\.,][0-9]+)?)", label)
        if match:
            capacity = float(match.group(1).replace(",", "."))
            if math.isfinite(capacity) and capacity > 0:
                return capacity
    capacity = source_number(vehicle_type_tag)
    return capacity if capacity is not None and math.isfinite(capacity) and capacity > 0 else None


def parse_mt_name(raw: Any) -> tuple[str | None, str | None, list[str]]:
    text = clean_str(raw)
    if not text:
        return None, None, ["missing MT name"]
    match = re.match(r"^\s*([A-Z0-9]+)\s*[-_/ ]\s*([0-9]+(?:\.[0-9]+)?\s*K?L)\s*$", text.upper())
    if match:
        return match.group(1), match.group(2).replace(" ", ""), []
    simple = normalize_key(text)
    if simple:
        return simple, None, ["capacity label not parsed"]
    return text, None, ["unparseable MT name"]


def split_project_tags(raw: Any) -> list[str]:
    text = clean_str(raw)
    if not text:
        return []
    tags: list[str] = []
    for item in text.split(","):
        tag = item.strip()
        if tag:
            tags.append(tag)
    return tags


VEHICLE_CLASS_TAGS = {"8", "16", "24", "32"}


def infer_tag_type(tag_value: str) -> str:
    normalized = normalize_key(tag_value) or "UNKNOWN"
    if normalized in VEHICLE_CLASS_TAGS:
        return "VEHICLE_CLASS"
    return "PROJECT"


def parse_coordinate(raw: Any) -> tuple[float | None, float | None, list[str]]:
    text = clean_str(raw)
    if not text:
        return None, None, ["missing coordinate"]
    pieces = re.findall(r"[-+]?\d+(?:[\.,]\d+)?", text)
    if len(pieces) != 2:
        return None, None, ["coordinate must contain latitude and longitude"]
    try:
        lat = float(pieces[0].replace(",", "."))
        lon = float(pieces[1].replace(",", "."))
    except ValueError:
        return None, None, ["coordinate values are not numeric"]
    messages = []
    if not -90 <= lat <= 90:
        messages.append("latitude outside valid range")
    if not -180 <= lon <= 180:
        messages.append("longitude outside valid range")
    return (lat, lon, messages) if not messages else (None, None, messages)


def coerce_date(value: Any) -> date | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def coerce_time(value: Any) -> time | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        fraction = float(value) % 1
        seconds = int(round(fraction * 24 * 60 * 60))
        return (datetime(2000, 1, 1) + timedelta(seconds=seconds)).time()
    text = str(value).strip()
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.time().replace(microsecond=0)


def combine_datetime(date_value: Any, time_value: Any) -> datetime | None:
    parsed_date = coerce_date(date_value)
    parsed_time = coerce_time(time_value)
    if parsed_date is None:
        return None
    if parsed_time is None:
        parsed_time = time(0, 0, 0)
    return datetime.combine(parsed_date, parsed_time)


def normalize_product(value: Any) -> str | None:
    text = clean_str(value)
    if not text:
        return None
    return re.sub(r"\s+", " ", text.upper())


def dataframe_records(path: Path, sheet_name: str) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=object)
    else:
        df = pd.read_excel(path, sheet_name=sheet_name, dtype=object)
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        records.append({str(column): clean_value(row[column]) for column in df.columns})
    return records


def resolve_sheet_name(path: Path, requested_sheet_name: str, aliases: list[str] | tuple[str, ...] = ()) -> str:
    if path.suffix.lower() == ".csv":
        return requested_sheet_name
    workbook = pd.ExcelFile(path)
    sheet_names = list(workbook.sheet_names)
    candidates = [requested_sheet_name, *aliases]
    for candidate in candidates:
        if candidate in sheet_names:
            return candidate
    normalized_sheets = {sheet.strip().casefold(): sheet for sheet in sheet_names}
    for candidate in candidates:
        matched = normalized_sheets.get((candidate or "").strip().casefold())
        if matched:
            return matched
    if len(sheet_names) == 1:
        return sheet_names[0]
    available = ", ".join(sheet_names)
    expected = ", ".join(candidate for candidate in candidates if candidate)
    raise ValueError(f"Worksheet not found. Expected one of: {expected}. Available sheets: {available}.")
