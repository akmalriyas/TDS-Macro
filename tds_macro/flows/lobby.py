"""Lobby, matchmaking, and intermission flows."""
from __future__ import annotations

import os
import time
from typing import Optional

import cv2

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
MODIFIER_GEAR = (60, 1376)
GLASS_ICON = (1088, 440)
BOMB_ICON = (1177, 455)
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

        # 1. Login Rewards / Daily Rewards popup with a 'CLOSE' button
        if any(k in text for k in ("login rewards", "login streak", "daily rewards", "streak", "day streak", "rewards scale")):
            close_btn = find_line(lines, "close", exact=True) or find_line(lines, "close", fuzzy=0.75)
            if close_btn is not None:
                m.log(f"closing Login Rewards popup via CLOSE button at {close_btn.box.center}", "cyan")
                inp.click_box(close_btn.box.tuple)
                time.sleep(1.0)
                dismissed = True
                continue
            # Fallback: click bottom-center of modal where CLOSE button sits
            h, w = frame.shape[:2]
            m.log("clicking calibrated Login Rewards CLOSE button at center-bottom", "yellow")
            inp.click(int(w * 0.50), int(h * 0.77))
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
    """Handle the TDS idle-kick dialog, reconnecting if possible."""
    frame = m.grab()
    lines = m.ocr.recognize(frame)
    m.snap("disconnected", frame)
    rec = find_line(lines, "reconnect", fuzzy=0.75)
    if rec is not None:
        m.log("idle disconnect detected; reconnecting", "yellow")
        m.click_box(rec.box)
        time.sleep(8.0)
        return True
    leave = find_line(lines, "leave", fuzzy=0.75, region=(0, 500, 1600, 500))
    if leave is not None:
        m.log("reconnect unavailable; leaving and relaunching", "yellow")
        m.click_box(leave.box)
        time.sleep(3.0)
        window.open_url(GAME_URL)
        time.sleep(10.0)
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

    for x, y in ((1659, 264), (2268, 29)):
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

    # Close inventory: red X at top-right (same place as most TDS modals).
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

        # Click the green PLAY button (center ~ 1280, 1275)
        if not m.click_text("play", region=(1100, 1220, 360, 120), timeout=1.0):
            if not m.click_green(PLAY_BUTTON_REGION, min_area=800):
                inp.click(1280, 1275, hold=0.06, settle=0.10)

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
    m.click_fixed(*MODIFIER_GEAR)
    time.sleep(1.0)
    m.wait_for_state(State.MODIFIERS, timeout=8.0)
    m.snap("modifier_panel")


def select_modifiers(m: Macro) -> None:
    targets = [s.strip().lower() for s in getattr(m.settings, "modifiers", ())]
    if not targets:
        m.log("no modifiers configured in settings to select", "dim")
        return

    m.log(f"selecting modifiers: {', '.join(m.settings.modifiers)}", "bold")
    m.focus()
    clicked = 0
    for mod_name in targets:
        coord = MODIFIER_COORDS.get(mod_name)
        if not coord:
            for k, c in MODIFIER_COORDS.items():
                if k in mod_name or mod_name in k:
                    coord = c
                    break
        if coord:
            m.log(f"clicking modifier '{mod_name}' at {coord}", "cyan")
            inp.click(*coord, hold=0.05, settle=0.20)
            time.sleep(0.35)
            m.focus()
            clicked += 1
        else:
            m.log(f"modifier '{mod_name}' has no calibrated click coordinates; skipping click", "yellow")

    if clicked > 0:
        time.sleep(0.5)
        m.snap("modifier_selected")
        # Verify the panel shows selected count; OCR may read "2/13" or "2 / 13".
        lines = m.ocr.recognize(m.grab(), (850, 1000, 850, 260))
        text = " ".join(l.norm for l in lines)
        m.log(f"selected modifiers text: {text}", "dim")


