# 04 — Reading Numbers Off the Screen

> **If you only remember one thing:** OCR is the slow, fragile part of a macro. Use it only on tiny crops, only as often as you must, and always sanity-check the number against what you already know.

This doc answers the question: *"how does the macro know I have 12,450 coins?"*

---

## 1. Why numbers are hard

Reading `12,450` from a screenshot sounds trivial. It isn't, because:

1. **The font is custom.** Game UIs use decorative fonts. OCR models are trained on normal text.
2. **The background is busy.** Numbers sit on gradients, particles, or gameplay.
3. **The text is small and anti-aliased.** 14px text is near the limit of many OCR engines.
4. **Numbers are abbreviated.** `12.4K`, `1.2M`, `3.4B`. You lose precision by design.
5. **It changes constantly.** Money ticks up every frame in some games.
6. **It's localised.** `1,234.56` vs `1.234,56`.
7. **OCR confuses characters.** `0/O`, `1/l/I`, `5/S`, `6/G`, `8/B`, `2/Z`.

So a real macro never does "OCR the whole screen and parse the number". It does this:

```
find the money label  ->  crop it tight  ->  clean it up  ->  read it
      ->  parse  ->  validate  ->  smooth  ->  publish to world model
```

---

## 2. Two ways to read a number

### 2.1 OCR (optical character recognition)

You give an image of text to an engine, it gives you a string.

**Pros:** reads any number, any length, no per-font setup.
**Cons:** 100–300 ms per call, misreads characters, needs preprocessing, needs a language pack.

### 2.2 Digit templates (a home-made OCR)

You store 10 small images: `0.png` … `9.png` (plus maybe `,` `.` `K` `M` `B`). To read a number:

1. Crop the number region.
2. Binarize (text = white, background = black).
3. Find connected blobs — each blob is one character.
4. Sort blobs left to right.
5. Compare each blob to the 10 templates; take the best match.
6. Concatenate the digits.

**Pros:** very fast (1–5 ms), immune to font weirdness (you captured that exact font), no dependencies.
**Cons:** you must capture templates per font/size/resolution; struggles with touching characters (`1` next to `1`).

### 2.3 Which to use

| Situation | Use |
|---|---|
| Number is small, changes slowly, font is stable | **Digit templates** |
| Number has many digits / formats / locales | **OCR** |
| You need it 10× per second | **Digit templates** (or cache OCR) |
| You need it once per match | **OCR** |
| Font is decorative and OCR keeps failing | **Digit templates** |
| You can't be bothered to capture templates | **OCR** |

**Real macros mix them.** Natro uses literal digit bitmaps for sticker counts and OCR for inventory names. GRP's mini-game bot uses contour segmentation + digit templates and calls it *"a very fast and lightweight OCR solution"*. Ultimate Macro (TDS) uses Windows OCR for wave numbers and currency.

---

## 3. Choosing an OCR engine

| Engine | Speed | Accuracy on game UI | Setup | Notes |
|---|---|---|---|---|
| **Windows.Media.Ocr** | ~137 ms (benchmark) | OK for clean text | Built into Windows; needs language pack | Best speed/effort ratio on Windows |
| **Tesseract** | 200 ms–2 s | Poor on stylised game fonts | Bundled, ~15 MB | Bad at small game text; good with `--psm 7` + whitelist |
| **PaddleOCR** | Slow on CPU | Good | Large models | Overkill for a number |
| **EasyOCR** | Slow on CPU, GPU helps | Good | PyTorch, ~100 MB+ | Fine if you already ship Python + GPU |
| **oneocr / Snipping Tool OCR** | Fast | Very good | Undocumented API | Fragile across Windows updates |
| **Cloud OCR** | Fast | Excellent | Network + privacy | **Never** for a game macro (latency, cost, privacy) |

**Recommendation for a Roblox macro:** Windows.Media.Ocr on a tight crop, with digit templates as a fast path for the values you read most often.

### Windows OCR requirements

- The OCR language pack must be installed. Ultimate Macro explicitly checks for **English (US)** and offers to open Windows language settings if it's missing.
- `OcrEngine.TryCreateFromUserProfileLanguages()` uses the user's languages. That's why "install English (US)" is in every guide.
- Windows OCR has a maximum image dimension (`OcrEngine.MaxImageDimension`). Clamp your upscaled crop to it.

