# 05 — Window, Screen, and Scaling

> **If you only remember one thing:** never store a screen coordinate. Store a coordinate *relative to the game's client area*, then scale it by the client size at runtime. Everything else in this doc is edge cases around that rule.

---

## 1. Three coordinate systems

Windows has three nested spaces. Mixing them up is the most common source of "it clicks 200px off".

```
SCREEN coordinates (virtual desktop)
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   WINDOW coordinates (includes title bar + borders)     │
│   ┌───────────────────────────────────────────────┐     │
│   │  title bar                                    │     │
│   │  ┌─────────────────────────────────────────┐  │     │
│   │  │  CLIENT coordinates (the game canvas)   │  │     │
│   │  │                                         │  │     │
│   │  │   (0,0) is here                         │  │     │
│   │  │                                         │  │     │
│   │  └─────────────────────────────────────────┘  │     │
│   └───────────────────────────────────────────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

| Space | Origin | Use for |
|---|---|---|
| **Screen** | Top-left of the virtual desktop (can be negative on multi-monitor) | `SetCursorPos`, overlays, debug drawing |
| **Window** | Top-left of the window frame (title bar) | Rarely useful |
| **Client** | Top-left of the drawable area | **All game detection and clicking** |

**Rule:** detect in client coordinates, click in client coordinates, and convert to screen only at the very last moment.

---

## 2. Getting the client rectangle

```python
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

def get_client_box(hwnd):
    """Return (screen_x, screen_y, width, height) of the client area."""
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None

    # client (0,0) -> screen
    pt = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None

    return pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top
```

```ahk
WinGetClientPos &x, &y, &w, &h, "ahk_id " hwnd
```

**Do not use `GetWindowRect`** for detection. It includes the title bar and borders. On Windows 10/11 with DWM, it can also include invisible resize borders that are ~7–8 px on each side, making your offsets subtly wrong.

If you *must* use `GetWindowRect` (e.g. for positioning the window), use `DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ...)` to get the visible frame instead.

---

## 3. DPI: the whole story in one section

### 3.1 What DPI scaling does

At 100% scaling, 1 logical pixel = 1 physical pixel.
At 150% scaling, 1 logical pixel = 1.5 physical pixels.

Windows reports different numbers depending on whether your process is **DPI aware**:

| Your process | `GetClientRect` returns | `BitBlt` captures | `SetCursorPos` expects |
|---|---|---|---|
| DPI unaware | logical (e.g. 1280×720) | physical (1920×1080) | logical |
| System DPI aware | physical-ish for primary | physical | physical |
| Per-monitor aware v2 | physical | physical | physical |

If you're unaware, your capture is 1920 wide but your click coordinates are computed against 1280. At x=1200 you click at physical 1800. Everything is off by 1.5×, growing towards the bottom-right.

### 3.2 Fix it once, at startup

```python
import ctypes
# per-monitor v2 (Windows 10 1703+)
try:
    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()
```

```ahk
; AHK v2
DllCall("SetThreadDpiAwarenessContext", "ptr", -3, "ptr")
```

```csharp
// C# — app manifest is better, but this works at runtime
[DllImport("user32.dll")] static extern bool SetProcessDPIAware();
SetProcessDPIAware();
```

Best practice for a shipped app: declare DPI awareness in the **application manifest** so it's set before any window is created.

### 3.3 Getting the actual scale factor

```python
def get_scale(hwnd):
    # Windows 10 1607+
    dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
    return dpi / 96.0
```

```ahk
dpi := DllCall("GetDpiForWindow", "ptr", hwnd, "uint")
scale := dpi / 96
```

### 3.4 Why so many macros just require 100%

Because supporting 125%/150%/175% means:

- every captured pixel might be a blend of 1.5 physical pixels (blurry text),
- template matching scores drop,
- OCR accuracy drops,
- coordinates need rounding in two directions,
- multi-monitor mixed-DPI breaks assumptions.

Revolution sidesteps all of it:

> Scale: 100%. Scaled displays break detection offsets and can block startup with `Your monitor scale must be set to 100% in order for the macro to start.`

Ultimate Macro (TDS) says the same: "Windows display scale 100% ... recommended baseline for predictable OCR and UI geometry."

**If you support scaling**, you must test at 100/125/150/175/200%. If you don't, detect it and refuse to start with a clear message. Both are valid. Silently mis-clicking is not.

---

## 4. The scaling formula

### 4.1 Reference resolution

Pick one design resolution. Everything is authored against it.

```
REFERENCE = 1920 x 1080
```

Then at runtime:

```python
sx = client_w / 1920
sy = client_h / 1080

