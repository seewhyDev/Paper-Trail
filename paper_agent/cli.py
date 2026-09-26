import argparse
import json
from pathlib import Path

from .config import data_root, default_limits, load_config, model_name, reasoning_effort
from .demo import DEMO_QUESTION, SCENARIOS
from .schema import Context, RunState
from .store import Store
from .worker import launch


def main():
    load_config()
    p = argparse.ArgumentParser(description="Paper Trail local research agent")
    p.add_argument("mode", choices=["demo", "live"])
    p.add_argument("--question", default=DEMO_QUESTION)
    p.add_argument("--papers", type=int, choices=range(1, 6), default=3, help="최종 추천 편수 (1~5, 기본 3)")
    p.add_argument("--scenario", choices=SCENARIOS, default="sufficient")
    p.add_argument("--root", type=Path)
    p.add_argument("--export", type=Path, help="Export public trace and PDF to this directory")
    args = p.parse_args()
    limits = default_limits()
    limits.target = args.papers
    if args.mode == "demo" and args.scenario == "budget":
        limits.tool_calls = 2
    s = RunState(mode=args.mode, context=Context(question=args.question), limits=limits,
                 model=model_name() if args.mode == "live" else "scripted-replay (not LLM)",
                 reasoning_effort=reasoning_effort() if args.mode == "live" else None, scenario=args.scenario,
                 require_target=args.mode == "live", require_screening=True, require_depth=args.mode == "live")
    store = Store(args.root or data_root())
    store.save(s)
    launch(store, s.id, wait=True)
    s = store.load(s.id)
    directory = store.directory(s.id)
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)
        (args.export / "trace.json").write_text(store.trace(s), encoding="utf-8")
        if (directory / "briefing.pdf").exists():
            (args.export / "briefing.pdf").write_bytes((directory / "briefing.pdf").read_bytes())
    print(json.dumps({"run": s.id, "mode": s.mode, "status": s.status, "reason": s.stop_reason,
                      "model_calls": s.usage.model_calls, "tool_calls": s.usage.tool_calls,
                      "pdf": str(directory / "briefing.pdf"), "pdf_error": s.pdf_error}, ensure_ascii=False, indent=2))
    if s.status == "waiting":
        print("추가 질문:", s.pending_question, "— UI에서 저장된 실행을 열어 답변하세요.")
    if s.status != "completed" or s.pdf_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
