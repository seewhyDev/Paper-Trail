"""Save repeatable scripted plumbing evidence, explicitly separate from model evals."""
import json
from pathlib import Path

from paper_agent.agent import Agent
from paper_agent.demo import DEMO_QUESTION, FixtureSources, ReplayProvider, SCENARIOS
from paper_agent.evaluation import grade
from paper_agent.schema import Context, RunState
from paper_agent.store import Store


def main():
    store = Store(Path("tmp/scenario-runs"))
    output = Path("output/validation/scripted")
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for scenario in SCENARIOS:
        s = RunState(mode="demo", context=Context(question=DEMO_QUESTION), model="scripted-replay (not LLM)", scenario=scenario)
        if scenario == "budget":
            s.limits.tool_calls = 2
        Agent(s, ReplayProvider(s), FixtureSources(s), store).run()
        report = grade(s)
        reports.append(report)
        (output / f"{scenario}-trace.json").write_text(store.trace(s), encoding="utf-8")
    report = {"real_model_executed": False, "real_sources_executed": False,
              "classification": "scripted loop/tool plumbing tests; not autonomy evaluation", "results": reports}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"scripted_scenarios": len(reports), "passed": sum(x["pass"] for x in reports), "real_model_executed": False}))


if __name__ == "__main__":
    main()
