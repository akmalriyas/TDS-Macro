"""Discord Webhook integration for TDS Macro alerts, stats, and run results."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

GREEN = 0x2FE08A
RED = 0xF2113D
AMBER = 0xF5B301
NEUTRAL = 0x2B2D31


def send_discord_webhook(
    url: str,
    *,
    title: str,
    description: str = "",
    color: int = RED,
    fields: Optional[list[dict[str, Any]]] = None,
    footer: str = "Flare Macro",
) -> tuple[bool, str]:
    """Send a single Discord embed to the configured webhook URL."""
    if not url or not url.startswith("https://discord.com/api/webhooks/"):
        return False, "Invalid Discord webhook URL"

    embed: dict[str, Any] = {
        "title": title,
        "color": color,
        "footer": {"text": footer},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = fields

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"embeds": [embed]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "FlareMacro-TDS"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            if resp.status in (200, 204):
                return True, "Webhook sent successfully"
            return False, f"Discord returned HTTP status {resp.status}"
    except Exception as e:
        return False, str(e)


def _field(name: str, value: str) -> dict[str, Any]:
    return {"name": name, "value": value, "inline": True}


def _mmss(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def send_run_result_webhook(
    url: str,
    *,
    task_name: str,
    map_name: str,
    gamemode: str,
    outcome: str,
    wave_reached: int,
    coins_earned: int,
    xp_earned: int,
    duration_s: float,
    total_coins: int = 0,
    coins_per_hr: float = 0.0,
) -> tuple[bool, str]:
    """Post a short match result: outcome, coins, time."""
    won = outcome.lower() in ("victory", "triumph", "win")
    return send_discord_webhook(
        url,
        title="Triumph" if won else "Defeat",
        description=f"{map_name} · {gamemode} · Wave {wave_reached}/20",
        color=GREEN if won else RED,
        fields=[
            _field("Coins", f"+{coins_earned:,}"),
            _field("Time", _mmss(duration_s)),
            _field("Per hour", f"{coins_per_hr:,.0f}"),
        ],
    )


def send_error_webhook(
    url: str,
    *,
    task_name: str,
    error_message: str,
    context: str = "",
) -> tuple[bool, str]:
    """Post a short error notice. The macro keeps running and retries."""
    msg = error_message.strip()[:300] or "Unknown error"
    desc = f"{context}\n```{msg}```" if context else f"```{msg}```"
    return send_discord_webhook(
        url,
        title="Error — retrying",
        description=desc,
        color=AMBER,
    )


def send_hourly_webhook(
    url: str,
    *,
    session_duration_s: float,
    runs_completed: int,
    wins: int,
    coins_farmed: int,
    coins_per_hr: float,
    current_wave: Optional[int] = None,
) -> tuple[bool, str]:
    """Post a short session summary."""
    h = int(session_duration_s // 3600)
    m = int((session_duration_s % 3600) // 60)
    return send_discord_webhook(
        url,
        title="Hourly summary",
        description=f"Running for {h}h {m:02d}m",
        color=NEUTRAL,
        fields=[
            _field("Coins", f"+{coins_farmed:,}"),
            _field("Per hour", f"{coins_per_hr:,.0f}"),
            _field("Wins", f"{wins} / {runs_completed}"),
        ],
    )
