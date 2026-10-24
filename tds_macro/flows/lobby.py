"""Lobby, matchmaking, and intermission flows."""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import cv2
import numpy as np

from .. import input as inp
from .. import vision, window
from ..config import GAME_URL
from ..core import Macro, MacroError
from ..ocr import Box, find_line, parse_int
from ..state import State

PLAY_BUTTON_REGION = (800, 1180, 1000, 240)
TOP_RIGHT_CLOSE = (2268, 29)
ITEMS_REGION = (0, 500, 260, 220)
LEFT_TAB_REGION = (300, 200, 180, 460)
MODIFIER_GEAR = (64, 1373)
GLASS_ICON = (1199, 483)
BOMB_ICON = (1348, 483)
MODIFIER_COORDS: dict[str, tuple[int, int]] = {
    "glass": GLASS_ICON,
    "explosive": BOMB_ICON,
    "exploding enemies": BOMB_ICON,
    "bomb": BOMB_ICON,
}
VOTE_MODIFIERS_REGION = (1250, 1120, 550, 180)
READY_REGION = (1050, 1180, 850, 180)


def dismiss_popups(m: Macro, max_rounds: int = 5) -> bool:
    """Close daily rewards / battle-pass / login rewards overlays that cover the lobby."""
    dismissed = False
    for _ in range(max_rounds):
        frame = m.grab()
        lines = m.ocr.recognize(frame)
        text = " ".join(l.norm for l in lines)

        # 1. Login Rewards / Daily Rewards popup with a 'CLAIM' or 'CLOSE' button
        if any(k in text for k in ("login rewards", "login streak", "daily rewards", "streak", "day streak", "rewards scale", "claim!")):
            action_btn = (
                find_line(lines, "claim", exact=True)
                or find_line(lines, "claim", fuzzy=0.75)
                or find_line(lines, "close", exact=True)
                or find_line(lines, "close", fuzzy=0.75)
            )
            if action_btn is not None:
                m.log(f"closing Login Rewards popup via button '{action_btn.text}' at {action_btn.box.center}", "cyan")
                inp.click_box(action_btn.box.tuple)
                time.sleep(1.0)
                dismissed = True
                continue
            # Fallback: click bottom-center of modal where CLAIM/CLOSE button sits (y ~ 975 in 2560x1440)
            h, w = frame.shape[:2]
            m.log("clicking calibrated Login Rewards CLAIM/CLOSE button at center (1280, 975)", "yellow")
            inp.click(int(round(w * 0.50)), int(round(h * 0.678)))
            time.sleep(1.0)
            dismissed = True
            continue

        # 2. Any overlay with an explicit CLOSE button
        close_btn = find_line(lines, "close", exact=True)
        if close_btn is not None and close_btn.box.y > 400:
            m.log(f"closing overlay via CLOSE button at {close_btn.box.center}", "cyan")
            inp.click_box(close_btn.box.tuple)
            time.sleep(1.0)
            dismissed = True
            continue

        # 3. Free rewards / Reward info popups with red X
        if "free rewards" in text or "reward info" in text or "earn rewards for playing" in text:
            title = find_line(lines, "free rewards") or find_line(lines, "reward info")
            reds = vision.find_red_buttons(frame, None, min_area=250, max_boxes=40)
            candidates = [
                b
                for b in reds
                if 35 <= b.w <= 100 and 35 <= b.h <= 100 and 0.65 <= b.w / max(1, b.h) <= 1.5 and b.y > 120
            ]
            if title is not None:
                title_right = title.box.x + title.box.w
                title_cy = title.box.y + title.box.h / 2
                right_side = [
                    b
                    for b in candidates
                    if b.x >= title_right and abs((b.y + b.h / 2) - title_cy) < 190
                ]
                if right_side:
                    candidates = right_side
            candidates.sort(key=lambda b: abs(b.w * b.h - 4200))
            if candidates:
                box = candidates[0]
                m.log(f"closing rewards popup at {box.center}", "cyan")
                inp.click_box(box.tuple)
                time.sleep(1.0)
                dismissed = True
                continue
            m.log("rewards popup found but no close button", "yellow")

        break
    return dismissed


