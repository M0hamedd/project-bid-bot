from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable


CATEGORIES = (
    "form",
    "certification",
    "insurance",
    "bonding",
    "license",
    "safety",
    "site_visit",
    "deadline",
    "pricing_sheet",
    "scope",
    "experience",
    "submission_instruction",
    "addendum",
    "other",
)
RESOLUTION_TYPES = {
    "site_visit_attended": "Site visit attended",
    "addendum_acknowledged": "Addendum acknowledged",
    "certificate_available": "Certificate available",
    "pricing_form_assigned": "Pricing form assigned",
    "uploaded_evidence": "Evidence uploaded or confirmed",
    "capability_confirmed": "Business capability confirmed",
    "not_applicable": "Requirement marked not applicable",
}

MANDATORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shall", re.compile(r"\bshall\b", re.IGNORECASE)),
    ("must", re.compile(r"\bmust\b", re.IGNORECASE)),
    ("mandatory", re.compile(r"\bmandatory\b", re.IGNORECASE)),
    ("required", re.compile(r"\brequir(?:ed|ement|ements|es|ing)\b", re.IGNORECASE)),
    ("submit", re.compile(r"\bsubmit(?:ted|tal|tals|s|ting)?\b", re.IGNORECASE)),
    ("provide", re.compile(r"\bprovid(?:e|ed|es|ing)\b", re.IGNORECASE)),
    ("attend", re.compile(r"\battend(?:ance|ed|ing|s)?\b", re.IGNORECASE)),
    ("bond", re.compile(r"\bbond(?:ed|ing|s)?\b", re.IGNORECASE)),
    ("insurance", re.compile(r"\binsurance\b", re.IGNORECASE)),
    ("WSIB", re.compile(r"\bwsib\b", re.IGNORECASE)),
    ("license", re.compile(r"\blicen[cs](?:e|ed|es|ing)?\b", re.IGNORECASE)),
    ("certificate", re.compile(r"\bcertificat(?:e|es|ion|ions)\b", re.IGNORECASE)),
    ("addendum", re.compile(r"\baddend(?:um|a)\b", re.IGNORECASE)),
)

STOPWORDS = {
    "all",
    "and",
    "are",
    "bid",
    "bidder",
    "bidders",
    "contract",
    "contractor",
    "for",
    "from",
    "have",
    "include",
    "included",
    "must",
    "of",
    "on",
    "or",
    "proponent",
    "proponents",
    "provide",
    "required",
    "shall",
    "submit",
    "the",
    "their",
    "this",
    "to",
    "with",
}


@dataclass
class TextChunk:
    text: str
    source: str = ""
    page: int | str | None = None
    chunk_id: str = ""

    @classmethod
    def from_any(cls, value: Any, index: int = 0) -> "TextChunk":
        if isinstance(value, TextChunk):
            return value
        if isinstance(value, str):
            return cls(text=value, chunk_id=str(index))
        if isinstance(value, dict):
            return cls(
                text=str(value.get("text") or value.get("content") or value.get("body") or ""),
                source=str(value.get("source") or value.get("source_name") or value.get("source_filename") or value.get("file") or ""),
                page=value.get("page") if value.get("page") is not None else value.get("page_number"),
                chunk_id=str(value.get("chunk_id") or value.get("id") or index),
            )
        return cls(
            text=str(_value(value, "text") or _value(value, "content") or ""),
            source=str(_value(value, "source") or _value(value, "source_name") or _value(value, "source_filename") or _value(value, "file") or ""),
            page=_value(value, "page", _value(value, "page_number")),
            chunk_id=str(_value(value, "chunk_id", _value(value, "id", index))),
        )


@dataclass
class RequirementCitation:
    source: str = ""
    page: int | str | None = None
    chunk_id: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequirementRow:
    requirement_id: str
    requirement: str
    category: str
    trigger: str
    citation: RequirementCitation
    requirement_detected: bool = True
    evidence_needed: list[str] = field(default_factory=list)
    business_has_capability: bool | None = None
    uploaded_evidence: list[dict[str, str]] = field(default_factory=list)
    matched_capabilities: list[str] = field(default_factory=list)
    resolved: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["citation"] = self.citation.to_dict()
        return data


