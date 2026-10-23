"""Screen capture using DXGI Desktop Duplication (dxcam)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import SCREEN_H, SCREEN_W, TEMP, ensure_dpi_aware


_SHARED_CAMERAS: dict[int, object] = {}
_LAST_FRAMES: dict[int, np.ndarray] = {}


def _ensure_default_desktop() -> None:
    """Ensure the current thread is attached to the interactive Default desktop."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


def grab_window(hwnd: int) -> Optional[np.ndarray]:
    """Capture ONLY the target window surface via Win32 PrintWindow (PW_RENDERFULLCONTENT).
    Completely immune to other applications, popups, or overlays covering or obscuring the game."""
    try:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        rect = wt.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None

        hdc = user32.GetDC(hwnd)
        if not hdc:
            return None
        mdc = gdi32.CreateCompatibleDC(hdc)
        hbm = gdi32.CreateCompatibleBitmap(hdc, w, h)
        old_bm = gdi32.SelectObject(mdc, hbm)

        # PW_RENDERFULLCONTENT = 2 grabs the window composition surface directly from DWM
        res = user32.PrintWindow(hwnd, mdc, 2)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wt.DWORD),
                ("biWidth", wt.LONG),
                ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf = np.zeros((h, w, 4), dtype=np.uint8)
        gdi32.GetDIBits(mdc, hbm, 0, h, buf.ctypes.data_as(ctypes.c_void_p), ctypes.byref(bmi), 0)

        gdi32.SelectObject(mdc, old_bm)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)

        if res and buf[:, :, :3].mean() > 5.0:
            return cv2.cvtColor(buf, cv2.COLOR_BGRA2BGR)
    except Exception:
        pass
    return None


class Capture:
    def __init__(self, output_idx: int = 0):
        _ensure_default_desktop()
        ensure_dpi_aware()
        import dxcam

        self._dxcam = dxcam
        self.output_idx = output_idx
        self.target_hwnd: Optional[int] = None
        self.camera = _SHARED_CAMERAS.get(output_idx)
        if self.camera is None:
            self._create()

    def _create(self) -> None:
        ensure_dpi_aware()
        existing = _SHARED_CAMERAS.get(self.output_idx)
        if existing is not None:
            try:
                existing.release()
            except Exception:
                pass
            _SHARED_CAMERAS.pop(self.output_idx, None)
        try:
            self.camera = self._dxcam.create(output_idx=self.output_idx)
        except Exception:
            self.camera = None
        if self.camera is None:
            raise RuntimeError("dxcam could not create a capture device")
        _SHARED_CAMERAS[self.output_idx] = self.camera

    def grab(self, retries: int = 8, hwnd: Optional[int] = None) -> np.ndarray:
        """Return the current frame as a BGR uint8 array (H, W, 3).
        Prioritizes capturing ONLY the Roblox window client area directly to prevent interference."""
        _ensure_default_desktop()
        ensure_dpi_aware()

        # 1. Window-isolated capture: captures ONLY Roblox, ignoring background/covering apps
        target_hwnd = hwnd or self.target_hwnd
        if target_hwnd is None:
            try:
                from .window import find_window
                info = find_window()
                if info is not None:
                    target_hwnd = info.hwnd
                    self.target_hwnd = target_hwnd
            except Exception:
                pass

        if target_hwnd:
            win_frame = grab_window(target_hwnd)
            if win_frame is not None:
                from . import viewport
                viewport.set_from_hwnd(target_hwnd)
                norm = viewport.normalize_frame(win_frame)
                _LAST_FRAMES[self.output_idx] = norm
                return norm

        # 2. Desktop fallback via DXGI Desktop Duplication
        from . import viewport

        for _ in range(retries):
            try:
                frame = self.camera.grab()
            except Exception:
                frame = None
            if frame is not None:
                # dxcam returns RGB; OpenCV uses BGR.
                bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                if target_hwnd:
                    vp = viewport.client_viewport(target_hwnd)
                    if vp and 0 <= vp.left and 0 <= vp.top and vp.left + vp.width <= bgr.shape[1] and vp.top + vp.height <= bgr.shape[0]:
                        bgr = bgr[vp.top:vp.top + vp.height, vp.left:vp.left + vp.width]
                        viewport.set_viewport(vp)
                norm = viewport.normalize_frame(bgr)
                _LAST_FRAMES[self.output_idx] = norm
                return norm
            time.sleep(0.02)
        # If the screen is completely static, DXGI Desktop Duplication returns None;
        # return the last cached frame if available before recreating the device.
        cached = _LAST_FRAMES.get(self.output_idx)
        if cached is not None:
            return cached.copy()
        # Last resort: recreate the device (display mode change etc.)
        self._create()
        frame = self.camera.grab()
        if frame is None:
            raise RuntimeError("screen capture returned no frame")
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if target_hwnd:
            vp = viewport.client_viewport(target_hwnd)
            if vp and 0 <= vp.left and 0 <= vp.top and vp.left + vp.width <= bgr.shape[1] and vp.top + vp.height <= bgr.shape[0]:
                bgr = bgr[vp.top:vp.top + vp.height, vp.left:vp.left + vp.width]
                viewport.set_viewport(vp)
        norm = viewport.normalize_frame(bgr)
        _LAST_FRAMES[self.output_idx] = norm
        return norm

    def grab_pil(self):
        from PIL import Image

        return Image.fromarray(cv2.cvtColor(self.grab(), cv2.COLOR_BGR2RGB))

    def save(self, frame: np.ndarray, name: str) -> Path:
        path = TEMP / name
        cv2.imwrite(str(path), frame)
        return path

    def grab_save(self, name: str) -> Tuple[np.ndarray, Path]:
        frame = self.grab()
        return frame, self.save(frame, name)

    def close(self) -> None:
        # Keep the shared dxcam singleton alive across runs in the same process
        # so starting a second run from the UI does not fail DXGI creation.
        pass
