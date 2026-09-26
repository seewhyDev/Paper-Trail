"""Clearly synthetic fixtures + deterministic replay policy. Not a real model."""
import json

from .network import SourceError
from .provider import Call, Turn
from .schema import Chunk, Paper
from .screening import pending, has_read, comparison_current, quote_passages

SCENARIOS = ["sufficient", "insufficient", "fulltext_failure", "mismatch", "budget"]
DEMO_QUESTION = "라벨이 적은 상황에서 문서 분류 모델을 비교하려고 합니다. 소규모 데이터에서 재현 가능한 방법과 한계를 검토해 주세요."


def fixture_paper(index: int, bad=False):
    pid = "fixture_4" if bad else f"fixture_{index}"
    names = ["적은 라벨로 학습하는 문서 분류", "불확실성을 활용한 라벨 선택", "검색 예시를 활용한 분류", "조건 불일치 예제", "지식 증류를 활용한 분류", "약한 지도 신호를 활용한 분류"]
    return Paper(id=pid, title="[합성 예제] " + ("적은 라벨 문서 분류의 실험 검토" if bad else names[index - 1]),
                 authors=["합성 연구자 (실제 저자 아님)"], year=2025, source="fixture", source_id=pid,
                 identifiers={"fixture": pid}, url=f"https://example.org/synthetic/{pid}",
                 abstract="합성 데이터: 적은 라벨의 문서 분류를 검토하는 재현 가능한 도구 연결 테스트용 자료.",
                 fulltext_urls=[f"https://example.org/synthetic/{pid}/fulltext"])


TEXTS = {
    1: ["이 합성 실험은 적은 라벨을 사용할 때 문서 분류기를 학습하는 문제를 다룬다.",
        "방법은 사전 학습 표현을 고정하고 작은 분류기를 학습하는 것이다. 라벨 100개를 사용했다.",
        "동일 데이터의 내부 비교에서 분류 오류가 줄었다. 이 예제는 실제 논문의 수치나 결론이 아니다.",
        "한계는 한 언어의 작은 합성 문서 집합만 사용했다는 것이다. 다른 분야로의 일반화는 확인하지 않았다."],
    2: ["이 합성 실험은 문서 분류의 라벨 수집 비용을 줄이는 문제를 다룬다.",
        "방법은 불확실성이 높은 문서를 먼저 골라 사람이 라벨링하는 것이다. 라벨 80개를 사용했다.",
        "무작위 선택에 비해 유용한 학습 예시를 더 빨리 확보했다. 실제 측정 수치는 제공하지 않는다.",
        "한계는 라벨링 시간과 오류 비용을 실측하지 않았다는 것이다. 문서 분포가 바뀌면 선택 편향이 생길 수 있다."],
    3: ["이 합성 실험은 적은 학습 문서로 새로운 문서를 분류하는 문제를 다룬다.",
        "방법은 유사한 학습 문서를 검색해 입력에 포함하는 것이다. 라벨 120개를 사용했다.",
        "유사 예시가 있는 문서에서는 분류를 지원했다. 검색 실패 사례에서는 도움이 제한적이었다.",
        "한계는 검색 결과 품질에 의존한다는 것이다. 실험 조건이 다른 합성 예제와 성능을 직접 비교할 수 없다."],
}


class FixtureSources:
    def __init__(self, state):
        self.state = state

    def search(self, source, query, limit, offset=0):
        if self.state.scenario == "insufficient" and self.state.usage.searches == 1:
            return []
        papers = [fixture_paper(i) for i in range(1, 4)]
        if self.state.limits.target > 3:
            papers += [fixture_paper(i) for i in range(5, 5 + self.state.limits.target - 3)]
        if self.state.scenario == "mismatch":
            papers.insert(0, fixture_paper(1, bad=True))
        return papers[:limit]

    def details(self, p):
        return p.model_copy(deep=True)

    def fulltext(self, p, route):
        if self.state.scenario == "fulltext_failure" and p.id == "fixture_1" and route != "pdf":
            raise SourceError("통제된 합성 상황: 기본 공개 원문 경로 HTTP 404. 다른 경로나 후보를 선택하세요.")
        if p.id == "fixture_4":
            texts = ["이 합성 원문은 라벨 100만 개를 사용하는 대규모 문서 분류만 평가한다. 적은 라벨 조건은 실험하지 않았다."]
        else:
            texts = TEXTS.get(int(p.id[-1]), TEXTS[1])
        headings = ["1 문제 정의", "2 방법", "3 결과", "4 한계"]
        return [Chunk(id=f"c{i+1:03}", location=headings[i], text=t,
                      source_url=p.fulltext_urls[0]) for i, t in enumerate(texts)], "합성 원문 fixture; 실시간 검색/실제 논문 아님"


