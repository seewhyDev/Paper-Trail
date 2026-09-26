import io
import json
import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from pypdf import PdfReader

from .network import Network, SourceError
from .schema import Chunk, Paper

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ATOM = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}


def clean(text):
    return " ".join((text or "").split())


def plain(text):
    return clean(BeautifulSoup(text or "", "html.parser").get_text(" "))


def arxiv_papers(data: bytes) -> list[Paper]:
    root = ET.fromstring(data)
    result = []
    for e in root.findall("a:entry", ATOM):
        url = e.findtext("a:id", default="", namespaces=ATOM)
        aid = url.split("/abs/")[-1]
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", aid):
            continue
        base_id = re.sub(r"v\d+$", "", aid)
        title = clean(e.findtext("a:title", default="", namespaces=ATOM))
        result.append(Paper(title=title, source="arxiv", source_id=aid,
                            authors=[clean(a.findtext("a:name", namespaces=ATOM)) for a in e.findall("a:author", ATOM)],
                            year=int(e.findtext("a:published", namespaces=ATOM)[:4]),
                            doi=e.findtext("ar:doi", namespaces=ATOM), identifiers={"arxiv": base_id},
                            url="https://arxiv.org/abs/" + aid,
                            fulltext_urls=["https://arxiv.org/html/" + aid, "https://arxiv.org/pdf/" + aid],
                            abstract=clean(e.findtext("a:summary", default="", namespaces=ATOM))))
    return result


def epmc_papers(data: bytes) -> list[Paper]:
    payload = json.loads(data)
    result = []
    for e in payload.get("resultList", {}).get("result", []):
        source, sid = e.get("source", "MED"), e["id"]
        pmcid = e.get("pmcid")
        identifiers = {"epmc": f"{source}:{sid}"}
        if pmcid:
            identifiers["pmcid"] = pmcid
        if source == "MED":
            identifiers["pmid"] = sid
        authors = [a.get("fullName", "") for a in e.get("authorList", {}).get("author", [])]
        result.append(Paper(title=plain(e.get("title", sid)), source="europepmc", source_id=f"{source}:{sid}",
                            authors=authors or [e.get("authorString", "미확인")],
                            year=int(e["pubYear"]) if str(e.get("pubYear", "")).isdigit() else None,
                            doi=e.get("doi"), identifiers=identifiers,
                            url=f"https://europepmc.org/article/{source}/{sid}",
                            fulltext_urls=[f"{EPMC}/{pmcid}/fullTextXML"] if pmcid and e.get("isOpenAccess") == "Y" else [],
                            abstract=plain(e.get("abstractText", ""))))
    return result


def crossref_paper(e) -> Paper:
    dates = e.get("published", {}).get("date-parts", [[]])
    doi = e["DOI"]
    return Paper(title=plain((e.get("title") or [doi])[0]), source="crossref", source_id=doi,
                 authors=[clean(a.get("given", "") + " " + a.get("family", a.get("name", ""))) for a in e.get("author", [])],
                 year=dates[0][0] if dates and dates[0] else None, doi=doi, identifiers={"doi": doi.lower()},
                 url="https://doi.org/" + doi, abstract=plain(e.get("abstract", "")))


def chunks_from_sections(sections: list[tuple[str, str]], url: str) -> tuple[list[Chunk], str]:
    chunks = []
    truncated = False
    # Combine adjacent paragraphs within a section so short labels do not consume
    # the chunk cap before a paper's results/limitations become available.
    grouped = []
    for location, text in sections:
        text = clean(text)
        if not text:
            continue
        if grouped and grouped[-1][0] == location:
            grouped[-1] = (location, grouped[-1][1] + " " + text)
        else:
            grouped.append((location, text))
    for location, text in grouped:
        text = clean(text)
        for start in range(0, len(text), 3200):
            if len(chunks) >= 100:
                truncated = True
                break
            chunks.append(Chunk(id=f"c{len(chunks) + 1:03}", location=f"{location} / 문자 {start + 1}-{min(start + 3200, len(text))}",
                                text=text[start:start + 3200], source_url=url))
        if truncated:
            break
    if not chunks or sum(len(c.text) for c in chunks) < 100:
        raise SourceError("본문 텍스트가 부족합니다. 스캔본/OCR 또는 접근 제한일 수 있습니다.")
    return chunks, ("추출 상한 100개 청크로 뒷부분 생략" if truncated else "텍스트 추출 완료; 표·수식·이미지의 완전한 해석은 지원하지 않음")


