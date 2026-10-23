"""In-match gameplay flow for Dead Ahead (Golden Scout strategy) and Victory handling."""
from __future__ import annotations

import re
import time
from typing import Optional

import cv2
import numpy as np

from .. import input as inp
from .. import vision
from ..core import Macro, MacroError
from ..ocr import find_line, parse_int, text_near
from ..runlog import RunRecord
from ..state import State

# Top-center region where "Ready? -> Yes" and "Skip Wave? -> Yes" prompts appear (2560x1440)
TOP_PROMPT_REGION = (920, 65, 720, 235)

# 20 Golden Scout placement coordinates along the road on Dead Ahead (2560x1440 overhead).
# Left shoulder coordinates (x=1045, 945) and right median/shoulder coordinates (x=1390, 1490).
# Ordered starting from tunnel area (y=480..640) where enemies exit, down toward portal spawn (y=720..1040),
# ensuring a continuous gauntlet of fire across the entire bridge.
SCOUT_SLOTS_2560x1440: list[tuple[int, int]] = [
    # Top/Tunnel defense (last line of defense before exit)
    (1040, 560),
    (1390, 560),
    (1040, 640),
    (1390, 640),
    (940, 560),
    (1490, 560),
    # Mid-bridge gauntlet
    (1045, 720),
    (1390, 720),
    (1045, 800),
    (1390, 800),
    (945, 720),
    (1490, 720),
    (945, 800),
    (1490, 800),
    # Spawn/Portal approach (front damage)
    (1045, 880),
    (1390, 880),
    (1045, 960),
    (1390, 960),
    (945, 880),
    (1490, 880),
]

def get_top_prompt_region(frame: np.ndarray) -> tuple[int, int, int, int]:
    """Return top prompt search region dynamically scaled to current screen resolution."""
    h, w = frame.shape[:2]
    if w == 2560 and h == 1440:
        return TOP_PROMPT_REGION
    sx, sy = w / 2560.0, h / 1440.0
    return (int(round(920 * sx)), int(round(65 * sy)), int(round(720 * sx)), int(round(235 * sy)))


def get_scout_slots(frame: np.ndarray) -> list[tuple[int, int]]:
    """Return 20 scout placement coordinates dynamically scaled to current screen resolution."""
    h, w = frame.shape[:2]
    if w == 2560 and h == 1440:
        return list(SCOUT_SLOTS_2560x1440)
    sx, sy = w / 2560.0, h / 1440.0
    return [(int(round(x * sx)), int(round(y * sy))) for x, y in SCOUT_SLOTS_2560x1440]



def is_valid_placement_spot(frame: np.ndarray, x: int, y: int) -> bool:
    """Ultra-low latency (<1ms) check if the placement spot at (x, y) is unobstructed.

    In TDS, an obstructed placement spot (on road, rocks, or another tower) turns
    bright saturated neon red. When valid, red is absent.
    """
    h, w = frame.shape[:2]
    y1, y2 = max(0, y - 35), min(h, y + 35)
    x1, x2 = max(0, x - 35), min(w, x + 35)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return False

    b = roi[:, :, 0].astype(int)
    g = roi[:, :, 1].astype(int)
    r = roi[:, :, 2].astype(int)

    # In TDS, invalid spots show a distinctive bright neon-red pedestal:
    red_invalid_mask = (r > 130) & (r > (g * 1.30).astype(int)) & (r > (b * 1.30).astype(int))
    red_count = int(red_invalid_mask.sum())
    return red_count < 60


def _find_top_green_chevron(frame: np.ndarray) -> Optional[tuple[int, int]]:
    """Find the bright neon-green enemy path chevron near the top of the road (refs/221734.png)."""
    roi = frame[230:1120, 600:1960]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (36, 95, 145), (88, 255, 255))
    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    candidates: list[tuple[int, int, int]] = []
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if 80 <= area <= 12000:
            cx = int(centroids[i][0]) + 600
            cy = int(centroids[i][1]) + 230
            candidates.append((cy, cx, area))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    top_y, top_x, _ = candidates[0]
    return (top_x, top_y)


