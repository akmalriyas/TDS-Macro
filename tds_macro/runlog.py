"""Persistent run logging and hourly statistics."""
from __future__ import annotations

import csv
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .config import LOGS


FIELDS = [
    "run_id",
    "started_at",
    "ended_at",
    "duration_s",
    "result",
    "map",
    "mode",
    "difficulty",
    "wave",
    "coins_before",
    "gems_before",
    "coins_after",
    "gems_after",
    "coin_delta",
    "gem_delta",
    "reward_coins",
    "reward_xp",
    "time_completed",
    "notes",
]


@dataclass
class RunRecord:
    run_id: str
    started_at: str
    ended_at: str = ""
    duration_s: float = 0.0
    result: str = "running"
    map: str = ""
    mode: str = "Survival"
    difficulty: str = "Easy"
    wave: int = 0
    coins_before: Optional[int] = None
    gems_before: Optional[int] = None
    coins_after: Optional[int] = None
    gems_after: Optional[int] = None
    coin_delta: Optional[int] = None
    gem_delta: Optional[int] = None
    reward_coins: Optional[int] = None
    reward_xp: Optional[int] = None
    time_completed: str = ""
    notes: str = ""

    @classmethod
    def start_new(
        cls,
        run_index: int = 1,
        gamemode: str = "Easy",
        map_name: str = "Dead Ahead",
        modifiers: Optional[list[str]] = None,
    ) -> "RunRecord":
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(
            run_id=f"run_{run_index:04d}_{int(datetime.now(timezone.utc).timestamp())}",
            started_at=now_iso,
            map=map_name,
            mode="Survival",
            difficulty=gamemode,
            notes=",".join(modifiers) if modifiers else "",
        )

    def finish(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        if not self.ended_at:
            self.ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self.duration_s <= 0.0 and self.started_at and self.ended_at:
            try:
                t0 = datetime.fromisoformat(self.started_at)
                t1 = datetime.fromisoformat(self.ended_at)
                self.duration_s = max(1.0, (t1 - t0).total_seconds())
            except Exception:
                pass
        if self.coins_before is not None and self.coins_after is not None:
            self.coin_delta = self.coins_after - self.coins_before
        elif self.coin_delta is None and self.reward_coins is not None:
            self.coin_delta = self.reward_coins
        if self.gems_before is not None and self.gems_after is not None:
            self.gem_delta = self.gems_after - self.gems_before
        elif self.gem_delta is None:
            self.gem_delta = 0


class RunLog:
    def __init__(self, directory: Path = LOGS):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / "runs.jsonl"
        self.csv = self.dir / "runs.csv"
        self._lock = threading.Lock()
        if not self.csv.exists():
            with self.csv.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=FIELDS).writeheader()

    def append(self, record: RunRecord) -> None:
        data = asdict(record)
        with self._lock:
            with self.jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            with self.csv.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writerow({k: data.get(k, "") for k in FIELDS})

    def records(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        out = []
        for line in self.jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def hourly(self, hours: int = 24) -> list[dict]:
        records = self.records()
        if not records:
            return []

        dt_records: list[tuple[datetime, dict]] = []
        for r in records:
            ts = r.get("ended_at") or r.get("started_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_records.append((dt, r))
            except ValueError:
                continue

        if not dt_records:
            return []

        now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        latest_rec = max(x[0] for x in dt_records).replace(minute=0, second=0, microsecond=0)
        end_dt = max(latest_rec, now_utc)
        start_dt = end_dt - timedelta(hours=hours - 1)

        buckets: dict[str, dict] = {}
        curr = start_dt
        while curr <= end_dt:
            key = curr.strftime("%Y-%m-%d %H:00")
            buckets[key] = {
                "hour": key,
                "runs": 0,
                "wins": 0,
                "losses": 0,
                "coins": 0,
                "gems": 0,
                "seconds": 0.0,
            }
            curr += timedelta(hours=1)

        for dt, r in dt_records:
            key = dt.strftime("%Y-%m-%d %H:00")
            if key in buckets:
                b = buckets[key]
                b["runs"] += 1
                result = (r.get("result") or "").lower()
                if result in ("victory", "triumph", "win"):
                    b["wins"] += 1
                elif result in ("defeat", "loss"):
                    b["losses"] += 1
                b["coins"] += int(r.get("coin_delta") or r.get("reward_coins") or 0)
                b["gems"] += int(r.get("gem_delta") or 0)
                b["seconds"] += float(r.get("duration_s") or 0)

        return [buckets[k] for k in sorted(buckets)]

    def summary(self) -> dict:
        recs = [r for r in self.records() if r.get("result") != "running"]
        runs = len(recs)
        wins = sum(1 for r in recs if (r.get("result") or "").lower() in ("victory", "triumph", "win"))
        losses = sum(1 for r in recs if (r.get("result") or "").lower() in ("defeat", "loss", "error"))
        coins = sum(int(r.get("coin_delta") or r.get("reward_coins") or 0) for r in recs)
        gems = sum(int(r.get("gem_delta") or 0) for r in recs)
        xp = sum(int(r.get("reward_xp") or 0) for r in recs)
        hours = sum(float(r.get("duration_s") or 0) for r in recs) / 3600.0
        eff_hours = max(hours, 1e-6) if hours > 0 else 0.0
        return {
            "runs": runs,
            "wins": wins,
            "losses": losses,
            "coins": coins,
            "gems": gems,
            "hours": hours,
            "coins_total": coins,
            "gems_total": gems,
            "xp_total": xp,
            "coins_per_hour": (coins / eff_hours) if eff_hours > 0 else 0.0,
            "gems_per_hour": (gems / eff_hours) if eff_hours > 0 else 0.0,
            "xp_per_hour": (xp / eff_hours) if eff_hours > 0 else 0.0,
        }
