"""One atomic snapshot per run; an OS file lock is held by its supervisor."""
import json
import os
import re
from filelock import FileLock
from pathlib import Path

from .schema import RunState


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run identifier")
        return self.root / run_id

    def directory(self, run_id: str) -> Path:
        p = self.path(run_id)
        p.mkdir(exist_ok=True, mode=0o700)
        return p

    def save(self, state: RunState):
        with FileLock(str(self.root / "state.lock"), timeout=10):
            if (self.root / "resetting").exists() and not (self.path(state.id) / "state.json").exists():
                raise RuntimeError("기록 초기화 중입니다. 잠시 후 다시 시작하세요.")
            self._save(state)

    def _save(self, state: RunState):
        path = self.directory(state.id) / "state.json"
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            os.chmod(temp, 0o600)
            f.write(state.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)

    def load(self, run_id: str) -> RunState:
        return RunState.model_validate_json((self.path(run_id) / "state.json").read_text())

    def update_existing(self, run_id, change):
        with FileLock(str(self.root / "state.lock"), timeout=10):
            state = self.load(run_id)
            change(state)
            self._save(state)
            return state

    def run_directories(self):
        return [p for p in self.root.iterdir() if re.fullmatch(r"[a-f0-9]{32}", p.name)
                and p.is_dir() and not p.is_symlink()]

    def list_runs(self) -> list[RunState]:
        found = []
        for directory in self.run_directories():
            path = directory / "state.json"
            try:
                found.append((path.stat().st_mtime, RunState.model_validate_json(path.read_text())))
            except (ValueError, OSError):
                continue
        return [s for _, s in sorted(found, key=lambda x: x[0], reverse=True)[:30]]

    def trace(self, state: RunState) -> str:
        # No conversation items / hidden reasoning / environment / credentials.
        return json.dumps({"run_id": state.id, "mode": state.mode, "model": state.model,
                           "reasoning_effort": state.reasoning_effort,
                           "status": state.status, "stop_reason": state.stop_reason,
                           "usage": state.usage.model_dump(),
                           "events": [e.model_dump() for e in state.events]}, ensure_ascii=False, indent=2)
