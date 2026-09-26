import copy
import json
from pathlib import Path

import pytest

from paper_agent.activity import activity_view
from paper_agent.agent import Agent, state_view
from paper_agent.completion import prepare_resume, repair_structure
from paper_agent.demo import FixtureSources, ReplayProvider
from paper_agent.history import STATE_PREFIX, model_input
from paper_agent.provider import Call, Turn
from paper_agent.tools import ToolExecutor, definitions, validate_briefing, validate_call


def test_three_paper_policy_rejects_partial_and_early_stop(completed):
    completed.require_target = True
    partial = completed.briefing.model_copy(deep=True)
    partial.papers.pop()
    partial.reading_order.pop()
    assert any('정확히 3편' in e for e in validate_briefing(completed, partial))
    completed.briefing, completed.status = None, 'running'
    ex = ToolExecutor(completed, FixtureSources(completed))
    for tool, extra in [('stop_incomplete', {'reason': '질문이 너무 넓음'}), ('ask_user', {'question': '범위를 좁혀 주세요'})]:
        result = ex.execute(tool, validate_call(tool, json.dumps({'decision': 'test', **extra})))
        assert result['error'] == 'continue_to_target'
        assert completed.status == 'running'
    allowed = {d['name'] for d in definitions(completed)}
    assert 'submit_briefing' in allowed
    assert not allowed & {'ask_user', 'stop_incomplete', 'search_papers', 'get_metadata'}


def test_early_stop_is_observation_then_three_papers_complete(state, store):
    state.require_target = True
    replay = ReplayProvider(state)
    class Provider:
        turns = 0
        def respond(self, *args):
            self.turns += 1
            if self.turns == 1:
                return Turn([Call('early', 'stop_incomplete', json.dumps({'decision': 'broad question', 'reason': '범위가 넓음'}))])
            return replay.respond(*args)
    Agent(state, Provider(), FixtureSources(state), store).run()
    assert state.status == 'completed' and len(state.briefing.papers) == 3
    assert any(e.result and e.result.get('error') == 'continue_to_target' for e in state.events)


def test_structural_repair_never_attaches_invented_support(completed):
    completed.require_target = True
    original = completed.briefing.model_copy(deep=True)
    broken = original.model_copy(deep=True)
    broken.reading_order = ['wrong name', 'other title', 'alias']
    unsupported = broken.comparison[0].model_copy(deep=True)
    unsupported.evidence_ids = broken.papers[0].method.evidence_ids
    broken.comparison.append(unsupported)
    repaired, changes = repair_structure(completed, broken)
    assert changes and not validate_briefing(completed, repaired)
    assert repaired.comparison == original.comparison
    assert repaired.reading_order == [p.paper_id for p in original.papers]
    assert repaired.papers == original.papers
    broken.papers[0].results.evidence_ids = ['invented']
    still_broken, changes = repair_structure(completed, broken)
    assert validate_briefing(completed, still_broken) and not changes
    only_bad = original.model_copy(deep=True)
    only_bad.comparison = [unsupported]
    assert not repair_structure(completed, only_bad)[1]


def test_compact_finalization_retains_complete_latest_round_and_source_state(completed):
    completed.require_target = True
    before = copy.deepcopy(completed.conversation)
    snapshot = {'role': 'user', 'content': STATE_PREFIX + json.dumps(state_view(completed))}
    full = model_input(completed, snapshot)
    compact = model_input(completed, snapshot, recent_turns=1)
    assert len(json.dumps(compact)) < len(json.dumps(full))
    inputs = [i['call_id'] for i in compact if i.get('type') == 'function_call']
    outputs = [i['call_id'] for i in compact if i.get('type') == 'function_call_output']
    assert inputs == outputs
    assert compact[-1] == snapshot and completed.conversation == before
    last = next(i for i in reversed(before) if i.get('type') == 'function_call_output')
    assert last in compact
    assert all(e.id in snapshot['content'] for e in completed.evidence.values())


def test_resume_preserves_spending_and_source_work(completed):
    completed.briefing, completed.status = None, 'incomplete'
    before = completed.usage.model_dump()
    papers = copy.deepcopy(completed.papers)
    prepare_resume(completed)
    assert completed.status == 'ready' and completed.require_target
    assert completed.usage.model_dump() == before and completed.papers == papers
    completed.status = 'incomplete'
    completed.limits.finalization_calls = 4
    completed.usage.finalization_calls = completed.limits.finalization_calls
    with pytest.raises(ValueError):
        prepare_resume(completed)