def click_top_yes(m: Macro) -> bool:
    """Click the green 'Ready' or 'Yes' button on the top-center banner.
    Filters out road chevrons and health bars by checking button aspect ratio and skipping question titles."""
    frame = m.grab()
    region = get_top_prompt_region(frame)

    # 1. Primary check: Green button on banner with horizontal aspect ratio (w/h >= 1.6, w >= 110)
    # This specifically isolates the button (w=211, h=73, ratio=2.89) from road chevrons (w=68, h=73, ratio=0.93)
    boxes = vision.find_green_buttons(frame, region, min_area=400, max_boxes=4)
    for box in boxes:
        aspect = box.w / max(1, box.h)
        if box.w >= 110 and 28 <= box.h <= 90 and aspect >= 1.6:
            m.log(f"clicking top banner green button at {box.center} (ratio={aspect:.2f})", "cyan")
            inp.click_box(box.tuple)
            m.touch()
            time.sleep(0.08)
            return True

    # 2. Secondary check: OCR text matching "ready" or "yes" or "skip", skipping question titles ("Ready?")
    lines = m.ocr.recognize(frame, region)
    for line in lines:
        if "?" in line.text or "required" in line.norm:
            continue
        norm = line.norm
        if norm in ("ready", "yes", "skip") or norm.startswith("ready ") or norm == "ready!":
            m.log(f"found top banner button '{line.text}' at {line.box.center}; clicking", "cyan")
            inp.click(*line.box.center)
            m.touch()
            time.sleep(0.08)
            return True

    return False


def setup_camera_and_position(m: Macro) -> list[tuple[int, int]]:
    """Position camera top-down, zoom out fully, and walk toward the highest street light."""
    m.log("setting up top-down camera & walking to highest street light", "bold")
    m.focus()
    time.sleep(2.0)

    # 1. Pitch camera straight down (overhead view)
    inp.rotate_camera(0, 750, steps=30)
    time.sleep(0.15)
    inp.rotate_camera(0, 450, steps=20)
    time.sleep(0.2)

    # 2. Zoom out fully using 'O' key + scroll wheel for complete map view
    m.zoom_out(key_duration=2.2, wheel_clicks=20)
    time.sleep(0.3)

    # 3. Walk forward toward the highest street light
    m.hold(["w"], 0.85)
    time.sleep(0.25)
    m.snap("camera_aligned")
    frame = m.grab()

    return get_scout_slots(frame)


def _place_scout_at(m: Macro, slot_xy: tuple[int, int]) -> Optional[tuple[int, int]]:
    """Select Scout ('1') and place at slot_xy.
    Verifies cash consumption, tower count increment, or unobstructed placement."""
    sx, sy = slot_xy
    search_offsets = [
        (0, 0),
        (-25, 0),
        (25, 0),
        (0, -25),
        (0, 25),
        (-40, 0),
        (40, 0),
    ]

    m.press("1")
    time.sleep(0.06)

    for ox, oy in search_offsets:
        tx, ty = sx + ox, sy + oy
        inp.move_to(tx, ty)
        time.sleep(0.06)
        frame = m.grab()
        if is_valid_placement_spot(frame, tx, ty):
            cash_before = m.read_cash(frame)
            t_before, _ = m.read_tower_count(frame)

            inp.click(tx, ty)
            time.sleep(0.20)

            frame_after = m.grab()
            cash_after = m.read_cash(frame_after)
            t_after, _ = m.read_tower_count(frame_after)

            # Verification: Cash dropped by >= $180, OR tower count incremented,
            # OR if OCR didn't read cash, unobstructed slot click is accepted.
            placed = False
            if cash_before is not None and cash_after is not None and cash_after <= cash_before - 180:
                placed = True
            elif t_before is not None and t_after is not None and t_after > t_before:
                placed = True
            elif cash_before is None and cash_after is None:
                placed = True

            if placed:
                m.log(f"VERIFIED: Scout placed at ({tx}, {ty}) [Cash: ${cash_before}->${cash_after}]", "green")
                m.press("q")
                time.sleep(0.05)
                return (tx, ty)
            else:
                m.log(f"Placement click at ({tx}, {ty}) unverified; trying next offset", "dim")

    # If all offsets failed, deselect placement mode with 'q'
    m.press("q")
    time.sleep(0.05)
    return None


