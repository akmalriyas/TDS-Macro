"""Computer-vision helpers: color buttons, templates, and layout probes."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

import cv2
import numpy as np

from .config import ASSETS
from .ocr import Box


def crop(frame: np.ndarray, box: Box | tuple[int, int, int, int]) -> np.ndarray:
    if isinstance(box, Box):
        x, y, w, h = box.tuple
    else:
        x, y, w, h = box
    return frame[max(0, y) : max(0, y + h), max(0, x) : max(0, x + w)]


def save_crop(frame: np.ndarray, box: Box | tuple[int, int, int, int], name: str) -> Path:
    path = ASSETS / name
    cv2.imwrite(str(path), crop(frame, box))
    return path


def green_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (35, 70, 70), (88, 255, 255))


def red_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, (0, 110, 110), (12, 255, 255))
    m2 = cv2.inRange(hsv, (168, 110, 110), (179, 255, 255))
    return cv2.bitwise_or(m1, m2)


def yellow_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (15, 100, 100), (38, 255, 255))


def _boxes_from_mask(mask: np.ndarray, min_area: int = 400, max_boxes: int = 20) -> list[Box]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        boxes.append((area, Box(x, y, w, h)))
    boxes.sort(key=lambda t: t[0], reverse=True)
    return [b for _, b in boxes[:max_boxes]]


def find_green_buttons(
    frame: np.ndarray,
    region: Optional[tuple[int, int, int, int]] = None,
    min_area: int = 800,
    max_boxes: int = 12,
) -> list[Box]:
    mask = green_mask(frame)
    if region is not None:
        x, y, w, h = region
        m = np.zeros_like(mask)
        m[max(0, y) : y + h, max(0, x) : x + w] = mask[max(0, y) : y + h, max(0, x) : x + w]
        mask = m
    return _boxes_from_mask(mask, min_area, max_boxes)


def find_green_button(
    frame: np.ndarray,
    region: Optional[tuple[int, int, int, int]] = None,
    min_area: int = 800,
) -> Optional[Box]:
    boxes = find_green_buttons(frame, region, min_area)
    return boxes[0] if boxes else None


def find_red_buttons(
    frame: np.ndarray,
    region: Optional[tuple[int, int, int, int]] = None,
    min_area: int = 300,
    max_boxes: int = 12,
) -> list[Box]:
    mask = red_mask(frame)
    if region is not None:
        x, y, w, h = region
        m = np.zeros_like(mask)
        m[max(0, y) : y + h, max(0, x) : x + w] = mask[max(0, y) : y + h, max(0, x) : x + w]
        mask = m
    return _boxes_from_mask(mask, min_area, max_boxes)


def find_red_button(
    frame: np.ndarray,
    region: Optional[tuple[int, int, int, int]] = None,
    min_area: int = 300,
) -> Optional[Box]:
    boxes = find_red_buttons(frame, region, min_area)
    return boxes[0] if boxes else None


def load_template(name: str) -> Optional[np.ndarray]:
    path = ASSETS / name
    if not path.exists():
        return None
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return img


def match_template(
    frame: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.82,
    region: Optional[tuple[int, int, int, int]] = None,
    max_results: int = 8,
    scales: Sequence[float] = (1.0,),
) -> list[tuple[float, Box]]:
    if template is None or template.size == 0:
        return []
    ox = oy = 0
    hay = frame
    if region is not None:
        x, y, w, h = region
        hay = frame[max(0, y) : y + h, max(0, x) : x + w]
        ox, oy = max(0, x), max(0, y)
    results: list[tuple[float, Box]] = []
    for scale in scales:
        t = template if scale == 1.0 else cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if t.shape[0] > hay.shape[0] or t.shape[1] > hay.shape[1]:
            continue
        res = cv2.matchTemplate(hay, t, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for x, y in zip(xs, ys):
            score = float(res[y, x])
            w, h = t.shape[1], t.shape[0]
            results.append((score, Box(int(x + ox), int(y + oy), w, h)))
    results.sort(key=lambda t: t[0], reverse=True)
    # non-max suppression
    kept: list[tuple[float, Box]] = []
    for score, box in results:
        duplicate = False
        for _, kb in kept:
            ix = max(0, min(box.x + box.w, kb.x + kb.w) - max(box.x, kb.x))
            iy = max(0, min(box.y + box.h, kb.y + kb.h) - max(box.y, kb.y))
            inter = ix * iy
            if inter > 0.5 * min(box.w * box.h, kb.w * kb.h):
                duplicate = True
                break
        if not duplicate:
            kept.append((score, box))
        if len(kept) >= max_results:
            break
    return kept


def match_template_best(
    frame: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.82,
    region: Optional[tuple[int, int, int, int]] = None,
    scales: Sequence[float] = (1.0,),
) -> Optional[Box]:
    results = match_template(frame, template, threshold, region, max_results=1, scales=scales)
    return results[0][1] if results else None


def color_fraction(frame: np.ndarray, mask: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / float(mask.size)
