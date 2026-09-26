"""Academic network integration only; never calls a model."""
import json
from datetime import datetime, timezone
from pathlib import Path

from paper_agent.config import load_config
from paper_agent.network import Network
from paper_agent.sources import AcademicSources


def main():
    load_config()
    net = Network(timeout=20, retries=1, rate_dir=Path("data"))
    sources = AcademicSources(net)
    report = {"time": datetime.now(timezone.utc).isoformat(), "model_called": False, "checks": []}
    for source, query in [("crossref", "classroom formative assessment"), ("arxiv", 'ti:"Attention Is All You Need"'),
                          ("europepmc", "TITLE:CRISPR AND OPEN_ACCESS:Y")]:
        row = {"source": source, "query": query}
        try:
            papers = sources.search(source, query, 2)
            if not papers:
                raise ValueError("no_results")
            paper = papers[0]
            detail = sources.details(paper)
            row.update(status="metadata_ok", title=detail.title, identifiers=detail.identifiers, doi=detail.doi, url=detail.url,
                       abstract_chars=len(detail.abstract))
            if source in ("arxiv", "europepmc"):
                failures = []
                for route in (["html", "pdf"] if source == "arxiv" else ["xml"]):
                    try:
                        chunks, note = sources.fulltext(detail, route)
                        row.update(status="fulltext_ok", route=route, chunks=len(chunks), location=chunks[0].location,
                                   source_url=chunks[0].source_url, extraction_note=note)
                        break
                    except Exception as e:
                        failures.append({"route": route, "error_type": type(e).__name__, "error": str(e)[:250]})
                row["fulltext_failures"] = failures
        except Exception as e:
            row.update(status="failed", error_type=type(e).__name__, error=str(e)[:250])
        report["checks"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    net.close()
    path = Path("output/validation/source-smoke.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    expected = {"crossref": "metadata_ok", "arxiv": "fulltext_ok", "europepmc": "fulltext_ok"}
    if any(row["status"] != expected[row["source"]] for row in report["checks"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