def synthetic_briefing(state):
    papers = [p for p in state.papers.values() if p.verdict == "keep"][:state.limits.target]
    briefs = []
    def cited(text, eid, kind="paper_claim"):
        return {"text": text, "kind": kind, "evidence_ids": [eid]}
    for p in papers:
        notes = {e.chunk_id: e for e in state.evidence.values() if e.paper_id == p.id}
        refs = [notes[c] for c in sorted(notes)]
        briefs.append({"paper_id": p.id,
                       "selection_reason": cited("합성 자료에서 적은 라벨 조건을 다루어 선정 기준에 부합한다.", refs[1].id, "agent_interpretation"),
                       "problem": cited(refs[0].claim, refs[0].id), "method": cited(refs[1].claim, refs[1].id),
                       "results": cited(refs[2].claim, refs[2].id), "limitations": cited(refs[3].claim, refs[3].id),
                       "application": cited("사용자 연구의 비교 방법 후보로 검토할 수 있다. 실제 재현 실험은 별도로 필요하다.", refs[1].id, "agent_interpretation"),
                       "first_read_chunks": ["c002", "c004"]})
    compare_ids = [next(e.id for e in state.evidence.values() if e.paper_id == p.id and e.chunk_id == "c002") for p in papers]
    return {"title": "적은 라벨 문서 분류: 합성 예제 브리핑", "papers": briefs,
            "comparison": [{"text": "합성 예제들은 적은 라벨 문제를 공유하며 표현 학습·라벨 선택·검색 예시라는 다른 접근을 보여 준다. 데이터와 라벨 수가 달라 성능 순위를 매길 수 없다.",
                            "kind": "agent_interpretation", "evidence_ids": compare_ids}],
            "reading_order": [p.id for p in papers], "scope": "코드에 포함된 합성 자료만 사용했다. 실시간 학술 검색과 실제 모델 판단은 실행하지 않았다.",
            "uncertainties": ["이 PDF는 형식과 도구 연결을 보여 주는 데모이며 실제 연구 추천이 아니다.", "근거 위치 일치 검사는 주장의 의미적 정확성을 보장하지 않는다."]}


class ReplayProvider:
    """Scripted policy for UI demonstration and plumbing tests ONLY."""
    def __init__(self, state):
        self.s = state

    def respond(self, conversation, tools, max_output_tokens, timeout):
        s = self.s
        requests = []
        def req(name, **args):
            args.setdefault("decision", "합성 데모: 저장된 시나리오에 따른 동작")
            requests.append(Call(f"demo_{s.usage.model_calls}_{len(requests)}", name, json.dumps(args, ensure_ascii=False)))
        if not s.goal:
            req("set_criteria", goal=s.context.question, criteria=["라벨이 적은 문서 분류", "방법과 한계의 원문 근거", "서로 다른 접근의 보완 관계"])
        elif not s.papers:
            req("search_papers", source="arxiv", query="low label text classification" if not s.searches else "few shot document classification methods",
                limit=max(5, s.limits.target + 1), offset=0, decision="첫 검색 후보가 없어 검색 표현을 바꿉니다." if s.searches else "합성 데모 후보 조회")
        elif s.require_screening and pending(s):
            candidates = [s.papers[pid] for pid in pending(s)]
            unread = [p for p in candidates if not has_read(p)]
            if unread:
                req("read_candidates", paper_ids=[p.id for p in unread[:5]])
            else:
                req("screen_candidates", reviews=[{"paper_id": p.id, "relevance": 4, "method_fit": 4,
                    "evidence_potential": 4, "decision": "fulltext", "reason": "합성 예제의 적은 라벨 조건과 방법을 비교할 원문 검토 후보입니다.",
                    "quote_id": quote_passages(p)[0]["id"], "limitation": "합성 자료"} for p in candidates[:5]])
        elif s.require_screening and not comparison_current(s):
            req("compare_candidates", ranked_paper_ids=list(s.papers), shortlist=list(s.papers),
                summary="합성 후보들은 적은 라벨 문서 분류를 공유하며 표현 학습·라벨 선택·검색 예시라는 서로 다른 접근을 비교합니다.")
        elif any(not p.metadata_read for p in s.papers.values()):
            for p in s.papers.values():
                if not p.metadata_read:
                    req("get_metadata", paper_id=p.id, abstract_offset=0)
        elif any(not p.chunks and p.verdict != "exclude" for p in s.papers.values()):
            for p in s.papers.values():
                if not p.chunks and p.verdict != "exclude":
                    req("fetch_fulltext", paper_id=p.id, route="pdf" if p.fulltext_status == "failed" else "auto",
                        decision="기본 경로 실패를 관측해 PDF 대체 경로를 조회합니다." if p.fulltext_status == "failed" else "합성 원문 확보")
        elif any(not p.read_chunks for p in s.papers.values()):
            for p in s.papers.values():
                if not p.read_chunks:
                    req("read_chunks", paper_id=p.id, chunk_ids=list(p.chunks)[:4])
        elif any(p.verdict == "unassessed" for p in s.papers.values()):
            for p in s.papers.values():
                if p.verdict != "unassessed":
                    continue
                bad = p.id == "fixture_4"
                req("assess_candidate", paper_id=p.id, verdict="exclude" if bad else "keep", relevance=1 if bad else 4,
                    reason="원문이 라벨 100만 개 조건이므로 연구 조건과 맞지 않아 제외" if bad else "적은 라벨 조건과 방법·결과·한계를 확인",
                    notes=[{"chunk_id": c.id, "quote": c.text, "claim": c.text, "kind": "paper_claim"} for c in p.chunks.values()])
        else:
            req("submit_briefing", briefing=synthetic_briefing(s), decision="합성 데모에서 필요한 원문 근거가 확보되어 종료")
        return Turn(requests)  # zero real token usage; UI labels synthetic calls explicitly