def reconnect(m: Macro) -> bool:
    """Handle the TDS idle-kick dialog, reconnecting or relaunching reliably."""
    m.log("idle disconnect / kick modal detected; recovering", "bold yellow")
    m.focus()
    time.sleep(0.4)

    for attempt in range(3):
        frame = m.grab()
        lines = m.ocr.recognize(frame)
        m.snap("disconnected", frame)

        # 1. OCR search for Reconnect button across full screen
        rec = find_line(lines, "reconnect", fuzzy=0.70)
        if rec is not None:
            m.log(f"reconnect button found at {rec.box.center}; clicking", "green")
            inp.click_box(rec.box.tuple)
            time.sleep(7.0)
            det = m.detect()
            if det.state != State.DISCONNECTED:
                m.log("reconnect succeeded!", "bold green")
                return True

        # 2. OCR search for Leave button across full screen
        leave = find_line(lines, "leave", fuzzy=0.70)
        if leave is not None:
            m.log(f"leave button found at {leave.box.center}; clicking to relaunch", "yellow")
            inp.click_box(leave.box.tuple)
            time.sleep(3.0)
            window.open_url(GAME_URL)
            time.sleep(10.0)
            return True

        # 3. Fallback calibrated clicks on standard Roblox disconnect dialog buttons:
        # On standard Roblox modal, [Leave] is at ~ (1200, 810), [Reconnect] is at ~ (1360, 810)
        m.log(f"OCR unresolved; attempting calibrated modal click on Reconnect at (1360, 810) [attempt {attempt+1}/3]", "yellow")
        inp.click(1360, 810)
        time.sleep(5.0)
        if m.detect().state != State.DISCONNECTED:
            m.log("calibrated Reconnect click succeeded!", "green")
            return True

        m.log("trying secondary modal click on [Leave] at (1200, 810) and relaunching", "yellow")
        inp.click(1200, 810)
        time.sleep(2.5)
        window.open_url(GAME_URL)
        time.sleep(10.0)
        if m.detect().state != State.DISCONNECTED:
            return True

    return False


def ensure_game(m: Macro, timeout: float = 150.0) -> State:
    """Make sure the TDS client is open and return its current state."""
    info = window.find_window()
    if info is None:
        m.log("launching Roblox via deep link", "yellow")
        info = window.launch()
        if info is None:
            raise MacroError("could not launch Roblox")
    m.window_info = window.focus_window(info)
    time.sleep(0.5)

    deadline = time.time() + timeout
    unknown_streak = 0
    while time.time() < deadline:
        det = m.detect()
        m.log(f"startup state: {det.state.value} ({det.detail})")
        unknown_streak = unknown_streak + 1 if det.state == State.UNKNOWN else 0
        if det.state == State.DISCONNECTED:
            reconnect(m)
            continue
        if det.state == State.LOBBY:
            if dismiss_popups(m):
                continue
            return det.state
        if det.state in (State.INTERMISSION, State.GAMEPLAY, State.GAMEPLAY_PREP, State.VICTORY, State.DEFEAT):
            return det.state
        if det.state == State.UNKNOWN and unknown_streak >= 3 and unknown_streak % 3 == 0:
            # An unrecognised panel (inventory, shop, ...) is covering the lobby: close it.
            m.log("unrecognised screen; trying to close a modal", "yellow")
            if close_modal(m):
                time.sleep(0.8)
                continue
        if det.state == State.UNKNOWN:
            text = " ".join(l.norm for l in det.lines)
            if "free rewards" in text or "reward info" in text or "earn rewards" in text:
                if dismiss_popups(m):
                    continue
        if det.state == State.ROBLOX_HOME:
            m.log("Roblox home detected; launching TDS", "yellow")
            window.open_url(GAME_URL)
            time.sleep(4.0)
            continue
        if det.state == State.LOADING:
            time.sleep(2.0)
            continue
        if det.state in (State.PLAY_MENU, State.SQUAD_SELECT, State.MODIFIERS, State.OVERRIDE):
            # Already in the lobby flow; let the caller handle it.
            return det.state
        time.sleep(1.0)
    raise MacroError("game did not reach a usable state")


def read_currencies(m: Macro) -> tuple[Optional[int], Optional[int]]:
    coins, gems = m.read_lobby_currencies()
    m.log(f"lobby currencies: coins={coins} gems={gems}", "magenta")
    return coins, gems


def _white_fraction(frame, box: Box) -> float:
    x, y, w, h = box.tuple
    crop = frame[max(0, y) : y + h, max(0, x) : x + w]
    if crop.size == 0:
        return 0.0
    white = (crop[:, :, 0] > 200) & (crop[:, :, 1] > 200) & (crop[:, :, 2] > 200)
    return float(white.mean())


def close_modal(m: Macro) -> bool:
    """Close a game modal using its X, without opening the Roblox menu."""
    frame = m.grab()
    lines = m.ocr.recognize(frame)
    # Most TDS panels have a small OCR-visible "x" at their top-right.
    xline = find_line(lines, "x", exact=True, region=(0, 0, 2200, 650))
    if xline is not None and 8 <= xline.box.w <= 90 and 8 <= xline.box.h <= 90:
        m.log(f"close modal via OCR x at {xline.box.center}", "cyan")
        inp.click_box(xline.box.expanded(6).tuple)
        time.sleep(0.6)
        return True

    # Otherwise find a square red button with a white X glyph.
    reds = vision.find_red_buttons(frame, None, min_area=180, max_boxes=60)
    candidates = [
        b
        for b in reds
        if 20 <= b.w <= 95 and 20 <= b.h <= 95 and 0.62 <= b.w / max(1, b.h) <= 1.55 and b.y < 750 and b.x < 2150
    ]
    scored = sorted(candidates, key=lambda b: (_white_fraction(frame, b), b.w * b.h), reverse=True)
    if scored and _white_fraction(frame, scored[0]) > 0.04:
        box = scored[0]
        m.log(f"close modal via red X at {box.center}", "cyan")
        inp.click_box(box.tuple)
        time.sleep(0.6)
        return True

    for x, y in ((1414, 94), (1659, 264), (2268, 29)):
        m.log(f"trying fixed close at ({x},{y})", "yellow")
        inp.click(x, y)
        time.sleep(0.45)
    return False


