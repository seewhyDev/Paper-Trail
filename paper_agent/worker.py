"""A supervisor enforces wall time and cancellation even during SDK/PDF parsing."""
import argparse
import os
import subprocess
import sys
import time
import shutil
from pathlib import Path

from filelock import FileLock, Timeout

from .agent import Agent, TERMINAL
from .config import load_config
from .demo import FixtureSources, ReplayProvider
from .network import Network
from .provider import ModelError, OpenAIProvider
from .provider import Call, result_item
from .sources import AcademicSources
from .store import Store


def launch(store, run_id, wait=False):
    # No raw input or API key goes into process arguments / output logs.
    proc = subprocess.Popen([sys.executable, "-m", "paper_agent.worker", "--root", str(store.root.resolve()), "--run", run_id],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if wait:
        proc.wait()
    return proc.pid


def close_interrupted_calls(s):
    """An interrupted call is unknown, never silently replayed or called successful."""
    results = {i["call_id"] for i in s.conversation if i.get("type") == "function_call_output"}
    for item in list(s.conversation):
        if item.get("type") == "function_call" and item["call_id"] not in results:
            c = Call(item["call_id"], item["name"], item["arguments"])
            result = {"ok": False, "error": "execution_interrupted", "execution_status": "unknown; not retried"}
            s.conversation.append(result_item(c, result))
            s.event("tool_result", "강제 종료로 결과 미확정. 자동 재실행하지 않습니다.", call_id=c.id, name=c.name, result=result)
            results.add(c.id)


def child(store, run_id):
    s = store.load(run_id)
    net = None
    try:
        if s.mode == "demo":
            provider, sources = ReplayProvider(s), FixtureSources(s)
        else:
            provider = OpenAIProvider(s.model, reasoning_effort=s.reasoning_effort)
            net = Network(s.limits.network_timeout, s.limits.retries, rate_dir=store.root)
            sources = FixtureSources(s) if s.mode == "model_eval" else AcademicSources(net)
        Agent(s, provider, sources, store, lambda: (store.directory(s.id) / "stop").exists()).run()
    except Exception as e:
        # State may have been saved during the run; retain all durable observations.
        s = store.load(run_id)
        s.status = "error"
        s.stop_reason = str(e) if isinstance(e, ModelError) else f"작업 오류 ({type(e).__name__})"
        s.event("termination", s.stop_reason)
        store.save(s)
    finally:
        if net:
            net.close()


def pdf_child(store, run_id):
    from .pdf import render_pdf
    s = store.load(run_id)
    try:
        render_pdf(s, store.directory(s.id) / "briefing.pdf")
    except Exception as e:
        s.pdf_error = f"PDF 생성 실패 ({type(e).__name__}). 한글 TTF 경로를 확인하세요."
        store.save(s)


def supervise(store, run_id):
    directory = store.path(run_id)
    try:
        # One local research run at a time, including across Streamlit sessions.
        with FileLock(str(store.root / "worker.lock"), timeout=0):
            # A queued start from before a reset must never recreate deleted runs.
            if (store.root / "resetting").exists() or not (directory / "state.json").exists():
                return
            with FileLock(str(directory / "run.lock"), timeout=0):
                s = store.load(run_id)
                if s.status != "ready":
                    return
                (directory / "stop").unlink(missing_ok=True)
                s.status = "running"
                store.save(s)
                start, previous = time.monotonic(), s.usage.active_seconds
                proc = subprocess.Popen([sys.executable, "-m", "paper_agent.worker", "--child", "--root", str(store.root), "--run", run_id],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                (directory / "supervisor.pid").write_text(str(os.getpid()))
                try:
                    while proc.poll() is None:
                        elapsed = previous + time.monotonic() - start
                        cancelled = (directory / "stop").exists()
                        if cancelled or elapsed >= s.limits.seconds:
                            proc.terminate()
                            try:
                                proc.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                            s = store.load(run_id)
                            # A completed, verified result is not retroactively invalidated.
                            if s.status not in TERMINAL:
                                s.status = "cancelled" if cancelled else "incomplete"
                                s.stop_reason = "사용자가 강제 중지했습니다." if cancelled else "전체 실행 시간 상한: 작업 프로세스 강제 종료"
                                s.usage.active_seconds = elapsed
                                close_interrupted_calls(s)
                                s.event("termination", s.stop_reason)
                                store.save(s)
                            break
                        time.sleep(.2)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
                    (directory / "supervisor.pid").unlink(missing_ok=True)
                s = store.load(run_id)
                if s.status == "running":
                    s.status, s.stop_reason = "error", "작업 프로세스가 예기치 않게 종료되었습니다. 자동 재호출하지 않습니다."
                    s.event("termination", s.stop_reason)
                    close_interrupted_calls(s)
                    store.save(s)
                if s.status in TERMINAL:
                    # PDF is deterministic postprocessing, separately bounded to 30 seconds.
                    p = subprocess.Popen([sys.executable, "-m", "paper_agent.worker", "--pdf", "--root", str(store.root), "--run", run_id],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    try:
                        p.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
                        s = store.load(run_id)
                        s.pdf_error = "PDF 후처리 시간 상한 30초 초과"
                        store.save(s)
    except Timeout:
        # No new model/network calls: a second start must not duplicate an active run.
        def mark_busy(s):
            if s.status == "ready":
                s.event("busy", "다른 로컬 실행이 진행 중입니다. 종료 후 실행 버튼으로 다시 시작하세요.")
        try:
            store.update_existing(run_id, mark_busy)
        except FileNotFoundError:
            return


def reset_runs(store, timeout=40):
    """Stop active work, then remove every run (including corrupt/older records).

    Keep root lock/rate-limit files so other processes cannot bypass a held lock.
    Only UUID run directories are removed; configuration and example exports remain.
    """
    with FileLock(str(store.root / "reset.lock"), timeout=0):
        marker = store.root / "resetting"
        try:
            with FileLock(str(store.root / "state.lock"), timeout=10):
                marker.touch()
                for directory in store.run_directories():
                    (directory / "stop").touch()
            # The supervisor terminates its child and finishes bounded PDF cleanup.
            with FileLock(str(store.root / "worker.lock"), timeout=timeout):
                with FileLock(str(store.root / "state.lock"), timeout=10):
                    directories = store.run_directories()
                    for directory in directories:
                        shutil.rmtree(directory)
                    return len(directories)
        finally:
            marker.unlink(missing_ok=True)


def main():
    load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    store = Store(args.root)
    if args.child:
        child(store, args.run)
    elif args.pdf:
        pdf_child(store, args.run)
    else:
        supervise(store, args.run)


if __name__ == "__main__":
    main()
