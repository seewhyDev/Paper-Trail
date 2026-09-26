# 실제 검증 결과

> 실행 로그·PDF 등 `output/` 산출물은 개인 연구 기록 보호를 위해 저장소에 포함하지 않습니다. 아래 경로는 개발 당시 로컬 기록의 위치이며, 직접 실행하면 자신의 결과를 생성할 수 있습니다.

검증일: 2026-09-25. 환경: macOS ARM64, Python 3.11.11. 정확한 직접 의존성 버전은 [requirements-tested.txt](../requirements-tested.txt)에 기록했습니다.

## 완료 중심 총 토큰 정책

2026-09-26, **129개 테스트 통과**. [토큰 정책 회귀 테스트](../tests/test_adaptive_tokens.py)는 합성 사용량이 누적 50만·100만 토큰을 넘어도 후보 4편 브리핑을 완료하는 경우, 실제 사용량 정산, 실패 요청의 예약량 유지, 고정 예산의 요청 전 차단, 재개 버튼과 실제 실행의 동일한 예산 검사, 이전 상태의 자료·초안·사용량 보존을 검증했습니다. 결과 XML은 `output/validation/pytest-adaptive-tokens.xml`(로컬 산출물)입니다.

실제 4편 요청에서 초안 3편을 저장하고 멈춘 기록은 복사본으로 재개 검증했습니다. `MAX_TOKENS=auto` 적용 시 다음 요청의 출력 여유가 6,500으로 확보되며 기존 자료·초안·누적 사용량이 유지됩니다. 원본 실행은 변경하거나 유료 재개하지 않았습니다. 실제 네 번째 논문의 완성까지 검증한 것은 아닙니다. 총 토큰 자동 모드는 API 비용 상한을 제공하지 않으며, 시간·도구·반복 감지와 모델 자체의 컨텍스트 한도는 유지됩니다.

## 완료 중심 호출 정책

2026-09-26, **121개 테스트 통과**(pytest 결과 (`output/validation/pytest-adaptive-calls.xml`, 로컬 산출물)). [회귀 테스트](../tests/test_adaptive_calls.py)는 24회 이후 합성 후보 4편 비교·브리핑·PDF 생성, 30번의 새 본문 열람 후 정상 제출, 진전 없는 호출의 복구 지시·중단, 프로세스 재시작 시 반복 감지 유지, 기존 실행 재개의 자료·사용량 보존, 다른 한도 소진 시 UI 재개 버튼 숨김을 검증했습니다. 기존 SWIG 경고 5개가 남아 있습니다.

실제 4편 요청에서 24회로 멈춘 저장 기록은 메모리 복사본으로만 재개 검증했습니다. 현재 `auto` 정책을 적용하면 기존 초안 2편·자료·사용량을 유지한 채 `ready`가 됩니다. 실제 API 호출이나 원본 실행 상태 변경은 하지 않았으며, 해당 4편 실제 브리핑의 완성까지 검증한 것은 아닙니다. 모델 호출 상한은 기본 해제했지만 총 토큰·시간·도구 등 다른 한도는 유지됩니다.

## 추천 편수·원문 검토·상세 브리핑 개선

2026-09-26, 기존 실제 KV-cache 후보 10편과 저장 원문을 재사용했습니다. 모델(`gpt-5.4-mini`, low)·총 토큰/호출 한도는 유지했으며, 새 검색의 성공률을 측정한 실험은 아닙니다.

