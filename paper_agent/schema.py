from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Text = Annotated[str, Field(min_length=1, max_length=3000)]
Short = Annotated[str, Field(min_length=1, max_length=800)]


class Context(StrictModel):
    question: Annotated[str, Field(min_length=3, max_length=8000)]
    help_wanted: str = Field(default="", max_length=4000)
    constraints: str = Field(default="", max_length=4000)
    already_read: str = Field(default="", max_length=4000)


class Limits(StrictModel):
    candidates: int = Field(default=15, ge=1, le=30)
    fulltexts: int = Field(default=5, ge=1, le=10)
    target: int = Field(default=3, ge=1, le=5)
    searches: int = Field(default=6, ge=1, le=20)
    model_calls: int | None = Field(default=None, ge=1, le=1000)
    finalization_calls: int | None = Field(default=None, ge=1, le=1000)
    stalled_turns: int = Field(default=6, ge=3, le=20)
    tool_calls: int = Field(default=80, ge=1, le=160)
    seconds: int = Field(default=480, ge=5, le=1800)
    tokens: int = Field(default=500000, ge=500, le=1000000)
    output_tokens: int = Field(default=6500, ge=256, le=16000)
    network_timeout: int = Field(default=20, ge=1, le=60)
    retries: int = Field(default=1, ge=0, le=2)


class Usage(StrictModel):
    searches: int = 0
    model_calls: int = 0
    finalization_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # Reserves uncertain/failed requests rather than pretending they cost zero.
    charged_tokens: int = 0
    active_seconds: float = 0
    fulltext_attempts: list[str] = Field(default_factory=list)


class Chunk(StrictModel):
    id: str
    location: str
    text: str
    source_url: str


class CandidateReview(StrictModel):
    relevance: int = Field(ge=0, le=5)
    method_fit: int = Field(ge=0, le=5)
    evidence_potential: int = Field(ge=0, le=5)
    decision: Literal["fulltext", "reference", "exclude"]
    reason: Text
    quote: Short
    basis: Literal["abstract", "title_only"]
    limitation: str
    source_hash: str
    criteria_hash: str


class CandidateComparison(StrictModel):
    ranked_paper_ids: list[str]
    shortlist: list[str]
    summary: str
    cohort_hash: str


class Paper(StrictModel):
    id: str = Field(default_factory=lambda: "p_" + uuid4().hex[:10])
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    dedup_keys: list[str] = Field(default_factory=list)
    source: str
    source_id: str
    url: str
    fulltext_urls: list[str] = Field(default_factory=list)
    abstract: str = ""
    metadata_read: bool = False
    metadata_attempted: bool = False
    metadata_issue: str = ""
    screening_read_hash: str = ""
    screening_read_turn: int = -1
    abstract_read_ranges: list[tuple[int, int]] = Field(default_factory=list)
    screening: CandidateReview | None = None
    fulltext_status: str = "not_fetched"
    fulltext_errors: list[str] = Field(default_factory=list)
    extraction_note: str = ""
    chunks: dict[str, Chunk] = Field(default_factory=dict)
    read_chunks: list[str] = Field(default_factory=list)
    last_read_turn: int = -1
    verdict: str = "unassessed"
    relevance: int | None = None
    reason: str = ""


class EvidenceInput(StrictModel):
    chunk_id: Short
    quote: Annotated[str, Field(min_length=8, max_length=500)]
    claim: Text
    kind: Literal["paper_claim", "agent_interpretation"]


class Evidence(EvidenceInput):
    id: str
    paper_id: str


class CitedText(StrictModel):
    text: Text
    kind: Literal["paper_claim", "agent_interpretation"]
    evidence_ids: Annotated[list[str], Field(min_length=1, max_length=8)]


class PaperBrief(StrictModel):
    paper_id: Short
    selection_reason: CitedText
    problem: CitedText
    method: CitedText
    results: CitedText
    limitations: CitedText
    application: CitedText
    first_read_chunks: Annotated[list[str], Field(min_length=1, max_length=5)]


class Briefing(StrictModel):
    title: Short
    papers: Annotated[list[PaperBrief], Field(min_length=1, max_length=5)]
    comparison: Annotated[list[CitedText], Field(max_length=6)]
    reading_order: Annotated[list[str], Field(min_length=1, max_length=5)]
    scope: Text
    uncertainties: Annotated[list[Short], Field(min_length=1, max_length=10)]


class Event(StrictModel):
    seq: int
    kind: str
    summary: str
    call_id: str | None = None
    name: str | None = None
    arguments: dict | None = None
    result: dict | None = None
    model_turn: int = 0


class RunState(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    mode: Literal["live", "demo", "model_eval"]
    context: Context
    limits: Limits = Field(default_factory=Limits)
    model: str = ""
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] | None = None
    # Legacy/evaluation records retain their original completion rules.
    require_target: bool = False
    require_screening: bool = False
    require_depth: bool = False
    paper_briefs: dict[str, PaperBrief] = Field(default_factory=dict)
    progress_markers: list[str] = Field(default_factory=list)
    stalled_turns: int = 0
    candidate_comparison: CandidateComparison | None = None
    status: str = "ready"
    goal: str = ""
    criteria: list[str] = Field(default_factory=list)
    papers: dict[str, Paper] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    searches: list[dict] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    # Private API protocol items, never rendered in the UI or public trace.
    conversation: list[dict] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    pending_question: str | None = None
    answers: list[str] = Field(default_factory=list)
    briefing: Briefing | None = None
    stop_reason: str = ""
    pdf_error: str = ""
    scenario: str = "sufficient"

    def event(self, kind: str, summary: str, **kwargs):
        self.events.append(Event(seq=len(self.events) + 1, kind=kind, summary=summary,
                                 model_turn=self.usage.model_calls, **kwargs))


def normalize_doi(value: str | None) -> str:
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip().lower())


def normalize_title(value: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold())


def add_paper(state: RunState, incoming: Paper) -> str | None:
    incoming.doi = normalize_doi(incoming.doi) or None
    keys = {"title:" + normalize_title(incoming.title)}
    keys.update(f"{k}:{v}" for k, v in incoming.identifiers.items())
    if incoming.doi:
        keys.add("doi:" + incoming.doi)
    for p in state.papers.values():
        shared_id = any(p.identifiers.get(k) == v for k, v in incoming.identifiers.items())
        if (set(p.dedup_keys) & keys or (p.doi and p.doi == incoming.doi) or shared_id
                or normalize_title(p.title) == normalize_title(incoming.title)):
            p.dedup_keys = sorted(set(p.dedup_keys) | keys)
            for kind, value in incoming.identifiers.items():
                p.identifiers.setdefault(kind, value)
            p.doi = p.doi or incoming.doi
            p.fulltext_urls = list(dict.fromkeys(p.fulltext_urls + incoming.fulltext_urls))
            if not p.abstract:
                p.abstract = incoming.abstract
            return p.id
    active_count = sum(p.verdict != "exclude" for p in state.papers.values()) if state.require_target else len(state.papers)
    if active_count >= state.limits.candidates and not state.require_screening:
        return None
    incoming.dedup_keys = sorted(keys)
    state.papers[incoming.id] = incoming
    return incoming.id
