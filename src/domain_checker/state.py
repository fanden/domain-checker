from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .models import TaskState


def state_filename(words: list[str]) -> str:
    key = ",".join(sorted(w.lower() for w in words))
    h = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"state_{h}.json"


class StateManager:
    def __init__(self, data_dir: Path, words: list[str]):
        self.data_dir = data_dir
        self.words = words
        self.filepath = data_dir / state_filename(words)
        self._state: TaskState | None = None

    @property
    def state(self) -> TaskState | None:
        return self._state

    @state.setter
    def state(self, value: TaskState) -> None:
        self._state = value

    def exists(self) -> bool:
        return self.filepath.exists()

    def load(self) -> TaskState:
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._state = TaskState.from_dict(data)
        return self._state

    def save(self, state: TaskState | None = None) -> None:
        if state is not None:
            self._state = state
        if self._state is None:
            return
        self._state.updated_at = __import__("time").time()
        self._save_atomic(self._state)

    def save_sync(self) -> None:
        """Synchronous save for use in signal handlers."""
        self.save()

    def _save_atomic(self, state: TaskState) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.data_dir), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2)
            os.replace(tmp_path, str(self.filepath))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def delete(self) -> None:
        if self.filepath.exists():
            self.filepath.unlink()