def to_screen(x_ref, y_ref):
    return int(round(x_ref * sx)), int(round(y_ref * sy))

def box_from_ref(x, y, w, h):
    return (int(x * sx), int(y * sy), int(w * sx), int(h * sy))
```

### 4.2 Uniform vs non-uniform

- **Uniform scale** (`s = min(sx, sy)`) keeps circles circular and squares square. Use this for **template sizes** and anything shape-sensitive.
- **Non-uniform scale** (`sx`, `sy` separately) fills the window exactly. Use this for **positions and rectangles** when the aspect ratio is guaranteed 16:9.

If aspect ratio is not guaranteed, you need letterboxing:

```python
def letterbox(client_w, client_h, ref_w=1920, ref_h=1080):
    scale = min(client_w / ref_w, client_h / ref_h)
    draw_w = int(ref_w * scale)
    draw_h = int(ref_h * scale)
    off_x = (client_w - draw_w) // 2
    off_y = (client_h - draw_h) // 2
    return scale, off_x, off_y
```

Then a reference point maps to:

```python
def map_point(x_ref, y_ref, client_w, client_h):
    scale, ox, oy = letterbox(client_w, client_h)
    return int(ox + x_ref * scale), int(oy + y_ref * scale)
```

But note: **Roblox does not letterbox its UI.** If the window is 21:9, the game renders a wider view and UI elements anchored to the right edge move further right. So letterboxing assumptions only work if you enforce 16:9.

### 4.3 Enforce a sane window

The simplest robust strategy:

1. Ask the user to set Roblox to a specific size (e.g. 1920×1080 borderless).
2. If the client area isn't that size, **resize the window yourself** with `SetWindowPos`.
3. If that fails (fullscreen, locked), refuse to start.

```python
def ensure_size(hwnd, target_w=1920, target_h=1080):
    x, y, w, h = get_client_box(hwnd)
    if (w, h) == (target_w, target_h):
        return True
    # account for non-client area
    whole = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(whole))
    frame_w = (whole.right - whole.left) - w
    frame_h = (whole.bottom - whole.top) - h
    user32.SetWindowPos(hwnd, 0, whole.left, whole.top,
                        target_w + frame_w, target_h + frame_h,
                        0x0004 | 0x0010)   # SWP_NOZORDER | SWP_NOACTIVATE
    return True
```

Many macros do exactly this — or they simply document "run at 1920×1080 windowed" and check it at startup.

---

## 5. Why Roblox UI does *not* scale evenly

This trips people up constantly. Roblox has two kinds of UI:

1. **CoreGui** (the Roblox top bar, chat button, menu, backpack): mostly uses **offset** sizes — fixed pixel sizes regardless of resolution. The top bar is ~36 px tall on every screen.
2. **Game UI** (money, health, wave counter, shop): usually uses **scale** (UDim2 scale values), so it grows and shrinks with the viewport.

Consequences:

- Your money label does **not** sit at `x = 0.76 * width` at every resolution, because the game may anchor it with an offset, or with a mix of scale + offset.
- At 1280×720 the top bar is still 36 px, so it takes a bigger fraction of the screen.
- At 21:9 the right-anchored elements move further right than a simple `w/1920` scale predicts.

### What to do about it

| Approach | Effort | Robustness |
|---|---|---|
| Force 1920×1080 window | low | ★★★★★ for that one size |
| Scale all coords by `w/1920` | low | ★★★ good on 16:9, wrong on ultrawide |
| Anchor to a detected UI element | medium | ★★★★ good if the anchor is stable |
| Detect every element independently (no coordinates at all) | high | ★★★★★ best, slowest |

The progression is real: simple macros scale coordinates; mature macros **find elements** and never trust a coordinate they didn't detect.

---

## 6. Multi-monitor

Problems:

- Screen coordinates can be negative (monitor to the left of primary).
- Different monitors can have different DPI.
- A window can straddle two monitors.
- `A_ScreenWidth` only reports the primary monitor in AHK.

Rules:

1. Always use the window's client origin (`ClientToScreen`), never `(0,0)`.
2. Capture from the window, not the desktop.
3. If you use `SetCursorPos`, coordinates are in the virtual desktop space and can be negative — that's fine.
4. If you use `SendInput` with `MOUSEEVENTF_ABSOLUTE`, the coordinates are **normalised 0–65535 across the virtual desktop**, which is a common bug source:

```python
# Convert screen pixels -> SendInput absolute units
def to_absolute(x, y, vx, vy, vw, vh):
    ax = int((x - vx) * 65535 / (vw - 1))
    ay = int((y - vy) * 65535 / (vh - 1))
    return ax, ay
