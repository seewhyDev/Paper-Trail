import os
import re

import streamlit as st
from filelock import FileLock, Timeout

from paper_agent.agent import answer_question
from paper_agent.config import data_root, default_limits, load_config, model_name, reasoning_effort
from paper_agent.demo import DEMO_QUESTION
from paper_agent.pdf import ensure_pdf, safe_link
from paper_agent.schema import Context, RunState
from paper_agent.store import Store
from paper_agent.worker import launch, reset_runs
from paper_agent.completion import prepare_resume, resume_problem
from paper_agent.activity import activity_view

load_config()
st.set_page_config(page_title="Paper Trail · 연구 브리핑", page_icon="📖", layout="wide")
store = Store(data_root())
st.markdown("""<style>
.stApp {background:#fbfcfb; color:#243b3a;}
.block-container {padding-top:2.5rem; padding-bottom:4rem; max-width:1040px;}
h1,h2,h3 {letter-spacing:-.035em; color:#183d39;}
h1 {font-size:2.35rem !important;}
h3 {font-size:1.22rem !important; line-height:1.5 !important;}
[data-testid="stSidebar"] {background:#f0f4f2; border-right:1px solid #e1e8e4;}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-radius:14px;}
[data-testid="stTabs"] [role="tablist"] {gap:1.8rem; margin-bottom:1rem;}
[data-testid="stTabs"] [role="tab"] {padding:0.7rem 0;}
[data-testid="stExpander"] {background:#fff; border-color:#e5ebe7;}
[data-testid="stHeader"] {background:transparent;}
[data-testid="stToolbar"] {display:none;}
.agent-working {display:flex; align-items:center; gap:12px; color:#087f78; font-weight:600; margin-bottom:16px;}
.agent-wheel {display:inline-block; width:22px; height:22px; border:3px solid #d1e7e3; border-top-color:#087f78; border-radius:50%; animation:agent-spin 1s linear infinite;}
@keyframes agent-spin {to {transform:rotate(360deg);}}
@media (prefers-reduced-motion:reduce) {.agent-wheel {animation:none;}}
.paper-quote {padding:12px 16px; margin:8px 0 12px; border-left:3px solid #b4cbc1;
 background:#f5f8f6; color:#52645c; font-size:.92rem; line-height:1.7; overflow-wrap:anywhere;}
.paper-kicker {color:#647b70; font-size:.78rem; letter-spacing:.08em; margin-bottom:.4rem;}
</style>""", unsafe_allow_html=True)

STATUS = {"ready": "대기 중", "running": "검토 중", "waiting": "답변 필요", "completed": "완료",
          "incomplete": "검토 종료", "cancelled": "중지됨", "error": "다시 시도 필요"}
def new_briefing():
    st.session_state.view = "new"
    st.session_state.pop("active_run", None)
    st.query_params.clear()


def select_history():
    selected = st.session_state.get("history_run")
    if selected:
        st.session_state.active_run = selected
        st.session_state.view = "result"
        st.query_params["run"] = selected


@st.dialog("기록을 모두 삭제할까요?", dismissible=False)
def confirm_reset():
    st.warning("지금까지 저장된 모든 브리핑, 논문과 원문, 실행 기록, 생성된 PDF를 삭제합니다. 진행 중인 탐색도 중지되며 삭제한 기록은 복구할 수 없습니다.")
    cancel, remove = st.columns(2)
    if cancel.button("취소", use_container_width=True):
        st.session_state.reset_pending = False
        st.rerun()
    if remove.button("모두 삭제", type="primary", use_container_width=True):
        try:
            with st.spinner("진행 중인 작업을 정리하고 기록을 삭제하고 있어요…"):
                reset_runs(store)
        except (Timeout, OSError):
            st.error("작업 정리가 아직 끝나지 않았습니다. 잠시 후 초기화를 다시 시도해 주세요.")
        else:
            st.session_state.clear()
            st.session_state.view = "new"
            st.session_state.reset_done = True
            st.query_params.clear()
            st.rerun()


runs = store.list_runs()
choices = [s.id for s in runs]
labels = {s.id: f"{s.context.question[:48]}{'…' if len(s.context.question) > 48 else ''} · {STATUS.get(s.status, '검토 중')}" for s in runs}
if "view" not in st.session_state:
    requested = st.query_params.get("run")
    active = requested if requested in choices else (choices[0] if choices else None)
    st.session_state.view = "result" if active else "new"
    st.session_state.active_run = active
active = st.session_state.get("active_run")
if active and active not in choices:
    new_briefing()
    active = None
st.session_state.history_run = active

