# 07 — Macro Architecture (Lightweight but Solid)

> **If you only remember one thing:** separate *seeing*, *deciding*, and *doing* into different modules, and run them on different threads so a 200 ms OCR call never freezes your clicks or your UI.

---

## 1. Design goals

A macro that runs for 8 hours needs different priorities from a demo script:

| Goal | What it means in practice |
|---|---|
| **Never freeze** | UI stays responsive; stop button always works |
| **Never die silently** | Every loop has a timeout and a recovery path |
| **Never leak** | Bitmaps, GDI objects, threads, and file handles are released |
| **Never lie** | If detection fails, it says so instead of clicking randomly |
| **Easy to debug** | Logs + screenshots + an overlay that shows what it sees |
| **Easy to extend** | Adding a new game/button is data, not surgery |

"Lightweight" doesn't mean "few files". It means **no unnecessary runtime**: no database, no web server, no microservices, no Electron if you can avoid it.

---

## 2. The four layers

```
┌─────────────────────────────────────────────────────────────┐
│  UI LAYER                                                   │
│  settings window, status, log, overlay, hotkeys             │
│  (talks to the core via a simple command/event interface)   │
└───────────────────────────┬─────────────────────────────────┘
                            │ commands: start, stop, pause, reload config
                            │ events: state changed, log line, detection
┌───────────────────────────▼─────────────────────────────────┐
│  CORE LAYER                                                 │
│  state machine · scheduler · config · recovery · logging    │
│  (pure logic; no Win32, no OpenCV, no pixels)                │
└──────────┬──────────────────────────────────┬───────────────┘
           │ world model                      │ actions
┌──────────▼───────────────┐      ┌───────────▼───────────────┐
│  PERCEPTION              │      │  ACTUATION                │
│  capture · detect · OCR  │      │  move · click · key       │
│  builds a WorldState     │      │  humanises timing          │
└──────────┬───────────────┘      └───────────┬───────────────┘
           │                                  │
┌──────────▼──────────────────────────────────▼───────────────┐
│  PLATFORM LAYER                                             │
│  Win32 · DXGI/WGC · OpenCV · OCR engine · SendInput          │
│  (the only code that knows what OS it's on)                 │
└─────────────────────────────────────────────────────────────┘
```

**The rule:** the core layer must be testable without a game running. You should be able to feed it fake `WorldState` objects and check that it makes the right decisions.

---

## 3. The world state

One object, rebuilt every tick, that describes everything the macro currently believes.

```python
from dataclasses import dataclass, field

@dataclass
class WorldState:
    t: float = 0.0

    # window
    hwnd: int = 0
    client: tuple = (0, 0, 0, 0)      # x, y, w, h in screen coords
    focused: bool = False
    alive: bool = True

    # screen-level
    screen_kind: str = "unknown"       # loading | lobby | game | results | error
    confidence: float = 0.0

    # game values
    money: float | None = None
    money_text: str = ""
    wave: int | None = None
    level: int | None = None

    # detected UI
    buttons: dict = field(default_factory=dict)   # name -> {x, y, score}
    panels: dict = field(default_factory=dict)

    # diagnostics
    last_error: str = ""
    detections_ok: int = 0
    detections_failed: int = 0
```

Rules:

- **Never** let two threads write to it. Build it in one place.
- Include a timestamp. Stale data must be detectable.
- Include confidence. "Found at 0.61" is different from "found at 0.97".
- Keep raw strings (OCR text) for debugging.

---

## 4. Threading model

The simplest model that works:

```
Thread 1: UI            (event loop; never blocks)
Thread 2: Perception    (capture + detect at N Hz; publishes WorldState)
Thread 3: Core          (state machine at M Hz; consumes WorldState, calls actions)
Thread 4: OCR worker    (optional; queue of crops -> text)
Thread 5: Watchdog      (optional; checks heartbeats, triggers recovery)
```

Why separate perception and core?