def extract_requirements(
    chunks: Iterable[Any],
    contractor_profile: Any | None = None,
    document_inventory: Any | None = None,
) -> list[RequirementRow]:
    """Extract deterministic compliance rows from solicitation text chunks."""
    evidence = _Evidence.from_sources(contractor_profile, document_inventory)
    rows: list[RequirementRow] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for chunk_index, raw_chunk in enumerate(chunks):
        chunk = TextChunk.from_any(raw_chunk, chunk_index)
        for statement_index, statement in enumerate(_candidate_statements(chunk.text)):
            trigger = _mandatory_trigger(statement)
            if not trigger:
                continue
            category = classify_requirement(statement)
            state = infer_requirement_state(statement, category, evidence)
            requirement = _clean_statement(statement)
            key = (requirement.lower(), category, str(chunk.source), str(chunk.page), str(chunk.chunk_id))
            if key in seen:
                continue
            seen.add(key)
            citation = RequirementCitation(
                source=chunk.source,
                page=chunk.page,
                chunk_id=chunk.chunk_id,
                snippet=_snippet(requirement),
            )
            rows.append(
                RequirementRow(
                    requirement_id=_requirement_id(chunk, statement_index, requirement, category),
                    requirement=requirement,
                    category=category,
                    trigger=trigger,
                    citation=citation,
                    requirement_detected=True,
                    evidence_needed=state["evidence_needed"],
                    business_has_capability=state["business_has_capability"],
                    uploaded_evidence=state["uploaded_evidence"],
                    matched_capabilities=state["matched_capabilities"],
                    resolved=state["resolved"],
                    notes=state["notes"],
                )
            )
    return rows


def requirements_to_dicts(rows: Iterable[RequirementRow]) -> list[dict[str, Any]]:
    return [row.to_dict() for row in rows]


def classify_requirement(text: str) -> str:
    lower = text.lower()
    if _has_any(lower, ("addendum", "addenda")):
        return "addendum"
    if _has_any(lower, ("site visit", "site meeting", "job showing", "bidders meeting", "mandatory meeting")):
        return "site_visit"
    if _has_any(lower, ("closing date", "closing time", "submission deadline", "deadline", "due date", "no later than")):
        return "deadline"
    if _has_any(lower, ("pricing sheet", "pricing form", "price schedule", "schedule of prices", "unit price", "price form")):
        return "pricing_sheet"
    if _has_any(lower, ("bid bond", "performance bond", "labour and material bond", "surety", "bonding")) or re.search(r"\bbond\b", lower):
        return "bonding"
    if _has_any(lower, ("insurance", "commercial general liability", "cgl", "liability coverage")):
        return "insurance"
    if _has_any(lower, ("wsib", "health and safety", "safety plan", "traffic control plan", "cor safety")):
        return "safety"
    if re.search(r"\blicen[cs](?:e|ed|es|ing)?\b", lower) or _has_any(lower, ("permit", "registered trade")):
        return "license"
    if _has_any(lower, ("certificate", "certification", "certified", "clearance certificate")):
        return "certification"
    if _has_any(lower, ("similar experience", "references", "reference projects", "years of experience", "past projects")):
        return "experience"
    if _has_any(lower, ("form", "appendix", "schedule", "attachment")):
        return "form"
    if _has_any(lower, ("submit", "upload", "deliver", "sealed envelope", "electronic submission", "portal")):
        return "submission_instruction"
    if _has_any(lower, ("contractor shall", "contractor must", "work shall", "scope", "perform", "supply", "install", "replace")):
        return "scope"
    return "other"


