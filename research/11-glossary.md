# 12 — Glossary

Every term used in this folder, in plain language.

---

## A

**Anchor** — A stable, always-visible UI element (a logo, a panel corner) used as a reference point. Instead of hardcoding where the money label is, you find the anchor and compute the money label as `anchor + offset`. Makes the macro survive window moves and resolution changes.

**Anti-AFK** — A periodic harmless input (jump, small camera move) sent every few minutes so the game doesn't kick the player for inactivity.

**Ayymmetry / aspect ratio** — The ratio of width to height. 1920×1080 is 16:9. 2560×1080 is 21:9 (ultrawide). Macros usually require 16:9 because UI layouts differ on other ratios.

---

## B

**Base64** — A way to store binary data (like a PNG) as plain text. Natro stores its image templates as base64 strings inside `.ahk` files so there are no external image files to lose.

**BGR / RGB** — Colour channel order. OpenCV uses BGR; most other tools use RGB. Getting this backwards makes red and blue swap.

**Bezier curve** — A smooth curve defined by control points. Used to make mouse movement look human instead of a straight teleport.

**Binarization** — Converting an image to pure black and white. Makes text and shapes easier to match and easier for OCR.

**BitBlt** — A Windows GDI function that copies a rectangle of pixels from one device context to another. The classic screenshot method. Often fails on hardware-accelerated game windows.

**Blob** — A connected group of same-coloured pixels. "Find the blobs" is how you segment digits or tokens.

**BSS** — Bee Swarm Simulator, a Roblox game.

---

## C

**Canny** — An edge-detection algorithm in OpenCV. Sometimes gives more stable template matching than raw grayscale, because it ignores colour and brightness.

**Capture** — Taking a screenshot of a region or window.

**Client area** — The drawable part of a window, excluding the title bar and borders. `GetClientRect` returns its size; `ClientToScreen` gives its screen position. **All game coordinates should be client-relative.**

**ClientToScreen** — Win32 function that converts a client-relative point to a screen point by adding the window's client origin.

**Cooldown** — A minimum time before the same action can happen again. Prevents double-clicks and spam.

**Connected components** — An algorithm that labels groups of touching pixels. `cv2.connectedComponentsWithStats` gives you a bounding box per blob. Used for digit segmentation.

**ControlClick / ControlSend** — AutoHotkey commands that send messages directly to a control. **They do not work in Roblox.**

**Crop** — The rectangular sub-image you actually analyse. Smaller crop = faster detection and fewer false positives.

---

## D

**DC (Device Context)** — A Windows handle representing something drawable (a window, a bitmap, the screen). GDI functions draw into or copy from DCs.

**Digit templates** — Storing images of `0`–`9` and matching each character of a number against them. A fast, font-specific alternative to OCR.

**DirectInput** — An older Microsoft input API that games use to read keyboards and mice directly, often bypassing normal window messages. Why `ControlClick` fails and why keys need to be held.

**DPI (dots per inch)** — Windows' scaling setting. 96 DPI = 100%, 120 = 125%, 144 = 150%. Affects whether coordinates are logical or physical pixels.

**DPI awareness** — Whether your app tells Windows "don't scale my coordinates". A DPI-unaware app gets logical coordinates while captures return physical pixels, causing offsets.

**Drift compensation** — In movement macros, correcting for the fact that a character doesn't travel exactly the intended distance (collisions, slopes, lag).

**DXGI Desktop Duplication** — A fast Windows API for capturing the desktop via the GPU. Used by `dxcam`. Cannot capture occluded windows.

---

## E

**External** — A program that runs outside the game process, reading the screen and sending input. The opposite of injection. What this folder is about.

---

## F

**FindText** — A popular AutoHotkey library that encodes an image as a black/white text string and searches for it. Faster than `ImageSearch` and needs no image files.

**Fitts's law** — A model of human movement time based on distance and target size. Used by humanisation libraries to make cursor movement timing realistic.

**Frame** — One still image from the screen.

---

## G

**GDI / GDI+** — Windows' older 2D graphics APIs. Used for screenshots and for drawing/decoding images in AutoHotkey (`Gdip_All.ahk`).

**Grayscale** — Converting colour to shades of grey. Template matching and OCR usually work better and faster on grayscale.

**GUI scale / UI scale** — An in-game setting that changes the size of game UI elements. Changes template sizes and text metrics, so macros often require a specific value (e.g. TDS "Large").

---

## H

**HDR** — High Dynamic Range. Changes how colours are rendered and captured. Macros usually require it off.

**Hotkey** — A key combination that works globally, even when the game is focused. Used for start/pause/stop.

**HSV** — Hue, Saturation, Value. A colour space that separates "what colour" from "how bright". Better than RGB for colour detection under changing lighting.

**HWND** — A handle to a Windows window. You need it to get the client rect, focus the window, and check it's alive.

---

## I

**ImageSearch** — AutoHotkey's built-in template matching command. Slower than FindText, needs external image files, DPI-sensitive.

