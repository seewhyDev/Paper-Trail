import copy
import json
from pathlib import Path

import pytest

from paper_agent.agent import Agent
from paper_agent.completion import ready_to_finalize
from paper_agent.demo import FixtureSources, ReplayProvider, fixture_paper
from paper_agent.history import STATE_PREFIX, model_input
from paper_agent.network import SourceError
from paper_agent.schema import add_paper
from paper_agent.screening import has_read, screened, pending, comparison_current, screening_errors, quote_passages
from paper_agent.tools import ToolExecutor, validate_call, validate_briefing, definitions


def execute(ex, name, **kw):
    return ex.execute(name, validate_call(name,json.dumps({'decision':'test',**kw})))


def configure(s):
    s.require_screening = True
    s.goal, s.criteria = 'research goal', ['relevance', 'method and conditions']
    return ToolExecutor(s, FixtureSources(s))


def review(p, decision='fulltext'):
    return dict(paper_id=p.id,relevance=4,method_fit=3,evidence_potential=4,decision=decision,
                reason='공통 연구 조건에 맞는 접근으로 다른 후보와 비교할 가치가 있습니다.',
                quote_id=quote_passages(p)[0]['id'],limitation='' if p.abstract else '초록 미확보: 제목만으로 평가해 세부 방법은 미확인입니다.')


def screen_all(s, ex):
    for start in range(0,len(s.papers),5):
        papers=list(s.papers.values())[start:start+5]
        execute(ex,'read_candidates',paper_ids=[p.id for p in papers])
        s.usage.model_calls += 1
        execute(ex,'screen_candidates',reviews=[review(p) for p in papers])


def compare_all(s, ex):
    execute(ex,'compare_candidates',ranked_paper_ids=list(s.papers),shortlist=list(s.papers)[:3],
            summary='같은 연구 과제를 다루며 방법과 실험 조건의 차이를 기준으로 원문 검토 우선순위를 정했습니다.')


def test_all_candidates_must_be_read_evaluated_and_compared_before_submission(completed):
    s=completed
    ex=configure(s)
    extra=fixture_paper(1).model_copy(deep=True)
    extra.id,extra.title,extra.identifiers='extra','Additional distinct candidate',{'extra':'1'}
    add_paper(s,extra)
    assert validate_briefing(s,s.briefing)
    assert not ready_to_finalize(s)
    screen_all(s,ex)
    assert all(screened(s,p) for p in s.papers.values())
    assert validate_briefing(s,s.briefing) # all individual reviews alone are insufficient
    compare_all(s,ex)
    assert not validate_briefing(s,s.briefing)
    assert ready_to_finalize(s)


def test_search_card_or_same_turn_read_does_not_count_as_evaluation(state):
    ex=configure(state)
    execute(ex,'search_papers',source='arxiv',query='ti:test',limit=3,offset=0)
    p=next(iter(state.papers.values()))
    with pytest.raises(SourceError,match='screening_read_required'):
        execute(ex,'screen_candidates',reviews=[review(p)])
    execute(ex,'read_candidates',paper_ids=[p.id])
    with pytest.raises(SourceError,match='screening_observation_required'):
        execute(ex,'screen_candidates',reviews=[review(p)])
    state.usage.model_calls += 1
    execute(ex,'screen_candidates',reviews=[review(p)])
    assert screened(state,p)


def test_long_abstract_requires_every_range(state):
    ex=configure(state)
    p=fixture_paper(1);p.abstract='Evidence sentence. '*700
    add_paper(state,p)
    execute(ex,'read_candidates',paper_ids=[p.id])
    state.usage.model_calls+=1
    with pytest.raises(SourceError,match='screening_read_required'):
        execute(ex,'screen_candidates',reviews=[review(p)])
    execute(ex,'get_metadata',paper_id=p.id,abstract_offset=10000)
    assert not has_read(p) # a hole must not be mistaken for full coverage
    execute(ex,'get_metadata',paper_id=p.id,abstract_offset=5000)
    state.usage.model_calls+=1
    execute(ex,'screen_candidates',reviews=[review(p)])
    assert screened(state,p)


def test_missing_abstract_records_honest_limited_assessment(state):
    ex=configure(state)
    p=fixture_paper(1);p.abstract=''
    add_paper(state,p)
    class Broken(FixtureSources):
        def details(self,p): raise SourceError('unavailable')
    ex.sources=Broken(state)
    result=execute(ex,'read_candidates',paper_ids=[p.id])
    assert result['candidates'][0]['basis']=='title_only'
    state.usage.model_calls+=1
    with pytest.raises(SourceError,match='missing_abstract'):
        execute(ex,'screen_candidates',reviews=[review(p)])
    execute(ex,'screen_candidates',reviews=[review(p,'reference')])
    assert screened(state,p) and p.screening.basis=='title_only' and p.screening.limitation
    assert not p.read_chunks