def infer_requirement_state(
    text: str,
    category: str,
    evidence: Any | None = None,
) -> dict[str, Any]:
    normalized = evidence if isinstance(evidence, _Evidence) else _Evidence.from_sources(evidence, None)
    evidence_needed = _evidence_needed_for_category(category)
    uploaded_evidence = _uploaded_evidence_for_category(normalized, category)
    business_has_capability, matched_capabilities, capability_note = _business_capability_for_requirement(
        text,
        category,
        normalized,
    )
    resolved = _is_resolved(
        category=category,
        evidence_needed=evidence_needed,
        uploaded_evidence=uploaded_evidence,
        business_has_capability=business_has_capability,
    )

    if not normalized.has_context:
        return {
            "business_has_capability": None,
            "matched_capabilities": [],
            "uploaded_evidence": [],
            "evidence_needed": evidence_needed,
            "resolved": False,
            "notes": "No contractor profile or uploaded evidence supplied.",
        }

    if business_has_capability is False:
        notes = "Profile lists this as a capability gap."
    elif resolved:
        notes = "Required evidence or resolution has been recorded."
    elif uploaded_evidence:
        notes = "Evidence exists, but capability still needs confirmation."
    elif business_has_capability is True and evidence_needed:
        notes = f"Business appears capable; collect {', '.join(evidence_needed)}."
    elif business_has_capability is True:
        notes = capability_note or "Business appears capable."
    elif evidence_needed:
        notes = f"Collect {', '.join(evidence_needed)}."
    else:
        notes = capability_note or "Requirement needs manual review."

    return {
        "business_has_capability": business_has_capability,
        "matched_capabilities": matched_capabilities,
        "uploaded_evidence": uploaded_evidence,
        "evidence_needed": [] if resolved else evidence_needed,
        "resolved": resolved,
        "notes": notes,
    }


def apply_requirement_resolution(
    rows: list[dict[str, Any]],
    requirement_id: str,
    resolution_type: str,
    *,
    note: str = "",
    resolved_at: str = "",
) -> list[dict[str, Any]]:
    resolution_key = str(resolution_type or "").strip()
    if resolution_key not in RESOLUTION_TYPES:
        raise ValueError(f"Unsupported compliance resolution type: {resolution_type}")
    target_id = str(requirement_id or "").strip()
    if not target_id:
        raise ValueError("A requirement_id is required.")

    updated: list[dict[str, Any]] = []
    found = False
    for row in rows:
        current = dict(row)
        if str(current.get("requirement_id") or "") == target_id:
            found = True
            evidence = list(current.get("uploaded_evidence") or [])
            evidence.append(
                {
                    "type": resolution_key,
                    "label": RESOLUTION_TYPES[resolution_key],
                    "note": str(note or "").strip(),
                    "resolved_at": str(resolved_at or "").strip(),
                }
            )
            current["uploaded_evidence"] = evidence
            current["resolved"] = True
            current["evidence_needed"] = []
            current["resolution_type"] = resolution_key
            current["resolution_label"] = RESOLUTION_TYPES[resolution_key]
            if resolution_key == "capability_confirmed":
                current["business_has_capability"] = True
            if resolution_key == "not_applicable":
                current["business_has_capability"] = None
            current["notes"] = RESOLUTION_TYPES[resolution_key]
        updated.append(current)

    if not found:
        raise ValueError(f"Requirement {requirement_id} was not found in this analysis.")
    return updated


