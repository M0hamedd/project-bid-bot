from __future__ import annotations

from typing import Any

from contract_radar.line_item_pricing import build_line_item_cost_rollup


PENDING_ESTIMATOR_APPROVAL_STATUS = "pending_estimator_approval"
ESTIMATOR_APPROVED_STATUS = "approved"
PRICING_INPUT_TYPES = {
    "quantity",
    "unit_count",
    "direct_cost",
    "overhead",
    "contingency",
    "margin",
    "target_bid_override",
    "line_item_unit_cost",
}


def build_pricing_worksheet(
    opportunity: Any,
    *,
    compliance_matrix: Any | None = None,
    pricing_inputs: Any | None = None,
) -> dict[str, Any]:
    pricing = _dict_value(opportunity, "pricing_breakdown")
    recommendation = _dict_value(opportunity, "bid_recommendation")
    historical = _dict_value(opportunity, "historical")
    rag = _dict_value(opportunity, "rag_evidence")
    customer_outcomes = _dict_value(opportunity, "customer_outcomes")
    estimator_inputs = _pricing_inputs(pricing_inputs if pricing_inputs is not None else _value(opportunity, "pricing_inputs"))
    pricing_line_items = _pricing_line_items(opportunity)
    rollup_source = _opportunity_with_pricing_inputs(opportunity, estimator_inputs)
    line_item_rollup = build_line_item_cost_rollup(pricing_line_items, rollup_source)
    quantity_summary = _quantity_summary(opportunity, pricing_line_items)
    pricing_form_detected = bool(_value(opportunity, "pricing_form_detected") or _value(_dict_value(opportunity, "pricing_extraction"), "pricing_form_detected"))
    rows = _rows(compliance_matrix)
    blockers = _pricing_blockers(rows)
    missing_inputs = _missing_pricing_inputs(opportunity, estimator_inputs)
    blockers.extend(_line_item_blockers(line_item_rollup))

    recommended = _money(
        _latest_input_value(estimator_inputs, "target_bid_override")
        or pricing.get("recommended_bid")
        or recommendation.get("recommended_bid")
        or line_item_rollup.get("target_bid")
    )
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

    comps = _comparable_awards(historical, rag, customer_outcomes)
    confidence = _confidence(pricing, recommendation, comps, blockers)
    status = _worksheet_status(blockers, missing_inputs, bool(rows))
    assumptions = _assumptions(pricing, recommendation, estimator_inputs, pricing_line_items, line_item_rollup)
    risks = _pricing_risks(
        pricing,
        recommendation,
        comps,
        rows,
        missing_inputs,
        pricing_form_detected,
        pricing_line_items,
        line_item_rollup,
        recommended,
    )

    return {
        "source": "deterministic_pricing_worksheet",
        "status": status,
        "low_bid": low,
        "target_bid": recommended,
        "high_bid": high,
        "target_bid_source": "estimator_input" if _latest_input_value(estimator_inputs, "target_bid_override") else "agent_estimate",
        "confidence": confidence,
        "can_use_for_owner_packet": status in {"draft_agent_estimate", "estimator_review_required"} and recommended > 0,
        "blockers": blockers,
        "missing_inputs": missing_inputs,
        "estimator_inputs": estimator_inputs,
        "pricing_form_detected": pricing_form_detected,
        "pricing_line_items": pricing_line_items,
        "line_item_rollup": line_item_rollup,
        "quantity_summary": quantity_summary,
        "assumptions": assumptions,
        "risks": risks,
        "comparable_awards": comps,
        "cost_stack": {
            "market_reference": _money(pricing.get("market_reference")),
            "direct_cost": _money(_latest_input_value(estimator_inputs, "direct_cost") or line_item_rollup.get("direct_cost") or pricing.get("direct_cost")),
            "contingency": _money(_latest_input_value(estimator_inputs, "contingency") or line_item_rollup.get("contingency") or pricing.get("contingency")),
            "overhead": _money(_latest_input_value(estimator_inputs, "overhead") or line_item_rollup.get("overhead") or pricing.get("overhead")),
            "estimated_cost": _money(line_item_rollup.get("estimated_cost") or pricing.get("estimated_cost")),
            "target_margin": _money(_latest_input_value(estimator_inputs, "margin") or line_item_rollup.get("margin") or pricing.get("margin")),
            "bid_prep_cost": _money(pricing.get("bid_prep_cost")),
        },
        "rates": {
            "contingency_rate": _rate(_dict_value(line_item_rollup, "rates").get("contingency_rate") or pricing.get("contingency_rate")),
            "overhead_rate": _rate(_dict_value(line_item_rollup, "rates").get("overhead_rate") or pricing.get("overhead_rate")),
            "margin_rate": _rate(_dict_value(line_item_rollup, "rates").get("margin_rate") or pricing.get("margin_rate")),
            "win_probability": _rate(pricing.get("win_probability")),
        },
        "candidate_bids": candidate_bids,
        "evidence": _evidence(pricing, recommendation, historical, rag, customer_outcomes, blockers, pricing_line_items),
    }