with st.sidebar:
    st.markdown("## Paper Trail")
    st.caption("읽을 논문을, 근거와 함께.")
    st.button("＋ 새 브리핑", on_click=new_briefing, use_container_width=True, type="primary")
    st.divider()
    st.markdown("**내 브리핑**")
    if choices:
        st.selectbox("지난 브리핑", choices, key="history_run", format_func=lambda x: labels[x],
                     index=None, placeholder="브리핑을 선택하세요", label_visibility="collapsed", on_change=select_history)
    else:
        st.caption("완성한 브리핑이 여기에 모입니다.")
    st.divider()
    if st.button("초기화", use_container_width=True, disabled=not bool(store.run_directories())):
        st.session_state.reset_pending = True
    if st.session_state.get("reset_pending"):
        confirm_reset()

if st.session_state.pop("reset_done", False):
    st.success("모든 기록을 삭제했습니다. 새 연구를 시작해 보세요.")


def render_new():
    st.caption("PAPER TRAIL / RESEARCH READING")
    st.title("어떤 연구를 시작하시나요?")
    st.write("관련 논문을 찾고 원문을 읽어, 핵심 내용과 한계를 담은 브리핑으로 정리해 드립니다.")
    source = st.radio("사용할 자료", ["실제 논문", "예시 체험"],
                      index=0 if os.getenv("OPENAI_API_KEY") else 1, horizontal=True)
    mode = "live" if source == "실제 논문" else "demo"
    if mode == "demo":
        st.caption("합성 논문과 고정된 진행 흐름으로 화면을 체험합니다. 실제 논문 추천은 아닙니다.")
    with st.form("new_research"):
        question = st.text_area("연구 질문", value=DEMO_QUESTION if mode == "demo" else "", height=140,
                                placeholder="예: 적은 라벨로 문서를 분류하는 방법을 비교하고 싶어요.", max_chars=8000)
        target = st.selectbox("최종 추천 논문 수", [1, 2, 3, 4, 5], index=2, format_func=lambda n: f"{n}편")
        with st.expander("원하는 방향을 더 알려주세요 · 선택"):
            help_wanted = st.text_input("어떤 도움이 필요한가요?", placeholder="예: 실험에 사용할 기준선과 핵심 설계", max_chars=4000)
            constraints = st.text_input("고려할 조건", placeholder="예: 공개 코드, 적은 데이터, 최근 5년", max_chars=4000)
            already_read = st.text_input("이미 읽은 논문", placeholder="제목 또는 DOI", max_chars=4000)
        submitted = st.form_submit_button("브리핑 만들기", type="primary", use_container_width=True)
    if submitted:
        if len(question.strip()) < 3:
            st.error("연구 질문을 조금 더 구체적으로 적어주세요.")
        elif mode == "live" and not os.getenv("OPENAI_API_KEY"):
            st.error("실제 논문 탐색을 위한 서버 설정이 필요합니다. README의 API 키 설정을 확인하거나 예시 체험을 선택하세요.")
        else:
            state = RunState(mode=mode, context=Context(question=question.strip(), help_wanted=help_wanted,
                             constraints=constraints, already_read=already_read), limits=default_limits(),
                             model="scripted-replay (not LLM)" if mode == "demo" else model_name(),
                             reasoning_effort=reasoning_effort() if mode == "live" else None, require_target=True, require_screening=True, require_depth=mode == "live")
            state.limits.target = target
            try:
                store.save(state)
                launch(store, state.id)
            except (RuntimeError, Timeout, OSError):
                st.error("다른 작업을 정리하고 있습니다. 잠시 후 다시 시작해 주세요.")
            else:
                st.session_state.active_run = state.id
                st.session_state.view = "result"
                st.query_params["run"] = state.id
                st.rerun()


def paper_meta(paper):
    authors = ", ".join(paper.authors[:3])
    if len(paper.authors) > 3:
        authors += f" 외 {len(paper.authors) - 3}명"
    return " · ".join(x for x in [str(paper.year) if paper.year else "", authors] if x)


def paper_link(paper):
    if safe_link(paper.url):
        st.link_button("논문 보기 ↗", paper.url)


def render_recommendations(s):
    briefs = {b.paper_id: b for b in s.briefing.papers}
    for i, pid in enumerate(s.briefing.reading_order, 1):
        brief, paper = briefs[pid], s.papers[pid]
        with st.container(border=True):
            st.markdown(f'<div class="paper-kicker">논문 {i:02}</div>', unsafe_allow_html=True)
            st.subheader(paper.title)
            st.caption(paper_meta(paper))
            for field, label in (("problem", "다루는 문제"), ("method", "핵심 방법"),
                                 ("results", "주요 결과"), ("limitations", "한계와 해석")):
                st.markdown(f"**{label}**")
                st.write(getattr(brief, field).text)
            paper_link(paper)


