"""Continuous multi-run orchestration loop with hourly stats and error recovery."""
from __future__ import annotations

import time
from typing import Optional

from rich.table import Table

from ..config import RunSettings
from ..core import Macro, MacroError
from ..runlog import RunLog, RunRecord
from ..state import State
from . import lobby, match


def _print_hourly_table(m: Macro, log: RunLog) -> None:
    s = log.summary()
    t = Table(title="TDS Macro — Session & Hourly Summary", show_header=True, header_style="bold cyan")
    t.add_column("Runs", justify="right")
    t.add_column("W / L", justify="right")
    t.add_column("Coins Earned", justify="right", style="yellow")
    t.add_column("Coins / hr", justify="right", style="bold yellow")
    t.add_column("Gems Earned", justify="right", style="magenta")
    t.add_column("Gems / hr", justify="right", style="bold magenta")
    t.add_column("XP / hr", justify="right", style="green")
    t.add_row(
        str(int(s["runs"])),
        f"{int(s['wins'])} / {int(s['losses'])}",
        f"{int(s['coins_total']):,}",
        f"{s['coins_per_hour']:,.0f}/hr",
        f"{int(s['gems_total']):,}",
        f"{s['gems_per_hour']:,.0f}/hr",
        f"{s['xp_per_hour']:,.0f}/hr",
    )
    m.console.print(t)


