import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from paper_agent.pdf import render_pdf
from paper_agent.provider import OpenAIProvider


def test_pdf_korean_links_and_bounds(completed, tmp_path):
    path = render_pdf(completed, tmp_path / "example.pdf")
    doc = fitz.open(path)
    text = "".join(p.get_text() for p in doc)
    assert "합성" in text and "핵심 방법" in text and "SYNTHETIC" in text
    assert "\ufffd" not in text
    assert any(p.get_links() for p in doc)
    assert not any(link["kind"] == fitz.LINK_GOTO for p in doc for link in p.get_links())
    assert any(doc.extract_font(f[0])[3] for p in doc for f in p.get_fonts())
    for p in doc:
        for block in p.get_text("blocks"):
            assert p.rect.contains(fitz.Rect(block[:4]))


def test_incomplete_report_does_not_fake_recommendations(state, tmp_path):
    state.status, state.stop_reason = "incomplete", "검색 예산 소진"
    doc = fitz.open(render_pdf(state, tmp_path / "partial.pdf"))
    assert "검증된 최종 추천 없음" in "".join(p.get_text() for p in doc)


def test_downloaded_pdf_extraction_preserves_real_page_locations(completed, tmp_path):
    from paper_agent.sources import extract_document
    pdf = render_pdf(completed, tmp_path / "source.pdf")
    chunks, note = extract_document(pdf.read_bytes(), "https://arxiv.org/pdf/fixture", "pdf")
    assert any("PDF p.2" in c.location for c in chunks)
    assert "연구" in "".join(c.text for c in chunks)


@pytest.mark.parametrize("effort", [None, "low"])
def test_provider_uses_responses_and_preserves_all_calls_no_reasoning_display(effort):
    captured = {}
    class Item(SimpleNamespace):
        def model_dump(self, **kwargs):
            return vars(self).copy()
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output=[Item(type="reasoning", summary=["private"], encrypted_content="opaque"),
                  Item(type="function_call", call_id="a", name="x", arguments="{}"),
                  Item(type="function_call", call_id="b", name="y", arguments="{}")],
                  usage=SimpleNamespace(input_tokens=20, output_tokens=10))
    p = OpenAIProvider("configured-model", client=SimpleNamespace(responses=SimpleNamespace(create=create)), reasoning_effort=effort)
    turn = p.respond([{"role": "user", "content": "test"}], [], 500, 10)
    assert [c.id for c in turn.calls] == ["a", "b"]
    assert turn.items[0]["summary"] == [] and turn.items[0]["encrypted_content"] == "opaque"
    assert captured["model"] == "configured-model" and captured["store"] is False
    assert turn.input_tokens == 20 and turn.output_tokens == 10
    assert captured.get("reasoning") == ({"effort": effort} if effort else None)


def test_ui_load_and_rerun_never_launches(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_AGENT_DATA", str(tmp_path / "ui"))
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=15).run()
    assert not app.exception
    assert "어떤 연구" in app.title[0].value
    app.run()
    assert not app.exception
    assert not list((tmp_path / "ui").glob("*/state.json"))


def test_completed_ui_has_no_magic_object_dump(completed, store, monkeypatch):
    monkeypatch.setenv("PAPER_AGENT_DATA", str(store.root))
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=15).run()
    assert not app.exception
    assert len(app.tabs) == 2
    assert [tab.label for tab in app.tabs] == ["추천 논문", "전체 후보 평가"]
    assert not app.get("json") and not app.get("metric") and not app.number_input
    visible = " ".join(str(item.value) for kind in ("title", "subheader", "caption", "markdown", "text") for item in app.get(kind))
    for internal in (completed.id, completed.model, "API 보고", "예산 계상", "model_request", "fixture_1", "실행 ID"):
        assert internal not in visible
    assert not app.get("doc_string")
    assert app.query_params['run'] == [completed.id]
    assert not any('role="status"' in item.value for item in app.markdown)
    for removed in ('함께 읽으면 보이는 차이', '먼저 읽을 부분', '출처와 인용 확인'):
        assert removed not in visible
    before = store.load(completed.id).usage.model_dump()
    app.run()
    assert not app.exception and store.load(completed.id).usage.model_dump() == before


def test_pdf_contains_only_selected_papers(completed, tmp_path):
    completed.context.question = "PRIVATE_CONTEXT_CANARY"
    completed.goal = "PRIVATE_GOAL_CANARY"
    completed.criteria = ["PRIVATE_CRITERIA_CANARY"]
    completed.briefing.scope = "INTERNAL_SCOPE_CANARY"
    completed.stop_reason = "INTERNAL_STOP_CANARY"
    other = next(iter(completed.papers.values())).model_copy(deep=True)
    other.id, other.title, other.verdict = "other", "UNSELECTED_PAPER_CANARY", "exclude"
    completed.papers[other.id] = other
    doc = fitz.open(render_pdf(completed, tmp_path / "selected.pdf"))
    text = "".join(p.get_text() for p in doc)
    for private in ("PRIVATE_", "INTERNAL_", "UNSELECTED_", "연구 맥락", "선정 기준", "실행 기록", "보고된 토큰", "fixture_", completed.id):
        assert private not in text
    for removed in ("추천 논문 브리핑", "함께 읽으면 보이는 차이", "먼저 읽을 부분", "출처와 인용"):
        assert removed not in text
    for item in completed.briefing.papers:
        assert completed.papers[item.paper_id].title in text
    assert "핵심 방법" in text and "주요 결과" in text and "출처와 인용" not in text


def test_pdf_preserves_greek_hyperparameters(completed, tmp_path):
    completed.briefing.papers[0].method.text += " Mixing α=0.5, trade-off λ=0.3."
    doc = fitz.open(render_pdf(completed, tmp_path / "symbols.pdf"))
    text = "".join(page.get_text() for page in doc)
    assert "α=0.5" in text and "λ=0.3" in text and "\x00" not in text


def test_saved_legacy_pdf_is_upgraded_without_model_calls(completed, tmp_path, monkeypatch):
    import paper_agent.pdf as pdf_module
    path = tmp_path / "briefing.pdf"
    path.write_bytes(b"legacy layout")
    before = completed.usage.model_dump()
    pdf_module.ensure_pdf(completed, path)
    assert path.read_bytes().startswith(b"%PDF")
    assert path.with_suffix(".layout").read_text() == pdf_module.PDF_LAYOUT_VERSION
    monkeypatch.setattr(pdf_module, "_render_pdf", lambda *args: pytest.fail("unchanged PDF regenerated"))
    pdf_module.ensure_pdf(completed, path)
    assert completed.usage.model_dump() == before