| 항목 | 결과 | 증거 |
|---|---|---|
| 자동 테스트 | **109 passed**. 1·2·5편 파이프라인, 선택 기본값 3·저장/재개 유지, 원문 깊이·본론 근거·분량 검사, 본문 구절 ID·문자 표시 회귀 검사 | pytest (`output/validation/pytest-detail.xml`, 로컬 산출물), [새 테스트](../tests/test_detail_target.py) |
| 실제 API | **10/10 후보 평가, 3편 상세 브리핑·PDF 완료**, 모델 20회·도구 24회, API 보고 288,942 토큰, 약 101초 | 실행 결과 (`output/validation/detail/result.json`, 로컬 산출물), trace (`output/validation/detail/trace.json`, 로컬 산출물) |
| 원문 열람 | Nexus Sampling **4 → 15/33**, G-KV **4 → 11/27**, EVICPRESS **4 → 9/24** 구간 | 실행 결과 (`output/validation/detail/result.json`, 로컬 산출물) |
| 상세 내용 | 문제·방법·결과·한계 합계 각각 **2,446 / 1,779 / 2,080자**. 방법의 구성·작동 원리, 실험 설정·수치 조건, 검증 한계 설명 포함 | 새 PDF (`output/pdf/detailed-research-briefing.pdf`, 로컬 산출물) |
| PDF | **3쪽**, 외부 논문 링크 3개. 표지·논문 비교·읽을 부분·인용 목록 없음. 영역 이탈/대체·누락 글리프 0. 전체 페이지 시각 검사 완료 | PDF 검사 (`output/validation/detail/rendered/checks.json`, 로컬 산출물) |
| UI | 추천 편수 선택·기본값·회전 아이콘·두 탭과 제거된 항목 검사. 새 화면 조회가 모델 호출을 발생시키지 않음 | [UI 테스트](../tests/test_pdf_provider_ui.py), [진행 표시 테스트](../tests/test_completion_activity.py) |

첫 상세 작성 구현은 24회 호출 한도에서 1편만 작성했습니다. 자유 인용문의 복사 오류, 서로 다른 논문 근거 ID를 섞은 요청과 반복 보완을 확인했고 실패 결과 (`output/validation/detail/before-located-evidence-result.json`, 로컬 산출물)를 보존했습니다. 이후 `record_evidence`로 실제 본문의 구절 ID를 선택하고, 한 번에 한 논문에 집중하며 해당 논문의 실제 근거 ID만 도구 스키마에서 선택하도록 보완했습니다. 개선 후 실행은 원래 사용자 결과를 보존한 새 기록입니다. 모델 업그레이드는 하지 않았습니다.

PDF 검사에서 한글 폰트가 일부 그리스 문자를 표시하지 못하는 문제도 발견했습니다. 표준 Symbol 폰트 대체와 α·λ 추출 테스트를 추가해 수식 매개변수가 사라지지 않도록 했습니다. Poppler 설치는 Xcode 라이선스 미승인으로 실패해 기존 PyMuPDF로 렌더링했습니다. 라이선스를 임의 수락하거나 시스템 설정을 변경하지 않았습니다.

읽은 구간 수와 글자 수는 최소 검토 범위를 확인하는 지표입니다. 원문 전체 정독, 수식·표·이미지 완전 해석, 모든 주장·수치의 의미적 정확성을 보장하지 않습니다. 실제 유료 검증은 3편 요청 한 사례이며, 1·2·5편은 합성 파이프라인과 상태/화면 테스트로 검증했습니다.

## 전체 후보 비교 평가 검증

2026-09-26, 동일 환경. 이번 검증은 기존 실제 검색의 15편과 저장된 초록·원문 자료를 재사용했습니다. 새 검색 API 요청의 종단 간 재검증은 아니며, **실제 모델이 모든 후보를 새로 평가하고 순위를 정하는 과정과 최종 제출**을 검증했습니다. 모델과 실행 한도는 변경하지 않았습니다.

| 항목 | 결과 | 증거 |
|---|---|---|
| 전체 테스트 | **99 passed**; 기존 SWIG 경고 5개 | pytest XML (`output/validation/pytest-screening.xml`, 로컬 산출물), [필수 평가 테스트](../tests/test_screening.py) |
| 실제 모델 평가 | **15/15 개별 평가, 15편 전체 순위, 3편 브리핑·PDF 완료**, 최종 참조 검사 오류 0 | 결과 (`output/validation/screening/result.json`, 로컬 산출물), 전체 trace (`output/validation/screening/trace.json`, 로컬 산출물) |
| 입력 처리 | 한 열람 도구당 최대 5편. 실제 실행은 3묶음의 초록을 열람하고 모델이 모든 후보를 평가. 평가 중 원문 근거를 숨겨 기존 선정 결과에 치우치는 입력을 줄임 | [screening.py](../paper_agent/screening.py), [agent.py](../paper_agent/agent.py) |
| PDF 자동 검사 | 4쪽, 선정 제목 3개, 외부 링크 15개, 대체 글리프 0. 연구 맥락·선정 기준 제외 유지 | PDF 검사 (`output/validation/screening/pdf-checks.json`, 로컬 산출물) |
| 필수 검사 | 미열람·초록 일부만 열람·같은 응답에서 읽기와 평가·가짜/다른 논문/이전 자료의 구절 ID·누락/중복 순위·shortlist 외 제출 거부. 자료·기준·후보·평가 변경 감지 | [필수 평가 테스트](../tests/test_screening.py) |
| UI | Chrome에서 `전체 15편 중 15편 후보 평가 완료 · 원문 일부 검토 3편`, 전체 순위·분류·평가 이유·출처 구절 확인. 이전 실행은 전체 평가 부재를 표시하고 새 재평가 실행 제공 | [app.py](../app.py), [UI 테스트](../tests/test_screening.py) |

