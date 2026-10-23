# 13. Codebase Status, Visual Discoveries & Strategy Audit

**Date:** October 2026  
**Target Game:** Tower Defense Simulator (TDS) v2.15.0 (`https://www.roblox.com/games/3260590327/Tower-Defense-Simulator`)  
**Reference Resolution:** `2560 x 1440` (16:9, scaled automatically via `ClientRect.scale()` to any client window size)

---

## 1. Executive Summary

This document audits the existing `tds_macro/` Python engine, catalogs the exact visual discoveries from all 23 reference screenshots (`refs/Screenshot 2026-10-21 221208.png` through `223001.png`) and live full-screen captures (`%TEMP%\tds_macro`), and formalizes the end-to-end **Dead Ahead (Easy + Glass + Exploding Enemies) Golden Scout Strategy**.

---

## 2. Audit of Existing `tds_macro/` Modules

| Module | Status | Audit Findings & Required Changes |
|---|---|---|
| [`tds_macro/config.py`](../tds_macro/config.py) | Built (needs tuning) | Defines `REF_W = 2560`, `REF_H = 1440`, `Settings`, `Coords`, and `Colors`. Needs `scout_count: int = 12` (configurable 10–15), `use_play_again: bool = True`, and hotkey constants (`F5`–`F8`). |
| [`tds_macro/window.py`](../tds_macro/window.py) | Complete | DPI-aware (`PROCESS_PER_MONITOR_DPI_AWARE = 2`), finds `RobloxPlayerBeta.exe` (`WINDOWSCLIENT`), computes `ClientRect`, and provides `scale(rx, ry)` and `scale_rect(x, y, w, h)`. |
| [`tds_macro/capture.py`](../tds_macro/capture.py) | Complete | Uses `dxcam` (Desktop Duplication API) with automatic `mss` fallback. Captures BGR numpy frames cropped to the Roblox client area. |
| [`tds_macro/vision.py`](../tds_macro/vision.py) | Complete | Multi-scale `cv2.matchTemplate`, HSV masks (`find_green_buttons`, `find_yellow_Close_buttons`, `color_fraction`), and `pixel_changed`. |
| [`tds_macro/ocr.py`](../tds_macro/ocr.py) | Complete | Uses `winocr` (`Windows.Media.Ocr`, ~50–120ms/crop). Includes `find_text`, `read_int`, `read_signed_ints`, and `parse_number` (`K`/`M` suffixes). |
| [`tds_macro/input.py`](../tds_macro/input.py) | Complete | Uses `pydirectinput` + Win32 `mouse_event`. Uses the essential **1 px relative mouse nudge (`MOUSEEVENTF_MOVE`)** before clicks so Roblox's GuiService registers hover state. Also supports `rotate_camera(dx, dy)` and `scroll(clicks)`. |
| [`tds_macro/state.py`](../tds_macro/state.py) | Complete | Classifies screen into `LOBBY`, `ITEMS`, `PLAY_MENU`, `SQUAD_SELECT`, `INTERMISSION`, `MODIFIERS`, `OVERRIDE`, `GAMEPLAY_PREP`, `GAMEPLAY`, `VICTORY`, `DEFEAT`, `DISCONNECTED`, or `UNKNOWN`. |
| [`tds_macro/runlog.py`](../tds_macro/runlog.py) | Complete | Appends `RunRecord` entries to `logs/runs.jsonl` and `logs/runs.csv` and calculates `hourly()` and `summary()` statistics. |
| [`tds_macro/core.py`](../tds_macro/core.py) | Needs fixes | `read_cash()` previously scanned `(2150, 1280, 410, 160)`, missing the in-round cash display (`$600` / `$1,649`) next to hotbar slot 5 (`x ≈ 1400..1850`). Must widen region to `(1300, 1240, 1260, 200)` and add `read_tower_count()`, `scout_checked` session flag, and UI event callbacks. |
| [`tds_macro/flows/lobby.py`](../tds_macro/flows/lobby.py) | Needs fixes | Lobby navigation (`Items`, `Play -> Survival -> Easy -> Solo`) works. Intermission flow needs the corrected sequence: Modifiers -> Walk from spawn to Override terminal -> Open `[E] Override Map` with verification -> Select `Insane -> Dead Ahead` -> Walk from Override terminal to Map Selector Board pad -> Ready. |
| `tds_macro/flows/match.py` | Missing (New) | Needs full implementation for top-down street-light camera setup, `I`/`O` zoom keys, 10–15 Golden Scout placement & upgrade loop, wave skip, and Victory screen OCR + `Play Again`. |
| `tds_macro/flows/runloop.py` | Missing (New) | Imported by `__main__.py:158` (`from .flows import runloop`), needs full state-machine orchestration loop. |
| `tds_macro/watchdog.py` | Missing (New) | Global hotkeys (`F5` Start/Resume, `F6` Pause, `F7` Overlay, `F8` Kill Switch). |
| `tds_macro/ui/` | Missing (New) | Iteration 2 `customtkinter` dark control panel (`app.py`) with hourly Coins/Gems chart and Win32 click-through transparent HUD overlay (`overlay.py`). |

