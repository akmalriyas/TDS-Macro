"""Desktop shell: a frameless WebView2 window rendering the HTML UI in ./web with a floating in-game HUD."""
from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path
from typing import Any, Optional

import webview
import win32con
import win32gui

from ..config import RunSettings, ensure_dpi_aware
from .backend import Core

from ..paths import WEB_DIR


class Api:
    """Methods exposed to JavaScript as window.pywebview.api.*  (underscore attrs stay private)."""

    def __init__(self) -> None:
        self._core = Core()
        self._window: Any = None
        self._hud_window: Any = None
        self._maximized = False

    def _bind(self, window: Any, hud_window: Any = None) -> None:
        self._window = window
        self._hud_window = hud_window
        self._core.window = window
        self._core.hud_window = hud_window

    # state
    def get_state(self) -> dict:
        return self._core.get_state()

    def get_log(self) -> list:
        return self._core.get_log()

    def get_analytics(self) -> dict:
        return self._core.get_analytics()

    def presets(self) -> dict:
        return self._core.presets()

    # control
    def start(self) -> None:
        self._core.start()

    def pause(self) -> None:
        self._core.toggle_pause()

    def stop(self) -> None:
        self._core.stop()

    # queue
    def save_task(self, data: dict) -> None:
        self._core.save_task(data)

    def delete_task(self, task_id: str) -> None:
        self._core.queue.remove(task_id)

    def move_task(self, task_id: str, delta: int) -> None:
        self._core.queue.move(task_id, int(delta))

    def reorder_tasks(self, ids: list) -> None:
        self._core.queue.reorder([str(i) for i in ids])

    def reset_progress(self) -> None:
        self._core.queue.reset_progress()

    # settings
    def get_settings(self) -> dict:
        return self._core.get_settings()

    def save_settings(self, data: dict) -> dict:
        return self._core.save_settings(data)

    def set_hud_visible(self, flag: bool) -> None:
        self._core.set_hud_visible(bool(flag))

    def test_webhook(self, url: str) -> dict:
        return self._core.test_webhook(url)

    def open_logs(self) -> None:
        self._core.open_logs()

    def check_requirements(self) -> dict:
        return self._core.check_requirements()

    def fix_requirement(self, action_id: str) -> dict:
        return self._core.fix_requirement(action_id)

    def is_setup_complete(self) -> bool:
        return self._core.is_setup_complete()

    def mark_setup_complete(self) -> None:
        self._core.mark_setup_complete()

    def check_updates(self) -> dict:
        return self._core.check_updates()

    def download_update(self, url: str) -> dict:
        return self._core.download_update(url)

    def install_update(self, path: str) -> dict:
        return self._core.install_update(path)

    def relaunch_setup(self) -> None:
        import threading
        _relaunch_setup()
        threading.Timer(0.1, self.win_close).start()

    # window chrome
    def win_minimize(self) -> None:
        self._window.minimize()

    def win_maximize(self) -> bool:
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized
        return self._maximized

    def win_close(self) -> None:
        self._core.shutdown()
        if self._hud_window is not None:
            try:
                self._hud_window.destroy()
            except Exception:
                pass
        self._window.destroy()

    def set_on_top(self, flag: bool) -> None:
        self._window.on_top = bool(flag)


def _setup_hud_clickthrough() -> None:
    """Pin HUD overlay with click-through and toolwindow ex-styles so it floats seamlessly over Roblox."""
    time.sleep(1.2)
    try:
        hwnd = win32gui.FindWindow(None, "Flare Macro HUD")
        if hwnd:
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                ex | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW,
            )
    except Exception:
        pass


class SetupApi:
    def __init__(self, window: Any = None):
        self._window = window

    def check_requirements(self) -> dict:
        from .. import validator
        return validator.check_all()

    def fix_requirement(self, action_id: str) -> dict:
        from .. import validator
        return validator.fix_requirement(action_id)

    def complete_and_launch(self) -> None:
        import threading
        from .. import validator
        validator.mark_setup_completed()
        _spawn_main_app()
        if self._window:
            threading.Timer(0.1, self._window.destroy).start()

    def win_minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def win_close(self) -> None:
        if self._window:
            self._window.destroy()


def _spawn_main_app() -> None:
    import subprocess
    import sys
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable, 'ui']
    else:
        cmd = [sys.executable, '-m', 'tds_macro', 'ui']
    subprocess.Popen(cmd)


def _relaunch_setup() -> None:
    import subprocess
    import sys
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable, '--setup']
    else:
        cmd = [sys.executable, '-m', 'tds_macro', '--setup']
    subprocess.Popen(cmd)


def launch_setup() -> int:
    ensure_dpi_aware()
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    mutex = kernel32.CreateMutexW(None, False, 'Global\\FlareMacro_SingleInstance_Setup')
    if kernel32.GetLastError() == 183:
        existing = user32.FindWindowW(None, 'Flare Macro - Setup')
        if existing:
            user32.ShowWindow(existing, 9)
            user32.SetForegroundWindow(existing)
        return 0
    api = SetupApi()
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    w, h = 640, 720
    x = max(0, (screen_w - w) // 2)
    y = max(0, (screen_h - h) // 2)

    window = webview.create_window(
        'Flare Macro - Setup',
        url=str(WEB_DIR / 'setup.html'),
        js_api=api,
        width=w,
        height=h,
        x=x,
        y=y,
        min_size=(600, 680),
        frameless=True,
        easy_drag=False,
        background_color='#07080B',
        text_select=False,
    )
    api._window = window
    webview.start(debug=False)
    return 0


def launch_ui(settings: Optional[RunSettings] = None) -> int:
    ensure_dpi_aware()
    # Single-instance check
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    mutex = kernel32.CreateMutexW(None, False, 'Global\\FlareMacro_SingleInstance_App')
    if kernel32.GetLastError() == 183:
        existing = user32.FindWindowW(None, 'Flare Macro - TDS')
        if existing:
            user32.ShowWindow(existing, 9)
            user32.SetForegroundWindow(existing)
        return 0
    api = Api()

    # Calculate HUD position in top-right corner below Roblox title bar
    user32 = ctypes.windll.user32
    screen_w = user32.GetSystemMetrics(0)
    hud_w, hud_h = 350, 185
    hud_x = max(20, screen_w - hud_w - 24)
    hud_y = 52

    window = webview.create_window(
        "Flare Macro - TDS",
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=980,
        height=780,
        min_size=(900, 700),
        frameless=True,
        easy_drag=False,
        background_color="#07080B",
        text_select=False,
    )

    hud_window = webview.create_window(
        "Flare Macro HUD",
        url=str(WEB_DIR / "hud.html"),
        width=hud_w,
        height=hud_h,
        x=hud_x,
        y=hud_y,
        frameless=True,
        on_top=True,
        transparent=True,
        hidden=not api._core.settings.show_hud,
        text_select=False,
        background_color="#07080B",
    )

    api._bind(window, hud_window)

    def on_closed():
        api._core.shutdown()
        try:
            hud_window.destroy()
        except Exception:
            pass

    window.events.closed += on_closed
    threading.Thread(target=_setup_hud_clickthrough, daemon=True).start()

    webview.start(debug=False)
    return 0