최종 실행은 수정 전 시도를 포함해 모델 16회(최종 작성 1회 포함), 도구 17회입니다. API 보고 입력 167,707 + 출력 12,177 토큰이며, 개발 중 강제 중지한 요청의 예약분까지 포함한 차감 기록은 234,950입니다. 중지·재개 시 이미 사용한 예산을 초기화하지 않았습니다. 원래 사용자 실행은 덮어쓰지 않았습니다.

개발 과정에서 다음 실패를 실제로 재현하고 보완했습니다.

- 첫 구현 (`output/validation/screening/failed-v1-result.json`, 로컬 산출물): 모델이 선정 기준을 반복 변경해 기존 평가가 무효화되고 24회 한도에서 중단. 전체 비교가 끝날 때까지 기준을 고정하고 단계별 허용 도구를 제한했습니다.
- 인용 재입력 방식 (`output/validation/screening/failed-v2-result.json`, 로컬 산출물): 장식 따옴표·부정확한 구절과 미열람 후보 선택을 반복. 현재 방식은 모델이 읽은 초록의 구절 ID를 선택하고 서버가 실제 원문을 연결합니다. 도구 스키마도 열람한 미평가 후보 ID로 제한합니다.
- 전체 순위 보완 전 (`output/validation/screening/before-ranking-fix-result.json`, 로컬 산출물): 15편 평가 완료 후 ID 한 글자를 빠뜨린 순위를 반복 제출. 스키마에서 실제 후보 ID와 정확한 배열 길이를 제한하고, 서버 오류에 누락·잘못된 ID·중복을 구체적으로 반환했습니다. 사용량을 유지한 채 재개한 다음 전체 비교와 최종 제출이 완료됐습니다.

이는 **평가 누락 방지와 출처 연결의 검증**입니다. 모든 원문 전체를 읽었거나 점수·순위·최신성 해석까지 옳다는 보증은 아닙니다. 모델은 일부 2024년 논문을 최신 대표 연구로 표현하고 다른 후보의 날짜를 부정확하게 해석하는 등 내용 검수 대상이 남아 있습니다. 기존에 확보한 원문 일부와 근거는 재사용했으며 이번 검증에서 새로 읽었다고 계산하지 않습니다.

## 3편 완료 정책·실시간 현황 검증

2026-09-25, 같은 환경에서 실제 API를 사용해 검증했습니다.