class _Evidence:
    def __init__(
        self,
        inventory_terms: list[str] | None = None,
        inventory_records: list[dict[str, Any]] | None = None,
        profile_terms: list[str] | None = None,
        missing_capabilities: list[str] | None = None,
        has_context: bool = False,
        has_inventory: bool = False,
        has_profile: bool = False,
    ) -> None:
        self.inventory_terms = _unique(inventory_terms or [])
        self.inventory_records = [dict(record) for record in inventory_records or [] if isinstance(record, dict)]
        self.profile_terms = _unique(profile_terms or [])
        self.missing_capabilities = _unique(missing_capabilities or [])
        self.has_context = has_context
        self.has_inventory = has_inventory
        self.has_profile = has_profile

    @classmethod
    def from_sources(cls, contractor_profile: Any | None, document_inventory: Any | None) -> "_Evidence":
        inventory_records = _inventory_records(document_inventory)
        inventory_terms = _inventory_terms(document_inventory)
        profile_terms: list[str] = []
        missing_capabilities: list[str] = []
        if contractor_profile is not None:
            profile_terms.extend(_profile_terms(contractor_profile))
            missing_capabilities.extend(_list_value(contractor_profile, "missing_capabilities"))
            insurance = str(_value(contractor_profile, "insurance_coverage") or "").strip()
            if insurance:
                profile_terms.append(insurance)
            bonding_limit = _value(contractor_profile, "bonding_single_job_limit")
            if bonding_limit not in (None, "", 0):
                profile_terms.append("bonding capacity")
        return cls(
            inventory_terms=inventory_terms,
            inventory_records=inventory_records,
            profile_terms=profile_terms,
            missing_capabilities=missing_capabilities,
            has_context=bool(contractor_profile is not None or document_inventory is not None),
            has_inventory=bool(document_inventory is not None),
            has_profile=bool(contractor_profile is not None),
        )

    def matches(self, needles: Iterable[str]) -> list[str]:
        matched: list[str] = []
        needle_terms = [str(needle or "").lower().strip() for needle in needles if str(needle or "").strip()]
        for evidence in self.inventory_terms:
            lower = evidence.lower()
            if any(needle in lower or lower in needle for needle in needle_terms):
                matched.append(evidence)
        return _unique(matched)

    def matching_records(self, needles: Iterable[str]) -> list[dict[str, Any]]:
        needle_terms = [str(needle or "").lower().strip() for needle in needles if str(needle or "").strip()]
        if not needle_terms:
            return []
        matched: list[dict[str, Any]] = []
        for record in self.inventory_records:
            if not _record_is_current(record):
                continue
            searchable = " ".join(
                [
                    str(record.get("label") or ""),
                    str(record.get("evidence_type") or ""),
                    " ".join(str(tag) for tag in record.get("capability_tags") or []),
                ]
            ).lower()
            if any(needle in searchable or searchable in needle for needle in needle_terms):
                matched.append(record)
        return matched[:5]

    def profile_matches(self, text: str) -> list[str]:
        text_terms = _terms(text)
        matched: list[str] = []
        for evidence in self.profile_terms:
            evidence_lower = evidence.lower()
            evidence_terms = _terms(evidence_lower)
            if evidence_lower and (evidence_lower in text or len(text_terms & evidence_terms) >= 2):
                matched.append(evidence)
        return _unique(matched)[:5]

    def missing_capability_matches(self, text: str) -> list[str]:
        text_terms = _terms(text)
        matched: list[str] = []
        for capability in self.missing_capabilities:
            capability_lower = capability.lower()
            capability_terms = _terms(capability_lower)
            if capability_lower and (capability_lower in text or len(text_terms & capability_terms) >= 2):
                matched.append(capability)
        return _unique(matched)


def _candidate_statements(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    rough_parts = re.split(r"(?:\n+|(?<=[.;!?])\s+)", normalized)
    statements: list[str] = []
    for part in rough_parts:
        cleaned = _clean_statement(part)
        if not cleaned:
            continue
        if len(cleaned) > 260:
            statements.extend(_split_long_statement(cleaned))
        else:
            statements.append(cleaned)
    return statements


def _split_long_statement(text: str) -> list[str]:
    parts = re.split(r"\s+(?:and|;)\s+(?=(?:the\s+)?(?:bidder|bidders|proponent|proponents|contractor|all|a|an)\b)", text)
    return [_clean_statement(part) for part in parts if _clean_statement(part)]


def _mandatory_trigger(text: str) -> str:
    for label, pattern in MANDATORY_PATTERNS:
        if pattern.search(text):
            return label
    return ""


def _requirement_id(chunk: TextChunk, statement_index: int, requirement: str, category: str) -> str:
    payload = "|".join([str(chunk.source), str(chunk.page), str(chunk.chunk_id), str(statement_index), category, requirement])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"REQ-{digest.upper()}"


def _clean_statement(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = re.sub(r"^[\-*\u2022]\s*", "", cleaned)
    return cleaned.strip()


def _snippet(text: str, limit: int = 220) -> str:
    cleaned = _clean_statement(text)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def _has_any(text: str, needles: Iterable[str]) -> bool:
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text)
        for needle in needles
    )