def candidate_text(text, s):
    for pid, paper in sorted(s.papers.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(pid, f"「{paper.title}」")
    return re.sub(r"\bp_[a-zA-Z0-9]+", "해당 후보", text)


def render_candidates(s):
    from paper_agent.screening import screened, comparison_current, has_read
    papers = list(s.papers.values())
    if not papers:
        st.caption("검색된 후보가 여기에 표시됩니다.")
        return
    selected = set(s.briefing.reading_order) if s.briefing else set()
    assessed = sum(screened(s, p) for p in papers)
    st.write(f"전체 {len(papers)}편 중 {assessed}편 후보 평가 완료 · 원문 일부 검토 {sum(bool(p.read_chunks) for p in papers)}편")
    st.caption("모든 후보의 제목·초록을 비교하고, 우선순위가 높은 후보의 원문 구간을 읽습니다. 초록이 없으면 제목만 평가한 것으로 구분합니다.")
    if not s.require_screening:
        st.info("이전 실행에는 전체 후보 비교 평가 절차가 적용되지 않았습니다. 기록된 검토 범위만 표시합니다. 새 탐색부터 전체 후보 평가가 필수입니다.")
    current = comparison_current(s)
    if current:
        with st.expander("전체 후보 비교·우선순위 이유"):
            st.write(candidate_text(s.candidate_comparison.summary, s))
        papers = [s.papers[pid] for pid in s.candidate_comparison.ranked_paper_ids]
    labels = {"fulltext": "원문 검토 유망", "reference": "참고", "exclude": "제외"}
    def stage(p):
        if screened(s, p):
            base = "초록 평가 완료" if p.screening.basis == "abstract" else "제목만 평가 · 초록 미확보"
        elif p.screening:
            base = "재평가 필요"
        else:
            base = "초록 읽음 · 평가 대기" if has_read(p) else "후보 평가 대기"
        return base + (" · 원문 일부 검토" if p.read_chunks else "")
    st.dataframe([{"우선순위": i if current else "미정", "논문": p.title,
                   "검토 범위": stage(p),
                   "분류": "최종 추천" if p.id in selected else (labels[p.screening.decision] if screened(s, p) else "평가 대기")}
                  for i, p in enumerate(papers, 1)], hide_index=True, use_container_width=True)
    st.markdown("**논문별 평가와 근거**")
    for paper in papers:
        with st.expander(paper.title):
            st.caption(paper_meta(paper))
            st.write(stage(paper))
            if screened(s, paper):
                review = paper.screening
                st.markdown("**비교 평가 이유**")
                st.write(candidate_text(review.reason, s))
                st.caption(f"질문 관련성 {review.relevance}/5 · 방법·조건 적합성 {review.method_fit}/5 · 원문 검토 가치 {review.evidence_potential}/5")
                st.markdown("**평가에 사용한 초록 구절**" if review.basis == "abstract" else "**확인한 제목**")
                st.write(review.quote)
                if review.limitation:
                    st.caption("확인 한계 · " + candidate_text(review.limitation, s))
            if paper.read_chunks and paper.reason:
                st.markdown("**원문 구간 검토 결과**")
                st.write(candidate_text(paper.reason, s))
            paper_link(paper)


def render_activity(s):
    current, recent = activity_view(s)
    with st.container(border=True):
        st.markdown('<div class="agent-working" role="status" aria-live="polite"><span class="agent-wheel" aria-hidden="true"></span>에이전트가 작업하고 있습니다</div>', unsafe_allow_html=True)
        st.markdown("**지금 하고 있는 일**")
        st.subheader(current["title"])
        if current["tool"]:
            st.caption("사용 중인 도구 · " + current["tool"])
        if current["site"]:
            st.markdown("**사이트 · " + current["site"] + "**")
        if current["query"]:
            st.text("검색어 · " + current["query"])
        if current["detail"]:
            st.write(current["detail"])
        if current.get("route"):
            st.caption("조회 경로 · " + current["route"])
        if current.get("sections"):
            st.caption("읽는 부분 · " + " / ".join(current["sections"]))
        if current["url"]:
            st.caption(current["url"])
        if recent:
            with st.expander("방금 진행한 작업", expanded=True):
                for item in recent:
                    st.markdown(f"**{item['title']}** · {item['status']}")
                    st.caption(" · ".join(x for x in (item['tool'], item['site'], item['query'] or item['detail']) if x))


def download_briefing(s):
    try:
        # Serialize with reset so viewing a deleted run cannot recreate its files.
        with FileLock(str(store.root / "state.lock"), timeout=10):
            if not (store.path(s.id) / "state.json").exists():
                return
            pdf = ensure_pdf(s, store.path(s.id) / "briefing.pdf")
            content = pdf.read_bytes()
        st.download_button("PDF 다운로드", content, "paper-trail-briefing.pdf", "application/pdf", type="primary")
    except (OSError, ValueError, Timeout):
        st.error("PDF를 준비하지 못했습니다. 잠시 후 다시 열어주세요.")


@st.fragment(run_every="2s")
def monitor(run_id):
    try:
        s = store.load(run_id)
    except (FileNotFoundError, ValueError):
        new_briefing()
        st.rerun()
    if st.query_params.get("run") != s.id:
        st.query_params["run"] = s.id
    st.caption("예시 브리핑 · 합성 논문" if s.mode != "live" else "나의 연구 브리핑")
    title = "읽을 논문을 정리했어요." if s.briefing else (
        "논문을 살펴보고 있어요." if s.status in {"ready", "running", "waiting"}
        else "이번 탐색을 마쳤어요.")
    st.title(title)
    st.write(s.context.question)
    if s.mode != "live":
        st.caption("합성 자료로 구성한 예시입니다. 실제 학술 논문에 대한 추천이 아닙니다.")
    if s.briefing:
        if not s.require_screening:
            st.caption("이전 실행입니다. 저장된 후보 전체를 새 기준으로 비교 평가할 수 있습니다.")
            if st.button("전체 후보 다시 비교 평가"):
                from paper_agent.screening import rescreen_run
                revised = rescreen_run(s, default_limits())
                store.save(revised)
                launch(store, revised.id)
                st.session_state.active_run, st.session_state.view = revised.id, "result"
                st.query_params["run"] = revised.id
                st.rerun()
        if s.mode == "live" and not s.require_depth:
            st.caption("이전 형식의 브리핑입니다. 원문을 더 읽어 상세하게 다시 작성할 수 있습니다.")
            if st.button("원문을 더 읽고 상세 브리핑 만들기"):
                from paper_agent.screening import rescreen_run
                revised = rescreen_run(s, default_limits())
                revised.require_depth = True
                store.save(revised)
                launch(store, revised.id)
                st.session_state.active_run, st.session_state.view = revised.id, "result"
                st.query_params["run"] = revised.id
                st.rerun()
        download_briefing(s)
        recommended, candidates = st.tabs(["추천 논문", "전체 후보 평가"])
        with recommended:
            render_recommendations(s)
        with candidates:
            render_candidates(s)
        return
    if s.status == "running":
        render_activity(s)
        if st.button("탐색 중지"):
            with FileLock(str(store.root / "state.lock"), timeout=10):
                directory = store.path(s.id)
                if directory.exists():
                    (directory / "stop").touch()
            st.rerun()
        try:
            with FileLock(str(store.path(s.id) / "run.lock"), timeout=0):
                if st.button("중단된 작업 정리"):
                    def recover(current):
                        current.status, current.stop_reason = "error", "작업 프로세스가 종료되었습니다."
                    try:
                        store.update_existing(s.id, recover)
                    except FileNotFoundError:
                        pass
                    st.rerun()
        except Timeout:
            pass
    elif s.status == "ready":
        st.info("탐색을 시작할 준비가 되었습니다. 다른 탐색이 진행 중이라면 끝난 뒤 시작할 수 있어요.")
        if st.button("탐색 계속하기"):
            launch(store, s.id)
    elif s.status == "waiting":
        st.info(s.pending_question)
        with st.form("answer_" + s.id):
            answer = st.text_input("조금 더 알려주세요", max_chars=4000)
            if st.form_submit_button("이어서 탐색", type="primary"):
                try:
                    store.update_existing(s.id, lambda current: answer_question(current, answer))
                    launch(store, s.id)
                    st.rerun()
                except (ValueError, OSError, Timeout):
                    st.error("답변을 확인하고 잠시 후 다시 시도해 주세요.")
    else:
        blocked = resume_problem(s, refresh_call_policy=True)
        message = "탐색을 중지했습니다." if s.status == "cancelled" else (
            "연결 또는 서버 설정 문제로 작업이 중단됐습니다. 확보한 자료는 저장되어 있습니다." if s.status == "error"
            else "브리핑 완성 전에 작업이 중단됐습니다. 확보한 자료는 저장되어 있습니다.")
        st.info(message)
        if blocked:
            st.caption(blocked)
        elif s.mode == "live":
            st.caption("저장된 논문·근거·초안에서 이어갑니다. 추가 API 사용 비용이 발생합니다.")
        if s.mode == "live" and not blocked and st.button(f"{s.limits.target}편 브리핑 완성하기", type="primary"):
            try:
                store.update_existing(s.id, lambda current: prepare_resume(current, refresh_call_policy=True))
                launch(store, s.id)
                st.rerun()
            except (ValueError, OSError, Timeout) as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "잠시 후 다시 시도해 주세요.")
    st.divider()
    st.subheader("전체 후보 평가")
    render_candidates(s)


if st.session_state.view == "new":
    render_new()
else:
    monitor(st.session_state.active_run)
