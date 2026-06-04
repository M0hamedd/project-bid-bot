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
    rates = _rate_entries(profile, profile_id)
    priced_items: list[dict[str, Any]] = []
    unpriced_items: list[dict[str, Any]] = []

    for item in clean_items:
        quantity = _money(item.get("quantity"))
        unit = _normalize_unit(item.get("unit"))
        match = _rate_for_item(item, unit, rates)
        if quantity <= 0 or not match:
            unpriced_items.append(_unpriced_item(item, reason="No deterministic profile rate matched this line item."))
            continue
        unit_cost = _money(match.get("unit_direct_cost"))
        direct_cost = _round_money(quantity * unit_cost)
        priced_items.append(
            {
                "line_item_id": str(item.get("line_item_id") or _id("pricing-line", item.get("description"), quantity, unit)),
                "description": str(item.get("description") or "Pricing line item"),
                "quantity": quantity,
                "unit": unit,
                "unit_direct_cost": unit_cost,
                "direct_cost": direct_cost,
                "rate_source": str(match.get("rate_source") or ""),
                "rate_source_type": str(match.get("source_type") or ""),
                "rate_id": str(match.get("rate_id") or ""),
                "rate_label": str(match.get("label") or ""),
                "confidence": str(match.get("confidence") or "Moderate"),
                "citation": item.get("citation") if isinstance(item.get("citation"), dict) else {},
            }
        )

    direct_cost = _round_money(sum(_money(item.get("direct_cost")) for item in priced_items))
    coverage = round(len(priced_items) / len(clean_items), 4) if clean_items else 0.0
    contingency_rate = _contingency_rate(opportunity, profile, coverage)
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
        "business_rate_card_count": len([rate for rate in rates if rate.get("source_type") == "business_profile"]),
        "business_rate_count": len({
            item.get("rate_id")
            for item in priced_items
            if item.get("rate_source_type") == "business_profile" and item.get("rate_id")
        }),
        "rate_card_source": _rate_card_source(priced_items),
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
        "rate_card_facts": _rate_card_facts(priced_items),
        "assumptions": _assumptions(profile_id, priced_items, contingency_rate, overhead_rate, margin_rate),
        "risks": _risks(coverage, unpriced_items, priced_items),
    }


