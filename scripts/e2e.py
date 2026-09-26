"""Real model + real academic APIs. Paid; runs only if a server key is present."""
import argparse
import json
import os
from pathlib import Path

from paper_agent.config import data_root, default_limits, load_config, model_name, reasoning_effort
from paper_agent.schema import Context, RunState
from paper_agent.store import Store
from paper_agent.tools import validate_briefing
from paper_agent.worker import launch


def main():
    load_config()
    p = argparse.ArgumentParser()
    p.add_argument("--question", default="적은 라벨을 이용한 문서 분류 연구를 시작합니다. 공개 원문에서 방법과 실험 조건 및 한계를 확인하고 서로 다른 접근 약 3편을 비교해 주세요.")
    p.add_argument("--papers", type=int, choices=range(1, 6), default=3)
    args = p.parse_args()
    out = Path("output/validation/e2e.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not os.getenv("OPENAI_API_KEY"):
        result = {"status": "skipped", "reason": "OPENAI_API_KEY 미설정", "real_model_executed": False, "real_sources_executed": False}
    else:
        s = RunState(mode="live", context=Context(question=args.question), limits=default_limits(), model=model_name(), reasoning_effort=reasoning_effort(), require_target=True, require_screening=True, require_depth=True)
        s.limits.target = args.papers
        store = Store(data_root())
        store.save(s)
        launch(store, s.id, wait=True)
        s = store.load(s.id)
        result = {"status": s.status, "run_id": s.id, "model": s.model, "reasoning_effort": s.reasoning_effort,
                  "real_model_executed": s.usage.model_calls > 0,
                  "real_sources_executed": s.usage.searches > 0, "stop_reason": s.stop_reason,
                  "verified": bool(s.briefing and not validate_briefing(s, s.briefing)), "pdf_error": s.pdf_error,
                  "usage": s.usage.model_dump()}
        (out.parent / f"e2e-trace-{s.id}.json").write_text(store.trace(s), encoding="utf-8")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] not in ("skipped", "completed") or result.get("pdf_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
