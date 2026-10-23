"""Backend bridge between the web UI and the macro engine (no UI toolkit code in here)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ..config import LOGS, RunSettings
from ..core import Macro
from ..flows import runloop
from ..queue import PRESETS, QueueTask, TaskQueue
from ..runlog import RunLog
from ..watchdog import HotkeyWatchdog, release_all_game_keys
from ..webhook import send_discord_webhook

SETTINGS_FILE = LOGS / "ui_settings.json"
PERSISTED = ("webhook_url", "webhook_on_triumph", "webhook_on_defeat", "webhook_on_error", "webhook_hourly", "use_play_again", "verify_scout_once", "enable_modifiers", "modifiers", "minimize_on_start", "show_hud", "hotkey_start", "hotkey_pause", "hotkey_stop", "hotkey_overlay")


class Core:
    """All mutable app state. Kept out of the pywebview-exposed object on purpose."""

    def __init__(self) -> None:
        self.settings = RunSettings()
        self._load_settings()
        self.queue = TaskQueue()
        self.runlog = RunLog(self.settings.log_dir)
        self.macro: Optional[Macro] = None
        self.thread: Optional[threading.Thread] = None
        self.status = "IDLE"  # IDLE | RUNNING | PAUSED
        self.started_at: Optional[float] = None
        self.session_base = 0
        self.active_id: Optional[str] = None
        self.task_base = 0  # run-log length when the active task started
        self.task_runs0 = 0
        self.task_coins0 = 0
        self.lock = threading.Lock()
        self.window: Any = None
        self.hud_window: Any = None
        self.watchdog = HotkeyWatchdog(
            on_start=self.start,
            on_pause=self.toggle_pause,
            on_overlay=self.toggle_hud,
            on_stop=self.stop,
            key_start=self.settings.hotkey_start,
            key_pause=self.settings.hotkey_pause,
            key_stop=self.settings.hotkey_stop,
            key_overlay=self.settings.hotkey_overlay,
        )
        self.watchdog.start()

    # ------------------------------------------------------------ persistence
    def _load_settings(self) -> None:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        for key in PERSISTED:
            if key in data:
                val = data[key]
                if key == "modifiers" and isinstance(val, (list, tuple)):
                    val = tuple(val)
                setattr(self.settings, key, val)

    def save_settings(self, data: dict) -> dict:
        s = self.settings
        s.webhook_url = str(data.get("webhook_url", s.webhook_url)).strip()
        s.webhook_on_triumph = bool(data.get("webhook_on_triumph", s.webhook_on_triumph))
        s.webhook_on_defeat = bool(data.get("webhook_on_defeat", s.webhook_on_defeat))
        s.webhook_on_error = bool(data.get("webhook_on_error", getattr(s, "webhook_on_error", True)))
        s.webhook_hourly = bool(data.get("webhook_hourly", getattr(s, "webhook_hourly", True)))
        s.use_play_again = bool(data.get("use_play_again", s.use_play_again))
        s.verify_scout_once = bool(data.get("verify_scout_once", s.verify_scout_once))
        s.enable_modifiers = bool(data.get("enable_modifiers", getattr(s, "enable_modifiers", True)))
        if "modifiers" in data:
            raw_mods = data.get("modifiers")
            if isinstance(raw_mods, (list, tuple)):
                s.modifiers = tuple(str(x).strip() for x in raw_mods if str(x).strip())
        s.minimize_on_start = bool(data.get("minimize_on_start", s.minimize_on_start))
        s.show_hud = bool(data.get("show_hud", getattr(s, "show_hud", False)))
        s.hotkey_start = str(data.get("hotkey_start", s.hotkey_start)).upper()
        s.hotkey_pause = str(data.get("hotkey_pause", s.hotkey_pause)).upper()
        s.hotkey_stop = str(data.get("hotkey_stop", s.hotkey_stop)).upper()
        s.hotkey_overlay = str(data.get("hotkey_overlay", s.hotkey_overlay)).upper()
        self.watchdog.set_keys(
            start=s.hotkey_start,
            pause=s.hotkey_pause,
            stop=s.hotkey_stop,
            overlay=s.hotkey_overlay,
        )
        self.set_hud_visible(s.show_hud)
        try:
            payload = {}
            for k in PERSISTED:
                v = getattr(s, k)
                if isinstance(v, tuple):
                    v = list(v)
                payload[k] = v
            SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
        return self.get_settings()


    def toggle_hud(self) -> None:
        self.settings.show_hud = not self.settings.show_hud
        self.save_settings({"show_hud": self.settings.show_hud})

    def set_hud_visible(self, visible: bool) -> None:
        if self.hud_window is not None:
            try:
                if visible:
                    self.hud_window.show()
                else:
                    self.hud_window.hide()
            except Exception:
                pass

    def sync_hud(self, state_dict: dict) -> None:
        if self.hud_window is not None and self.settings.show_hud:
            try:
                payload = json.dumps(state_dict)
                self.hud_window.evaluate_js(f"updateHud({payload})")
            except Exception:
                pass

    def get_settings(self) -> dict:
        d = {k: getattr(self.settings, k) for k in PERSISTED}
        d["modifiers"] = list(self.settings.modifiers)
        return d

    # ---------------------------------------------------------------- control
    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self) -> None:
        with self.lock:
            if self.alive():
                if self.macro is not None and self.macro.paused:
                    self.macro.paused = False
                    self.status = "RUNNING"
                    self.macro.log("macro resumed", "green")
                return
            if not self.queue.tasks:
                self.status = "IDLE"
                return
            if self.queue.next_pending() is None:
                self.queue.reset_progress()
            task = self.queue.next_pending()
            if task is None:
                self.status = "IDLE"
                return
            self.macro = Macro(self.settings)
            self.status = "RUNNING"
            self.started_at = time.time()
            self.session_base = len(self.runlog.records())
            self.thread = threading.Thread(target=self._worker, name="tds-queue-worker", daemon=True)
            self.thread.start()
        if self.settings.minimize_on_start and self.window is not None:
            try:
                self.window.minimize()
            except Exception:
                pass

    def toggle_pause(self) -> None:
        if not self.alive() or self.macro is None:
            return
        self.macro.paused = not self.macro.paused
        release_all_game_keys()
        self.status = "PAUSED" if self.macro.paused else "RUNNING"
        self.macro.log("macro paused" if self.macro.paused else "macro resumed", "yellow")

    def stop(self) -> None:
        release_all_game_keys()
        if self.macro is not None:
            self.macro.stop_requested = True
            self.macro.paused = False
            self.macro.log("stop requested", "red")

    def _apply_task(self, task: QueueTask) -> None:
        spec = task.spec
        self.settings.gamemode = spec["gamemode"]
        self.settings.map_name = spec["map_name"]
        self.settings.scout_count = task.scout_count
        self.settings.max_runs = max(0, task.loop_count - task.runs_completed) if task.loop_count else 0

    def _records_since(self, base: int) -> list[dict]:
        return self.runlog.records()[base:]

    @staticmethod
    def _coins(rec: dict) -> int:
        return int(rec.get("coin_delta") or rec.get("reward_coins") or 0)

    def _sync_task(self, task: QueueTask) -> None:
        recs = self._records_since(self.task_base)
        task.runs_completed = self.task_runs0 + len(recs)
        task.coins_earned = self.task_coins0 + sum(self._coins(r) for r in recs)
        self.queue.save()

    def _worker(self) -> None:
        m = self.macro
        assert m is not None
        try:
            while not m.stop_requested:
                task = self.queue.next_pending()
                if task is None:
                    break
                self.active_id = task.id
                self.task_base = len(self.runlog.records())
                self.task_runs0, self.task_coins0 = task.runs_completed, task.coins_earned
                self._apply_task(task)
                m.log(f"queue: starting '{task.name}'", "bold cyan")
                runloop.run_forever(m, self.runlog, self.settings)
                self._sync_task(task)
                if m.stop_requested:
                    break
                task.done = True
                self.queue.save()
        except Exception as exc:  # keep the UI alive no matter what
            m.log(f"worker crashed: {exc!r}", "red")
        finally:
            active = self.queue.get(self.active_id) if self.active_id else None
            if active is not None:
                self._sync_task(active)
            self.active_id = None
            self.status = "IDLE"
            if self.settings.minimize_on_start and self.window is not None:
                try:
                    self.window.restore()
                except Exception:
                    pass
            try:
                m.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ state
    def _task_view(self, task: QueueTask) -> dict:
        d = task.to_dict()
        if task.id == self.active_id and self.alive():
            recs = self._records_since(self.task_base)
            d["runs_completed"] = self.task_runs0 + len(recs)
            d["coins_earned"] = self.task_coins0 + sum(self._coins(r) for r in recs)
        running = task.id == self.active_id and self.alive()
        d["state"] = "running" if running else ("done" if task.done else "pending")
        return d

    def _get_status_word(self) -> str:
        if self.status == "IDLE":
            return "Idle"
        if self.status == "PAUSED":
            return "Paused"
        if not self.alive() or self.macro is None:
            return "Idle"
        m = self.macro
        last = (m.log_history[-1] if m.log_history else "").lower()
        if len(last) > 9 and last[2] == ":" and last[5] == ":":
            last = last[9:].strip()
        if "triumph" in last or "victory" in last:
            return "Victory"
        if "defeat" in last:
            return "Defeat"
        if "placing scout" in last or "place" in last:
            return "Placing Scout"
        if "upgrade" in last:
            return "Upgrading Scout"
        if "vote" in last or "override" in last:
            return "Selecting Map"
        if "intermission" in last:
            return "Intermission"
        if "survival" in last or "solo" in last or "matchmaking" in last:
            return "Matchmaking"
        if "loading" in last:
            return "Loading Match"
        if "play again" in last:
            return "Replaying"
        if "error" in last or "failed" in last:
            return "Error"
        st = getattr(m, "current_state", None)
        if st is not None:
            v = getattr(st, "value", str(st)).lower()
            if "lobby" in v:
                return "Lobby"
            if "intermission" in v:
                return "Intermission"
            if "gameplay" in v:
                w = getattr(m, "current_wave", None)
                return f"Wave {w}" if w else "Wave Active"
            if "prep" in v:
                return "Starting Wave"
        return "Running"

    def get_state(self) -> dict:
        m = self.macro if self.alive() else None
        records = self.runlog.records()
        session = records[self.session_base:] if self.started_at else []
        finished = [r for r in session if r.get("result") != "running"]
        wins = sum(1 for r in finished if (r.get("result") or "").lower() in ("victory", "triumph", "win"))
        coins = sum(self._coins(r) for r in finished)
        elapsed = int(time.time() - self.started_at) if (self.started_at and self.status != "IDLE") else 0
        st = {
            "status": self.status,
            "sys": self._get_status_word(),
            "empty_queue": len(self.queue.tasks) == 0,
            "elapsed": elapsed,
            "coins": coins,
            "coins_per_hr": int(coins * 3600 / elapsed) if elapsed > 60 else 0,
            "runs": len(finished),
            "wins": wins,
            "wave": getattr(m, "current_wave", None) if m else None,
            "cash": getattr(m, "current_cash", None) if m else None,
            "scouts": getattr(m, "scouts_placed", 0) if m else 0,
            "game_state": m.current_state.value if m else None,
            "tasks": [self._task_view(t) for t in self.queue.tasks],
            "webhook": bool(self.settings.webhook_url),
            "hotkeys": {
                "start": self.settings.hotkey_start,
                "pause": self.settings.hotkey_pause,
                "stop": self.settings.hotkey_stop,
                "overlay": self.settings.hotkey_overlay,
            },
        }
        self.sync_hud(st)
        return st

    def get_log(self) -> list[str]:
        return list(self.macro.log_history[-200:]) if self.macro is not None else []

    def get_analytics(self) -> dict:
        recs = [r for r in self.runlog.records() if r.get("result") != "running"]
        rows = [
            {
                "id": r.get("run_id", ""),
                "ended": r.get("ended_at", ""),
                "result": r.get("result", ""),
                "wave": r.get("wave"),
                "coins": self._coins(r),
                "xp": int(r.get("reward_xp") or 0),
                "duration": float(r.get("duration_s") or 0),
                "map": r.get("map", ""),
                "mode": r.get("difficulty", ""),
            }
            for r in recs
        ]
        return {"summary": self.runlog.summary(), "hourly": self.runlog.hourly()[-24:], "runs": rows[-60:][::-1]}

    # ------------------------------------------------------------------ queue
    def save_task(self, data: dict) -> None:
        self.queue.upsert(data)

    def presets(self) -> dict:
        return PRESETS

    def test_webhook(self, url: str) -> dict:
        ok, msg = send_discord_webhook(
            url.strip(),
            title="Flare Macro connected",
            description="Run results and performance reports will be posted to this channel.",
            color=0xFF2A55,
            footer="Flare Macro - TDS",
        )
        return {"ok": ok, "message": msg}

    def open_logs(self) -> None:
        try:
            os.startfile(str(LOGS))  # noqa: S606
        except Exception:
            pass

    # ----------------------------------------------------------------- window
    def shutdown(self) -> None:
        self.stop()
        self.watchdog.close()