def run_forever(m: Macro, log: RunLog, settings: Optional[RunSettings] = None) -> None:
    """Run the complete Lobby -> Intermission -> Match -> Play Again loop indefinitely."""
    settings = settings or m.settings
    session_runs = 0
    total_runs = len(log.records())
    loop_start_time = time.time()
    last_hourly_time = time.time()

    while not m.stop_requested:
        if settings.max_runs > 0 and session_runs >= settings.max_runs:
            m.log(f"reached max_runs={settings.max_runs} this session; stopping loop", "green")
            break

        session_runs += 1
        total_runs += 1
        run_index = total_runs
        rec = RunRecord.start_new(
            run_index=run_index,
            gamemode=settings.gamemode,
            map_name=settings.map_name,
            modifiers=list(settings.modifiers) if getattr(settings, "enable_modifiers", True) else [],
        )
        if m.last_coins is not None:
            rec.coins_before = m.last_coins
        if m.last_gems is not None:
            rec.gems_before = m.last_gems

        # Check hourly performance webhook
        now = time.time()
        if getattr(settings, "webhook_url", "") and getattr(settings, "webhook_hourly", False) and (now - last_hourly_time >= 3600):
            last_hourly_time = now
            try:
                from ..webhook import send_hourly_webhook
                stats = log.summary()
                send_hourly_webhook(
                    settings.webhook_url,
                    session_duration_s=now - loop_start_time,
                    runs_completed=session_runs - 1,
                    wins=sum(1 for r in log.records()[-session_runs:] if (r.get("result") or "").lower() in ("victory", "triumph", "win")),
                    coins_farmed=int(stats.get("coins_total", 0)),
                    coins_per_hr=float(stats.get("coins_per_hour", 0.0)),
                    current_wave=getattr(m, "current_wave", None),
                )
            except Exception as e:
                m.log(f"hourly webhook error: {e}", "dim")

        m.log(f"=== Starting Run #{run_index} ({settings.gamemode} / {settings.map_name}) ===", "bold cyan")

        try:
            m.check_interrupts()
            state = lobby.ensure_game(m)

            if state == State.DISCONNECTED:
                m.log("Roblox client disconnected; executing reconnect recovery", "bold yellow")
                lobby.reconnect(m)
                m.sleep(4.0)
                continue

            # 1. If in LOBBY / PLAY_MENU / SQUAD_SELECT, record currencies, check Golden Scout ONCE, and queue Solo
            if state in (State.LOBBY, State.PLAY_MENU, State.SQUAD_SELECT):
                if state == State.LOBBY:
                    coins, gems = lobby.read_currencies(m)
                    rec.coins_before = coins if coins is not None else rec.coins_before
                    rec.gems_before = gems if gems is not None else rec.gems_before

                    # Step 2: Check if Scout is equipped & Golden is ticked ONLY ONCE per session start
                    if settings.verify_scout_once and not m.scout_checked:
                        lobby.check_scout(m)

                    lobby.open_play_menu(m)

                lobby.select_survival_easy_solo(m)
                state = m.wait_for_state(
                    [State.INTERMISSION, State.GAMEPLAY_PREP, State.GAMEPLAY, State.DISCONNECTED],
                    timeout=90.0,
                ).state

            if state == State.DISCONNECTED:
                m.log("matchmaking disconnected; executing reconnect recovery", "bold yellow")
                lobby.reconnect(m)
                m.sleep(4.0)
                continue

            # 2. If in INTERMISSION / MODIFIERS / OVERRIDE, configure modifiers + override Dead Ahead + select map + Ready
            if state in (State.INTERMISSION, State.MODIFIERS, State.OVERRIDE):
                if state in (State.MODIFIERS, State.OVERRIDE):
                    lobby.close_modal(m)
                    time.sleep(0.6)
                lobby.run_intermission(m)
                state = m.wait_for_state(
                    [State.GAMEPLAY_PREP, State.GAMEPLAY, State.VICTORY, State.DEFEAT, State.DISCONNECTED],
                    timeout=90.0,
                ).state

            if state == State.DISCONNECTED:
                m.log("intermission disconnected; executing reconnect recovery", "bold yellow")
                lobby.reconnect(m)
                m.sleep(4.0)
                continue

            # 3. In-Match Gameplay (Dead Ahead Golden Scout strategy)
            if state in (State.GAMEPLAY_PREP, State.GAMEPLAY):
                state = match.run_match(m, record=rec)

            if state == State.DISCONNECTED:
                m.log("match disconnected; executing reconnect recovery", "bold yellow")
                lobby.reconnect(m)
                m.sleep(4.0)
                continue

            # 4. Victory / Defeat Screen -> OCR Stats, Log Run, and Click Play Again
            if state in (State.VICTORY, State.DEFEAT):
                match.parse_results_and_continue(m, record=rec)
                rec.finish(result=rec.result if rec.result != "running" else state.value)
                log.append(rec)
                m.notify_status()
                _print_hourly_table(m, log)

                # Send Discord Webhook notification if configured
                _won = (rec.result or "").lower() in ("victory", "triumph", "win")
                _wants = settings.webhook_on_triumph if _won else settings.webhook_on_defeat
                if getattr(settings, "webhook_url", "") and _wants:
                    try:
                        from ..webhook import send_run_result_webhook
                        stats = log.summary()
                        send_run_result_webhook(
                            settings.webhook_url,
                            task_name=f"{rec.map} ({rec.difficulty})",
                            map_name=rec.map or "Dead Ahead",
                            gamemode=rec.difficulty or "Easy",
                            outcome=rec.result,
                            wave_reached=rec.wave or 20,
                            coins_earned=rec.reward_coins or rec.coin_delta or 0,
                            xp_earned=rec.reward_xp or 0,
                            duration_s=rec.duration_s,
                            total_coins=int(stats.get("coins_total", 0)),
                            coins_per_hr=float(stats.get("coins_per_hour", 0.0)),
                        )
                    except Exception as e:
                        m.log(f"webhook notice error: {e}", "dim")

                # After clicking Play Again, wait briefly for next Intermission or Lobby load
                m.sleep(3.0)
                continue

            if state == State.LOBBY:
                m.log("match completed and returned to lobby", "green")
                rec.finish(result="defeat", notes="returned to lobby after match")
                log.append(rec)
                m.notify_status()
                _print_hourly_table(m, log)
                m.sleep(2.0)
                continue

        except MacroError as exc:
            if m.stop_requested:
                m.log("run loop stopped by user", "yellow")
                break
            m.log(f"run #{run_index} error: {exc}", "red")
            m.snap(f"run_{run_index}_error")
            rec.finish(result="error", notes=str(exc))
            log.append(rec)
            m.notify_status()
            if getattr(settings, "webhook_url", "") and getattr(settings, "webhook_on_error", False):
                try:
                    from ..webhook import send_error_webhook
                    send_error_webhook(
                        settings.webhook_url,
                        task_name=f"{settings.map_name} ({settings.gamemode})",
                        error_message=str(exc),
                        context=f"Run #{run_index} - State: {getattr(m, 'current_state', 'Unknown')}",
                    )
                except Exception as e:
                    m.log(f"error webhook failed: {e}", "dim")
            m.sleep(settings.retry_delay_s)
        except Exception as exc:
            if m.stop_requested:
                break
            m.log(f"unexpected exception in run #{run_index}: {exc}", "red")
            m.snap(f"run_{run_index}_exception")
            rec.finish(result="error", notes=repr(exc))
            log.append(rec)
            m.notify_status()
            if getattr(settings, "webhook_url", "") and getattr(settings, "webhook_on_error", False):
                try:
                    from ..webhook import send_error_webhook
                    send_error_webhook(
                        settings.webhook_url,
                        task_name=f"{settings.map_name} ({settings.gamemode})",
                        error_message=repr(exc),
                        context=f"Run #{run_index} - Unexpected Exception",
                    )
                except Exception as e:
                    m.log(f"error webhook failed: {e}", "dim")
            m.sleep(settings.retry_delay_s)
