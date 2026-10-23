# 08 — UI Design: What Revolution Gets Right

> **If you only remember one thing:** a macro UI is not a settings form. It is a **control panel for a machine that is doing something right now**. The user needs to know three things at all times: *is it running, what is it doing, and is it working?*

This doc studies Revolution Macro's interface and documentation, extracts the patterns, and turns them into a concrete design for a TDS/BSS-style macro.

---

## 1. Why Revolution's UI feels good

Revolution is a Bee Swarm Simulator macro, but its UI principles apply to any game automation tool. The public docs show the shape of the app: a left navigation, a set of task tabs, feature cards, a status log, and a detection overlay.

What it does well, in order of impact:

### 1.1 It is organised by *task*, not by *code*

The navigation is:

- **Gather** — choose fields, patterns, boosts
- **Tools** — Vic Hop, Bug Run, Mondo Hop, Auto Field Boost
- **Connect / Relay** — accounts
- **Settings** — Macro (hotkeys, capture), Game (movement, routing), etc.
- **Status / Log**

A user thinks "I want to farm honey in Pine Tree", not "I want to enable the token-scoring subsystem". The UI mirrors the first sentence.

**Compare to the bad version:** a single window with 60 checkboxes grouped by source file. Nobody can use that.

### 1.2 Every feature is a card with an on/off switch and a summary

The docs screenshots show feature cards with:

- a title,
- an enable toggle,
- a one-line summary of the current configuration ("Enabled · On · Pine Tree"),
- a grip (six dots) for reordering,
- a click target that opens the detail editor.

This is **progressive disclosure done right**. You can see the whole state at a glance, and drill in only when needed.

```
┌────────────────────────────────────────────┐
│ ⠿  Pine Tree                     [ ON  ]   │
│    AI Gather · 4x4 · 600s · 98% backpack   │
│    Blue hive · walk return on              │
└────────────────────────────────────────────┘
```

### 1.3 Live status is always visible

The status log shows timestamped entries with **named** failures:

```
Detection Failed: Hive        attempt 3
Detection Failed: Hive        attempt 4
```

Not "Error 0x80004005". A named failure tells the user *which* detector broke, which is the single most useful debugging fact. Revolution's troubleshooting page is organised around exactly these names (`Detection Failed: Hive`, `Detection Failed: Nectar`, `Detection Failed: Quest`).

### 1.4 A detection overlay

`Show Overlay` draws bounding boxes over detected tokens and sprinklers *during* the run.

This is the highest-value feature in the entire app, because:

- It turns "it's not working" into "it can't see the tokens on the left side of the field".
- It teaches the user how the macro sees.
- It makes support conversations concrete.

### 1.5 Pre-run diagnostics

Before starting, the macro checks resolution, scaling, OCR, dependencies, and refuses to start with a specific message if something is wrong.

> `Your monitor scale must be set to 100% in order for the macro to start.`

A macro that fails loudly at startup is infinitely better than one that fails silently at minute 400.

### 1.6 Sensible defaults + presets

Revolution ships recommended configurations and lets you **paste a JSON config from the clipboard** onto a field card. The default settings are described as "the meta settings ship by default".

This means a new user can be productive in one minute, and an expert can still tune everything.

### 1.7 Plain-language option descriptions

From the docs:

> **Maximum Model FPS** — Defaults to 30. Lowering it reduces GPU load and can reduce token collection accuracy.
>
> **Eco Mode** — Uses a lightweight model. More efficient, slightly worse accuracy, limited token priority.

Every option says what it does, what the default is, and what the trade-off is. No jargon without explanation.

### 1.8 Escape hatches for weird machines

`Capture Mode: Default / Legacy Monitor / Window / Legacy` is a dropdown that lets a user switch capture backends when the default misreads their setup.

This is honest engineering: "we know our first choice doesn't work on every PC, here's the fallback, and here's how to know when to use it."

### 1.9 Visual polish

- Dark and light themes.
- Consistent spacing and card radii.
- A small icon set.
- Compact layout, because it runs next to the game.
- Screenshots in the docs are actual UI, not mockups.

None of this is decoration. A macro is a tool you stare at while debugging at 2am. Legibility is a feature.

---

## 2. The information hierarchy

A good macro UI answers these questions in this order:

```
1. Is it running?             -> big status indicator
2. What is it doing now?      -> current state + task
3. Is it working?             -> last detection + success/failure
4. What has it done?          -> counters, run history
5. How do I change it?        -> settings (collapsed by default)
6. What went wrong?           -> log + diagnostics
```

Most amateur macro UIs show #5 first and #1 last. Flip it.

---

## 3. A concrete layout for a TDS macro