def test_finalization_has_reserved_calls_after_research_cap(completed, store):
    completed.limits.model_calls = 24
    completed.limits.finalization_calls = 4
    completed.require_target = True
    completed.status, completed.briefing = 'ready', None
    completed.usage.model_calls = completed.limits.model_calls
    Agent(completed, ReplayProvider(completed), FixtureSources(completed), store).run()
    assert completed.status == 'completed' and len(completed.briefing.papers) == 3
    assert completed.usage.model_calls == completed.limits.model_calls + 1
    assert completed.usage.finalization_calls == 1


def test_finalization_reserve_is_bounded(completed, store):
    completed.limits.model_calls = 24
    completed.limits.finalization_calls = 4
    completed.require_target = True
    completed.status, completed.briefing = 'ready', None
    completed.usage.model_calls = completed.limits.model_calls
    completed.usage.finalization_calls = completed.limits.finalization_calls
    class NeverCall:
        def respond(self, *args):
            pytest.fail('finalization limit exceeded')
    Agent(completed, NeverCall(), FixtureSources(completed), store).run()
    assert completed.status == 'incomplete' and '최종 브리핑' in completed.stop_reason


def test_excluded_candidates_leave_room_for_replacements(state):
    from paper_agent.schema import add_paper
    from paper_agent.demo import fixture_paper
    state.require_target, state.limits.candidates = True, 1
    old = fixture_paper(1)
    add_paper(state, old)
    assert add_paper(state, fixture_paper(2)) is None
    old.verdict = 'exclude'
    assert add_paper(state, fixture_paper(2)) == 'fixture_2'
    assert old.id in state.papers  # the audit record is kept


def test_arxiv_unquoted_phrase_is_rejected_before_network():
    from paper_agent.network import SourceError
    args = {'decision':'test', 'source':'arxiv','query':'ti:SSM OR ti:state space model OR ti:Mamba', 'limit':3, 'offset':0}
    with pytest.raises(SourceError, match='arxiv_query_syntax'):
        validate_call('search_papers',json.dumps(args))
    args['query'] = 'ti:SSM OR ti:"state space model" OR ti:Mamba'
    assert validate_call('search_papers',json.dumps(args)).query == args['query']


def test_live_activity_shows_actual_tool_site_query_and_completion(state):
    state.status = 'running'
    state.event('tool_request', 'test', call_id='a', name='search_papers',
                arguments={'source':'arxiv','query':'all:"linear attention"','limit':5})
    state.event('network_request', 'test', call_id='a', arguments={'url':'https://export.arxiv.org/api/query'})
    current, recent = activity_view(state)
    assert current['tool'] == 'search_papers' and current['site'] == 'arXiv'
    assert current['query'] == 'all:"linear attention"' and current['status'] == '진행 중'
    assert current['url'] == 'https://export.arxiv.org/api/query' and not recent
    state.event('tool_result','done',call_id='a',name='search_papers',result={'papers':[]})
    state.event('model_request','next decision')
    current, recent = activity_view(state)
    assert current['tool'] == '' and recent[0]['status'] == '완료'


def test_live_activity_names_paper_route_and_sections(completed):
    completed.status = 'running'
    paper = next(iter(completed.papers.values()))
    completed.event('tool_request','read',call_id='live-read',name='read_chunks',
                    arguments={'paper_id':paper.id,'chunk_ids':paper.read_chunks[:2]})
    current, _ = activity_view(completed)
    assert current['detail'] == paper.title
    assert current['sections'] == [paper.chunks[c].location for c in paper.read_chunks[:2]]


def test_progress_ui_renders_specific_activity_without_spending(state, store, monkeypatch):
    from streamlit.testing.v1 import AppTest
    state.status = 'running'
    state.event('tool_request','test',call_id='a',name='search_papers',
                arguments={'source':'arxiv','query':'all:"linear attention"','limit':5})
    state.event('network_request','test',call_id='a',arguments={'url':'https://export.arxiv.org/api/query'})
    store.save(state)
    monkeypatch.setenv('PAPER_AGENT_DATA', str(store.root))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=15).run()
    assert not app.exception
    visible = ' '.join(str(x.value) for kind in ('caption','markdown','text','subheader') for x in app.get(kind))
    for text in ('search_papers','arXiv','linear attention','export.arxiv.org'):
        assert text in visible
    assert state.id not in visible and 'API 보고' not in visible
    assert any('role="status"' in item.value and 'agent-wheel' in item.value for item in app.markdown)
    assert store.load(state.id).usage.model_calls == 0
