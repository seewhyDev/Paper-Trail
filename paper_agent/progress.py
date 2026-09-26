"""Detect sustained lack of new research work, not a fixed total turn count."""
import hashlib
import json


def milestones(state):
    from .screening import screened, comparison_current
    from .depth import detailed_ready

    markers = set()

    def mark(*parts):
        markers.add(hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest())

    if state.criteria:
        mark("criteria")  # rewording instructions is not research progress
    for paper in state.papers.values():
        mark("candidate", paper.id)
        if paper.metadata_attempted:
            mark("metadata", paper.id)
        for start, end in paper.abstract_read_ranges:
            mark("abstract", paper.id, start, end)
        if screened(state, paper):
            mark("screened", paper.id)
        if paper.fulltext_status == "available":
            mark("fulltext", paper.id)
        for chunk in paper.read_chunks:
            mark("read", paper.id, chunk)
        if paper.verdict != "unassessed":
            mark("assessed", paper.id)
        if detailed_ready(state, paper):
            mark("draft", paper.id)
    if state.candidate_comparison and comparison_current(state):
        mark("comparison", sorted(state.papers))
    for paper_id in state.usage.fulltext_attempts:
        mark("fulltext_attempt", paper_id)
    for evidence in state.evidence.values():
        # Rewriting a claim or assigning another evidence ID is not new reading.
        mark("evidence", evidence.paper_id, evidence.chunk_id, " ".join(evidence.quote.split()))
    if state.briefing:
        mark("finished")
    return markers


def initialize_progress(state):
    state.progress_markers = sorted(set(state.progress_markers) | milestones(state))


def record_progress(state):
    current, seen = milestones(state), set(state.progress_markers)
    state.stalled_turns = 0 if current - seen or state.status == "completed" else state.stalled_turns + 1
    state.progress_markers = sorted(current | seen)
    if state.stalled_turns == 3:
        state.event("progress_recovery", "새로운 검토 결과가 없어 반복을 점검하고 다른 작업을 선택합니다.")


def recovery_instruction(state):
    if state.stalled_turns < 3:
        return None
    return ("최근 호출에서 새 자료 열람·근거·유효한 초안이 늘지 않았습니다. 같은 도구와 인자를 반복하지 마세요. "
            "직전 오류를 수정하거나 아직 읽지 않은 본문을 읽고, 원문 접근이 안 되면 다른 후보를 선택하세요. "
            "작성 가능한 논문은 write_paper_brief로 저장하고, 필요한 초안이 모두 있으면 즉시 최종 제출하세요.")
