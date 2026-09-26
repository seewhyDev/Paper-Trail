"""Auditable candidate screening; completeness is a program invariant, not a prompt."""
import hashlib
import json

from .network import SourceError
from .schema import CandidateReview, CandidateComparison


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def source_hash(p):
    return digest([p.title, p.abstract, p.year, p.authors, p.doi])


def quote_passages(p):
    """Source-bound locators prevent transcription errors without inventing quotes."""
    text = p.abstract or p.title
    prefix = f"{p.id}:{source_hash(p)[:12]}"
    return [{"id": f"{prefix}:{start}", "text": text[start:start + 600], "offset": start}
            for start in range(0, len(text), 600)]


def criteria_hash(s):
    return digest([s.context.model_dump(), s.answers, s.goal, s.criteria])


def has_read(p):
    if p.screening_read_hash != source_hash(p):
        return False
    end = 0
    for start, stop in sorted(p.abstract_read_ranges):
        if start > end:
            break
        end = max(end, stop)
    return end >= len(p.abstract)


def mark_read(p, offset, end):
    fingerprint = source_hash(p)
    if p.screening_read_hash != fingerprint:
        p.abstract_read_ranges = []
    p.screening_read_hash = fingerprint
    p.abstract_read_ranges = sorted(set(p.abstract_read_ranges + [(offset, end)]))


def screened(s, p):
    r = p.screening
    text = p.abstract if p.abstract else p.title
    return bool(r and has_read(p) and r.source_hash == source_hash(p)
                and r.criteria_hash == criteria_hash(s) and r.quote.strip() and r.quote in text
                and r.basis == ("abstract" if p.abstract else "title_only")
                and (p.abstract or r.limitation.strip()))


def pending(s):
    return [p.id for p in s.papers.values() if not screened(s, p)]


def cohort_hash(s):
    return digest([criteria_hash(s), [(p.id, source_hash(p), p.screening.model_dump() if p.screening else None)
                                     for p in s.papers.values()]])


def comparison_current(s):
    c = s.candidate_comparison
    return bool(c and not pending(s) and c.cohort_hash == cohort_hash(s)
                and len(c.ranked_paper_ids) == len(s.papers) and set(c.ranked_paper_ids) == set(s.papers))


def screening_errors(s):
    if not s.require_screening:
        return []
    missing = pending(s)
    if missing:
        return [f"candidate_screening: 모든 후보의 제목·초록 열람과 현재 기준 평가가 필요합니다. 미완료: {missing}"]
    if not comparison_current(s):
        return ["candidate_comparison: compare_candidates로 전체 후보를 빠짐없이 순위화하고 비교 이유를 기록하세요."]
    return []


def read_candidate(executor, p, offset=0):
    # Search APIs often already supplied the complete abstract. Reuse it.
    if not p.abstract and not p.metadata_attempted:
        p.metadata_attempted = True
        try:
            fresh = executor.sources.details(p)
            p.abstract, p.authors, p.year = fresh.abstract, fresh.authors, fresh.year
            p.doi = fresh.doi or p.doi
            p.identifiers.update(fresh.identifiers)
            p.fulltext_urls = list(dict.fromkeys(p.fulltext_urls + fresh.fulltext_urls))
            p.metadata_issue = "" if p.abstract else "공개 메타데이터에 초록이 없습니다."
        except SourceError:
            p.metadata_issue = "상세 조회에 실패해 초록을 확보하지 못했습니다."
    p.metadata_read = True
    if offset > len(p.abstract):
        raise SourceError("abstract_offset: 초록 길이를 넘는 시작 위치입니다.")
    end = min(offset + 5000, len(p.abstract))
    mark_read(p, offset, end)
    p.screening_read_turn = executor.state.usage.model_calls
    return {"paper_id": p.id, "title": p.title, "year": p.year, "authors": p.authors,
            "abstract": p.abstract[offset:end], "abstract_offset": offset,
            "quote_passages": [q for q in quote_passages(p)
                               if not p.abstract or (q["offset"] >= offset and q["offset"] + len(q["text"]) <= end)],
            "abstract_next_offset": end if end < len(p.abstract) else None,
            "basis": "abstract" if p.abstract else "title_only",
            "limitation": p.metadata_issue if not p.abstract else "",
            "untrusted_source_material": True}


