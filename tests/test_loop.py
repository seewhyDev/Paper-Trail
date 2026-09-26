import json

import pytest

from paper_agent.agent import Agent, answer_question
from paper_agent.demo import FixtureSources, ReplayProvider, SCENARIOS
from paper_agent.evaluation import grade
from paper_agent.provider import Call, ModelError, Turn


class Script:
    def __init__(self, turns):
        self.turns, self.inputs = iter(turns), []
    def respond(self, conversation, *args):
        self.inputs.append(list(conversation))
        return next(self.turns)


def call(cid, name, **kwargs):
    return Call(cid, name, json.dumps({"decision": "test decision", **kwargs}))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_controlled_scripted_scenarios_are_plumbing_only(state, store, scenario):
    state.scenario = scenario
    if scenario == "budget":
        state.limits.tool_calls = 2
    Agent(state, ReplayProvider(state), FixtureSources(state), store).run()
    assert grade(state)["pass"]
    requests = [e for e in state.events if e.kind == "tool_request"]
    results = [e for e in state.events if e.kind == "tool_result"]
    assert [e.call_id for e in requests] == [e.call_id for e in results]
    assert not state.usage.input_tokens  # no real model autonomy claim


def test_multiple_calls_observations_reach_followup(state, store):
    provider = Script([Turn([call("a", "set_criteria", goal="goal", criteria=["criterion"]),
                              call("b", "search_papers", source="arxiv", query="test", limit=3, offset=0)]),
                       Turn([call("c", "stop_incomplete", reason="observations received")])])
    Agent(state, provider, FixtureSources(state), store).run()
    observed = [i for i in provider.inputs[1] if i.get("type") == "function_call_output"]
    assert [i["call_id"] for i in observed] == ["a", "b"]
    assert len(json.loads(observed[1]["output"])["papers"]) == 3


def test_pause_preserves_all_call_results_and_resume(state, store):
    provider = Script([Turn([call("q", "ask_user", question="어느 언어를 연구하나요?"),
                              call("extra", "search_papers", source="arxiv", query="test", limit=3, offset=0)])])
    Agent(state, provider, FixtureSources(state), store).run()
    paused = store.load(state.id)
    assert paused.status == "waiting" and paused.usage.searches == 0
    outputs = [i for i in paused.conversation if i.get("type") == "function_call_output"]
    assert len(outputs) == 2
    answer_question(paused, "한국어")
    followup = Script([Turn([call("done", "stop_incomplete", reason="test pause completed")])])
    Agent(paused, followup, FixtureSources(paused), store).run()
    assert paused.answers == ["한국어"] and paused.usage.model_calls == 2
    assert any("한국어" in str(x) for x in followup.inputs[0])


def test_finish_rejection_is_observation_and_repair_possible(completed, store):
    state = completed.model_copy(deep=True)
    state.status, state.stop_reason, state.briefing = "ready", "", None
    broken = completed.briefing.model_dump()
    broken["papers"][0]["results"]["evidence_ids"] = ["fictional"]
    provider = Script([Turn([call("broken", "submit_briefing", briefing=broken)]),
                       Turn([call("repaired", "submit_briefing", briefing=completed.briefing.model_dump())])])
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "completed"
    observed = [i for i in provider.inputs[1] if i.get("call_id") == "broken" and i.get("type") == "function_call_output"]
    assert json.loads(observed[0]["output"])["error"] == "invalid_briefing"


def test_budget_preserves_outputs_for_unexecuted_calls(state, store):
    state.limits.tool_calls = 1
    provider = Script([Turn([call("a", "set_criteria", goal="goal", criteria=["x"]),
                              call("b", "search_papers", source="arxiv", query="test", limit=3, offset=0)])])
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "incomplete" and state.usage.tool_calls == 1
    assert state.usage.searches == 0
    assert [i["call_id"] for i in state.conversation if i.get("type") == "function_call_output"] == ["a", "b"]


@pytest.mark.parametrize("limit,reason", [("model_calls", "모델"), ("tokens", "토큰"), ("seconds", "시간")])
def test_budget_prevents_further_model_calls(state, store, limit, reason):
    if limit == "model_calls":
        state.limits.model_calls = 24
        state.usage.model_calls = state.limits.model_calls
    elif limit == "tokens":
        state.limits.tokens = 500
    else:
        state.usage.active_seconds = state.limits.seconds
    provider = Script([])
    Agent(state, provider, FixtureSources(state), store).run()
    assert not provider.inputs and state.status == "incomplete" and reason in state.stop_reason


def test_stop_and_failure_are_honest(state, store):
    Agent(state, Script([]), FixtureSources(state), store, lambda: True).run()
    assert state.status == "cancelled"


def test_no_tools_model_response_is_retried_under_budget(state, store):
    state.limits.model_calls = 1
    Agent(state, Script([Turn([])]), FixtureSources(state), store).run()
    assert state.status == "incomplete"


def test_failure_reserves_tokens_no_automatic_model_retry(state, store):
    class Failing:
        calls = 0
        def respond(self, *args):
            self.calls += 1
            raise ModelError("model unavailable")
    provider = Failing()
    Agent(state, provider, FixtureSources(state), store).run()
    assert state.status == "error" and provider.calls == 1 and state.usage.charged_tokens > 0


def test_terminal_run_is_not_reexecuted(completed, store):
    provider = Script([])
    before = completed.usage.model_dump()
    Agent(completed, provider, FixtureSources(completed), store).run()
    assert not provider.inputs and completed.usage.model_dump() == before