**Injection** — Loading code into another process. What cheats do and what anti-cheat targets. **Never do this.**

**InRange** — OpenCV function that creates a mask of pixels within a colour range. The basis of colour ratio detection.

---

## J

**Jitter** — Small random variation added to timings or positions so actions don't look perfectly mechanical.

---

## L

**Latency** — The delay between an event (a button appearing) and your reaction (clicking it). Composed of capture, processing, decision, and input time.

**Logical pixels** — The coordinate space Windows shows to DPI-unaware apps. At 150% scaling, a 1920-wide screen is 1280 logical pixels.

---

## M

**Mask** — A black/white image that tells an algorithm which pixels to consider. Used for transparent templates and colour isolation.

**Median filter** — Taking the middle value of the last N readings to smooth out outliers. Useful for OCR readings.

**Minimum-jerk** — A model of human reaching movement where the hand accelerates and decelerates smoothly. Used in high-end humanisation.

**MSS** — A fast Python screenshot library. Simple and reliable, uses BitBlt under the hood.

**Multi-scale matching** — Trying a template at several sizes (0.8×, 0.9×, 1.0×, 1.1×) to handle different resolutions. Slower but more flexible.

---

## N

**NMS (non-maximum suppression)** — After finding many overlapping matches, keep only the best one in each area. Prevents 40 boxes on one coin.

**Nudge (Roblox)** — Moving the cursor 1 pixel after warping it, so the game registers a real mouse movement before the click.

---

## O

**OCR** — Optical Character Recognition. Converting an image of text into characters. Slow but flexible.

**OpenCV** — The standard open-source computer vision library. Template matching, colour masks, contours, resizing, edge detection.

**Otsu's method** — An automatic way to choose a binarization threshold by maximising separation between foreground and background.

---

## P

**Perception** — The part of the macro that turns pixels into meaning (capture → detect → read → world state).

**Pixel signature** — A fingerprint made of a few sampled pixel colours at fixed offsets. Very fast way to identify a screen.

**PostMessage / SendMessage** — Win32 functions that put a message in a window's queue. **Roblox ignores synthetic mouse messages.**

**PSM (page segmentation mode)** — A Tesseract setting describing the layout of the text (`7` = single line, `8` = single word, `6` = block).

---

## R

**Raw input** — A Windows input path that gives applications raw device data (WM_INPUT). Games use it for precise mouse look. It's why synthetic messages fail.

**Reference resolution** — The resolution you design against (usually 1920×1080). Runtime coordinates are scaled from it.

**Region** — A rectangular area of the screen. Also called ROI (region of interest).

**ROI** — Region of interest. The part of the image you actually analyse.

---

## S

**Scaling factor** — `client_width / reference_width`. Multiplies reference coordinates to get current coordinates.

**Screen coordinates** — Absolute position on the virtual desktop. Origin is the top-left of the primary monitor; can be negative on multi-monitor setups.

**SendInput** — The modern Win32 API for injecting keyboard and mouse events. Most reliable software input method for games.

**Soak test** — Running the macro for many hours to find leaks, drift, and rare failures.

**State machine** — A program structure with named states (`lobby`, `loading`, `game`, `recover`) and defined transitions. Makes long-running automation debuggable.

**Stable frames** — Requiring the same detection result for N consecutive frames before acting, to filter out flicker.

---

## T

**TDS** — Tower Defense Simulator, a Roblox game.

**Template** — A small reference image you search for on screen.

**Template matching** — Sliding a template over an image and computing a similarity score at each position.

**Threshold** — The score above which a match is accepted. Chosen from data, not guessed.

**Tesseract** — An open-source OCR engine. Good for documents, mediocre for stylised game fonts.

**Ticks** — The macro's internal clock unit. One tick = one loop iteration.

---

## U

**UDim2** — Roblox's data type for UI position/size, combining **scale** (percentage of parent) and **offset** (fixed pixels). Explains why Roblox UI doesn't scale evenly.

**UI scale** — See GUI scale.

---

## V

**Vision** — The perception subsystem. "Vision pipeline" = capture → preprocess → detect → interpret.

---

## W

**Watchdog** — A separate thread that checks the main loop is still running and restarts/stops it if it isn't.

**WGC (Windows.Graphics.Capture)** — A modern Windows API for capturing a specific window or monitor via the GPU. Works on occluded windows. Handles hardware-accelerated apps like Roblox better than BitBlt.

**Window coordinates** — Position relative to the top-left of the window frame (including title bar). Rarely what you want.

**World model / world state** — The macro's current beliefs about the game: which screen, what money, what wave, which buttons are visible.

**World space** — In 3D games, the game's internal coordinate system. Screen-reading macros can't access it directly; they infer it.

---

## X / Y / Z

**Yaw** — Rotation around the vertical axis (turning left/right). Used in movement patterns to specify camera direction.

**YOLO** — A family of fast object-detection neural networks. Used by some advanced macros; not needed for a first version.

---

*Back to [README.md](README.md)*
