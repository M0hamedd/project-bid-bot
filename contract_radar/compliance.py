from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
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
STATUSES = ("ready", "missing", "needs_review", "blocker")

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
    status: str
    trigger: str
    citation: RequirementCitation
    matched_evidence: list[str] = field(default_factory=list)
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
            status, matched_evidence, notes = infer_requirement_status(statement, category, evidence)
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
                    status=status,
                    trigger=trigger,
                    citation=citation,
                    matched_evidence=matched_evidence,
                    notes=notes,
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


def infer_requirement_status(
    text: str,
    category: str,
    evidence: Any | None = None,
) -> tuple[str, list[str], str]:
    normalized = evidence if isinstance(evidence, _Evidence) else _Evidence.from_sources(evidence, None)
    if not normalized.has_context:
        return "needs_review", [], "No contractor profile or document inventory supplied."

    lower = text.lower()
    if category == "scope":
        blockers = normalized.missing_capability_matches(lower)
        if blockers:
            return "blocker", blockers, "Profile lists this scope as a missing capability."
        matches = normalized.profile_matches(lower)
        if matches:
            return "ready", matches, "Profile appears to cover this scope."
        return "needs_review", [], "Scope requires estimator review."

    if category == "site_visit":
        matches = normalized.matches(("site visit", "site meeting", "job showing", "mandatory meeting attended"))
        if matches:
            return "ready", matches, "Attendance evidence found."
        return "blocker", [], "Mandatory attendance gate is not documented."

    if category == "addendum":
        matches = normalized.matches(("addendum", "addenda", "addendum acknowledgment", "addenda acknowledged"))
        if matches:
            return "ready", matches, "Addendum acknowledgement evidence found."
        return "blocker", [], "Addendum acknowledgement is not documented."

    if category == "deadline":
        return "needs_review", [], "Deadline must be calendared and confirmed against the official source."

    if category == "experience":
        matches = normalized.matches(("reference", "references", "municipal references", "similar experience", "past projects"))
        if matches:
            return "ready", matches, "Experience evidence found."
        return "missing", [], "Experience or reference evidence is not documented."

    category_terms = _status_terms_for_category(category)
    matches = normalized.matches(category_terms)
    if matches:
        return "ready", matches, "Requirement evidence found."

    if category in {"form", "pricing_sheet", "insurance", "bonding", "license", "safety", "certification", "submission_instruction"}:
        return "missing", [], f"No matching {category.replace('_', ' ')} evidence found."

    profile_matches = normalized.profile_matches(lower)
    if profile_matches:
        return "ready", profile_matches, "Profile evidence found."
    return "needs_review", [], "Requirement needs manual review."


class _Evidence:
    def __init__(
        self,
        available_terms: list[str] | None = None,
        profile_terms: list[str] | None = None,
        missing_capabilities: list[str] | None = None,
        has_context: bool = False,
    ) -> None:
        self.available_terms = _unique(available_terms or [])
        self.profile_terms = _unique(profile_terms or [])
        self.missing_capabilities = _unique(missing_capabilities or [])
        self.has_context = has_context

    @classmethod
    def from_sources(cls, contractor_profile: Any | None, document_inventory: Any | None) -> "_Evidence":
        available_terms = _inventory_terms(document_inventory)
        profile_terms: list[str] = []
        missing_capabilities: list[str] = []
        if contractor_profile is not None:
            profile_terms.extend(_profile_terms(contractor_profile))
            missing_capabilities.extend(_list_value(contractor_profile, "missing_capabilities"))
            available_terms.extend(_list_value(contractor_profile, "ready_documents"))
            available_terms.extend(_list_value(contractor_profile, "certifications"))
            insurance = str(_value(contractor_profile, "insurance_coverage") or "").strip()
            if insurance:
                available_terms.append(insurance)
            bonding_limit = _value(contractor_profile, "bonding_single_job_limit")
            if bonding_limit not in (None, "", 0):
                available_terms.append("bonding capacity")
        return cls(
            available_terms=available_terms,
            profile_terms=profile_terms,
            missing_capabilities=missing_capabilities,
            has_context=bool(contractor_profile is not None or document_inventory is not None),
        )

    def matches(self, needles: Iterable[str]) -> list[str]:
        matched: list[str] = []
        needle_terms = [str(needle or "").lower().strip() for needle in needles if str(needle or "").strip()]
        for evidence in self.available_terms:
            lower = evidence.lower()
            if any(needle in lower or lower in needle for needle in needle_terms):
                matched.append(evidence)
        return _unique(matched)

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
    return any(needle in text for needle in needles)


def _status_terms_for_category(category: str) -> tuple[str, ...]:
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


def _inventory_terms(document_inventory: Any | None) -> list[str]:
    if document_inventory is None:
        return []
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
