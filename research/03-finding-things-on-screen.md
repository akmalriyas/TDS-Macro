# 03 — Finding Things on Screen

> **If you only remember one thing:** a detector returns a *score*, not a fact. Your job is to pick a threshold where the score means something, and to keep the search area small enough that the wrong answer is unlikely.

---

## 1. The four detectors you actually need

| Detector | Question it answers | Cost | Use for |
|---|---|---|---|
| **Template match** | "Where is this picture?" | 1–20 ms | Buttons, icons, logos, towers |
| **Colour test** | "Is this area this colour?" | < 1 ms | Button enabled/disabled, bars, screen fades |
| **Pixel signature** | "Does this exact spot look like X?" | < 0.1 ms | Menu open/closed, tab selected |
| **OCR** | "What does this text say?" | 100–300 ms | Money, wave, pollen |

Everything else is a combination of these. Learn them in that order.

---

## 2. Template matching

### 2.1 The idea

You have a small image (the **template**) — say, the "Play Again" button, 180×48 pixels. You slide it across the screenshot and, at every position, compute a similarity score. The best position is your match.

```
screenshot (1920x1080)
┌──────────────────────────────────────────┐
│                                          │
│        ┌────────┐                        │
│        │template│  <- slide everywhere    │
│        └────────┘                        │
│                                          │
└──────────────────────────────────────────┘
```

OpenCV implements this as `matchTemplate`. The result is a 2D array of scores; you take the maximum.

### 2.2 Which method?

Use **`TM_CCOEFF_NORMED`** by default.

| Method | Score range | Notes |
|---|---|---|
| `TM_SQDIFF_NORMED` | 0 = perfect | Lower is better; easy to get backwards |
| `TM_CCORR_NORMED` | 0..1 | Bad with bright/uniform templates |
| `TM_CCOEFF_NORMED` | -1..1 | **Best general choice**; 1.0 = perfect |
| `TM_CCOEFF_NORMED` + mask | -1..1 | Use for transparent / non-rectangular templates |

### 2.3 Code

```python
import cv2
import numpy as np

def find_template(screen_bgr, template_bgr, threshold=0.85, mask=None):
    """Return (x, y, w, h, score) of the best match, or None."""
    screen = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    templ  = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)

    if templ.shape[0] > screen.shape[0] or templ.shape[1] > screen.shape[1]:
        return None

    method = cv2.TM_CCOEFF_NORMED
    if mask is not None:
        result = cv2.matchTemplate(screen, templ, method, mask=mask)
    else:
        result = cv2.matchTemplate(screen, templ, method)

    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None

    h, w = templ.shape[:2]
    return (max_loc[0], max_loc[1], w, h, float(max_val))
```

### 2.4 What threshold?

There is no universal number. Published defaults:

- OpenCV/MAS-style automation guides use **0.8** as a starting default.
- Many practical macros use **0.85–0.95** for UI, because UI is pixel-perfect.
- For noisy/animated things, **0.65–0.8**.
- Use **0.98+** only if you want an almost exact match (e.g. detecting a specific text string rendered identically).

**Do not guess.** Tune it with data:

1. Collect 50–100 screenshots: 30 where the element is present, 30 where it isn't, plus edge cases (partially covered, different map, different theme).
2. Run the detector on all of them and record the best score for each.
3. Plot two histograms: "present" scores and "absent" scores.
4. Put the threshold in the gap.

```python
# If present scores are all > 0.91 and absent scores are all < 0.72,
# then 0.82 is a safe threshold with margin on both sides.
```

If the two distributions overlap, **template matching is the wrong tool** for that element. Switch to colour, OCR, or a combination.

### 2.5 The classic false positive

A 0.95 score does not always mean a match. A template that is mostly flat colour (a white button, a solid panel) will correlate highly with lots of flat areas.

Fixes, in order of effectiveness:

1. **Make the template more distinctive.** Crop tight around unique details — text, an icon, a corner, a shadow. Don't include large flat regions.
2. **Use a mask** so flat/transparent pixels don't vote.
3. **Match on edges** (Canny) instead of raw grayscale.
4. **Check the neighbourhood** — a real "Play Again" button is near the results panel; a random white blob is not.
5. **Require two elements** — e.g. the button *and* its icon.

```python
# Edge-based matching: often much more robust to colour/theme changes
edges_screen = cv2.Canny(screen_gray, 50, 150)
edges_templ  = cv2.Canny(templ_gray, 50, 150)
```

### 2.6 Masks (transparent or non-rectangular templates)

If your template has transparency (a PNG icon on a transparent background), build a mask from the alpha channel:

```python
templ = cv2.imread("coin.png", cv2.IMREAD_UNCHANGED)
bgr   = templ[:, :, :3]
alpha = templ[:, :, 3]

mask = cv2.cvtColor(alpha, cv2.COLOR_GRAY2BGR)  # 255 where opaque
result = cv2.matchTemplate(screen_gray, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY),
                           cv2.TM_CCORR_NORMED, mask=mask)
```

Note: masked matching only works with `TM_SQDIFF` and `TM_CCORR_NORMED` in OpenCV. Test both and see which gives cleaner scores for your assets.

### 2.7 Multiple matches

`minMaxLoc` gives you only the best match. For "find all coins" you need all peaks:

```python
def find_all(screen_gray, templ_gray, threshold=0.8, min_distance=20):
    res = cv2.matchTemplate(screen_gray, templ_gray, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    pts = sorted(zip(xs, ys, res[ys, xs]), key=lambda p: -p[2])

    kept = []
    for x, y, score in pts:
        if all(abs(x - kx) > min_distance or abs(y - ky) > min_distance
               for kx, ky, _ in kept):
            kept.append((int(x), int(y), float(score)))
    return kept
```

This is **non-maximum suppression (NMS)**: after finding a good match, ignore everything close to it. Without NMS you get 40 boxes on one coin.

### 2.8 Multi-scale matching

If the UI can be a different size (different resolution, UI scale setting), the template won't match at its native size. Resize the template across a range of scales and try each:

```python
def find_multiscale(screen_gray, templ_gray, scales=(0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1),
                    threshold=0.85):
    best = None
    for s in scales:
        w = int(templ_gray.shape[1] * s)
        h = int(templ_gray.shape[0] * s)
        if w < 8 or h < 8:
            continue
        t = cv2.resize(templ_gray, (w, h), interpolation=cv2.INTER_AREA)
        if t.shape[0] > screen_gray.shape[0] or t.shape[1] > screen_gray.shape[1]:
            continue
        res = cv2.matchTemplate(screen_gray, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx >= threshold and (best is None or mx > best[4]):
            best = (loc[0], loc[1], w, h, float(mx), s)
    return best
```

Cost scales linearly with the number of scales. 7 scales = 7× slower. Only use multi-scale when you actually support multiple resolutions.

**Better alternative:** normalise first. If you capture at 1920×1080 always (by asking the user to size the window, or by scaling the captured image down), a single scale works.

### 2.9 Template sizes — practical advice

| Bad template | Good template |
|---|---|
| Whole button including flat background | Tight crop on the text + icon + border |
| 300×200 area with one small detail | 80×40 around the detail |
| Changes colour with theme | Grayscale/edge version |
| One frame of an animation | 3–5 frames, try each |
| Includes the mouse cursor | Never include the cursor |

A good template is **small, distinctive, and stable**. If you can't describe in one sentence why it's unique, it isn't.

---

## 3. Colour detection

### 3.1 Single pixel

```python
px = screen[y, x]           # BGR
is_green = px[1] > 150 and px[0] < 100 and px[2] < 100
```

Fast, but brittle: one pixel can be affected by anti-aliasing, compression, or a shadow.

### 3.2 Region ratio (much better)

Ask "what fraction of this box is green?" instead of "is this pixel green?".

```python
def colour_ratio(region_bgr, lower_bgr, upper_bgr):
    mask = cv2.inRange(region_bgr, np.array(lower_bgr), np.array(upper_bgr))
    return mask.mean() / 255.0     # 0.0 .. 1.0

# "Ready button is green" -> ratio > 0.35
```

This survives partial occlusion, text on top of the button, and small animations. It is the workhorse for state checks.

### 3.3 Use HSV, not RGB

RGB values change a lot with brightness. HSV separates **hue** (what colour) from **value** (how bright), so a shadow doesn't break your test.

```python
hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
# OpenCV hue is 0-179
mask = cv2.inRange(hsv, (35, 80, 80), (85, 255, 255))   # greens
```

### 3.4 Progress bars

A health/mana/charge bar is a rectangle that fills from left to right. Two ways to read it:

```python
# Method A: find the boundary in one row
row = bar_region[mid_y]
filled = 0
for px in row:
    if is_bar_colour(px): filled += 1
    else: break
percent = filled / bar_width

# Method B: count coloured pixels in the whole bar
ratio = colour_ratio(bar_region, bar_low, bar_high)
```

Method A is more accurate if the bar has a border. Method B is more robust to noise.

### 3.5 Screen fades and loading screens

A very cheap and very useful check:

```python
def screen_state(frame):
    mean = frame.mean()
    std  = frame.std()
    if mean < 12:            return "black"      # loading / fade
    if mean > 245:           return "white"      # flash / broken capture
    if std < 3:              return "flat"       # solid colour screen
    return "content"
```

