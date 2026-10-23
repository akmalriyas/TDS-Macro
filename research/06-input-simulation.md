# 06 — Input Simulation (Clicking and Typing)

> **If you only remember one thing:** Roblox ignores "fake" clicks sent directly to its window. You must move the *real* cursor and send *real* OS-level input, and you must give the game time to notice.

---

## 1. The input API ladder

From least to most "real":

| Method | What it does | Roblox? |
|---|---|---|
| `PostMessage(hwnd, WM_LBUTTONDOWN, ...)` | Drops a message in the window's queue | ❌ ignored |
| `ControlClick` / `ControlSend` (AHK) | Sends a message to a control | ❌ ignored |
| `SendMessage` | Same, synchronously | ❌ ignored |
| `mouse_event` / `keybd_event` | Legacy OS-level input injection | ✅ usually |
| `SendInput` | Modern OS-level input injection | ✅ usually |
| Physical HID device (Arduino, KMBox) | Looks like real hardware | ✅ always |

Roblox uses **raw input / DirectInput** for mouse look and much of its input handling. It does not process synthetic window messages, which is why every "ControlClick doesn't work in Roblox" thread ends with "use Click instead".

**Use `SendInput` (or `mouse_event` as a fallback).** Reserve hardware devices for cases where software input is blocked, and understand that's a much bigger ethical/ToS step.

---

## 2. The Roblox cursor quirk

A very specific and very common bug: you call `SetCursorPos(x, y)`, then click, and **nothing happens**. The game didn't register the click because it never saw the cursor *move*.

The fix, discovered independently by many people:

```ahk
MouseMove targetX, targetY
MouseMove 0, -1, , "R"     ; move 1px relative — forces a movement event
Click
```

Or in Python:

```python
import ctypes, time
user32 = ctypes.windll.user32

def move_and_click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.03)
    # tiny relative nudge so the game sees a real move
    user32.mouse_event(0x0001, 1, 0, 0, 0)   # MOUSEEVENTF_MOVE relative
    time.sleep(0.02)
    user32.SetCursorPos(x, y)
    time.sleep(0.02)
    user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.04)
    user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
```

### Why it happens

- The game tracks the cursor from raw input deltas, not from the absolute position.
- If the cursor was already at that position (or was warped there without a delta), there's no movement event, so the game thinks the mouse isn't over the button.
- Moving the physical mouse by 1px makes the game notice.

Other fixes that sometimes help:

- Move in **two steps** with a small delay between them.
- Use `SendInput` with `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE`.
- Move to a point slightly offset from the target, then to the target.
- Ensure the window is actually foreground.

---

## 3. Keyboard input

### 3.1 Key presses need to be held

Games using DirectInput poll the keyboard every ~10–15 ms (or once per frame). A key that is pressed and released within 2 ms can fall entirely between two polls and be missed.

```python
def press_key(vk, hold_ms=40):
    user32.keybd_event(vk, 0, 0, 0)              # key down
    time.sleep(hold_ms / 1000)
    user32.keybd_event(vk, 0, 0x0002, 0)         # key up
```

In AHK:

```ahk
Send "{w down}"
Sleep 40
Send "{w up}"
```

`SetKeyDelay 20, 10` also helps if you use `Send`.

### 3.2 `SendInput` vs `Send`

- `SendInput` is atomic and very fast — sometimes **too** fast for games.
- AHK's `Send` with `SetKeyDelay` inserts delays and is more reliable in games.
- Don't mix `SendInput` and `SetKeyDelay` and expect the delay to apply; `SendInput` ignores it.

### 3.3 Scan codes vs virtual keys

Some games read **scan codes** (physical key positions), not virtual key codes. That's why a script sometimes works for `W` but not `Z` on a non-US keyboard.

AHK's `Send` handles scan codes by default (`SendMode Input` uses `SendInput` with scan codes). If you're writing raw Win32 code, use `MapVirtualKey(vk, MAPVK_VK_TO_VSC)` and send `KEYEVENTF_SCANCODE`.