def extract_document(data: bytes, url: str, route: str) -> tuple[list[Chunk], str]:
    if data.startswith(b"%PDF"):
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise SourceError("암호화된 PDF는 처리하지 않습니다.")
        sections = [(f"PDF p.{i + 1}", p.extract_text() or "") for i, p in enumerate(reader.pages[:120])]
        chunks, note = chunks_from_sections(sections, url)
        if len(reader.pages) > 120:
            note += "; 120페이지까지만 추출"
        return chunks, note
    if route == "xml":
        root = ET.fromstring(data)
        body = root.find("body")
        if body is None:
            raise SourceError("공개 JATS 본문이 없습니다.")
        sections = []
        def walk(node, heading):
            title = node.find("title")
            if title is not None:
                heading = heading + " / " + clean(" ".join(title.itertext()))
            for child in node:
                if child.tag == "sec":
                    walk(child, heading)
                elif child.tag not in ("title", "label"):
                    sections.append((heading, " ".join(child.itertext())))
        walk(body, "본문")
        return chunks_from_sections(sections, url)
    soup = BeautifulSoup(data, "html.parser")
    article = soup.select_one(".ltx_document")
    if article is None:
        raise SourceError("arXiv HTML 본문 없음. PDF 경로를 시도할 수 있습니다.")
    for tag in article.select("script, style, nav, .ltx_bibliography"):
        tag.decompose()
    sections, heading = [], "본문"
    for tag in article.find_all(["h1", "h2", "h3", "h4", "p"]):
        if tag.name.startswith("h"):
            heading = tag.get_text(" ", strip=True)
        elif not tag.find_parent(class_="ltx_abstract"):
            sections.append((heading, tag.get_text(" ", strip=True)))
    return chunks_from_sections(sections, url)


class AcademicSources:
    def __init__(self, network: Network):
        self.net = network

    def search(self, source: str, query: str, limit: int, offset: int = 0) -> list[Paper]:
        if source == "arxiv":
            data, _ = self.net.get("https://export.arxiv.org/api/query", params={"search_query": query, "start": offset,
                                 "max_results": limit, "sortBy": "relevance", "sortOrder": "descending"})
            return arxiv_papers(data)
        if source == "europepmc":
            # Page-number pagination; exact count/offset is in the search log.
            data, _ = self.net.get(EPMC + "/search", params={"query": query, "format": "json", "resultType": "core",
                                 "pageSize": limit, "page": offset // limit + 1})
            return epmc_papers(data)
        params = {"query.bibliographic": query, "rows": limit, "offset": offset}
        if os.getenv("PAPER_AGENT_CONTACT"):
            params["mailto"] = os.environ["PAPER_AGENT_CONTACT"]
        data, _ = self.net.get("https://api.crossref.org/works", params=params)
        return [crossref_paper(e) for e in json.loads(data)["message"]["items"]]

    def details(self, p: Paper) -> Paper:
        if p.source == "arxiv":
            data, _ = self.net.get("https://export.arxiv.org/api/query", params={"id_list": p.source_id})
            papers = arxiv_papers(data)
        elif p.source == "europepmc":
            source, sid = p.source_id.split(":", 1)
            papers = self.search("europepmc", f"EXT_ID:{sid} AND SRC:{source}", 1)
        else:
            data, _ = self.net.get("https://api.crossref.org/works/" + quote(p.source_id, safe=""))
            papers = [crossref_paper(json.loads(data)["message"])]
        if not papers:
            raise SourceError("상세 메타데이터를 찾지 못했습니다.")
        return papers[0]

    def fulltext(self, p: Paper, route: str) -> tuple[list[Chunk], str]:
        aid = p.identifiers.get("arxiv")
        pmcid = p.identifiers.get("pmcid")
        if route in ("auto", "html") and aid:
            # An auto request tries one preferred path. The model chooses any fallback.
            url, kind = f"https://arxiv.org/html/{p.source_id if p.source == 'arxiv' else aid}", "html"
        elif route == "pdf" and aid:
            url, kind = f"https://arxiv.org/pdf/{p.source_id if p.source == 'arxiv' else aid}", "pdf"
        elif route in ("auto", "xml") and pmcid:
            url, kind = f"{EPMC}/{pmcid}/fullTextXML", "xml"
        else:
            raise SourceError("이 경로의 공개 원문 식별자가 없습니다. DOI로 Europe PMC/arXiv를 검색하거나 다른 후보를 선택하세요.")
        if not re.fullmatch(r"PMC\d+", pmcid or "PMC0"):
            raise SourceError("원문 식별자 오류")
        data, final_url = self.net.get(url)
        try:
            return extract_document(data, final_url, kind)
        except SourceError:
            raise
        except Exception:
            raise SourceError("원문 파싱 실패. 다른 경로/후보를 검토하세요.") from None