- Perception can be 10 Hz while the state machine runs at 30 Hz (cheap decisions).
- The core never waits on a capture.
- A slow OCR call goes to its own thread and the core uses the last known value.

### The "latest value" pattern

```python
import threading

class Latest:
    """A one-slot mailbox: writers overwrite, readers get the newest."""
    def __init__(self):
        self._lock = threading.Lock()
        self._value = None
        self._seq = 0

    def set(self, value):
        with self._lock:
            self._value = value
            self._seq += 1

    def get(self):
        with self._lock:
            return self._value, self._seq
```

This is better than a queue for perception. If perception runs faster than the core, a queue would build up stale frames. `Latest` always gives you the newest one.

### Timing

Don't use `time.sleep(1/60)` in a loop — it drifts. Use a deadline:

```python
import time

next_tick = time.perf_counter()
while running:
    now = time.perf_counter()
    if now < next_tick:
        time.sleep(next_tick - now)
        continue
    next_tick += 1.0 / 10.0          # 10 Hz
    if next_tick < now:              # we fell behind; don't spiral
        next_tick = now + 1.0 / 10.0
    tick()
```

---

## 5. The state machine

### 5.1 Structure

```python
class State:
    name = "base"
    timeout = 30.0

    def enter(self, ctx): ...
    def tick(self, ctx, world) -> str | None: ...   # return next state name
    def exit(self, ctx): ...


class Idle(State):
    name = "idle"
    timeout = 0

    def tick(self, ctx, world):
        if ctx.want_running and world.screen_kind == "lobby":
            return "lobby"


class Lobby(State):
    name = "lobby"
    timeout = 120

    def tick(self, ctx, world):
        if world.screen_kind == "game":
            return "game"
        if "play" in world.buttons:
            ctx.actions.click(world.buttons["play"])
            ctx.wait(1.0)
        return None


STATES = {s.name: s for s in [Idle(), Lobby(), ...]}
```

### 5.2 The driver

```python
def run_state_machine(ctx):
    state = STATES["idle"]
    state.enter(ctx)
    entered_at = time.time()

    while ctx.running:
        world, _ = ctx.world.get()

        if world is None:
            time.sleep(0.05)
            continue

        # global overrides
        if not world.alive:
            nxt = "recover"
        elif time.time() - entered_at > state.timeout > 0:
            ctx.log(f"{state.name} timed out")
            nxt = "recover"
        else:
            nxt = state.tick(ctx, world)

        if nxt and nxt != state.name:
            state.exit(ctx)
            state = STATES[nxt]
            state.enter(ctx)
            entered_at = time.time()
            ctx.log(f"state -> {state.name}")

        time.sleep(1 / 30)
```

### 5.3 Why states beat scripts

A linear script:

```python
click_play()
sleep(30)
place_tower(1)
sleep(20)
upgrade(1)
...
```

...breaks permanently if anything takes 1 second longer than expected.

A state machine re-checks reality every tick. If the loading screen took 45 seconds, the `Loading` state just waits. If a popup appeared, a global handler can dismiss it and return to the same state.

### 5.4 Global interrupt handlers

Run these before the state's own tick:

```python
def handle_interrupts(ctx, world):
    if world.buttons.get("disconnect_reconnect"):
        return "recover"
    if world.buttons.get("daily_reward"):
        ctx.actions.click(world.buttons["daily_reward"])
        return None
    if world.screen_kind == "error_dialog":
        ctx.actions.click(world.buttons.get("close_dialog"))
        return None
    return None
```

This is how mature macros handle "a random popup appeared" without special-casing it in every state.

---

## 6. Configuration

### 6.1 Format

JSON or TOML. JSON is easiest to serialise; TOML is nicer to hand-edit.

```json
{
  "schema_version": 3,
  "profile": "tds_farm",
  "window": {
    "require_size": [1920, 1080],
    "require_scale": 1.0,
    "auto_resize": true
  },
  "timing": {
    "perception_hz": 10,
    "ocr_hz": 1.5,
    "action_jitter": 0.35
  },
  "features": {
    "auto_rejoin": true,
    "anti_afk": true,
    "discord_webhook": false
  },
  "strategy": {
    "map": "Meadow",
    "difficulty": "Intermediate",
    "loadout": ["Soldier", "Farm", "Sniper"],
    "rotation_after_runs": 5
  }
}
```

