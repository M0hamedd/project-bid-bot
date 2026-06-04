from __future__ import annotations

import csv
import hashlib
from io import StringIO
from typing import Any


IMPORT_SOURCE = "deterministic_rate_card_import"

ALIASES = {
    "rate_id": ("rate_id",),
    "label": ("label", "name", "item"),
    "keywords": ("keywords", "terms"),
    "units": ("units", "unit"),
    "unit_direct_cost": ("unit_direct_cost", "direct_cost", "cost"),
    "confidence": ("confidence",),
}


def import_rate_card(source: str | list[dict[str, Any]], *, profile_id: str = "", created_at: str = "") -> dict:
    rows = _source_rows(source)
    rate_card: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for row_number, row in rows:
        record, reason = _rate_record(row, profile_id=profile_id, created_at=created_at)
        if record:
            rate_card.append(record)
        else:
            errors.append({"row": row_number, "reason": reason})

    return {
        "source": IMPORT_SOURCE,
        "imported_count": len(rate_card),
        "skipped_count": len(errors),
        "rate_card": rate_card,
        "errors": errors,
    }


def _source_rows(source: str | list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    if isinstance(source, str):
        text = source.strip()
        if not text:
            return []
        reader = csv.DictReader(StringIO(text))
        return [(index, dict(row)) for index, row in enumerate(reader, start=2)]
    if isinstance(source, list):
        return [(index, dict(row)) for index, row in enumerate(source, start=1) if isinstance(row, dict)]
    return [(0, {})]


def _rate_record(row: dict[str, Any], *, profile_id: str, created_at: str) -> tuple[dict[str, Any], str]:
    label = _text(_value(row, ALIASES["label"]))
    unit_direct_cost = _number(_value(row, ALIASES["unit_direct_cost"]))

    if not label:
        return {}, "missing label"
    if unit_direct_cost <= 0:
        return {}, "unit_direct_cost must be positive"

    keywords = _list_value(_value(row, ALIASES["keywords"]) or label, lower=True)
    units = _list_value(_value(row, ALIASES["units"]) or "unit", lower=True)
    confidence = _confidence(_value(row, ALIASES["confidence"]))
    rate_id = _text(_value(row, ALIASES["rate_id"]))
    if not rate_id:
        rate_id = _rate_id(profile_id, label, units, unit_direct_cost)

    return (
        {
            "rate_id": rate_id,
            "label": label,
            "keywords": keywords,
            "units": units,
            "unit_direct_cost": unit_direct_cost,
            "confidence": confidence,
            "profile_id": _text(profile_id),
            "source": IMPORT_SOURCE,
            "created_at": _text(created_at),
        },
        "",
    )


def _value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    normalized = {_field_key(key): value for key, value in row.items()}
    for alias in aliases:
        key = _field_key(alias)
        if key in normalized:
            return normalized[key]
    return None


def _field_key(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").split())


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list_value(value: Any, *, lower: bool = False) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value]
    else:
        text = str(value or "").strip()
        parts = text.replace(";", ",").split(",") if text else []
    if lower:
        return [part.lower() for part in parts if part.strip()]
    return [part for part in parts if part.strip()]


def _number(value: Any) -> float:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _confidence(value: Any) -> str:
    label = str(value or "").strip().title()
    return label if label in {"High", "Moderate", "Low"} else "High"


def _rate_id(profile_id: str, label: str, units: list[str], unit_direct_cost: float) -> str:
    parts = (_text(profile_id), label, tuple(units), unit_direct_cost)
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:12]
    return f"rate-card-{digest}"
