"""Discord Webhook integration for TDS Macro alerts, stats, and run results."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_LOGO_URL = "https://raw.githubusercontent.com/akmalriyas/TDS-Macro/main/tds_macro/assets/logo.png"

DEFAULT_AUTHOR = {
    "name": "FLARE // TDS AUTOMATION",
    "icon_url": DEFAULT_LOGO_URL,
}


def send_discord_webhook(
    url: str,
    *,
    title: str,
    description: str,
    color: int = 0xF2113D,  # Flare neon crimson accent
    fields: Optional[list[dict[str, Any]]] = None,
    author: Optional[dict[str, str]] = None,
    footer: str = "Flare Macro • TDS Autonomous Engine",
) -> tuple[bool, str]:
    """Send a rich Discord embed to the configured webhook URL."""
    if not url or not url.startswith("https://discord.com/api/webhooks/"):
        return False, "Invalid Discord webhook URL"

    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields or [],
        "footer": {"text": footer, "icon_url": DEFAULT_LOGO_URL},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    auth = author if author is not None else DEFAULT_AUTHOR
    if auth:
        embed["author"] = auth

    payload = {"embeds": [embed]}

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "FlareMacro-TDS/2.16",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            if resp.status in (200, 204):
                return True, "Webhook sent successfully"
            return False, f"Discord returned HTTP status {resp.status}"
    except Exception as e:
        return False, str(e)


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
    """Send a refined post-match run summary card to Discord."""
    is_victory = outcome.lower() in ("victory", "triumph", "win")
    status_label = "TRIUMPH" if is_victory else "DEFEAT"
    title = f"MATCH COMPLETED — {status_label}"
    color = 0x10B981 if is_victory else 0xF2113D

    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    time_str = f"{mins}m {secs:02d}s"

    description = f"**{map_name}** • `{gamemode}` (Solo)\nMatch concluded in **`{time_str}`** with outcome **`{status_label}`**."

    fields = [
        {"name": "Wave Cleared", "value": f"`{wave_reached} / 20`", "inline": True},
        {"name": "Coins Earned", "value": f"**`+{coins_earned:,}`**", "inline": True},
        {"name": "XP Earned", "value": f"**`+{xp_earned:,}`**", "inline": True},
        {"name": "Match Time", "value": f"`{time_str}`", "inline": True},
        {"name": "Efficiency", "value": f"`{coins_per_hr:,.0f}` / hr", "inline": True},
        {"name": "Session Balance", "value": f"`{total_coins:,}` coins", "inline": True},
    ]

    return send_discord_webhook(
        url,
        title=title,
        description=description,
        color=color,
        fields=fields,
    )


def send_error_webhook(
    url: str,
    *,
    task_name: str,
    error_message: str,
    context: str = "Gameplay Loop",
) -> tuple[bool, str]:
    """Send an alert to Discord when the macro encounters a failure or exception."""
    title = "SYSTEM ALERT — RUNTIME EXCEPTION"
    description = f"The automation engine encountered an interruption during **{task_name}**."
    fields = [
        {"name": "Routine", "value": f"`{task_name}`", "inline": True},
        {"name": "Context", "value": f"`{context}`", "inline": True},
        {"name": "Action Taken", "value": "`Auto-recovering`", "inline": True},
        {"name": "Diagnostic Log", "value": f"```python\n{error_message[:450]}\n```", "inline": False},
    ]
    return send_discord_webhook(
        url,
        title=title,
        description=description,
        color=0xF59E0B,
        fields=fields,
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
    """Send an hourly performance summary card to Discord."""
    title = "HOURLY PERFORMANCE REPORT"
    hours = max(1, int(session_duration_s // 3600))
    time_str = f"{int(session_duration_s // 3600)}h {int((session_duration_s % 3600) // 60):02d}m"
    losses = max(0, runs_completed - wins)
    win_rate = f"{(wins / runs_completed * 100):.0f}%" if runs_completed else "—"
    wave_str = f"Wave {current_wave}/20" if current_wave is not None else "In Lobby"

    description = f"Autonomous session telemetry across the past **{hours} hour(s)**."

    fields = [
        {"name": "Session Time", "value": f"`{time_str}`", "inline": True},
        {"name": "Matches", "value": f"`{runs_completed}` ({wins}W · {losses}L)", "inline": True},
        {"name": "Win Rate", "value": f"**`{win_rate}`**", "inline": True},
        {"name": "Total Farmed", "value": f"**`+{coins_farmed:,}`** coins", "inline": True},
        {"name": "Pacing Rate", "value": f"**`{coins_per_hr:,.0f}`** / hr", "inline": True},
        {"name": "Macro State", "value": f"`{wave_str}`", "inline": True},
    ]
    return send_discord_webhook(
        url,
        title=title,
        description=description,
        color=0x38BDF8,
        fields=fields,
    )