### 6.2 Rules

- **Version the schema.** When you add a field, migrate old configs instead of crashing.
- **Validate on load.** Unknown keys → warn, don't explode. Missing keys → defaults.
- **Save atomically.** Write to `config.tmp`, then `os.replace()`.
- **Keep a backup.** `config.json.bak` before each save.
- **Separate user config from shipped defaults.** Never overwrite a user's file on update.

```python
def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
```

### 6.3 Profiles

Users want different setups per game/account. A profile is just a named config file.

```
config/
  app.json
  profiles/
    tds_main.json
    tds_alt.json
    bss_blue.json
```

---

## 7. Assets

```
assets/
  tds/
    play.png
    play.json          <- metadata: search box, threshold
    play_again.png
    play_again.json
    tower_soldier.png
  common/
    close_x.png
    yes.png
```

Two philosophies:

| Approach | Pros | Cons |
|---|---|---|
| **External PNGs + JSON** | Easy to edit, hot-reload, user can fix broken assets | Files can go missing; needs a folder |
| **Embedded base64 in code** | Single file, nothing to lose | Painful to edit, bloats source |

Natro embeds everything as base64 inside `.ahk` files. That's great for distribution (one folder, no missing assets) and bad for maintenance.

**Recommendation:** develop with external files, and optionally embed at build time.

```python
# build step: assets/*.png -> assets.py with base64 strings
def embed_assets():
    out = ["import base64", "ASSETS = {}"]
    for p in Path("assets").rglob("*.png"):
        key = str(p.relative_to("assets")).replace("\\", "/")
        b64 = base64.b64encode(p.read_bytes()).decode()
        out.append(f'ASSETS[{key!r}] = base64.b64decode({b64!r})')
    Path("embedded_assets.py").write_text("\n".join(out))
```

---

## 8. Logging

### 8.1 What to log

| Level | Examples |
|---|---|
| ERROR | "capture returned all-white frame", "OCR language pack missing" |
| WARN | "play button not found after 3 tries", "money read rejected (jump 12K -> 120M)" |
| INFO | state changes, run started/ended, rewards read |
| DEBUG | per-detection scores, capture timings, click coordinates |

### 8.2 Format

```
2026-10-21 03:14:07.221 INFO  state -> lobby
2026-10-21 03:14:07.450 DEBUG detect play: 0.94 at (960, 812)
2026-10-21 03:14:07.512 INFO  clicked play
2026-10-21 03:14:09.004 INFO  state -> loading
2026-10-21 03:14:31.882 WARN  loading timeout 22s, retrying
```

Include the detection score. When a user says "it doesn't click the button", the log tells you whether it didn't find it or found it at 0.55 and rejected it.

### 8.3 Log rotation

An 8-hour run at DEBUG can produce hundreds of MB. Rotate:

```python
import logging.handlers
handler = logging.handlers.RotatingFileHandler(
    "logs/macro.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
```

### 8.4 Crash dumps

On an unhandled exception, save:

- the last screenshot,
- the last 200 log lines,
- the world state as JSON,
- the config (with secrets redacted).

Zip it and let the user send it. This turns "it doesn't work" into a fixable bug report.

---

## 9. Recovery

Every long-running macro eventually hits:

| Failure | Detection | Recovery |
|---|---|---|
| Disconnected | "Reconnect" button, error text | Click reconnect, wait, rejoin |
| Kicked to lobby | Screen changed to lobby | Re-enter game |
| Wrong map | Map name mismatch | Leave, rejoin, retry |
| Stuck in a menu | Same screen for N seconds | Press Esc, close dialogs |
| Dead character | Respawn button | Click respawn |
| Game updated (UI moved) | Detection below threshold | Stop and alert |
| Roblox crashed | Window handle gone | Restart Roblox, rejoin |
| OCR broken | Repeated `None` reads | Fall back to last value, warn |
| PC lag | Actions take too long | Increase delays, reduce rate |