```
┌──────────────────────────────────────────────────────────────────────┐
│  TDS Macro            [ ● RUNNING ]   Wave 14 · 00:32:11   [STOP]   │
├──────────────┬───────────────────────────────────────────────────────┤
│              │                                                       │
│  Dashboard   │   ┌─ Current run ──────────────────────────────────┐   │
│  Strategy    │   │  Map: Meadow        Difficulty: Intermediate   │   │
│  Loadout     │   │  Wave: 14 / 40      Cash: 12.4K                │   │
│  Recovery    │   │  Next action: upgrade Farm @ wave 15 (0:12)    │   │
│  Settings    │   └────────────────────────────────────────────────┘   │
│  Logs        │                                                       │
│              │   ┌─ Features ─────────────────────────────────────┐   │
│              │   │ ⠿ Auto Rejoin            [ ON ]                │   │
│              │   │ ⠿ Anti-AFK               [ ON ]                │   │
│              │   │ ⠿ Playtime Rewards       [ OFF ]               │   │
│              │   │ ⠿ Strategy Rotation      [ ON ]  5 runs        │   │
│              │   └────────────────────────────────────────────────┘   │
│              │                                                       │
│              │   ┌─ Live status ──────────────────────────────────┐   │
│              │   │ 03:14:07  state -> lobby                       │   │
│              │   │ 03:14:09  state -> loading                     │   │
│              │   │ 03:14:31  state -> game                        │   │
│              │   │ 03:14:32  money 12.4K (0.93)                   │   │
│              │   └────────────────────────────────────────────────┘   │
└──────────────┴───────────────────────────────────────────────────────┘
```

### Why this works

- **Status bar** at the top: running state, the two numbers that matter (wave, elapsed), and a stop button.
- **Current run card**: what the macro believes about the game right now.
- **Features**: cards, each with a switch and a summary.
- **Live status**: the log, always visible, not hidden behind a menu.

The user can leave this open on a second monitor and understand the state in one glance.

---

## 4. Screen-by-screen design

### 4.1 First run / onboarding

A wizard, not a settings dump.

```
Step 1 of 4: Display check
  ✔ Resolution 1920x1080
  ✔ Windows scale 100%
  ✘ HDR is ON          [Open display settings]
  ✔ Roblox window found

  [ Re-check ]                         [ Continue ]
```

Then:

