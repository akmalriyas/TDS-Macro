"""Persistent task queue. Only strategies that the macro can really execute are offered."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .paths import QUEUE_FILE

# Presets the engine can actually run end to end. Add an entry here once a new flow exists.
PRESETS: dict[str, dict] = {
    "dead_ahead_coin_farm": {
        "label": "Dead Ahead Coin Farm",
        "map_name": "Dead Ahead",
        "gamemode": "Easy",
        "waves": 20,
        "max_scouts": 20,
        "default_scouts": 16,
    },
}


@dataclass
class QueueTask:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    preset: str = "dead_ahead_coin_farm"
    name: str = "Dead Ahead Coin Farm"
    loop_count: int = 0  # 0 = infinite
    scout_count: int = 16
    done: bool = False
    runs_completed: int = 0
    coins_earned: int = 0

    @property
    def spec(self) -> dict:
        return PRESETS[self.preset]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(
            map_name=self.spec["map_name"],
            gamemode=self.spec["gamemode"],
            waves=self.spec["waves"],
        )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "QueueTask":
        preset = d.get("preset") if d.get("preset") in PRESETS else "dead_ahead_coin_farm"
        spec = PRESETS[preset]
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            preset=preset,
            name=(str(d.get("name") or spec["label"]).strip() or spec["label"])[:48],
            loop_count=max(0, int(d.get("loop_count", 0))),
            scout_count=max(10, min(spec["max_scouts"], int(d.get("scout_count", spec["default_scouts"])))),
            done=bool(d.get("done", False)),
            runs_completed=max(0, int(d.get("runs_completed", 0))),
            coins_earned=max(0, int(d.get("coins_earned", 0))),
        )


class TaskQueue:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or QUEUE_FILE
        self.tasks: list[QueueTask] = []
        self.load()

    # ------------------------------------------------------------ persistence
    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.tasks = [QueueTask.from_dict(t) for t in data.get("tasks", [])]
        except Exception:
            self.tasks = []
        pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"tasks": [asdict(t) for t in self.tasks]}, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ---------------------------------------------------------------- queries
    def get(self, task_id: str) -> Optional[QueueTask]:
        return next((t for t in self.tasks if t.id == task_id), None)

    def next_pending(self) -> Optional[QueueTask]:
        return next((t for t in self.tasks if not t.done), None)

    # -------------------------------------------------------------- mutations
    def upsert(self, data: dict) -> QueueTask:
        task = QueueTask.from_dict(data)
        existing = self.get(task.id) if data.get("id") else None
        if existing is not None:
            task.done = existing.done
            task.runs_completed = existing.runs_completed
            task.coins_earned = existing.coins_earned
            self.tasks[self.tasks.index(existing)] = task
        else:
            self.tasks.append(task)
        self.save()
        return task

    def remove(self, task_id: str) -> None:
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.save()

    def move(self, task_id: str, delta: int) -> None:
        task = self.get(task_id)
        if task is None:
            return
        i = self.tasks.index(task)
        j = max(0, min(len(self.tasks) - 1, i + delta))
        self.tasks.insert(j, self.tasks.pop(i))
        self.save()

    def reorder(self, ids: list[str]) -> None:
        by_id = {t.id: t for t in self.tasks}
        ordered = [by_id[i] for i in ids if i in by_id]
        ordered += [t for t in self.tasks if t.id not in ids]
        self.tasks = ordered
        self.save()

    def reset_progress(self) -> None:
        for t in self.tasks:
            t.done = False
            t.runs_completed = 0
            t.coins_earned = 0
        self.save()