```

where `vx, vy, vw, vh` come from `GetSystemMetrics(SM_XVIRTUALSCREEN)` etc.

5. Test with the game on a secondary monitor at a different scale. If you don't support it, say so.

---

## 7. Fullscreen, borderless, and window focus

| Mode | Capture | Input | Overlay | Recommendation |
|---|---|---|---|---|
| Exclusive fullscreen | Often black | Works | Hidden | ❌ avoid |
| Borderless windowed | Works | Works | Visible | ✅ best |
| Windowed | Works | Works | Visible | ✅ good |
| Minimised | Fails | Fails | n/a | ❌ |

Roblox calls it "Fullscreen" vs "Windowed". There's no true exclusive fullscreen on Roblox in the same way as native games, but the "Fullscreen" mode can still cause capture issues. Borderless windowed (a window sized to the monitor with no border) is the safe choice.

### Focus

Most input methods require the game window to be **foreground**:

```python
def focus(hwnd):
    if user32.GetForegroundWindow() == hwnd:
        return True
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd
```

Windows blocks `SetForegroundWindow` from background processes in some cases. Workarounds:

- `AttachThreadInput` to the foreground thread, then `SetForegroundWindow`, then detach.
- Send an `ALT` key tap first (a well-known trick).
- Ask the user to click the game.

Some macros avoid this entirely by requiring the user to keep the game focused and only running one instance.

### Window position drift

If your macro moves the mouse to click something, and the user bumps the window, your cached client rect is stale. Re-read it every tick (it's cheap) or listen for `WM_MOVE` / `WM_SIZE`.

```python
# Cheap enough to do every loop
x, y, w, h = get_client_box(hwnd)
if (x, y, w, h) != last_box:
    invalidate_cached_regions()
    last_box = (x, y, w, h)
```

---

## 8. Mapping a click from detection to the mouse

Detection returns client-relative coordinates. The mouse needs screen coordinates.

```python
def click_client(hwnd, cx, cy):
    sx, sy, w, h = get_client_box(hwnd)
    screen_x = sx + cx
    screen_y = sy + cy
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.02)
    user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