### Python access to Windows OCR

```python
import asyncio
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.graphics.imaging import BitmapDecoder, SoftwareBitmap
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

async def ocr_png_bytes(png_bytes: bytes) -> str:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("No OCR language pack installed")

    result = await engine.recognize_async(bitmap)
    return result.text
```

(That's the same flow the open-source Dig Tool uses.)

### Tesseract, if you must

```python
import pytesseract, cv2

cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,.KMBT"
text = pytesseract.image_to_string(gray_crop, config=cfg)
```

- `--psm 7` = treat the image as a single line of text.
- `--psm 8` = single word. `--psm 6` = a block.
- The whitelist dramatically improves digit accuracy and stops it inventing letters.
- Tesseract hates anti-aliased text on noisy backgrounds. Threshold first.

---

## 4. Preprocessing: the part that decides success

Raw crops OCR badly. Clean them up first.

### 4.1 The pipeline

```
crop
 │
 ├─ 1. convert to grayscale
 ├─ 2. upscale 2x (or 3x)         <- helps small fonts a lot
 ├─ 3. increase contrast
 ├─ 4. threshold / binarize       <- text becomes pure white on black
 ├─ 5. add padding (10-20 px)     <- OCR engines need margin
 │
 ▼
clean image -> OCR
```

```python
import cv2
import numpy as np

def clean_for_ocr(bgr, upscale=2):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # upscale
    if upscale != 1:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale,
                          interpolation=cv2.INTER_CUBIC)

    # contrast stretch
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    # binarize: Otsu picks a threshold automatically
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # OCR likes dark text on light background. If the game uses white text,
    # invert so text is black.
    if bw.mean() < 127:
        bw = cv2.bitwise_not(bw)

    # pad
    bw = cv2.copyMakeBorder(bw, 16, 16, 16, 16,
                            cv2.BORDER_CONSTANT, value=255)
    return bw
```

### 4.2 White text on dark background

Most game HUDs use white text. After grayscale, white text = high values. After Otsu you get white text on black. OCR engines prefer black on white, so invert.

```python
if (bw > 127).mean() < 0.5:   # mostly dark -> text is probably light
    bw = cv2.bitwise_not(bw)
```

### 4.3 Isolating text by colour

If the number is pure white and the background is coloured, keep only near-white pixels:

```python
hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv, (0, 0, 200), (179, 40, 255))   # low saturation, high value
text_only = cv2.bitwise_and(bgr, bgr, mask=mask)
```

This removes most of the background before OCR even sees it. Revolution and other macros lean on this heavily: the HUD is designed to be readable, so its text is high-contrast.

### 4.4 What *doesn't* help

A careful test on Windows OCR found that upscaling, grayscale, and contrast enhancement made **no difference** when the input was already high-resolution (692×174). Preprocessing helps *small, low-contrast* crops. It cannot fix an engine that simply doesn't know the font.

So: preprocess, measure, keep what helps, drop what doesn't. Don't cargo-cult a 10-step pipeline.

---

## 5. Parsing the text into a number

### 5.1 The formats you'll see

| Display | Meaning | Parse to |
|---|---|---|
| `12345` | 12,345 | 12345 |
| `12,345` | 12,345 | 12345 |
| `12.345` (EU) | 12,345 | 12345 |
| `1.2K` | ~1,200 | 1200 |
| `12.4K` | ~12,400 | 12400 |
| `1.2M` | ~1,200,000 | 1_200_000 |
| `3.45B` | ~3,450,000,000 | 3_450_000_000 |
| `1.2T` | 1.2 trillion | 1_200_000_000_000 |
| `1,2K` (EU) | 1.2K | 1200 |
| `+1.2K` | gained 1,200 | 1200 (and remember the sign) |

### 5.2 A robust parser

```python
import re

SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

def parse_number(text: str, decimal_comma=False) -> float | None:
    if not text:
        return None

    s = text.strip().upper()
    s = s.replace(" ", "").replace("\u00a0", "")
    s = s.replace("O", "0").replace("Q", "0")     # common OCR confusions
    s = s.replace("I", "1").replace("L", "1").replace("|", "1")
    s = s.replace("S", "5") if re.fullmatch(r"[0-9SL.,KMBT]+", s) else s

    m = re.search(r"([+-]?)(\d[\d.,]*)\s*([KMBT])?", s)
    if not m:
        return None

    sign, num, suffix = m.groups()

    # decide what the separator means
    if decimal_comma:
        num = num.replace(".", "").replace(",", ".")
    else:
        # "1,234" -> thousands ; "1.5" -> decimal
        if num.count(",") == 1 and "." not in num and len(num.split(",")[1]) == 3:
            num = num.replace(",", "")
        else:
            num = num.replace(",", "")

    try:
        value = float(num)
    except ValueError:
        return None

    if suffix:
        value *= SUFFIX[suffix]

    return -value if sign == "-" else value
```

### 5.3 The abbreviation problem (important)

`1.2M` is **not** 1,200,000. It's anything from 1,150,000 to 1,249,999. You cannot recover the exact value from the display.

This matters a lot. Workarounds:

| Need | Workaround |
|---|---|
| "Do I have enough for a 500K upgrade?" | Compare against the lower bound: `1.2M >= 500K` is safe. |
| "How much did I spend?" | Read before and after. `before - after` is exact if both are exact; if abbreviated, you get an estimate. |
| "Track exact money over time" | Impossible from an abbreviated display. Use another signal. |
| "Stop at 1M" | Trigger when the displayed value reaches `1.0M`. That's all the game gives you. |

**Design rule:** if the game only shows 2 significant digits, your macro should only make decisions that 2 significant digits can support. Don't build a strategy that needs ±1% precision on a number displayed to ±5%.

### 5.4 Character confusion table

| OCR sees | Might actually be | Fix |
|---|---|---|
| `O` | `0` | replace O→0 inside numeric context |
| `l`, `I`, `|` | `1` | replace |
| `S` | `5` | replace in numeric-only strings |
| `B` | `8` | **dangerous** — `B` is also a suffix |
| `G` | `6` | replace |
| `Z` | `2` | replace |
| `,` | `.` | ambiguous — depends on locale |
| ` ` | nothing | strip |

Do these replacements **only after** you've split off the suffix, otherwise "1.2B" becomes "1.28".

---

## 6. Validation: knowing when the read is wrong

This is what separates a macro that runs all night from one that empties your account.

### 6.1 Physical constraints

```python
class NumberTracker:
    def __init__(self, max_rate_per_sec):
        self.value = None
        self.max_rate = max_rate_per_sec
        self.history = []

    def update(self, reading, dt, allow_decrease=False):
        if reading is None:
            return self.value

        if self.value is not None:
            delta = reading - self.value
            if not allow_decrease and delta < 0:
                return self.value                     # money doesn't go down by itself
            if abs(delta) / max(dt, 1e-3) > self.max_rate:
                return self.value                     # impossible jump -> misread
        self.value = reading
        self.history.append(reading)
        self.history = self.history[-5:]
        return self.value

    def smoothed(self):
        if not self.history:
            return None
        return sorted(self.history)[len(self.history) // 2]   # median
```

### 6.2 Cross-checks

- **Monotonicity:** money only goes up unless you spent. Wave number only goes up. Level only goes up.
- **Plausible range:** if you had 12K a second ago, 120M is a misread, not a jackpot.
- **Digit count:** if the crop is 5 characters wide, a 9-character read is wrong.
- **Suffix sanity:** `1.2K` → `1.2M` in one tick is almost certainly an OCR error.
- **Confidence:** OCR engines can return word-level bounding boxes; reject words whose height is wildly different from the expected text height.
- **Two reads agree:** if two consecutive frames give the same value, trust it more.

### 6.3 Retry, don't crash

```python
def read_money_with_retry(frame_fn, crop_fn, tries=3):
    for _ in range(tries):
        crop = crop_fn(frame_fn())
        text = ocr(crop)
        value = parse_number(text)
        if value is not None:
            return value
        time.sleep(0.1)
    return None      # caller decides: keep last known value, or pause
```

Never let a failed OCR throw an exception that kills the loop.

---

## 7. Worked example: reading TDS cash

Goal: know how much cash you have, 2× per second, to decide when to upgrade.

### Step 1 — find the label

TDS shows cash at the top of the screen. The exact position depends on resolution. Two options:

- **Fixed box scaled by resolution:** capture at 1920×1080, define the box once, scale by `client_w / 1920`.
- **Anchored box:** find a stable element (the cash icon) and offset from it.

Start with the scaled fixed box; add anchoring if you support many resolutions.

```python
REF_W, REF_H = 1920, 1080
CASH_BOX_REF = (1460, 18, 220, 52)     # x, y, w, h at 1920x1080

def cash_box(client_w, client_h):
    x, y, w, h = CASH_BOX_REF
    sx, sy = client_w / REF_W, client_h / REF_H
    return int(x * sx), int(y * sy), int(w * sx), int(h * sy)
```

### Step 2 — crop and clean

```python
bx, by, bw, bh = cash_box(cw, ch)
crop = frame[by:by+bh, bx:bx+bw]
clean = clean_for_ocr(crop, upscale=3)
```

### Step 3 — read

```python
text = windows_ocr(clean)      # e.g. "12.4K"
value = parse_number(text)     # 12400.0
```

### Step 4 — validate

```python
tracker.update(value, dt=0.5, allow_decrease=True)   # spending is allowed
```

### Step 5 — publish

```python
world.money = tracker.smoothed()
world.money_text = text          # keep the raw string for the UI/log
```

### Step 6 — cache

Running OCR at 2 Hz on a 220×52 crop is cheap. Running it at 20 Hz is not. Check whether the crop changed at all before OCR:

```python
h = region_hash(frame, bx, by, bw, bh)
if h != last_hash:
    text = windows_ocr(clean)
    last_hash = h
```

In practice this cuts OCR calls by 80–95%, because the number only changes when money changes.

---

## 8. Worked example: reading the wave number

The wave number is a small integer that increases 1→N.

```python
WAVE_BOX_REF = (930, 14, 60, 40)

def read_wave(frame, cw, ch):
    crop = crop_scaled(frame, WAVE_BOX_REF, cw, ch)
    text = windows_ocr(clean_for_ocr(crop, upscale=4))
    n = parse_int(text)                 # digits only
    if n is None or not (0 <= n <= 100):
        return None
    if last_wave is not None and n < last_wave - 1:
        return None                     # can't go backwards
    return n
```

Because it's monotonic and bounded, validation is trivial and very effective.

Use the wave number as your **clock**. Instead of "wait 45 seconds then upgrade", do "when wave == 7, upgrade". That's far more robust to lag and slower machines. TDS strategies effectively do this: they record actions by wave, not by wall-clock time.

---

## 9. Digit templates in detail

If OCR is too slow or too inaccurate, build the 10-digit matcher.

### 9.1 Capturing templates

1. Get a screenshot where the number is clear.
2. Crop each digit **tightly** (no background, no padding).
3. Save as `digits/0.png` … `digits/9.png`.
4. Store the expected height so you can rescale at runtime.

### 9.2 Segmenting the number

```python
def segment_digits(bw):
    # bw: white text on black background, uint8
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(bw, 8)

    boxes = []
    for i in range(1, n):                     # skip background label 0
        x, y, w, h, area = stats[i]
        if area < 8:                          # noise
            continue
        if h < 6:                             # too short to be a digit
            continue
        boxes.append((x, y, w, h))

    boxes.sort(key=lambda b: b[0])            # left to right
    return boxes
```

Problem: `1` is narrow, `0` is wide, and adjacent digits can touch. Fixes:

- Use `cv2.morphologyEx` with a vertical kernel to separate touching digits.
- Or use vertical projection: sum each column; gaps are zero columns.

```python
def split_by_projection(bw):
    col = (bw > 0).sum(axis=0)
    gaps, start = [], None
    for x, v in enumerate(col):
        if v > 0 and start is None:
            start = x
        elif v == 0 and start is not None:
            gaps.append((start, x))
            start = None
    if start is not None:
        gaps.append((start, len(col)))
    return gaps
```

### 9.3 Matching

```python
def classify_digit(blob, templates, size=(24, 32)):
    blob = cv2.resize(blob, size, interpolation=cv2.INTER_AREA)
    best, best_score = None, -1
    for label, tpl in templates.items():
        tpl = cv2.resize(tpl, size, interpolation=cv2.INTER_AREA)
        score = cv2.matchTemplate(blob, tpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if score > best_score:
            best, best_score = label, score
    return best, best_score
```

Reject the whole number if any digit's score is below ~0.7, or if the digits' heights vary wildly (a sign the segmentation was wrong).

### 9.4 Normalising size

If the UI can be at different resolutions, resize the **crop** to the reference size before segmenting, so your templates always apply.

```python
crop = cv2.resize(crop, (ref_w, ref_h), interpolation=cv2.INTER_AREA)
```

This is much cheaper than generating templates at every scale.

---

## 10. When the number is not text at all

Some games show values as **bars**, **stars**, **pips**, or **coloured segments**, not numbers.

| Display | How to read it |
|---|---|
| Health bar | Width of the coloured region / total width |
| Progress ring | Angle of the filled arc (harder; use a template per 10% step) |
| Stars (1–5) | Count filled stars via template match |
| Segmented bar (10 blocks) | Count blocks matching the "filled" colour |
| Cooldown sweep | Sample the pixel at a fixed radius; when it's the "ready" colour, it's ready |

For a cooldown, you usually don't need the remaining time — just "is it ready?". That's a single colour test.

---

## 11. Performance budget

| Operation | Typical cost | Frequency |
|---|---|---|
| Crop 220×52 | < 0.1 ms | 10 Hz |
| Grayscale + upscale 3× | 1–2 ms | 2 Hz |
| Hash check | < 0.1 ms | 10 Hz |
| Windows OCR | 100–300 ms | 1–2 Hz |
| Digit template match (6 digits) | 1–5 ms | 10 Hz |

A good pattern:

```
every tick (10 Hz):
    capture money region
    if hash changed:
        enqueue OCR job          <- don't block the loop

OCR worker thread:
    take latest crop
    OCR -> parse -> validate
    publish to world model
```

The main loop never waits 200 ms for OCR. It always uses the most recent successful reading.

---

## 12. Reading numbers checklist

- [ ] Crop tight around the number, nothing else.
- [ ] Find the crop via anchor or resolution-scaled reference box.
- [ ] Check the region hash before OCR.
- [ ] Preprocess (grayscale, upscale, threshold, invert if needed, pad).
- [ ] Use the right OCR language pack; verify it exists at startup.
- [ ] Parse suffixes (K/M/B/T), separators, and signs.
- [ ] Fix common OCR confusions (`O`→`0` etc.) *after* suffix parsing.
- [ ] Validate against last value, physical limits, digit count.
- [ ] Median/smooth over the last few good reads.
- [ ] Never throw on a bad read; keep the last known value.
- [ ] Log the raw OCR string next to the parsed value for debugging.
- [ ] Understand the precision limit of abbreviated numbers and design around it.

---

## Sources

- Windows.Media.Ocr docs: <https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr>
- OCR engine benchmark on game screens (Windows OCR 137 ms; Tesseract poor; PaddleOCR slow): <https://qiita.com/nabemax/items/9f149a8c35dac5b20e81>
- Preprocessing experiment showing limits of upscaling/contrast: <https://zenn.dev/hidecode365/articles/d0c4b5cd57ccc5>
- Windows OCR preprocessing pipeline in Rust (grayscale, bilinear upscale, Sauvola): <https://github.com/wangkang1133/desktop-touch-mcp/blob/main/src/image_processing.rs>
- Dig Tool OCR implementation (Windows Runtime OCR): <https://github.com/iamnotbobby/dig-tool/blob/main/docs/TECHNICAL.md>
- Natro digit bitmaps for sticker stack counts: <https://deepwiki.com/NatroTeam/NatroMacro/6.2-image-recognition-system>
- GRP mini-game automation (contour + digit templates = "lightweight OCR"): <https://github.com/DataGoblin/GRP-MiniGame-Automation>
- Ultimate Macro OCR requirements: <https://ultmacro.xyz/guide/>
- Tesseract page segmentation modes: <https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html>

---

*Next: [05-window-screen-and-scaling.md](05-window-screen-and-scaling.md)*