| 항목 | 결과 | 증거 |
|---|---|---|
| 전체 테스트 | **78 passed**, 10.72초; 기존 SWIG 경고 5개 | pytest XML (`output/validation/pytest-completion.xml`, 로컬 산출물), [정책·현황 테스트](../tests/test_completion_activity.py) |
| 기존 중단 기록 복구 | 이미 3편의 원문 근거가 있었지만 비교 인용 보완 중 입력 예약량 때문에 종료됨. 입력 축약 후 **추가 모델 1회, 8,839 토큰**으로 정확히 3편과 PDF 완료. 추가 검색 없음 | 복구 결과 (`output/validation/completion/recovery.json`, 로컬 산출물), 복구 전 trace (`output/validation/completion/before-trace.json`, 로컬 산출물), 복구 후 trace (`output/validation/completion/after-trace.json`, 로컬 산출물) |
| 새로운 넓은 질문 | SSM·linear attention 동향 질문으로 실제 검색·원문 검토. 24회 연구 호출 직후 작성 기회를 잃는 실패를 재현하고 최종 작성 4회 예약 추가. 저장된 실행에서 예약 1회로 **3편 완료**, 전체 25회·215,099 토큰·약 155.5초 | 최종 결과 (`output/validation/completion/fresh-live/result.json`, 로컬 산출물), 수정 전 실패 (`output/validation/completion/fresh-live/before-finalization-reserve.json`, 로컬 산출물), 전체 trace (`output/validation/completion/fresh-live/trace.json`, 로컬 산출물) |
| 실시간 UI | Chrome에서 실제 작업 중 도구명·검색어·논문 제목과 최근 완료 작업 표시 확인. AppTest에서 사이트·요청 URL·검색어 및 재조회 시 모델 호출 없음 확인 | [정책·현황 테스트](../tests/test_completion_activity.py) |
| 복구 PDF | 4쪽, 외부 링크 15개·내부 링크 31개, 영역 이탈·대체 글리프 0 | 복구 브리핑 (`output/pdf/ssm-linear-attention-briefing.pdf`, 로컬 산출물), PDF 검사 (`output/validation/completion/pdf-checks.json`, 로컬 산출물) |

새 탐색 결과는 Dynamic Linear Attention(2026), Log-Linear Attention(2025), Exact Linear Attention(2026)입니다. 첫 검색의 잘못된 arXiv 구절 문법과 활성 후보 정원 문제를 발견해 문법 사전 검사·제외 후보 교체 공간도 추가했습니다. 테스트는 3편 미만 제출 거부, 조기 종료 거부 후 계속 진행, 인용을 임의 생성하지 않는 구조 보정, 최근 응답 그룹의 call_id 일관성, 최종 작성 예약과 한도를 검증합니다.

복구한 이전 브리핑에는 출판 연도 2024인 논문들을 “최근 2년 이내”로 표현한 내용 오류가 남아 있었습니다. 개발 검수로 실제 저장 연도를 사용하도록 정정하고 선정 이유를 해석으로 표시했습니다. 원래 모델 출력 (`output/validation/completion/recovered-model-briefing.json`, 로컬 산출물)과 검수 내역 (`output/validation/completion/review-notes.json`, 로컬 산출물)을 보존했습니다. 자동 참조 검증이 의미·최신성 정확성을 보증한다는 뜻은 아닙니다.

두 실행은 각각 한 사례이며 모든 분야·질문의 성공률을 추정하지 않습니다. 새 정책은 질문의 넓이 때문에 조기 종료하거나 1~2편을 완료로 처리하지 않습니다. API 장애·전체 한도 소진에도 논문을 만들어 내거나 무한 요청을 보내지는 않습니다. 변경 전 검증 이력은 아래에 보존합니다.

## UI·초기화·PDF 개선 검증

동일 환경에서 2026-09-25에 확인했습니다. 이번 변경 검증에는 새 유료 API 요청을 사용하지 않았습니다.

| 항목 | 결과 | 증거 |
|---|---|---|
| 전체 테스트 | **66 passed**, 10.93초; 기존 PyMuPDF SWIG 경고 5개 | pytest XML (`output/validation/pytest-ux.xml`, 로컬 산출물) |
| 초기화 | 경고 1회, 취소 시 보존, 확인 시 전체 삭제·새 입력 화면. 표시 한도보다 오래된 기록과 손상된 기록 삭제, 실행 중 자식 프로세스 중지, 삭제된 기록의 지연 재시작 차단 | [초기화 테스트](../tests/test_reset.py) |
| UI | 새 연구 입력과 추천 논문/논문 비교/살펴본 논문 분리. 실행 ID·모델·토큰·예산·원시 로그를 화면에서 제거 | [UI/PDF 테스트](../tests/test_pdf_provider_ui.py), 브라우저 검사 (`output/validation/ui-ux-checks.json`, 로컬 산출물) |
| PDF | 연구 맥락·선정 기준·미선정 논문 제외, 선정 논문·비교·출처 유지. 기존 저장 PDF도 다운로드 시 새 형식으로 교체 | [UI/PDF 테스트](../tests/test_pdf_provider_ui.py) |
| PDF 자동·시각 검사 | **4쪽**, 외부 링크 13개/내부 링크 29개, 영역 이탈·대체 글리프 0, 한글 폰트 포함. 모든 페이지의 제목·여백·줄바꿈·인용 번호 확인 | 새 PDF (`output/pdf/research-briefing.pdf`, 로컬 산출물), 검사 결과 (`output/validation/pdf-ux-checks.json`, 로컬 산출물) |

