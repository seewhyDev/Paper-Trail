import pytest

from paper_agent.agent import Agent
from paper_agent.demo import DEMO_QUESTION, FixtureSources, ReplayProvider
from paper_agent.schema import Context, RunState
from paper_agent.store import Store


@pytest.fixture
def state():
    return RunState(mode="demo", context=Context(question=DEMO_QUESTION), model="scripted-test")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "runs")


@pytest.fixture
def completed(state, store):
    Agent(state, ReplayProvider(state), FixtureSources(state), store).run()
    assert state.status == "completed"
    return state