def test_bad_quote_batch_is_atomic(state):
    ex=configure(state)
    for i in (1,2): add_paper(state,fixture_paper(i))
    execute(ex,'read_candidates',paper_ids=list(state.papers))
    state.usage.model_calls+=1
    reviews=[review(p) for p in state.papers.values()]
    reviews[-1]['quote_id']='fabricated abstract evidence'
    with pytest.raises(SourceError,match='screening_quote'):
        execute(ex,'screen_candidates',reviews=reviews)
    assert all(p.screening is None for p in state.papers.values())


def test_quote_locator_is_bound_to_the_paper_and_source_version(state):
    ex = configure(state)
    p, q = fixture_paper(1), fixture_paper(2)
    add_paper(state, p); add_paper(state, q)
    execute(ex, 'read_candidates', paper_ids=[p.id, q.id])
    state.usage.model_calls += 1
    r = review(p)
    execute(ex, 'screen_candidates', reviews=[r])
    assert p.screening.quote == quote_passages(p)[0]['text'] and screened(state, p)
    r['quote_id'] = quote_passages(q)[0]['id']
    with pytest.raises(SourceError, match='screening_quote'):
        execute(ex, 'screen_candidates', reviews=[r])
    r = review(p)
    p.abstract += ' Newly updated source.'
    execute(ex, 'read_candidates', paper_ids=[p.id])
    state.usage.model_calls += 1
    with pytest.raises(SourceError, match='screening_quote'):
        execute(ex, 'screen_candidates', reviews=[r])


@pytest.mark.parametrize('mutation',['new_candidate','criteria','source','review'])
def test_changed_candidates_or_criteria_invalidate_comparison(state,mutation):
    ex=configure(state)
    for i in (1,2,3): add_paper(state,fixture_paper(i))
    screen_all(state,ex); compare_all(state,ex)
    assert comparison_current(state)
    p=next(iter(state.papers.values()))
    if mutation=='new_candidate':
        q=fixture_paper(1);q.id,q.title,q.identifiers='new','new unique candidate',{'new':'id'};add_paper(state,q)
    elif mutation=='criteria': state.criteria.append('another condition')
    elif mutation=='source': p.abstract += ' New source information.'
    else: p.screening.reason='Different priority after comparing candidates.'
    assert not comparison_current(state) and screening_errors(state)


def test_ranking_requires_all_ids_and_shortlist_inclusion(completed):
    ex=configure(completed);screen_all(completed,ex)
    with pytest.raises(SourceError,match='ranking_coverage'):
        execute(ex,'compare_candidates',ranked_paper_ids=list(completed.papers)[:2],shortlist=[],summary='comparison')
    execute(ex,'compare_candidates',ranked_paper_ids=list(completed.papers),shortlist=list(completed.papers)[:2],summary='comparison')
    assert any('candidate_shortlist' in e for e in validate_briefing(completed,completed.briefing))


def test_ranking_schema_and_error_identify_missing_and_mistyped_ids(state):
    ex = configure(state)
    for i in (1, 2, 3): add_paper(state, fixture_paper(i))
    screen_all(state, ex)
    schema = next(d['parameters'] for d in definitions(state) if d['name'] == 'compare_candidates')
    ranking = schema['properties']['ranked_paper_ids']
    assert ranking['minItems'] == ranking['maxItems'] == 3
    assert set(ranking['items']['enum']) == set(state.papers)
    ids = list(state.papers)
    with pytest.raises(SourceError) as caught:
        execute(ex, 'compare_candidates', ranked_paper_ids=ids[:2] + ['typo'], shortlist=[], summary='comparison')
    assert ids[2] in str(caught.value) and 'typo' in str(caught.value)


def test_screening_tools_offer_only_read_pending_candidates(state):
    ex = configure(state)
    p, q = fixture_paper(1), fixture_paper(2)
    add_paper(state, p); add_paper(state, q)
    execute(ex, 'read_candidates', paper_ids=[p.id])
    tool = next(d for d in definitions(state) if d['name'] == 'screen_candidates')
    fields = tool['parameters']['$defs']['ScreenItem']['properties']
    assert fields['paper_id']['enum'] == [p.id]
    assert fields['quote_id']['enum'] == [r['id'] for r in quote_passages(p)]


def test_three_reviewed_papers_cannot_skip_unreviewed_candidates(completed):
    configure(completed)
    allowed={d['name'] for d in definitions(completed)}
    assert 'read_candidates' in allowed
    assert 'screen_candidates' not in allowed
    assert not {'submit_briefing','fetch_fulltext','search_papers'} & allowed
    ex=ToolExecutor(completed,FixtureSources(completed))
    with pytest.raises(SourceError,match='candidate_screening'):
        execute(ex,'fetch_fulltext',paper_id=next(iter(completed.papers)),route='auto')


