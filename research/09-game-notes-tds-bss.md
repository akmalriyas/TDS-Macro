# 09 — Game Notes: TDS, Bee Swarm, and Friends

> **If you only remember one thing:** the macro architecture is the same for every game. What changes is the **list of things you look for** and the **decision loop**. Write those down before you write code.

---

## 1. The common shape of every Roblox farm game

Almost every game in this genre has the same four screens:

```
LOBBY  ->  LOADING  ->  MATCH  ->  RESULTS
  ^                                  │
  └──────────────────────────────────┘
```

And the same four things to read:

| Category | Examples | Technique |
|---|---|---|
| **Navigation** | Play, Ready, Play Again, Back, Close | Template match |
| **Resources** | cash, coins, gems, honey, pollen | OCR or digit templates |
| **Progress** | wave, round, level, quest count | OCR + monotonic validation |
| **State** | "in lobby", "dead", "disconnected" | Pixel signature / colour |

If you build a clean layer for those four, porting to a new game is mostly swapping assets and strategy data.

---

## 2. Tower Defense Simulator (TDS)

### 2.1 The loop

```
1. Join lobby
2. Vote for map / select difficulty
3. Equip loadout (towers must be in the right slots)
4. Press Ready
5. Wait for match start (intermission countdown)
6. Place towers at specific positions during early waves
7. Upgrade towers at specific waves
8. Use abilities (DJ, Commander, etc.) on cooldown
9. Match ends (Victory/Defeat)
10. Read rewards, press Play Again
11. Repeat
```

### 2.2 What to read

| Value | Where | Method | Notes |
|---|---|---|---|
| Cash | Top HUD | OCR / digits | Changes constantly; needs validation |
| Wave | Top HUD | OCR / digits | Monotonic; use as the clock |
| Health / lives | Top HUD | OCR / bar | Optional |
| Map name | Vote screen / loading | Template or OCR | For "is this the map I wanted?" |
| Difficulty | Vote screen | Template | Normal / Intermediate / Fallen etc. |
| Tower placement validity | Ground marker | Colour | Red = can't place, green/white = can |
| Tower panel | Right side | Template | "Upgrade", "Sell", "Targeting" buttons |
| Wave rewards | Results screen | OCR | Coins, gems, XP |
| Buttons | Varies | Template | Play, Ready, Play Again, Reconnect, Vote |

### 2.3 What to click

- Map vote button (or the map tile).
- Difficulty selector.
- Tower slots in the loadout bar.
- Ground positions for placement.
- Upgrade path buttons (usually 2 paths × 4-5 levels).
- Ability buttons / hotkeys.
- Play Again / Restart.

### 2.4 The strategy problem

TDS is not a "click one button" game. A winning run is a **sequence of placements and upgrades timed to waves**. Two ways to handle that:

#### A. Record and replay (most common)

1. The user plays one match normally.
2. The macro records `(wave, action, target)` tuples.
3. On replay, it waits for the wave number to match, then performs the action.

```
wave 1   place Soldier at (820, 540)
wave 2   place Farm at (900, 600)
wave 3   upgrade Soldier -> level 2
wave 5   place Farm #2
wave 7   upgrade Farm -> level 2
wave 10  ability Commander
...
```

This is how Luxi's TDS Macro and Ultimate Macro work: record a `.strat`, replay it, rotate between strategies.

**Why wave-based and not time-based?** Because a slow PC, a lag spike, or a longer intermission would desynchronise a timed script. Waves are a game-provided clock. Ultimate Macro explicitly detects game end, checks the map, and uses Restart/Play Again.

#### B. Declarative strategy (more work, more robust)

A data file describes intent:

```json
{
  "map": "Meadow",
  "difficulty": "Intermediate",
  "loadout": ["Soldier", "Farm", "Sniper", "DJ"],
  "steps": [
    {"at_wave": 1,  "do": "place", "tower": "Soldier", "spot": "A1"},
    {"at_wave": 2,  "do": "place", "tower": "Farm",    "spot": "B2"},
    {"at_wave": 3,  "do": "upgrade", "tower": "Soldier", "path": 0, "times": 2},
    {"at_wave": 10, "do": "ability", "name": "DJ"},
    {"every_wave": true, "do": "ability_if_ready", "name": "Commander"}
  ]
}
```

