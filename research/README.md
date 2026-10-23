# Roblox Game Macro Research

**What this folder is:** everything I found about how screen-reading game macros are built, focused on Roblox games like Tower Defense Simulator (TDS) and Bee Swarm Simulator (BSS), and on tools like Revolution Macro.

**Who it's for:** a human who wants to understand it, and an AI agent who has to build one later. Every doc is written in plain language, with real numbers, formulas, and code you can copy.

**Date of research:** October 2026.

---

## The 30-second summary

A macro like this is not magic and it is not "AI". It is a loop:

```
look at the screen  ->  understand what is there  ->  decide  ->  move mouse / press key  ->  repeat
```

Five separate problems have to be solved:

| # | Problem | Doc |
|---|---------|-----|
| 1 | Grab the game's pixels fast enough | [02-screen-capture.md](02-screen-capture.md) |
| 2 | Find buttons, icons and text on those pixels | [03-finding-things-on-screen.md](03-finding-things-on-screen.md) |
| 3 | Read numbers like money, wave, pollen | [04-reading-numbers.md](04-reading-numbers.md) |
| 4 | Know *where* things are on any screen size | [05-window-screen-and-scaling.md](05-window-screen-and-scaling.md) |
| 5 | Click and type in a way the game accepts | [06-input-simulation.md](06-input-simulation.md) |

Then you wrap that in a program that doesn't crash at 3am:

| # | Topic | Doc |
|---|-------|-----|
| 6 | Program structure, state machine, config, logging | [07-macro-architecture.md](07-macro-architecture.md) |
| 7 | What makes Revolution's UI good and what to copy | [08-ui-design-revolution.md](08-ui-design-revolution.md) |
| 8 | Game-specific notes for TDS and BSS | [09-game-notes-tds-bss.md](09-game-notes-tds-bss.md) |
| 9 | A practical build plan | [10-build-plan.md](10-build-plan.md) |
| 10 | Bans, ToS, anti-cheat reality | [11-safety-and-tos.md](11-safety-and-tos.md) |
| 11 | Glossary of every term used | [12-glossary.md](12-glossary.md) |
| 12 | Codebase audit, 23-screenshot coordinate map & Dead Ahead strategy | [13-codebase-status-and-strategy-audit.md](13-codebase-status-and-strategy-audit.md) |
| 13 | Iteration 1: CLI & autonomous engine specification (`tds_macro/`) | [14-cli-and-engine-implementation-spec.md](14-cli-and-engine-implementation-spec.md) |
| 14 | Iteration 2: Control-panel UI, hourly charts & transparent HUD overlay | [15-ui-control-panel-and-overlay-spec.md](15-ui-control-panel-and-overlay-spec.md) |
| 15 | `open-computer-use` (`ocu`) MCP server setup & integration | [16-open-computer-use-mcp-setup.md](16-open-computer-use-mcp-setup.md) |

---

## The one thing most people get wrong

Most beginners think the hard part is clicking the right pixel.

It isn't. The hard part is **knowing when your understanding of the screen is wrong**.

A macro that thinks money is "1.2M" when it's actually "12M" will happily spend 10x too much. A macro that misses a "Play Again" button will sit in a dead lobby for 8 hours. A macro that clicks 3 pixels off because Windows was at 125% scaling will fail on every PC except the developer's.

So every good macro has three habits:

1. **Verify before acting.** Find the button, then check you actually found it (confidence score), then click.
2. **Verify after acting.** Did the screen change? If not, the click failed. Retry, don't assume.
3. **Have a fallback and a timeout.** Every wait has a maximum. Every state can recover.

Revolution's own docs are a great example of this mindset: they list ~15 things that can break detection (HDR, scaling, colour profile, camera mode, FPS) and give a specific fix for each. That is not over-engineering; that is what shipping a macro to thousands of random PCs actually requires.

---

## Quick answers to the questions you asked

**"How does it find out the amount of money from reading the screen?"**
Two ways, usually combined:

- **OCR** on a small cropped box around the money label (Windows OCR or Tesseract). Slow-ish (100–300 ms) but reads any number.
- **Digit templates**: crop the number, split it into individual characters, and compare each character against 10 stored images (0–9). Much faster and immune to font weirdness, but you must capture templates per font/size.

Then you parse `1.2K` / `3.4M` / `12,345`, sanity-check the value against the last reading, and smooth it. Full detail in [04-reading-numbers.md](04-reading-numbers.md).

**"How does it handle different screen sizes?"**
It never uses absolute screen coordinates. It gets the Roblox window's client rectangle, converts everything to window-relative coordinates, and scales by `client_width / reference_width`. Most serious macros *also* enforce a minimum resolution, 16:9 aspect ratio, and 100% Windows display scaling, because that removes 90% of the bugs. See [05-window-screen-and-scaling.md](05-window-screen-and-scaling.md).

**"Why is Revolution's UI good?"**
Because it is task-shaped, not code-shaped. You pick a field, pick a pattern, press start. Every feature is a card with an on/off switch and a one-line summary. It shows live status, a timestamped log with named errors, a detection overlay, and a pre-run check that refuses to start if your display settings will break it. See [08-ui-design-revolution.md](08-ui-design-revolution.md).

**"Is it image detection or AI?"**
Revolution is now a hybrid: classic screen reading plus small trained models for token detection. Classic macros are 100% template matching + colour checks + OCR. Both are "read the screen, move the mouse". Neither injects into Roblox. See [01-the-big-picture.md](01-the-big-picture.md).

---

## How to read this folder

- Building something? Read 01 → 02 → 03 → 05 → 06 → 07, then 10.
- Just curious how money reading works? Read 04.
- Designing the app window? Read 08.
- Want TDS specifics? Read 09.
- Worried about bans? Read 11 first.

---

## Sources used

These are the main public references behind the findings. Specific links are repeated at the bottom of each doc.

- Revolution Macro docs — <https://revolutionmacro.com/docs/>
- Revolution detection troubleshooting — <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>
- Natro Macro source (open-source BSS macro, AHK v2) — <https://github.com/NatroTeam/NatroMacro>
- Ultimate Macro for TDS (AHK v2 + OCR) — <https://ultmacro.xyz/guide/> and <https://github.com/DarksenDev/tds-macro>
- AutoHotkey v2 docs: ImageSearch, DPI scaling — <https://www.autohotkey.com/docs/v2/>
- OpenCV template matching docs — <https://docs.opencv.org/>
- Windows.Graphics.Capture docs — <https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture>
- Windows.Media.Ocr docs — <https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr>
- OBS PR adding Roblox `WINDOWSCLIENT` auto-WGC capture — <https://github.com/obsproject/obs-studio/pull/12348>

---

*Next: [01-the-big-picture.md](01-the-big-picture.md)*