---

## 3. Complete Visual Walkthrough & Reference Screenshot Catalog (`2560x1440`)

Every step of the user's walkthrough was verified against the reference screenshots in `refs/` and full-screen captures in `%TEMP%\tds_macro`:

### Phase 1: Lobby Currency & One-Time Golden Scout Check
1. **`refs/Screenshot 2026-10-21 221208.png` — Lobby Currency Display**:
   - Displays **Coins** (`103,769`, gold icon) and **Gems** (`2,095`, purple gem icon) stacked vertically with a `+` button (`(2362, 718)` on right HUD or left-side HUD depending on user layout).
   - **Rule**: Read both Coins and Gems at the start of each run to compute hourly Coins/hr and Gems/hr charts.
2. **`refs/Screenshot 2026-10-21 221232.png` — Left Sidebar Navigation**:
   - Four vertical icon buttons on the left edge (`x = 140`):
     - `Store`: `(140, 505)`
     - `Items`: `(140, 597)`
     - `Rewards`: `(140, 688)`
     - `Index`: `(140, 780)`
3. **`refs/Screenshot 2026-10-21 221258.png` — Items Inventory Modal (`Scout` + `Golden`)**:
   - Clicking `Items` opens the inventory modal.
   - Left sidebar shows `Scout` with a red **`UNEQUIP`** button (`(748, 868)`), confirming Scout is equipped.
   - Below the 3D preview is the yellow **`Golden`** toggle pill (`(805, 800)`). When enabled, its yellow HSV fraction (`H: 18..35, S: 120..255, V: 150..255`) exceeds `0.15`.
   - Top-right yellow **`X`** button (`(1929, 326)`) closes the modal.
   - **Rule**: Only run this check **once per macro session start** (`m.scout_checked = True`).

### Phase 2: Matchmaking (`Play -> Survival -> Easy -> Solo`)
4. **`refs/Screenshot 2026-10-21 221319.png` — Bottom `PLAY` Button**:
   - Green `PLAY` button at bottom center `(1280, 1285)`.
5. **`refs/Screenshot 2026-10-21 221330.png` — Mode Selection (`Survival`)**:
   - Left tab: **`Survival`** (`(380, 285)`).
6. **`refs/Screenshot 2026-10-21 221341.png` — Difficulty Carousel (`Easy`)**:
   - `Easy` card (`"For new players"`). Found via OCR `"for new players"` / `"easy"` (scrolling the card carousel horizontally if needed).
7. **`refs/Screenshot 2026-10-21 221349.png` — Squad Selection (`Solo`)**:
   - Clicking `Easy` opens the `Mode: Easy` squad modal with **`Solo`** at `(830, 718)`.

### Phase 3: Intermission Voting Room (`Modifiers -> Override -> Map Pad -> Ready`)
8. **`refs/Screenshot 2026-10-21 221427.png` & `%TEMP%\tds_macro\0002_after_modvote_now.png` — Intermission Room Layout**:
   - Bottom-left: **Modifier Gear Button** at `(60, 1376)`.
   - Straight ahead (`W`): **4 Map Voting Boards** with 4 bright white glowing floor pads in front of them.
   - Forward-right (`D` 1.2s + `W` 1.45s): **Override Map Computer Terminal** inside a red glowing circle on the floor.
9. **`refs/Screenshot 2026-10-21 221445.png` — Modifiers Modal**:
   - Two modifier icons in the `"Select Modifiers:"` grid:
     - **Glass** (shattered heart icon): `(1088, 440)`
     - **Exploding Enemies** (explosion icon): `(1177, 455)`
   - Green **`Vote For Modifiers`** button at `(1325, 922)`, yellow **`X`** close button at `(1680, 396)`.
