"""Deterministic PDF renderer: no model calls, escaped text, embedded Korean font."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from filelock import FileLock

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase import _glyphlist
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                               PageBreak)

from .schema import RunState
from .tools import validate_briefing


def font_path():
    candidates = [os.getenv("PAPER_AGENT_FONT", ""),
                  str(Path(__file__).resolve().parent.parent / "assets/fonts/NanumGothic-Regular.ttf"),
                  "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
                  "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                  "C:/Windows/Fonts/malgun.ttf"]
    for value in candidates:
        if value and Path(value).is_file():
            return value
    raise RuntimeError("한글 TTF 폰트가 없습니다. PAPER_AGENT_FONT에 NanumGothic.ttf 등의 경로를 설정하세요.")


def safe_link(url: str) -> str | None:
    try:
        u = urlsplit(url)
        return url if u.scheme == "https" and u.hostname and not u.username and not u.password else None
    except ValueError:
        return None


PDF_LAYOUT_VERSION = "detailed-papers-v4.1"


def ensure_pdf(state: RunState, output: Path, *, force=False) -> Path:
    """Refresh older saved PDFs on download without another model/API call."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    version = output.with_suffix(".layout")
    with FileLock(str(output) + ".lock", timeout=10):
        if not force and output.exists() and version.exists() and version.read_text() == PDF_LAYOUT_VERSION:
            return output
        _render_pdf(state, output)
        version.write_text(PDF_LAYOUT_VERSION)
    return output


def render_pdf(state: RunState, output: Path) -> Path:
    return ensure_pdf(state, output, force=True)


def section_names(paper, chunk_ids):
    return list(dict.fromkeys(paper.chunks[c].location.split(" / 문자")[0] for c in chunk_ids))


def _render_pdf(state: RunState, output: Path) -> Path:
    if state.briefing:
        errors = validate_briefing(state, state.briefing)
        if errors:
            raise ValueError("브리핑 재검증 실패: " + "; ".join(errors))
    if "Korean" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Korean", font_path()))
    styles = getSampleStyleSheet()
    for name, size, leading, color in [("Body", 9, 14, "#243247"), ("Small", 7.6, 11, "#526177"),
                                       ("TitleK", 25, 34, "#102F38"), ("H1K", 16, 23, "#102F38"),
                                       ("H2K", 10.5, 16, "#087F78")]:
        styles.add(ParagraphStyle(name=name, fontName="Korean", fontSize=size, leading=leading,
                                  textColor=colors.HexColor(color), spaceAfter=8, wordWrap="CJK",
                                  alignment=TA_LEFT, splitLongWords=True,
                                  keepWithNext=name in {"H1K", "H2K"}))
    story = []
    def p(text, style="Body"):
        # Nanum Gothic lacks some Greek variables. Use the standard Symbol font rather
        # than silently dropping scientific symbols in methods and results.
        primary = pdfmetrics.getFont("Korean").face.charToGlyph
        fallback = {_glyphlist._glyphname2unicode.get(glyph)
                    for glyph in pdfmetrics.getFont("Symbol").encoding.vector if glyph}
        parts = []
        for char in str(text):
            escaped = escape(char)
            if char == "\n":
                parts.append("<br/>")
            elif ord(char) not in primary and ord(char) in fallback:
                parts.append(f'<font name="Symbol">{escaped}</font>')
            else:
                parts.append(escaped)
        return Paragraph("".join(parts), styles[style])
    def add(text, style="Body"):
        story.append(p(text, style))
    def link(url, label):
        clean = safe_link(url)
        return f'<link href={quoteattr(clean)} color="#087F78">{escape(label)}</link>' if clean else escape(label)

    b = state.briefing
    fields = [("problem", "다루는 문제"), ("method", "핵심 방법"),
              ("results", "주요 결과"), ("limitations", "한계")]
    if b:
        briefs = {item.paper_id: item for item in b.papers}
        for i, pid in enumerate(b.reading_order, 1):
            brief, paper = briefs[pid], state.papers[pid]
            if i > 1:
                story.append(PageBreak())
            add(f"PAPER {i:02}", "Small")
            if state.mode != "live":
                add("합성 자료 예시 · 실제 학술 논문에 대한 추천이 아닙니다.", "Small")
            add(paper.title, "H1K")
            add(f"{'; '.join(paper.authors)} · {paper.year or '연도 미확인'}", "Small")
            story.append(Paragraph(link(paper.url, "논문 페이지 열기"), styles["Small"]))
            story.append(Spacer(1, 10))
            for field, label in fields:
                add("한계와 해석" if field == "limitations" else label, "H2K")
                add(getattr(brief, field).text)
    else:
        add("검증된 최종 추천 없음", "H1K")
        add("원문 근거를 확인한 선정 논문이 아직 없어 브리핑을 제공할 수 없습니다.")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Korean", 7)
        canvas.setFillColor(colors.HexColor("#526177"))
        canvas.drawString(52, 28, "SYNTHETIC DATA / 예시 자료" if state.mode != "live" else "PAPER TRAIL")
        canvas.drawRightString(A4[0] - 52, 28, f"{doc.page}")
        canvas.restoreState()
    temp = output.with_suffix(".tmp.pdf")
    SimpleDocTemplate(str(temp), pagesize=A4, rightMargin=52, leftMargin=52, topMargin=46,
                      bottomMargin=46, title="논문별 상세 검토", author="Paper Trail",
                      pageCompression=1).build(story, onFirstPage=footer, onLaterPages=footer)
    os.replace(temp, output)
    return output
