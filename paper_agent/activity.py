"""Human-readable activity derived only from real saved execution events."""
from urllib.parse import urlsplit

TOOL_LABELS = {
    "record_evidence": "본문 근거와 해석 정리",
    "write_paper_brief": "논문별 상세 브리핑 작성", "finish_briefing": "검토한 논문을 PDF로 정리",
    "read_candidates": "후보 제목·초록 읽기", "screen_candidates": "후보별 비교 평가",
    "compare_candidates": "전체 후보 우선순위 비교",
    "set_criteria": "탐색 방향 정리", "search_papers": "관련 논문 검색",
    "get_metadata": "제목·저자·초록 확인", "fetch_fulltext": "원문 다운로드",
    "list_sections": "논문 목차 확인", "read_chunks": "원문 구간 읽기",
    "assess_candidate": "논문 평가와 근거 정리", "submit_briefing": "브리핑 작성·인용 검사",
    "ask_user": "추가 정보 확인", "stop_incomplete": "탐색 방향 재검토",
}
SITES = {"arxiv": "arXiv", "europepmc": "Europe PMC", "crossref": "Crossref"}


def describe_tool(state, event):
    args = event.arguments or {}
    paper = state.papers.get(args.get("paper_id") or args.get("brief", {}).get("paper_id"))
    result_event = next((e for e in reversed(state.events)
                         if e.kind == "tool_result" and e.call_id == event.call_id), None)
    network = next((e for e in reversed(state.events)
                    if e.kind == "network_request" and e.call_id == event.call_id), None)
    item = {"title": TOOL_LABELS.get(event.name, "자료 정리"), "tool": event.name,
            "detail": paper.title if paper else "", "site": "", "query": "", "url": "",
            "status": "진행 중" if result_event is None and state.status == "running" else "중단됨"}
    if result_event:
        result = result_event.result or {}
        item["status"] = "보완 필요" if result.get("ok") is False else "완료"
        if result.get("error") == "invalid_briefing":
            item["detail"] = "논문별 인용과 비교 문장의 출처를 보완합니다."
    if event.name == "search_papers":
        item["site"] = SITES.get(args.get("source"), "학술 자료")
        item["query"] = args.get("query", "")
    if event.name in {"read_candidates", "screen_candidates"}:
        ids = args.get("paper_ids", []) if event.name == "read_candidates" else [r.get("paper_id") for r in args.get("reviews", [])]
        item["detail"] = " / ".join(state.papers[pid].title for pid in ids if pid in state.papers)
    if event.name == "fetch_fulltext":
        item["route"] = {"auto": "공개 원문", "html": "HTML", "pdf": "PDF", "xml": "XML"}.get(args.get("route"), "공개 원문")
    if event.name == "read_chunks" and paper:
        locations = [paper.chunks[c].location.split(" / 문자")[0] for c in args.get("chunk_ids", []) if c in paper.chunks]
        item["sections"] = list(dict.fromkeys(locations))
    if network:
        item["url"] = (network.arguments or {}).get("url", "")
        item["site"] = item["site"] or urlsplit(item["url"]).hostname or ""
    return item


def activity_view(state):
    requests = [e for e in state.events if e.kind == "tool_request" and e.arguments]
    latest = requests[-1] if requests else None
    pending = None
    if latest and not any(e.kind == "tool_result" and e.call_id == latest.call_id for e in state.events):
        pending = describe_tool(state, latest)
    if pending is None:
        from .completion import ready_to_finalize
        finalizing = ready_to_finalize(state)
        pending = {"title": f"{state.limits.target}편 브리핑을 작성하고 있어요" if finalizing else "다음 검색·검토 대상을 고르고 있어요",
                   "tool": "", "detail": "논문별 상세 내용을 확인하고 PDF를 완성합니다." if finalizing
                   else "지금까지 확인한 자료를 바탕으로 다음 행동을 결정합니다.",
                   "site": "", "query": "", "url": "", "status": "진행 중"}
        if state.require_screening:
            from .screening import pending as missing, comparison_current
            left = missing(state)
            if left:
                pending["title"] = "전체 후보의 제목·초록을 비교하고 있어요"
                pending["detail"] = f"{len(state.papers)}편 중 {len(state.papers)-len(left)}편 평가 완료. 각 후보의 관련성과 검토 이유를 기록합니다."
            elif state.papers and not comparison_current(state):
                pending["title"] = "후보들의 우선순위를 정하고 있어요"
                pending["detail"] = "개별 평가를 종합해 원문을 읽을 후보와 참고·제외할 후보를 비교합니다."
    done = [describe_tool(state, e) for e in requests[-6:]
            if any(r.kind == "tool_result" and r.call_id == e.call_id for r in state.events)]
    return pending, list(reversed(done[-4:]))