def test_screening_phase_prevents_criteria_churn_and_requires_observation_first(state):
    ex = configure(state)
    add_paper(state, fixture_paper(1))
    original = list(state.criteria)
    with pytest.raises(SourceError, match='criteria_locked'):
        execute(ex, 'set_criteria', goal='another goal', criteria=['another criterion'])
    assert state.criteria == original
    execute(ex, 'read_candidates', paper_ids=list(state.papers))
    assert {d['name'] for d in definitions(state)} == {'screen_candidates'}
    state.usage.model_calls += 1
    execute(ex, 'screen_candidates', reviews=[review(p) for p in state.papers.values()])
    assert {d['name'] for d in definitions(state)} == {'compare_candidates'}
    compare_all(state, ex)
    execute(ex, 'set_criteria', goal='another goal', criteria=['another criterion'])
    assert not comparison_current(state) and pending(state) == list(state.papers)


def test_search_caps_request_not_silently_discarding_returned_candidates(state):
    ex=configure(state);state.limits.candidates=2
    class Extra(FixtureSources):
        requested=None
        def search(self,source,query,limit,offset=0):
            self.requested=limit
            return [fixture_paper(i) for i in (1,2,3)] # faulty source returns too many
    ex.sources=Extra(state)
    result=execute(ex,'search_papers',source='arxiv',query='ti:test',limit=15,offset=0)
    assert ex.sources.requested==2 and len(state.papers)==3 and len(result['papers'])==3
    assert len(pending(state))==3


def test_unassessed_abstract_observation_survives_history_window(state):
    configure(state)
    p=fixture_paper(1);add_paper(state,p)
    call={'type':'function_call','call_id':'read','name':'read_candidates','arguments':'{}'}
    result={'type':'function_call_output','call_id':'read','output':json.dumps({'candidates':[{'paper_id':p.id,'abstract':p.abstract}]})}
    state.conversation=[{'role':'user','content':STATE_PREFIX+'old'},call,result,
                        {'role':'user','content':STATE_PREFIX+'new'},
                        {'type':'function_call','call_id':'other','name':'set_criteria','arguments':'{}'},
                        {'type':'function_call_output','call_id':'other','output':'{}'}]
    assert result in model_input(state,{'role':'user','content':STATE_PREFIX+'now'},recent_turns=1)


def test_worker_screening_pipeline_and_roundtrip(state,store):
    from paper_agent.worker import launch
    state.require_screening=state.require_target=True
    store.save(state);launch(store,state.id,wait=True)
    s=store.load(state.id)
    assert s.status=='completed' and len(s.briefing.papers)==3
    assert comparison_current(s) and all(screened(s,p) for p in s.papers.values())
    assert (store.path(s.id)/'briefing.pdf').exists()


def test_ui_labels_all_candidates_and_legacy_honestly(completed,store,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PAPER_AGENT_DATA',str(store.root))
    app=AppTest.from_file(Path('app.py').resolve(),default_timeout=15).run()
    assert not app.exception and any('이전 실행' in i.value for i in app.info)
    ex=configure(completed);screen_all(completed,ex);compare_all(completed,ex);store.save(completed)
    app.run()
    assert not app.exception
    assert '전체 후보 평가' in [t.label for t in app.tabs]
    assert len(app.dataframe[0].value)==len(completed.papers)
    assert all('초록 평가 완료' in value for value in app.dataframe[0].value['검토 범위'])


def test_rescreen_creates_new_record_without_fake_read_receipts(completed):
    from paper_agent.screening import rescreen_run
    original=copy.deepcopy(completed.model_dump())
    revised=rescreen_run(completed,completed.limits)
    assert revised.id!=completed.id and revised.briefing is None and revised.status=='ready'
    assert revised.require_target and revised.require_screening
    assert len(pending(revised))==len(completed.papers)
    assert revised.evidence==completed.evidence and revised.usage.model_calls==0
    assert completed.model_dump()==original


def test_finalization_waits_for_reviewed_shortlist_not_arbitrary_old_papers(completed):
    from paper_agent.completion import completion_directive
    ex=configure(completed)
    extra=fixture_paper(1);extra.id,extra.title,extra.identifiers='extra','new distinct candidate',{'new':'x'}
    add_paper(completed,extra)
    screen_all(completed,ex)
    shortlisted=[extra.id]+list(completed.papers)[:2]
    execute(ex,'compare_candidates',ranked_paper_ids=list(completed.papers),shortlist=shortlisted,summary='새 후보를 포함해 다른 접근의 원문을 우선 검토합니다.')
    assert not ready_to_finalize(completed)
    assert '현재 2편' in completion_directive(completed)
    with pytest.raises(SourceError,match='candidate_shortlist'):
        execute(ex,'fetch_fulltext',paper_id=list(completed.papers)[2],route='auto')
