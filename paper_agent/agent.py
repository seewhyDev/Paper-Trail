"""The explicit observe -> model tool call -> validate -> execute -> observe loop."""
import json
import time
from datetime import date

from .network import SourceError
from .history import STATE_PREFIX, model_input
from .provider import SYSTEM, ModelError, call_item, result_item
from .schema import RunState
from .tools import ToolExecutor, definitions, validate_call
from .completion import completion_directive, reviewed_papers, ready_to_finalize
from .progress import initialize_progress, record_progress, recovery_instruction

TERMINAL = {"completed", "incomplete", "error", "cancelled"}


def state_view(s: RunState):
    from .screening import pending, comparison_current
    from .depth import reading_status, detailed_ready, focus_paper
    view = {
        "research_context": s.context.model_dump(), "answers": s.answers, "goal": s.goal, "criteria": s.criteria,
        "mode": s.mode, "target_papers": s.limits.target, "today": date.today().isoformat(),
        "detailed_briefing_required": s.require_depth,
        "completion_policy": completion_directive(s) if s.require_target else "best_effort",
        "recovery_instruction": recovery_instruction(s),
        "screening": {"required": s.require_screening, "pending": pending(s) if s.require_screening else [],
                      "comparison_current": comparison_current(s),
                      "comparison": s.candidate_comparison.model_dump() if s.candidate_comparison else None},
        "remaining": {"searches": s.limits.searches - s.usage.searches,
                      "model_calls": (max(0, s.limits.model_calls - s.usage.model_calls)
                                      if s.limits.model_calls is not None else "until_complete"),
                      "finalization_calls": (max(0, s.limits.finalization_calls - s.usage.finalization_calls)
                                             if s.limits.finalization_calls is not None else "until_complete"),
                      "tools": s.limits.tool_calls - s.usage.tool_calls,
                      "seconds": round(max(0, s.limits.seconds - s.usage.active_seconds), 1),
                      "tokens": max(0, s.limits.tokens - s.usage.charged_tokens),
                      "distinct_fulltext_attempts": s.limits.fulltexts - len(s.usage.fulltext_attempts),
                      "candidate_slots": s.limits.candidates - (sum(p.verdict != "exclude" for p in s.papers.values())
                                                                  if s.require_target else len(s.papers))},
        "papers": [{"paper_id": p.id, "title": p.title, "verdict": p.verdict, "reason": p.reason,
                    "reading_depth": reading_status(p) if s.require_depth else None,
                    "detailed_brief_written": detailed_ready(s, p) if s.require_depth else False,
                    "fulltext": p.fulltext_status, "chunks": len(p.chunks), "read_chunks": p.read_chunks,
                    "metadata_read": p.metadata_read, "doi": p.doi, "identifiers": p.identifiers,
                    "screening": p.screening.model_dump(exclude={"source_hash", "criteria_hash"}) if p.screening else None,
                    "year": p.year,
                    "read_locations": {cid: p.chunks[cid].location for cid in p.read_chunks if cid in p.chunks}}
                   for p in s.papers.values()],
        "evidence": [e.model_dump() for e in s.evidence.values()],
        "searches": s.searches,
    }
    if s.require_screening and pending(s):
        # Initial screening compares source abstracts. Previously kept papers and
        # full-text notes return once screening is complete, avoiding anchoring
        # on an old shortlist and unnecessary input during this phase.
        view["papers"] = [{k: p[k] for k in ("paper_id", "title", "year", "screening")}
                          for p in view["papers"]]
        view["evidence"] = []
    focus = focus_paper(s)
    if focus:
        view["current_detail_paper"] = {"paper_id": focus.id, "title": focus.title,
                                        "instruction": "이 논문의 추가 원문 검토·근거 정리·상세 작성을 먼저 완료하세요."}
        view["evidence"] = [e.model_dump() for e in s.evidence.values() if e.paper_id == focus.id]
    return view


