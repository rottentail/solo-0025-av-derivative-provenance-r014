"""Atomic JSON state file with serialized in-process mutations."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..errors import PersistenceFailure


T = TypeVar("T")

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": 1,
    "assets": {},
    "renditions": {},
    "provenance_edges": [],
    "integrity_checks": {},
}


class JsonStateFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if not self.path.exists():
                self._write_unlocked(deepcopy(DEFAULT_STATE))

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersistenceFailure("The durable state file is unreadable.") from exc
        if not isinstance(value, dict):
            raise PersistenceFailure("The durable state root must be an object.")
        for key, default in DEFAULT_STATE.items():
            value.setdefault(key, deepcopy(default))
        return value

    def _write_unlocked(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".state-",
            suffix=".tmp",
            dir=self.path.parent,
            delete=False,
        )
        temporary_path = Path(temporary.name)
        try:
            json.dump(
                value,
                temporary,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary.close()
            os.replace(temporary_path, self.path)
        except OSError as exc:
            temporary.close()
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise PersistenceFailure("The durable state file could not be written.") from exc

    def read(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._load_unlocked())

    def mutate(self, mutation: Callable[[dict[str, Any]], T]) -> T:
        with self._lock:
            state = self._load_unlocked()
            result = mutation(state)
            self._write_unlocked(state)
            return result
