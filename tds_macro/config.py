"""TDS Macro - configuration and global constants."""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "tds_macro" / "assets"
LOGS = ROOT / "logs"
TEMP = Path(os.environ.get("TEMP", str(ROOT / "tmp"))) / "tds_macro"
for _p in (ASSETS, LOGS, TEMP):
    _p.mkdir(parents=True, exist_ok=True)

PLACE_ID = 3260590327
GAME_URL = f"roblox://experiences/start?placeId={PLACE_ID}"
WINDOW_TITLE = "Roblox"

# The live game is running at this resolution. All coordinates in the code are
# physical pixels. The process is made per-monitor DPI aware in ensure_dpi_aware.
SCREEN_W = 2560
SCREEN_H = 1440

# A tiny relative nudge is needed after SetCursorPos; Roblox tracks raw mouse
# movement and otherwise may not notice the cursor teleport.
CLICK_JIGGLE = 2
CLICK_HOLD = 0.075
CLICK_SETTLE = 0.10


def ensure_dpi_aware() -> None:
    """Make this process per-monitor DPI aware and attached to the active input desktop."""
    try:
        # Attach to the interactive input desktop if launched inside a sandboxed desktop
        hinput = ctypes.windll.user32.OpenInputDesktop(0, False, 0x10000000)
        if hinput:
            ctypes.windll.user32.SetThreadDesktop(hinput)
    except Exception:
        pass
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class RunSettings:
    # Match setup
    gamemode: str = "Easy"
    squad: str = "Solo"
    map_name: str = "Dead Ahead"
    enable_modifiers: bool = True
    modifiers: tuple[str, ...] = ("Glass", "Exploding Enemies")

    # Strategy
    scout_count: int = 16
    first_upgrade_level: int = 2
    max_upgrade_before_wave: int = 20
    verify_scout_once: bool = True
    use_play_again: bool = True
    battlepass_farm: bool = False
    battlepass_interval_s: float = 12.0

    # Loop
    max_runs: int = 0  # 0 = unlimited
    retry_delay_s: float = 8.0
    wait_for_players_s: float = 0.0

    # Hotkeys
    hotkey_start: str = "F1"
    hotkey_pause: str = "F2"
    hotkey_overlay: str = "F7"
    hotkey_stop: str = "F3"

    # Webhooks
    webhook_url: str = ""
    webhook_on_triumph: bool = True
    webhook_on_defeat: bool = True
    webhook_on_error: bool = True
    webhook_hourly: bool = True

    # UI
    minimize_on_start: bool = True  # keep the panel from covering the game while the macro runs
    show_hud: bool = False

    # Logging
    log_dir: Path = field(default_factory=lambda: LOGS)
    save_debug_frames: bool = True
    debug_every_step: bool = False

    def load_persisted(self) -> RunSettings:
        """Load user-configured settings from logs/ui_settings.json if present."""
        import json
        settings_file = LOGS / "ui_settings.json"
        if settings_file.is_file():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(self, k):
                        if k == "modifiers" and isinstance(v, (list, tuple)):
                            v = tuple(v)
                        setattr(self, k, v)
            except Exception:
                pass
        return self