삭제 검증에는 테스트용 임시 데이터를 사용했습니다. 브라우저에서는 새 입력·완료 결과·비교 화면과 초기화 경고·취소를 확인했습니다. 새 PDF 예시는 기존 개발 검수본 JSON을 새 형식으로 렌더링한 것입니다. 기존 실제 실행의 원본 상태·과거 검증 산출물은 보존하며, 아래 표는 개선 전 검증 이력입니다.

## 초기 에이전트 실행 결과

| 층위 | 실제 실행 결과 | 증거 |
|---|---|---|
| 단위·오프라인 통합 테스트 | **59 passed**, 9.18초; PyMuPDF SWIG DeprecationWarning 5개 | pytest XML (`output/validation/pytest.xml`, 로컬 산출물) |
| 고정 응답+합성 도구 시나리오 | 5/5 통과; 자율성 검증 아님 | 합성 시나리오 (`output/validation/scripted/summary.json`, 로컬 산출물) |
| 키 없는 데모 CLI | 별도 worker에서 7개 스크립트 응답, 15개 도구 요청, 합성 브리핑/PDF 완료 | 예제 trace (`output/pdf/trace.json`, 로컬 산출물) |
| 실제 학술 소스 네트워크 | Crossref 메타데이터, arXiv HTML, Europe PMC XML 성공 | 학술 소스 결과 (`output/validation/source-smoke.json`, 로컬 산출물) |
| 실제 모델+합성 도구 평가 | **5/5 통과**, 각 시나리오 1회; gpt-5.4-mini, reasoning=low | 모델 평가 (`output/validation/model-evaluation.json`, 로컬 산출물) |
| 실제 모델+실제 학술 소스 E2E | **completed**, 3편 선정, 12개 근거, 기계적 검증 통과 | E2E (`output/validation/e2e.json`, 로컬 산출물), 실제 trace (`output/live/trace.json`, 로컬 산출물) |
| PDF 자동·시각 검사 | 합성/실제 원본/개발 검수본 모두 5쪽. 한글·폰트·링크·여백·줄바꿈 확인 | 합성 검사 (`output/validation/pdf-checks.json`, 로컬 산출물), 실제 원본 검사 (`output/validation/live-pdf-checks.json`, 로컬 산출물), 검수본 검사 (`output/validation/reviewed-pdf-checks.json`, 로컬 산출물) |
| 브라우저 확인 | Chrome에서 실제 completed 실행, 10개 후보·예산·3개 KEEP 표시. 합성 PDF 다운로드 파일 원본 일치 | 브라우저 확인 (`output/validation/browser-checks.json`, 로컬 산출물) |

키는 로컬 `.env`에서 읽었습니다. `.env.example`은 빈 키 템플릿이며 `.env` 권한은 0600입니다. 코드·문서·공개 결과물에 키가 포함되지 않았는지 별도 검사했습니다. 실제 API를 호출했으며 모델 접근과 Responses/function-call 호환성도 해당 계정에서 확인했습니다.

## 실제 모델의 통제된 행동 평가

최종 평가 버전 3은 합성 자료를 검토하는 평가임을 명시하고, 부적합 후보의 ID/제목에서 기대 답변이 드러나지 않도록 했습니다. 행동 순서는 모델이 결정합니다. 정상 실행에 실패나 교체를 강제하지 않습니다.

