# 02 — Screen Capture

> **If you only remember one thing:** capture the smallest rectangle you can, from the game's *client area*, using a method that actually works on hardware-accelerated windows. Everything else is optimisation.

---

## 1. What "capturing the screen" means

Windows does not give you "the screen". It gives you a **device context (DC)** — a handle to something drawable — and you copy pixels out of it.

There are four practical ways to get game pixels:

| Method | What it copies | Speed | Can capture occluded window? | Works on Roblox? |
|---|---|---|---|---|
| **GDI `BitBlt`** | A rectangle from a DC (window or desktop) | Fast (5–30 ms) | No (captures what's on top) | Often gives **white/black** on Roblox |
| **DXGI Desktop Duplication** | The composited desktop, GPU-side | Very fast (200+ FPS possible) | No | Yes, but only the visible desktop |
| **Windows.Graphics.Capture (WGC)** | A specific window or monitor, GPU-side | Fast, GPU | **Yes** | **Yes — recommended for Roblox** |
| **`PrintWindow`** | Asks a window to draw itself into a DC | Slow (26 ms+) | **Yes** | Unreliable with hardware acceleration |

**Practical recommendation:**

- If the macro requires the Roblox window to be focused and visible (most do, because input needs focus), **GDI `BitBlt` on the client area is fine and simplest**.
- If you see white/black frames, switch to **Windows.Graphics.Capture**.
- Do not build on `PrintWindow` unless you specifically need background capture and have tested it.

---

## 2. The Roblox-specific capture problem

Roblox renders with DirectX into a hardware-accelerated swap chain. GDI `BitBlt` reads the *window's* DC, which for a D3D window may not contain the rendered frame — you get white, black, or the last GDI-drawn content.

Evidence:

- OBS added a special case in 2025: when the window class is `WINDOWSCLIENT` (Roblox), automatically switch window capture to **Windows Graphics Capture** mode, because the default BitBlt path produced a "non-functional white screen".
- Roblox users report the same: window capture via BitBlt = white screen; switching to "Windows 10 (WGC)" fixes it.
- Exclusive fullscreen makes it worse. **Borderless windowed / windowed** is the reliable mode.

So:

```
Roblox display mode:
  ✅ Windowed
  ✅ Borderless windowed (best for macros)
  ❌ Exclusive fullscreen  (capture breaks, overlays hidden)
```

Most macro documentation tells users to run windowed/borderless and often to keep the game at a fixed size. Revolution even creates a *virtual display* on macOS and patches Roblox to a lower-DPI window so it can read it reliably.

---

## 3. Finding the Roblox window

Roblox's process is `RobloxPlayerBeta.exe`. Its main window class is `WINDOWSCLIENT` and its title is usually `Roblox`.

### Windows API calls you need

| Call | Purpose |
|---|---|
| `FindWindow(class, title)` / `EnumWindows` | Get the window handle (`HWND`) |
| `GetClientRect(hwnd, &rect)` | Client area size (excludes title bar/borders) |
| `ClientToScreen(hwnd, &point)` | Convert client (0,0) to screen coordinates |
| `GetWindowRect(hwnd, &rect)` | Whole window including borders (usually not what you want) |
| `GetDpiForWindow(hwnd)` | DPI of the monitor the window is on (Windows 10+) |
| `GetForegroundWindow()` | Is the game actually focused? |
| `IsIconic(hwnd)` | Is it minimised? |

### Python

```python
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

def find_roblox():
    hwnd = user32.FindWindowW("WINDOWSCLIENT", None)
    if not hwnd:
        # fallback: search by process name
        import win32gui, win32process, psutil
        def cb(h, _):
            if win32gui.IsWindowVisible(h):
                _, pid = win32process.GetWindowThreadProcessId(h)
                try:
                    if psutil.Process(pid).name().lower() == "robloxplayerbeta.exe":
                        found.append(h)
                except Exception:
                    pass
            return True
        found = []
        win32gui.EnumWindows(cb, None)
        hwnd = found[0] if found else 0
    return hwnd

def client_rect(hwnd):
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    # pt = screen coords of client top-left
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top
```

### AutoHotkey v2

```ahk
GetRobloxHWND() {
    if (hwnd := WinExist("Roblox ahk_exe RobloxPlayerBeta.exe"))
        return hwnd
    return 0
}

GetRobloxClientPos(hwnd) {
    WinGetClientPos &x, &y, &w, &h, "ahk_id " hwnd
    return {x: x, y: y, w: w, h: h}
}
```

Natro Macro's `lib/Roblox.ahk` does exactly this, including a fallback for the Microsoft Store version (`ApplicationFrameHost.exe` → `ApplicationFrameInputSinkWindow1`).

---

## 4. Capture only the region you need

This is the single biggest performance win, and it costs nothing.

```python
# Bad: capture the whole 1920x1080 screen, then crop
frame = grab(0, 0, 1920, 1080)          # 2,073,600 pixels
crop  = frame[900:1020, 1500:1900]

# Good: capture the 400x120 region directly
crop = grab(x + 1500, y + 900, 400, 120)  # 48,000 pixels  (43x less work)
```

### Rules of thumb

| What you're reading | Region size | Capture rate |
|---|---|---|
| A single button | 100×60 | 5–10 Hz |
| Money counter | 250×60 | 1–2 Hz |
| Tower placement grid | 600×400 | 10 Hz |
| Whole game (debug overlay) | full client | 2–5 Hz only |

If you need to watch 5 different small regions, **take one screenshot of the bounding box that contains all of them** and slice it in memory. One capture + five slices is much cheaper than five captures.

---

## 5. Capture code

### 5.1 Python + `mss` (simple, reliable, ~60 FPS)

```python
import mss
import numpy as np

sct = mss.mss()

def grab(x, y, w, h):
    img = sct.grab({"left": x, "top": y, "width": w, "height": h})
    # BGRA -> BGR numpy array
    return np.array(img)[:, :, :3]
```

`mss` uses BitBlt under the hood. Works for most windows, fails on some hardware-accelerated ones.

### 5.2 Python + `dxcam` (fastest)

```python
import dxcam

cam = dxcam.create()          # picks the primary output
frame = cam.grab(region=(x, y, x + w, y + h))   # returns HxWx3 BGR or None
```

DXGI Desktop Duplication. Very fast (hundreds of FPS), but:
- Only captures what's visible on that monitor.
- Returns `None` if nothing changed since the last frame (that's a feature — you can skip processing).
- Doesn't work if the game is minimised.

### 5.3 Windows.Graphics.Capture (window-specific, occluded OK)

Simplest path is a library, e.g. `wgc-python` or `WindowsCapture`:

```python
from windows_capture import WindowsCapture

capture = WindowsCapture(cursor_capture=False, draw_border=False,
                         window_name="Roblox")

@capture.event
def on_frame_arrived(frame, control):
    img = frame.frame_buffer   # numpy BGRA
    # ... process ...
    control.stop()

capture.start()
```

Notes:
- Windows may draw a yellow border around the captured window unless you use the newer `IsBorderRequired = false` API (Windows 11).
- Frame delivery is tied to DWM composition — typically monitor refresh rate, and it may stop delivering when nothing changes.
- It can capture a window that is behind another window, which is useful for "run in background" designs.

### 5.4 AutoHotkey v2 + GDI+

```ahk
#Include Gdip_All.ahk

pToken := Gdip_Startup()

Capture(x, y, w, h) {
    ; "x|y|w|h" is the Gdip_BitmapFromScreen syntax
    return Gdip_BitmapFromScreen(x "|" y "|" w "|" h)
}

; later
pBitmap := Capture(cx, cy, 400, 120)
Gdip_SaveBitmapToFile(pBitmap, "debug.png")
Gdip_DisposeImage(pBitmap)
```

Natro stores its templates as base64 strings inside `.ahk` files, decodes them to GDI+ bitmaps at startup into a `Map`, and keeps them in memory. That's a nice lightweight pattern: **no external image files to lose, no disk I/O per frame**.

### 5.5 C# / .NET

```csharp
using var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
using (var g = Graphics.FromImage(bmp))
    g.CopyFromScreen(x, y, 0, 0, new Size(w, h), CopyPixelOperation.SourceCopy);
```

Same BitBlt limitations. For WGC, use `Windows.Graphics.Capture` with `Direct3D11CaptureFramePool`.

---

## 6. DPI: the bug that eats weeks

Windows has two coordinate spaces:

- **Logical pixels** — what most apps see. At 150% scaling, a 1920×1080 monitor is "1280×720" logically.
- **Physical pixels** — what the GPU actually draws.

Capture APIs usually give **physical** pixels. Input APIs (`SetCursorPos`, `SendInput`) usually take **logical** coordinates unless your process is DPI-aware.

If you mix them, every coordinate is off by the scale factor, and it gets worse the further from the top-left you click.

### The fix

Make your process **per-monitor DPI aware** before doing anything else.

C#:
```csharp
[DllImport("user32.dll")]
static extern bool SetProcessDPIAware();
SetProcessDPIAware();
```

Python (must be called before any window/DC use):
```python
import ctypes
ctypes.windll.user32.SetProcessDPIAware()
# or, better, per-monitor v2:
# ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
```

AutoHotkey v2:
```ahk
DllCall("SetThreadDpiAwarenessContext", "ptr", -3, "ptr")  ; per-monitor aware
```

After that, `GetClientRect` and capture agree, and `Click(x, y)` means the same pixel.

### The other fix: don't support scaling at all

Many macros simply require **Windows display scaling = 100%** and refuse to run otherwise. Revolution literally blocks startup with:

> `Your monitor scale must be set to 100% in order for the macro to start.`

This is a legitimate engineering choice. It removes an entire class of bugs. Just tell the user *why*.

---

## 7. HDR, colour profiles, and "why are my colours wrong?"

- **HDR on** changes the pixel values Windows reports. A red button may capture as a different red, or the whole image may look washed out. Revolution requires HDR off, including Auto-HDR.
- **Windows "night light"** tints everything orange. Detection thresholds break.
- **Monitor colour profiles** (especially on macOS, e.g. "Color LCD" vs "Display P3") shift colours enough to break matching. Revolution recommends Display P3 on macOS.
- **In-game graphics settings** (shadows, bloom, colour grading) change pixels. TDS macros ask for "Graphics Mode: Manual" so the game doesn't silently change quality.

**Design implication:** never match on exact RGB values if you can avoid it. Use:
- grayscale template matching (immune to hue shifts),
- colour *ranges* with tolerance,
- or normalise the crop before matching.

---

## 8. Verifying that capture actually works

Before building any detection, write a 20-line sanity check:

1. Find the window.
2. Capture the client area.
3. Save it as `debug_capture.png`.
4. Compute the fraction of non-black and non-white pixels.

```python
import numpy as np

def looks_valid(img):
    if img is None or img.size == 0:
        return False, "empty"
    mean = img.mean()
    black = (img.max(axis=2) < 8).mean()
    white = (img.min(axis=2) > 247).mean()
    if black > 0.98:
        return False, "all black (capture blocked or minimised)"
    if white > 0.98:
        return False, "all white (BitBlt failed on hardware acceleration)"
    if not (5 < mean < 250):
        return False, f"suspicious mean brightness {mean:.0f}"
    return True, "ok"
```

Run this on every user's machine at startup. If it fails, show a specific message ("Switch Roblox to borderless windowed" / "Disable HDR") instead of silently clicking nothing.

Revolution's equivalent is their pre-run diagnostic and their `Capture Mode` dropdown (Default → Legacy Monitor → Window → Legacy), which lets a user switch capture backends when the default one misreads their setup.

---

## 9. Performance numbers (measured, from public benchmarks)

From a Python screenshot benchmark on a low-power mini PC (full screen / cropped):

| Library | Full screen (ms) | Cropped (ms) |
|---|---|---|
| Win32 `BitBlt` | 12.5 | 29.0 |
| PIL `ImageGrab` | 13.2 | 17.0 |
| `mss` | 16.0 | 55.1 |
| `pyautogui` | 11.5 | 15.9 |
| `dxcam` | 40.1* | 37.3* |

\* These dxcam numbers look bad because the test includes GPU→CPU readback and the machine has weak integrated graphics. On a normal desktop, dxcam reaches 200+ FPS. The lesson: **benchmark on your target hardware**, not on someone else's blog.

Practical target: **one capture + all detection under 30 ms** for a 10 Hz macro. That leaves plenty of CPU for the game.

---

## 10. Capture checklist

- [ ] Process is DPI-aware before any capture or click.
- [ ] Using `GetClientRect` + `ClientToScreen`, not `GetWindowRect`.
- [ ] Capturing the smallest region possible.
- [ ] Saving a debug PNG on failure.
- [ ] Detecting all-black / all-white frames and reporting a real error.
- [ ] Requiring borderless/windowed, not exclusive fullscreen.
- [ ] Not capturing on a timer that drifts (use a fixed-rate loop or `time.perf_counter`).
- [ ] Releasing GDI objects / bitmaps every frame (a leak here kills an overnight run).
- [ ] Handling the window being minimised, moved, or resized.

---

## Sources

- OBS PR adding `WINDOWSCLIENT` → WGC auto-switch: <https://github.com/obsproject/obs-studio/pull/12348>
- OBS forum: Roblox white screen with BitBlt, fixed by WGC: <https://obsproject.com/forum/threads/roblox-game-capture-not-working-just-a-black-screen.167811/>
- Roblox DevForum: game capture black screen: <https://devforum.roblox.com/t/robloxplayerbetaexe-not-working-with-a-game-capture-in-obs/2436067>
- Windows.Graphics.Capture docs: <https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture>
- WGC vs Desktop Duplication: <https://stackoverflow.com/questions/74084077/desktop-duplication-api-vs-windows-graphics-capture>
- dxcam benchmark claims: <https://github.com/ra1nty/DXcam>
- Python screenshot library benchmark: <https://github.com/kavmax/compare-screenshots-python-windows>
- AutoHotkey DPI tutorial: <https://www.autohotkey.com/boards/viewtopic.php?t=121040>
- Natro `Roblox.ahk`: <https://github.com/NatroTeam/NatroMacro/blob/main/lib/Roblox.ahk>
- Revolution detection requirements: <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>

---

*Next: [03-finding-things-on-screen.md](03-finding-things-on-screen.md)*
