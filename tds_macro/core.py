"""High-level macro controller shared by all flows."""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

import numpy as np
from rich.console import Console

from . import input as inp
from . import vision, window
from .capture import Capture
from .config import RunSettings, TEMP
from .ocr import Box, OCR, OcrLine, find_line, parse_int, text_near
from .state import Detection, State, StateDetector


class MacroError(RuntimeError):
    pass


class Macro:
    def __init__(self, settings: Optional[RunSettings] = None, console: Optional[Console] = None):
        self.settings = settings or RunSettings()
        self.console = console or Console()
        self.capture = Capture()
        self.ocr = OCR()
        self.detector = StateDetector(self.ocr)
        self.window_info = window.find_window()
        if self.window_info:
            from . import viewport
            viewport.set_from_hwnd(self.window_info.hwnd)
        self._snap_count = 0
        self._last_input = time.time()
        self.scout_checked: bool = False
        self.paused: bool = False
        self.stop_requested: bool = False
        self.current_state: State = State.UNKNOWN
        self.current_wave: Optional[int] = None
        self.current_cash: Optional[int] = None
        self.scouts_placed: int = 0
        self.last_coins: Optional[int] = None
        self.last_gems: Optional[int] = None
        self.log_history: list[str] = []
        self.on_status_change: Optional[Callable[[], None]] = None
        self._keepalive_stop = threading.Event()
        self._keepalive_interval = 300.0  # Roblox idle kick is 20 minutes (1200s); 5 mins is plenty
        self._keepalive_thread = threading.Thread(target=self._keepalive_loop, name="tds-keepalive", daemon=True)
        self._keepalive_thread.start()

    # ------------------------------------------------------------------ basics
    def log(self, message: str, style: str = "") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        plain = re.sub(r"\[/?[^\]]+\]", "", f"{ts}  {message}")
        self.log_history.append(plain)
        if len(self.log_history) > 300:
            self.log_history = self.log_history[-300:]
        self.console.print(f"[dim]{ts}[/dim] {message}", style=style)
        self.notify_status()

    def notify_status(self) -> None:
        cb = self.on_status_change
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def check_interrupts(self) -> None:
        while self.paused and not self.stop_requested:
            time.sleep(0.1)
        if self.stop_requested:
            raise MacroError("Macro stopped by user")

    def sleep(self, seconds: float) -> None:
        deadline = time.time() + max(0.0, seconds)
        while time.time() < deadline:
            self.check_interrupts()
            time.sleep(min(0.1, max(0.01, deadline - time.time())))

    def touch(self) -> None:
        self._last_input = time.time()

    def _keepalive_loop(self) -> None:
        # TDS kicks idle players after 20 minutes. Keepalive should only be active
        # in the lobby to prevent disconnection, NEVER inside an active match!
        while not self._keepalive_stop.wait(10.0):
            if time.time() - self._last_input < self._keepalive_interval:
                continue
            # NEVER jump or send keepalive inputs during match gameplay
            if self.current_state in (State.GAMEPLAY, State.GAMEPLAY_PREP):
                continue
            try:
                info = window.find_window()
                if info is not None:
                    self.window_info = window.focus_window(info)
                    # Non-intrusive nudge in lobby only
                    inp.rotate_camera(1, 0)
                    time.sleep(0.05)
                    inp.rotate_camera(-1, 0)
                    self.touch()
                    self.log("keepalive camera nudge in lobby", "dim")
            except Exception:
                pass

    def focus(self) -> None:
        info = window.focus_window(self.window_info)
        if info is None:
            raise MacroError("Roblox window not found")
        self.window_info = info
        from . import viewport
        viewport.set_from_hwnd(info.hwnd)
        time.sleep(0.08)

    def grab(self) -> np.ndarray:
        return self.capture.grab()

    def snap(self, tag: str = "frame", frame: Optional[np.ndarray] = None) -> Path:
        frame = self.grab() if frame is None else frame
        self._snap_count += 1
        name = f"{self._snap_count:04d}_{tag}.png"
        return self.capture.save(frame, name)

    def ocr_frame(self, frame: Optional[np.ndarray] = None, region: Optional[tuple[int, int, int, int]] = None) -> list[OcrLine]:
        frame = self.grab() if frame is None else frame
        return self.ocr.recognize(frame, region)

    def detect(self, frame: Optional[np.ndarray] = None) -> Detection:
        frame = self.grab() if frame is None else frame
        det = self.detector.detect(frame)
        self.current_state = det.state
        self.notify_status()
        return det

    # ---------------------------------------------------------------- waiting
    def wait_for_state(
        self,
        targets: State | Iterable[State],
        timeout: float = 60.0,
        interval: float = 0.55,
        refresh_focus: bool = True,
    ) -> Detection:
        if isinstance(targets, State):
            targets = [targets]
        targets = list(targets)
        deadline = time.time() + timeout
        last: Optional[Detection] = None
        while time.time() < deadline:
            if refresh_focus:
                self.focus()
            frame = self.grab()
            det = self.detector.detect(frame)
            last = det
            if det.state in targets:
                self.log(f"state -> [bold]{det.state.value}[/bold] ({det.detail})", "green")
                return det
            time.sleep(interval)
        detail = last.detail if last else "no frame"
        raise MacroError(f"timed out waiting for {[s.value for s in targets]}; last={last.state.value if last else '?'} ({detail})")

    def wait_for_text(self, target: str, timeout: float = 20.0, fuzzy: float = 0.0, region: Optional[tuple[int, int, int, int]] = None) -> OcrLine:
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.grab()
            lines = self.ocr.recognize(frame, region)
            line = find_line(lines, target, fuzzy=fuzzy, region=region)
            if line is not None:
                return line
            time.sleep(0.4)
        raise MacroError(f"text not found: {target!r}")

    # ---------------------------------------------------------------- clicking
    def click_box(self, box: Box, hold: float = inp.CLICK_HOLD) -> None:
        self.focus()
        inp.click_box(box.tuple, hold=hold)
        self.touch()
        time.sleep(0.12)

    def click_text(
        self,
        target: str,
        *,
        timeout: float = 8.0,
        region: Optional[tuple[int, int, int, int]] = None,
        fuzzy: float = 0.0,
        index: int = 0,
        pad: int = 0,
        hold: float = inp.CLICK_HOLD,
    ) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.grab()
            # Recognize on full frame so Windows OCR has complete context, then filter by region
            lines = self.ocr.recognize(frame)
            matches = [l for l in lines if find_line([l], target, fuzzy=fuzzy, region=region) is not None]
            if matches:
                matches.sort(key=lambda l: (l.box.y, l.box.x))
                line = matches[min(index, len(matches) - 1)]
                box = line.box.expanded(pad)
                self.log(f"click text {target!r} at {box.center}", "cyan")
                self.click_box(box, hold=hold)
                return True
            time.sleep(0.35)
        self.log(f"text not found: {target!r}", "red")
        return False

    def click_green(self, region: Optional[tuple[int, int, int, int]] = None, min_area: int = 800, index: int = 0, hold: float = inp.CLICK_HOLD) -> bool:
        self.focus()
        frame = self.grab()
        boxes = vision.find_green_buttons(frame, region, min_area)
        if not boxes:
            return False
        box = boxes[min(index, len(boxes) - 1)]
        self.log(f"click green at {box.center} ({box.w}x{box.h})", "cyan")
        inp.click_box(box.tuple, hold=hold)
        self.touch()
        time.sleep(0.12)
        return True

    def click_fixed(self, x: int, y: int, hold: float = inp.CLICK_HOLD) -> None:
        self.focus()
        self.log(f"click fixed ({x},{y})", "cyan")
        inp.click(x, y, hold=hold)
        self.touch()
        time.sleep(0.1)

    def click_3d(self, x: int, y: int, hold: float = inp.CLICK_HOLD) -> None:
        self.focus()
        inp.click_3d(x, y, hold=hold)
        self.touch()
        time.sleep(0.1)

    # -------------------------------------------------------------- keyboard
    def press(self, key: str, times: int = 1, interval: float = 0.08) -> None:
        self.check_interrupts()
        self.focus()
        inp.press(key, presses=times, interval=interval)
        self.touch()
        time.sleep(0.12)

    def hold(self, keys: Sequence[str], duration: float) -> None:
        self.check_interrupts()
        self.focus()
        inp.hold_keys(keys, duration)
        self.touch()
        time.sleep(0.12)

    def zoom_in(self, key_duration: float = 0.35, wheel_clicks: int = 5) -> None:
        """Zoom camera in using Roblox 'I' key and mouse wheel."""
        self.check_interrupts()
        self.focus()
        if key_duration > 0:
            inp.hold_keys(["i"], key_duration)
        if wheel_clicks > 0:
            inp.wheel(wheel_clicks, 1280, 650)
        self.touch()
        time.sleep(0.12)

    def zoom_out(self, key_duration: float = 1.5, wheel_clicks: int = 15) -> None:
        """Zoom camera out using Roblox 'O' key and mouse wheel."""
        self.check_interrupts()
        self.focus()
        if key_duration > 0:
            inp.hold_keys(["o"], key_duration)
        if wheel_clicks > 0:
            inp.wheel(-wheel_clicks, 1280, 650)
        self.touch()
        time.sleep(0.12)

    # --------------------------------------------------------------- currencies
    def read_lobby_currencies(self, frame: Optional[np.ndarray] = None) -> tuple[Optional[int], Optional[int]]:
        frame = self.grab() if frame is None else frame
        # Scan top-right corner first (live v2.15 HUD in 0002_inventory.png), then left column.
        regions = [
            (2100, 0, 460, 300),
            (0, 200, 750, 1240),
            (1800, 200, 760, 1100),
        ]
        coins = gems = None
        for reg in regions:
            lines = self.ocr.recognize(frame, reg, scale=1.5 if reg[3] <= 320 else 1.0)
            cl = find_line(lines, "coins")
            gl = find_line(lines, "gems")
            if cl and coins is None:
                n = text_near(lines, cl, "below", max_distance=160)
                if n:
                    coins = parse_int(n.text)
                if coins is None:
                    coins = parse_int(cl.text.replace("coins", ""))
            if gl and gems is None:
                n = text_near(lines, gl, "below", max_distance=160)
                if n:
                    gems = parse_int(n.text)
                if gems is None:
                    gems = parse_int(gl.text.replace("gems", ""))
            if coins is None or gems is None:
                # In compact HUD mode (refs/221208.png and 0002_inventory.png), Coins and Gems
                # are two stacked integer lines without the words "Coins"/"Gems".
                num_lines = []
                for ln in lines:
                    if any(
                        w in ln.norm
                        for w in ("lvl", "level", "items", "store", "rewards", "index", "play", "/", "tds", "wave", "cash")
                    ):
                        continue
                    v = parse_int(ln.text)
                    if v is not None and v >= 0 and re.fullmatch(r"[\d,.\s]+", ln.text.strip()):
                        num_lines.append((ln.box.y, v))
                num_lines.sort(key=lambda t: t[0])
                if len(num_lines) >= 2:
                    if coins is None:
                        coins = num_lines[0][1]
                    if gems is None:
                        gems = num_lines[1][1]
            if coins is not None and gems is not None:
                break
        if coins is not None:
            self.last_coins = coins
        if gems is not None:
            self.last_gems = gems
        self.notify_status()
        return coins, gems

    def read_bottom_hud(self, frame: Optional[np.ndarray] = None) -> tuple[Optional[int], tuple[Optional[int], Optional[int]]]:
        """Read exact cash and placed tower count simultaneously from bottom hotbar HUD."""
        frame = self.grab() if frame is None else frame
        h, w = frame.shape[:2]
        # Broaden crop region to guarantee coverage across all resolutions & hotbar offsets
        y1, y2 = max(0, 1260), min(h, 1435)
        x1, x2 = max(0, 1340), min(w, 1850)
        crop = frame[y1:y2, x1:x2]
        cash = None
        towers = (None, None)

        if crop.size > 0:
            import cv2
            # 1. Tower count parser (multi-scale check)
            for scale in [1.0, 2.0, 2.5]:
                img = crop if scale == 1.0 else cv2.resize(crop, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                lines = self.ocr.recognize(img)
                for line in lines:
                    clean = re.sub(r"[oO]", "0", line.text)
                    m = re.search(r"(\d{1,2})\s*[/@|;:!1zZ\[\]\\(\)\s]\s*(4[01zZ])", clean)
                    if m:
                        towers = (int(m.group(1)), 41)
                        self.scouts_placed = max(self.scouts_placed, towers[0])
                        break
                if towers[0] is not None:
                    break

            # 2. Cash parser (multi-scale check)
            for scale in [1.0, 2.0, 2.5]:
                img = crop if scale == 1.0 else cv2.resize(crop, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                lines = self.ocr.recognize(img)
                for line in lines:
                    text_str = line.text.strip()
                    if towers[0] is not None and str(towers[1]) in text_str:
                        continue
                    v = self._parse_cash_token(text_str)
                    if v is not None:
                        cash = v
                        self.current_cash = v
                        break
                if cash is not None:
                    break

        if cash is not None or towers[0] is not None:
            self.notify_status()

        return cash, towers

    def _parse_cash_token(self, text: str) -> Optional[int]:
        """Parse integer cash value from OCR string, handling currency symbols, K notation, and character noise."""
        text = text.strip()
        if not text:
            return None
        # 'K' or 'k' notation (e.g. $47.39K -> 47390, 19.74k -> 19740)
        m_k = re.search(r"[$sScC]?\s*(\d+(?:\.\d+)?)\s*[kK]", text)
        if m_k:
            try:
                return int(float(m_k.group(1)) * 1000)
            except Exception:
                pass
        # Normalize currency prefixes
        clean = re.sub(r"^[$sScC¢&+\-\s]+", "$", text).strip()
        has_dollar = clean.startswith("$")
        num_part = clean[1:].strip().replace(",", "") if has_dollar else clean.replace(",", "")
        # Normalize digit substitutions
        trans = str.maketrans({
            'o': '0', 'O': '0', 'D': '0',
            'l': '1', 'I': '1', '|': '1', 'i': '1', '!': '1',
            'z': '2', 'Z': '2',
        })
        num_part = num_part.translate(trans)
        m_num = re.search(r"(\d+)", num_part)
        if m_num:
            try:
                val = int(m_num.group(1))
                # Must have explicit dollar prefix OR be at least 25 (minimum bounty/cost in TDS)
                # and strictly exclude tower count cap 40 or 41
                if (has_dollar or val >= 25) and 0 <= val <= 9999999 and val not in (40, 41):
                    return val
            except Exception:
                pass
        return None

    def read_cash(self, frame: Optional[np.ndarray] = None) -> Optional[int]:
        """Read current cash from HUD with multi-tier, multi-scale detection across resolutions.
        Checks top-right match leaderboard first, then bottom hotbar, then fallbacks."""
        frame = self.grab() if frame is None else frame
        import cv2

        # 1. Primary Check: Top-right match leaderboard cash column ($Cash for player Flare)
        # Bounded in normalized frame at x: 2450..2555, y: 95..160
        h, w = frame.shape[:2]
        y1, y2 = max(0, 95), min(h, 160)
        x1, x2 = max(0, 2450), min(w, 2555)
        tr_crop = frame[y1:y2, x1:x2]
        if tr_crop.size > 0:
            # Pass 1: raw multi-scale
            for scale in [1.0, 2.5, 3.0]:
                tr_img = tr_crop if scale == 1.0 else cv2.resize(tr_crop, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                for l in self.ocr.recognize(tr_img):
                    v = self._parse_cash_token(l.text)
                    if v is not None:
                        self.current_cash = v
                        self.notify_status()
                        return v

            # Pass 2: high-contrast threshold for lower resolutions (900p / 720p)
            gray = cv2.cvtColor(tr_crop, cv2.COLOR_BGR2GRAY)
            for th in [170, 180]:
                _, b = cv2.threshold(gray, th, 255, cv2.THRESH_BINARY)
                b3 = cv2.resize(b, (0, 0), fx=3.0, fy=3.0, interpolation=cv2.INTER_NEAREST)
                pad = cv2.copyMakeBorder(b3, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=0)
                for l in self.ocr.recognize(pad):
                    v = self._parse_cash_token(l.text)
                    if v is not None:
                        self.current_cash = v
                        self.notify_status()
                        return v

        # 2. Secondary Check: Bottom hotbar cash HUD
        cash, _ = self.read_bottom_hud(frame)
        if cash is not None:
            return cash

        # 3. Tertiary Check: Top-right broader search (x=2400..2555, y=70..220)
        top_right_broader = self.ocr.recognize(frame, (2400, 70, 160, 200))
        for line in top_right_broader:
            v = self._parse_cash_token(line.text)
            if v is not None:
                self.current_cash = v
                self.notify_status()
                return v

        return self.current_cash

    def read_tower_count(self, frame: Optional[np.ndarray] = None) -> tuple[Optional[int], Optional[int]]:
        """Read placed tower counter (e.g. 10/41) next to the bottom hotbar."""
        frame = self.grab() if frame is None else frame
        _, towers = self.read_bottom_hud(frame)
        if towers[0] is not None:
            return towers

        for roi in ((1460, 1330, 200, 105), (1380, 1280, 1180, 160)):
            lines = self.ocr.recognize(frame, roi)
            for line in lines:
                clean = re.sub(r"[oO]", "0", line.text)
                m = re.search(r"(\d{1,2})\s*[/@|;:!1zZ\[\]\\(\)\s]\s*(4[01zZ])", clean)
                if m:
                    placed, cap = int(m.group(1)), 41
                    self.scouts_placed = max(self.scouts_placed, placed)
                    self.notify_status()
                    return placed, cap
        return None, None

    def read_wave(self, frame: Optional[np.ndarray] = None) -> Optional[int]:
        """Read current wave number from top HUD with multi-scale recognition."""
        frame = self.grab() if frame is None else frame
        import cv2
        for roi in ((850, 20, 320, 100), (650, 0, 1260, 180)):
            x, y, w, h = roi
            crop = frame[y:y+h, x:x+w]
            if crop.size == 0:
                continue
            for sc in [1.0, 2.0]:
                img = crop if sc == 1.0 else cv2.resize(crop, (0, 0), fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR)
                lines = self.ocr.recognize(img)
                for line in lines:
                    m = re.search(r"wave\s*[:#]?\s*(\d{1,2})", line.norm)
                    if m:
                        w_num = int(m.group(1))
                        self.current_wave = w_num
                        self.notify_status()
                        return w_num
                    m_slash = re.search(r"(\d{1,2})\s*/\s*(?:20|50)", line.text)
                    if m_slash:
                        w_num = int(m_slash.group(1))
                        self.current_wave = w_num
                        self.notify_status()
                        return w_num
                # If during prep, 'Wave:' is visible without number or '0/1 required' is present
                for line in lines:
                    if "wave" in line.norm and ("prep" in line.norm or "0/1" in line.text or "required" in line.norm):
                        self.current_wave = 0
                        self.notify_status()
                        return 0
        return self.current_wave

    # --------------------------------------------------------------- lifecycle
    def close(self) -> None:
        self._keepalive_stop.set()
        self.capture.close()