Implement recovery as a **state**, not as scattered `try/except`:

```python
class Recover(State):
    name = "recover"
    timeout = 180

    def enter(self, ctx):
        ctx.attempts += 1
        if ctx.attempts > 5:
            ctx.stop("too many recovery attempts")

    def tick(self, ctx, world):
        if world.screen_kind == "lobby":
            ctx.attempts = 0
            return "lobby"
        if world.buttons.get("reconnect"):
            ctx.actions.click(world.buttons["reconnect"])
            ctx.wait(5)
        elif not world.alive:
            ctx.restart_game()
            ctx.wait(30)
        elif world.buttons.get("close_dialog"):
            ctx.actions.click(world.buttons["close_dialog"])
        return None
```

### Watchdog

A separate thread that checks "has the core ticked recently?":

```python
def watchdog(ctx, timeout=15):
    while ctx.running:
        time.sleep(1)
        if time.time() - ctx.last_tick > timeout:
            ctx.log("watchdog: core stalled", level="ERROR")
            ctx.request_stop()
```

This catches deadlocks, infinite loops, and blocked I/O.

---

## 10. Hotkeys

Global hotkeys must work even when the game has focus.

| Key | Action |
|---|---|
| F1 | Start |
| F2 | Pause / resume |
| F3 | Stop |
| F4 | Toggle debug overlay |
| F5 | Save a debug screenshot |
| F8 | **Emergency stop** |

Implementation:

- AHK: `Hotkey` / `#HotIf`.
- Python: `keyboard` library (global hook) or `RegisterHotKey` via Win32.
- C#: `RegisterHotKey` or a low-level keyboard hook.

**Emergency stop must not depend on the main loop.** Set a flag from the hook and also `TerminateProcess` after a grace period if the loop doesn't exit.

---

## 11. UI ↔ core communication

Keep it simple: a command queue in one direction, an event queue in the other.

```python
class Bus:
    def __init__(self):
        self.commands = queue.Queue()
        self.events = queue.Queue()

    def send(self, cmd, **kw):        # UI -> core
        self.commands.put((cmd, kw))

    def emit(self, event, **kw):      # core -> UI
        self.events.put((event, kw))
```

Commands: `start`, `stop`, `pause`, `reload_config`, `capture_debug`, `set_profile`.
Events: `state_changed`, `log`, `stat`, `detection`, `run_finished`, `error`.

This makes it trivial to swap the UI later (console → Tkinter → Qt → web) without touching the core.

---

## 12. Project layout

A layout that stays manageable at ~5–15k lines:

```
tds-macro/
  main.py                 # entry point, arg parsing
  app/
    __init__.py
    bus.py                # command/event queues
    config.py             # load/save/migrate/validate
    logging_setup.py
    state.py              # WorldState
    states/
      __init__.py
      idle.py
      lobby.py
      loading.py
      game.py
      results.py
      recover.py
    core.py               # state machine driver
  perception/
    __init__.py
    capture.py            # Win32 / mss / dxcam / WGC
    window.py             # hwnd, client rect, dpi, focus
    detect.py             # template, colour, signature
    ocr.py                # windows OCR / tesseract
    numbers.py            # parse + validate
    world.py              # build WorldState from raw frame
  actions/
    __init__.py
    mouse.py
    keyboard.py
    humanize.py
    strategy.py            # recorded / declarative strategies
  ui/
    __init__.py
    main_window.py
    overlay.py
    widgets.py
  assets/
    ...
  config/
    app.json
    profiles/
  logs/
  tools/
    capture_debug.py       # save screenshots, test capture
    template_tool.py       # crop a template + write metadata
    ocr_tuner.py           # test preprocessing on saved crops
  tests/
    test_numbers.py
    test_states.py
    test_scaling.py
```

