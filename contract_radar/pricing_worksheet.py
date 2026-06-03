from __future__ import annotations

from typing import Any


def build_pricing_worksheet(
    opportunity: Any,
    *,
    compliance_matrix: Any | None = None,
) -> dict[str, Any]:
    pricing = _dict_value(opportunity, "pricing_breakdown")
    recommendation = _dict_value(opportunity, "bid_recommendation")
    historical = _dict_value(opportunity, "historical")
    rag = _dict_value(opportunity, "rag_evidence")
    rows = _rows(compliance_matrix)
    blockers = _pricing_blockers(rows)

    recommended = _money(pricing.get("recommended_bid") or recommendation.get("recommended_bid"))
    if recommended <= 0:
        blockers.append("No deterministic bid amount is available from historical award or cost-stack evidence.")

    candidate_bids = [item for item in pricing.get("candidate_bids") or [] if isinstance(item, dict)]
    candidate_amounts = sorted(_money(item.get("bid")) for item in candidate_bids if _money(item.get("bid")) > 0)
    low = candidate_amounts[0] if candidate_amounts else _money(recommendation.get("low_bid"))
    high = candidate_amounts[-1] if candidate_amounts else _money(recommendation.get("high_bid"))
    if recommended > 0:
        low = low or _round_money(recommended * 0.92)
        high = high or _round_money(recommended * 1.08)
        low = min(low, recommended)
        high = max(high, recommended)

    comps = _comparable_awards(historical, rag)
    confidence = _confidence(pricing, recommendation, comps, blockers)
    status = "blocked" if blockers else "ready" if rows else "draft_estimate"
    assumptions = _assumptions(pricing, recommendation)
    risks = _pricing_risks(pricing, recommendation, comps, rows)

    return {
        "source": "deterministic_pricing_worksheet",
        "status": status,
        "low_bid": low,
        "target_bid": recommended,
        "high_bid": high,
        "confidence": confidence,
        "can_use_for_owner_packet": status in {"ready", "draft_estimate"} and recommended > 0,
        "blockers": blockers,
        "assumptions": assumptions,
        "risks": risks,
        "comparable_awards": comps,
        "cost_stack": {
            "market_reference": _money(pricing.get("market_reference")),
            "direct_cost": _money(pricing.get("direct_cost")),
            "contingency": _money(pricing.get("contingency")),
            "overhead": _money(pricing.get("overhead")),
            "estimated_cost": _money(pricing.get("estimated_cost")),
            "target_margin": _money(pricing.get("margin")),
            "bid_prep_cost": _money(pricing.get("bid_prep_cost")),
        },
        "rates": {
            "contingency_rate": _rate(pricing.get("contingency_rate")),
            "overhead_rate": _rate(pricing.get("overhead_rate")),
            "margin_rate": _rate(pricing.get("margin_rate")),
            "win_probability": _rate(pricing.get("win_probability")),
        },
        "candidate_bids": candidate_bids,
        "evidence": _evidence(pricing, recommendation, historical, rag, blockers),
    }


def with_pricing_worksheet(
    opportunity: Any,
    *,
    compliance_matrix: Any | None = None,
) -> dict[str, Any]:
    payload = dict(opportunity) if isinstance(opportunity, dict) else _to_dict(opportunity)
    payload["pricing_worksheet"] = build_pricing_worksheet(payload, compliance_matrix=compliance_matrix)
    return payload