def with_estimator_approval(
    worksheet: dict[str, Any] | None,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(worksheet or {})
    approval_data = dict(approval or {})
    target_bid = _money(payload.get("target_bid"))
    base_status = str(payload.get("status") or "")
    base_ready = bool(payload.get("can_use_for_owner_packet")) and not base_status.startswith("blocked") and target_bid > 0
    approved_target = _money(approval_data.get("approved_target_bid") or target_bid)
    is_approved = str(approval_data.get("status") or "") == ESTIMATOR_APPROVED_STATUS and approved_target > 0

    payload["approval_required"] = True
    payload["estimator_approval_status"] = (
        ESTIMATOR_APPROVED_STATUS
        if base_ready and is_approved
        else PENDING_ESTIMATOR_APPROVAL_STATUS
    )
    payload["can_use_for_owner_packet"] = base_ready and is_approved
    if base_ready and is_approved:
        payload["status"] = "estimator_approved"
        payload["target_bid"] = approved_target
        payload["estimator_approval"] = {
            "approval_id": str(approval_data.get("approval_id") or ""),
            "status": ESTIMATOR_APPROVED_STATUS,
            "approved_target_bid": approved_target,
            "approved_by": str(approval_data.get("approved_by") or "Estimator"),
            "approved_at": str(approval_data.get("approved_at") or ""),
            "note": str(approval_data.get("note") or ""),
        }
    return payload


def with_pricing_worksheet(
    opportunity: Any,
    *,
    compliance_matrix: Any | None = None,
) -> dict[str, Any]:
    payload = dict(opportunity) if isinstance(opportunity, dict) else _to_dict(opportunity)
    payload["pricing_worksheet"] = build_pricing_worksheet(payload, compliance_matrix=compliance_matrix)
    return payload


def validate_pricing_input(payload: dict[str, Any] | None, *, analysis_id: str, created_at: str) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    input_type = str(data.get("input_type") or "").strip()
    if input_type not in PRICING_INPUT_TYPES:
        raise ValueError(f"Unsupported pricing input type: {input_type}")
    value = _money(data.get("value"))
    if value <= 0:
        raise ValueError("Pricing input value must be greater than zero.")
    unit = str(data.get("unit") or "").strip()
    created_by = str(data.get("created_by") or data.get("approved_by") or "Estimator").strip() or "Estimator"
    pricing_input_id = str(data.get("pricing_input_id") or "").strip() or _pricing_input_id(
        analysis_id,
        input_type,
        value,
        unit,
        created_by,
        created_at,
    )
    record = {
        "pricing_input_id": pricing_input_id,
        "analysis_id": analysis_id,
        "input_type": input_type,
        "value": value,
        "unit": unit,
        "source": "estimator_input",
        "created_by": created_by,
        "created_at": created_at,
        "note": str(data.get("note") or "").strip(),
    }
    if input_type == "line_item_unit_cost":
        line_item_id = str(data.get("line_item_id") or "").strip()
        if not line_item_id:
            raise ValueError("A line_item_id is required for a line item unit cost.")
        record["line_item_id"] = line_item_id
        record["description"] = str(data.get("description") or "").strip()
        record["keywords"] = _text_list(data.get("keywords") or data.get("description") or "")
    return record


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


def _line_item_blockers(line_item_rollup: dict[str, Any]) -> list[str]:
    if not isinstance(line_item_rollup, dict):
        return []
    unpriced_count = int(_money(line_item_rollup.get("unpriced_line_item_count")))
    if unpriced_count <= 0:
        return []
    return [
        f"{unpriced_count} extracted PDF pricing line item(s) need estimator unit costs before target-bid approval."
    ]


def _worksheet_status(blockers: list[str], missing_inputs: list[dict[str, str]], has_rows: bool) -> str:
    if missing_inputs:
        return "blocked_missing_pricing_inputs"
    if blockers:
        return "blocked"
    return "estimator_review_required" if has_rows else "draft_agent_estimate"


def _missing_pricing_inputs(opportunity: Any, estimator_inputs: list[dict[str, Any]]) -> list[dict[str, str]]:
    requirements = _required_pricing_inputs(opportunity)
    present = {str(item.get("input_type") or "") for item in estimator_inputs if _money(item.get("value")) > 0}
    present.update(_extracted_pricing_input_types(opportunity))
    return [
        {
            "input_type": input_type,
            "reason": _missing_input_reason(input_type),
        }
        for input_type in requirements
        if input_type not in present
    ]


def _required_pricing_inputs(opportunity: Any) -> list[str]:
    raw = _value(opportunity, "required_pricing_inputs")
    if not raw:
        pricing = _dict_value(opportunity, "pricing_breakdown")
        recommendation = _dict_value(opportunity, "bid_recommendation")
        raw = pricing.get("required_pricing_inputs") or recommendation.get("required_pricing_inputs")
    return _unique([
        str(item).strip()
        for item in raw or []
        if str(item).strip() in PRICING_INPUT_TYPES
    ])


def _extracted_pricing_input_types(opportunity: Any) -> set[str]:
    line_items = _pricing_line_items(opportunity)
    rollup = build_line_item_cost_rollup(line_items, opportunity)
    types: set[str] = set()
    if any(_money(item.get("quantity")) > 0 for item in line_items):
        types.add("quantity")
    if _money(rollup.get("direct_cost")) > 0 and _money(rollup.get("coverage")) >= 0.75:
        types.add("direct_cost")
    return types


def _missing_input_reason(input_type: str) -> str:
    return {
        "quantity": "Estimator quantity is required before pricing can be approved.",
        "unit_count": "Estimator unit count is required before pricing can be approved.",
        "direct_cost": "Estimator direct cost input is required before pricing can be approved.",
        "overhead": "Estimator overhead input is required before pricing can be approved.",
        "contingency": "Estimator contingency input is required before pricing can be approved.",
        "margin": "Estimator margin input is required before pricing can be approved.",
        "target_bid_override": "Estimator target bid override is required before pricing can be approved.",
        "line_item_unit_cost": "Estimator unit cost is required before line-item pricing can be approved.",
    }.get(input_type, "Estimator pricing input is required before pricing can be approved.")


def _comparable_awards(
    historical: dict[str, Any],
    rag: dict[str, Any],
    customer_outcomes: dict[str, Any],
) -> list[dict[str, Any]]:
    comps: list[dict[str, Any]] = _customer_outcome_comps(customer_outcomes)
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


def _customer_outcome_comps(customer_outcomes: dict[str, Any]) -> list[dict[str, Any]]:
    comps: list[dict[str, Any]] = []
    for item in customer_outcomes.get("matches") or []:
        if not isinstance(item, dict):
            continue
        final_bid = _money(item.get("final_bid_amount"))
        winning_amount = _money(item.get("winning_amount"))
        amount = winning_amount or final_bid
        comps.append(
            {
                "source": "customer_outcome",
                "document_number": str(item.get("opportunity_id") or ""),
                "description": str(item.get("opportunity_title") or ""),
                "buyer": "",
                "division": str(item.get("division") or ""),
                "supplier": str(item.get("winner_name") or ""),
                "award_value": amount,
                "final_bid_amount": final_bid,
                "winning_amount": winning_amount,
                "award_status": str(item.get("award_status") or "unknown"),
                "matched_terms": [str(term) for term in item.get("matched_terms") or [] if str(term).strip()],
            }
        )
    return comps


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


def _assumptions(
    pricing: dict[str, Any],
    recommendation: dict[str, Any],
    estimator_inputs: list[dict[str, Any]],
    pricing_line_items: list[dict[str, Any]],
    line_item_rollup: dict[str, Any],
) -> list[str]:
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
    for item in estimator_inputs:
        input_type = str(item.get("input_type") or "").replace("_", " ")
        value = _money(item.get("value"))
        unit = str(item.get("unit") or "").strip()
        label = f"{value:,.2f} {unit}".strip()
        assumptions.append(f"Estimator input: {input_type} = {label}.")
    if pricing_line_items:
        assumptions.append(f"Official PDF pricing schedule has {len(pricing_line_items)} cited quantity line item(s).")
        for item in pricing_line_items[:3]:
            description = str(item.get("description") or "line item")
            quantity = _money(item.get("quantity"))
            unit = str(item.get("unit") or "").strip()
            assumptions.append(f"PDF quantity: {description} = {quantity:,.2f} {unit}.")
    for item in line_item_rollup.get("assumptions") or []:
        assumptions.append(str(item))
    return _unique(assumptions)[:8]


def _pricing_risks(
    pricing: dict[str, Any],
    recommendation: dict[str, Any],
    comps: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    missing_inputs: list[dict[str, str]],
    pricing_form_detected: bool,
    pricing_line_items: list[dict[str, Any]],
    line_item_rollup: dict[str, Any],
    target_bid: float,
) -> list[str]:
    risks = []
    for item in missing_inputs:
        risks.append(str(item.get("reason") or "Estimator pricing input is missing."))
    if pricing_form_detected and not pricing_line_items:
        risks.append("Pricing form language was detected, but no line-item quantities were extracted from the PDF.")
    for item in line_item_rollup.get("risks") or []:
        risks.append(str(item))
    rollup_target = _money(line_item_rollup.get("target_bid"))
    if rollup_target > 0 and target_bid > 0:
        variance = abs(rollup_target - target_bid) / max(target_bid, rollup_target)
        if variance > 0.25:
            risks.append(
                f"Line-item rollup target ${rollup_target:,.0f} differs materially from market target ${target_bid:,.0f}."
            )
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
    customer_outcomes: dict[str, Any],
    blockers: list[str],
    pricing_line_items: list[dict[str, Any]],
) -> list[str]:
    evidence = [
        *[str(item) for item in pricing.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in recommendation.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in historical.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in rag.get("evidence") or [] if str(item).strip()],
        *[str(item) for item in customer_outcomes.get("evidence") or [] if str(item).strip()],
    ]
    for item in pricing_line_items[:5]:
        description = str(item.get("description") or "line item")
        quantity = _money(item.get("quantity"))
        unit = str(item.get("unit") or "").strip()
        evidence.append(f"PDF pricing line item: {description} = {quantity:,.2f} {unit}.")
    evidence.extend(blockers)
    return _unique(evidence)[:10]


