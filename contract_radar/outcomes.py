from __future__ import annotations

import hashlib
from typing import Any


AWARD_STATUSES = {"won", "lost", "no_award_yet", "not_submitted", "unknown"}


def build_outcome_record(
    payload: dict[str, Any],
    *,
    business_profile: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
    now: str = "",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    profile = business_profile if isinstance(business_profile, dict) else {}
    opportunity_payload = opportunity if isinstance(opportunity, dict) else {}
    solicitation = opportunity_payload.get("solicitation") if isinstance(opportunity_payload.get("solicitation"), dict) else {}

    opportunity_id = str(
        payload.get("opportunity_id")
        or solicitation.get("document_number")
        or opportunity_payload.get("opportunity_id")
        or ""
    ).strip()
    if not opportunity_id:
        raise ValueError("An opportunity_id is required to record an outcome.")

    profile_id = str(payload.get("profile_id") or profile.get("profile_id") or "").strip()
    analysis_id = str(payload.get("analysis_id") or "").strip()
    submitted = _bool(payload.get("submitted"))
    award_status = _award_status(payload.get("award_status"), submitted=submitted)
    final_bid_amount = _money(payload.get("final_bid_amount"))
    winning_amount = _money(payload.get("winning_amount"))
    margin_estimate = _rate_or_money(payload.get("margin_estimate"))
    hours_spent = _money(payload.get("hours_spent"))
    matched_terms = _unique(
        [
            *[str(item) for item in payload.get("matched_terms") or [] if str(item).strip()],
            *[str(item) for item in opportunity_payload.get("matched_terms") or [] if str(item).strip()],
        ]
    )
    created_at = str(payload.get("created_at") or now)
    updated_at = str(now or payload.get("updated_at") or created_at)
    outcome_id = str(payload.get("outcome_id") or "").strip() or _id(
        "outcome",
        profile_id,
        opportunity_id,
        analysis_id,
    )
    return {
        "outcome_id": outcome_id,
        "profile_id": profile_id,
        "opportunity_id": opportunity_id,
        "analysis_id": analysis_id,
        "opportunity_title": str(payload.get("opportunity_title") or solicitation.get("description") or ""),
        "buyer_name": str(payload.get("buyer_name") or solicitation.get("buyer_name") or ""),
        "division": str(payload.get("division") or solicitation.get("division") or ""),
        "category": str(payload.get("category") or solicitation.get("category") or ""),
        "matched_terms": matched_terms,
        "submitted": submitted,
        "final_bid_amount": final_bid_amount,
        "award_status": award_status,
        "winning_amount": winning_amount,
        "winner_name": str(payload.get("winner_name") or ""),
        "reason_lost": str(payload.get("reason_lost") or ""),
        "hours_spent": hours_spent,
        "margin_estimate": margin_estimate,
        "notes": str(payload.get("notes") or ""),
        "created_at": created_at,
        "updated_at": updated_at,
        "source": "user_recorded_outcome",
    }


def summarize_outcomes(
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
    *,
    profile_id: str = "",
) -> dict[str, Any]:
    rows = _records(records, profile_id=profile_id)
    submitted = [row for row in rows if row.get("submitted")]
    won = [row for row in rows if row.get("award_status") == "won"]
    lost = [row for row in rows if row.get("award_status") == "lost"]
    not_submitted = [row for row in rows if row.get("award_status") == "not_submitted"]
    no_award = [row for row in rows if row.get("award_status") == "no_award_yet"]
    hours = [_money(row.get("hours_spent")) for row in rows if _money(row.get("hours_spent")) > 0]
    margins = [_rate_or_money(row.get("margin_estimate")) for row in rows if _rate_or_money(row.get("margin_estimate")) > 0]
    return {
        "profile_id": profile_id,
        "total": len(rows),
        "submitted": len(submitted),
        "won": len(won),
        "lost": len(lost),
        "not_submitted": len(not_submitted),
        "no_award_yet": len(no_award),
        "win_rate": round(len(won) / len(submitted), 4) if submitted else 0.0,
        "total_final_bid_amount": _round_money(sum(_money(row.get("final_bid_amount")) for row in submitted)),
        "average_hours_spent": round(sum(hours) / len(hours), 2) if hours else 0.0,
        "average_margin_estimate": round(sum(margins) / len(margins), 4) if margins else 0.0,
        "good_fit_terms": _top_terms(won),
        "bad_fit_terms": _top_terms(lost + not_submitted),
        "recent_outcomes": [_public_outcome(row) for row in sorted(rows, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[:6]],
    }


def customer_outcomes_for_opportunity(
    opportunity: Any,
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
    *,
    profile_id: str = "",
) -> dict[str, Any]:
    payload = opportunity.to_dict() if hasattr(opportunity, "to_dict") else dict(opportunity) if isinstance(opportunity, dict) else {}
    solicitation = payload.get("solicitation") if isinstance(payload.get("solicitation"), dict) else {}
    opportunity_terms = set(str(item).lower() for item in payload.get("matched_terms") or [] if str(item).strip())
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in _records(records, profile_id=profile_id):
        score = 0.0
        record_terms = set(str(item).lower() for item in record.get("matched_terms") or [] if str(item).strip())
        term_overlap = opportunity_terms & record_terms
        score += len(term_overlap) * 2.0
        if str(record.get("division") or "").lower() == str(solicitation.get("division") or "").lower() and record.get("division"):
            score += 2.0
        if str(record.get("category") or "").lower() == str(solicitation.get("category") or "").lower() and record.get("category"):
            score += 1.5
        if str(record.get("buyer_name") or "").lower() == str(solicitation.get("buyer_name") or "").lower() and record.get("buyer_name"):
            score += 1.0
        if score > 0:
            scored.append((score, record))
    matches = [
        _public_outcome(row, match_score=score)
        for score, row in sorted(scored, key=lambda item: (-item[0], str(item[1].get("updated_at") or "")))[:6]
    ]
    wins = [row for row in matches if row.get("award_status") == "won"]
    losses = [row for row in matches if row.get("award_status") == "lost"]
    score_delta = min(8, len(wins) * 4) - min(10, len(losses) * 5)
    evidence = []
    if wins:
        evidence.append(f"{len(wins)} similar customer win(s) found in recorded outcomes.")
    if losses:
        evidence.append(f"{len(losses)} similar customer loss(es) found in recorded outcomes.")
    if not evidence:
        evidence.append("No similar customer outcome records found.")
    return {
        "source": "customer_outcome_feedback",
        "matches": matches,
        "wins": len(wins),
        "losses": len(losses),
        "score_delta": score_delta,
        "evidence": evidence,
    }


def apply_outcome_feedback(
    profile: Any,
    opportunities: list[Any],
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
) -> list[Any]:
    profile_id = str(getattr(profile, "profile_id", "") or "").strip()
    for opportunity in opportunities:
        outcome_context = customer_outcomes_for_opportunity(opportunity, records, profile_id=profile_id)
        setattr(opportunity, "customer_outcomes", outcome_context)
        delta = int(outcome_context.get("score_delta") or 0)
        if delta:
            opportunity.rank_score = max(0, min(100, int(opportunity.rank_score or 0) + delta))
            if delta > 0:
                message = f"Customer outcomes: similar recorded wins increased fit score by {delta}."
                if message not in opportunity.bid_fitness_trace.positive_signals:
                    opportunity.bid_fitness_trace.positive_signals.append(message)
            else:
                message = f"Customer outcomes: similar recorded losses reduced fit score by {abs(delta)}."
                if message not in opportunity.bid_fitness_trace.soft_warnings:
                    opportunity.bid_fitness_trace.soft_warnings.append(message)
            opportunity.bid_fitness_trace.scorecard_labels["Customer Outcomes"] = f"{delta:+d} score"
        for evidence in outcome_context.get("evidence") or []:
            if evidence not in opportunity.bid_fitness_trace.historical_analogs:
                opportunity.bid_fitness_trace.historical_analogs.append(str(evidence))
    return opportunities


def _records(records: list[dict[str, Any]] | dict[str, dict[str, Any]], *, profile_id: str = "") -> list[dict[str, Any]]:
    values = records.values() if isinstance(records, dict) else records
    rows = [dict(item) for item in values or [] if isinstance(item, dict)]
    if profile_id:
        rows = [row for row in rows if str(row.get("profile_id") or "") == profile_id]
    return rows


def _public_outcome(row: dict[str, Any], *, match_score: float = 0.0) -> dict[str, Any]:
    payload = {
        "outcome_id": str(row.get("outcome_id") or ""),
        "opportunity_id": str(row.get("opportunity_id") or ""),
        "opportunity_title": str(row.get("opportunity_title") or ""),
        "division": str(row.get("division") or ""),
        "category": str(row.get("category") or ""),
        "matched_terms": [str(item) for item in row.get("matched_terms") or [] if str(item).strip()][:6],
        "submitted": bool(row.get("submitted")),
        "final_bid_amount": _money(row.get("final_bid_amount")),
        "award_status": str(row.get("award_status") or "unknown"),
        "winning_amount": _money(row.get("winning_amount")),
        "winner_name": str(row.get("winner_name") or ""),
        "reason_lost": str(row.get("reason_lost") or ""),
        "hours_spent": _money(row.get("hours_spent")),
        "margin_estimate": _rate_or_money(row.get("margin_estimate")),
        "updated_at": str(row.get("updated_at") or ""),
    }
    if match_score:
        payload["match_score"] = round(match_score, 2)
    return payload


def _top_terms(rows: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        for term in row.get("matched_terms") or []:
            key = str(term or "").strip().lower()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
    return [
        term
        for term, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]


def _award_status(value: Any, *, submitted: bool) -> str:
    status = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "win": "won",
        "winner": "won",
        "loss": "lost",
        "lose": "lost",
        "pending": "no_award_yet",
        "no_award": "no_award_yet",
        "not_submitted": "not_submitted",
        "not_submit": "not_submitted",
    }
    status = aliases.get(status, status)
    if not submitted:
        return "not_submitted"
    return status if status in AWARD_STATUSES else "unknown"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "submitted", "won", "lost"}


def _money(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _rate_or_money(value: Any) -> float:
    return _money(value)


def _round_money(value: float) -> float:
    return float(round(float(value or 0.0), 2))


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
