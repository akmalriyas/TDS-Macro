"""Global Win32 hotkey watchdog with configurable hotkeys."""
from __future__ import annotations

import ctypes
import threading
import time
from typing import Callable, Optional

import pydirectinput as pdi

user32 = ctypes.windll.user32

VK_MAP: dict[str, int] = {
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "NUMPAD0": 0x60,
    "NUMPAD1": 0x61,
    "NUMPAD2": 0x62,
    "NUMPAD3": 0x63,
    "NUMPAD4": 0x64,
    "NUMPAD5": 0x65,
    "NUMPAD6": 0x66,
    "NUMPAD7": 0x67,
    "NUMPAD8": 0x68,
    "NUMPAD9": 0x69,
}


def release_all_game_keys() -> None:
    """Release all movement/action keys so the character never keeps walking after pause/stop."""
    for k in ("w", "a", "s", "d", "e", "q", "i", "o", "space"):
        try:
            pdi.keyUp(k)
        except Exception:
            pass


class HotkeyWatchdog:
    """Polls Win32 GetAsyncKeyState at 25 Hz with user-configurable hotkey mappings."""

    def __init__(
        self,
        on_start: Optional[Callable[[], None]] = None,
        on_pause: Optional[Callable[[], None]] = None,
        on_overlay: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        key_start: str = "F1",
        key_pause: str = "F2",
        key_stop: str = "F3",
        key_overlay: str = "F7",
    ) -> None:
        self.on_start = on_start
        self.on_pause = on_pause
        self.on_overlay = on_overlay
        self.on_stop = on_stop
        self.key_start = key_start.upper()
        self.key_pause = key_pause.upper()
        self.key_stop = key_stop.upper()
        self.key_overlay = key_overlay.upper()
        self._stop_event = threading.Event()
        self._pressed: dict[int, bool] = {}
        self._thread = threading.Thread(target=self._loop, name="tds-hotkey-watchdog", daemon=True)

    def set_keys(
        self,
        start: Optional[str] = None,
        pause: Optional[str] = None,
        stop: Optional[str] = None,
        overlay: Optional[str] = None,
    ) -> None:
        if start:
            self.key_start = start.upper()
        if pause:
            self.key_pause = pause.upper()
        if stop:
            self.key_stop = stop.upper()
        if overlay:
            self.key_overlay = overlay.upper()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def close(self) -> None:
        self._stop_event.set()

    def _check_vk(self, vk: int) -> bool:
        state = user32.GetAsyncKeyState(vk)
        is_down = bool(state & 0x8000)
        was_down = self._pressed.get(vk, False)
        self._pressed[vk] = is_down
        return is_down and not was_down

    def _vk(self, key_name: str) -> Optional[int]:
        return VK_MAP.get(key_name)

    def _loop(self) -> None:
        while not self._stop_event.wait(0.04):
            try:
                vk_start = self._vk(self.key_start)
                vk_pause = self._vk(self.key_pause)
                vk_stop = self._vk(self.key_stop)
                vk_overlay = self._vk(self.key_overlay)

                # Start / Resume
                if vk_start and self._check_vk(vk_start) and self.on_start:
                    self.on_start()
                # Pause / Resume
                if vk_pause and self._check_vk(vk_pause) and self.on_pause:
                    release_all_game_keys()
                    self.on_pause()
                # Toggle HUD Overlay
                if vk_overlay and self._check_vk(vk_overlay) and self.on_overlay:
                    self.on_overlay()
                # Emergency Stop
                if vk_stop and self._check_vk(vk_stop) and self.on_stop:
                    release_all_game_keys()
                    self.on_stop()
            except Exception:
                pass
