import json
from pathlib import Path

import pytest

from paper_agent.agent import Agent, state_view
from paper_agent.completion import prepare_resume, resume_problem
from paper_agent.config import default_limits
from paper_agent.demo import FixtureSources, ReplayProvider
from paper_agent.progress import initialize_progress, record_progress
from paper_agent.provider import Call, Turn


def tool(cid, name, **kwargs):
    return Call(cid, name, json.dumps({"decision": "synthetic regression test", **kwargs}))


def test_four_papers_can_complete_after_old_call_cap(state, store, tmp_path):
    from paper_agent.pdf import render_pdf
    state.require_target = state.require_screening = True
    state.limits.target = 4
    state.usage.model_calls = 24
    Agent(state, ReplayProvider(state), FixtureSources(state), store).run()
    assert state.status == "completed"
    assert state.usage.model_calls > 24
    assert len(state.briefing.papers) == 4
    assert render_pdf(state, tmp_path / "four.pdf").is_file()


def test_over_24_distinct_reading_turns_continue_to_valid_briefing(completed, store):
    state = completed
    brief = state.briefing.model_dump()
    state.briefing, state.status = None, "ready"
    paper = next(iter(state.papers.values()))
    template = next(iter(paper.chunks.values()))
    for i in range(30):
        cid = f"extra{i}"
        paper.chunks[cid] = template.model_copy(update={"id": cid, "text": f"Extra source passage {i}."})

    class Reader:
        calls = 0

        def respond(self, *args):
            i = self.calls
            self.calls += 1
            request = (tool(str(i), "read_chunks", paper_id=paper.id, chunk_ids=[f"extra{i}"])
                       if i < 30 else tool("finish", "submit_briefing", briefing=brief))
            return Turn([request])

    provider = Reader()
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "completed" and provider.calls == 31
    assert state.stalled_turns == 0


@pytest.mark.parametrize("empty", [True, False])
def test_no_progress_stops_and_recovery_reaches_model(state, store, empty):
    class Stuck:
        inputs = []

        def respond(self, conversation, *args):
            self.inputs.append(conversation)
            return Turn([] if empty else [tool(str(len(self.inputs)), "unknown_tool")])

    provider = Stuck()
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "incomplete" and "반복" in state.stop_reason
    assert len(provider.inputs) == state.limits.stalled_turns
    assert any("progress_recovery" == e.kind for e in state.events)
    assert "최근 호출에서" in provider.inputs[3][-1]["content"]
    persisted = store.load(state.id)
    before = len(provider.inputs)
    persisted.status = "ready"  # restarting a process must not bypass the guard
    Agent(persisted, provider, FixtureSources(persisted), store).run()
    assert len(provider.inputs) == before


def test_repeated_reading_and_renamed_evidence_do_not_count_as_progress(completed):
    completed.status, completed.briefing = "running", None
    initialize_progress(completed)
    existing = next(iter(completed.evidence.values()))
    completed.evidence["another_id"] = existing.model_copy(update={"id": "another_id", "claim": "Rephrased"})
    record_progress(completed)
    assert completed.stalled_turns == 1
    paper = next(iter(completed.papers.values()))
    paper.read_chunks.append(paper.read_chunks[0])
    record_progress(completed)
    assert completed.stalled_turns == 2
    paper.read_chunks.append("new_location")
    record_progress(completed)
    assert completed.stalled_turns == 0


def test_old_resume_adopts_auto_without_resetting_usage_or_work(completed, monkeypatch):
    monkeypatch.setenv("MAX_MODEL_CALLS", "auto")
    monkeypatch.setenv("MAX_FINALIZATION_CALLS", "auto")
    completed.status, completed.briefing = "incomplete", None
    completed.limits.model_calls, completed.limits.finalization_calls = 24, 4
    completed.usage.model_calls, completed.usage.finalization_calls = 24, 4
    completed.stalled_turns = 6
    before = completed.model_copy(deep=True)
    assert resume_problem(completed)
    assert resume_problem(completed, refresh_call_policy=True) is None
    assert completed == before  # rendering the button does not mutate the run
    prepare_resume(completed, refresh_call_policy=True)
    assert completed.limits.model_calls is completed.limits.finalization_calls is None
    assert completed.status == "ready" and completed.stalled_turns == 0
    assert completed.usage == before.usage and completed.papers == before.papers
    assert completed.evidence == before.evidence and completed.paper_briefs == before.paper_briefs


@pytest.mark.parametrize("limit", ["tokens", "seconds", "tool_calls"])
def test_auto_resume_preserves_other_exhausted_limits(state, monkeypatch, limit):
    monkeypatch.setenv("MAX_MODEL_CALLS", "auto")
    monkeypatch.setenv("MAX_FINALIZATION_CALLS", "auto")
    state.status = "incomplete"
    if limit == "tokens":
        state.limits.tokens = 500000
        monkeypatch.setenv("MAX_TOKENS", "500000")
    usage_field = {"tokens": "charged_tokens", "seconds": "active_seconds", "tool_calls": "tool_calls"}[limit]
    setattr(state.usage, usage_field, getattr(state.limits, limit))
    before = state.model_copy(deep=True)
    with pytest.raises(ValueError, match="실행 한도"):
        prepare_resume(state, refresh_call_policy=True)
    assert state == before


def test_call_config_defaults_auto_and_supports_operator_limits(monkeypatch, state):
    for name in ("MAX_MODEL_CALLS", "MAX_FINALIZATION_CALLS"):
        monkeypatch.delenv(name, raising=False)
    assert default_limits().model_calls is None
    assert default_limits().finalization_calls is None
    assert state_view(state)["remaining"]["model_calls"] == "until_complete"
    monkeypatch.setenv("MAX_MODEL_CALLS", "40")
    monkeypatch.setenv("MAX_FINALIZATION_CALLS", "5")
    assert default_limits().model_calls == 40 and default_limits().finalization_calls == 5


@pytest.mark.parametrize("exhausted", [False, True])
def test_ui_only_offers_resumable_work(state, store, monkeypatch, exhausted):
    from streamlit.testing.v1 import AppTest
    state.status, state.mode = "incomplete", "live"
    state.limits.target = 4
    state.limits.model_calls = state.usage.model_calls = 24
    state.limits.tokens = 500000
    monkeypatch.setenv("MAX_TOKENS", "500000")
    if exhausted:
        state.usage.charged_tokens = state.limits.tokens
    store.save(state)
    monkeypatch.setenv("PAPER_AGENT_DATA", str(store.root))
    monkeypatch.setenv("MAX_MODEL_CALLS", "auto")
    monkeypatch.setenv("MAX_FINALIZATION_CALLS", "auto")
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=15).run()
    assert not app.exception
    assert any(b.label == "4편 브리핑 완성하기" for b in app.button) == (not exhausted)
    assert store.load(state.id) == state
