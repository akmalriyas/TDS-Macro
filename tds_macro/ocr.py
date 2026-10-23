"""Windows OCR helpers (winocr / Windows.Media.Ocr)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Optional, Sequence

import cv2
import numpy as np
from PIL import Image

try:
    import winocr
except Exception:  # pragma: no cover
    winocr = None


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def expanded(self, pad: int) -> "Box":
        return Box(self.x - pad, self.y - pad, self.w + 2 * pad, self.h + 2 * pad)


@dataclass
class OcrLine:
    text: str
    box: Box
    words: list["OcrWord"] = field(default_factory=list)

    @property
    def norm(self) -> str:
        return normalize(self.text)


@dataclass
class OcrWord:
    text: str
    box: Box

    @property
    def norm(self) -> str:
        return normalize(self.text)


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("0", "o") if False else text
    text = re.sub(r"[^a-z0-9$%.,:+\-/ ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _rect_to_box(r: dict, scale: float, ox: int, oy: int) -> Box:
    return Box(
        int(round(r.get("x", 0) / scale + ox)),
        int(round(r.get("y", 0) / scale + oy)),
        int(round(r.get("width", 0) / scale)),
        int(round(r.get("height", 0) / scale)),
    )


class OCR:
    def __init__(self, lang: str = "en", default_scale: float = 1.0):
        self.lang = lang
        self.default_scale = default_scale
        self._cache_key = None
        self._cache_lines: list[OcrLine] = []
        self.last_error: Optional[str] = None
        if winocr is None:
            raise RuntimeError("winocr is not installed; run: pip install winocr")

    def recognize(
        self,
        frame: np.ndarray,
        region: Optional[tuple[int, int, int, int]] = None,
        scale: Optional[float] = None,
        grayscale: bool = False,
    ) -> list[OcrLine]:
        if frame is None or frame.size == 0:
            return []
        scale = self.default_scale if scale is None else scale
        ox = oy = 0
        img = frame
        if region is not None:
            x, y, w, h = region
            x = max(0, x)
            y = max(0, y)
            w = min(w, frame.shape[1] - x)
            h = min(h, frame.shape[0] - y)
            if w <= 0 or h <= 0:
                return []
            img = frame[y : y + h, x : x + w]
            ox, oy = x, y
        if grayscale:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        try:
            result = winocr.recognize_pil_sync(pil, self.lang)
        except Exception as exc:  # OCR engine can throw on odd frames
            self.last_error = repr(exc)
            return []
        lines: list[OcrLine] = []
        for line in result.get("lines", []):
            words: list[OcrWord] = []
            for w in line.get("words", []):
                rect = w.get("bounding_rect", {})
                words.append(OcrWord(w.get("text", ""), _rect_to_box(rect, scale, ox, oy)))
            if not words:
                continue
            x = min(w.box.x for w in words)
            y = min(w.box.y for w in words)
            x2 = max(w.box.x + w.box.w for w in words)
            y2 = max(w.box.y + w.box.h for w in words)
            text = line.get("text", " ".join(w.text for w in words)).strip()
            lines.append(OcrLine(text, Box(x, y, x2 - x, y2 - y), words))
        return lines

    def recognize_cached(
        self,
        frame: np.ndarray,
        region: Optional[tuple[int, int, int, int]] = None,
        scale: Optional[float] = None,
    ) -> list[OcrLine]:
        key = (id(frame), region, scale)
        if key == self._cache_key:
            return self._cache_lines
        lines = self.recognize(frame, region, scale)
        self._cache_key = key
        self._cache_lines = lines
        return lines


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def find_line(
    lines: Iterable[OcrLine],
    target: str,
    *,
    fuzzy: float = 0.0,
    region: Optional[tuple[int, int, int, int]] = None,
    exact: bool = False,
) -> Optional[OcrLine]:
    target_n = normalize(target)
    best: Optional[OcrLine] = None
    best_score = 0.0
    for line in lines:
        if region is not None:
            x, y, w, h = region
            if not (line.box.x + line.box.w > x and line.box.x < x + w and line.box.y + line.box.h > y and line.box.y < y + h):
                continue
        n = line.norm
        if exact and n == target_n:
            return line
        if target_n and target_n in n:
            # Prefer the tightest match (shortest extra text).
            score = 1.0 - min(1.0, (len(n) - len(target_n)) / max(1, len(n))) * 0.2
            if score > best_score:
                best, best_score = line, score
        elif fuzzy > 0:
            score = ratio(n, target_n)
            if score >= fuzzy and score > best_score:
                best, best_score = line, score
    return best


def find_all(
    lines: Iterable[OcrLine],
    target: str,
    *,
    fuzzy: float = 0.0,
    region: Optional[tuple[int, int, int, int]] = None,
) -> list[OcrLine]:
    target_n = normalize(target)
    out: list[OcrLine] = []
    for line in lines:
        if region is not None:
            x, y, w, h = region
            if not (line.box.x + line.box.w > x and line.box.x < x + w and line.box.y + line.box.h > y and line.box.y < y + h):
                continue
        n = line.norm
        if target_n in n or (fuzzy and ratio(n, target_n) >= fuzzy):
            out.append(line)
    return out


_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def parse_number(text: str) -> Optional[float]:
    if not text:
        return None
    m = _NUM_RE.search(text.replace(" ", ""))
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    suffix = text[m.end() : m.end() + 1].lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    elif suffix == "b":
        value *= 1_000_000_000
    return value


def parse_int(text: str) -> Optional[int]:
    v = parse_number(text)
    return int(v) if v is not None else None


def text_near(
    lines: Sequence[OcrLine],
    anchor: OcrLine,
    direction: str = "below",
    max_distance: float = math.inf,
) -> Optional[OcrLine]:
    ax, ay = anchor.box.center
    candidates = []
    for line in lines:
        if line is anchor:
            continue
        x, y = line.box.center
        if direction == "below" and y <= ay:
            continue
        if direction == "above" and y >= ay:
            continue
        if direction == "right" and x <= ax:
            continue
        if direction == "left" and x >= ax:
            continue
        dist = math.hypot(x - ax, y - ay)
        if dist <= max_distance:
            candidates.append((dist, line))
    return min(candidates, key=lambda t: t[0])[1] if candidates else None