def _opportunity_with_pricing_inputs(opportunity: Any, estimator_inputs: list[dict[str, Any]]) -> Any:
    if isinstance(opportunity, dict):
        payload = dict(opportunity)
        payload["pricing_inputs"] = estimator_inputs
        return payload
    payload = _to_dict(opportunity)
    payload["pricing_inputs"] = estimator_inputs
    return payload


def _dict_value(source: Any, key: str) -> dict[str, Any]:
    value = _value(source, key)
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value) if isinstance(value, dict) else {}


def _value(source: Any, key: str) -> Any:
    return source.get(key) if isinstance(source, dict) else getattr(source, key, None)


def _pricing_inputs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        input_type = str(item.get("input_type") or "").strip()
        if input_type not in PRICING_INPUT_TYPES:
            continue
        amount = _money(item.get("value"))
        if amount <= 0:
            continue
        record = {
            "pricing_input_id": str(item.get("pricing_input_id") or ""),
            "analysis_id": str(item.get("analysis_id") or ""),
            "input_type": input_type,
            "value": amount,
            "unit": str(item.get("unit") or ""),
            "source": str(item.get("source") or ""),
            "created_by": str(item.get("created_by") or ""),
            "created_at": str(item.get("created_at") or ""),
            "note": str(item.get("note") or ""),
        }
        if input_type == "line_item_unit_cost":
            record["line_item_id"] = str(item.get("line_item_id") or "")
            record["description"] = str(item.get("description") or "")
            record["keywords"] = _text_list(item.get("keywords") or item.get("description") or "")
        rows.append(record)
    return rows


