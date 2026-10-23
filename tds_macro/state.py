"""Game-state detection from OCR and simple pixel probes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

import numpy as np

from . import vision
from .ocr import OCR, OcrLine, find_line, normalize


class State(str, Enum):
    UNKNOWN = "unknown"
    ROBLOX_HOME = "roblox_home"
    LOADING = "loading"
    LOBBY = "lobby"
    PLAY_MENU = "play_menu"
    SQUAD_SELECT = "squad_select"
    INTERMISSION = "intermission"
    MODIFIERS = "modifiers"
    OVERRIDE = "override"
    GAMEPLAY_PREP = "gameplay_prep"
    GAMEPLAY = "gameplay"
    VICTORY = "victory"
    DEFEAT = "defeat"
    DISCONNECTED = "disconnected"


@dataclass
class Detection:
    state: State
    lines: list[OcrLine]
    confidence: float = 1.0
    detail: str = ""


def _has(lines: Sequence[OcrLine], *needles: str, fuzzy: float = 0.0) -> bool:
    for n in needles:
        if find_line(lines, n, fuzzy=fuzzy) is not None:
            return True
    return False


class StateDetector:
    def __init__(self, ocr: OCR):
        self.ocr = ocr

    def detect(self, frame: np.ndarray) -> Detection:
        raw_lines = self.ocr.recognize(frame)
        # Filter out any text from our own HUD overlay if it was ever captured
        lines = [
            l
            for l in raw_lines
            if not any(
                hud_tok in l.norm
                for hud_tok in (
                    "tds macro",
                    "coins/hr",
                    "gems/hr",
                    "scouts:",
                    "f5 start",
                    "f6 pause",
                    "f8 stop",
                    "state:",
                    "wave:",
                    "cash:",
                    "/20",
                )
            )
        ]
        text = " | ".join(l.norm for l in lines)

        # End-of-match screens first: they also contain Wave/Map text.
        if (
            _has(lines, "you lost", fuzzy=0.8)
            or _has(lines, "defeat", fuzzy=0.8)
            or _has(lines, "we have to fall back", fuzzy=0.8)
        ) and (_has(lines, "return to lobby") or _has(lines, "restart match") or _has(lines, "play again")):
            return Detection(State.DEFEAT, lines, 1.0, "defeat")

        if (
            _has(lines, "triumph", fuzzy=0.8)
            or _has(lines, "victory", fuzzy=0.8)
        ) and (_has(lines, "play again") or _has(lines, "return to lobby") or _has(lines, "time completed")):
            return Detection(State.VICTORY, lines, 1.0, "triumph")

        if _has(lines, "play again") and (_has(lines, "triumph", fuzzy=0.8) or _has(lines, "time completed", fuzzy=0.8) or _has(lines, "return to lobby")):
            if _has(lines, "triumph", fuzzy=0.8):
                return Detection(State.VICTORY, lines, 1.0, "triumph")
            if _has(lines, "defeat", fuzzy=0.8):
                return Detection(State.DEFEAT, lines, 1.0, "defeat")
            return Detection(State.VICTORY, lines, 0.8, "results")
        if _has(lines, "triumph", fuzzy=0.8) and _has(lines, "wave"):
            return Detection(State.VICTORY, lines, 0.9, "triumph")
        if _has(lines, "defeat", fuzzy=0.8) and (_has(lines, "play again") or _has(lines, "return to lobby")):
            return Detection(State.DEFEAT, lines, 0.9, "defeat")
        if _has(lines, "disconnected", fuzzy=0.8) or _has(lines, "reconnect", fuzzy=0.8):
            return Detection(State.DISCONNECTED, lines, 0.9, "disconnected")

        # Modal panels.
        if _has(lines, "game modifiers") or _has(lines, "vote for modifiers") or _has(lines, "selected modifiers"):
            return Detection(State.MODIFIERS, lines, 1.0, "modifier panel")
        if (
            _has(lines, "search for maps")
            or _has(lines, "all maps")
            or _has(lines, "the menu to exit")
            or _has(lines, "anywhere off the menu")
            or (_has(lines, "override map") and _has(lines, "insane") and _has(lines, "difficulty"))
        ):
            return Detection(State.OVERRIDE, lines, 1.0, "override grid")

        # Intermission lobby.
        if _has(lines, "vote for a map") or (_has(lines, "ready") and _has(lines, "veto")):
            return Detection(State.INTERMISSION, lines, 1.0, "intermission")

        # Squad size.
        if _has(lines, "choose a squad size") or (_has(lines, "solo") and _has(lines, "duo") and _has(lines, "trio")):
            return Detection(State.SQUAD_SELECT, lines, 1.0, "squad size")

        # Play/matchmaking menu. The v2.15 menu has a Survival tab and mode cards.
        if _has(lines, "choose a gamemode") or (_has(lines, "survival") and _has(lines, "casual") and _has(lines, "intermediate")):
            return Detection(State.PLAY_MENU, lines, 1.0, "play menu")
        if _has(lines, "solar requiem") and _has(lines, "survival"):
            return Detection(State.PLAY_MENU, lines, 0.9, "play menu")

        # Main lobby.
        if _has(lines, "play") and (_has(lines, "store") or _has(lines, "items") or _has(lines, "skills")):
            return Detection(State.LOBBY, lines, 1.0, "main lobby")
        if _has(lines, "coins") and _has(lines, "gems") and _has(lines, "play"):
            return Detection(State.LOBBY, lines, 1.0, "main lobby")

        # In-match HUD (v2.15.0 shows Wave N, Ready? / Skip Wave?, $600, Quick Place, etc.).
        if _has(lines, "ready?") or (_has(lines, "ready") and _has(lines, "wave") and not _has(lines, "veto")):
            return Detection(State.GAMEPLAY_PREP, lines, 1.0, "prep")
        if _has(lines, "skip wave") or _has(lines, "quick place") or _has(lines, "sell ("):
            return Detection(State.GAMEPLAY, lines, 1.0, "in match")
        if _has(lines, "base health") and _has(lines, "wave"):
            if _has(lines, "ready") and _has(lines, "required"):
                return Detection(State.GAMEPLAY_PREP, lines, 1.0, "prep")
            return Detection(State.GAMEPLAY, lines, 0.9, "in match")
        if _has(lines, "wave") and (any("$" in l.text for l in lines) or _has(lines, "cash")):
            return Detection(State.GAMEPLAY, lines, 0.9, "in match")

        # Roblox home / game page.
        if _has(lines, "recommended for you") or _has(lines, "continue") and _has(lines, "home"):
            return Detection(State.ROBLOX_HOME, lines, 0.9, "roblox home")

        # Loading screen. Roblox's loading UI is mostly black with a small logo.
        mean = float(frame.mean())
        if mean < 65 and not lines:
            return Detection(State.LOADING, lines, 0.7, "dark/loading")
        if _has(lines, "loading", fuzzy=0.8):
            return Detection(State.LOADING, lines, 0.9, "loading")

        return Detection(State.UNKNOWN, lines, 0.0, text[:160])
