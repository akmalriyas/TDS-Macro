"""Low-level keyboard and mouse input for Roblox.

Roblox uses raw mouse deltas for its internal cursor, so a plain SetCursorPos
teleport can be ignored. Every click therefore ends with a tiny relative
movement at the target. This is the pattern that was verified against the live
v2.15.0 client.
"""
from __future__ import annotations

import ctypes
import time
from typing import Iterable, Sequence

from .config import CLICK_HOLD, CLICK_JIGGLE, CLICK_SETTLE, ensure_dpi_aware

ensure_dpi_aware()
user32 = ctypes.WinDLL("user32", use_last_error=True)

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

try:
    import pydirectinput

    pydirectinput.PAUSE = 0.02
    pydirectinput.FAILSAFE = False
except Exception:  # pragma: no cover - fallback path
    pydirectinput = None

_KEY_ALIASES = {
    "escape": "esc",
    "return": "enter",
    "control": "ctrl",
    "windows": "win",
    "pageup": "pageup",
    "pagedown": "pagedown",
}


def _key_name(key: str) -> str:
    key = key.lower()
    return _KEY_ALIASES.get(key, key)


def key_down(key: str) -> None:
    if pydirectinput is None:
        raise RuntimeError("pydirectinput is not installed")
    pydirectinput.keyDown(_key_name(key))


def key_up(key: str) -> None:
    if pydirectinput is None:
        raise RuntimeError("pydirectinput is not installed")
    pydirectinput.keyUp(_key_name(key))


def press(key: str, presses: int = 1, interval: float = 0.06) -> None:
    if pydirectinput is None:
        raise RuntimeError("pydirectinput is not installed")
    pydirectinput.press(_key_name(key), presses=presses, interval=interval)


def type_text(text: str, interval: float = 0.04) -> None:
    """Type an ASCII string character-by-character using pydirectinput."""
    if pydirectinput is None:
        raise RuntimeError("pydirectinput is not installed")
    for ch in text:
        if ch == " ":
            pydirectinput.press("space")
        else:
            pydirectinput.press(ch.lower())
        time.sleep(interval)


def hold_keys(keys: Iterable[str], duration: float, release: bool = True) -> None:
    keys = list(keys)
    for k in keys:
        key_down(k)
    time.sleep(duration)
    if release:
        for k in reversed(keys):
            key_up(k)


def move_rel(dx: int, dy: int) -> None:
    user32.mouse_event(MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)


def cursor_pos() -> tuple[int, int]:
    import ctypes.wintypes as wt

    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move_to(x: int | float, y: int | float, jiggle: int = CLICK_JIGGLE, raw: bool = False) -> None:
    """Move the OS cursor to a physical pixel position and wake Roblox's cursor.

    Unless raw=True, (x, y) is treated as a reference coordinate (2560x1440 space)
    and translated to physical client screen pixels via viewport.to_screen.
    """
    if not raw:
        from . import viewport
        x, y = viewport.to_screen(x, y)
    x, y = int(round(x)), int(round(y))
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    if jiggle:
        # A relative movement at the destination makes Roblox register the
        # cursor position before the click arrives.
        user32.mouse_event(MOUSEEVENTF_MOVE, jiggle, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_MOVE, -jiggle, 0, 0, 0)
        time.sleep(0.03)


def mouse_down(button: str = "left") -> None:
    flag = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
    user32.mouse_event(flag, 0, 0, 0, 0)


def mouse_up(button: str = "left") -> None:
    flag = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
    user32.mouse_event(flag, 0, 0, 0, 0)


def click(x: int, y: int, hold: float = CLICK_HOLD, button: str = "left", settle: float = CLICK_SETTLE) -> None:
    move_to(x, y)
    time.sleep(0.06)
    mouse_down(button)
    time.sleep(hold)
    mouse_up(button)
    time.sleep(settle)


def click_box(box, hold: float = CLICK_HOLD, button: str = "left") -> None:
    x, y, w, h = box
    click(x + w // 2, y + h // 2, hold=hold, button=button)


def double_click(x: int, y: int, interval: float = 0.12) -> None:
    click(x, y, hold=0.05, settle=0.02)
    time.sleep(interval)
    click(x, y, hold=0.05, settle=0.05)


def wheel(clicks: int, x: int | None = None, y: int | None = None) -> None:
    if x is not None and y is not None:
        move_to(x, y, jiggle=0)
    if clicks == 0:
        return
    step_delta = 120 if clicks > 0 else -120
    for _ in range(abs(int(clicks))):
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, step_delta, 0)
        time.sleep(0.025)
    time.sleep(0.10)


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", steps: int = 24, duration: float = 0.35) -> None:
    """Drag with relative movement, useful for camera rotation and carousels."""
    from . import viewport
    sx1, sy1 = viewport.to_screen(x1, y1)
    sx2, sy2 = viewport.to_screen(x2, y2)
    move_to(sx1, sy1, raw=True)
    time.sleep(0.05)
    mouse_down(button)
    time.sleep(0.05)
    dx, dy = sx2 - sx1, sy2 - sy1
    step_delay = duration / max(1, steps)
    for i in range(1, steps + 1):
        move_rel(round(dx / steps), round(dy / steps))
        time.sleep(step_delay)
    mouse_up(button)
    time.sleep(0.12)


def rotate_camera(dx: int, dy: int, steps: int = 30) -> None:
    """Right-mouse drag used to rotate the Roblox camera."""
    move_to(1280, 500, jiggle=0)
    mouse_down("right")
    time.sleep(0.06)
    step_x = round(dx / max(1, steps))
    step_y = round(dy / max(1, steps))
    for _ in range(steps):
        move_rel(step_x, step_y)
        time.sleep(0.012)
    time.sleep(0.05)
    mouse_up("right")
    time.sleep(0.08)