```

With `SendInput` it's the same idea but the struct is more verbose. With AHK:

```ahk
Click(cx + clientX, cy + clientY)
```

The important part is: **add the client origin at the last moment**, and re-read the origin every time in case the window moved.

---

## 9. Overlays and debug drawing

If you draw a transparent overlay on top of the game, its coordinates are screen coordinates. Convert from client:

```python
screen_x = client_x + box_x
screen_y = client_y + box_y
```

Also:

- The overlay must be `WS_EX_LAYERED | WS_EX_TRANSPARENT` so clicks pass through.
- It must be `WS_EX_TOPMOST` to stay above the game.
- It must **not** be captured by your own screenshot (otherwise you detect your own boxes). Either capture the game window directly (not the desktop), or draw the overlay only every N frames, or use a separate monitor.
- It will not show over exclusive fullscreen.

Revolution's overlay is a great reference: bounding boxes over tokens and sprinklers, toggled by a setting, used as the primary "is detection working?" diagnostic.

---

## 10. Case study: Revolution's environment rules

Revolution's troubleshooting page is effectively a specification for "what can break coordinate assumptions". Worth reading as a checklist:

| Requirement | Why it matters |
|---|---|
| Min 1366×768, 1920×1080 recommended | Below that, UI elements overlap and detection models can't resolve them |
| Horizontal widescreen only | Portrait/vertical layouts move everything |
| Windows scale 100% | Offsets break otherwise |
| HDR off (incl. Auto-HDR) | Colours shift |
| Text size 100% | Text metrics change |
| No high-contrast themes | Colours change |
| Roblox camera mode Classic/Default | Camera-relative movement assumes it |
| Movement mode Default (Keyboard) | Same |
| Performance Stats and MicroProfiler off | They cover the HUD |
| Fullscreen off | Capture issues |
| English (USA) experience language | OCR / text matching |
| Roblox text scale and background transparency 0 | Layout changes |
| No custom fonts | OCR breaks (also called out by TDS macros) |

Ultimate Macro adds:

| Requirement | Why |
|---|---|
| Visible Windows taskbar | The macro uses it as a layout reference |
| TDS UI Scale: Large | Reference images captured at that scale |
| TDS screen shake off | Moves the UI mid-frame |
| TDS "Prefer Vertical Upgrades" on | Fixes the upgrade panel layout |
| TDS dialogs off | Dialogs cover the HUD |
| Max frame rate 60 | Keeps animation timing predictable |
| Graphics mode Manual | Automatic changes quality mid-session |
| English (US) OCR pack | Required for wave/currency reading |

That last group is interesting: the macro doesn't just tolerate the game's settings, it **requires specific in-game settings** so the UI is deterministic. That's a legitimate and very effective strategy. Document it, check it at startup, and offer an "Auto Configure Settings" button that applies them and restores them afterwards (Ultimate Macro does exactly this).

---

## 11. Testing across resolutions

You can't test every monitor, but you can test the important ones:

| Resolution | Aspect | Why |
|---|---|---|
| 1280×720 | 16:9 | Minimum supported |
| 1366×768 | 16:9 | Common laptop |
| 1600×900 | 16:9 | Scaled laptop |
| 1920×1080 | 16:9 | Reference |
| 2560×1440 | 16:9 | Common desktop |
| 3840×2160 | 16:9 | 4K |
| 2560×1080 | 21:9 | Ultrawide (decide: support or refuse) |
| 3440×1440 | 21:9 | Ultrawide |

For each, verify:

1. Capture region lands on the right UI element.
2. Template match score is still above threshold.
3. OCR still reads the number.
4. Click lands on the button.

A quick way to test without changing your monitor: resize the Roblox window to each 16:9 size. That exercises the scaling code even if the physical monitor stays the same.

---

## 12. Scaling checklist

- [ ] Process is per-monitor DPI aware before anything else.
- [ ] All stored coordinates are client-relative.
- [ ] Client origin re-read every tick (or on move/resize).
- [ ] Reference resolution documented (usually 1920×1080).
- [ ] Scale factors computed from the **client** size, not the window size.
- [ ] Uniform scale for templates, non-uniform only when 16:9 is guaranteed.
- [ ] Aspect ratio checked at startup; unsupported ratios refused with a message.
- [ ] DPI scale checked at startup; unsupported scales refused with a message.
- [ ] Multi-monitor negative coordinates handled.
- [ ] Window resized to the reference size if possible.
- [ ] Tested at 1280×720, 1920×1080, 2560×1440, 3840×2160.

---

## Sources

- `GetClientRect`: <https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getclientrect>
- `GetDpiForWindow`: <https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow>
- AutoHotkey DPI scaling: <https://www.autohotkey.com/docs/v2/misc/DPIScaling.htm>
- AHK DPI tutorial (multi-monitor, ImageSearch across DPI): <https://www.autohotkey.com/boards/viewtopic.php?t=121040>
- Roblox UDim2 scale vs offset: <https://create.roblox.com/docs/ui/position-and-size>
- Roblox UI scaling guide: <https://devforum.roblox.com/t/complete-comprehensive-roblox-ui-scaling-guide/2232510>
- Natro `GetRobloxClientPos` / `GetYOffset`: <https://github.com/NatroTeam/NatroMacro/blob/main/lib/Roblox.ahk>
- Revolution detection requirements: <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>
- Ultimate Macro setup guide: <https://ultmacro.xyz/guide/>

---

*Next: [06-input-simulation.md](06-input-simulation.md)*
