from __future__ import annotations

from typing import Any

from contract_radar.models import BusinessProfile, EvaluatedOpportunity, OpportunityBrief, RequirementExtraction


BRIEF_MODE = "deterministic_bid_brief"


def brief_status() -> dict[str, Any]:
    return {
        "available": True,
        "mode": BRIEF_MODE,
        "purpose": "Build owner review packets from bid gates, historical evidence, and company profile data.",
    }


def enrich_opportunity_briefs_with_stats(
    profile: BusinessProfile,
    opportunities: list[EvaluatedOpportunity],
) -> tuple[list[EvaluatedOpportunity], str, dict[str, Any]]:
    enriched = [enrich_opportunity_brief(profile, opportunity) for opportunity in opportunities]
    stats = {
        "shortlisted_for_brief": len(opportunities),
        "briefs_generated": len(enriched),
        "briefs_from_rules": len(enriched),
    }
    return enriched, BRIEF_MODE, stats


def enrich_opportunity_brief(profile: BusinessProfile, opportunity: EvaluatedOpportunity) -> EvaluatedOpportunity:
    opportunity.requirements = _requirements_from_trace(opportunity)
    opportunity.opportunity_brief = _brief_from_trace(profile, opportunity)
    _attach_brief_to_trace(opportunity)
    return opportunity


def _requirements_from_trace(opportunity: EvaluatedOpportunity) -> RequirementExtraction:
    solicitation = opportunity.solicitation
    trace = opportunity.bid_fitness_trace
    scorecard = trace.scorecard_labels or {}
    matched_terms = list(opportunity.matched_terms or [])
    missing = list(opportunity.missing_requirements or [])
    blockers = list(trace.hard_blockers or [])
    warnings = list(trace.soft_warnings or [])
    capacity_warnings = list((opportunity.capacity_assessment.warnings or []))

    return RequirementExtraction(
        source=BRIEF_MODE,
        services=matched_terms[:8],
        certifications=_extract_profile_like_items(missing, ("certification", "licence", "license", "clearance")),
        documents=_extract_profile_like_items(
            [*missing, *trace.requirement_signals],
            ("document", "insurance", "wsib", "bond", "reference", "policy", "plan"),
        ),
        facility_signals=[value for value in [solicitation.division, solicitation.category, solicitation.wards] if value],
        risk_flags=[*blockers[:4], *warnings[:4]],
        capacity_flags=capacity_warnings[:4],
        procurement_type=solicitation.solicitation_type,
        deadline_risk=scorecard.get("Deadline Risk", ""),
        delivery_complexity=scorecard.get("Pursuit Effort", ""),
        scope_size=scorecard.get("Execution Capacity", ""),
        disqualifying_requirements=blockers if opportunity.label == "Skip" else [],
        next_action=scorecard.get("Recommended Action", opportunity.label),
        summary=trace.final_rationale or _fallback_summary(opportunity),
    )


def _brief_from_trace(profile: BusinessProfile, opportunity: EvaluatedOpportunity) -> OpportunityBrief:
    trace = opportunity.bid_fitness_trace
    solicitation = opportunity.solicitation
    blockers = list(trace.hard_blockers or [])
    warnings = list(trace.soft_warnings or [])
    required_documents = list(dict.fromkeys([*profile.ready_documents, *opportunity.requirements.documents]))
    missing_items = list(dict.fromkeys([*opportunity.missing_requirements, *opportunity.requirements.disqualifying_requirements]))
    title = solicitation.description or solicitation.document_number

    return OpportunityBrief(
        source=BRIEF_MODE,
        owner_summary=_owner_summary(profile, opportunity, title),
        fit_reason=_fit_reason(opportunity),
        blockers=[*blockers[:4], *warnings[:3]],
        required_documents=required_documents[:10],
        missing_items=missing_items[:8],
        clarification_questions=_clarification_questions(opportunity),
        next_steps=_next_steps(profile, opportunity),
        buyer_email_draft=_buyer_email_draft(profile, opportunity),
    )


def _owner_summary(profile: BusinessProfile, opportunity: EvaluatedOpportunity, title: str) -> str:
    action = opportunity.capacity_assessment.recommended_action or opportunity.label
    value = opportunity.predicted_bid or opportunity.bid_recommendation.recommended_bid or 0
    value_text = f" Estimated bid worksheet starts around ${value:,.0f}." if value else ""
    return (
        f"{profile.name} is marked {opportunity.label} for {title}. "
        f"Recommended action: {action}.{value_text}"
    )


def _fit_reason(opportunity: EvaluatedOpportunity) -> str:
    trace = opportunity.bid_fitness_trace
    if trace.final_rationale:
        return trace.final_rationale
    if opportunity.matched_terms:
        return f"Matched scope terms: {', '.join(opportunity.matched_terms[:5])}."
    return _fallback_summary(opportunity)


def _clarification_questions(opportunity: EvaluatedOpportunity) -> list[str]:
    questions = [
        "Are there mandatory site visits or addenda that change the response requirements?",
        "Are equivalent certifications, subcontractors, or partner qualifications accepted?",
    ]
    if opportunity.days_until_deadline is None:
        questions.insert(0, "What is the confirmed submission deadline and timezone?")
    if opportunity.pricing_breakdown.market_reference:
        questions.append("Are there pricing forms or unit-rate schedules that differ from the historical award comparables?")
    return questions[:4]


def _next_steps(profile: BusinessProfile, opportunity: EvaluatedOpportunity) -> list[str]:
    steps = [
        "Confirm final eligibility against the official solicitation package and addenda.",
        "Assign an owner or estimator to validate scope, schedule, and price assumptions.",
        "Gather required company documents and references for the submission package.",
    ]
    if opportunity.pricing_breakdown.recommended_bid:
        steps.append("Review the pricing worksheet before committing to a final bid amount.")
    if profile.active_pursuit_count >= profile.max_active_pursuits:
        steps.append("Decide whether another active pursuit should pause before this bid starts.")
    return steps


def _buyer_email_draft(profile: BusinessProfile, opportunity: EvaluatedOpportunity) -> str:
    solicitation = opportunity.solicitation
    buyer_name = solicitation.buyer_name or "Procurement Team"
    document = solicitation.document_number or "the solicitation"
    capability_line = ", ".join(opportunity.matched_terms[:5]) or profile.business_type
    return (
        f"Subject: Question on {document}\n\n"
        f"Hello {buyer_name},\n\n"
        f"{profile.name} is reviewing {document}. We provide {capability_line} and are confirming "
        "whether the posted requirements, addenda, and response forms are complete before deciding on a bid.\n\n"
        "Please let us know if there are mandatory details or upcoming addenda bidders should account for.\n\n"
        f"Thank you,\n{profile.name}"
    )


def _attach_brief_to_trace(opportunity: EvaluatedOpportunity) -> None:
    trace = opportunity.bid_fitness_trace
    if "Bid brief generated from deterministic decision trace." not in trace.rules_triggered:
        trace.rules_triggered.append("Bid brief generated from deterministic decision trace.")


def _extract_profile_like_items(values: list[str], needles: tuple[str, ...]) -> list[str]:
    matched: list[str] = []
    for value in values:
        text = str(value or "").strip()
        lower = text.lower()
        if text and any(needle in lower for needle in needles):
            matched.append(text)
    return list(dict.fromkeys(matched))[:6]


def _fallback_summary(opportunity: EvaluatedOpportunity) -> str:
    return f"{opportunity.label}: {opportunity.reasons[0] if opportunity.reasons else 'review the listing evidence'}."