Better still: **make your keybinds keyboard-layout independent** by using keys that exist in the same place on every layout (letters), and document that the user should use a US layout if things misbehave.

### 3.4 IME and language

If the user has a CJK IME active, key presses can be swallowed by the IME. Ask for English (US) input, or send scan codes.

---

## 4. Focus, admin rights, and "it works in Notepad but not Roblox"

| Symptom | Cause | Fix |
|---|---|---|
| Keys work in Notepad, not the game | Game uses raw input / DirectInput | Use `SendInput`/`Send` with holds |
| Clicks work sometimes | Cursor movement not registered | Nudge trick (§2) |
| Nothing works when the game is focused | Your app isn't elevated, game is | Run both as admin |
| Works until you click elsewhere | Game lost focus | Re-focus before every action |
| Works for 5 minutes then stops | Game re-hooked input, or AHK hook lost | Re-install hook / re-focus |
| Only first keypress registers | Key state stuck / game ignores repeats | Always send explicit down+up |

### Admin privileges

If Roblox runs as administrator (some launchers do), a non-elevated macro cannot send input to it because of UIPI (User Interface Privilege Isolation). Either:

- run the macro as admin, or
- don't, and tell the user to run both at the same level.

Never silently request elevation without explaining why.

### Multi-instance

Roblox allows multiple clients on one PC in some configurations. If you support that:

- Each instance is a separate `RobloxPlayerBeta.exe` with its own HWND.
- Only the **foreground** one receives input.
- You must focus, act, then move to the next, which is slow and fragile.
- Ultimate Macro explicitly refuses to start while Roblox Account Manager or similar is running, because multi-instance changes window behaviour.

For v1, support one instance.

---

## 5. Humanisation

"Humanisation" means making the input statistically similar to a person's, instead of perfectly linear and perfectly timed.

### What actually matters (and what doesn't)

For a Roblox farm macro, the realistic risks are:

1. **Server-side statistics** — 24/7 uptime, identical run duration, impossibly consistent APM.
2. **Player reports** — someone sees you doing the same loop for 6 hours.
3. **Obvious visual tells** — teleporting cursor, instant 180° snaps.

Not realistic for external macros: a kernel anti-cheat analysing your mouse curve. Roblox's Hyperion targets injection into the client, not other desktop apps.

So humanisation should focus on **plausible behaviour**, not on defeating a mouse-biometrics classifier.

### 5.1 Timing jitter

```python
import random, time

def human_delay(base=0.12, spread=0.35):
    """Sleep base seconds, jittered by +/- spread."""
    time.sleep(base * random.uniform(1 - spread, 1 + spread))
```

Guidelines:

- Base delays: 80–250 ms for UI clicks, 300–800 ms between distinct actions.
- Jitter: ±25–40%.
- Occasional longer pause: 2–5 s every 20–60 actions (like a person alt-tabbing or thinking).
- **Never** jitter a timing-critical wait (e.g. "click before the menu closes") — use a fixed safe margin there.

### 5.2 Mouse paths

Instead of teleporting:

```python
import math, random, time

def bezier_path(x0, y0, x1, y1, steps=25):
    # control points offset perpendicular to the line
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy) or 1
    nx, ny = -dy / dist, dx / dist

    bend1 = random.uniform(-0.15, 0.15) * dist
    bend2 = random.uniform(-0.15, 0.15) * dist

    cx1 = x0 + dx * 0.33 + nx * bend1
    cy1 = y0 + dy * 0.33 + ny * bend1
    cx2 = x0 + dx * 0.66 + nx * bend2
    cy2 = y0 + dy * 0.66 + ny * bend2

    pts = []
    for i in range(steps):
        t = i / (steps - 1)
        # ease-in-out
        t = t * t * (3 - 2 * t)
        u = 1 - t
        x = u**3 * x0 + 3 * u**2 * t * cx1 + 3 * u * t**2 * cx2 + t**3 * x1
        y = u**3 * y0 + 3 * u**2 * t * cy1 + 3 * u * t**2 * cy2 + t**3 * y1
        pts.append((int(x), int(y)))
    return pts

def human_move(x1, y1, duration=0.25):
    x0, y0 = get_cursor_pos()
    pts = bezier_path(x0, y0, x1, y1)
    delay = duration / len(pts)
    for x, y in pts:
        user32.SetCursorPos(x, y)
        time.sleep(delay * random.uniform(0.7, 1.3))
```