Spots are named, calibrated positions (screen coordinates relative to the client), not raw pixels in the file.

This is easier to edit and share than a recorded timeline, but harder to author. Most tools start with recording and add declarative later.

#### C. Vision-driven (hardest)

Detect enemies, decide where to place, react to leaks. Very few TDS macros do this. Not recommended for v1.

### 2.5 Camera alignment (the sneaky hard part)

Tower placement clicks the **ground**, so the click lands at a world position that depends on the camera angle. If the camera drifted, your "perfect spot" is now a different place.

Solutions, in order of reliability:

1. **Reset the camera before placing.** Many games have a camera reset key or you can re-enter a known state.
2. **Require a fixed camera mode.** Ultimate Macro requires "Camera Mode: Classic".
3. **Check orientation with a visual landmark** before the first placement.
4. **Place by UI, not ground**, where possible (some games let you drag from a tower button).
5. **Verify placement succeeded** (tower appears / cash decreased) and retry.

Ultimate Macro's docs mention that TDS doesn't have a Bee-Swarm-style camera reset button, so their macro rotates the camera manually after respawn if the orientation is wrong.

### 2.6 TDS settings that make the UI deterministic

From Ultimate Macro's setup guide — these are effectively requirements for reliable detection:

| Setting | Value | Why |
|---|---|---|
| Max frame rate | 60 | Predictable animation timing |
| Camera mode | Classic | Placement assumes it |
| Graphics mode | Manual | Auto changes quality mid-session |
| UI navigation | Toggle enabled | Menu handling |
| TDS UI scale | **Large** | Reference images captured at this scale |
| Screen shake | Disabled | Shake moves the UI mid-frame |
| Prefer vertical upgrades | Enabled | Fixes upgrade panel layout |
| Dialog | Disabled | Dialogs cover the HUD |
| Show tower options | Enabled | Needed to upgrade/sell/target |
| Custom fonts | None | Altered letterforms break OCR |

Note how many of these are **UI-layout** settings. The macro isn't fighting the game; it's asking the player to make the game's UI predictable. That's a legitimate and powerful design move. Offer an "Auto-configure" button that applies them and restores the originals afterwards.

### 2.7 TDS failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Tower placed in the wrong spot | Camera drifted | Reset camera; verify placement |
| Upgrade button not found | Panel layout changed (vertical upgrades off) | Enforce the setting |
| Wrong map | Vote failed / random | Detect map name, leave and requeue |
| Stuck in lobby | "Ready" not clicked / vote screen changed | Detect and retry |
| Match never ends | Towers too weak / strategy outdated | Stop after N minutes, requeue |
| Cash misread | OCR confusion | Validate + smooth; use thresholds |
| Dialog blocks the HUD | A popup appeared | Detect and close it |
| Disconnected overnight | Network | Rejoin flow + retry limit |

### 2.8 Extras worth building (they're in the good macros)

- **Auto-equip** the loadout before joining.
- **Timescale** support (1.5× / 2× tickets) — the macro must know that waves come faster.
- **Strategy rotation** — alternate strategies every N runs or minutes.
- **Playtime / daily rewards** — visit the lobby and claim them.
- **Discord webhook** — send run results, currency, screenshots.
- **VIP/private server** support.
- **Split-path towers** (Pursuit, Hacker, etc.) need special upgrade handling.

---

## 3. Bee Swarm Simulator (BSS)

BSS is a very different problem: it's continuous movement in a 3D world, not a menu-driven match.

### 3.1 The loop

```
1. Join server, claim a hive (blue/red/white)
2. Walk to a field
3. Gather pollen (walk patterns / collect tokens)
4. Return to hive when backpack is full
5. Convert pollen to honey
6. Claim quests, use dispensers, manage planters
7. Repeat, occasionally hop servers for specific bosses
```

### 3.2 What to read

