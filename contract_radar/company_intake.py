from __future__ import annotations

import copy
import hashlib
from typing import Any

from contract_radar.profiles import profile_from_payload


LIST_ALIASES = {
    "skills": ("skills", "services", "capabilities", "work_types", "service_lines"),
    "ready_documents": ("ready_documents", "documents_on_hand", "documents", "evidence_documents"),
    "certifications": ("certifications", "licenses", "licences", "permits"),
    "owned_equipment": ("owned_equipment", "equipment", "fleet"),
    "recent_municipal_work": ("recent_municipal_work", "past_projects", "reference_projects", "municipal_references"),
    "bid_constraints": ("bid_constraints", "constraints", "avoid", "limitations"),
    "missing_capabilities": ("missing_capabilities", "not_a_fit", "excluded_work"),
}

STRING_ALIASES = {
    "name": ("name", "company_name", "legal_name"),
    "business_type": ("business_type", "company_type", "description"),
    "base_location": ("base_location", "location", "yard_location", "office_location"),
    "service_area": ("service_area", "coverage_area"),
    "crew_mix": ("crew_mix", "staffing", "team_description"),
    "insurance_coverage": ("insurance_coverage", "insurance", "liability_coverage"),
    "estimating_capacity": ("estimating_capacity", "bid_capacity", "proposal_capacity"),
}

NUMBER_ALIASES = {
    "years_in_business": ("years_in_business", "years_operating"),
    "team_size": ("team_size", "employees", "staff_count"),
    "max_contract_value": ("max_contract_value", "max_project_value", "max_bid_value"),
    "max_sites_per_day": ("max_sites_per_day", "site_capacity"),
    "bonding_single_job_limit": ("bonding_single_job_limit", "bonding_limit", "single_job_bonding_limit"),
    "active_pursuit_count": ("active_pursuit_count", "active_bids"),
    "max_active_pursuits": ("max_active_pursuits", "max_active_bids"),
    "response_days_available": ("response_days_available", "response_days"),
}

CORE_PROFILE_FACTS = (
    "name",
    "skills",
    "ready_documents",
    "insurance_coverage",
    "bonding_single_job_limit",
    "owned_equipment",
    "recent_municipal_work",
    "pricing_rate_card",
    "max_contract_value",
    "team_size",
)


def build_company_intake_profile(payload: dict[str, Any] | None, *, now: str = "") -> dict[str, Any]:
    payload = payload or {}
    source = _source_payload(payload)
    profile_id = str(
        payload.get("profile_id")
        or source.get("profile_id")
        or source.get("supported_profile")
        or _infer_profile_id(source)
    ).strip()
    base = profile_from_payload({"profile_id": profile_id}).to_dict()
    profile = _company_fact_base(base)
    profile["profile_id"] = base.get("profile_id") or profile_id or profile["profile_id"]
    profile["label"] = base.get("label") or profile.get("label") or "Company Profile"
    profile["profile_source"] = "company_intake"
    if now:
        profile["intake_updated_at"] = now

    for field_name, aliases in STRING_ALIASES.items():
        if _has_any_key(source, aliases):
            profile[field_name] = str(_first_value(source, aliases) or "").strip()
    for field_name, aliases in NUMBER_ALIASES.items():
        if _has_any_key(source, aliases):
            profile[field_name] = _number(_first_value(source, aliases))
    for field_name, aliases in LIST_ALIASES.items():
        if _has_any_key(source, aliases):
            profile[field_name] = _list_value(_first_value(source, aliases))

    services = _list_value(_first_value(source, ("services", "capabilities", "work_types", "service_lines")))
    if services:
        profile["skills"] = services
        if not str(profile.get("business_type") or "").strip():
            profile["business_type"] = ", ".join(services[:6])

    profile["pricing_rate_card"] = _rate_card(source)
    profile["pricing_policy"] = _pricing_policy(source)
    profile["missing_profile_facts"] = _missing_profile_facts(profile)
    profile["profile_completeness"] = round(
        (len(CORE_PROFILE_FACTS) - len(profile["missing_profile_facts"])) / len(CORE_PROFILE_FACTS),
        4,
    )
    profile["intake_summary"] = {
        "source": "deterministic_company_intake",
        "evidence_fact_count": len(profile.get("ready_documents") or [])
        + len(profile.get("certifications") or [])
        + len(profile.get("owned_equipment") or [])
        + len(profile.get("recent_municipal_work") or []),
        "rate_card_count": len(profile.get("pricing_rate_card") or []),
        "missing_fact_count": len(profile["missing_profile_facts"]),
    }
    return profile_from_payload({"profile_id": profile["profile_id"], "business_profile": profile}).to_dict()


