# 학술 소스와 공식 문서

> 실행 로그·PDF 등 `output/` 산출물은 개인 연구 기록 보호를 위해 저장소에 포함하지 않습니다. 아래 경로는 개발 당시 로컬 기록의 위치이며, 직접 실행하면 자신의 결과를 생성할 수 있습니다.

확인일: 2026-09-25. 아래 소스만 앱에서 직접 사용합니다. 모델의 내장 웹 검색이나 Codex 도구에 의존하지 않습니다.

| 소스 | 키 | 분야·자료 | 이 앱의 원문 경로 | 주요 한계 |
|---|---|---|---|---|
| Crossref REST | 이 구현의 공개 메타데이터 조회에는 불필요 | 여러 분야의 DOI 메타데이터, 저널 논문·책 장 등 | 직접 원문 확보하지 않음; 다른 저장소 검색으로 연결 가능 | 초록·원문 링크가 없을 수 있음; 동명이거나 부정확한 메타데이터 |
| arXiv API | 이 구현에서는 불필요 | 물리·수학·컴퓨터과학·통계 등 프리프린트 | 공개 HTML 우선, 모델이 PDF 대체 경로 선택 | 모든 분야를 포괄하지 않음, 심사 전 연구 포함, HTML 미제공 논문 |
| Europe PMC REST | 이 구현의 공개 API에는 불필요 | 생명과학·의생명과학 자료 | 공개 접근 가능한 PMCID의 JATS XML | PMC에 있어도 공개 재사용 본문이 제공되지 않는 논문 존재 |

Crossref는 DOI 메타데이터 검색의 범용 출발점으로 선택했습니다. `query.bibliographic`, `rows`, `offset`, `/works/{doi}`를 사용하며 선택적 연락처를 `mailto`로 보냅니다. 전체 본문 서비스라는 가정은 하지 않습니다. [Crossref 공식 REST 문서](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).

arXiv의 legacy API는 3초당 최대 한 요청과 단일 연결 조건을 명시합니다. 앱은 3.1초 간격, 파일 잠금 기반 단일 연결, 제한된 재시도를 적용합니다. API 검색/ID 조회와 HTML/PDF 경로를 구분합니다. [arXiv API User Manual](https://info.arxiv.org/help/api/user-manual.html), [arXiv API 이용 조건](https://info.arxiv.org/help/api/tou.html).

Europe PMC에서는 `search?resultType=core&format=json`으로 초록과 식별자를 받고 `/{PMCID}/fullTextXML`로 공개 본문을 조회합니다. 문서에 명시된 수치형 보장 quota를 가정하지 않고 앱 자체에서 1초 간격을 둡니다. HTTP 429와 Retry-After를 처리하며 긴 대기 요구에는 해당 조회를 중단합니다. [Europe PMC 공식 REST 안내](https://europepmc.org/RestfulWebService), [공식 개발자 자료](https://europepmc.org/developers).

## 접근과 품질 제한

- 학술 API가 403·404·429·5xx를 반환하는 것은 도구의 관측입니다. 모델은 남은 예산 내에서 검색어/소스/후보를 바꿀 수 있습니다.
- 임의 출판사 URL을 모델이 전달해 다운로드하는 도구는 없습니다. 허용된 HTTPS 호스트와 생성된 저장소 경로만 사용하며 리다이렉트도 검사합니다.
- 유료 접근·로그인·CAPTCHA 우회는 없습니다. Crossref의 링크만 보고 원문을 읽었다고 표시하지 않습니다.
- 원문 확보, 청크 추출, 실제 모델에 반환한 열람 구간을 구분합니다. 마지막 단계만 실제 검토 범위입니다.
- 식별자, DOI, 제목으로 중복을 병합하고 보조 식별자는 검색 키로 보존합니다. 제목만 같은 별개 논문이 합쳐지거나 제목이 크게 바뀐 판본이 남는 경우는 있을 수 있습니다. DOI 일치가 가장 강한 단서입니다.
- 원문 다운로드는 개인 연구용 로컬 캐시입니다. 공개 배포나 재호스팅을 허용한다고 간주하지 않습니다. 원문별 이용 허락을 확인해야 합니다.
- HTML/JATS는 구조화된 절 이름을 활용하고 PDF는 페이지 단위 텍스트를 추출합니다. 스캔 PDF는 OCR하지 않습니다.
- 학술 검색 결과의 순위를 최종 추천 순위로 그대로 쓰지 않습니다. 최종 추천은 실제 원문 근거와 사용자 기준을 보고 모델이 판단합니다.

실제 네트워크 검사는 source-smoke.json (`output/validation/source-smoke.json`, 로컬 산출물)에 질의, 제목, 식별자, 원문 경로, 추출 범위를 기록했습니다. 이 검사 스크립트의 HTML→PDF fallback은 파서 검증용 고정 워크플로입니다. 앱의 에이전트가 그 결정을 했다는 뜻은 아닙니다.
