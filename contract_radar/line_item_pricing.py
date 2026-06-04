from __future__ import annotations

import hashlib
from typing import Any


DEFAULT_RATES = {
    "m2": 90.0,
    "m3": 120.0,
    "m": 45.0,
    "linear m": 135.0,
    "tonne": 175.0,
    "tonnes": 175.0,
    "ton": 175.0,
    "tons": 175.0,
    "each": 850.0,
    "unit": 850.0,
    "hour": 125.0,
    "day": 1200.0,
}


PROFILE_RATE_CARDS = {
    "road_civil_infrastructure": [
        (("milling", "grind"), ("m2",), 18.0, "civil_milling_m2"),
        (("asphalt", "paving", "resurfacing"), ("m2",), 72.0, "civil_asphalt_m2"),
        (("curb", "gutter"), ("linear m", "m"), 210.0, "civil_curb_linear_m"),
        (("sidewalk", "concrete slab"), ("m2",), 155.0, "civil_sidewalk_m2"),
        (("excavat", "trench"), ("m3",), 135.0, "civil_excavation_m3"),
        (("traffic control", "staging"), ("day",), 1650.0, "civil_traffic_control_day"),
        (("catch basin", "maintenance hole", "manhole"), ("each", "unit"), 4800.0, "civil_structure_each"),
        (("granular", "aggregate", "stone"), ("tonne", "tonnes", "ton", "tons"), 68.0, "civil_granular_tonne"),
    ],
    "parks_landscape": [
        (("sod", "turf"), ("m2",), 16.0, "landscape_sod_m2"),
        (("mulch",), ("m2",), 9.0, "landscape_mulch_m2"),
        (("planting bed", "topsoil"), ("m2",), 18.0, "landscape_bed_m2"),
        (("tree",), ("each", "unit"), 650.0, "landscape_tree_each"),
        (("shrub", "perennial"), ("each", "unit"), 85.0, "landscape_plant_each"),
        (("watering", "maintenance"), ("hour",), 110.0, "landscape_hour"),
    ],
    "professional_engineering_design": [
        (("engineer", "design", "inspection", "contract administration"), ("hour",), 155.0, "engineering_hour"),
        (("site visit", "field review"), ("each", "unit"), 950.0, "engineering_site_visit_each"),
        (("report", "drawing", "submission"), ("each", "unit"), 2500.0, "engineering_deliverable_each"),
        (("day",), ("day",), 1200.0, "engineering_day"),
    ],
}


def build_line_item_cost_rollup(
    line_items: list[dict[str, Any]],
    opportunity: Any,
) -> dict[str, Any]:
    clean_items = [dict(item) for item in line_items if isinstance(item, dict)]
    if not clean_items:
        return {}

    profile = _business_profile(opportunity)
    profile_id = str(profile.get("profile_id") or "road_civil_infrastructure")
    rates = PROFILE_RATE_CARDS.get(profile_id, PROFILE_RATE_CARDS["road_civil_infrastructure"])
    priced_items: list[dict[str, Any]] = []
    unpriced_items: list[dict[str, Any]] = []

    for item in clean_items:
        quantity = _money(item.get("quantity"))
        unit = _normalize_unit(item.get("unit"))
        match = _rate_for_item(item, unit, rates)
        if quantity <= 0 or not match:
            unpriced_items.append(_unpriced_item(item, reason="No deterministic profile rate matched this line item."))
            continue
        unit_cost, rate_source, confidence = match
        direct_cost = _round_money(quantity * unit_cost)
        priced_items.append(
            {
                "line_item_id": str(item.get("line_item_id") or _id("pricing-line", item.get("description"), quantity, unit)),
                "description": str(item.get("description") or "Pricing line item"),
                "quantity": quantity,
                "unit": unit,
                "unit_direct_cost": unit_cost,
                "direct_cost": direct_cost,
                "rate_source": rate_source,
                "confidence": confidence,
                "citation": item.get("citation") if isinstance(item.get("citation"), dict) else {},
            }
        )

    direct_cost = _round_money(sum(_money(item.get("direct_cost")) for item in priced_items))
    coverage = round(len(priced_items) / len(clean_items), 4) if clean_items else 0.0
    contingency_rate = _contingency_rate(opportunity, coverage)
    overhead_rate = _overhead_rate(profile)
    margin_rate = _margin_rate(profile, coverage)
    contingency = _round_money(direct_cost * contingency_rate)
    overhead = _round_money(direct_cost * overhead_rate)
    estimated_cost = _round_money(direct_cost + contingency + overhead)
    target_bid = _round_money(estimated_cost / max(0.55, 1.0 - margin_rate)) if estimated_cost > 0 else 0.0
    margin = _round_money(target_bid - estimated_cost) if target_bid > 0 else 0.0

    return {
        "source": "deterministic_profile_rate_card",
        "profile_id": profile_id,
        "line_item_count": len(clean_items),
        "priced_line_item_count": len(priced_items),
        "unpriced_line_item_count": len(unpriced_items),
        "coverage": coverage,
        "confidence": _confidence(coverage, priced_items),
        "direct_cost": direct_cost,
        "contingency": contingency,
        "overhead": overhead,
        "estimated_cost": estimated_cost,
        "margin": margin,
        "target_bid": target_bid,
        "rates": {
            "contingency_rate": contingency_rate,
            "overhead_rate": overhead_rate,
            "margin_rate": margin_rate,
        },
        "priced_line_items": priced_items,
        "unpriced_line_items": unpriced_items,
        "assumptions": _assumptions(profile_id, priced_items, contingency_rate, overhead_rate, margin_rate),
        "risks": _risks(coverage, unpriced_items),
    }