def vote_modifiers(m: Macro) -> None:
    m.log("voting for modifiers", "bold")
    frame = m.grab()
    boxes = vision.find_green_buttons(frame, VOTE_MODIFIERS_REGION, min_area=1200)
    if not boxes:
        # Also check mid-screen region (refs/221445.png has Vote For Modifiers around y=922)
        boxes = vision.find_green_buttons(frame, (1050, 820, 750, 480), min_area=1200)
    if boxes:
        box = boxes[0]
        m.log(f"clicking Vote For Modifiers at {box.center}", "cyan")
        inp.click_box(box.tuple)
    elif not m.click_text("vote for modifiers", region=(1000, 800, 900, 520), timeout=4.0):
        raise MacroError("Vote For Modifiers button not found")
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
    # Roblox proximity prompts require holding E for 0.8s..1.0s; hold for 1.2s to ensure completion
    m.hold(["e"], 1.2)
    time.sleep(0.75)
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
        time.sleep(0.85)
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
    time.sleep(0.15)
    m.hold(["w"], 0.4)
    m.hold(["d"], 0.4)
    time.sleep(0.25)
    m.snap("at_override_terminal")

    if _try_trigger_override_prompt(m):
        return

    # Search pattern around the red circle if the first E did not open the modal.
    nudges: list[tuple[list[str], float]] = [
        (["w"], 0.35),
        (["d"], 0.30),
        (["s"], 0.35),
        (["a"], 0.35),
        (["w", "d"], 0.30),
    ]
    for keys, dur in nudges:
        m.log(f"nudging {keys} ({dur:.2f}s) to trigger Override Map prompt", "yellow")
        m.hold(keys, dur)
        time.sleep(0.2)
        if _try_trigger_override_prompt(m):
            return

    # Final wait check in case of UI lag
    m.wait_for_state(State.OVERRIDE, timeout=4.0)


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

    # 1. Use the "Search for Maps" input bar at (1100, 290) to filter directly to Dead Ahead
    m.log("clicking Search for Maps bar at (1100, 290)", "cyan")
    m.click_fixed(1100, 290)
    time.sleep(0.3)
    inp.type_text("dead ahead", interval=0.04)
    time.sleep(0.7)

    frame = m.grab()
    m.snap("override_search", frame)

    # 2. Click the Dead Ahead tile at Row 1 Col 1 (1045, 385)
    tpl = vision.load_template("dead_ahead_tile.png")
    clicked_tile = False
    if tpl is not None:
        box = vision.match_template_best(
            frame,
            tpl,
            threshold=0.62,
            region=(995, 330, 565, 740),
            scales=(0.95, 1.0, 1.05),
        )
        if box is not None:
            m.log(f"matched Dead Ahead tile template at {box.center}", "green")
            m.click_box(box)
            clicked_tile = True

    if not clicked_tile:
        m.log("clicking Dead Ahead tile at Row 1 Col 1 (1045, 385)", "cyan")
        m.click_fixed(1045, 385)
        clicked_tile = True

    time.sleep(0.8)
    m.snap("dead_ahead_selected")

    # 3. Wait briefly for confirmation toast ("Map changed to Dead Ahead")
    try:
        m.wait_for_text("map changed", timeout=2.5, fuzzy=0.72)
        m.log("map override confirmed ('Map changed to Dead Ahead')", "green")
    except MacroError:
        m.log("proceeding after Dead Ahead tile selection", "dim")

    # 4. Close the Override Map modal by clicking off-menu (500, 700)
    det = m.detect()
    if det.state == State.OVERRIDE:
        m.log("closing Override Map modal by clicking off-menu (500, 700)", "cyan")
        m.click_fixed(500, 700)
        time.sleep(0.65)
        if m.detect().state == State.OVERRIDE:
            close_modal(m)
            time.sleep(0.6)


def walk_from_override_to_map_selector(m: Macro) -> None:
    """Walk from the Override computer toward Board 1 (Dead Ahead pad) and register the vote."""
    m.log("walking from Override machine to Map Selector Board 1 (Dead Ahead pad)", "bold")
    # Step back from override terminal away from front pads
    m.hold(["s"], 0.8)
    time.sleep(0.12)
    # Walk left across the open floor directly to Board 1 column
    m.hold(["a"], 2.4)
    time.sleep(0.12)
    # Step forward onto Board 1 pad
    m.hold(["w"], 1.3)
    time.sleep(0.3)
    m.snap("at_map_selector")

    # If inventory or another modal accidentally opened near the kiosk, close it immediately
    det = m.detect()
    if find_line(det.lines, "inventory", fuzzy=0.75):
        m.log("inventory modal opened near kiosk; closing it", "yellow")
        close_modal(m)
        time.sleep(0.5)

    # Closed-loop vision/OCR alignment: ensure we are centered on "Dead Ahead"
    for _ in range(3):
        frame = m.grab()
        lines = m.ocr.recognize(frame, (80, 140, 2400, 860))
        da = find_line(lines, "dead ahead", fuzzy=0.72)
        if da is not None:
            cx, cy = da.box.center
            m.log(f"saw Dead Ahead on Map Selector Board at ({cx},{cy})", "cyan")
            if cx < 1000:
                m.hold(["a"], 0.35)
            elif cx > 1450:
                m.hold(["d"], 0.35)
            m.hold(["w"], 0.45)
            time.sleep(0.3)
            m.log("Dead Ahead vote confirmed on Board 1!", "green")
            m.snap("dead_ahead_voted")
            return
        m.hold(["w"], 0.3)
        time.sleep(0.2)

    m.log("finished map selector walk; proceeding to Ready", "yellow")


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

    ensure_facing_room(m)
    existing_board = scan_boards_for_dead_ahead(m)

    if existing_board is not None:
        m.log(f"Dead Ahead is already in the pool on Board #{existing_board}; voting directly without override", "green")
        vote_on_board_pad(m, existing_board)
    else:
        m.log("Dead Ahead is not in the pool; overriding via machine", "bold")
        for attempt in range(2):
            try:
                walk_to_override_from_spawn(m)
                override_dead_ahead(m)
                walk_from_override_to_map_selector(m)
                break
            except Exception as exc:
                m.log(f"override attempt {attempt+1} encountered ({exc}); retrying", "yellow")
                time.sleep(1.0)

    ready_up(m)
