"""Resolution-independent coordinate space.

All flows, OCR regions, colour checks and click targets in this project are
written for a 2560x1440 reference frame. This module makes that true on any
monitor:

* Capture: the Roblox client area is grabbed at its native size and resized to
  REF_W x REF_H, so every pixel ROI in the code base reads the same UI region.
* Input: every absolute cursor position goes through ``to_screen``, which maps
  a reference coordinate onto the real client area (offset + scale).

Roblox 3D viewports use a fixed vertical FOV, and the TDS UI is laid out in
scale units, so at the same aspect ratio (16:9) the picture scales uniformly.
Other aspect ratios still run, but the layout can differ; ``status()`` reports
this so the setup screen can warn the user.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
import time
from dataclasses import dataclass
from typing import Optional

REF_W = 2560
REF_H = 1440
REF_ASPECT = REF_W / REF_H
ASPECT_TOLERANCE = 0.02  # 16:9 +/- 2 %
MIN_CLIENT_H = 720       # below this OCR becomes unreliable

_user32 = ctypes.WinDLL("user32", use_last_error=True)


@dataclass(frozen=True)
class Viewport:
    """Roblox client area in physical screen pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def sx(self) -> float:
        return self.width / REF_W

    @property
    def sy(self) -> float:
        return self.height / REF_H

    @property
    def is_reference(self) -> bool:
        return self.width == REF_W and self.height == REF_H

    @property
    def aspect(self) -> float:
        return self.width / max(1, self.height)


_DEFAULT = Viewport(0, 0, REF_W, REF_H)
_lock = threading.Lock()
_current: Viewport = _DEFAULT
_last_refresh = 0.0
_REFRESH_S = 1.0


def client_viewport(hwnd: int) -> Optional[Viewport]:
    """Return the client rect of ``hwnd`` in screen coordinates."""
    rect = wt.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    origin = wt.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return Viewport(origin.x, origin.y, w, h)


def set_from_hwnd(hwnd: Optional[int]) -> Viewport:
    """Refresh the active viewport from a window handle (cheap; safe to call often)."""
    global _current, _last_refresh
    vp = client_viewport(hwnd) if hwnd else None
    with _lock:
        if vp is not None:
            _current = vp
        _last_refresh = time.time()
        return _current


def set_viewport(vp: Viewport) -> None:
    global _current, _last_refresh
    with _lock:
        _current = vp
        _last_refresh = time.time()


def current(refresh: bool = True) -> Viewport:
    """Active viewport. Re-reads the Roblox window at most once per second."""
    if refresh and time.time() - _last_refresh > _REFRESH_S:
        try:
            from .window import find_window

            info = find_window()
            set_from_hwnd(info.hwnd if info else None)
        except Exception:
            pass
    with _lock:
        return _current


def to_screen(x: float, y: float) -> tuple[int, int]:
    """Map a reference (2560x1440) coordinate to a physical screen pixel."""
    vp = current()
    return (
        int(round(vp.left + x * vp.sx)),
        int(round(vp.top + y * vp.sy)),
    )


def to_screen_3d(x: float, y: float) -> tuple[int, int]:
    """Map a reference (2560x1440) 3D coordinate to physical client screen pixels.

    In Roblox, the camera uses a fixed vertical FOV (70 deg). 3D world projections
    maintain aspect ratio and scale uniformly by client height relative to REF_H (1440),
    originating from the center of the client viewport. This guarantees that 3D placements
    and tower clicks remain pixel-perfect across 1080p, 1440p, 4K, and windowed modes.
    """
    vp = current()
    scale = vp.height / float(REF_H)
    cx = vp.left + vp.width / 2.0
    cy = vp.top + vp.height / 2.0
    return (
        int(round(cx + (x - (REF_W / 2.0)) * scale)),
        int(round(cy + (y - (REF_H / 2.0)) * scale)),
    )


def scale_delta(dx: float, dy: float) -> tuple[int, int]:
    """Scale a reference-space distance (UI drags) to physical pixels."""
    vp = current()
    return int(round(dx * vp.sx)), int(round(dy * vp.sy))


def normalize_frame(frame):
    """Resize a client-area frame to the reference resolution if needed."""
    h, w = frame.shape[:2]
    if w == REF_W and h == REF_H:
        return frame
    import cv2

    interp = cv2.INTER_AREA if w > REF_W else cv2.INTER_CUBIC
    return cv2.resize(frame, (REF_W, REF_H), interpolation=interp)


def status(vp: Optional[Viewport] = None) -> dict:
    """Describe whether the current window size is supported."""
    vp = vp or current()
    aspect_ok = abs(vp.aspect - REF_ASPECT) / REF_ASPECT <= ASPECT_TOLERANCE
    size_ok = vp.height >= MIN_CLIENT_H
    if aspect_ok and size_ok:
        level, msg = "ok", f"{vp.width}x{vp.height} (16:9)"
    elif not size_ok:
        level, msg = "error", f"Roblox window is {vp.width}x{vp.height}; needs at least 1280x720"
    else:
        level, msg = "warn", (
            f"Roblox window is {vp.width}x{vp.height} ({vp.aspect:.2f}:1). "
            "Use a 16:9 resolution or windowed 16:9 for reliable clicks."
        )
    return {
        "level": level,
        "message": msg,
        "width": vp.width,
        "height": vp.height,
        "scale": round(vp.sy, 4),
    }
