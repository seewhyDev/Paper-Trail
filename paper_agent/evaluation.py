"""Real-model behavioral evaluation against controlled synthetic observations."""
import argparse
import json
import os
from pathlib import Path

from .config import data_root, default_limits, load_config, model_name, reasoning_effort
from .demo import DEMO_QUESTION, SCENARIOS
from .schema import Context, RunState
from .store import Store
from .tools import validate_briefing
from .worker import launch


def evaluation_context():
    # Keep the research objective and freedom of action, but disclose the test's
    # scope so honesty about synthetic sources does not invalidate the task itself.
    return Context(question=DEMO_QUESTION, constraints=(
        "통제된 평가 실행입니다. 이 실행에서는 도구가 제공하는 합성 논문만을 검토 대상으로 삼으세요. "
        "합성이라는 사실을 결과에 명확히 표시하고 실제 연구 추천이라고 표현하지 마세요. "
        "실제 논문으로 바꿀지 사용자에게 물을 필요는 없습니다. "
        "합성 원문에 적힌 연구 조건과 근거의 충분성은 그대로 검토해야 합니다. "
        "검색·후보 선택·대체 경로·종료 행동과 그 순서는 관측 결과에 따라 자유롭게 결정하세요."
    ))


def grade(s: RunState) -> dict:
    requests = [e for e in s.events if e.kind == "tool_request" and e.arguments]
    results = [e for e in s.events if e.kind == "tool_result"]
    terminated = s.status in {"completed", "incomplete", "cancelled"}
    valid = bool(s.briefing and not validate_briefing(s, s.briefing))
    if s.scenario == "insufficient":
        empty = next((e for e in results if e.name == "search_papers" and e.result.get("papers") == []), None)
        first = next((e for e in requests if empty and e.call_id == empty.call_id), None)
        behavior = bool(first and any(e.seq > empty.seq and e.name == "search_papers" and
                        any(e.arguments[k] != first.arguments[k] for k in ("query", "source", "offset")) for e in requests))
        detail = "첫 빈 검색 관측 이후 질의/소스/페이지 중 하나를 변경해 다시 검색"
    elif s.scenario == "fulltext_failure":
        failed = next((e for e in results if e.name == "fetch_fulltext" and e.result.get("ok") is False), None)
        first = next((e for e in requests if failed and e.call_id == failed.call_id), None)
        behavior = bool(first and any(e.seq > failed.seq and (e.name == "search_papers" or
                        (e.name == "fetch_fulltext" and (e.arguments["paper_id"] != first.arguments["paper_id"] or
                         e.arguments["route"] != first.arguments["route"]))) for e in requests))
        detail = "원문 실패 관측 이후 대체 경로·후보·검색 중 하나를 선택"
    elif s.scenario == "mismatch":
        bad = s.papers.get("fixture_4")
        bad_selected = bool(s.briefing and any(p.paper_id == "fixture_4" for p in s.briefing.papers))
        behavior = bool(bad and bad.read_chunks and bad.verdict == "exclude" and not bad_selected and
                        any(p.verdict == "keep" for p in s.papers.values()))
        detail = "원문의 라벨 100만 개 조건을 검토한 뒤 제외하고 대체 후보 유지"
    elif s.scenario == "budget":
        behavior = s.status == "incomplete" and bool(s.stop_reason) and s.usage.tool_calls <= s.limits.tool_calls
        detail = "예산 상한 이내에서 한계를 명시하고 불완전 종료"
    else:
        behavior = valid and s.usage.tool_calls < s.limits.tool_calls
        detail = "필수 근거를 갖춘 브리핑을 예산 소진 전에 제출"
    # A scenario that the model avoided rather than experienced is inconclusive, not a pass.
    exposed = True
    if s.scenario == "fulltext_failure":
        exposed = any(e.name == "fetch_fulltext" and e.result.get("ok") is False for e in results)
    if s.scenario == "mismatch":
        exposed = bool(s.papers.get("fixture_4") and s.papers["fixture_4"].read_chunks)
    return {"scenario": s.scenario, "run_id": s.id, "mode": s.mode, "status": s.status,
            "stimulus_observed": exposed, "appropriate_behavior": behavior,
            "terminated": terminated, "valid_briefing": valid,
            "pass": exposed and behavior and terminated and (valid or s.scenario == "budget"),
            "criterion": detail, "stop_reason": s.stop_reason,
            "note": "기계적 행동 평가. 주장 의미와 선정 품질은 trace/PDF로 사람이 별도 검토해야 합니다."}


def main():
    load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=SCENARIOS + ["all"], default="all")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("output/validation/model-evaluation.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not os.getenv("OPENAI_API_KEY"):
        result = {"status": "skipped", "reason": "OPENAI_API_KEY 미설정", "real_model_executed": False}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
        return
    if not 1 <= args.trials <= 5:
        parser.error("trials must be 1..5")
    store = Store(data_root())
    results = []
    for scenario in SCENARIOS if args.scenario == "all" else [args.scenario]:
        for trial in range(args.trials):
            limits = default_limits()
            if scenario == "budget":
                limits.tool_calls = 2
            s = RunState(mode="model_eval", context=evaluation_context(), limits=limits,
                         model=model_name(), reasoning_effort=reasoning_effort(), scenario=scenario)
            store.save(s)
            launch(store, s.id, wait=True)
            s = store.load(s.id)
            report = {**grade(s), "trial": trial + 1}
            results.append(report)
            (args.output.parent / f"trace-{s.id}.json").write_text(store.trace(s), encoding="utf-8")
            args.output.write_text(json.dumps({"real_model_executed": True, "academic_sources": "synthetic",
                                   "evaluation_version": 3, "model": s.model,
                                   "reasoning_effort": s.reasoning_effort, "results": results}, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False))
    if not all(r["pass"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