| 시나리오 | 실제 관측 후 행동 | 공개 trace |
|---|---|---|
| 충분한 근거 | 3편을 제출하고 교차 논문 인용 오류를 수정해 완료 | sufficient (`output/validation/trace-a389f895c8e445f7b1ed5c8a318470f4.json`, 로컬 산출물) |
| 첫 검색 부족 | 빈 결과 뒤 질의/소스/페이지를 변경해 재검색하고 완료 | insufficient (`output/validation/trace-4c5374c0128347a7bb5044c5e64db513.json`, 로컬 산출물) |
| 원문 실패 | 실패를 관측한 뒤 대체 후보를 검토하고 근거 있는 2편으로 완료 | fulltext_failure (`output/validation/trace-1b9df68d0fd54c958663b56888f033ba.json`, 로컬 산출물) |
| 원문 조건 불일치 | 라벨 100만 개 원문을 읽은 뒤 제외하고 적합 후보로 완료 | mismatch (`output/validation/trace-6bac2a787fc8439ba9dcb2ceded125d4.json`, 로컬 산출물) |
| 예산 소진 | 도구 2회 상한에서 불완전 종료 | budget (`output/validation/trace-f6644b9bc9af4297a6b49ae4e0a399a7.json`, 로컬 산출물) |

**각 1회 결과이며 성공률의 통계적 추정은 아닙니다.** 이전 gpt-4.1-mini 평가에서는 3/5만 통과했습니다. 합성 자료를 실제 자료로 바꿀지 질문하며 멈추거나, 원문 실패 후 최종 브리핑을 제출하지 않거나, 부적합 원문을 방문하지 않아 해당 행동을 검증할 수 없는 경우가 있었습니다. 초기 평가 (`output/validation/model-evaluation-initial.json`, 로컬 산출물)와 버전 2 평가 (`output/validation/model-evaluation-v2.json`, 로컬 산출물)를 그대로 보존했습니다. 샌드박스 연결 실패도 초기 단일 평가 (`output/validation/model-sufficient.json`, 로컬 산출물)에 남아 있습니다.

## 실제 학술 소스 E2E와 내용 검수

연구 질문은 “적은 라벨을 이용한 문서 분류 연구의 방법·실험 조건·한계와 서로 다른 접근 약 3편 비교”였습니다. 최종 실행 `ffa97eeac6b84e2b95c3253960a546f2`는 arXiv/Crossref 검색 2회, 후보 10편, 서로 다른 원문 4편, 모델 16회, 도구 30회를 사용했습니다. 약 **103.7초**, API 보고 입력 299,168 + 출력 11,029 = **310,197 토큰**이었습니다. 토큰 수는 금액이 아니며 반복 실험은 추가 비용을 발생시킵니다.

선정은 HBM(2021), CACO(2018), MHAN(2017)의 문서 구조/언어 전이 접근입니다. 각 4개 청크를 읽었으며 원문 전체를 검토한 것은 아닙니다. 실제 trace에서 `submit_briefing`의 비교 근거 누락 오류가 다음 모델 턴에 반환되고, 서로 다른 논문의 근거를 추가한 후 완료되는 연결을 확인했습니다.

기계적 검증은 **참조 무결성**을 확인합니다. 내용 검수에서는 원본 제목에 최종 선정되지 않은 “프롬프트 기반”이 남고, 선정 이유가 논문 주장으로 표시되며, 일부 활용 설명이 연결 인용보다 넓은 문제가 발견됐습니다. 이를 숨기거나 자동 평가 통과를 의미적 정확성 보증으로 표현하지 않습니다.

- 자동 생성 원본 PDF (`output/live/briefing.pdf`, 로컬 산출물)와 원본 JSON (`output/live/briefing.json`, 로컬 산출물), 실제 실행 상태/trace는 변경하지 않았습니다.
- 개발 검수본 PDF (`output/live/briefing-reviewed.pdf`, 로컬 산출물)는 제목·해석 표기·비교 범위를 수정했고, PDF 안에도 편집 사실을 표시합니다. 수정 내역 (`output/live/review-notes.json`, 로컬 산출물)을 제공합니다. 독립 분야 전문가 검수는 아닙니다.
- 실제 원본과 검수본 모두 5쪽, 외부 링크 13개/내부 링크 41개, 영역 이탈·대체 글리프 0입니다. 모든 페이지를 렌더링해 확인했습니다.

### 개발 중 실패 기록