def check_scout(m: Macro, force: bool = False) -> dict:
    """Open Items once, ensure Scout is equipped, and ensure Golden is on.

    The live v2.15 inventory is OCR-driven; if a control cannot be found the
    function logs what it saw and returns a status dict instead of guessing.
    """
    if m.scout_checked and not force:
        m.log("Scout + Golden already verified this session; skipping Items check", "dim")
        return {"opened": False, "scout_found": True, "equipped": True, "golden": True, "notes": "cached"}

    status = {"opened": False, "scout_found": False, "equipped": None, "golden": None, "notes": ""}
    m.log("checking Scout loadout (once per session)", "bold")
    if not m.click_text("items", region=ITEMS_REGION, timeout=5.0):
        # Fall back to the known live left-menu position.
        m.click_fixed(140, 597)
    time.sleep(1.2)
    frame = m.grab()
    m.snap("inventory", frame)
    lines = m.ocr.recognize(frame)
    if not lines:
        status["notes"] = "inventory OCR returned nothing"
        return status
    text = " ".join(l.norm for l in lines)
    m.log(f"inventory text: {text[:240]}", "dim")
    status["opened"] = True

    scout = find_line(lines, "scout", fuzzy=0.75)
    golden = find_line(lines, "golden", fuzzy=0.75)
    status["scout_found"] = scout is not None
    status["golden"] = golden is not None

    # Equip Scout if an EQUIP button is present and the card is not equipped.
    equip = find_line(lines, "equip", fuzzy=0.8)
    unequip = find_line(lines, "unequip", fuzzy=0.8)
    if unequip is not None:
        status["equipped"] = True
    elif equip is not None:
        status["equipped"] = False
        m.log("Scout is not equipped; clicking EQUIP", "yellow")
        m.click_box(equip.box)
        time.sleep(0.8)
        status["equipped"] = True

    # Check the golden badge. The badge is bright yellow when active.
    if golden is not None:
        def golden_frac() -> float:
            f = m.grab()
            box = golden.box.expanded(30)
            gx, gy, gw, gh = box.tuple
            crop = f[max(0, gy) : gy + gh, max(0, gx) : gx + gw]
            if crop.size == 0:
                return 0.0
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            yellow = cv2.inRange(hsv, (18, 110, 110), (40, 255, 255))
            return float(yellow.mean() / 255.0)

        frac = golden_frac()
        m.log(f"golden badge yellow fraction: {frac:.3f}", "dim")
        status["golden"] = frac > 0.15
        if frac <= 0.15:
            m.log("Golden appears OFF; clicking the badge", "yellow")
            m.click_box(golden.box.expanded(10))
            time.sleep(0.7)
            frac2 = golden_frac()
            status["golden"] = frac2 > 0.15
            m.log(f"golden badge after click: {frac2:.3f}", "dim")

    # Close inventory: click the red X at (1414, 94) directly.
    m.click_fixed(1414, 94)
    time.sleep(0.4)
    if not close_modal(m):
        m.log("could not find inventory close button", "red")
    time.sleep(0.8)
    m.scout_checked = True
    return status


def open_play_menu(m: Macro, timeout: float = 30.0) -> None:
    m.log("opening Play menu", "bold")
    m.focus()
    time.sleep(0.3)

    deadline = time.time() + timeout
    while time.time() < deadline:
        det = m.detect()
        if det.state in (State.PLAY_MENU, State.SQUAD_SELECT):
            m.log("Play menu opened", "green")
            return

        # Make sure no modal or popup is covering the screen
        dismiss_popups(m, max_rounds=2)

        # Click the green PLAY button (center ~ 1280, 1220)
        if not m.click_text("play", region=(1000, 1140, 560, 220), timeout=1.0):
            if not m.click_green((1100, 1180, 360, 120), min_area=800):
                inp.click(1280, 1220, hold=0.08, settle=0.15)

        time.sleep(1.5)

    raise MacroError("timed out waiting for play_menu")


def _back_to_play_menu(m: Macro) -> None:
    det = m.detect()
    if det.state == State.SQUAD_SELECT:
        m.log("returning from squad screen to the play menu", "yellow")
        if not m.click_text("back", region=(1350, 1020, 500, 260), timeout=3.0, fuzzy=0.8):
            m.click_fixed(1614, 1127)
        time.sleep(1.4)


