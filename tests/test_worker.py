import subprocess
import sys
import threading
import time

from paper_agent.provider import Call, call_item
from paper_agent.worker import close_interrupted_calls, launch, supervise


def test_real_worker_subprocess_completes_demo_once(state, store):
    store.save(state)
    launch(store, state.id, wait=True)
    done = store.load(state.id)
    assert done.status == "completed"
    assert (store.directory(state.id) / "briefing.pdf").exists()
    before = done.model_dump()
    launch(store, state.id, wait=True)
    assert store.load(state.id).model_dump() == before


def test_supervisor_cancels_blocked_child(state, store, monkeypatch):
    import paper_agent.worker as worker
    store.save(state)
    original = subprocess.Popen
    spawned = []
    def spawn(args, **kwargs):
        if "--child" in args:
            args = [sys.executable, "-c", "import time; time.sleep(30)"]
        proc = original(args, **kwargs)
        spawned.append(proc)
        return proc
    monkeypatch.setattr(worker.subprocess, "Popen", spawn)
    def cancel():
        time.sleep(.4)
        (store.directory(state.id) / "stop").touch()
    thread = threading.Thread(target=cancel)
    thread.start()
    supervise(store, state.id)
    thread.join()
    assert store.load(state.id).status == "cancelled"
    assert all(p.poll() is not None for p in spawned)


def test_supervisor_wall_time_kills_blocked_child(state, store, monkeypatch):
    import paper_agent.worker as worker
    state.limits.seconds = 5
    store.save(state)
    original = subprocess.Popen
    def spawn(args, **kwargs):
        if "--child" in args:
            args = [sys.executable, "-c", "import time; time.sleep(30)"]
        return original(args, **kwargs)
    monkeypatch.setattr(worker.subprocess, "Popen", spawn)
    start = time.monotonic()
    supervise(store, state.id)
    done = store.load(state.id)
    assert done.status == "incomplete" and "시간" in done.stop_reason
    assert time.monotonic() - start < 10


def test_interrupted_calls_are_linked_errors_not_faked_success(state):
    state.conversation = [call_item(Call("a", "fetch_fulltext", "{}")), call_item(Call("b", "read_chunks", "{}"))]
    close_interrupted_calls(state)
    assert [i["call_id"] for i in state.conversation if i["type"] == "function_call_output"] == ["a", "b"]
    assert all(e.result["ok"] is False for e in state.events)