Use this to avoid running detection on a loading screen and generating 500 false failures.

---

## 4. Pixel signatures (the cheapest detector)

If you have a fixed UI at a fixed size, you can identify a screen by sampling a handful of pixels at known offsets.

```python
SIGNATURES = {
    "lobby":   [(120, 40, (40, 40, 40)), (300, 60, (255, 210, 60))],
    "in_game": [(120, 40, (20, 20, 20)), (300, 60, (90, 90, 90))],
}

def match_signature(frame, tolerance=12):
    for name, points in SIGNATURES.items():
        ok = True
        for x, y, (b, g, r) in points:
            px = frame[y, x]
            if abs(int(px[0]) - b) > tolerance or \
               abs(int(px[1]) - g) > tolerance or \
               abs(int(px[2]) - r) > tolerance:
                ok = False
                break
        if ok:
            return name
    return None
```

**Use it for:** "which menu am I on?", "is the inventory open?", "did the screen change since last tick?"
**Don't use it for:** anything that moves, animates, or can be covered.

The cheapest version of all: hash a small region and compare hashes.

```python
import hashlib
def region_hash(frame, x, y, w, h):
    return hashlib.md5(frame[y:y+h, x:x+w].tobytes()).hexdigest()
```

If the hash is unchanged, the region didn't change — skip OCR entirely.

---

## 5. FindText (the AHK secret weapon)

If you're building in AutoHotkey, the built-in `ImageSearch` is slow and needs external image files. **FindText** is a popular library that solves both.

How it works:

1. You capture a small image.
2. It converts it to **black and white**, then encodes it as a string of `1`/`0` (text vs background).
3. At runtime it does the same to the screenshot and matches the strings.

Why it's good:

- **No image files** — the template lives in your script as text.
- **Faster** than `ImageSearch` (reported ~10%, sometimes 2–3× depending on case).
- **Tunable error margins** — `err1` for text pixels, `err0` for background pixels.
- Can search a **bound window** even if it's behind other windows.
- Has a built-in capture GUI, and you can build simple OCR with it (match digit templates).

Example:

```ahk
#include <FindText>

Text := "|<PlayAgain>**50$41.0000...0000"   ; pasted from the FindText GUI

if (ok := FindText(&X, &Y, x1, y1, x2, y2, 0.1, 0.1, Text)) {
    Click(X, Y)
}
```

Caveats:

- **DPI sensitive.** A template captured at 100% won't match at 125%.
- Slower as you widen the error margins (5–10× if you go from 0 to 0.3).
- Slower as you widen the search area — always restrict to the window.

Natro Macro uses this approach: all UI templates are stored as **base64-encoded PNGs inside `.ahk` files**, decoded into GDI+ bitmaps at startup and cached in a `Map`. It also has literal **digit bitmaps 0–9** for reading sticker counts — a home-made OCR.

---

## 6. Anchors: the trick that makes everything resize-proof

Never position a detector by absolute coordinates. Find a **stable anchor** first, then define everything relative to it.

```
whole screen
┌─────────────────────────────────────────────┐
│  [Roblox logo]  <- anchor (always top-left) │
│                                             │
│         money label is at anchor + (1450, 20)
│                                             │
└─────────────────────────────────────────────┘

If the window moves 300 px right:
  anchor moves 300 px right
  money label moves 300 px right   (same offset)
```

Natro does this for BSS: `GetYOffset()` searches for the **top pollen bar** in a 60×100 strip at the top-centre of the client area, and uses its Y position to compute the vertical offset of every other UI element. That's why the macro still works if Roblox adds a banner or changes the top bar height.

### How to pick an anchor

| Good anchor | Bad anchor |
|---|---|
| A fixed logo or icon in a corner | Something that disappears in menus |
| The top-left of a panel border | An animated element |
| A HUD label that is always visible in-game | A button that changes state |
| The game's own UI frame | Anything with transparency over gameplay |

### Anchor + relative detection

```python
def locate_ui(client_frame):
    anchor = find_template(client_frame, TEMPLATES["hud_logo"], threshold=0.9)
    if anchor is None:
        return None                       # not in game
    ax, ay, _, _, _ = anchor

    money_box = (ax + 1450, ay + 20, 250, 60)
    return {"anchor": (ax, ay), "money_box": money_box}
```

This also acts as a **state check**: if the anchor isn't found, you're not where you think you are, so don't click anything.

---

## 7. Waiting, debouncing, and "is it really there?"

Screens flicker. Menus animate. A single frame is not evidence.

### Require N consecutive frames