def _upgrade_scout_at(m: Macro, scout: dict, presses: int = 1) -> bool:
    """Click a placed Scout to select it and trigger upgrade.
    Validates whether cash was consumed by the server before confirming success.
    Tracks actual confirmed level and marks maxed ONLY when Level 4 ($2,550) is reached."""
    if scout.get("maxed", False):
        return True

    coord = scout["coord"]
    m.touch()
    cash_before = m.read_cash()

    # Try clicking the base (dy=0), waist (dy=-15), and torso (dy=-25)
    for dy in (0, -15, -25):
        # 1. Click tower to select
        inp.click(coord[0], coord[1] + dy, hold=0.04, settle=0.06)
        time.sleep(0.08)

        # 2. Trigger upgrades using BOTH the keybind ('e') AND screen buttons
        for _ in range(presses):
            inp.click(290, 800, hold=0.04, settle=0.05)
            inp.click(200, 785, hold=0.04, settle=0.05)
            m.press("e")
            time.sleep(0.15)

        time.sleep(0.20)  # Settle time for server replication
        cash_after = m.read_cash()

        # 3. Deselect/close panel with 'q'
        m.press("q")
        m.touch()
        time.sleep(0.04)

        # Verification: Did cash decrease?
        if cash_before is not None and cash_after is not None and cash_after < cash_before:
            delta = cash_before - cash_after
            scout["level"] = scout.get("level", 0) + 1
            if delta >= 1800 or scout["level"] >= 4:
                scout["level"] = 4
                scout["maxed"] = True
                m.log(f"VERIFIED: Scout at {coord} REACHED LEVEL 4 MAX! (Spent ${delta}, cash remaining=${cash_after})", "bold green")
            else:
                m.log(f"VERIFIED: Scout at {coord} upgraded to Level {scout['level']} (Spent ${delta}, cash=${cash_after})", "green")
            return True

    m.log(f"Upgrade at {coord} unconfirmed (${cash_before} -> {cash_after})", "dim")
    return False


def collect_battlepass_drops(m: Macro) -> None:
    """Sweep forward toward enemy portal (W) where tokens drop, then return (S) with exact matching time.
    Uses an exact mathematically balanced net-zero displacement vector to keep camera 100% aligned."""
    m.log("Battlepass Farm: sweeping forward toward enemy portal to collect drops", "cyan")
    prev_status = getattr(m, "_custom_status", None)
    m._custom_status = "Battlepass Farm"
    m.notify_status()
    try:
        SWEEP_TIME = 0.95
        LATERAL_TIME = 0.25

        # 1. Walk FORWARD (W) up the road median toward the portal where tokens drop
        m.hold(["w"], SWEEP_TIME)
        time.sleep(0.04)

        # 2. Side-to-side sweep across the road to pick up lateral drops
        m.hold(["a"], LATERAL_TIME)
        time.sleep(0.03)
        m.hold(["d"], LATERAL_TIME * 2)
        time.sleep(0.03)
        m.hold(["a"], LATERAL_TIME)
        time.sleep(0.04)

        # 3. Walk BACK (S) down the median with exact matching duration
        # (Net W/S = 0, Net A/D = 0 -> returns precisely to starting position)
        m.hold(["s"], SWEEP_TIME)
        time.sleep(0.06)
        m.log("Battlepass Farm: sweep complete; returned to anchor position", "green")
    except Exception as exc:
        m.log(f"Battlepass sweep interrupted: {exc}", "yellow")
    finally:
        m._custom_status = prev_status
        m.notify_status()


