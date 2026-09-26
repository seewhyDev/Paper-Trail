"""Completion policy: three grounded papers, automatic scope decisions, safe resume."""


def reviewed_papers(state):
    from .tools import validate_citations
    from .depth import detailed_ready
    return [p for p in state.papers.values()
            if p.verdict == "keep" and p.fulltext_status == "available" and p.read_chunks
            and any(e.paper_id == p.id and not validate_citations(state, [e.id], {p.id})
                    for e in state.evidence.values())
            and (not state.require_depth or detailed_ready(state, p))]


def ready_to_finalize(state):
    from .screening import screening_errors
    eligible = reviewed_papers(state)
    if state.require_screening:
        eligible = [p for p in eligible if state.candidate_comparison and p.id in state.candidate_comparison.shortlist]
    return len(eligible) >= state.limits.target and not screening_errors(state)


def completion_directive(state):
    if state.require_screening:
        from .screening import pending, comparison_current, has_read
        missing = pending(state)
        if missing:
            ready = [pid for pid in missing if has_read(state.papers[pid])]
            if ready:
                return (f"기존 선정 기준을 유지하세요. 다음 후보를 먼저 screen_candidates로 평가하세요(최대 5편): {ready[:5]}. "
                        "read_candidates/get_metadata의 quote_passages에서 해당 논문의 근거 구절 ID를 quote_id로 선택하세요. "
                        "이전에 선정했던 논문만 평가하지 말고 모든 미평가 후보를 차례로 처리하세요.")
            return (f"전체 후보 비교 평가가 우선입니다. 미완료 후보: {missing}. "
                    "read_candidates로 최대 5편씩 제목·초록 전체를 읽고 screen_candidates로 공통 기준 평가·인용·이유를 기록하세요. "
                    "초록이 없으면 제목만 확인한 한계를 명시하세요. 모든 후보 평가가 끝나기 전에는 추가 검색·원문 검토·최종 제출을 할 수 없습니다.")
        if state.papers and not comparison_current(state):
            return "compare_candidates로 제외 후보까지 전체를 순위화하고 접근의 차이·우선순위 이유와 원문 검토 shortlist를 기록하세요."
    if state.require_depth:
        count = len(reviewed_papers(state))
        if count >= state.limits.target:
            return f"상세 브리핑 {count}편이 검증되었습니다. finish_briefing에 정확히 {state.limits.target}개의 paper_id를 전달해 완료하세요."
        return (f"요청한 {state.limits.target}편 중 상세 브리핑 {count}편 완료. 원문 검토 shortlist에서 논문 한 편씩 마무리하세요. "
                "list_sections로 방법·실험 설정·결과·분석·한계 구간을 찾고 최소 8개 본문 구간(짧으면 전체)을 read_chunks로 나누어 읽으세요. "
                "방법과 결과는 서론의 요약이 아닌 해당 본론을 읽어야 합니다. record_evidence에 quote_passages의 ID를 선택해 최소 4개 서로 다른 구간의 근거를 저장하세요. "
                "그 다음 write_paper_brief로 문제 180자·방법 350자·결과 300자·한계 200자 이상, 여러 문장의 구체적인 설명을 작성하세요. "
                "문제의 필요성과 기존 한계, 방법의 단계·기존 방식과 차이, 데이터·모델·예산·기준선·측정 지표·수치의 조건, "
                "검증 범위와 적용상 한계를 포함하세요. 확인하지 못한 수치는 만들지 말고 미확인이라고 적으세요. 같은 말을 반복해 분량을 채우지 마세요. "
                "이미 상세 작성한 논문은 반복하지 말고 다음 논문으로 넘어가세요. 원문 불가/부적합이면 다른 후보나 검색을 선택하세요.")
    count = len(reviewed_papers(state))
    if state.require_screening and state.candidate_comparison:
        count = sum(p.id in state.candidate_comparison.shortlist for p in reviewed_papers(state))
    if count >= state.limits.target:
        return (f"원문과 근거를 갖춘 후보 {count}편이 있습니다. 추가 검색을 멈추고 정확히 {state.limits.target}편의 "
                "submit_briefing을 완성하세요. 부족한 구간만 read_chunks로 확인하세요. "
                "reading_order에는 paper_id를 쓰고, comparison의 각 문장은 서로 다른 두 논문 이상의 "
                "실제 근거 ID를 인용하세요. invalid_briefing은 지적된 필드만 수정해 다시 제출하세요.")
    return (f"최종 결과는 정확히 {state.limits.target}편의 원문 근거를 갖춘 브리핑입니다. 현재 {count}편입니다. "
            "질문이 넓으면 요청 편수에 맞는 대표 접근으로 스스로 구체화하고, 좁아서 결과가 적으면 "
            "동의어·약어의 전체 이름·상위 주제·직접 관련 방법론으로 단계적으로 확장하세요. "
            "확장한 후보의 원래 질문과의 관계는 selection_reason에 명시하세요. 명시적 제외 조건은 지키세요. "
            "무관한 후보는 assess_candidate(exclude, notes=[])로 즉시 제외해 대체 후보 자리를 확보하세요. "
            "빈 결과에는 같은 검색을 반복하지 말고 질의/소스를 바꾸세요. 원문 실패에는 다른 경로나 후보를 쓰세요. "
            "질문의 범위를 사용자에게 다시 정하게 하거나 1~2편으로 종료하지 마세요. "
            "논문과 인용은 실제 도구 자료만 사용하고, 없는 결과를 만들지 마세요.")