2. **Game settings check** — camera mode, UI scale, screen shake, fonts. Offer an "Auto-configure" button.
3. **Calibration** — let the user position detection boxes over the money label, wave number, etc. (like the Fisch appraisal macro's 4-step overlay wizard).
4. **Strategy** — pick a preset or record one.

Why a wizard: it front-loads the failures that would otherwise happen at minute 400.

### 4.2 Dashboard

Only:
- big status,
- current map/mode/wave/cash,
- time elapsed, runs completed, estimated coins,
- start/stop.

No settings here.

### 4.3 Strategy

- A list of strategy cards.
- Each card: name, map, difficulty, loadout, duration, last used.
- Buttons: Record, Edit, Duplicate, Export, Delete.
- A **timeline editor** for recorded strategies (place/upgrade events at waves).
- Import/export as a code or JSON.

The "record then replay" pattern is how TDS macros dodge the hard problem of *deciding* what to do. You play once, it replays. Good UX makes recording feel safe:

```
● Recording — play a normal match.
  Captured: 14 actions (3 towers, 11 upgrades)
  [ Stop & save ]   [ Discard ]
```

### 4.4 Loadout

- The towers the strategy needs, in slot order.
- A warning if the user doesn't own one.
- A "copy from strategy" button.

### 4.5 Recovery

- Auto-rejoin: on/off, max attempts.
- Wrong map: leave and retry, or continue.
- Anti-AFK: on/off, interval.
- Stall detection: timeout.
- "If all else fails": stop, or restart Roblox.

### 4.6 Settings

Grouped, with search:

```
Macro
  Hotkeys
  Capture
  Timing
  Performance
Game
  Window
  UI scale
  Camera
Advanced
  Debug overlay
  Log level
  Config folder
```

Each option has a one-line description *and* a "reset to default" affordance.

### 4.7 Logs

- Filter by level.
- Search.
- "Copy" and "Open folder".
- Auto-scroll toggle (so you can read while it runs).
- A "Save diagnostic bundle" button (screenshot + log + config).

---

## 5. Status and error design

### 5.1 Name your failures

Bad:
```
Error: detection failed
```

Good:
```
Detection Failed: Wave Counter (attempt 3/5)
  region: 930,14 60x40
  best score: 0.41 (threshold 0.85)
  see: Settings > Debug > Save screenshot
```

The second one lets the user (or you) act.

### 5.2 Show the score

Anywhere a detection fails, show the best score. It distinguishes:

- "not on screen" (score 0.2)
- "on screen but threshold too high" (score 0.80 vs 0.85)
- "on screen but the template is wrong" (score 0.55, stable)

### 5.3 Colour + text, not colour alone

Use a status dot **and** a word:

```
● RUNNING     green
● PAUSED      amber
● STOPPED     grey
● ERROR       red
```

Colour-blind users, and screenshots in support tickets, both benefit.

### 5.4 Never show a raw stack trace to a normal user

Put it behind "Details", and put a plain sentence in front:

> "Couldn't read the wave number. This usually means a custom font is installed. [Details] [Open guide]"

---

## 6. The debug overlay

This deserves its own section because it's the most under-built feature in amateur macros.

### What it should show

| Layer | Visual |
|---|---|
| Search regions | thin grey rectangles |
| Successful detections | green boxes + label + score |
| Failed detections | red boxes + label + best score |
| Click targets | crosshair + coordinates |
| Current state | text in a corner: `STATE: game  TICK: 10234  FPS: 9.8` |
| OCR crops | small thumbnails in a side panel |

### Rules

- Toggle with a hotkey (F4).
- Never intercept clicks (`WS_EX_TRANSPARENT`).
- Never appear in your own captures (capture the game window, not the desktop).
- Draw at most 15–20 boxes; more is noise.
- Include the timestamp so a screenshot is self-documenting.

### Bonus: a "why did you click there?" panel

Keep a ring buffer of the last 20 actions:

```
03:14:07.512  CLICK (960, 812)  target=play       score=0.94
03:14:09.004  KEY   space       reason=anti-afk
03:14:12.220  CLICK (1440, 300) target=tower_slot score=0.88
```

When a user says "it clicked the wrong thing", this answers it instantly.

---

## 7. Settings design rules

1. **Defaults must be good.** Most users never change anything.
2. **Group by user intent**, not by implementation.
3. **Explain the trade-off** in one sentence.
4. **Show units.** `Delay: 250 ms`, not `Delay: 250`.
5. **Constrain input.** Sliders/steppers with min/max, not free text.
6. **Validate immediately.** If a value is invalid, say so next to the field.
7. **Reset to default** on every field.
8. **Search** if there are more than ~30 options.
9. **Advanced section** collapsed by default.
10. **Never require a restart** unless truly necessary.

### Example of a good option row

```
┌──────────────────────────────────────────────────────────────┐
│ Action delay                              250 ms   [====|--] │
│ Time between clicks. Raise this if actions are being missed. │
│                                                    Reset     │
└──────────────────────────────────────────────────────────────┘
```

### Example of a bad option row

```
[ ] Delay: [250]
```

---

## 8. Onboarding and calibration

Calibration is where most users get stuck, so make it visual.

### The overlay calibration wizard

```
┌─────────────────────────────────────────────────────────────┐
│  Step 3 of 5: Wave number                                   │
│                                                             │
│  Drag a box around ONLY the wave number.                    │
│  Do not include the word "Wave".                            │
│                                                             │
│         ┌ ─ ─ ─ ─ ─ ─ ┐                                     │
│         │     14      │   <- live preview                  │
│         └ ─ ─ ─ ─ ─ ─ ┘                                     │
│                                                             │
│  Test read: "14"  ✔                                         │
│                                                             │
│  [ Back ]                              [ Retry ] [ Next ]  │
└─────────────────────────────────────────────────────────────┘
```

Key details:

- **Live preview** of the crop, not a static instruction.
- **Test read** so the user knows it works before continuing.
- **Tight-box guidance** ("only the numbers, not the letters") — the Fisch appraisal macro docs say exactly this because including "KG" breaks OCR.
- **Persist the box as reference-resolution coordinates**, scaled at runtime.

### Auto-calibration (better)

If you can detect the element automatically, offer "Auto-detect" first and fall back to manual. Revolution/Pokémon-style macros do this with "Detect" vs "Check" hive modes.

---

## 9. Anti-patterns to avoid

| Anti-pattern | Why it hurts | Fix |
|---|---|---|
| Settings dump as the main screen | User can't tell if it's running | Status-first layout |
| "Error" with no context | Unactionable | Named errors + score + region |
| Hidden log | Can't debug | Always-visible status strip |
| Modal dialogs during a run | Blocks the loop | Toasts / inline banners |
| Auto-start on launch | Starts clicking before the game is ready | Require explicit start |
| No stop button during a run | Dangerous | Persistent stop + hotkey |
| Reset everything on update | Loses user config | Migrate schema |
| Tiny fonts, low contrast | Unreadable at 2am | 12–14px minimum, high contrast |
| Overlay that eats clicks | Game becomes unplayable | Click-through overlay |
| "It just works" with no diagnostics | Unfixable support load | Pre-run checks |
| 40 toggles on one page | Overwhelming | Cards + progressive disclosure |
| Requiring the user to edit JSON | Hostile | GUI editor, JSON as export only |

---

## 10. Visual design basics

You don't need a designer, but you do need consistency.

| Element | Recommendation |
|---|---|
| Base font | System UI font, 12–14 px |
| Monospace | For logs, coordinates, scores |
| Spacing | 8 px grid (8/16/24/32) |
| Corner radius | 6–8 px |
| Card background | 1 step lighter/darker than page |
| Accent colour | One, used only for primary actions and "running" |
| Status colours | Green / amber / grey / red, always with text |
| Icons | One set, 16–20 px, same stroke width |
| Density | Compact — it lives next to a game |
| Theme | Dark by default, light optional |
| Window | Resizable, min ~900×600, remembers position |

### Dark theme specifics

Game macros are used at night. Dark theme reduces glare and matches the game.

- Background: near-black but not pure black (`#14161a`).
- Cards: `#1c1f26`.
- Text: `#e6e8ec` primary, `#9aa1ad` secondary.
- Borders: `#2a2f3a`.
- Accent: a single saturated colour (blue/teal).
- Success `#3fb950`, warning `#d29922`, error `#f85149`.

---

## 11. Implementation options

| Stack | UI quality | Effort | Notes |
|---|---|---|---|
| **AutoHotkey v2 + Gui** | Basic | Low | Native-ish, tiny, but ugly and painful for complex layouts |
| **Python + Tkinter/ttk** | Basic | Low | Ships with Python, theming is limited |
| **Python + PySide6/Qt** | Good | Medium | Proper widgets, styling, dark themes; ~60 MB |
| **C# + WPF/WinUI** | Very good | Medium | Native Windows, good performance, single-file publish |
| **Tauri + web UI** | Very good | Medium | Small binary, web flexibility, Rust backend |
| **Electron + React** | Very good | Medium | Heavy (~100 MB+), but fastest to build rich UI |
| **ImGui** | Good (tool-like) | Medium | Perfect for debug overlays, less so for settings |

**Recommendation:**

- If you're building in AHK: use AHK Gui, keep it simple, invest in the log and overlay instead of polish.
- If you're building in Python: PySide6 if you want a real app; Tkinter if you want zero dependencies.
- If you want a modern look with a small binary: Tauri.
- Only use Electron if you already know React and don't care about 100 MB.

**Critical:** whichever you pick, run the UI on its own thread and communicate with the core through a queue (see [07-macro-architecture.md](07-macro-architecture.md)).

---

## 12. UI checklist

- [ ] Status (running/paused/stopped/error) is visible at all times.
- [ ] The current task is visible in plain language.
- [ ] A stop button is always reachable, plus an emergency hotkey.
- [ ] Features are cards with a toggle + a one-line summary.
- [ ] Log is visible without opening a menu.
- [ ] Errors are named and include the detection score.
- [ ] A debug overlay exists and is one hotkey away.
- [ ] Pre-run diagnostics check resolution, scale, OCR, and game settings.
- [ ] First-run wizard calibrates the important regions with live previews.
- [ ] Every setting has a description and a reset.
- [ ] Defaults are good enough to run without touching anything.
- [ ] Window is compact and remembers its position.
- [ ] Dark theme by default.
- [ ] No modal dialogs during a run.

---

## Sources

- Revolution docs home (navigation, screenshots, themes): <https://revolutionmacro.com/docs/>
- Revolution gather tab / field cards: <https://revolutionmacro.com/docs/gathering/choose-fields-and-patterns/>
- Revolution AI Gather settings (option descriptions, defaults, overlay): <https://revolutionmacro.com/docs/gathering/set-up-ai-gather/>
- Revolution detection troubleshooting (named errors, capture modes): <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>
- Revolution AI Studio (separate IDE, live preview, test bench): <https://revolutionmacro.com/docs/ai-studio/what-ai-studio-is/>
- Ultimate Macro setup guide (pre-run diagnostics, "Auto Configure Settings", Potato Mode, Legacy Mode): <https://ultmacro.xyz/guide/>
- Fisch appraisal macro (4-step visual calibration wizard, tight OCR box): <https://robloxtutorial.com/best-roblox-fisch-macro/>

---

*Next: [09-game-notes-tds-bss.md](09-game-notes-tds-bss.md)*