def _pricing_blockers(rows: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for row in rows:
        category = str(row.get("category") or "")
        if category not in {"pricing_sheet", "form"}:
            continue
        if row.get("resolved"):
            continue
        requirement = str(row.get("requirement") or category.replace("_", " "))
        blockers.append(f"Official package has unresolved pricing/form requirement: {requirement}")
    return _unique(blockers)


def _comparable_awards(historical: dict[str, Any], rag: dict[str, Any]) -> list[dict[str, Any]]:
    comps: list[dict[str, Any]] = []
    for item in historical.get("examples") or []:
        if not isinstance(item, dict):
            continue
        comps.append(
            {
                "source": "historical_award",
                "document_number": str(item.get("document_number") or ""),
                "description": str(item.get("description") or ""),
                "buyer": str(item.get("buyer") or ""),
                "division": str(item.get("division") or ""),
                "supplier": str(item.get("supplier") or ""),
                "award_value": _money(item.get("award_value")),
                "matched_terms": [str(term) for term in item.get("matched_terms") or [] if str(term).strip()],
            }
        )
    for item in rag.get("analogs") or []:
        if not isinstance(item, dict):
            continue
        document_number = str(item.get("document_number") or item.get("id") or "")
        if any(comp.get("document_number") == document_number and document_number for comp in comps):
            continue
        comps.append(
            {
                "source": "retrieved_award",
                "document_number": document_number,
                "description": str(item.get("description") or item.get("text") or ""),
                "buyer": str(item.get("buyer") or ""),
                "division": str(item.get("division") or ""),
                "supplier": str(item.get("supplier") or ""),
                "award_value": _money(item.get("award_value") or item.get("value") or item.get("amount")),
                "matched_terms": [str(term) for term in item.get("matched_terms") or [] if str(term).strip()],
            }
        )
    return [comp for comp in comps if comp.get("award_value") or comp.get("description") or comp.get("document_number")][:6]


def _confidence(
    pricing: dict[str, Any],
    recommendation: dict[str, Any],
    comps: list[dict[str, Any]],
    blockers: list[str],
) -> str:
    if blockers:
        return "Blocked"
    if _money(pricing.get("recommended_bid")) <= 0:
        return "Insufficient"
    comp_count = len([comp for comp in comps if _money(comp.get("award_value")) > 0])
    if comp_count >= 4 and _rate(pricing.get("win_probability")) >= 0.35:
        return "High"
    if comp_count >= 2:
        return "Moderate"
    source_confidence = str(recommendation.get("confidence") or "").strip().title()
    if source_confidence in {"High", "Moderate", "Low"}:
        return source_confidence
    return "Low"


def _assumptions(pricing: dict[str, Any], recommendation: dict[str, Any]) -> list[str]:
    assumptions = []
    if _money(pricing.get("market_reference")):
        assumptions.append(f"Market reference is ${_money(pricing.get('market_reference')):,.0f}.")
    if _money(pricing.get("direct_cost")):
        assumptions.append(f"Direct cost estimate is ${_money(pricing.get('direct_cost')):,.0f}.")
    if _rate(pricing.get("contingency_rate")):
        assumptions.append(f"Contingency rate is {_rate(pricing.get('contingency_rate')):.0%}.")
    if _rate(pricing.get("overhead_rate")):
        assumptions.append(f"Overhead rate is {_rate(pricing.get('overhead_rate')):.0%}.")
    if _rate(pricing.get("margin_rate")):
        assumptions.append(f"Target margin rate is {_rate(pricing.get('margin_rate')):.0%}.")
    if recommendation.get("basis"):
        assumptions.append(str(recommendation.get("basis")))
    return _unique(assumptions)[:8]


def _pricing_risks(
    pricing: dict[str, Any],
    recommendation: dict[str, Any],
    comps: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[str]:
    risks = []
    if len([comp for comp in comps if _money(comp.get("award_value")) > 0]) < 2:
        risks.append("Few close comparable awards are available; treat the range as directional.")
    if _rate(pricing.get("win_probability")) and _rate(pricing.get("win_probability")) < 0.25:
        risks.append("Estimated win probability is low at the target bid.")
    if _rate(pricing.get("complexity_score")) > 0.55:
        risks.append("Scope complexity is high; estimator should review quantities and exclusions.")
    if not rows:
        risks.append("Official PDF pricing forms have not been verified yet.")
    if str(recommendation.get("confidence") or "").lower() == "low":
        risks.append("Underlying bid recommendation confidence is low.")
    return _unique(risks)[:6]


def _evidence(
    pricing: dict[str, Any],
    recommendation: dict[str, Any],
    historical: dict[str, Any],
    rag: dict[str, Any],
    blockers: list[str],
) -> list[str]:
    evidence = [
        *[str(item) for item in pricing.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in recommendation.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in historical.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in rag.get("evidence") or [] if str(item).strip()],
    ]
    evidence.extend(blockers)
    return _unique(evidence)[:10]


def _dict_value(source: Any, key: str) -> dict[str, Any]:
    value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value) if isinstance(value, dict) else {}


def _rows(value: Any | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return {}


def _money(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _rate(value: Any) -> float:
    return max(0.0, min(1.0, _money(value)))


def _round_money(value: float) -> float:
    amount = max(0.0, float(value or 0.0))
    if amount <= 0:
        return 0.0
    if amount < 100000:
        increment = 1000
    elif amount < 1000000:
        increment = 5000
    else:
        increment = 10000
    return float(round(amount / increment) * increment)


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