def resume_problem(state, *, refresh_call_policy=False):
    """Read-only check, shared by the UI and the mutation under the store lock."""
    if state.status not in {"incomplete", "error", "cancelled"} or state.briefing:
        return "이어갈 수 있는 중단 상태가 아닙니다."
    from .config import default_limits
    policy = default_limits() if refresh_call_policy else state.limits
    finalizing = ready_to_finalize(state)
    if ((policy.tokens is not None and state.usage.charged_tokens >= policy.tokens)
            or (policy.model_calls is not None and state.usage.model_calls >= policy.model_calls and not finalizing)
            or (finalizing and policy.finalization_calls is not None
                and state.usage.finalization_calls >= policy.finalization_calls)
            or state.usage.tool_calls >= state.limits.tool_calls
            or state.usage.active_seconds >= state.limits.seconds):
        return "설정된 실행 한도를 모두 사용해 바로 이어갈 수 없습니다. 확보한 자료는 저장되어 있습니다."
    if policy.tokens is not None:
        from .agent import prepare_model_request
        from .worker import close_interrupted_calls
        candidate = state.model_copy(deep=True)
        if refresh_call_policy:
            apply_resume_policy(candidate, policy)
        candidate.require_target = True
        candidate.stalled_turns = 0
        close_interrupted_calls(candidate)
        if prepare_model_request(candidate)[-1] < 256:
            return "남은 토큰 예산으로 다음 요청을 보낼 수 없습니다. MAX_TOKENS를 auto 또는 더 큰 값으로 설정하고 서버를 재시작하세요."
    return None


def apply_resume_policy(state, policy):
    """Apply renewable execution policy while preserving observations and usage."""
    state.limits.model_calls = policy.model_calls
    state.limits.finalization_calls = policy.finalization_calls
    state.limits.stalled_turns = policy.stalled_turns
    state.limits.tokens = policy.tokens


def prepare_resume(state, *, refresh_call_policy=False):
    """Reuse work; optionally adopt current call/token policy, never reset spending."""
    problem = resume_problem(state, refresh_call_policy=refresh_call_policy)
    if problem:
        raise ValueError(problem)
    from .worker import close_interrupted_calls
    close_interrupted_calls(state)
    if refresh_call_policy:
        from .config import default_limits
        policy = default_limits()
        apply_resume_policy(state, policy)
    state.stalled_turns = 0  # explicit user resume permits another recovery attempt
    state.require_target = True
    state.status, state.stop_reason, state.pdf_error = "ready", "", ""
    state.event("resume", f"확보한 논문과 근거를 유지하고 {state.limits.target}편 브리핑 작성을 이어갑니다.")


def repair_structure(state, briefing):
    """Repair presentation only; never invent or attach evidence to an unsupported claim."""
    from .tools import validate_briefing, validate_citations
    candidate = briefing.model_copy(deep=True)
    selected = [p.paper_id for p in candidate.papers]
    changes = []
    if len(set(selected)) != state.limits.target or len(selected) != state.limits.target:
        return briefing, changes
    if len(candidate.reading_order) != len(selected) or set(candidate.reading_order) != set(selected):
        candidate.reading_order = selected
        changes.append("읽기 순서를 제출된 논문 순서의 실제 식별자로 정리했습니다.")
    comparisons = []
    for index, claim in enumerate(candidate.comparison):
        covered = {state.evidence[e].paper_id for e in claim.evidence_ids if e in state.evidence}
        if len(covered) >= 2 and not validate_citations(state, claim.evidence_ids, set(selected)):
            comparisons.append(claim)
        else:
            changes.append(f"comparison[{index}]: 출처가 충족되지 않은 비교 문장을 제외했습니다.")
    if not comparisons:
        return briefing, []  # the model must supply at least one grounded comparison
    candidate.comparison = comparisons
    if validate_briefing(state, candidate):
        return briefing, []
    return candidate, changes
