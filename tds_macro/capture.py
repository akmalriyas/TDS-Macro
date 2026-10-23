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


class Capture:
    def __init__(self, output_idx: int = 0):
        _ensure_default_desktop()
        ensure_dpi_aware()
        import dxcam

        self._dxcam = dxcam
        self.output_idx = output_idx
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

    def grab(self, retries: int = 8) -> np.ndarray:
        """Return the current screen as a BGR uint8 array (H, W, 3)."""
        _ensure_default_desktop()
        ensure_dpi_aware()
        for _ in range(retries):
            try:
                frame = self.camera.grab()
            except Exception:
                frame = None
            if frame is not None:
                # dxcam returns RGB; OpenCV uses BGR.
                bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                _LAST_FRAMES[self.output_idx] = bgr
                return bgr
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
        _LAST_FRAMES[self.output_idx] = bgr
        return bgr

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