def _source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("company", "company_profile", "business_profile"):
        value = payload.get(key)
        if isinstance(value, dict):
            merged = {key: item for key, item in payload.items() if key not in {"company", "company_profile", "business_profile"}}
            merged.update(value)
            return merged
    return dict(payload)


def _company_fact_base(base: dict[str, Any]) -> dict[str, Any]:
    profile = copy.deepcopy(base)
    profile.update(
        {
            "name": "",
            "crew_mix": "",
            "insurance_coverage": "",
            "bonding_single_job_limit": 0.0,
            "estimating_capacity": "",
            "team_size": 0,
            "max_contract_value": 0.0,
            "max_sites_per_day": 0,
            "ready_documents": [],
            "certifications": [],
            "owned_equipment": [],
            "recent_municipal_work": [],
            "bid_constraints": [],
            "pricing_rate_card": [],
            "pricing_policy": {},
        }
    )
    return profile


def _infer_profile_id(source: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(source.get("business_type") or source.get("description") or ""),
            " ".join(_list_value(source.get("services") or source.get("skills") or source.get("capabilities"))),
        ]
    ).lower()
    if any(term in text for term in ("engineering", "design", "inspection", "contract administration", "architecture")):
        return "professional_engineering_design"
    if any(term in text for term in ("landscape", "parks", "tree", "sod", "turf", "playground", "arborist")):
        return "parks_landscape"
    return "road_civil_infrastructure"


def _rate_card(source: dict[str, Any]) -> list[dict[str, Any]]:
    value = (
        source.get("pricing_rate_card")
        or source.get("rate_card")
        or source.get("line_item_rates")
        or source.get("unit_rates")
        or []
    )
    if not isinstance(value, list):
        return []
    rates: list[dict[str, Any]] = []
    for item in value:
        rate = _rate_record(item)
        if rate:
            rates.append(rate)
    return rates


def _rate_record(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    label = str(item.get("label") or item.get("description") or item.get("name") or "").strip()
    keywords = _list_value(item.get("keywords") or item.get("matches") or item.get("description_terms") or label)
    units = _list_value(item.get("units") or item.get("unit"))
    unit_direct_cost = _number(item.get("unit_direct_cost") or item.get("rate") or item.get("cost"))
    if not label or not keywords or not units or unit_direct_cost <= 0:
        return {}
    rate_id = str(item.get("rate_id") or _id("company-rate", label, units, unit_direct_cost)).strip()
    return {
        "rate_id": rate_id,
        "label": label,
        "keywords": keywords,
        "units": units,
        "unit_direct_cost": unit_direct_cost,
        "confidence": str(item.get("confidence") or "High").strip().title(),
    }


def _pricing_policy(source: dict[str, Any]) -> dict[str, Any]:
    policy = dict(source.get("pricing_policy") or {}) if isinstance(source.get("pricing_policy"), dict) else {}
    aliases = {
        "contingency_rate": ("contingency_rate", "contingency"),
        "overhead_rate": ("overhead_rate", "overhead"),
        "margin_rate": ("margin_rate", "target_margin_rate", "margin"),
    }
    for key, alias_set in aliases.items():
        if key not in policy and _has_any_key(source, alias_set):
            policy[key] = _rate(_first_value(source, alias_set))
        elif key in policy:
            policy[key] = _rate(policy[key])
    return {key: value for key, value in policy.items() if isinstance(value, (int, float)) and value >= 0}


def _missing_profile_facts(profile: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field_name in CORE_PROFILE_FACTS:
        value = profile.get(field_name)
        if isinstance(value, list) and not value:
            missing.append(field_name)
        elif isinstance(value, dict) and not value:
            missing.append(field_name)
        elif isinstance(value, (int, float)) and value <= 0:
            missing.append(field_name)
        elif value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing


def _first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in source:
            return source.get(key)
    return None


def _has_any_key(source: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(key in source for key in keys)


def _list_value(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _number(value: Any) -> float:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _rate(value: Any) -> float:
    amount = _number(value)
    if amount > 1 and amount <= 100:
        amount = amount / 100
    return min(0.5, max(0.0, amount))


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