For game UI clicks, a 150–300 ms move is plenty. For repeated clicks on the same button, don't re-run the full path — just small jitter around the target.

### 5.3 Click timing

Humans don't press and release in 2 ms:

```python
def human_click(x, y):
    human_move(x, y, duration=random.uniform(0.15, 0.30))
    time.sleep(random.uniform(0.05, 0.15))     # settle
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(random.uniform(0.06, 0.14))     # hold
    user32.mouse_event(0x0004, 0, 0, 0, 0)
```

### 5.4 What *not* to do

- Don't add so much jitter that your macro misses time windows.
- Don't randomise the *order* of actions unless the game allows it.
- Don't simulate "human error" (misclicks) unless you're deliberately trying to look human — it just wastes time and can break strategies.
- Don't use "undetectable" claims from libraries designed for browser bot detection; they solve a different problem.

---

## 6. Camera control (the hard part)

In 3D Roblox games, placing a tower or walking to a spot requires a specific camera angle. There are two approaches:

### 6.1 Fixed camera, reset every time

1. Press the key that resets the camera (often `Shift` lock or a game-specific bind).
2. Move the mouse to a known position without holding any button (this rotates the camera only if the game uses "mouse look").
3. Or hold right mouse button and move by a **known delta**, then release.

```python
def rotate_camera(dx, dy, steps=10):
    user32.mouse_event(0x0008, 0, 0, 0, 0)     # RIGHTDOWN
    for _ in range(steps):
        user32.mouse_event(0x0001, dx // steps, dy // steps, 0, 0)
        time.sleep(0.01)
    user32.mouse_event(0x0010, 0, 0, 0, 0)     # RIGHTUP
```

**Important:** `dx`/`dy` here are *mouse deltas*, not screen coordinates. The game translates them into rotation. This is why camera control is resolution-independent but **sensitivity-dependent** — the user's in-game sensitivity changes how many degrees a given delta produces.

TDS macros handle this by requiring a specific camera mode and, in some cases, a specific sensitivity, then calibrating: rotate a known amount, take a screenshot, see how far the view moved.

### 6.2 Closed-loop aiming

For real precision (e.g. aiming at a specific world object), you can't trust dead reckoning. You need feedback:

```
rotate a bit -> capture -> detect target -> compute error -> rotate more
```

That's a control loop. It's slower but robust to sensitivity, FOV, and lag.

Most farm macros avoid this entirely by using **fixed, pre-recorded camera states** and re-recording the strategy if the game changes. That's the pragmatic choice.

### 6.3 Mouse lock

If the game is in first-person / shift-lock, the cursor is hidden and moving the mouse rotates the camera. You cannot click UI elements in this state without unlocking.

Rules:

- Detect the state (cursor visible? crosshair? mouse icon?).
- Unlock (usually `Esc`, `Shift`, or a game menu key) before clicking UI.
- Re-lock after.

Many macros simply require "camera mode: Classic" (third-person, cursor free) so they never have to deal with this. Revolution requires exactly that.

---

## 7. Anti-AFK

Roblox kicks you after ~20 minutes of no input. Farm macros need a heartbeat:

```python
def anti_afk():
    # rotate the camera slightly, or jump, in a way that doesn't disturb the task
    press_key(VK_SPACE, hold_ms=40)
    human_delay(300)
```

Guidelines:

- Every 5–10 minutes, not every 10 seconds (the latter looks robotic and can interfere with gameplay).
- Use an action that's harmless in context: jump, tiny camera wiggle, open/close a menu.
- Don't send random WASD if the character is standing on a platform — you'll walk off.
- Some games have their own AFK detection; check whether moving is enough.

