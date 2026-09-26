from pathlib import Path

import pytest

from paper_agent.agent import Agent, prepare_model_request, state_view
from paper_agent.completion import prepare_resume, resume_problem
from paper_agent.config import default_limits
from paper_agent.demo import FixtureSources, ReplayProvider
from paper_agent.provider import ModelError
from paper_agent.schema import Limits, RunState


def test_auto_completes_four_papers_past_cumulative_budget(state, store):
    state.require_target = state.require_screening = True
    state.limits.target = 4
    state.usage.charged_tokens = state.usage.input_tokens = 407585
    replay = ReplayProvider(state)

    class Metered:
        calls = 0

        def respond(self, conversation, tools, output, timeout):
            self.calls += 1
            assert output == state.limits.output_tokens
            checkpoint = store.load(state.id)
            assert checkpoint.usage.model_calls == self.calls
            assert checkpoint.usage.charged_tokens > 407585 + (self.calls - 1) * 80100
            turn = replay.respond(conversation, tools, output, timeout)
            turn.input_tokens, turn.output_tokens = 80000, 100
            return turn

    provider = Metered()
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "completed" and len(state.briefing.papers) == 4
    assert state.usage.charged_tokens == 407585 + provider.calls * 80100
    assert state.usage.charged_tokens > 1000000
    assert state.usage.input_tokens == 407585 + provider.calls * 80000
    assert state.usage.output_tokens == provider.calls * 100
    assert store.load(state.id).limits.tokens is None


def test_auto_failure_keeps_unknown_usage_reservation(state, store):
    state.usage.charged_tokens = 900000

    class Failure:
        calls = 0

        def respond(self, *args):
            self.calls += 1
            self.reserved = store.load(state.id).usage.charged_tokens
            raise ModelError("synthetic network failure")

    provider = Failure()
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "error" and provider.calls == 1
    assert state.usage.charged_tokens == provider.reserved
    assert provider.reserved > 900000 + state.limits.output_tokens
    assert state.usage.input_tokens == state.usage.output_tokens == 0


def test_fixed_admission_and_resume_use_same_request_estimate(state, store):
    state.require_target = True
    state.limits.tokens = 500000
    # Some budget is left, but not enough even for input + 256 output tokens.
    state.usage.charged_tokens = 499000
    state.status = "incomplete"
    before = state.model_copy(deep=True)
    assert "다음 요청" in resume_problem(state)
    assert state == before
    with pytest.raises(ValueError, match="다음 요청"):
        prepare_resume(state)
    assert state == before

    class NeverCall:
        def respond(self, *args):
            pytest.fail("fixed admission must block before API call")

    state.status = "ready"
    Agent(state, NeverCall(), FixtureSources(state), store).run()
    assert state.status == "incomplete" and "예약량" in state.stop_reason
    assert state.usage.charged_tokens == 499000 and state.usage.model_calls == 0


@pytest.mark.parametrize("setting", ["auto", "1500000"])
def test_existing_run_adopts_current_token_policy_without_losing_work(completed, monkeypatch, setting):
    completed.paper_briefs = {p.paper_id: p for p in completed.briefing.papers}
    completed.briefing, completed.status = None, "incomplete"
    completed.limits.tokens = 500000
    completed.usage.charged_tokens = 500000
    before = completed.model_copy(deep=True)
    monkeypatch.setenv("MAX_TOKENS", setting)
    monkeypatch.setenv("MAX_MODEL_CALLS", "auto")
    monkeypatch.setenv("MAX_FINALIZATION_CALLS", "auto")
    assert resume_problem(completed)
    assert resume_problem(completed, refresh_call_policy=True) is None
    assert completed == before
    prepare_resume(completed, refresh_call_policy=True)
    assert completed.status == "ready"
    assert completed.limits.tokens == (None if setting == "auto" else int(setting))
    assert completed.usage == before.usage
    assert completed.papers == before.papers and completed.evidence == before.evidence
    assert completed.paper_briefs == before.paper_briefs
    assert RunState.model_validate_json(completed.model_dump_json()).limits.tokens == completed.limits.tokens


def test_token_config_auto_and_optional_numeric_cap(monkeypatch, state):
    monkeypatch.delenv("MAX_TOKENS", raising=False)
    assert default_limits().tokens is None
    monkeypatch.setenv("MAX_TOKENS", "auto")
    assert default_limits().tokens is None
    assert state_view(state)["remaining"]["tokens"] == "until_complete"
    monkeypatch.setenv("MAX_TOKENS", "2000000")
    assert default_limits().tokens == 2000000
    assert Limits.model_validate({"tokens": 500000}).tokens == 500000
    with pytest.raises(ValueError):
        Limits(tokens=0)


@pytest.mark.parametrize("setting,offered", [("500000", False), ("auto", True)])
def test_ui_checks_admission_with_effective_token_policy(state, store, monkeypatch, setting, offered):
    from streamlit.testing.v1 import AppTest
    state.mode, state.status = "live", "incomplete"
    state.limits.tokens = 500000
    state.usage.charged_tokens = 499000
    store.save(state)
    monkeypatch.setenv("PAPER_AGENT_DATA", str(store.root))
    monkeypatch.setenv("MAX_TOKENS", setting)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=15).run()
    assert not app.exception
    assert any(b.label == "3편 브리핑 완성하기" for b in app.button) == offered
    assert store.load(state.id) == state