| 설정/기록 | 결과와 관측 |
|---|---|
| gpt-4.1-mini 초기 180k (`output/validation/e2e-initial.json`, 로컬 산출물) | 인용 불일치 후 다음 요청 토큰 예약량 초과 |
| 입력 축약 도입, 180k (`output/validation/e2e-compaction-180k.json`, 로컬 산출물) | 인용 보완 중 예산으로 불완전 종료 |
| gpt-4.1-mini 350k (`output/validation/e2e-gpt41mini-350k.json`, 로컬 산출물) | 무관한 이미지 분류 후보 검토와 예산 소진 |
| gpt-5.4-mini 초기 질의 (`output/validation/e2e-gpt54mini-query-v1.json`, 로컬 산출물) | 부정확한 검색 문법/후보 정원 소진 뒤 사용자 질문 대기 |
| 질의 문법 보완 (`output/validation/e2e-gpt54mini-query-v2.json`, 로컬 산출물) | 적합 원문을 확보했지만 모델이 일찍 불완전 종료 |
| reasoning=low, 350k (`output/validation/e2e-gpt54mini-low-350k.json`, 로컬 산출물) | 원문과 근거 확보 후 보수적 토큰 예약량 초과 |
| 최종 500k 및 평가 후 원문 축약 (`output/validation/e2e.json`, 로컬 산출물) | 3편 제출, 비교 인용 오류 보완, completed |

현재 기본값은 `gpt-5.4-mini`, `.env.example`의 추론 수준 `low`, 총 토큰 상한 500,000입니다. 출처별 검색 문법 안내, 명백한 과제 불일치 사전 평가, 짧은 정확한 인용, 오래된 상태 중복 제거 및 평가가 끝난 원문의 위치 기반 축약을 적용했습니다. 설정과 코드가 함께 변했으므로 모델 하나의 효과를 분리한 인과 비교는 아닙니다. 마지막 성공을 모든 실행의 안정적 성공률로 해석하지 마세요.

## 기본 테스트 범위

- DOI 정규화, 출처 ID 및 정규화 제목 중복 제거, 병합된 보조 식별자 보존, 후보 상한
- 알 수 없는 도구, 잘못된 인자 타입/범위, 추가 필드 차단; 모든 도구 JSON Schema의 strict 구조
- 저장되지 않은 인용, 읽지 않은 청크, 다른 논문의 근거, 원문 미검토 최종 추천 차단
- 인용 검증 실패를 모델의 관측으로 돌려주고 후속 제출로 수정하는 루프
- 한 모델 응답의 복수 호출 각각에 대응하는 tool output과 다음 턴 전달
- 원본 대화 보존, 최신 관측/사용자 답변 유지, 평가한 이전 원문의 위치 기반 축약
- 추론 설정 선택적 전달과 encrypted reasoning만 프로토콜에 유지
- 질문 뒤 상태 저장, 사용자 답변 후 기존 대화·예산에서 재개
- 호출/시간/토큰 예산과 명시적 중지, 빈 모델 응답, 모델 요청 실패 예약량 유지
- 실제 subprocess에서 데모 완료, 동일 완료 실행 재시작 시 외부 호출 없음
- 실제로 대기하는 자식 프로세스의 사용자 중지와 5초 hard timeout 강제 종료
- HTTP timeout/503 재시도 상한, 404 무재시도, 리다이렉트 URL 검사, 다운로드 크기 제한
- arXiv Atom, Europe PMC/Crossref 메타데이터, HTML/JATS 절, PDF 페이지 추출
- 논문 속 명령문을 자료로 유지하고 스크립트 태그 제거
- 상태 저장/복원, public trace에서 private conversation 제외, 경로 traversal 차단
- PDF 한글 텍스트·폰트·내부/외부 링크·페이지 범위, 불완전 결과 표시
- Streamlit 초기/완료 화면과 새로고침이 실행 횟수를 변경하지 않는지 검사

## 통제된 시나리오와 평가 기준

합성 자료는 [demo.py](../paper_agent/demo.py)의 `FixtureSources`에 코드로 고정되어 있습니다. 실제 논문으로 오인하지 않도록 모든 제목과 저자를 합성으로 표시하고 DOI는 만들지 않았습니다. `example.org/synthetic/…` 주소는 출처 형식 예시이며 실제 학술 원문 링크가 아닙니다.

