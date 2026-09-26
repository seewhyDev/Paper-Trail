import copy
import json
from pathlib import Path

import pytest

from paper_agent.agent import Agent
from paper_agent.completion import prepare_resume, ready_to_finalize
from paper_agent.demo import FixtureSources, ReplayProvider
from paper_agent.depth import validate_detailed_paper, reading_status
from paper_agent.network import SourceError
from paper_agent.schema import Chunk
from paper_agent.tools import ToolExecutor, validate_call, definitions, validate_briefing


def call(ex, name, **args):
    return ex.execute(name, validate_call(name, json.dumps({'decision':'test', **args})))


@pytest.mark.parametrize('target', [1, 2, 5])
def test_requested_count_survives_pipeline_and_resume(state, store, target):
    state.require_target = state.require_screening = True
    state.limits.target = target
    Agent(state, ReplayProvider(state), FixtureSources(state), store).run()
    assert state.status == 'completed' and len(state.briefing.papers) == target
    state.status, state.briefing = 'cancelled', None
    before = copy.deepcopy(state.usage)
    prepare_resume(state)
    assert state.limits.target == target and state.usage == before


def rich(brief):
    result = brief.model_copy(deep=True)
    for field in ('problem', 'method', 'results', 'limitations'):
        claim = getattr(result, field)
        claim.text = (claim.text + ' ') * 12
    return result


def add_reading(p):
    for i in range(5, 9):
        cid = f'c{i:03}'
        p.chunks[cid] = Chunk(id=cid, location=f'{i} Additional experiments', text='Additional controlled evidence.', source_url=p.url)
        p.read_chunks.append(cid)


def test_four_chunks_and_one_line_cannot_complete_new_detailed_policy(completed):
    completed.require_depth = True
    brief = completed.briefing.papers[0]
    p = completed.papers[brief.paper_id]
    for i in range(5, 13):
        cid=f'c{i:03}'
        p.chunks[cid]=Chunk(id=cid,location='Experiments',text='Evidence.',source_url=p.url)
    errors=validate_detailed_paper(completed, brief)
    assert any('reading_depth' in e for e in errors)
    assert any('method:' in e for e in errors)
    assert not ready_to_finalize(completed)
    assert 'submit_briefing' not in {d['name'] for d in definitions(completed)}
    assert validate_briefing(completed, completed.briefing)


def test_detailed_drafts_assemble_without_comparison_and_revalidate_evidence(completed):
    s=completed;original=list(s.briefing.papers)
    s.require_depth=s.require_target=True;s.limits.target=2;s.status='running';s.briefing=None
    ex=ToolExecutor(s,FixtureSources(s))
    for brief in original[:2]:
        p=s.papers[brief.paper_id];add_reading(p)
        result=call(ex,'write_paper_brief',brief=rich(brief).model_dump())
        assert result['ok']
    ids=[b.paper_id for b in original[:2]]
    with pytest.raises(SourceError,match='target_count'):
        call(ex,'finish_briefing',paper_ids=ids[:1])
    assert ready_to_finalize(s)
    result=call(ex,'finish_briefing',paper_ids=ids)
    assert result['ok'] and len(s.briefing.papers)==2 and not s.briefing.comparison
    note=s.evidence[s.briefing.papers[0].method.evidence_ids[0]]
    s.papers[note.paper_id].chunks[note.chunk_id].text='Changed source text'
    assert validate_briefing(s,s.briefing)


def test_method_results_cannot_rely_only_on_introduction(completed):
    s=completed;s.require_depth=True
    b=rich(s.briefing.papers[0]);p=s.papers[b.paper_id];add_reading(p)
    for cid in ('c002','c003'):p.chunks[cid].location='1 Introduction'
    errors=validate_detailed_paper(s,b)
    assert any('method:' in e for e in errors) and any('results:' in e for e in errors)


def test_short_document_requires_all_available_body_and_next_turn(completed):
    s=completed;s.require_depth=True
    b=rich(s.briefing.papers[0]);p=s.papers[b.paper_id]
    assert reading_status(p)['required']==4
    ex=ToolExecutor(s,FixtureSources(s))
    call(ex,'read_chunks',paper_id=p.id,chunk_ids=['c002'])
    assert not call(ex,'write_paper_brief',brief=b.model_dump())['ok']
    s.usage.model_calls+=1
    assert call(ex,'write_paper_brief',brief=b.model_dump())['ok']


def test_ui_target_default_selection_and_saved_request(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from paper_agent.store import Store
    monkeypatch.setenv('PAPER_AGENT_DATA',str(tmp_path/'data'))
    monkeypatch.setattr('paper_agent.worker.launch',lambda *args,**kwargs:None)
    app=AppTest.from_file(Path('app.py').resolve(),default_timeout=15).run()
    app.radio[0].set_value('예시 체험').run()
    target=next(x for x in app.selectbox if x.label=='최종 추천 논문 수')
    assert target.value==3
    target.set_value(5)
    next(b for b in app.button if b.label=='브리핑 만들기').click().run()
    assert not app.exception
    s=Store(tmp_path/'data').list_runs()[0]
    assert s.limits.target==5


def test_located_fulltext_evidence_uses_exact_source_and_rejects_other_chunk(completed):
    from paper_agent.depth import passages
    s=completed;s.require_depth=True
    p=next(iter(s.papers.values()));ex=ToolExecutor(s,FixtureSources(s))
    result=call(ex,'read_chunks',paper_id=p.id,chunk_ids=['c001','c002'])
    assert ''.join(q['text'] for q in result['chunks'][0]['quote_passages']) == p.chunks['c001'].text
    q=passages(p,'c001')[0]
    args=dict(paper_id=p.id,verdict='keep',relevance=4,reason='test',notes=[dict(chunk_id='c001',quote_id=q['id'],claim='test claim',kind='paper_claim')])
    result=call(ex,'record_evidence',**args)
    assert s.evidence[result['evidence_ids'][0]].quote==q['text']
    args['notes'][0]['chunk_id']='c002'
    with pytest.raises(SourceError,match='invalid_quote_id'):
        call(ex,'record_evidence',**args)