Revolution, Natro, and most BSS/TDS macros all have an anti-AFK feature. It's table stakes for overnight runs.

---

## 8. Reliability patterns

### 8.1 Retry with backoff

```python
def click_until(target_detector, click_fn, tries=4, wait=0.4):
    for i in range(tries):
        click_fn()
        t0 = time.time()
        while time.time() - t0 < wait:
            if target_detector():
                return True
            time.sleep(0.05)
    return False
```

### 8.2 Never trust one click

Menus animate. A click during the open animation can be swallowed. Detect the menu fully open (stable for 2 frames) before clicking inside it.

### 8.3 Keep the cursor where you left it

If your macro moves the mouse away and the user is watching, it's jarring. Options:

- Move back to a "parking" position after each action.
- Hide the cursor (bad — the game may need it).
- Accept it and document it.

Some macros park the cursor in a corner of the game window between actions.

### 8.4 Don't fight the user

If the user moves the mouse while the macro is running, you have a conflict. Options:

- Detect user movement (`GetCursorPos` differs from expected) and pause.
- Use `BlockInput` (dangerous — can lock the user out if the app crashes).
- Just document "don't touch the mouse".

A **panic hotkey** is mandatory:

```python
import keyboard
keyboard.add_hotkey("f8", lambda: setattr(state, "running", False))
```

Or in AHK:

```ahk
F8::ExitApp
```

Make it work even if the main loop is stuck — i.e. handle it in a separate thread or a global hook.

### 8.5 Failsafe

`pyautogui` has a built-in failsafe: slam the mouse into a screen corner to abort.

```python
import pyautogui
pyautogui.FAILSAFE = True
```

Worth enabling during development. In production, your own hotkey is better.

---

## 9. Input checklist

- [ ] Using `SendInput` / `mouse_event`, not `PostMessage` / `ControlClick`.
- [ ] Cursor is physically moved to the target before clicking.
- [ ] A 1px nudge (or two-step move) is used so Roblox registers the move.
- [ ] Window is focused before every action (or verified still focused).
- [ ] Keys are held for at least 20–50 ms.
- [ ] Delays have ±25–40% jitter, plus occasional longer pauses.
- [ ] Mouse moves use a curved path, not a teleport.
- [ ] Camera movement uses mouse deltas *and* accounts for in-game sensitivity.
- [ ] Mouse-lock state is detected before clicking UI.
- [ ] Anti-AFK heartbeat every 5–10 minutes.
- [ ] Panic hotkey works even if the main loop hangs.
- [ ] Every action is followed by a verification step.

---

## Sources

- ControlClick doesn't work in Roblox: <https://www.autohotkey.com/boards/viewtopic.php?t=118691>
- Roblox click not registering; 1px `MouseMove 0,-1,, "R"` fix: <https://www.autohotkey.com/boards/viewtopic.php?t=135036>
- Stack Overflow: cannot send clicks to inactive Roblox window: <https://stackoverflow.com/questions/52081351/autohotkey-cannot-send-mouse-click-event-to-inactive-roblox-window>
- AHK guide to making scripts work with games (DirectInput polling, key holds, admin): <https://www.autohotkey.com/boards/viewtopic.php?t=130388>
- Python SendInput mouse struct example: <https://stackoverflow.com/questions/69951287/cant-move-mouse-on-roblox>
- Roblox raw input discussion (GetRawInputData / WM_INPUT): <https://gist.github.com/dendenxu/557dea81ec0f903bf90eee76fe4efcc4>
- Human mouse motion model (minimum-jerk, Fitts's law, submovements): <https://pydoll.tech/docs/deep-dive/fingerprinting/behavioral-fingerprinting/>
- Bezier mouse path implementation: <https://docs.rs/stealthscraper-rs/latest/src/stealthscraper_rs/behavior.rs.html>
- Revolution camera/movement requirements: <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>

---

*Next: [07-macro-architecture.md](07-macro-architecture.md)*
