import json

import pytest

from paper_agent.demo import FixtureSources, fixture_paper
from paper_agent.network import SourceError
from paper_agent.schema import add_paper
from paper_agent.tools import ToolExecutor, definitions, validate_briefing, validate_call


def test_dedup_doi_ids_title_and_cap(state):
    state.limits.candidates = 1
    p = fixture_paper(1)
    p.doi = "https://doi.org/10.1234/ABC"
    first = add_paper(state, p)
    duplicate = fixture_paper(2)
    duplicate.doi = "doi:10.1234/abc"
    duplicate.identifiers["pmcid"] = "PMC123"
    assert add_paper(state, duplicate) == first
    assert state.papers[first].identifiers["pmcid"] == "PMC123"
    duplicate = fixture_paper(3)
    duplicate.title = " "+p.title.upper()+". "
    assert add_paper(state, duplicate) == first
    assert add_paper(state, fixture_paper(2)) == first  # merged shared ID survives
    other = fixture_paper(3)
    other.title = "A wholly different title"
    other.identifiers = {"fixture": "unseen"}
    assert add_paper(state, other) is None
    assert len(state.papers) == 1


@pytest.mark.parametrize("name,args", [
    ("exec", {}), ("search_papers", {"query": "x"}),
    ("fetch_fulltext", {"paper_id": "x", "route": "url", "decision": "test"}),
    ("ask_user", {"question": "test", "decision": "test", "shell": "whoami"}),
    ("search_papers", {"query": "test", "source": "arxiv", "limit": "3", "offset": 0, "decision": "test"}),
])
def test_argument_validation(name, args):
    with pytest.raises(SourceError):
        validate_call(name, json.dumps(args))


def test_every_object_schema_is_strict():
    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(value.get("properties", {}))
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    for definition in definitions():
        walk(definition["parameters"])


def test_evidence_references_quote_and_review_required(completed):
    s = completed
    assert validate_briefing(s, s.briefing) == []
    bad = s.briefing.model_copy(deep=True)
    bad.papers[0].results.evidence_ids = ["invented"]
    assert validate_briefing(s, bad)
    note = next(iter(s.evidence.values()))
    note.quote = "not in source"
    assert validate_briefing(s, s.briefing)


def test_fulltext_acquired_is_not_reviewed(completed):
    p = completed.papers[completed.briefing.papers[0].paper_id]
    p.read_chunks.clear()
    assert validate_briefing(completed, completed.briefing)


def test_cross_paper_evidence_rejected(completed):
    first, second = completed.briefing.papers[:2]
    first.results.evidence_ids = second.results.evidence_ids
    assert validate_briefing(completed, completed.briefing)


def test_invalid_note_does_not_mutate(state):
    p = fixture_paper(1)
    state.papers[p.id] = p
    args = validate_call("assess_candidate", json.dumps({"paper_id": p.id, "verdict": "keep", "relevance": 5,
            "reason": "test", "decision": "test", "notes": [{"chunk_id": "c001", "quote": "invented quote",
            "claim": "test claim", "kind": "paper_claim"}]}))
    with pytest.raises(SourceError):
        ToolExecutor(state, FixtureSources(state)).execute("assess_candidate", args)
    assert not state.evidence and p.verdict == "unassessed"


def test_state_roundtrip_and_no_calls_on_read(completed, store):
    before = completed.model_dump()
    loaded = store.load(completed.id)
    assert loaded.model_dump() == before
    assert store.load(completed.id).usage.tool_calls == completed.usage.tool_calls
    assert "conversation" not in json.loads(store.trace(loaded))


def test_path_traversal_rejected(store):
    with pytest.raises(ValueError):
        store.load("../../.env")


def test_search_cache_does_not_call_source_twice(state):
    class Counting(FixtureSources):
        count = 0
        def search(self, *args):
            self.count += 1
            return super().search(*args)
    source = Counting(state)
    ex = ToolExecutor(state, source)
    a = validate_call("search_papers", json.dumps({"source": "arxiv", "query": "test", "limit": 3, "offset": 0, "decision": "test"}))
    ex.execute("search_papers", a)
    result = ex.execute("search_papers", a)
    assert result["cached"] and source.count == 1 and state.usage.searches == 1


def test_failed_fulltext_counts_towards_distinct_cap(state):
    state.scenario = "fulltext_failure"
    state.limits.fulltexts = 1
    for i in (1, 2):
        p = fixture_paper(i)
        state.papers[p.id] = p
    ex = ToolExecutor(state, FixtureSources(state))
    def fetch(pid, route):
        return ex.execute("fetch_fulltext", validate_call("fetch_fulltext", json.dumps({"paper_id": pid, "route": route, "decision": "test"})))
    with pytest.raises(SourceError):
        fetch("fixture_1", "auto")
    with pytest.raises(SourceError, match="fulltext_budget"):
        fetch("fixture_2", "auto")
    assert fetch("fixture_1", "pdf")["status"] == "available"
    assert state.usage.fulltext_attempts == ["fixture_1"]