def _category_terms_for_evidence(category: str) -> tuple[str, ...]:
    return {
        "form": ("form", "appendix", "attachment", "schedule"),
        "certification": ("certificate", "certification", "certified", "clearance certificate"),
        "insurance": ("insurance", "commercial general liability", "cgl", "liability"),
        "bonding": ("bond", "bid bond", "performance bond", "surety", "bonding capacity"),
        "license": ("license", "licence", "permit", "registered trade"),
        "safety": ("wsib", "safety", "traffic control plan", "cor"),
        "pricing_sheet": ("pricing sheet", "pricing form", "price schedule", "schedule of prices", "unit price"),
        "submission_instruction": ("portal", "submission", "upload", "sealed envelope"),
    }.get(category, ())


def _evidence_needed_for_category(category: str) -> list[str]:
    return {
        "form": ["completed form"],
        "certification": ["current certificate"],
        "insurance": ["insurance certificate"],
        "bonding": ["bond or surety confirmation"],
        "license": ["license or permit proof"],
        "safety": ["safety clearance or plan"],
        "site_visit": ["site visit attendance"],
        "deadline": ["calendar confirmation"],
        "pricing_sheet": ["pricing form assigned"],
        "experience": ["reference evidence"],
        "submission_instruction": ["submission owner assigned"],
        "addendum": ["addendum acknowledgement"],
    }.get(category, [])


def _uploaded_evidence_for_category(evidence: "_Evidence", category: str) -> list[dict[str, str]]:
    records = evidence.matching_records(_evidence_terms_for_category(category))
    if records:
        return [
            {
                "type": "vault_evidence",
                "label": str(record.get("label") or record.get("evidence_type") or "Evidence vault item"),
                "note": str(record.get("verified_status") or ""),
                "resolved_at": "",
                "evidence_id": str(record.get("evidence_id") or ""),
                "evidence_type": str(record.get("evidence_type") or ""),
                "source": str(record.get("source") or "evidence_vault"),
                "verified_status": str(record.get("verified_status") or ""),
                "expires_at": str(record.get("expires_at") or ""),
            }
            for record in records
        ]
    matches = evidence.matches(_evidence_terms_for_category(category))
    return [
        {"type": "uploaded_evidence", "label": item, "note": "", "resolved_at": ""}
        for item in matches
    ]


def _business_capability_for_requirement(
    text: str,
    category: str,
    evidence: "_Evidence",
) -> tuple[bool | None, list[str], str]:
    lower = text.lower()
    if category == "scope":
        blockers = evidence.missing_capability_matches(lower)
        if blockers:
            return False, blockers, "Profile lists this scope as a missing capability."
        matches = evidence.profile_matches(lower)
        if matches:
            return True, matches, "Profile appears to cover this scope."
        return None, [], "Scope requires estimator review."

    if category in {"site_visit", "deadline", "pricing_sheet", "submission_instruction", "addendum", "form"}:
        return None, [], ""

    capability_terms = _profile_capability_terms_for_category(category)
    matches = evidence.profile_matches(" ".join([lower, *capability_terms]))
    if matches:
        return True, matches, "Profile has related capability, but evidence still needs confirmation."
    return None, [], ""


def _is_resolved(
    *,
    category: str,
    evidence_needed: list[str],
    uploaded_evidence: list[dict[str, str]],
    business_has_capability: bool | None,
) -> bool:
    if business_has_capability is False:
        return False
    if uploaded_evidence:
        return True
    if category == "scope" and business_has_capability is True and not evidence_needed:
        return True
    return False


