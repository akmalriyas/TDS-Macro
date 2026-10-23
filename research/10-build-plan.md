# 10 — Build Plan

> **If you only remember one thing:** build the *debug tools* before the macro. A screenshot saver, a template cropper, and an overlay will save you more time than any clever algorithm.

---

## 1. Pick your stack first

| Stack | Best for | Binary size | Dev speed | UI | Vision | Roblox input |
|---|---|---|---|---|---|---|
| **AutoHotkey v2** | Small Windows-only tool, fast iteration | ~2–5 MB | ★★★★★ | ★★☆ | ★★☆ (Gdip/FindText) | ★★★★★ (proven) |
| **Python 3.12** | Prototyping, CV-heavy work | 40–120 MB packaged | ★★★★★ | ★★★☆ | ★★★★★ | ★★★★☆ |
| **C# / .NET 8** | Polished Windows app | 15–60 MB | ★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ |
| **Rust / C++** | Max performance, tiny binary | 2–10 MB | ★★☆ | ★★☆ | ★★★★☆ | ★★★★☆ |
| **Electron / Tauri** | Rich UI shell | 80–150 MB / 5–15 MB | ★★★★ | ★★★★★ | depends on backend | depends |

### Recommendation

- **Prototype in Python.** Fastest to test capture, matching, and OCR. You'll throw away half of it, which is the point.
- **Ship in C#** if you want a nice UI, a single-file exe, and native Windows OCR without packaging pain.
- **Ship in AHK v2** if you want the smallest possible tool and you're comfortable with its limits. This is what Ultimate Macro (TDS) and Natro (BSS) use, so it's clearly viable.
- **Only use Electron/Tauri** if the UI is a big part of the product. For a farm macro, it's usually overkill.

If you're unsure: **Python + PySide6 for the UI, packaged with PyInstaller**. You can always port later.

---

## 2. Phase 0 — Feasibility (half a day)

**Goal:** prove you can see the game.

Deliverable: `tools/capture_debug.py` that:

1. Finds `RobloxPlayerBeta.exe`.
2. Gets the client rect.
3. Captures it.
4. Saves `debug/full.png`.
5. Prints the size, DPI, and mean brightness.

**Done when:** you have a correct screenshot of the game, at the right size, and clicking a coordinate you compute hits the right pixel.

**Pitfalls:** DPI awareness, exclusive fullscreen, white/black frames.

---

## 3. Phase 1 — Window + capture layer (1–2 days)

**Goal:** a reliable, reusable capture module.

Deliverables:

- `perception/window.py` — find, focus, client rect, DPI, is-alive.
- `perception/capture.py` — region capture with a pluggable backend (`mss`, `dxcam`, `wgc`).
- `tools/live_view.py` — shows the capture at 10 FPS with a cursor position readout.

**Done when:**

- Capture works at 10 Hz with < 10 ms per frame for a 400×200 region.
- It handles the window moving and resizing.
- It detects all-black/all-white frames.
- It survives the window being minimised (returns an error, not a crash).

**Pitfalls:** GDI leaks, re-creating the capture object every frame, capturing the desktop instead of the window.

---

## 4. Phase 2 — Detection layer + template tool (2–4 days)

**Goal:** find things reliably, and be able to add new things in minutes.

Deliverables:

- `perception/detect.py` — template match, multi-scale, masks, colour ratio, pixel signature, stable-frame filter, cooldown.
- `tools/template_tool.py` — a GUI or CLI that:
  - loads a screenshot,
  - lets you drag a box,
  - saves the crop as a PNG,
  - writes the JSON metadata (search box, threshold),
  - test-runs the match and shows the score.
- `assets/` with the first 5 templates (play, ready, play again, close, reconnect).

**Done when:** you can add a new button to the macro in under 2 minutes without writing code.

**Pitfalls:** templates that are too large, thresholds guessed instead of measured, no NMS.

---

## 5. Phase 3 — Input layer (1–2 days)

**Goal:** clicks that actually register, every time.

Deliverables:

- `actions/mouse.py` — move, click, drag, right-click, scroll, with the Roblox nudge fix.
- `actions/keyboard.py` — press, hold, key combos, with 20–50 ms holds.
- `actions/humanize.py` — bezier moves, jittered delays.
- `tools/click_test.py` — click a grid of points and verify the game reacts.

**Done when:** 100 consecutive clicks on a button all register, with the window focused, from a cold start.

**Pitfalls:** `ControlClick` (doesn't work), missing the 1px nudge, keys too short, admin mismatch.

---

## 6. Phase 4 — World state + lobby loop (2–3 days)

**Goal:** join a game, play it, and come back to the lobby — unattended.

Deliverables:

- `app/state.py` — `WorldState`.
- `perception/world.py` — builds the world state from one frame.
- `app/states/` — `idle`, `lobby`, `loading`, `game`, `results`, `recover`.
- A working loop: Lobby → Ready → Match → Results → Play Again → Lobby.

**Done when:** the macro completes 10 matches in a row with no human input.

**Pitfalls:** menus that animate, buttons that need a second click, the results screen taking time to appear.

---

## 7. Phase 5 — Number reading (2–3 days)

**Goal:** money and wave, reliably.

Deliverables:

- `perception/ocr.py` — Windows OCR wrapper with language check.
- `perception/numbers.py` — parser + validator + tracker.
- `tools/ocr_tuner.py` — feed it saved crops and see the raw text, parsed value, and pass/fail.

**Done when:**

- Wave is read correctly 99%+ of the time over a full match.
- Money is read correctly or rejected (never silently wrong) 99%+ of the time.
- The main loop never blocks on OCR.

**Pitfalls:** suffix parsing, OCR character confusion, no validation, calling OCR every tick.

---

## 8. Phase 6 — Strategy recording and replay (3–5 days)

**Goal:** the macro can play a real TDS strategy.

Deliverables:

- A recorder that logs `(wave, action, payload)` while the user plays.
- A `.strat` JSON format.
- A replayer that waits for the wave and executes.
- Verification after each action (did cash drop? did the tower appear?).
- At least 2 working strategies.

**Done when:** a recorded strategy replays and wins the same way it did when recorded, 5 times in a row.

**Pitfalls:** camera drift, placement validation, upgrades needing a tower selection first, split-path towers.

---

## 9. Phase 7 — Recovery + anti-AFK + long-run stability (2–3 days)

**Goal:** survive an 8-hour unattended run.

Deliverables:

- Reconnect flow.
- Wrong-map detection and requeue.
- Dialog dismissal.
- Anti-AFK heartbeat.
- Watchdog.
- Run/attempt limits with a clean stop.
- Discord/webhook notification (optional but nice).

**Done when:** you can disconnect the network for 60 seconds mid-run and the macro recovers without human input.

**Pitfalls:** infinite retry loops, forgetting to reset the attempt counter, recovery states that themselves get stuck.

---

## 10. Phase 8 — UI (4–7 days)

**Goal:** something a non-developer can use.

Deliverables (see [08-ui-design-revolution.md](08-ui-design-revolution.md)):

- Main window with status, current run, feature cards, log.
- Settings with validation and reset-to-default.
- First-run wizard.
- Debug overlay.
- Save/share strategy.

**Done when:** someone who has never seen the tool can install it, calibrate it, and start a run using only the UI.

**Pitfalls:** UI thread blocking, modal dialogs during runs, no stop button.

---

## 11. Phase 9 — Packaging + distribution (1–2 days)

- Single executable if possible.
- Config and assets in a predictable folder (`%APPDATA%\TDSMacro` or next to the exe).
- First-run creates defaults; updates migrate.
- Version number visible in the UI.
- Crash dumps to a `crash/` folder.
- A README with the exact supported environment.
- Optional: auto-update via signed releases (Ultimate Macro ships via GitHub Releases).

**Done when:** a fresh Windows VM can run it without Python/AHK/.NET pre-installed (or with a clearly documented prerequisite).

---

## 12. Phase 10 — Test matrix + beta (ongoing)

### 12.1 Automated tests

| Test | What it covers |
|---|---|
| `test_numbers.py` | `1.2K`, `12,345`, `1.234,56`, `3.4B`, garbage |
| `test_scaling.py` | 1280×720 → 3840×2160 mapping |
| `test_states.py` | Feed fake world states; assert transitions |
| `test_detect.py` | Golden screenshots; assert found/not found and score ranges |
| `test_parser.py` | Torrents of OCR strings, including known confusions |

Golden screenshots are the most valuable: save 30–50 real frames covering every screen, and run detection against them in CI. When you change a threshold, you immediately see what broke.

### 12.2 Manual test matrix

| Dimension | Values |
|---|---|
| Resolution | 1280×720, 1920×1080, 2560×1440, 3840×2160 |
| Windows scale | 100% (required), 125%, 150% (expect refusal or degradation) |
| GPU | NVIDIA, AMD, Intel iGPU |
| Roblox mode | Windowed, borderless |
| Network | normal, 200 ms latency, disconnect mid-match |
| Duration | 10 min, 1 h, 8 h |

### 12.3 Fault injection

Deliberately break things:

- Kill the network for 30 s.
- Move the window mid-run.
- Open a dialog.
- Change the map.
- Minimise the game.
- Change Windows scale mid-run.
- Put a window on top of the game.

Each should produce a clear recovery or a clean stop — never a wrong click.

### 12.4 Soak test

Run overnight. In the morning, check:

- Did it complete runs? How many?
- Any stuck states?
- Memory usage growth?
- Log size?
- Any wrong clicks (check the log for unexpected actions)?
- Did it stop cleanly or hang?

---

## 13. Suggested timeline (one developer, part-time)

| Phase | Days |
|---|---|
| 0–1 Capture | 2 |
| 2 Detection | 4 |
| 3 Input | 2 |
| 4 Lobby loop | 3 |
| 5 Numbers | 3 |
| 6 Strategy | 5 |
| 7 Recovery | 3 |
| 8 UI | 6 |
| 9 Packaging | 2 |
| 10 Testing | continuous |
| **MVP (phases 0–5)** | **~2 weeks** |
| **Usable tool (0–8)** | **~5 weeks** |
| **Polished (0–10)** | **~8–10 weeks** |

The first version that does something useful is much closer than it feels. The long tail is edge cases.

---

## 14. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Game update moves the UI | High | High | Anchors + templates as data; fast asset updates |
| Works on your PC only | High | High | Test matrix; refuse unsupported configs |
| OCR too slow/inaccurate | Medium | Medium | Digit templates fallback; cache |
| Camera drift breaks placement | High | High | Wave-synced replay + verify placement |
| Account banned | Medium | High | See [11-safety-and-tos.md](11-safety-and-tos.md); use an alt |
| Users can't install it | Medium | Medium | One-click build; prerequisites check |
| Support load explodes | High | Medium | Diagnostics, named errors, log bundle |
| Scope creep (AI, 10 games) | High | High | Ship ONE game and ONE strategy first |

---

## 15. Day 1 checklist

If you start right now, do this:

1. Create the folder structure from [07-macro-architecture.md](07-macro-architecture.md).
2. Write `tools/capture_debug.py`.
3. Run it against Roblox, save a screenshot, and confirm the size and content.
4. Mark the money label, wave number, and "Play" button by hand in an image editor.
5. Crop them into `assets/`.
6. Write a 30-line script that finds the "Play" button in the saved screenshot.
7. Print the score and draw a box. Save the debug image.
8. Only then start building the loop.

If step 3 doesn't work, stop and fix capture. Nothing else matters until you can see the game.

---

## 16. What "done" looks like

A farm macro is done when:

- A new user can install it, run the wizard, and start a run in under 5 minutes.
- It completes 50+ consecutive matches without human input.
- It never clicks when it isn't sure — it stops and says why.
- Any failure produces a log line that names the detector and shows the score.
- It survives a disconnect, a wrong map, and a popup.
- It runs 8 hours without leaking memory or filling the disk.
- You can add a new button or a new map in under 10 minutes.

---

*Next: [11-safety-and-tos.md](11-safety-and-tos.md)*
