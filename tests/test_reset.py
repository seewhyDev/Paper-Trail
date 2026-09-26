import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from filelock import FileLock, Timeout

from paper_agent.worker import reset_runs, supervise


def test_reset_removes_all_runs_including_older_and_corrupt_records(state, store, tmp_path):
    for _ in range(34):
        item = state.model_copy(deep=True)
        item.id = uuid4().hex
        store.save(item)
        (store.path(item.id) / 'briefing.pdf').write_bytes(b'pdf')
    corrupt = store.directory(uuid4().hex)
    (corrupt / 'state.json').write_text('invalid')
    unrelated = store.root / 'configuration.txt'
    unrelated.write_text('preserve')
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'keep').write_text('preserve')
    (store.root / uuid4().hex).symlink_to(external, target_is_directory=True)
    assert len(store.list_runs()) == 30
    assert reset_runs(store) == 35
    assert not store.run_directories() and not store.list_runs()
    assert unrelated.exists() and (external / 'keep').exists()
    assert not (store.root / 'resetting').exists()


def test_reset_stops_active_worker_and_queued_start_cannot_restore_it(state, store, monkeypatch):
    import paper_agent.worker as worker
    store.save(state)
    original = subprocess.Popen
    started = threading.Event()
    spawned = []
    errors = []
    def spawn(args, **kwargs):
        is_child = '--child' in args
        if is_child:
            args = [sys.executable, '-c', 'import time; time.sleep(30)']
        proc = original(args, **kwargs)
        spawned.append(proc)
        if is_child:
            started.set()
        return proc
    monkeypatch.setattr(worker.subprocess, 'Popen', spawn)
    def work():
        try:
            supervise(store, state.id)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=work)
    thread.start()
    assert started.wait(5)
    assert reset_runs(store, timeout=10) == 1
    thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert all(p.poll() is not None for p in spawned)
    assert not store.path(state.id).exists()
    supervise(store, state.id)
    assert not store.path(state.id).exists()


def test_reset_does_not_delete_while_worker_lock_is_held(state, store):
    store.save(state)
    with FileLock(str(store.root / 'worker.lock')):
        with pytest.raises(Timeout):
            reset_runs(store, timeout=0)
    assert store.load(state.id).id == state.id
    assert not (store.root / 'resetting').exists()


def test_new_run_is_rejected_during_reset_and_missing_reads_do_not_recreate(state, store):
    (store.root / 'resetting').touch()
    with pytest.raises(RuntimeError):
        store.save(state)
    assert not store.path(state.id).exists()
    with pytest.raises(FileNotFoundError):
        store.load(state.id)
    with pytest.raises(FileNotFoundError):
        store.update_existing(state.id, lambda s: None)
    assert not store.path(state.id).exists()


def test_reset_confirmation_cancel_and_confirm(completed, store, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PAPER_AGENT_DATA', str(store.root))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=15).run()
    def click(label):
        next(b for b in app.button if b.label == label).click().run()
        assert not app.exception
    click('초기화')
    assert len(app.warning) == 1
    assert store.path(completed.id).exists()
    click('취소')
    assert store.path(completed.id).exists()
    click('초기화')
    click('모두 삭제')
    assert not store.run_directories()
    assert any('모든 기록을 삭제' in x.value for x in app.success)
    assert '어떤 연구' in app.title[0].value
    app.run()
    assert not app.exception and not store.run_directories()