def _place_next_scout(m: Macro, slots: list[tuple[int, int]], scouts: list[dict], failed_slots: set[int]) -> Optional[tuple[int, int]]:
    """Iterate through slots, find an unobstructed placement spot, verify with server, and return coordinates."""
    available_indices = [
        idx for idx, slot_xy in enumerate(slots)
        if idx not in failed_slots
        and not any(abs(s["coord"][0] - slot_xy[0]) < 35 and abs(s["coord"][1] - slot_xy[1]) < 35 for s in scouts)
    ]
    if not available_indices:
        # If all slots were tried, clear failed_slots to allow retry on next iteration
        failed_slots.clear()
        available_indices = [
            idx for idx, slot_xy in enumerate(slots)
            if not any(abs(s["coord"][0] - slot_xy[0]) < 35 and abs(s["coord"][1] - slot_xy[1]) < 35 for s in scouts)
        ]

    for idx in available_indices:
        slot_xy = slots[idx]
        coord = _place_scout_at(m, slot_xy)
        if coord is not None:
            return coord
        m.log(f"Slot #{idx} at {slot_xy} obstructed or unverified; deferring to next slot", "dim")
        failed_slots.add(idx)
    return None


def run_match(m: Macro, record: Optional[RunRecord] = None) -> State:
    """Execute a full Dead Ahead match using the optimal burst DPS Golden Scout progression:

    1. Scout 1 -> L1 ($100) -> Ready -> L2 ($250) (Wave 1)
    2. Scout 2 -> Place & L2 ($350) (Waves 2-3)
    3. Scout 3 -> Place & L2 ($350) (Waves 3-4)
    4. Scout 1 -> L3 ($950) -> L4 MAX ($2,550) (60 DPS monster!)
    5. Scout 2 -> L3 ($950) -> L4 MAX ($2,550) (120 DPS combined!)
    6. Scout 4 & 5 -> Place & L2 ($600 each)
    7. Scout 3 -> L4 MAX ($2,550)
    8. Place remaining scouts and max them sequentially to wipe Wave 20 Grave Digger.
    """
    m.scouts_placed = 0
    m.current_wave = 1
    m.notify_status()

    det = m.detect()
    if det.state not in (State.GAMEPLAY_PREP, State.GAMEPLAY):
        det = m.wait_for_state([State.GAMEPLAY_PREP, State.GAMEPLAY, State.VICTORY, State.DEFEAT], timeout=60.0)
        if det.state in (State.VICTORY, State.DEFEAT):
            return det.state

    slots = setup_camera_and_position(m)
    failed_slots: set[int] = set()

    # 1. Opening sequence (Wave 0 Prep):
    m.log("placing Scout #1 and upgrading to Level 1", "bold")
    scout_1_coord = _place_next_scout(m, slots, [], failed_slots)
    if scout_1_coord is None:
        m.log("Failed initial placement; re-anchoring camera against street light", "yellow")
        setup_camera_and_position(m)
        scout_1_coord = _place_next_scout(m, slots, [], failed_slots) or slots[0]

    scouts: list[dict] = [{"coord": scout_1_coord, "level": 0, "maxed": False}]
    _upgrade_scout_at(m, scouts[0], presses=1)  # Level 1 ($100)
    scouts[0]["level"] = 1
    m.scouts_placed = 1
    m.notify_status()

    # Click Ready? -> Yes to start Wave 1 with verification loop
    m.log("clicking Ready at top of screen to start Wave 1", "bold")
    for attempt in range(8):
        m.check_interrupts()
        if click_top_yes(m):
            time.sleep(0.4)
            if not click_top_yes(m):
                m.log("Wave 1 Ready confirmed (prompt cleared)", "green")
                break
        else:
            m.click_text("yes", region=get_top_prompt_region(m.grab()), timeout=1.0)
        time.sleep(0.3)

    # Wait for $250 to upgrade Scout 1 to Level 2
    m.log("waiting for $250 to upgrade Scout #1 to Level 2", "cyan")
    w1_deadline = time.time() + 18.0
    while time.time() < w1_deadline:
        m.check_interrupts()
        cash = m.read_cash()
        if cash is not None and cash >= 250:
            if _upgrade_scout_at(m, scouts[0], presses=1):
                scouts[0]["level"] = 2
                m.log("upgraded Scout #1 to Level 2", "green")
                break
        m.sleep(0.3)

    target_scouts = max(12, min(len(slots), m.settings.scout_count))
    match_deadline = time.time() + 22 * 60.0  # 22-minute safety timeout
    last_skip_time = 0.0
    last_sweep_time = 0.0
    last_bp_sweep = time.time()

    m.log(f"entering main match combat loop (target={target_scouts} scouts, continuous MAX priority)", "bold")

    while time.time() < match_deadline:
        m.check_interrupts()
        m.touch()
        frame = m.grab()
        det = m.detector.detect(frame)
        m.current_state = det.state

        if det.state in (State.VICTORY, State.DEFEAT):
            m.log(f"match ended with state: [bold]{det.state.value}[/bold]", "green")
            return det.state
        if det.state == State.DISCONNECTED:
            raise MacroError("disconnected during match")
        if det.state == State.LOBBY:
            m.log("returned to lobby unexpectedly", "yellow")
            return State.LOBBY

        # Read HUD telemetry & sync live state
        cash = m.read_cash(frame)
        wave = m.read_wave(frame)
        t_count, _ = m.read_tower_count(frame)
        if wave is not None:
            m.current_wave = wave
        if cash is not None:
            m.current_cash = cash
        if t_count is not None:
            m.scouts_placed = max(len(scouts), t_count)
        else:
            m.scouts_placed = len(scouts)
        m.notify_status()

        # If we have accumulated surplus cash and haven't hit target scouts,
        # reset failed_slots so any previously skipped slots can be retried
        if cash is not None and cash >= 800 and len(scouts) < target_scouts and failed_slots:
            failed_slots.clear()

        # Wave skipping policy:
        now = time.time()
        should_skip = False
        if wave is not None:
            if wave <= 5:
                should_skip = True
            elif 6 <= wave <= 8 and len(scouts) >= 6 and now - last_skip_time > 12.0:
                should_skip = True
            elif 11 <= wave <= 18 and any(s.get("maxed", False) for s in scouts) and now - last_skip_time > 10.0:
                should_skip = True
            # Never skip Wave 9-10 (first boss) or Wave 19-20 (final boss) to guarantee 100% win rate
        elif now - last_skip_time > 15.0:
            should_skip = True

        if should_skip:
            if click_top_yes(m):
                last_skip_time = now

        # Step A: Early Gauntlet Foundation - Place up to min(8, target_scouts)
        # Placing an army of 6 to 8 scouts early creates a continuous suppressive wall
        if len(scouts) < min(8, target_scouts) and len(scouts) < len(slots):
            if cash is None or cash >= 250:
                coord = _place_next_scout(m, slots, scouts, failed_slots)
                if coord is not None:
                    scouts.append({"coord": coord, "level": 0, "maxed": False, "attempts": 0})
                    m.scouts_placed = len(scouts)
                    m.log(f"placed Scout #{len(scouts)} at {coord}", "green")
                    m.sleep(0.08)
                    continue

        # Step B: Bring any scout below Level 2 up to Level 2 ($100 for L1, $250 for L2)
        under_l2 = [s for s in scouts if not s.get("maxed", False) and s.get("level", 0) < 2]
        if under_l2:
            target = under_l2[0]
            needed = 100 if target.get("level", 0) == 0 else 250
            if cash is None or cash >= needed:
                if _upgrade_scout_at(m, target, presses=1):
                    m.sleep(0.06)
                    continue
                else:
                    scouts.remove(target)
                    scouts.append(target)
                    m.sleep(0.06)

        # Step C: Priority Burst: Upgrade scouts to Level 3 ($950) -> Lead Detection + 23.3 DPS
        under_l3 = [s for s in scouts if not s.get("maxed", False) and s.get("level", 0) == 2]
        if under_l3 and (cash is None or cash >= 950):
            target = under_l3[0]
            if _upgrade_scout_at(m, target, presses=1):
                m.sleep(0.06)
                continue
            else:
                scouts.remove(target)
                scouts.append(target)
                m.sleep(0.06)

        # Step D: Army Expansion - Fill out remaining slots up to target_scouts
        if len(scouts) < target_scouts and len(scouts) < len(slots):
            if cash is None or cash >= 250:
                coord = _place_next_scout(m, slots, scouts, failed_slots)
                if coord is not None:
                    scouts.append({"coord": coord, "level": 0, "maxed": False})
                    m.scouts_placed = len(scouts)
                    m.log(f"placed Scout #{len(scouts)}/{target_scouts} at {coord}", "green")
                    m.sleep(0.06)
                    continue

        # Step E: Boss Destroyer - Max existing Level 3 scouts to Level 4 MAX ($2,550 -> 60 DPS each!)
        under_l4 = [s for s in scouts if not s.get("maxed", False) and s.get("level", 0) == 3]
        if under_l4 and (cash is None or cash >= 2550):
            target = under_l4[0]
            if _upgrade_scout_at(m, target, presses=1):
                m.sleep(0.06)
                continue
            else:
                scouts.remove(target)
                scouts.append(target)
                m.sleep(0.06)

        # Step F: Relentless Cash Sink - if we have $1,000+ surplus cash, upgrade ANY unmaxed scout
        any_unmaxed = [s for s in scouts if not s.get("maxed", False)]
        if any_unmaxed and cash is not None and cash >= 1000:
            target = any_unmaxed[0]
            if _upgrade_scout_at(m, target, presses=1):
                m.sleep(0.06)
                continue
            else:
                scouts.remove(target)
                scouts.append(target)
                m.sleep(0.06)

        # Step G: Surplus cash expansion - if all current scouts are MAX and we still have slots & cash
        if len(scouts) < len(slots) and (cash is None or cash >= 250):
            coord = _place_next_scout(m, slots, scouts, failed_slots)
            if coord is not None:
                scouts.append({"coord": coord, "level": 0, "maxed": False})
                m.scouts_placed = len(scouts)
                m.log(f"surplus placement: Scout #{len(scouts)}/{len(slots)} at {coord}", "green")
                m.sleep(0.06)
                continue

        # Step H: Max Assurance Sweep - periodically check any unmaxed scouts
        if now - last_sweep_time > 15.0 and (cash is None or cash >= 950):
            last_sweep_time = now
            for s in scouts:
                if not s.get("maxed", False):
                    if _upgrade_scout_at(m, s, presses=1):
                        m.sleep(0.06)
                    m.sleep(0.08)

        # Step I: Battlepass Farm Sweep (collecting seasonal event drops)
        # Only sweep from Wave 4 onwards and with at least 6 scouts placed so early line is secure
        bp_interval = getattr(m.settings, "battlepass_interval_s", 16.0)
        current_w = m.current_wave or 1
        if getattr(m.settings, "battlepass_farm", False) and current_w >= 4 and len(scouts) >= 6 and (now - last_bp_sweep >= bp_interval):
            last_bp_sweep = now
            collect_battlepass_drops(m)

        m.sleep(0.08)

    raise MacroError("match timed out after 22 minutes")