def select_survival_easy_solo(m: Macro) -> None:
    m.log("selecting Survival -> Easy -> Solo", "bold")
    _back_to_play_menu(m)
    # In TDS v2.15 Survival menu, "Easy" is the large hero card on the left featuring the Brute zombie
    # at (685, 1210). Clicking it selects Easy mode and directly opens Squad Select ("Selected Gamemode: Easy").
    # "Casual" is a separate smaller card to its right at (1080, 1220).
    m.click_fixed(685, 1210)
    time.sleep(1.0)
    try:
        m.wait_for_state(State.SQUAD_SELECT, timeout=6.0)
    except MacroError:
        # Fallback: click "easy" text or click the Easy hero card again
        if not m.click_text("easy", region=(400, 1000, 600, 440), timeout=3.0, fuzzy=0.8):
            m.click_fixed(685, 1210)
        m.wait_for_state(State.SQUAD_SELECT, timeout=10.0)

    if m.click_text("solo", region=(600, 580, 520, 320), timeout=8.0, fuzzy=0.8):
        m.log("clicked Solo", "green")
    else:
        m.log("Solo text not found; clicking its known position (804, 717)", "yellow")
        m.click_fixed(804, 717)
    time.sleep(1.0)


def open_modifiers(m: Macro) -> None:
    m.log("opening game modifiers", "bold")
    for dx, dy in ((0, 0), (-5, -5), (5, 5), (-10, 0)):
        m.click_fixed(MODIFIER_GEAR[0] + dx, MODIFIER_GEAR[1] + dy)
        time.sleep(0.4)
        if m.detect().state == State.MODIFIERS:
            break
    m.wait_for_state(State.MODIFIERS, timeout=8.0)
    m.snap("modifier_panel")


def select_modifiers(m: Macro) -> None:
    targets = [s.strip().lower() for s in getattr(m.settings, "modifiers", ())]
    if not targets:
        m.log("no modifiers configured in settings to select", "dim")
        return

    m.log(f"selecting modifiers: {', '.join(m.settings.modifiers)}", "bold")
    m.focus()

    # Dynamic anchor to the Game Modifiers modal based on OCR title or search bar
    frame = m.grab()
    lines = m.ocr.recognize(frame)
    title = find_line(lines, "modifiers", fuzzy=0.7) or find_line(lines, "came", fuzzy=0.7)
    search_bar = find_line(lines, "search", fuzzy=0.7)

    if title is not None:
        base_x = title.box.x
        base_y = title.box.y
    elif search_bar is not None:
        base_x = search_bar.box.x - 34
        base_y = search_bar.box.y - 110
    else:
        base_x = 902
        base_y = 236

    target_count = len(targets)
    # Calibrated tile centers from modal base (verified live):
    # Row 0, Col 1 (Glass): base_x + 297, base_y + 247 -> (1199, 483)
    # Row 0, Col 2 (Exploding Enemies): base_x + 446, base_y + 247 -> (1348, 483)
    tile1_xy = (base_x + 297, base_y + 247)
    tile2_xy = (base_x + 446, base_y + 247)

    def _get_selected_count() -> int:
        vf = m.grab()
        vlines = m.ocr.recognize(vf, (base_x, base_y + 550, 750, 420))
        vtext = " ".join(l.norm for l in vlines)
        match = re.search(r"(\d+)\s*/\s*13", vtext)
        if match:
            return int(match.group(1))
        return -1

    # 1. First check if modifiers are ALREADY selected
    cur_count = _get_selected_count()
    if cur_count == target_count:
        m.log(f"SUCCESS: All {target_count} modifiers already selected ({target_count}/13)!", "bold green")
        m.snap("modifier_selected")
        return

    # 2. If 0 selected, click Tile 1 (Glass)
    if cur_count == 0:
        m.log(f"clicking Glass modifier tile at {tile1_xy}", "cyan")
        inp.click(tile1_xy[0], tile1_xy[1], hold=0.08, settle=0.35)
        time.sleep(0.35)
        cur_count = _get_selected_count()
        if cur_count == 0:
            m.log(f"re-clicking Glass tile at {tile1_xy}", "yellow")
            inp.click(tile1_xy[0], tile1_xy[1], hold=0.08, settle=0.35)
            time.sleep(0.35)
            cur_count = _get_selected_count()

    # 3. If 1 selected, click Tile 2 (Exploding Enemies)
    if cur_count == 1:
        m.log(f"clicking Exploding Enemies modifier tile at {tile2_xy}", "cyan")
        inp.click(tile2_xy[0], tile2_xy[1], hold=0.08, settle=0.35)
        time.sleep(0.35)
        cur_count = _get_selected_count()
        if cur_count == 1:
            m.log(f"re-clicking Exploding Enemies tile at {tile2_xy}", "yellow")
            inp.click(tile2_xy[0], tile2_xy[1], hold=0.08, settle=0.35)
            time.sleep(0.35)
            cur_count = _get_selected_count()

    if cur_count == target_count:
        m.log(f"SUCCESS: All {target_count} modifiers selected ({target_count}/13)!", "bold green")
    else:
        m.log(f"Modifiers state: {cur_count}/13 registered", "yellow")
    m.snap("modifier_selected")