def _pricing_line_items(opportunity: Any) -> list[dict[str, Any]]:
    value = _value(opportunity, "pricing_line_items")
    if not value:
        extraction = _dict_value(opportunity, "pricing_extraction")
        value = extraction.get("pricing_line_items")
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        quantity = _money(item.get("quantity"))
        if quantity <= 0:
            continue
        citation = item.get("citation") if isinstance(item.get("citation"), dict) else {}
        rows.append(
            {
                "line_item_id": str(item.get("line_item_id") or ""),
                "description": str(item.get("description") or "Pricing line item").strip(),
                "quantity": quantity,
                "unit": str(item.get("unit") or "").strip(),
                "source": str(item.get("source") or "uploaded_pdf"),
                "confidence": str(item.get("confidence") or "deterministic"),
                "citation": {
                    "source": str(citation.get("source") or ""),
                    "page": citation.get("page"),
                    "chunk_id": str(citation.get("chunk_id") or ""),
                    "snippet": str(citation.get("snippet") or ""),
                    "source_type": str(citation.get("source_type") or "uploaded_pdf"),
                    "source_label": str(citation.get("source_label") or "Official PDF"),
                },
            }
        )
    return rows[:30]


def _quantity_summary(opportunity: Any, line_items: list[dict[str, Any]]) -> dict[str, Any]:
    raw = _value(opportunity, "quantity_summary")
    if isinstance(raw, dict) and raw:
        summary = dict(raw)
    else:
        extraction = _dict_value(opportunity, "pricing_extraction")
        summary = dict(extraction.get("quantity_summary") or {}) if isinstance(extraction.get("quantity_summary"), dict) else {}
    units = summary.get("units") if isinstance(summary.get("units"), dict) else {}
    if not units:
        units = {}
        for item in line_items:
            unit = str(item.get("unit") or "").strip()
            if unit:
                units[unit] = _money(units.get(unit)) + _money(item.get("quantity"))
    return {
        "line_item_count": int(summary.get("line_item_count") or len(line_items)),
        "units": {str(key): _money(value) for key, value in units.items() if str(key).strip() and _money(value) > 0},
        "has_quantities": bool(summary.get("has_quantities") or line_items),
    }


def _latest_input_value(inputs: list[dict[str, Any]], input_type: str) -> float:
    for item in reversed(inputs):
        if str(item.get("input_type") or "") == input_type:
            return _money(item.get("value"))
    return 0.0


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


def _text_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


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


def _pricing_input_id(
    analysis_id: str,
    input_type: str,
    value: float,
    unit: str,
    created_by: str,
    created_at: str,
) -> str:
    import hashlib

    digest = hashlib.sha256(
        f"{analysis_id}:{input_type}:{value:.4f}:{unit}:{created_by}:{created_at}".encode("utf-8")
    ).hexdigest()[:16]
    return f"pricing-input-{digest}"


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
