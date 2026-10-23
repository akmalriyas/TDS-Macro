# 01 — The Big Picture

> **If you only remember one thing:** a macro is a camera + a brain + a hand, running in a loop. Everything else is engineering.

---

## 1. What a macro actually is

A game macro is a normal Windows program that:

1. **Looks** at the screen (a picture of pixels).
2. **Interprets** that picture (finds a button, reads a number, recognises a menu).
3. **Decides** what to do (a state machine or script).
4. **Acts** by moving the real mouse and pressing real keys.
5. **Checks** whether the action worked.
6. Repeats, usually 5–30 times per second.

It does **not** need to touch the game's code. It does **not** need to be "inside" Roblox. From the operating system's point of view it is just another app using the mouse.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   CAPTURE    │ --> │  PERCEPTION  │ --> │   DECISION   │
│ screenshot   │     │ find / read  │     │ state machine│
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                                                  v
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   VERIFY     │ <-- │    ACTION    │ <-- │   PLANNING   │
│ did it work? │     │ mouse / keys │     │ target pixel │
└──────────────┘     └──────────────┘     └──────────────┘
        │
        └────────────── loop forever ──────────────┘
```

---

## 2. "External" vs "internal" — the line you must not cross

There are two completely different kinds of game automation.

| | **External (what this folder is about)** | **Internal (exploits)** |
|---|---|---|
| How it works | Reads the screen, moves the real mouse | Injects code into the game process |
| Sees | Only what a human could see | Game memory, hidden values, positions |
| Needs | Screenshot + input APIs | A code executor / DLL injection |
| Examples | Revolution, Natro, TDS macros, AutoHotkey scripts | Script executors |
| Roblox's anti-cheat | Not targeted — it's outside the process | Actively targeted by Hyperion/Byfron |

Revolution says this plainly in its docs: *"It does not inject into Roblox or change game files. While the macro runs, it watches what is on your screen and sends the normal keyboard and mouse clicks the game needs."*

**Why this matters for design:** you cannot read `player.Money` from memory. You must infer money from pixels. That single constraint is why OCR and template matching exist in this world at all.

> Note: "not injected" is not the same as "allowed". See [11-safety-and-tos.md](11-safety-and-tos.md).

---

## 3. The four families of screen reading

Every macro uses some mix of these. From cheapest/simplest to most flexible.

### 3.1 Blind playback (TinyTask-style)
Record mouse/keyboard with timestamps, replay them exactly.

- **Cost:** almost zero.
- **Works when:** the game is 100% deterministic and the window never moves.
- **Breaks when:** a loading screen takes 1 second longer, the window moves, a popup appears, or the resolution changes.
- **Verdict:** fine for a 20-second repeating clicker. Useless for TDS.

### 3.2 Colour detection
Check the colour of specific pixels, or count how many pixels in a region match a colour.

- **Cost:** extremely low (microseconds).
- **Good for:** "is this button green?", "is the health bar above 50%?", "did the screen fade to black?", "is the inventory open?"
- **Bad for:** anything with text or complex shapes.
- **Example:** look at the pixel at the centre of a "Ready" button. Green = ready, grey = not ready.

### 3.3 Image / template matching
Take a small crop of a UI element (a button, an icon, a logo). Slide it over the screenshot and find where it matches best.

- **Cost:** low to medium (1–20 ms depending on area and scales).
- **Good for:** buttons, icons, menu headers, "Play Again", tower icons, coin icons.
- **Bad for:** things that change size, rotate, animate, or get covered.
- **This is the backbone of TDS/BSS macros.**

### 3.4 OCR (optical character recognition)
Convert a picture of text into actual characters.

- **Cost:** high (100–300 ms per call for Windows OCR; more for Tesseract on CPU).
- **Good for:** money, wave number, pollen count, quest text, player names.
- **Bad for:** fast loops, tiny fonts, stylised fonts, animated/scrolling text.
- **Used sparingly, on small crops, with caching.**

### 3.5 (Modern) small ML models
Revolution now uses trained models to find BSS tokens and sprinklers. This is still "look at the screen" — it's just a smarter detector than template matching.

- **Cost:** needs a GPU or a fast CPU; 5–30 FPS.
- **Good for:** objects that vary a lot (spinning tokens, different lighting).
- **Bad for:** tiny UI buttons where a template is already perfect.
- **Not required** to build a working macro. Start without it.

---

## 4. What the macro is actually deciding

Beginners imagine a macro as "a list of clicks". Real macros are **state machines**.

Example for TDS:

```
LOBBY
  ├─ detect "Play" button         -> click
  ├─ detect map vote screen       -> vote for chosen map
  └─ detect "Ready"               -> click

LOADING
  └─ wait for wave 1 HUD          -> timeout 60s -> rejoin

IN_MATCH
  ├─ read wave number
  ├─ if wave in strategy          -> place / upgrade tower
  ├─ if ability ready             -> press ability key
  └─ if "Victory"/"Defeat"        -> RESULTS

RESULTS
  ├─ read rewards
  ├─ click "Play Again"
  └─ back to LOBBY (or rejoin if button missing)

RECOVERY (from any state)
  ├─ detect disconnect screen     -> rejoin
  ├─ detect wrong map             -> leave + rejoin
  └─ detect stuck > N seconds     -> reset
```

Every state has three things:

- **Entry condition** — how do I know I'm here?
- **Tick action** — what do I do each loop?
- **Exit condition + timeout** — how do I leave, and what if I never do?

If you write your macro as a state machine, 80% of "it randomly stops working" bugs disappear, because you can *see* which state it's stuck in.

---

## 5. The perception pipeline in detail

This is the part that separates a toy from a tool.

```
full screen (1920x1080)
   │
   ├─ 1. find the Roblox window          (Win32: FindWindow / EnumWindows)
   ├─ 2. get its client rectangle        (GetClientRect + ClientToScreen)
   ├─ 3. capture only what you need      (e.g. 400x120 region)
   │
   ▼
