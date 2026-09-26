"""Render every PDF page and check Korean text, bounds, fonts and links."""
import argparse
import json
from pathlib import Path

import fitz


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tmp/pdfs"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(args.pdf)
    text = "".join(page.get_text() for page in doc)
    out_of_bounds, links, internal = [], 0, 0
    for i, page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).save(args.output / f"page-{i+1:02}.png")
        for link in page.get_links():
            links += link["kind"] == fitz.LINK_URI
            internal += link["kind"] == fitz.LINK_GOTO
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    rect = fitz.Rect(span["bbox"])
                    if not page.rect.contains(rect):
                        out_of_bounds.append({"page": i+1, "text": span["text"][:80]})
    report = {"pages": len(doc), "korean_text_present": "논문" in text and ("핵심 방법" in text or "최종 추천" in text),
              "replacement_glyphs": text.count("\ufffd") + text.count("\x00"), "external_links": links,
              "internal_links": internal, "out_of_bounds": out_of_bounds,
              "font_embedded": any(doc.extract_font(f[0])[3] for page in doc for f in page.get_fonts()),
              "rendered_by": f"PyMuPDF {fitz.VersionBind}", "visual_review": "PNG inspection required separately"}
    (args.output / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["korean_text_present"] or out_of_bounds or report["replacement_glyphs"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
