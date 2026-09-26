"""Per-paper reading and drafting gates; citations remain internal to the report."""
import re
import hashlib

FIELDS = {"problem": 180, "method": 350, "results": 300, "limitations": 200}


def passages(p, cid):
    text = p.chunks[cid].text
    fingerprint = hashlib.sha256(text.encode()).hexdigest()[:12]
    result, start = [], 0
    while start < len(text):
        end = min(start + 400, len(text))
        if len(text) - end < 8:
            end = len(text)
        result.append({"id": f"{p.id}/{cid}/{fingerprint}/{start}", "text": text[start:end]})
        start = end
    return result


def overview(chunk):
    heading = chunk.location.split(" / 문자")[0].lower()
    return bool(re.search(r"\b(abstract|introduction|related work|references|bibliography)\b|초록|서론|참고문헌", heading))


def body_chunks(p):
    return [cid for cid, c in p.chunks.items()
            if not re.search(r"\b(references|bibliography)\b|참고문헌", c.location.lower())]


def reading_status(p):
    body = body_chunks(p)
    return {"read": len(set(p.read_chunks) & set(body)), "required": min(8, len(body)),
            "available": len(body)}


def validate_detailed_paper(s, brief):
    from .tools import validate_citations
    p = s.papers.get(brief.paper_id)
    if not p or p.fulltext_status != "available" or p.verdict != "keep":
        return ["상세 작성 전에 원문 확보·열람·keep 평가가 필요합니다."]
    errors = []
    coverage = reading_status(p)
    if not coverage["required"] or coverage["read"] < coverage["required"]:
        errors.append(f"reading_depth: 본문 구간 {coverage['read']}/{coverage['required']}개 열람. 방법·실험·논의 구간을 추가로 읽으세요.")
    chunks_by_field = {}
    for field, minimum in FIELDS.items():
        claim = getattr(brief, field)
        if len(claim.text.strip()) < minimum:
            errors.append(f"{field}: 최소 {minimum}자. 구체적인 설정·작동 원리·실험 조건·해석을 근거에 맞게 설명하세요.")
        errors.extend(validate_citations(s, claim.evidence_ids, {p.id}))
        chunks_by_field[field] = {s.evidence[e].chunk_id for e in claim.evidence_ids
                                 if e in s.evidence and s.evidence[e].paper_id == p.id}
    for field in ("method", "results"):
        if not any(cid in p.chunks and not overview(p.chunks[cid]) for cid in chunks_by_field[field]):
            errors.append(f"{field}: 초록·서론 요약이 아닌 본문의 방법/실험 구간 근거가 필요합니다.")
    if len(set.union(*chunks_by_field.values())) < min(4, coverage["required"]):
        errors.append("evidence_depth: 문제·방법·결과·한계에 서로 다른 본문 구간의 근거를 사용하세요(최소 4구간, 짧은 원문은 전체).")
    if chunks_by_field["method"] == chunks_by_field["results"]:
        errors.append("evidence_depth: 방법과 결과는 서로 다른 본문 구간을 확인해 근거를 연결하세요.")
    return errors


def detailed_ready(s, p):
    brief = s.paper_briefs.get(p.id)
    return bool(brief and not validate_detailed_paper(s, brief))


def focus_paper(s):
    from .screening import comparison_current
    if not s.require_depth or not comparison_current(s):
        return None
    return next((s.papers[pid] for pid in s.candidate_comparison.shortlist
                 if s.papers[pid].verdict not in {"exclude", "reference"}
                 and not detailed_ready(s, s.papers[pid])), None)