```python
class StableDetector:
    def __init__(self, need=3):
        self.need = need
        self.count = 0

    def update(self, found: bool) -> bool:
        self.count = self.count + 1 if found else 0
        return self.count >= self.need
```

Requiring 2–3 frames costs 100–300 ms and eliminates almost all flicker false positives.

### Cooldowns

After clicking something, don't click it again for at least X ms, even if it's still on screen. Menus take time to close.

```python
last_click = {}
def can_click(name, now, cooldown=0.8):
    if now - last_click.get(name, 0) < cooldown:
        return False
    last_click[name] = now
    return True
```

### Verify the action

```python
def click_and_verify(click_fn, detect_fn, timeout=2.0):
    before = detect_fn()
    click_fn()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if detect_fn() != before:
            return True
        time.sleep(0.05)
    return False
```

If a click doesn't change anything, don't spam it 50 times — log it, try a fallback, or move to recovery.

---

## 8. Template metadata: store detection config with the image

Hardcoding thresholds and search boxes in code is how macros rot. Put them next to the asset.

```json
{
  "id": "tds_play_again",
  "file": "assets/tds/play_again.png",
  "search": { "anchor": "tds_results_panel", "dx": 620, "dy": 700, "w": 260, "h": 90 },
  "threshold": 0.88,
  "scales": [1.0],
  "grayscale": true,
  "require_frames": 2,
  "click_offset": [0, 0],
  "cooldown_ms": 1500,
  "description": "Results screen 'Play Again' button"
}
```

Then the detector is generic:

```python
def detect(frame, meta):
    x, y, w, h = resolve_search_box(frame, meta["search"])
    crop = frame[y:y+h, x:x+w]
    tpl  = load_template(meta["file"], grayscale=meta["grayscale"])
    hit  = find_template(crop, tpl, meta["threshold"])
    if not hit:
        return None
    hx, hy, hw, hh, score = hit
    return {"x": x + hx + hw // 2, "y": y + hy + hh // 2, "score": score}
```

This makes adding a new button a data change, not a code change. It also makes it easy to build a **template editor UI** later.

---

## 9. Debugging detections

When something doesn't work, you need to *see* what the detector sees. Build this early:

```python
def debug_draw(frame, detections, path="debug.png"):
    out = frame.copy()
    for d in detections:
        x, y, w, h = d["box"]
        colour = (0, 255, 0) if d.get("ok") else (0, 0, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), colour, 2)
        label = f'{d["name"]} {d.get("score", 0):.2f}'
        cv2.putText(out, label, (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
    cv2.imwrite(path, out)
```

Revolution does exactly this in-product: **Show Overlay** draws bounding boxes over detected tokens and sprinklers so the user can confirm detection is working before trusting a 10-hour run. That feature alone prevents a huge share of support tickets.

---

## 10. Detection checklist

- [ ] Searching a small region, not the whole screen.
- [ ] Grayscale (or edges) unless colour is the point.
- [ ] Threshold chosen from data, not guessed.
- [ ] Template is small and distinctive.
- [ ] Anchored to a stable element, not absolute coordinates.
- [ ] Requires 2–3 stable frames before acting.
- [ ] Cooldown after each action.
- [ ] Verifies the action changed the screen.
- [ ] Saves a debug image on failure.
- [ ] Every asset has metadata (search box, threshold, description).

---

## Sources

- OpenCV template matching docs: <https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html>
- Multi-scale template matching: <https://pyimagesearch.com/2015/01/26/multi-scale-template-matching-using-python-opencv/>
- OpenCV forum: false positives and threshold selection: <https://forum.opencv.org/t/false-positive-in-template-matching/525>
- Stack Overflow: reducing false positives on GUI matching: <https://stackoverflow.com/questions/63554276/how-to-reduce-false-positive-on-openCV-template-match-on-a-software-gui>
- MAS docs — template + OCR + threshold 0.8: <https://automationmacro.com/docs/concepts>
- FindText tutorial: <https://www.autohotkey.com/boards/viewtopic.php?t=102806>
- FindText source: <https://github.com/Ixiko/AHK-libs-and-classes-collection/blob/master/libs/a-f/FindText.ahk>
- Natro image recognition system (base64 bitmaps, digit OCR): <https://deepwiki.com/NatroTeam/NatroMacro/6.2-image-recognition-system>
- Natro `background.ahk` (bitmap cache): <https://github.com/NatroTeam/NatroMacro/blob/main/submacros/background.ahk>
- Revolution Show Overlay / detection troubleshooting: <https://revolutionmacro.com/docs/gathering/set-up-ai-gather/>

---

*Next: [04-reading-numbers.md](04-reading-numbers.md)*
