"""
Persistent conversation memory — 'that memory thing' in the Orion diagram.
Chat history is kept in RAM for the session and mirrored to a JSON file so
Orion remembers facts and context across restarts.
"""
from __future__ import annotations

import json
import threading
from typing import Any

import config
from orion.logger import log


class Memory:
    def __init__(self, path=None) -> None:
        self.path = path or config.MEMORY_FILE
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {"history": [], "facts": []}
        self._load()

    # ---------------------------------------------------------------- storage
    def _load(self) -> None:
        try:
            if self.path.is_file():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._state.update(data)
                log.info("Memory restored from %s", self.path.name)
        except Exception as exc:
            log.warning("Memory load failed (starting fresh): %s", exc)

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(self._state, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                log.error("Memory save failed: %s", exc)

    # ---------------------------------------------------------------- chat
    @property
    def messages(self) -> list[dict[str, str]]:
        with self._lock:
            history = list(self._state.get("history", []))
            maxlen = config.BRAIN["max_history"] * 2
            if len(history) > maxlen:
                history = history[-maxlen:]
            return [{"role": "system", "content": config.SYSTEM_PROMPT}] + history

    def all_history(self) -> list[dict[str, str]]:
        """Full stored history (untruncated) — used for fact recovery."""
        with self._lock:
            return [dict(m) for m in self._state.get("history", [])]

    def add(self, role: str, content: str) -> None:
        with self._lock:
            self._state.setdefault("history", []).append(
                {"role": role, "content": str(content)}
            )
            maxlen = config.BRAIN["max_history"] * 2
            if len(self._state["history"]) > maxlen:
                self._state["history"] = self._state["history"][-maxlen:]
        self.save()

    def add_exchange(self, user: str, assistant: str) -> None:
        self.add("user", user)
        self.add("assistant", assistant)

    def clear_history(self) -> None:
        with self._lock:
            self._state["history"] = []
        self.save()

    def history_text(self, limit: int = 8) -> str:
        with self._lock:
            items = self._state.get("history", [])[-limit:]
        lines = []
        for m in items:
            tag = "You" if m["role"] == "user" else "Orion"
            lines.append(f"{tag}: {m['content']}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- facts
    def remember(self, fact: str) -> None:
        with self._lock:
            facts = self._state.setdefault("facts", [])
            if fact not in facts:
                facts.append(fact)
        self.save()

    def recall(self) -> list[str]:
        with self._lock:
            return list(self._state.get("facts", []))

    def forget(self, fact: str) -> None:
        with self._lock:
            self._state["facts"] = [f for f in self._state.get("facts", []) if f != fact]
        self.save()