| Value | Method | Notes |
|---|---|---|
| Field name / location | Template/OCR | Or infer from the route |
| Pollen % | OCR or bar | "Backpack 98%" triggers return |
| Honey | OCR (often abbreviated) | Main progress metric |
| Hive slot / colour | Template or OCR | "Detection Failed: Hive" is a known error |
| Quest progress | OCR | Multiple quests; scrolling list |
| Buffs / nectars | Icon templates | Small, many, easy to miss |
| Tokens on the ground | Colour blobs or ML model | The core of "AI gather" |
| Sprinklers | Template | Natro has dedicated sprinkler assets |
| Day/night | Template set | Natro has `nm_image_assets/night/` |
| Dispensers | Templates | Collect loot without resetting |

### 3.3 The two gathering strategies

#### A. Fixed patterns (classic)

A pattern is a path through a field: rectangle, bowl, kettle, skillet, etc. The macro walks the same route every time.

Revolution's field config is a good example of what a pattern needs:

```json
{
  "position": "top-left",
  "length": 4,
  "width": 4,
  "distance": 4,
  "yaw": 3,
  "backpackPercent": 98,
  "seconds": 600,
  "walkReturn": true,
  "driftComp": true,
  "gatherPattern": "AI Gather",
  "field": "pinetree"
}
```

Note the practical parameters: **yaw** (camera angle), **drift compensation** (correct for your character sliding), **walk return** (walk back to the hive instead of teleporting), **backpack %** (when to leave).

Fixed patterns are simple, deterministic, and still work. Their weakness: they assume tokens spawn evenly, so they waste time in empty spots.

#### B. Token-driven / "AI gather"

Instead of a fixed path:

1. Detect tokens on screen (colour blobs, template matching, or a model).
2. Build a list of candidates with positions and value.
3. Score each: `value / distance`, adjusted by buffs and expiry.
4. Walk to the best one.
5. Repeat.

Revolution's AI Studio is exactly this, and its docs are explicit about the separation:

> "AI Gather isn't just another 'pattern' that runs fixed movements, but rather a framework that collects data and dynamically chooses what actions to take based on that data."
>
> "A movement profile decides what to do with the tokens the macro can see — it doesn't change what the macro sees or when it gathers."

That separation is a useful architectural lesson: **detection and scoring are different systems**. Detection says "there is a token at (x, y) worth 5". Scoring says "given my buffs and distance, go to this one". You can improve one without touching the other.

### 3.4 Movement in BSS

- Movement is camera-relative: `W` moves in the direction the camera faces.
- Patterns are defined in terms of yaw + distance + repetitions.
- Drift is real: your character doesn't move exactly the distance you expect. `driftComp` exists for this reason.
- Cannons, portals, and teleporters shortcut routes.
- Getting stuck on geometry is common; a "stuck detector" (no position change) plus a jump or re-route is necessary.

### 3.5 BSS failure modes

| Symptom | Cause | Fix |
|---|---|---|
| "Detection Failed: Hive" | Hive slot not visible / wrong movespeed | Set movespeed correctly, rejoin, claim method "Check" |
| Walking in circles | Wrong camera/movement mode | Camera Classic, Movement Default |
| Stuttering | Player movespeed mismatch / low FPS | Match movespeed, enable high alignment |
| Nectars/quests not detected | Display/capture settings | Switch capture mode, check colour profile |
| Planter scroll fails | Inventory layout | Dedicated scroll handling |
| Missed tokens | Detection model/overlay | Turn on overlay, check boxes |

### 3.6 What's transferable to TDS

- The **overlay** as a diagnostic.
- The **pre-run environment check**.
- The **capture mode fallback**.
- The **separation of detection from decision**.
- The **named error** style.

---

## 4. Other Roblox game types

### 4.1 Clicker / simulator (Pet Sim, clicker games)

- Mostly clicking one spot rapidly.
- Detection is minimal: is the button there? is the inventory full?
- The main challenges are anti-AFK and rate limits.
- A simple loop + colour checks is enough.

### 4.2 Fishing / minigame games (Fisch, etc.)

- A minigame bar where you must keep a marker inside a moving zone.
- Detection: find the bar, find the marker and the target zone (colour).
- Control: click/hold or press a key based on the delta.
- This is a **control loop**, not a state machine: sample at 20–30 Hz, compute error, act.