| 상황 | 평가하는 행동 | 증거 trace |
|---|---|---|
| 첫 검색에 관련 후보 부족 | 빈 결과 관측 이후 질의·소스·페이지 중 하나를 바꿔 검색 | insufficient (`output/validation/scripted/insufficient-trace.json`, 로컬 산출물) |
| 원문 조회 실패 | 실패 이후 다른 경로·후보·검색 선택 | fulltext_failure (`output/validation/scripted/fulltext_failure-trace.json`, 로컬 산출물) |
| 원문 조건 불일치 | 부적합 원문을 실제 읽은 후 제외하고 다른 후보 유지 | mismatch (`output/validation/scripted/mismatch-trace.json`, 로컬 산출물) |
| 충분한 근거 | 필수 근거가 있는 유효 브리핑을 예산 소진 전에 제출 | sufficient (`output/validation/scripted/sufficient-trace.json`, 로컬 산출물) |
| 예산 소진 | 상한을 넘지 않고 종료 이유를 남긴 불완전 상태 | budget (`output/validation/scripted/budget-trace.json`, 로컬 산출물) |

표의 trace는 **스크립트 응답을 사용한 루프/도구 연결 테스트**입니다. 예를 들어 fulltext_failure trace에는 기본 원문 요청→합성 404 관측→후속 PDF 요청의 연결이 있습니다. 이 연결을 실제 모델이 만들었다고 주장하지 않습니다.

```bash
# 스크립트 기반 재현
python scripts/record_scenarios.py

# 실제 모델 판단 평가: 키가 있을 때만 유료 API 요청
python -m paper_agent.evaluation --scenario all --trials 3
```

실제 모델 평가에서는 **응답을 고정하지 않습니다.** 같은 프롬프트/스키마에 다른 FixtureSources 관측을 주고 행동과 종료를 검사합니다. 특정 검색 문구나 완전히 같은 도구 순서는 요구하지 않습니다. 실패 경로나 부적합 원문을 모델이 방문하지 않았다면 `stimulus_observed=false`로 기록하며 성공으로 계산하지 않습니다. `waiting`은 자동으로 답변하지 않고 미완료 평가로 남깁니다. 보고서에 모델 ID, run ID, 결과, 원시 공개 trace를 남깁니다.

자율성의 완전한 증명이나 정교한 인과 실험은 아닙니다. 실제 모델의 동일 조건 반복 결과를 보고 적합성을 검토하는 평가 경로입니다. 실행 간 비결정성 때문에 `--trials` 반복과 사람의 trace 검토를 권장합니다. 자동 평가가 근거의 의미나 연구 분야의 전문적 적절성까지 판단하지는 않습니다.

## 실제 모델 E2E 확인 절차

1. 키를 로컬 `.env`에 설정하고 `OPENAI_MODEL`을 접근 가능한 모델로 지정합니다.
2. `python scripts/e2e.py --question '구체적인 연구 질문'`을 실행합니다.
3. `output/validation/e2e.json`의 완료 여부·선정 검증·PDF 오류를 확인합니다.
4. `e2e-trace-<id>.json`에서 요청→실제 도구 실행→관측→다음 요청/종료의 연결을 확인합니다.
5. 원문 링크를 직접 열어 주요 주장과 인용 구간, 조건 비교, 선정 이유를 검토합니다.

유효한 브리핑이 없으면 해당 실행을 실패/불완전으로 보존합니다. 예산을 늘리거나 실행을 다시 하더라도 앞선 실패 기록을 성공 기록으로 덮어 설명하지 마세요.

## 남은 제한

Windows/Linux 설치·UI, 독립 분야 전문가 검수, 다양한 연구 질문에 대한 반복 성공률은 미검증입니다. 실제 원격 PDF 다운로드는 이번 smoke에서 HTML이 성공해 시도하지 않았으며 PDF 파서는 생성된 PDF를 이용해 검증했습니다. 긴 실제 논문 전부의 의미, 표·수식·이미지, 연구별 검색 성능, 프롬프트 인젝션에 대한 모델의 강건성은 보장하지 않습니다. 시스템 Poppler가 없어 PyMuPDF로 모든 페이지를 렌더링했고 한글 PDF를 시각적으로 검수했습니다.