class Agent:
    def __init__(self, state, provider, sources, store, stop_requested=lambda: False):
        self.s, self.provider, self.sources, self.store = state, provider, sources, store
        self.stop_requested = stop_requested
        self.started, self.previous = time.monotonic(), state.usage.active_seconds
        self.executor = ToolExecutor(state, sources)
        self.executor.checkpoint = self.save
        self.active_call = None
        if hasattr(sources, "net"):
            sources.net.on_request = self.network_progress

    def network_progress(self, url):
        self.s.event("network_request", "공개 학술 자료 요청", call_id=self.active_call,
                     arguments={"url": url})
        self.save()

    def save(self):
        self.s.usage.active_seconds = self.previous + time.monotonic() - self.started
        self.store.save(self.s)

    def budget_reason(self):
        s = self.s
        if self.stop_requested():
            return "사용자가 실행을 중지했습니다."
        if self.previous + time.monotonic() - self.started >= s.limits.seconds:
            return "전체 실행 시간 상한 도달"
        finalizing = s.require_target and ready_to_finalize(s)
        if finalizing and s.limits.finalization_calls is not None and s.usage.finalization_calls >= s.limits.finalization_calls:
            return "최종 브리핑 작성 호출 상한 도달"
        if s.limits.model_calls is not None and s.usage.model_calls >= s.limits.model_calls and not finalizing:
            return "모델 호출 상한 도달"
        if s.stalled_turns >= s.limits.stalled_turns:
            return "새로운 자료·근거·브리핑 작성 없이 같은 작업이 반복되어 중단했습니다. 확보한 자료는 저장했습니다."
        if s.usage.tool_calls >= s.limits.tool_calls:
            return "도구 호출 상한 도달"
        if s.usage.charged_tokens >= s.limits.tokens:
            return "토큰 예산 상한 도달"
        return None

    def halt(self, reason, status="incomplete"):
        self.s.status, self.s.stop_reason = status, reason
        self.s.event("termination", reason)
        self.save()

    def run(self):
        s = self.s
        if s.status in TERMINAL or s.status == "waiting":
            return s
        s.status = "running"
        initialize_progress(s)
        while True:
            reason = self.budget_reason()
            if reason:
                self.halt(reason, "cancelled" if self.stop_requested() else "incomplete")
                break
            self.save()
            snapshot = {"role": "user", "content": STATE_PREFIX + json.dumps(state_view(s), ensure_ascii=False)}
            finalizing = s.require_target and ready_to_finalize(s)
            conversation = model_input(s, snapshot, recent_turns=(1 if finalizing else 2) if s.require_target else None)
            tool_defs = definitions(s)
            # Conservative admission budget: UTF-8 bytes upper-bound ordinary text tokens,
            # plus protocol overhead. Actual usage replaces this reservation if supplied.
            upper_input = len(json.dumps(conversation, ensure_ascii=False).encode()) + len(json.dumps(tool_defs, ensure_ascii=False).encode()) + len(SYSTEM.encode()) + 4096
            available_output = min(s.limits.output_tokens, s.limits.tokens - s.usage.charged_tokens - upper_input)
            if available_output < 256:
                self.halt("다음 요청의 입력 및 출력 예약량이 남은 토큰 예산을 초과합니다.")
                break
            reserve = upper_input + available_output
            s.usage.charged_tokens += reserve
            s.usage.model_calls += 1
            if finalizing:
                s.usage.finalization_calls += 1
            s.conversation.append(snapshot)
            s.event("model_request", f"모델 호출 {s.usage.model_calls}: 현재 관측과 남은 예산 전달")
            self.save()  # reserve before crossing the network boundary
            remaining_seconds = max(0.1, s.limits.seconds - s.usage.active_seconds)
            try:
                turn = self.provider.respond(conversation, tool_defs, available_output, min(90, remaining_seconds))
            except ModelError as e:
                self.halt(str(e), "error")
                break
            if turn.usage_known:
                s.usage.charged_tokens += turn.input_tokens + turn.output_tokens - reserve
                s.usage.input_tokens += turn.input_tokens
                s.usage.output_tokens += turn.output_tokens
            s.conversation.extend(turn.items or [call_item(c) for c in turn.calls])
            self.save()
            if not turn.calls:
                s.event("model_protocol", "도구 요청 없음. 구조화된 도구 호출을 다시 요청합니다.")
                s.conversation.append({"role": "user", "content": "반드시 제공된 function tool로 행동하고 유효한 submit_briefing으로 완료하세요."})
                record_progress(s)
                self.save()
                continue
            # Every call receives a matched output, including calls after pause/termination.
            # No hard-coded research tool order or query exists in this loop.
            for call in turn.calls:
                prior = next((e.result for e in s.events if e.kind == "tool_result" and e.call_id == call.id), None)
                if prior is not None:
                    result = {"ok": False, "error": "duplicate_call_id", "previous_result": prior}
                    s.conversation.append(result_item(call, result))
                    continue
                reason = None
                if self.stop_requested():
                    reason = "cancel_requested"
                elif self.previous + time.monotonic() - self.started >= s.limits.seconds:
                    reason = "time_budget"
                elif s.usage.charged_tokens >= s.limits.tokens:
                    reason = "token_budget"
                elif s.usage.tool_calls >= s.limits.tool_calls:
                    reason = "tool_budget"
                elif s.status != "running":
                    reason = "run_paused_or_finished"
                if reason:
                    result = {"ok": False, "error": reason, "executed": False}
                    s.event("tool_request", "상태/예산으로 실행하지 않은 요청", call_id=call.id, name=call.name)
                else:
                    s.usage.tool_calls += 1  # rejected arguments consume a call too
                    try:
                        args = validate_call(call.name, call.arguments)
                        s.event("tool_request", args.decision, call_id=call.id, name=call.name, arguments=args.model_dump())
                        self.save()
                        self.active_call = call.id
                        if hasattr(self.sources, "net"):
                            self.sources.net.deadline = self.started + s.limits.seconds - self.previous
                        result = self.executor.execute(call.name, args)
                    except SourceError as e:
                        if not any(e.kind == "tool_request" and e.call_id == call.id for e in s.events):
                            s.event("tool_request", "인자 검사에서 거부됨", call_id=call.id, name=call.name)
                        result = {"ok": False, "error": str(e)}
                    except Exception as e:
                        result = {"ok": False, "error": f"도구 내부 오류 ({type(e).__name__}); 다른 후보나 경로를 선택할 수 있습니다."}
                s.conversation.append(result_item(call, result))
                summary = (str(result.get("error")) if result.get("ok") is False else
                           f"{call.name}: 결과 저장 ({len(json.dumps(result, ensure_ascii=False))}자)")
                s.event("tool_result", summary, call_id=call.id, name=call.name, result=result)
                self.save()
            record_progress(s)
            self.save()
            if s.status in TERMINAL or s.status == "waiting":
                if s.status != "waiting":
                    s.event("termination", s.stop_reason)
                self.save()
                break
        return s


def answer_question(state: RunState, answer: str):
    if state.status != "waiting" or not state.pending_question:
        raise ValueError("답변 대기 중인 질문이 없습니다.")
    if not answer.strip() or len(answer) > 4000:
        raise ValueError("답변은 1~4000자로 입력하세요.")
    state.answers.append(answer.strip())
    state.conversation.append({"role": "user", "content": "추가 질문에 대한 사용자 답변: " + answer.strip()})
    state.event("user_answer", answer.strip())
    state.pending_question, state.status = None, "ready"