def record_reviews(s, reviews):
    if not s.goal or not s.criteria:
        raise SourceError("screening_criteria: 먼저 set_criteria로 공통 기준을 정하세요.")
    if len({r.paper_id for r in reviews}) != len(reviews):
        raise SourceError("duplicate_candidate: 같은 후보를 한 번씩 평가하세요.")
    staged = []
    for r in reviews:
        p = s.papers.get(r.paper_id)
        if not p or not has_read(p):
            raise SourceError(f"screening_read_required: {r.paper_id}의 제목과 초록 전체를 read_candidates/get_metadata로 먼저 읽으세요.")
        if p.screening_read_turn >= s.usage.model_calls:
            raise SourceError("screening_observation_required: 열람 도구의 결과를 다음 모델 턴에서 받은 뒤 평가하세요. 읽기와 평가는 같은 응답에 묶지 마세요.")
        if not r.reason.strip():
            raise SourceError("screening_reason: 후보별 평가 이유가 필요합니다.")
        passages = {q["id"]: q["text"] for q in quote_passages(p)}
        if r.quote_id not in passages:
            raise SourceError(f"screening_quote: {r.paper_id}의 현재 출처 구절 ID만 선택하세요: {list(passages)}")
        quote = passages[r.quote_id]
        if not p.abstract and (not r.limitation.strip() or r.decision == "fulltext"):
            raise SourceError(f"missing_abstract: {r.paper_id}는 초록 미확보 한계를 명시하고 reference/exclude로 분류하세요.")
        review = CandidateReview(**r.model_dump(exclude={"paper_id", "quote_id"}), quote=quote, basis="abstract" if p.abstract else "title_only",
                                 source_hash=source_hash(p), criteria_hash=criteria_hash(s))
        staged.append((p, review))
    for p, review in staged:
        p.screening = review
        # Screening is separate from the later full-text assessment.
        if not p.read_chunks:
            p.verdict = "exclude" if review.decision == "exclude" else "unassessed"
    return {"ok": True, "evaluated": [p.id for p, _ in staged], "remaining": pending(s)}


def compare(s, a):
    if pending(s):
        raise SourceError("screening_incomplete: 전체 후보의 개별 평가를 먼저 완료하세요.")
    if len(a.ranked_paper_ids) != len(s.papers) or set(a.ranked_paper_ids) != set(s.papers):
        missing = sorted(set(s.papers) - set(a.ranked_paper_ids))
        unknown = sorted(set(a.ranked_paper_ids) - set(s.papers))
        duplicates = sorted({pid for pid in a.ranked_paper_ids if a.ranked_paper_ids.count(pid) > 1})
        raise SourceError(f"ranking_coverage: 모든 후보를 한 번씩 포함하세요. 누락={missing}, "
                          f"존재하지 않는 ID={unknown}, 중복={duplicates}. 제목이나 ID를 임의 축약하지 마세요.")
    if len(set(a.shortlist)) != len(a.shortlist) or any(pid not in s.papers or s.papers[pid].screening.decision != "fulltext" for pid in a.shortlist):
        raise SourceError("shortlist: 원문 검토 대상으로 평가한 실제 후보만 중복 없이 포함하세요.")
    if not a.summary.strip():
        raise SourceError("comparison_summary: 공통점·차이와 우선순위를 정한 이유가 필요합니다.")
    s.candidate_comparison = CandidateComparison(ranked_paper_ids=a.ranked_paper_ids, shortlist=a.shortlist,
                                               summary=a.summary, cohort_hash=cohort_hash(s))
    return {"ok": True, "screened": len(s.papers), "shortlist": a.shortlist}


def rescreen_run(previous, limits):
    """Create a new auditable run; reuse source material without fabricating reviews."""
    from .schema import RunState
    state = RunState(mode=previous.mode, context=previous.context.model_copy(deep=True),
                     limits=limits.model_copy(deep=True), model=previous.model,
                     reasoning_effort=previous.reasoning_effort, require_target=True, require_screening=True,
                     goal=previous.goal, criteria=list(previous.criteria), answers=list(previous.answers),
                     papers={pid: p.model_copy(deep=True) for pid,p in previous.papers.items()},
                     evidence={eid: e.model_copy(deep=True) for eid,e in previous.evidence.items()})
    state.limits.target = previous.limits.target
    state.require_depth = previous.mode == "live" or previous.require_depth
    for paper in state.papers.values():
        paper.screening = None
        paper.screening_read_hash, paper.abstract_read_ranges, paper.screening_read_turn = "", [], -1
    state.event("rescreen", "이전 실행의 실제 자료를 재사용하고 전체 후보를 새로 비교 평가합니다.",
                arguments={"source_run":previous.id})
    return state