def vote_modifiers(m: Macro) -> None:
    m.log("voting for modifiers", "bold")
    frame = m.grab()
    lines = m.ocr.recognize(frame)

    # 1. Direct OCR search for Vote For Modifiers button across full screen
    vote_line = find_line(lines, "vote for modifiers", fuzzy=0.75) or find_line(lines, "vote", fuzzy=0.75)
    if vote_line is not None and vote_line.box.y > 600:
        m.log(f"found Vote button via OCR at {vote_line.box.center}", "green")
        inp.click_box(vote_line.box.tuple)
    else:
        # 2. Vision green button in modal button area
        boxes = vision.find_green_buttons(frame, (800, 950, 950, 350), min_area=800)
        if boxes:
            box = boxes[0]
            m.log(f"clicking Vote For Modifiers green button at {box.center}", "cyan")
            inp.click_box(box.tuple)
        else:
            m.log("Vote button text/color not found; clicking calibrated position (1506, 1222)", "yellow")
            inp.click(1506, 1222)

    time.sleep(1.0)
    # Ensure the modifier menu is closed before walking to the override machine.
    det = m.detect()
    if det.state == State.MODIFIERS:
        m.log("closing modifier menu", "cyan")
        close_modal(m)
        time.sleep(0.8)
    try:
        m.wait_for_state(State.INTERMISSION, timeout=6.0)
    except MacroError:
        m.log("modifier panel still open; clicking close button", "yellow")
        close_modal(m)
        time.sleep(0.8)


def timer_running(m: Macro) -> bool:
    frame = m.grab()
    lines = m.ocr.recognize(frame, (650, 0, 1260, 260))
    text = " ".join(l.norm for l in lines)
    if "vote for a map to start the timer" in text:
        return False
    if "time left" in text:
        return True
    return False


def is_facing_room(frame: np.ndarray) -> bool:
    """Check if the camera is facing the 4 intermission boards (red headers in y=300..700)."""
    hsv = cv2.cvtColor(frame[300:700, :], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 100, 100), (10, 255, 255)) | cv2.inRange(hsv, (170, 100, 100), (180, 255, 255))
    return int(cv2.countNonZero(mask)) > 3000


def ensure_facing_room(m: Macro) -> None:
    """Detect whether player spawned facing ocean vs facing room, and orient toward room."""
    frame = m.grab()
    if is_facing_room(frame):
        m.log("camera is already facing the Intermission room & boards", "green")
        return
    m.log("camera is facing the ocean; rotating 180 degrees to face the room", "bold")
    inp.rotate_camera(1200, 0, steps=30)
    time.sleep(0.4)
    frame2 = m.grab()
    if not is_facing_room(frame2):
        m.log("re-checking orientation; nudging camera", "yellow")
        inp.rotate_camera(600, 0, steps=15)
        time.sleep(0.3)