10. **`refs/Screenshot 2026-10-21 221506.png` & `%TEMP%\tds_macro\0001_override_grid_open.png` — `[E] Override Map` Terminal**:
    - Standing inside the red glowing circle displays the `[E] Override Map` interaction prompt (`(1918, 1005)` in `0001_override_grid_open.png`).
    - Pressing/holding `E` (or clicking the prompt) opens the Override Map modal.
11. **`refs/Screenshot 2026-10-21 221520.png` — Override Map Modal (`Insane` Tab)**:
    - Left sidebar difficulty tabs: `Easy` (`(770, 560)`), `Normal` (`(770, 622)`), `Hard` (`(770, 680)`), **`Insane`** (`(770, 742)`).
12. **`refs/Screenshot 2026-10-21 221536.png` — Selecting `Dead Ahead`**:
    - Under `Insane`, the **`Dead Ahead`** card is in the top row (`(1360, 560)`). Clicking it overrides the map.
13. **`refs/Screenshot 2026-10-21 221541.png` — Confirmation Toast**:
    - Bottom-center banner displays: **`"Map changed to Dead Ahead"`**.
14. **`refs/Screenshot 2026-10-21 221601.png` & `221617.png` — Walking to Map Selector Board & Clicking `Ready`**:
    - Overriding places `Dead Ahead` on the **leftmost board (Slot 1)** of the Map Voting Board (`221601.png`), initially with `0` votes (`"Vote for a map to start the timer!"`).
    - Walking forward-left (`A` + `W`) from the Override computer onto the leftmost white voting pad registers `1` vote for `Dead Ahead` and starts the countdown (`"Time Left: 00:34"`).
    - Clicking the green **`Ready (0/1)`** button at `(1280, 1260)` (`221617.png`) starts the match immediately.

### Phase 4: In-Match (`Dead Ahead`) Camera, Placement, Upgrades & Victory
15. **`refs/Screenshot 2026-10-21 221704.png` — Initial Match Spawn**:
    - Player spawns facing the road horizontally with the green **`Ready? -> Yes`** prompt at top-center (`(1365, 155)`).
16. **`refs/Screenshot 2026-10-21 221734.png` & `221752.png` — Top-Down Camera & Highest Street Light**:
    - Camera is pitched straight down (`rotate_camera(0, 650)`).
    - Player walks toward the **highest street light** (just below the top neon-green chevron arrow on the road median) and uses `I` / `O` keys to dial in the zoom level so the street light pole is near upper-center (`y ≈ 0.28 * H`).
17. **`refs/Screenshot 2026-10-21 221836.png` & `221912.png` — First Golden Scout Placement & Level 1/2 Upgrade**:
    - Press `1` (`$250` Golden Scout) and place just left of the road below the street light crossbar (`dx = -140, dy = -40` from center).
    - Click the placed Scout to open its left upgrade panel (`221912.png`), upgrade to **Level 1 (`$100`)** via `E`, click **`Ready? -> Yes`** at top-center to start Wave 1, then upgrade to **Level 2 (`$250`)** via `E`.
18. **`refs/Screenshot 2026-10-21 222051.png` — 10–15 Golden Scout Cluster**:
    - Up to 10–15 Golden Scouts are placed in two tight columns along the left side of the road and two columns along the right median below the street light.
    - Every Scout is upgraded to **Level 2** first, then maxed to **Level 4** (`$950` L3 -> `$2,550` L4) before Wave 20 ends.
    - Top-center **`Skip Wave? -> Yes`** is clicked whenever it appears.
19. **`refs/Screenshot 2026-10-21 222117.png` — Bottom Hotbar & Cash Display**:
    - Loadout slots `1`–`5` (`$250` Scout in slot 1).
    - Right of slot 5 (`x ≈ 1480..1750, y ≈ 1280..1420`): green **`$1,649`** cash counter and **`10 / 41`** tower count.
20. **`refs/Screenshot 2026-10-21 222652.png` — Victory (`TRIUMPH!`) Screen**:
    - Displays `TRIUMPH!`, `+93 XP`, `450 Coins`, `Time Completed: 7m 15s`, `Map: Dead Ahead`, `Wave: 20`, gray `Return To Lobby` button on the left, and green **`Play Again`** button on the right (`(1470, 1270)`).