def _rate_for_item(
    item: dict[str, Any],
    unit: str,
    rates: list[tuple[tuple[str, ...], tuple[str, ...], float, str]],
) -> tuple[float, str, str] | None:
    description = str(item.get("description") or "").lower()
    for keywords, units, value, source in rates:
        if unit in units and any(keyword in description for keyword in keywords):
            return float(value), source, "High"
    if unit in DEFAULT_RATES:
        return DEFAULT_RATES[unit], f"default_{unit.replace(' ', '_')}_rate", "Moderate"
    return None


def _business_profile(opportunity: Any) -> dict[str, Any]:
    if isinstance(opportunity, dict):
        profile = opportunity.get("business_profile")
        return dict(profile) if isinstance(profile, dict) else {}
    profile = getattr(opportunity, "business_profile", None)
    if hasattr(profile, "to_dict"):
        return dict(profile.to_dict())
    return dict(profile) if isinstance(profile, dict) else {}


def _unpriced_item(item: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "line_item_id": str(item.get("line_item_id") or ""),
        "description": str(item.get("description") or "Pricing line item"),
        "quantity": _money(item.get("quantity")),
        "unit": _normalize_unit(item.get("unit")),
        "reason": reason,
        "citation": item.get("citation") if isinstance(item.get("citation"), dict) else {},
    }


def _assumptions(
    profile_id: str,
    priced_items: list[dict[str, Any]],
    contingency_rate: float,
    overhead_rate: float,
    margin_rate: float,
) -> list[str]:
    assumptions = [
        f"Line-item costing uses the {profile_id} deterministic profile rate card.",
        f"Applied {contingency_rate:.0%} contingency, {overhead_rate:.0%} overhead, and {margin_rate:.0%} target margin to priced PDF quantities.",
    ]
    for item in priced_items[:4]:
        assumptions.append(
            f"{item['description']}: {item['quantity']:,.2f} {item['unit']} at ${item['unit_direct_cost']:,.2f}/{item['unit']}."
        )
    return assumptions


def _risks(coverage: float, unpriced_items: list[dict[str, Any]]) -> list[str]:
    risks: list[str] = []
    if coverage < 1:
        risks.append(f"{len(unpriced_items)} extracted line item(s) did not match a deterministic rate.")
    if coverage and coverage < 0.75:
        risks.append("Less than 75% of extracted line items were costed; estimator review is required before using the rollup.")
    return risks


def _contingency_rate(opportunity: Any, coverage: float) -> float:
    text = _opportunity_text(opportunity)
    rate = 0.12
    if any(term in text for term in ("traffic", "staging", "night", "emergency", "bridge", "watermain", "sewer")):
        rate += 0.04
    if coverage < 1:
        rate += 0.03
    return min(0.24, rate)


def _overhead_rate(profile: dict[str, Any]) -> float:
    text = f"{profile.get('profile_id', '')} {profile.get('business_type', '')}".lower()
    if "engineering" in text or "professional" in text:
        return 0.18
    if "parks" in text or "landscape" in text:
        return 0.13
    return 0.11


def _margin_rate(profile: dict[str, Any], coverage: float) -> float:
    text = f"{profile.get('profile_id', '')} {profile.get('business_type', '')}".lower()
    if "engineering" in text or "professional" in text:
        base = 0.18
    elif "parks" in text or "landscape" in text:
        base = 0.14
    else:
        base = 0.12
    if coverage < 1:
        base += 0.02
    return min(0.22, max(0.08, base))


def _confidence(coverage: float, priced_items: list[dict[str, Any]]) -> str:
    high_count = sum(1 for item in priced_items if item.get("confidence") == "High")
    if coverage >= 0.95 and priced_items and high_count >= max(1, len(priced_items) // 2):
        return "High"
    if coverage >= 0.75:
        return "Moderate"
    return "Low"


def _opportunity_text(opportunity: Any) -> str:
    if isinstance(opportunity, dict):
        solicitation = opportunity.get("solicitation") if isinstance(opportunity.get("solicitation"), dict) else {}
        values = [
            opportunity.get("title"),
            opportunity.get("description"),
            solicitation.get("description"),
            solicitation.get("category"),
            " ".join(str(item) for item in opportunity.get("matched_terms") or []),
        ]
    else:
        solicitation = getattr(opportunity, "solicitation", None)
        values = [
            getattr(opportunity, "title", ""),
            getattr(solicitation, "description", ""),
            getattr(solicitation, "category", ""),
            " ".join(str(item) for item in getattr(opportunity, "matched_terms", []) or []),
        ]
    return " ".join(str(value or "") for value in values).lower()


def _normalize_unit(value: Any) -> str:
    text = " ".join(str(value or "").lower().replace("²", "2").replace("³", "3").split())
    aliases = {
        "m^2": "m2",
        "sq m": "m2",
        "square metre": "m2",
        "square metres": "m2",
        "square meter": "m2",
        "square meters": "m2",
        "m^3": "m3",
        "cu m": "m3",
        "cubic metre": "m3",
        "cubic metres": "m3",
        "cubic meter": "m3",
        "cubic meters": "m3",
        "metre": "m",
        "metres": "m",
        "meter": "m",
        "meters": "m",
        "lin m": "linear m",
        "lm": "linear m",
        "ea": "each",
        "units": "unit",
        "hrs": "hour",
        "hours": "hour",
        "days": "day",
    }
    return aliases.get(text.strip(" ._-"), text.strip(" ._-"))


def _money(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _round_money(value: float) -> float:
    amount = max(0.0, float(value or 0.0))
    if amount <= 0:
        return 0.0
    if amount < 100000:
        increment = 100
    elif amount < 1000000:
        increment = 1000
    else:
        increment = 5000
    return float(round(amount / increment) * increment)


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