crop
   │
   ├─ 4. convert to grayscale            (3x less data, matching is easier)
   ├─ 5. optional: threshold / edges     (make the shape pop)
   │
   ▼
detect
   │
   ├─ 6a. template match -> score + x,y
   ├─ 6b. colour test    -> true/false
   ├─ 6c. OCR            -> string
   │
   ▼
interpret
   │
   ├─ 7. score >= threshold?  no -> "not found", wait, retry
   ├─ 8. convert to a game concept: "Ready button is visible"
   ├─ 9. sanity-check against last known state
   │
   ▼
world model  ("we are in LOBBY, money is ~12.4K, wave is 7")
```

The "world model" is important. Don't let every part of your code take its own screenshot and make its own decision. Capture once per tick, build one world model, then let the state machine read from it.

---

## 6. How fast does it need to be?

| Task | Needed rate | Why |
|---|---|---|
| Detecting a menu / button | 2–5 Hz | Humans take ~200 ms to react anyway |
| Reading money | 1–2 Hz | It changes slowly; OCR is expensive |
| Tracking a moving object | 15–30 Hz | Needs to keep up with motion |
| Reacting to a projectile | 60+ Hz | Rarely needed for farm macros |

**A farm macro running at 5–10 FPS of perception is completely normal.** Revolution's AI gather defaults to a "Maximum Model FPS" of 30, and that's for a much harder detection problem than TDS.

Do not chase 240 FPS. You will burn CPU, add heat, and gain nothing. Optimise *latency to react*, not frames per second.

Latency budget example for a click:

```
capture region        3 ms
grayscale + match     5 ms
decision              <1 ms
mouse move + click    5-15 ms (depends on OS/game)
verify next frame     100 ms (next tick)
------------------------------------
total                 ~120 ms
```

That is fine. Games are designed for human reaction times of 200–300 ms.

---

## 7. The "it works on my PC" trap

This is the number one reason macros fail for other people. Your macro was built on:

- 1920×1080, 100% scaling, 16:9, one monitor, English Windows, 60 FPS, borderless.

Your user has:

- 2560×1440 at 125% scaling, 21:9 ultrawide, HDR on, two monitors, a custom font mod, 30 FPS, and the taskbar on autohide.

Everything breaks at once. The fix is a combination of:

1. **Normalise** — convert every coordinate to window-relative and scale by the reference resolution.
2. **Verify** — find an anchor element on screen and correct your offsets from it.
3. **Refuse** — if the environment is unsupported, show a clear error instead of clicking randomly.

Revolution chose a strict version of #3:

> Resolution: minimum 1366×768, 1920×1080 recommended. Horizontal widescreen only. Scale: 100%. HDR: off. Windows text size 100%.
> *"Your monitor scale must be set to 100% in order for the macro to start."*

Ultimate Macro (TDS) is more permissive but still constrained:

> Supported 16:9 from 1280×720 to 3840×2160, 1920×1080 reference, Windows scale 100%, taskbar visible, English (US) OCR pack, TDS UI Scale "Large", screen shake off.

That is the real-world trade-off: **support fewer configurations well**, or **support many configurations with lots of fallbacks**. Pick one deliberately.

---

## 8. What "reading the screen" cannot tell you

Be honest about the limits:

| You want | Screen reading gives you | Problem |
|---|---|---|
| Exact money | `1.2M` | Only 2 significant digits. You know it's between 1.15M and 1.25M. |
| Cooldown remaining | A greyed-out icon | You know "not ready", not "3.4s left". |
| Enemy HP | A bar width | Approximate percentage, not a number. |
| Whether a tower is placed | A model on the ground | Hard to distinguish from decoration. |
| Server population | Player list text | Needs OCR + scrolling. |

Design around this. If you only need "money ≥ 10K", then `1.2M` is plenty. If you need exact arithmetic, you need a different signal (e.g. read the number *before* and *after* a purchase and use the difference).

---

## 9. A mental model for the whole app

```
┌─────────────────────────────────────────────────────────┐
│  UI (settings, status, log, overlay)                    │
└──────────────────────┬──────────────────────────────────┘
                       │ commands / events
┌──────────────────────▼──────────────────────────────────┐
│  ORCHESTRATOR  (state machine, scheduler, recovery)     │
└───────┬───────────────────────────────┬─────────────────┘
        │ world model                   │ actions
┌───────▼──────────────┐        ┌───────▼─────────────────┐
│  PERCEPTION          │        │  INPUT                  │
│  capture → detect    │        │  move / click / key     │
│  → OCR → world model │        │  with human timing      │
└───────┬──────────────┘        └───────┬─────────────────┘
        │                               │
┌───────▼───────────────────────────────▼─────────────────┐
│  PLATFORM LAYER (Win32, DXGI/WGC, OCR engine)           │
└─────────────────────────────────────────────────────────┘
```

Keep the platform layer thin and dumb. Keep the orchestrator free of pixel code. That way you can swap AHK for Python for C# without rewriting your game logic.

---

## Sources

- Revolution Macro — what it does: <https://revolutionmacro.com/docs/getting-started/what-revolution-does/>
- Revolution detection problems (environment requirements): <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>
- Ultimate Macro setup guide (TDS requirements): <https://ultmacro.xyz/guide/>
- ExoPanda architecture write-up (four detection families): <https://exopanda.com/guides/how-exopanda-works>
- Natro Macro source: <https://github.com/NatroTeam/NatroMacro>

---

*Next: [02-screen-capture.md](02-screen-capture.md)*