```python
error = marker_x - zone_center
if abs(error) > deadzone:
    press_and_hold("d" if error < 0 else "a", duration=0.03)
```

- OCR is used for the weight/value at the end.

### 4.3 Obby / parkour

- Camera + movement, no UI.
- Hard to do with screen reading; usually requires memory reading (which we're not doing).
- Skip.

### 4.4 Trading / marketplace games

- Mostly UI navigation + OCR of item names and values.
- High risk: a misread causes a bad trade.
- If you build one, require **confirmation** and never auto-accept without verification.

---

## 5. A game-agnostic detection config

Notice how similar the data is across games. You can use one schema:

```json
{
  "game": "tds",
  "reference_resolution": [1920, 1080],
  "regions": {
    "cash":   {"box": [1460, 18, 220, 52], "type": "number", "suffixes": true},
    "wave":   {"box": [930, 14, 60, 40],   "type": "integer", "min": 0, "max": 100},
    "map":    {"box": [40, 900, 300, 40],  "type": "text"}
  },
  "templates": {
    "play":        {"file": "play.png",        "threshold": 0.88},
    "ready":       {"file": "ready.png",       "threshold": 0.88},
    "play_again":  {"file": "play_again.png",  "threshold": 0.88},
    "reconnect":   {"file": "reconnect.png",   "threshold": 0.85},
    "close":       {"file": "close.png",       "threshold": 0.90}
  },
  "states": {
    "lobby":   {"any": ["play", "ready"]},
    "results": {"any": ["play_again"]},
    "error":   {"any": ["reconnect"]}
  }
}
```

Then the core code is game-agnostic; only this file changes.

---

## 6. Which game should you start with?

| Game | Difficulty | Why |
|---|---|---|
| **Simple clicker** | ★☆☆☆☆ | One button, one loop. Good for learning capture + input. |
| **TDS** | ★★★☆☆ | Menu-driven, wave clock, but camera + placement + many UI states. |
| **BSS** | ★★★★★ | 3D movement, tokens, many systems, environment-sensitive. |

If this is your first macro: build the clicker, then TDS. BSS is a much bigger project — it's why Revolution is a whole company-scale app with AI models, and why Natro has years of accumulated assets.

---

## 7. Game notes checklist

- [ ] You can list every screen the macro will encounter.
- [ ] You can list every value it must read, with its precision limit.
- [ ] You can list every button it must click, with its detection method.
- [ ] You know which game settings must be enforced.
- [ ] You know what the "clock" is (wave number, timer, or nothing).
- [ ] You know how the camera behaves and how to reset it.
- [ ] You have a recovery plan for disconnect / wrong map / stuck.
- [ ] You have a strategy format (recorded timeline or declarative).
- [ ] You have an overlay to verify detection.

---

## Sources

- Ultimate Macro (TDS) guide — settings, strategy recording, rotation, recovery, timescale, Discord webhook: <https://ultmacro.xyz/guide/>
- Ultimate Macro GitHub — features: <https://github.com/DarksenDev/tds-macro>
- Luxi TDS macro overview — record/replay, F4/F5, strategy codes: <https://robloxmacros.com/tds-macro/>
- Revolution — field config JSON, patterns, drift compensation: <https://revolutionmacro.com/docs/gathering/set-up-ai-gather/>
- Revolution — AI Gather and AI Studio separation of detection vs scoring: <https://revolutionmacro.com/docs/ai-studio/what-ai-studio-is/>
- Revolution — detection failures (hive, nectar, quests): <https://revolutionmacro.com/docs/troubleshooting/detection-problems/>
- Natro Macro — BSS asset categories (sprinkler, night, memory match, sticker stack, quests): <https://github.com/NatroTeam/NatroMacro>
- Natro image recognition system: <https://deepwiki.com/NatroTeam/NatroMacro/6.2-image-recognition-system>
- Fisch appraisal macro — OCR box calibration: <https://robloxtutorial.com/best-roblox-fisch-macro/>

---

*Next: [10-build-plan.md](10-build-plan.md)*