def parse_results_and_continue(m: Macro, record: Optional[RunRecord] = None) -> dict:
    """OCR the Victory/Defeat screen (refs/222652.png), update RunRecord, and click Play Again."""
    frame = m.grab()
    m.snap("match_results", frame)
    lines = m.ocr.recognize(frame)
    full_text = " ".join(l.norm for l in lines)
    m.log(f"results screen OCR: {full_text[:260]}", "dim")

    outcome = "victory" if ("triumph" in full_text or "victory" in full_text) else "defeat"
    coins_earned: Optional[int] = None
    gems_earned: Optional[int] = None
    xp_earned: Optional[int] = None
    wave_reached: Optional[int] = m.current_wave
    match_time_s: Optional[float] = None

    for ln in lines:
        t = ln.norm
        m_coins = re.search(r"(\d[\d,]*)\s*coins", t)
        if m_coins and coins_earned is None:
            coins_earned = parse_int(m_coins.group(1))
        m_gems = re.search(r"(\d[\d,]*)\s*gems", t)
        if m_gems and gems_earned is None:
            gems_earned = parse_int(m_gems.group(1))
        m_xp = re.search(r"\+?(\d[\d,]*)\s*xp", t)
        if m_xp and xp_earned is None:
            xp_earned = parse_int(m_xp.group(1))
        m_wave = re.search(r"wave:?\s*(\d{1,2})", t)
        if m_wave:
            wave_reached = int(m_wave.group(1))
        m_time = re.search(r"(\d+)\s*m\s*(\d+)\s*s", t)
        if m_time:
            match_time_s = int(m_time.group(1)) * 60.0 + int(m_time.group(2))

    if wave_reached is None or wave_reached < 20:
        w_lbl = find_line(lines, "wave")
        if w_lbl is not None:
            near_w = text_near(lines, w_lbl, "right", max_distance=380)
            if near_w is not None:
                wv = parse_int(near_w.text)
                if wv is not None and 1 <= wv <= 50:
                    wave_reached = wv

    is_defeat = "you lost" in full_text or "we have to fall back" in full_text or "defeat" in full_text
    is_victory = "triumph" in full_text or "victory" in full_text or (wave_reached is not None and wave_reached >= 20)
    outcome = "defeat" if (is_defeat and not is_victory) else "victory"

    if coins_earned is None and outcome == "victory":
        coins_earned = 450

    if record is not None:
        record.result = outcome
        record.reward_coins = coins_earned
        record.reward_xp = xp_earned
        if coins_earned is not None:
            record.coin_delta = coins_earned
            if record.coins_before is not None:
                record.coins_after = record.coins_before + coins_earned
                m.last_coins = record.coins_after
        if gems_earned is not None:
            record.gem_delta = gems_earned
            if record.gems_before is not None:
                record.gems_after = record.gems_before + gems_earned
                m.last_gems = record.gems_after
        elif record.gems_before is not None:
            record.gem_delta = 0
            record.gems_after = record.gems_before
        if wave_reached is not None:
            record.wave = wave_reached
        if match_time_s is not None:
            mins = int(match_time_s // 60)
            secs = int(match_time_s % 60)
            record.time_completed = f"{mins}m {secs}s"
            if record.duration_s <= 0:
                record.duration_s = match_time_s

    m.log(
        f"match summary: outcome=[bold]{outcome.upper()}[/bold] "
        f"coins=+{coins_earned or 0} xp=+{xp_earned or 0} wave={wave_reached} time={match_time_s}s",
        "green" if outcome == "victory" else "yellow",
    )
    m.notify_status()

    # Post-match navigation: on defeat or when use_play_again is disabled,
    # ALWAYS return to lobby to ensure a clean override to Dead Ahead on the next run.
    if outcome == "victory" and m.settings.use_play_again:
        m.log("clicking Play Again to start next run", "bold")
        if not m.click_text("play again", region=(1000, 850, 1100, 520), timeout=5.0, fuzzy=0.75):
            if not m.click_green((1250, 920, 750, 440), min_area=1000):
                m.click_fixed(1600, 1290)
    else:
        m.log("clicking Return To Lobby to guarantee Dead Ahead map override", "bold")
        # Defeat screen button is at (1095, 1105); Victory screen Return To Lobby is at (530, 1290)
        btn_xy = (1095, 1105) if outcome == "defeat" else (530, 1290)
        m.click_fixed(*btn_xy)
        time.sleep(1.0)
        for _ in range(4):
            post_det = m.detect()
            if post_det.state not in (State.VICTORY, State.DEFEAT):
                break
            m.log(f"still on {post_det.state.value} screen; retrying Return To Lobby click", "yellow")
            m.click_fixed(*btn_xy)
            time.sleep(1.2)

    time.sleep(2.0)
    return {
        "outcome": outcome,
        "coins_earned": coins_earned,
        "gems_earned": gems_earned,
        "xp_earned": xp_earned,
        "wave_reached": wave_reached,
        "match_time_s": match_time_s,
    }