def _rate_for_item(
    item: dict[str, Any],
    unit: str,
    rates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    description = str(item.get("description") or "").lower()
    for rate in rates:
        keywords = tuple(str(keyword).lower() for keyword in rate.get("keywords") or [])
        units = tuple(str(rate_unit) for rate_unit in rate.get("units") or [])
        if unit in units and any(keyword in description for keyword in keywords):
            return rate
    if unit in DEFAULT_RATES:
        return {
            "rate_id": f"default_{unit.replace(' ', '_')}_rate",
            "label": f"Default {unit} unit rate",
            "keywords": [],
            "units": [unit],
            "unit_direct_cost": DEFAULT_RATES[unit],
            "rate_source": f"default_{unit.replace(' ', '_')}_rate",
            "source_type": "global_unit_default",
            "confidence": "Moderate",
        }
    return None


def _business_profile(opportunity: Any) -> dict[str, Any]:
    if isinstance(opportunity, dict):
        profile = opportunity.get("business_profile")
        return dict(profile) if isinstance(profile, dict) else {}
    profile = getattr(opportunity, "business_profile", None)
    if hasattr(profile, "to_dict"):
        return dict(profile.to_dict())
    return dict(profile) if isinstance(profile, dict) else {}


def _rate_entries(profile: dict[str, Any], profile_id: str) -> list[dict[str, Any]]:
    entries = _business_rate_entries(profile.get("pricing_rate_card"))
    for keywords, units, value, source in PROFILE_RATE_CARDS.get(profile_id, PROFILE_RATE_CARDS["road_civil_infrastructure"]):
        entries.append(
            {
                "rate_id": source,
                "label": source.replace("_", " ").title(),
                "keywords": [str(keyword).lower() for keyword in keywords],
                "units": [_normalize_unit(unit) for unit in units],
                "unit_direct_cost": float(value),
                "rate_source": source,
                "source_type": "supported_profile_default",
                "confidence": "High",
            }
        )
    return entries


def _business_rate_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        keywords = _text_list(
            item.get("keywords")
            or item.get("description_terms")
            or item.get("matches")
            or item.get("match_terms")
        )
        units = [_normalize_unit(unit) for unit in _text_list(item.get("units") or item.get("unit"))]
        unit_direct_cost = _money(item.get("unit_direct_cost") or item.get("rate") or item.get("cost"))
        if not keywords or not units or unit_direct_cost <= 0:
            continue
        rate_id = str(item.get("rate_id") or _id("profile-rate", keywords, units, unit_direct_cost)).strip()
        entries.append(
            {
                "rate_id": rate_id,
                "label": str(item.get("label") or item.get("description") or rate_id).strip(),
                "keywords": [keyword.lower() for keyword in keywords],
                "units": units,
                "unit_direct_cost": unit_direct_cost,
                "rate_source": f"profile_rate_card:{rate_id}",
                "source_type": "business_profile",
                "confidence": _confidence_label(item.get("confidence")),
            }
        )
    return entries


def _rate_card_source(priced_items: list[dict[str, Any]]) -> str:
    source_types = {str(item.get("rate_source_type") or "") for item in priced_items}
    if "business_profile" in source_types:
        if source_types <= {"business_profile"}:
            return "business_profile"
        return "business_profile_with_fallbacks"
    if "supported_profile_default" in source_types:
        if source_types <= {"supported_profile_default"}:
            return "supported_profile_default"
        return "supported_profile_default_with_unit_fallbacks"
    if "global_unit_default" in source_types:
        return "global_unit_default"
    return ""


def _rate_card_facts(priced_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in priced_items:
        rate_id = str(item.get("rate_id") or item.get("rate_source") or "").strip()
        if not rate_id or rate_id in seen:
            continue
        seen.add(rate_id)
        facts.append(
            {
                "rate_id": rate_id,
                "rate_source": str(item.get("rate_source") or ""),
                "source_type": str(item.get("rate_source_type") or ""),
                "label": str(item.get("rate_label") or rate_id),
                "unit": str(item.get("unit") or ""),
                "unit_direct_cost": _money(item.get("unit_direct_cost")),
            }
        )
    return facts


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
    rate_card_source = _rate_card_source(priced_items)
    if rate_card_source.startswith("business_profile"):
        rate_card_text = "the business profile rate card with deterministic fallbacks"
    elif rate_card_source.startswith("global_unit"):
        rate_card_text = "broad deterministic unit defaults"
    else:
        rate_card_text = f"the {profile_id} deterministic profile rate card"
    assumptions = [
        f"Line-item costing uses {rate_card_text}.",
        f"Applied {contingency_rate:.0%} contingency, {overhead_rate:.0%} overhead, and {margin_rate:.0%} target margin to priced PDF quantities.",
    ]
    for item in priced_items[:4]:
        assumptions.append(
            f"{item['description']}: {item['quantity']:,.2f} {item['unit']} at ${item['unit_direct_cost']:,.2f}/{item['unit']}."
        )
    return assumptions


def _risks(
    coverage: float,
    unpriced_items: list[dict[str, Any]],
    priced_items: list[dict[str, Any]],
) -> list[str]:
    risks: list[str] = []
    if coverage < 1:
        risks.append(f"{len(unpriced_items)} extracted line item(s) did not match a deterministic rate.")
    if coverage and coverage < 0.75:
        risks.append("Less than 75% of extracted line items were costed; estimator review is required before using the rollup.")
    source_types = {str(item.get("rate_source_type") or "") for item in priced_items}
    if "business_profile" in source_types and "supported_profile_default" in source_types:
        risks.append("Some priced line items used supported-profile fallback rates because the business profile rate card did not cover them.")
    if "global_unit_default" in source_types:
        risks.append("Some priced line items used broad unit defaults; estimator should confirm those unit rates.")
    return risks


def _contingency_rate(opportunity: Any, profile: dict[str, Any], coverage: float) -> float:
    text = _opportunity_text(opportunity)
    rate = _policy_rate(profile, ("contingency_rate", "base_contingency_rate"), 0.12)
    if any(term in text for term in ("traffic", "staging", "night", "emergency", "bridge", "watermain", "sewer")):
        rate += 0.04
    if coverage < 1:
        rate += 0.03
    return min(0.24, rate)


def _overhead_rate(profile: dict[str, Any]) -> float:
    override = _policy_rate(profile, ("overhead_rate",), None)
    if override is not None:
        return override
    text = f"{profile.get('profile_id', '')} {profile.get('business_type', '')}".lower()
    if "engineering" in text or "professional" in text:
        return 0.18
    if "parks" in text or "landscape" in text:
        return 0.13
    return 0.11


def _margin_rate(profile: dict[str, Any], coverage: float) -> float:
    override = _policy_rate(profile, ("margin_rate", "target_margin_rate"), None)
    if override is not None:
        base = override
        if coverage < 1:
            base += 0.02
        return min(0.22, max(0.08, base))
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


def _policy_rate(profile: dict[str, Any], keys: tuple[str, ...], fallback: float | None) -> float | None:
    policy = profile.get("pricing_policy") if isinstance(profile.get("pricing_policy"), dict) else {}
    for key in keys:
        if key not in policy:
            continue
        try:
            rate = float(policy.get(key))
        except (TypeError, ValueError):
            continue
        if rate > 1 and rate <= 100:
            rate = rate / 100
        if 0 <= rate <= 0.5:
            return rate
    return fallback


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _confidence_label(value: Any) -> str:
    label = str(value or "").strip().title()
    return label if label in {"High", "Moderate", "Low"} else "High"


def _normalize_unit(value: Any) -> str:
    text = " ".join(str(value or "").lower().replace("\u00b2", "2").replace("\u00b3", "3").split())
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
