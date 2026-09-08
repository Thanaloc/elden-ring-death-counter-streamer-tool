"""
Double compteur : un total qui ne redescend jamais tout seul, et un
compteur de boss que le streamer remet a zero quand il veut.

L'etat est persiste sur disque a chaque mutation, pour survivre a un
crash d'OBS ou du script en plein milieu d'un stream.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_PATH = Path.home() / ".elden-death-counter" / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeathLog:
    def __init__(self, path: Path = DEFAULT_STATE_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._listeners: list = []
        self._state = self._load()

    # ------------------------------------------------------------ stockage

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                data.setdefault("total", 0)
                data.setdefault("boss", {"name": "", "count": 0})
                data.setdefault("history", [])
                return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"total": 0, "boss": {"name": "", "count": 0}, "history": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------ diffusion

    def subscribe(self, callback) -> None:
        """callback(snapshot: dict) appele a chaque changement."""
        with self._lock:
            self._listeners.append(callback)

    def unsubscribe(self, callback) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total": self._state["total"],
                "boss_name": self._state["boss"]["name"],
                "boss_count": self._state["boss"]["count"],
            }

    def _commit(self, event: str = "update") -> dict:
        self._save()
        snap = self.snapshot()
        snap["event"] = event
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception:
                pass
        return snap

    # ------------------------------------------------------------ mutations

    def record_death(self) -> dict:
        with self._lock:
            self._state["total"] += 1
            self._state["boss"]["count"] += 1
            return self._commit("death")

    def adjust(self, delta: int) -> dict:
        """Correction manuelle : s'applique aux deux compteurs."""
        with self._lock:
            self._state["total"] = max(0, self._state["total"] + delta)
            self._state["boss"]["count"] = max(0, self._state["boss"]["count"] + delta)
            return self._commit()

    def set_boss(self, name: str, keep_count: bool = False) -> dict:
        with self._lock:
            self._state["boss"]["name"] = name
            if not keep_count:
                self._state["boss"]["count"] = 0
            return self._commit()

    def reset_boss(self) -> dict:
        """Remet le compteur de boss a zero sans rien archiver."""
        with self._lock:
            self._state["boss"]["count"] = 0
            return self._commit()

    def clear_boss(self, next_boss: str = "") -> dict:
        """Boss vaincu : on archive le score puis on repart de zero."""
        with self._lock:
            boss = self._state["boss"]
            if boss["name"] or boss["count"]:
                self._state["history"].append({
                    "name": boss["name"] or "Boss sans nom",
                    "deaths": boss["count"],
                    "cleared_at": _now(),
                })
            boss["name"] = next_boss
            boss["count"] = 0
            return self._commit("cleared")

    def reset_all(self) -> dict:
        with self._lock:
            self._state = {"total": 0, "boss": {"name": "", "count": 0}, "history": []}
            return self._commit()

    @property
    def history(self) -> list:
        with self._lock:
            return list(self._state["history"])