**Tools matter.** A `template_tool.py` that lets you drag a box, save the PNG, and generate the JSON metadata will save you hundreds of hours.

---

## 13. A minimal but complete skeleton

```python
# main.py
import threading, time
from app.bus import Bus
from app.config import load_config
from app.state import WorldState
from perception.window import find_window, get_client_box
from perception.capture import Capture
from perception.world import build_world
from actions.mouse import Mouse
from app.core import run_state_machine


def perception_loop(ctx, hz=10):
    cap = Capture()
    period = 1 / hz
    next_t = time.perf_counter()

    while ctx.running:
        now = time.perf_counter()
        if now < next_t:
            time.sleep(min(next_t - now, 0.01))
            continue
        next_t += period
        if next_t < now:
            next_t = now + period

        hwnd = find_window()
        if not hwnd:
            ctx.world.set(WorldState(alive=False))
            continue

        box = get_client_box(hwnd)
        frame = cap.grab(*box)
        world = build_world(frame, box, hwnd, ctx)
        ctx.world.set(world)


def main():
    cfg = load_config()
    ctx = Context(cfg)
    ctx.world = Latest()
    ctx.actions = Mouse(cfg)

    threads = [
        threading.Thread(target=perception_loop, args=(ctx,), daemon=True),
        threading.Thread(target=run_state_machine, args=(ctx,), daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        while ctx.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        ctx.request_stop()

    for t in threads:
        t.join(timeout=2)
```

That's the whole idea in ~40 lines. Everything else is filling in the parts.

---

## 14. Lightweight structure rules

1. **No database.** JSON files are enough for config, strategies, and stats.
2. **No web server** unless you need a remote dashboard.
3. **No ORM, no DI framework, no plugin system** in v1.
4. **One process** unless you need a separate vision service (Python + a native UI, for example).
5. **Embed assets at build time** if distribution simplicity matters.
6. **Use the OS's own OCR** (Windows.Media.Ocr) before shipping 100 MB of models.
7. **Prefer a single-file executable** (PyInstaller `--onefile`, .NET single-file publish, AHK compiled).
8. **Keep the UI dumb.** It draws state and sends commands; it never captures or clicks.

Natro's structure is a good example of "lightweight but split": a `START.bat`, a main AHK script, and a separate `background.ahk` process for continuous monitoring, talking over a custom window message (`0x5552`). Two processes, no server, no database.

---

## 15. Architecture checklist

- [ ] Perception, decision, and action are separate modules.
- [ ] The core state machine can be unit-tested with fake world states.
- [ ] UI never blocks on capture or OCR.
- [ ] OCR runs on its own worker with a latest-value mailbox.
- [ ] Every state has a timeout.
- [ ] A global recovery state handles disconnects, popups, and stuck screens.
- [ ] A watchdog detects a stalled core.
- [ ] Config is versioned, validated, saved atomically, and backed up.
- [ ] Logs include detection scores and raw OCR text.
- [ ] Crash dumps include a screenshot + world state + log tail.
- [ ] Emergency stop works independently of the main loop.
- [ ] No unbounded queues, lists, or log files.

---

## Sources

- Natro Macro structure (`START.bat`, `submacros/natro_macro.ahk`, `background.ahk`, custom `0x5552` message): <https://github.com/NatroTeam/NatroMacro>
- Natro `background.ahk`: <https://github.com/NatroTeam/NatroMacro/blob/main/submacros/background.ahk>
- Game macro development manual — layered architecture (UI / core services / engine / storage / runtime / native): <https://bruceli0305.github.io/game-macro/>
- Macro recorder architecture with Electron + native input: <https://github.com/DefinitelyN0tMe/Macronyx>
- ARK Nexus X — macro engine + vision sidecar architecture: <https://github.com/Nortaq-PlayNexus/ArkNexusX>
- Ultimate Macro strategy rotation / recovery behaviour: <https://ultmacro.xyz/guide/>

---

*Next: [08-ui-design-revolution.md](08-ui-design-revolution.md)*