def scan_boards_for_dead_ahead(m: Macro) -> Optional[int]:
    """Scan the 4 map boards. If Dead Ahead is found on Board 1, 2, 3, or 4, return the board index (1-4)."""
    frame = m.grab()
    # Boards span across the front wall: x=100..2460, y=300..650
    crop = frame[300:650, 100:2460]
    crop_2x = cv2.resize(crop, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    lines = m.ocr.recognize(crop_2x)
    for l in lines:
        if "dead ahead" in l.norm:
            orig_x = l.box.x // 2 + 100
            if orig_x < 700:
                board_idx = 1
            elif orig_x < 1300:
                board_idx = 2
            elif orig_x < 1900:
                board_idx = 3
            else:
                board_idx = 4
            m.log(f"found 'Dead Ahead' already in pool on Board #{board_idx} (x={orig_x})", "green")
            return board_idx
    return None


def vote_on_board_pad(m: Macro, board_idx: int) -> None:
    """Walk from spawn facing room to Board board_idx (1-4) pad and hold E to vote."""
    m.log(f"walking directly to Board #{board_idx} pad to vote", "bold")
    if board_idx == 1:
        m.hold(["a", "w"], 0.6)
        m.hold(["w"], 1.4)
    elif board_idx == 2:
        m.hold(["a"], 0.25)
        m.hold(["w"], 1.8)
    elif board_idx == 3:
        m.hold(["d"], 0.25)
        m.hold(["w"], 1.8)
    else:  # board 4
        m.hold(["d", "w"], 0.8)
        m.hold(["w"], 1.3)
    time.sleep(0.2)
    m.hold(["e"], 1.2)
    time.sleep(0.5)


def _try_trigger_override_prompt(m: Macro) -> bool:
    """Press/hold E or click '[E] Override Map' prompt and check if State.OVERRIDE opens."""
    m.hold(["e"], 1.2)
    time.sleep(0.35)
    frame = m.grab()
    det = m.detector.detect(frame)
    if det.state == State.OVERRIDE:
        return True

    # Check if the '[E] Override Map' prompt is visible on screen
    ov_line = find_line(det.lines, "override map", fuzzy=0.75)
    if ov_line is not None:
        cx, cy = ov_line.box.center
        m.log(f"saw Override Map prompt at ({cx},{cy}); clicking and holding E", "cyan")
        m.click_fixed(cx, max(100, cy - 35))
        m.hold(["e"], 1.2)
        time.sleep(0.4)
        if m.detect().state == State.OVERRIDE:
            return True
    return False


def walk_to_override_from_spawn(m: Macro) -> None:
    """Walk from Intermission spawn directly to the Override Map computer terminal and open it."""
    det0 = m.detect()
    if det0.state == State.OVERRIDE:
        m.log("Override Map modal is already open", "green")
        return

    # If the '[E] Override Map' prompt is already visible, trigger it immediately
    if find_line(det0.lines, "override map", fuzzy=0.75) is not None:
        m.log("already at Override Map terminal; opening menu", "cyan")
        if _try_trigger_override_prompt(m):
            return

    ensure_facing_room(m)

    m.log("walking from spawn to Override Map machine (red circle)", "bold")
    # From spawn looking at the room: red circle is right and forward
    m.hold(["d", "w"], 1.6)
    time.sleep(0.1)
    m.hold(["w"], 0.75)
    time.sleep(0.1)
    m.hold(["d"], 0.4)
    time.sleep(0.2)
    m.snap("at_override_terminal")

    if _try_trigger_override_prompt(m):
        return

    # One quick nudge forward if needed
    for keys, dur in [((["w"], 0.35)), (["d"], 0.30)]:
        m.hold(keys, dur)
        time.sleep(0.15)
        if _try_trigger_override_prompt(m):
            return

    # Final wait check in case of UI lag
    m.wait_for_state(State.OVERRIDE, timeout=3.0)


def walk_to_map_board(m: Macro) -> None:
    """Walk from spawn straight to the map board."""
    m.log("walking to map board to start the vote timer", "bold")
    m.hold(["w"], 2.2)
    time.sleep(0.3)
    m.hold(["e"], 0.85)
    time.sleep(0.9)
    if not timer_running(m):
        m.log("timer not running yet; adjusting and retrying E", "yellow")
        m.hold(["w"], 0.45)
        m.hold(["e"], 0.85)
        time.sleep(0.8)
    m.snap("map_vote")


def walk_to_override(m: Macro) -> None:
    """Legacy helper: walk from map board back-right to the override computer."""
    m.log("walking to the map override computer", "bold")
    m.hold(["s"], 2.8)
    m.hold(["d"], 1.5)
    m.hold(["w"], 0.6)
    time.sleep(0.3)
    if not _try_trigger_override_prompt(m):
        m.hold(["w"], 0.4)
        _try_trigger_override_prompt(m)
        m.wait_for_state(State.OVERRIDE, timeout=4.0)


def override_dead_ahead(m: Macro) -> None:
    m.log("overriding map to Dead Ahead (Insane)", "bold")
    m.wait_for_state(State.OVERRIDE, timeout=6.0)
    m.snap("override_grid")

    # 1. Use the "Search for Maps" input bar
    frame = m.grab()
    lines = m.ocr.recognize(frame)
    search_bar = find_line(lines, "search for maps", fuzzy=0.70) or find_line(lines, "search", fuzzy=0.70)
    if search_bar is not None:
        m.log(f"clicking Search for Maps bar at {search_bar.box.center}", "cyan")
        m.click_box(search_bar.box)
    else:
        m.log("Search for Maps bar not resolved by OCR; clicking fallback (1100, 290)", "yellow")
        m.click_fixed(1100, 290)
    time.sleep(0.3)
    inp.type_text("dead ahead", interval=0.04)
    time.sleep(0.7)

    frame = m.grab()
    m.snap("override_search", frame)

    # 2. Click the Dead Ahead tile at Row 1 Col 1
    # Check OCR first for 'dead ahead' or 'ahead' in the grid area
    grid_lines = m.ocr.recognize(frame, (900, 320, 750, 500))
    dead_line = find_line(grid_lines, "dead ahead", fuzzy=0.70) or find_line(grid_lines, "ahead", fuzzy=0.70)
    clicked_tile = False
    if dead_line is not None:
        m.log(f"found Dead Ahead tile text via OCR at {dead_line.box.center}", "green")
        m.click_box(dead_line.box)
        clicked_tile = True

    if not clicked_tile:
        tpl = vision.load_template("dead_ahead_tile.png")
        if tpl is not None:
            box = vision.match_template_best(
                frame,
                tpl,
                threshold=0.62,
                region=(900, 320, 750, 600),
                scales=(0.85, 0.95, 1.0, 1.05, 1.15),
            )
            if box is not None:
                m.log(f"matched Dead Ahead tile template at {box.center}", "green")
                m.click_box(box)
                clicked_tile = True

    if not clicked_tile:
        m.log("clicking Dead Ahead tile at Row 1 Col 1 (1070, 395)", "cyan")
        m.click_fixed(1070, 395)
        clicked_tile = True

    time.sleep(0.8)
    m.snap("dead_ahead_selected")

    # 3. Wait briefly for confirmation toast ("Map changed to Dead Ahead")
    try:
        m.wait_for_text("map changed", timeout=2.0, fuzzy=0.72)
        m.log("map override confirmed ('Map changed to Dead Ahead')", "green")
    except MacroError:
        m.log("proceeding after Dead Ahead tile selection", "dim")

    # 4. Close the Override Map modal if still open (do NOT press ESC unconditionally)
    time.sleep(0.6)
    det = m.detect()
    if det.state == State.OVERRIDE:
        m.log("closing Override Map modal by clicking off-menu (600, 500)", "cyan")
        m.click_fixed(600, 500)
        time.sleep(0.5)
        if m.detect().state == State.OVERRIDE:
            m.click_fixed(600, 700)
            time.sleep(0.5)
        if m.detect().state == State.OVERRIDE:
            inp.press("escape")
            time.sleep(0.5)

    # Ensure Roblox ESC menu is not open
    frame = m.grab()
    if is_esc_menu_open(m, frame):
        m.log("Roblox ESC menu was open; pressing ESC to close it", "yellow")
        inp.press("escape")
        time.sleep(0.4)


def is_vote_timer_running(m: Macro, frame: np.ndarray) -> bool:
    """Check whether the intermission map voting countdown has started.

    Before voting, TDS displays a bright red banner in the top center:
    'Vote for a map to start the timer!'. When a vote is cast, this banner vanishes
    and the countdown timer runs ('Time Left: 00:15').
    """
    h, w = frame.shape[:2]
    y1, y2 = int(h * 0.05), int(h * 0.16)
    x1, x2 = int(w * 0.35), int(w * 0.65)
    crop = frame[y1:y2, x1:x2]
    r = crop[:, :, 2].astype(int)
    g = crop[:, :, 1].astype(int)
    b = crop[:, :, 0].astype(int)
    red_cnt = int(np.sum((r > 180) & (g < 60) & (b < 60)))

    lines = m.ocr.recognize(frame, (x1, y1, x2 - x1, y2 - y1))
    text = " ".join(l.norm for l in lines)
    has_start_prompt = "start the timer" in text or "vote for a map to start" in text

    # Timer is running if bright red pixels are gone (< 800) AND 'start the timer' prompt is absent
    timer_running = (red_cnt < 800) and not has_start_prompt
    return timer_running


def is_esc_menu_open(m: Macro, frame: np.ndarray) -> bool:
    """Check whether the Roblox in-game Escape menu is open."""
    h, w = frame.shape[:2]
    reg = (int(w * 0.30), int(h * 0.65), int(w * 0.40), int(h * 0.20))
    lines = m.ocr.recognize(frame, reg)
    text = " ".join(l.norm for l in lines)
    return any(k in text for k in ("respawn", "resume", "leave"))


def walk_from_override_to_map_selector(m: Macro) -> None:
    """Walk from the Override computer toward Board 1 (Dead Ahead pad) and register the vote.

    Path avoids the circular armory place in the center of the room by moving
    forward onto the stone walkway along the boards first, then strafing left
    directly onto Board 1's glowing white pad.
    """
    # Ensure any open modals or menus are closed before moving
    for _ in range(2):
        det = m.detect()
        if det.state in (State.OVERRIDE, State.MODIFIERS):
            m.click_fixed(600, 500)
            time.sleep(0.3)
    frame = m.grab()
    if is_esc_menu_open(m, frame):
        m.log("Roblox ESC menu was open; pressing ESC to close it", "yellow")
        inp.press("escape")
        time.sleep(0.4)

    m.log("walking from Override machine to Board 1 pad (avoiding armory circle)", "bold")
    # 1. Step left-forward out of the kiosk circle onto the stone runway in front of the boards
    m.hold(["w"], 0.8)
    time.sleep(0.1)
    m.hold(["a"], 1.6)
    time.sleep(0.1)
    # 2. Step forward onto the stone path along the boards (safely north of the armory)
    m.hold(["w"], 0.8)
    time.sleep(0.1)
    # 3. Walk left along the stone path all the way to Board 1 (Dead Ahead pad)
    m.hold(["a"], 1.4)
    time.sleep(0.1)
    # 4. Step forward squarely onto Board 1's glowing white pad
    m.hold(["w"], 0.8)
    time.sleep(0.2)
    m.snap("at_map_selector")

    # If inventory or another modal accidentally opened near the kiosk, close it immediately
    det = m.detect()
    if find_line(det.lines, "inventory", fuzzy=0.75):
        m.log("inventory modal opened near kiosk; closing it", "yellow")
        close_modal(m)
        time.sleep(0.5)

    # Cast the vote on Board 1 by holding E
    m.log("casting vote on Board 1 Dead Ahead pad (holding E)", "bold green")
    m.hold(["e"], 1.4)
    time.sleep(0.4)
    m.snap("dead_ahead_voted")

    # Verify if vote registered; if countdown has not started, nudge forward and hold E again
    frame = m.grab()
    if not is_vote_timer_running(m, frame):
        m.log("vote timer not yet active; nudging forward onto pad and retrying vote", "yellow")
        m.hold(["w"], 0.45)
        time.sleep(0.2)
        m.hold(["e"], 1.5)
        time.sleep(0.4)


def get_ready_region(frame: np.ndarray) -> tuple[int, int, int, int]:
    """Dynamically scaled region for the bottom Ready button across 1080p, 1440p, 4K."""
    h, w = frame.shape[:2]
    return (int(w * 0.35), int(h * 0.76), int(w * 0.40), int(h * 0.22))


def ready_up(m: Macro) -> bool:
    """Click Ready at the bottom of the screen with a verification loop to guarantee it registers."""
    m.log("clicking Ready at bottom of screen with verification loop", "bold")

    for attempt in range(6):
        m.check_interrupts()
        frame = m.grab()
        det = m.detector.detect(frame)

        # If match already loading or gameplay started, ready succeeded!
        if det.state in (State.GAMEPLAY_PREP, State.GAMEPLAY, State.LOADING):
            m.log("match loading/started; Ready confirmed", "green")
            return True

        if det.state in (State.OVERRIDE, State.MODIFIERS):
            m.log("modal covering Ready button; closing modal", "yellow")
            close_modal(m)
            time.sleep(0.5)
            frame = m.grab()

        region = get_ready_region(frame)
        lines = m.ocr.recognize(frame, region)
        text = " ".join(l.norm for l in lines)

        # Check if already verified ready: "ready (1/1)" or "unready"
        if "ready (1/1)" in text or "ready(1/1)" in text or "unready" in text or "1/1" in text:
            m.log("Ready state verified (1/1)!", "bold green")
            return True

        clicked = False
        for l in lines:
            if "ready" in l.norm:
                m.log(f"found Ready button at {l.box.center}; clicking", "cyan")
                inp.click(*l.box.center)
                clicked = True
                break

        if not clicked:
            # Fall back to green button detection in bottom bar
            green_boxes = vision.find_green_buttons(frame, region, min_area=800)
            if green_boxes:
                target_box = green_boxes[0]
                m.log(f"found green Ready button at {target_box.center}; clicking", "cyan")
                inp.click_box(target_box.tuple)
                clicked = True
            else:
                h, w = frame.shape[:2]
                fallback_xy = (int(w * 0.50), int(h * 0.88))
                m.log(f"Ready text/green button not resolved; trying center fallback at {fallback_xy}", "yellow")
                inp.click(*fallback_xy)
                clicked = True

        time.sleep(0.8)

        # Verify post-click
        post_frame = m.grab()
        post_det = m.detector.detect(post_frame)
        if post_det.state in (State.GAMEPLAY_PREP, State.GAMEPLAY, State.LOADING):
            m.log("Ready verified: transitioned to game prep", "green")
            return True

        post_lines = m.ocr.recognize(post_frame, region)
        post_text = " ".join(l.norm for l in post_lines)
        if "ready (1/1)" in post_text or "ready(1/1)" in post_text or "unready" in post_text or "1/1" in post_text:
            m.log("Ready verified: button changed to (1/1)", "green")
            return True

        m.log(f"Ready verification attempt {attempt + 1}/6 pending; retrying...", "yellow")

    return False


def run_intermission(m: Macro) -> None:
    """Complete the intermission in exact walkthrough order:
    1. Turn on the 2 modifiers (Glass + Exploding Enemies), vote, and close modifier menu.
    2. Check spawn orientation: if facing ocean, rotate 180 to face room.
    3. Scan the 4 boards for 'Dead Ahead':
       - If already present on Board i: skip override completely! Walk directly to Board i pad and vote!
       - If absent: walk to Override machine, select Dead Ahead, close modal, walk to Board 1 pad and vote.
    4. Click Ready at the bottom of the screen.
    """
    det = m.detect()
    if det.state in (State.GAMEPLAY_PREP, State.GAMEPLAY):
        return
    if det.state != State.INTERMISSION:
        m.wait_for_state(State.INTERMISSION, timeout=20.0)

    # Modifiers configuration
    if getattr(m.settings, "enable_modifiers", True) and getattr(m.settings, "modifiers", ()):
        open_modifiers(m)
        select_modifiers(m)
        vote_modifiers(m)
        time.sleep(0.6)
    else:
        m.log("game modifiers disabled in Run Settings; skipping modifier vote", "dim")

    if m.detect().state in (State.GAMEPLAY_PREP, State.GAMEPLAY):
        return

    ensure_facing_room(m)

    # Always override to Dead Ahead: Dead Ahead is an Insane difficulty map that never
    # naturally appears in the 4 random intermission boards on Easy mode.
    m.log("ensuring Dead Ahead is overridden on Board 1", "bold")
    for attempt in range(2):
        if m.detect().state in (State.GAMEPLAY_PREP, State.GAMEPLAY):
            return
        try:
            walk_to_override_from_spawn(m)
            override_dead_ahead(m)
            walk_from_override_to_map_selector(m)
            break
        except Exception as exc:
            m.log(f"override attempt {attempt+1} encountered ({exc}); retrying", "yellow")
            if m.detect().state in (State.GAMEPLAY_PREP, State.GAMEPLAY):
                return
            time.sleep(0.5)

    ready_up(m)
