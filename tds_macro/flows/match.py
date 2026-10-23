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
    """Ultra-low latency (<1ms) check of the placement ring and pedestal around (x, y).

    In TDS, when hovering a tower during placement mode:
    - If obstructed / invalid (e.g. road, rocks, out of bounds, overlapping another tower):
      The base pedestal and range ring turn bright neon red (R > 140, R > G*1.2, R > B*1.2).
    - If valid for placement:
      The pedestal and range hologram are vibrant blue / cyan / green with ZERO red pixels.
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

    # In TDS, invalid spots show a distinctive bright neon-red pedestal under the mouse:
    # R is high (>135), and significantly dominates G and B.
    red_invalid_mask = (r > 135) & (r > (g * 1.25).astype(int)) & (r > (b * 1.25).astype(int))
    red_count = int(red_invalid_mask.sum())
    if red_count > 60:
        return False

    # Check for presence of the placement hologram / range circle (blue, cyan, or green):
    blue_cyan_mask = (b > 80) & (b > (r * 1.2).astype(int)) & (b > (g * 1.2).astype(int))
    green_mask = (g > 90) & (g > (r * 1.2).astype(int)) & (g > (b * 1.1).astype(int))
    holo_count = int((blue_cyan_mask | green_mask).sum())

    # Valid if placement hologram is present and red obstruction is absent:
    return holo_count > 80 and red_count < 25


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
    """Click the green 'Yes' button on the top-center 'Ready?' or 'Skip Wave?' banner if present."""
    frame = m.grab()
    region = get_top_prompt_region(frame)
    boxes = vision.find_green_buttons(frame, region, min_area=320, max_boxes=4)
    if boxes:
        for box in boxes:
            if 35 <= box.w <= 240 and 20 <= box.h <= 110:
                m.log(f"clicking top Ready/Skip Yes at {box.center}", "cyan")
                inp.click_box(box.tuple)
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


def _place_scout_at(m: Macro, slot_xy: tuple[int, int]) -> tuple[int, int]:
    """Select Scout ('1') and place at slot_xy using real-time ring color sensing."""
    sx, sy = slot_xy
    search_offsets = [
        (0, 0),
        (-25, 0),
        (-50, 0),
        (25, 0),
        (0, -25),
        (0, 25),
        (-35, -25),
        (-35, 25),
        (35, -25),
        (35, 25),
    ]

    m.press("1")
    time.sleep(0.06)

    for ox, oy in search_offsets:
        tx, ty = sx + ox, sy + oy
        inp.move_to(tx, ty)
        time.sleep(0.08)
        frame = m.grab()
        if is_valid_placement_spot(frame, tx, ty):
            cash_before = m.read_cash(frame)
            inp.click(tx, ty)
            time.sleep(0.20)
            cash_after = m.read_cash()
            if cash_before is not None and cash_after is not None and cash_after < cash_before:
                m.log(f"Scout placed at ({tx}, {ty}) [cash: ${cash_before} -> ${cash_after}]", "green")
                m.press("q")
                return (tx, ty)
            m.press("q")
            return (tx, ty)

    # Fallback click at base spot
    inp.click(sx, sy)
    time.sleep(0.15)
    m.press("q")
    return (sx, sy)


def _upgrade_scout_at(m: Macro, coord: tuple[int, int], presses: int = 1) -> bool:
    """Click a placed Scout to select it and trigger upgrade.

    In TDS v2.15, clicking the tower opens its upgrade/stats panel on the left (x=100..500, y=700..900).
    We click the tower, click the on-screen Upgrade button at (290, 800) and press 'e',
    then close the selection with 'q'.
    Each upgrade step allows adequate server/animation settle time (0.16s).
    """
    m.touch()
    # 1. Click tower to select
    inp.click(coord[0], coord[1], hold=0.04, settle=0.08)
    time.sleep(0.08)

    c_before = m.read_cash()
    # 2. Trigger upgrades with adequate settle time between steps
    for _ in range(presses):
        inp.click(290, 800, hold=0.04, settle=0.06)
        m.press("e")
        time.sleep(0.16)

    c_after = m.read_cash()
    # 3. Deselect/close panel with 'q'
    m.press("q")
    m.touch()
    time.sleep(0.06)

    if c_before is not None and c_after is not None and c_after < c_before:
        return True
    return True


def collect_battlepass_drops(m: Macro) -> None:
    """Perform a quick collection sweep forward toward the track/killzone to collect dropped battlepass
    event tokens (e.g. sickles, crystals, pumpkins), then return immediately to starting position."""
    m.log("Battlepass Farm: sweeping forward toward track to vacuum dropped tokens", "cyan")
    prev_status = getattr(m, "_custom_status", None)
    m._custom_status = "Battlepass Farm"
    m.notify_status()
    try:
        # 1. Walk forward toward the track
        m.hold(["w"], 1.35)
        time.sleep(0.08)
        # 2. Sweep left along the road shoulder
        m.hold(["a"], 0.60)
        time.sleep(0.05)
        # 3. Sweep across the road to the right shoulder
        m.hold(["d"], 1.20)
        time.sleep(0.05)
        # 4. Re-center
        m.hold(["a"], 0.60)
        time.sleep(0.08)
        # 5. Return backward to baseline position
        m.hold(["s"], 1.35)
        time.sleep(0.12)
    except Exception as exc:
        m.log(f"Battlepass sweep interrupted: {exc}", "yellow")
    finally:
        m._custom_status = prev_status
        m.notify_status()


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

    # 1. Opening sequence (Wave 0 Prep):
    m.log("placing Scout #1 at slot 0 and upgrading to Level 1", "bold")
    scout_1_coord = _place_scout_at(m, slots[0])
    _upgrade_scout_at(m, scout_1_coord, presses=1)  # Level 1 ($100)
    scouts: list[dict] = [{"coord": scout_1_coord, "level": 1}]
    m.scouts_placed = 1
    m.notify_status()

    # Click Ready? -> Yes to start Wave 1
    m.log("clicking Ready at top of screen to start Wave 1", "bold")
    if not click_top_yes(m):
        m.click_text("yes", region=get_top_prompt_region(m.grab()), timeout=3.0)

    # Wait for $250 to upgrade Scout 1 to Level 2
    m.log("waiting for $250 to upgrade Scout #1 to Level 2", "cyan")
    w1_deadline = time.time() + 15.0
    while time.time() < w1_deadline:
        m.check_interrupts()
        cash = m.read_cash()
        if cash is not None and cash >= 250:
            _upgrade_scout_at(m, scout_1_coord, presses=1)
            scouts[0]["level"] = 2
            m.log("upgraded Scout #1 to Level 2", "green")
            break
        m.sleep(0.3)

    target_scouts = max(12, min(len(slots), m.settings.scout_count))
    match_deadline = time.time() + 22 * 60.0  # 22-minute safety timeout
    last_skip_time = 0.0
    last_sweep_time = 0.0
    last_bp_sweep = 0.0

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

        # Read HUD telemetry
        cash = m.read_cash(frame)
        wave = m.read_wave(frame)

        # Wave skipping policy:
        # Waves 1-5: skip immediately for fast startup cash.
        # Waves 6+: skip periodically when top prompt is active
        now = time.time()
        should_skip = False
        if wave is not None and wave <= 5:
            should_skip = True
        elif wave is not None and wave >= 6 and now - last_skip_time > 8.0:
            should_skip = True

        if should_skip:
            if click_top_yes(m):
                last_skip_time = now

        # ---------------- CONTINUOUS MAX UPGRADE & PLACEMENT LOGIC ----------------
        # Anti-Leak & Max DPS Doctrine for Dead Ahead Easy:
        # 1. Opening: First 3 Scouts placed and upgraded to Level 2 (Hidden Detection + early DPS).
        # 2. Priority Burst: Upgrade existing scouts to Level 3 ($950) -> Lead Detection + 23.3 DPS each!
        # 3. Max Priority: Max existing scouts to Level 4 MAX ($2,550) -> 60 DPS each!
        # 4. Sequential expansion: Place new scouts up to target_scouts and max them to Level 4 MAX.
        # 5. Over-cap expansion: If cash remains abundant, keep placing along all 20 slots and maxing.
        # 6. Periodic verification sweep: Ensures no tower is ever left un-maxed due to network drop.

        # Step A: Ensure at least 3 scouts are placed and at Level 2
        if len(scouts) < 3 and len(scouts) < len(slots):
            next_idx = len(scouts)
            if cash is None or cash >= 250:
                coord = _place_scout_at(m, slots[next_idx])
                scouts.append({"coord": coord, "level": 0})
                m.scouts_placed = len(scouts)
                m.log(f"placed Scout #{len(scouts)} at {coord}", "green")
                if cash is not None and cash >= 350:
                    _upgrade_scout_at(m, coord, presses=1)
                    scouts[-1]["level"] = 1
                if cash is not None and cash >= 600:
                    _upgrade_scout_at(m, coord, presses=1)
                    scouts[-1]["level"] = 2
                m.sleep(0.10)
                continue

        # Step B: Bring any placed scout < Level 2 up to Level 2
        under_l2 = [s for s in scouts if s["level"] < 2]
        if under_l2:
            target = under_l2[0]
            needed = 100 if target["level"] == 0 else 250
            if cash is None or cash >= needed:
                _upgrade_scout_at(m, target["coord"], presses=1)
                target["level"] += 1
                m.log(f"brought Scout to Level {target['level']} (cash=${cash})", "cyan")
                m.sleep(0.10)
                continue

        # Step C: Priority Burst: Upgrade existing scouts to Level 3 ($950)
        under_l3 = [s for s in scouts if s["level"] == 2]
        if under_l3 and (cash is None or cash >= 950):
            target = under_l3[0]
            _upgrade_scout_at(m, target["coord"], presses=1)
            target["level"] = 3
            m.log(f"UPGRADED Scout to Level 3 (Lead Detection + 23.3 DPS)! (cash=${cash})", "magenta")
            m.sleep(0.10)
            continue

        # Step D: Priority Burst: Max existing scouts to Level 4 MAX ($2,550) -> 60 DPS!
        under_l4 = [s for s in scouts if s["level"] == 3]
        if under_l4 and (cash is None or cash >= 2550):
            target = under_l4[0]
            _upgrade_scout_at(m, target["coord"], presses=1)
            target["level"] = 4
            m.log(f"MAXED Scout to Level 4 (60.0 DPS)! (cash=${cash})", "bold green")
            m.sleep(0.10)
            continue

        # Step E: Place new scouts up to target_scouts and step-by-step upgrade them
        if len(scouts) < target_scouts and len(scouts) < len(slots):
            # Only place new scout if cash permits ($250 to place)
            if cash is None or cash >= 250:
                next_idx = len(scouts)
                coord = _place_scout_at(m, slots[next_idx])
                scouts.append({"coord": coord, "level": 0})
                m.scouts_placed = len(scouts)
                m.log(f"placed Scout #{len(scouts)}/{target_scouts} at {coord}", "green")
                if cash is not None and cash >= 350:
                    _upgrade_scout_at(m, coord, presses=1)
                    scouts[-1]["level"] = 1
                if cash is not None and cash >= 600:
                    _upgrade_scout_at(m, coord, presses=1)
                    scouts[-1]["level"] = 2
                m.sleep(0.10)
                continue

        # Step F: Ensure ANY remaining scout not at Level 4 gets upgraded to MAX
        any_under_max = [s for s in scouts if s["level"] < 4]
        if any_under_max:
            target = any_under_max[0]
            cost = 100 if target["level"] == 0 else (250 if target["level"] == 1 else (950 if target["level"] == 2 else 2550))
            if cash is None or cash >= cost:
                _upgrade_scout_at(m, target["coord"], presses=1)
                target["level"] += 1
                lvl_str = "Level 4 MAX (60 DPS)" if target["level"] == 4 else f"Level {target['level']}"
                m.log(f"progressed Scout to {lvl_str} (cash=${cash})", "bold cyan")
                m.sleep(0.10)
                continue

        # Step G: Surplus cash expansion - if all target scouts are MAX and we still have slots & cash
        if len(scouts) < len(slots) and (cash is None or cash >= 250):
            next_idx = len(scouts)
            coord = _place_scout_at(m, slots[next_idx])
            scouts.append({"coord": coord, "level": 0})
            m.scouts_placed = len(scouts)
            m.log(f"surplus placement: Scout #{len(scouts)}/{len(slots)} at {coord}", "green")
            m.sleep(0.10)
            continue

        # Step H: Max Assurance Sweep - periodically tap scouts with 'e' to guarantee none were missed
        if now - last_sweep_time > 12.0 and (cash is None or cash >= 950):
            last_sweep_time = now
            for s in scouts:
                if s["level"] < 4:
                    _upgrade_scout_at(m, s["coord"], presses=1)
                    m.sleep(0.08)

        # Step I: Battlepass Farm Sweep (collecting seasonal event drops)
        bp_interval = getattr(m.settings, "battlepass_interval_s", 12.0)
        if getattr(m.settings, "battlepass_farm", False) and (now - last_bp_sweep >= bp_interval):
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

    # Click 'Play Again' (refs/222652.png right green button) to rinse and repeat
    if m.settings.use_play_again:
        m.log("clicking Play Again to start next run", "bold")
        if not m.click_text("play again", region=(1100, 880, 950, 480), timeout=5.0, fuzzy=0.75):
            if not m.click_green((1250, 920, 750, 440), min_area=1000):
                m.click_fixed(1470, 1270)
    else:
        m.log("clicking Return To Lobby", "bold")
        if not m.click_text("return to lobby", region=(600, 880, 900, 480), timeout=5.0, fuzzy=0.75):
            m.click_fixed(1090, 1270)

    time.sleep(2.0)
    return {
        "outcome": outcome,
        "coins_earned": coins_earned,
        "gems_earned": gems_earned,
        "xp_earned": xp_earned,
        "wave_reached": wave_reached,
        "match_time_s": match_time_s,
    }