def _evidence_terms_for_category(category: str) -> tuple[str, ...]:
    terms = {
        "form": ("completed form", "signed form", "form"),
        "certification": ("certificate", "certification", "clearance certificate"),
        "insurance": ("insurance certificate", "certificate of insurance", "commercial general liability", "cgl"),
        "bonding": ("bid bond", "performance bond", "surety", "bonding"),
        "license": ("license", "licence", "permit"),
        "safety": ("wsib", "safety plan", "traffic control plan", "cor"),
        "site_visit": ("site visit attended", "site meeting attended", "mandatory meeting attended", "job showing attended"),
        "deadline": ("deadline calendared", "calendar confirmation"),
        "pricing_sheet": ("pricing form assigned", "price schedule assigned", "pricing sheet"),
        "experience": ("reference", "references", "similar experience", "past projects"),
        "submission_instruction": ("submission owner assigned", "portal account", "submission checklist"),
        "addendum": ("addendum acknowledged", "addenda acknowledged", "addendum acknowledgement"),
    }
    return tuple([*terms.get(category, ()), *_category_terms_for_evidence(category)])


def _profile_capability_terms_for_category(category: str) -> tuple[str, ...]:
    return {
        "certification": ("certificate", "certification", "clearance"),
        "insurance": ("insurance", "commercial general liability", "cgl"),
        "bonding": ("bonding", "bond", "surety"),
        "license": ("license", "licence", "permit"),
        "safety": ("wsib", "safety", "traffic control"),
        "experience": ("references", "municipal references", "similar experience"),
    }.get(category, ())


def _inventory_terms(document_inventory: Any | None) -> list[str]:
    if document_inventory is None:
        return []
    records = _inventory_records(document_inventory)
    if records:
        terms: list[str] = []
        for record in records:
            if not _record_is_current(record):
                continue
            terms.append(str(record.get("label") or ""))
            terms.append(str(record.get("evidence_type") or ""))
            terms.extend(str(tag) for tag in record.get("capability_tags") or [])
        return _unique(terms)
    if isinstance(document_inventory, dict):
        terms: list[str] = []
        for key, value in document_inventory.items():
            if isinstance(value, bool):
                if value:
                    terms.append(str(key))
                continue
            if isinstance(value, (list, tuple, set)):
                terms.extend(str(item) for item in value if str(item).strip())
                if value:
                    terms.append(str(key))
                continue
            if value is not None and str(value).strip():
                terms.append(str(key))
                terms.append(str(value))
        return terms
    if isinstance(document_inventory, (list, tuple, set)):
        return [str(item) for item in document_inventory if str(item).strip()]
    return [str(document_inventory)] if str(document_inventory).strip() else []


def _inventory_records(document_inventory: Any | None) -> list[dict[str, Any]]:
    if document_inventory is None:
        return []
    if isinstance(document_inventory, dict):
        records = document_inventory.get("records")
        if isinstance(records, list):
            return [dict(record) for record in records if isinstance(record, dict)]
        if document_inventory.get("evidence_id") or document_inventory.get("evidence_type"):
            return [dict(document_inventory)]
        return []
    if isinstance(document_inventory, (list, tuple, set)):
        return [dict(record) for record in document_inventory if isinstance(record, dict)]
    return []


def _record_is_current(record: dict[str, Any]) -> bool:
    expires_at = str(record.get("expires_at") or "").strip()
    if not expires_at:
        return True
    expiry = expires_at[:10]
    if len(expiry) != 10:
        return True
    return expiry >= date.today().isoformat()


def _profile_terms(profile: Any) -> list[str]:
    fields = (
        "business_type",
        "skills",
        "ready_documents",
        "certifications",
        "owned_equipment",
        "recent_municipal_work",
        "good_fit_examples",
    )
    terms: list[str] = []
    for field_name in fields:
        value = _value(profile, field_name)
        if isinstance(value, (list, tuple, set)):
            terms.extend(str(item) for item in value if str(item).strip())
        elif value is not None and str(value).strip():
            terms.append(str(value))
    return terms


def _list_value(source: Any, key: str) -> list[str]:
    value = _value(source, key, []) or []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(term) > 2 and term not in STOPWORDS
    }


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned
