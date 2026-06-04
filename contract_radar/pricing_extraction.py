from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable


PRICING_FORM_PATTERNS = (
    re.compile(r"\bpricing\s+(?:form|sheet|schedule)\b", re.IGNORECASE),
    re.compile(r"\bprice\s+schedule\b", re.IGNORECASE),
    re.compile(r"\bschedule\s+of\s+prices\b", re.IGNORECASE),
    re.compile(r"\bunit\s+price(?:s|d)?\b", re.IGNORECASE),
    re.compile(r"\bbid\s+form\b", re.IGNORECASE),
)

QUANTITY_UNIT_PATTERN = re.compile(
    r"(?P<quantity>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>"
    r"lane[-\s]?m|linear\s+m(?:etre|eter)?s?|lin\.?\s*m|lm|"
    r"m2|m\^2|m²|sq\.?\s*m|square\s+m(?:etre|eter)?s?|"
    r"m3|m\^3|m³|cu\.?\s*m|cubic\s+m(?:etre|eter)?s?|"
    r"km|m|metres?|meters?|tonnes?|tons?|kg|each|ea|units?|hrs?|hours?|days?|lump\s+sum|ls"
    r")\b",
    re.IGNORECASE,
)

QUANTITY_LABEL_PATTERN = re.compile(
    r"\b(?:quantity|qty)\s*[:#-]?\s*"
    r"(?P<quantity>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>[A-Za-z0-9^²³ ._-]+)?",
    re.IGNORECASE,
)


def extract_pricing_structure(chunks: Iterable[Any]) -> dict[str, Any]:
    """Extract cited pricing-form and quantity structure from solicitation text."""
    chunk_rows = [_chunk_from_any(chunk, index) for index, chunk in enumerate(chunks)]
    form_citations = _pricing_form_citations(chunk_rows)
    line_items = _pricing_line_items(chunk_rows)
    required_inputs = []
    if form_citations and not line_items:
        required_inputs.append("quantity")
    return {
        "source": "deterministic_pricing_extractor",
        "pricing_form_detected": bool(form_citations),
        "pricing_form_citations": form_citations,
        "pricing_line_items": line_items,
        "required_pricing_inputs": required_inputs,
        "quantity_summary": _quantity_summary(line_items),
        "summary": _summary(form_citations, line_items),
    }


def merge_pricing_extraction(pricing_context: dict[str, Any] | None, extraction: dict[str, Any]) -> dict[str, Any]:
    context = dict(pricing_context or {})
    if not extraction:
        return context
    existing_required = [
        str(item)
        for item in context.get("required_pricing_inputs") or []
        if str(item).strip()
    ]
    extracted_required = [
        str(item)
        for item in extraction.get("required_pricing_inputs") or []
        if str(item).strip()
    ]
    if existing_required or extracted_required:
        context["required_pricing_inputs"] = _unique([*existing_required, *extracted_required])
    for key in (
        "pricing_form_detected",
        "pricing_form_citations",
        "pricing_line_items",
        "quantity_summary",
        "summary",
    ):
        if key in extraction:
            context[key] = extraction[key]
    context["pricing_extraction"] = extraction
    return context


def _pricing_form_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        for pattern in PRICING_FORM_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            snippet = _snippet(text, match.start(), match.end())
            key = f"{chunk.get('source')}:{chunk.get('page')}:{snippet.lower()}"
            if key in seen:
                continue
            seen.add(key)
            citations.append(_citation(chunk, snippet))
            break
    return citations[:6]


def _pricing_line_items(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        if not _has_pricing_context(str(chunk.get("text") or "")):
            continue
        for line_index, line in enumerate(str(chunk.get("text") or "").splitlines()):
            item = _line_item_from_line(chunk, line, line_index)
            if not item:
                continue
            key = f"{item['description'].lower()}:{item['quantity']}:{item['unit'].lower()}:{chunk.get('page')}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
    return rows[:30]


def _line_item_from_line(chunk: dict[str, Any], line: str, line_index: int) -> dict[str, Any] | None:
    text = " ".join(str(line or "").split())
    if len(text) < 8:
        return None
    match = QUANTITY_UNIT_PATTERN.search(text) or QUANTITY_LABEL_PATTERN.search(text)
    if not match:
        return None
    quantity = _number(match.group("quantity"))
    if quantity <= 0:
        return None
    unit = _clean_unit(match.groupdict().get("unit") or "")
    if not unit:
        return None
    description = _description_before_quantity(text, match.start())
    if len(description) < 4:
        description = _description_after_quantity(text, match.end())
    if len(description) < 4 or _looks_like_deadline_or_date(text):
        return None
    citation = _citation(chunk, text)
    line_item_id = _id("pricing-line", chunk.get("source"), chunk.get("page"), line_index, description, quantity, unit)
    return {
        "line_item_id": line_item_id,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "source": "uploaded_pdf",
        "confidence": "deterministic",
        "citation": citation,
    }


def _quantity_summary(line_items: list[dict[str, Any]]) -> dict[str, Any]:
    units: dict[str, float] = {}
    for item in line_items:
        unit = str(item.get("unit") or "").strip()
        if not unit:
            continue
        units[unit] = round(units.get(unit, 0.0) + _number(item.get("quantity")), 4)
    return {
        "line_item_count": len(line_items),
        "units": units,
        "has_quantities": bool(line_items),
    }


def _summary(form_citations: list[dict[str, Any]], line_items: list[dict[str, Any]]) -> str:
    if line_items:
        return f"Extracted {len(line_items)} cited pricing line item(s) from the official PDF."
    if form_citations:
        return "Pricing form language was detected, but no line-item quantities were extracted."
    return "No pricing form or line-item quantity structure was detected in the official PDF."


def _has_pricing_context(text: str) -> bool:
    lower = text.lower()
    return any(pattern.search(lower) for pattern in PRICING_FORM_PATTERNS) or (
        "item" in lower and ("quantity" in lower or "qty" in lower) and "unit" in lower
    )


def _description_before_quantity(text: str, quantity_start: int) -> str:
    prefix = text[:quantity_start].strip(" :-|#\t")
    prefix = re.sub(r"^(?:item|line)\s*\d+[A-Za-z]?\s*[-:.]?\s*", "", prefix, flags=re.IGNORECASE)
    prefix = re.sub(r"\b(?:qty|quantity)\s*[:#-]?\s*$", "", prefix, flags=re.IGNORECASE).strip(" :-|#\t")
    return _clean_description(prefix)


def _description_after_quantity(text: str, quantity_end: int) -> str:
    suffix = text[quantity_end:].strip(" :-|#\t")
    suffix = re.sub(r"\b(?:unit\s+price|extended\s+price|amount|total)\b.*$", "", suffix, flags=re.IGNORECASE)
    return _clean_description(suffix)


def _clean_description(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    cleaned = re.sub(r"\b(?:pricing|price)\s+(?:schedule|form|sheet)\b", "", cleaned, flags=re.IGNORECASE).strip(" :-|#\t")
    return cleaned[:160]


def _clean_unit(unit: str) -> str:
    text = " ".join(str(unit or "").lower().replace("²", "2").replace("³", "3").split())
    text = text.strip(" ._-")
    aliases = {
        "sq m": "m2",
        "square metre": "m2",
        "square metres": "m2",
        "square meter": "m2",
        "square meters": "m2",
        "cu m": "m3",
        "cubic metre": "m3",
        "cubic metres": "m3",
        "cubic meter": "m3",
        "cubic meters": "m3",
        "metre": "m",
        "metres": "m",
        "meter": "m",
        "meters": "m",
        "linear m": "linear m",
        "lin m": "linear m",
        "lm": "linear m",
        "ea": "each",
        "units": "unit",
        "hrs": "hour",
        "hours": "hour",
        "days": "day",
        "ls": "lump sum",
    }
    text = aliases.get(text, text)
    if text in {"m2", "m^2"}:
        return "m2"
    if text in {"m3", "m^3"}:
        return "m3"
    return text


def _looks_like_deadline_or_date(text: str) -> bool:
    lower = text.lower()
    if any(term in lower for term in ("deadline", "closing", "date", "calendar", "business days")):
        return True
    return bool(re.search(r"\b20\d{2}\b", lower))


def _chunk_from_any(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "text": str(value.get("text") or value.get("content") or value.get("body") or ""),
            "source": str(value.get("source") or value.get("source_filename") or value.get("filename") or ""),
            "page": value.get("page") if value.get("page") is not None else value.get("page_number"),
            "chunk_id": str(value.get("chunk_id") or value.get("id") or index),
        }
    return {
        "text": str(getattr(value, "text", "") or ""),
        "source": str(getattr(value, "source", "") or getattr(value, "source_filename", "") or ""),
        "page": getattr(value, "page", None) if getattr(value, "page", None) is not None else getattr(value, "page_number", None),
        "chunk_id": str(getattr(value, "chunk_id", "") or index),
    }


def _citation(chunk: dict[str, Any], snippet: str) -> dict[str, Any]:
    return {
        "source": str(chunk.get("source") or ""),
        "page": chunk.get("page"),
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "snippet": _shorten(snippet, 220),
        "source_type": "uploaded_pdf",
        "source_label": "Official PDF",
    }


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - 80)
    right = min(len(text), end + 120)
    return _shorten(" ".join(text[left:right].split()), 220)


def _shorten(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _number(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
