"""Discord Webhook integration for TDS Macro alerts, stats, and run results."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from typing import Any, Optional


def send_discord_webhook(
    url: str,
    *,
    title: str,
    description: str,
    color: int = 0xFF1744,  # Neon Red accent
    fields: Optional[list[dict[str, Any]]] = None,
    footer: str = "Flare Macro - TDS",
) -> tuple[bool, str]:
    """Send a rich Discord embed to the configured webhook URL."""
    if not url or not url.startswith("https://discord.com/api/webhooks/"):
        return False, "Invalid Discord webhook URL"

    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "fields": fields or [],
                "footer": {"text": footer},
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        ]
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "FlareMacro-TDS/1.0",
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
    """Send a detailed post-match run summary card to Discord."""
    is_victory = outcome.lower() in ("victory", "triumph")
    title = f"🏆 TRIUMPH! — {task_name}" if is_victory else f"💀 DEFEAT — {task_name}"
    color = 0x22C55E if is_victory else 0xEF4444

    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    time_str = f"{mins}m {secs}s"

    fields = [
        {"name": "🗺️ Map", "value": map_name, "inline": True},
        {"name": "⚔️ Mode", "value": gamemode, "inline": True},
        {"name": "🌊 Wave", "value": f"{wave_reached} / 20", "inline": True},
        {"name": "💰 Coins Earned", "value": f"+{coins_earned:,}", "inline": True},
        {"name": "⭐ XP Earned", "value": f"+{xp_earned:,}", "inline": True},
        {"name": "⏱️ Time", "value": time_str, "inline": True},
        {"name": "⚡ Coins / Hour", "value": f"{coins_per_hr:,.0f} / hr", "inline": True},
        {"name": "🏦 Total Coins Farmed", "value": f"{total_coins:,}", "inline": True},
        {"name": "📊 Status", "value": "Queue Active — Looping", "inline": True},
    ]

    return send_discord_webhook(
        url,
        title=title,
        description=f"Completed run in `{time_str}` with outcome **{outcome.upper()}**.",
        color=color,
        fields=fields,
    )


def send_error_webhook(
    url: str,
    *,
    task_name: str,
    error_message: str,
    context: str = "Gameplay / Match Loop",
) -> tuple[bool, str]:
    """Send an alert to Discord when the macro encounters a failure or crash."""
    title = f"⚠️ MACRO ERROR — {task_name}"
    fields = [
        {"name": "📍 Context", "value": context, "inline": True},
        {"name": "⚙️ Status", "value": "Retrying / Recovering", "inline": True},
        {"name": "📋 Error Details", "value": f"```{error_message[:400]}```", "inline": False},
    ]
    return send_discord_webhook(
        url,
        title=title,
        description="The macro encountered an error during automated execution.",
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
    title = "📈 HOURLY REPORT — Flare Macro"
    hours = max(1, int(session_duration_s // 3600))
    time_str = f"{int(session_duration_s // 3600)}h {int((session_duration_s % 3600) // 60)}m"
    win_rate = f"{(wins / runs_completed * 100):.0f}%" if runs_completed else "0%"

    fields = [
        {"name": "⏱️ Session Duration", "value": time_str, "inline": True},
        {"name": "🎮 Runs (W / L)", "value": f"{runs_completed} ({wins}W / {runs_completed - wins}L)", "inline": True},
        {"name": "🎯 Win Rate", "value": win_rate, "inline": True},
        {"name": "💰 Coins Farmed", "value": f"+{coins_farmed:,}", "inline": True},
        {"name": "⚡ Coins / Hour", "value": f"{coins_per_hr:,.0f} / hr", "inline": True},
        {"name": "🌊 Current Wave", "value": str(current_wave) if current_wave is not None else "In Lobby", "inline": True},
    ]
    return send_discord_webhook(
        url,
        title=title,
        description=f"Hourly progress report for the past {hours} hour(s) of automated farming.",
        color=0x3B82F6,
        fields=fields,
    )
