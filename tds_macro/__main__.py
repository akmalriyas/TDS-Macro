"""CLI entry point for the TDS macro.

Usage:
  python -m tds_macro doctor
  python -m tds_macro snap [name]
  python -m tds_macro watch
  python -m tds_macro lobby
  python -m tds_macro intermission
  python -m tds_macro match
  python -m tds_macro run [--runs N]
  python -m tds_macro ui
  python -m tds_macro click X Y
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import RunSettings, TEMP, ensure_dpi_aware

ensure_dpi_aware()

from rich.console import Console
from rich.table import Table

from . import vision, window
from .capture import Capture
from .core import Macro, MacroError
from .flows import lobby as lobby_flow
from .ocr import OCR
from .runlog import RunLog
from .state import State, StateDetector

console = Console()


def cmd_doctor(_args) -> int:
    table = Table(title="TDS Macro doctor")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail")

    try:
        cap = Capture()
        frame = cap.grab()
        table.add_row("Screen capture", "OK", f"{frame.shape[1]}x{frame.shape[0]} mean={frame.mean():.1f}")
        path = cap.save(frame, "doctor.png")
        table.add_row("Screenshot", "OK", str(path))
    except Exception as exc:
        table.add_row("Screen capture", "FAIL", repr(exc))
        frame = None

    try:
        ocr = OCR()
        if frame is not None:
            lines = ocr.recognize(frame)
            table.add_row("Windows OCR", "OK", f"{len(lines)} lines: {' | '.join(l.text for l in lines[:6])}")
        else:
            table.add_row("Windows OCR", "SKIP", "no frame")
    except Exception as exc:
        table.add_row("Windows OCR", "FAIL", repr(exc))

    info = window.find_window()
    if info:
        table.add_row("Roblox window", "OK", f"hwnd={info.hwnd} rect={info.rect} size={info.width}x{info.height}")
    else:
        table.add_row("Roblox window", "MISSING", "will launch on run")

    table.add_row("Assets", "OK" if any((Path(__file__).parent / "assets").iterdir()) else "EMPTY", str(Path(__file__).parent / "assets"))
    console.print(table)
    return 0


def cmd_snap(args) -> int:
    cap = Capture()
    frame = cap.grab()
    name = args.name or f"snap_{int(time.time())}"
    if not name.endswith(".png"):
        name += ".png"
    path = cap.save(frame, name)
    console.print(f"saved [bold]{path}[/bold]")
    ocr = OCR()
    for line in ocr.recognize(frame):
        console.print(f"  {line.text!r} @ {line.box.x},{line.box.y} {line.box.w}x{line.box.h}")
    return 0


def cmd_watch(args) -> int:
    m = Macro()
    try:
        while True:
            frame = m.grab()
            det = m.detector.detect(frame)
            text = " | ".join(l.text for l in det.lines[:8])
            console.print(f"[bold]{det.state.value:18}[/bold] {det.detail:20} {text[:160]}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        m.close()


def cmd_click(args) -> int:
    m = Macro()
    m.click_fixed(args.x, args.y)
    return 0


def _new_macro(settings: RunSettings) -> Macro:
    m = Macro(settings, console)
    info = window.find_window()
    if info:
        m.window_info = window.focus_window(info)
    return m


def cmd_lobby(args) -> int:
    settings = RunSettings()
    m = _new_macro(settings)
    try:
        state = lobby_flow.ensure_game(m)
        if state == State.LOBBY:
            coins, gems = lobby_flow.read_currencies(m)
            lobby_flow.check_scout(m)
            lobby_flow.open_play_menu(m)
            lobby_flow.select_survival_easy_solo(m)
            m.wait_for_state([State.LOADING, State.INTERMISSION, State.GAMEPLAY_PREP], timeout=90.0)
            if m.detect().state == State.LOADING:
                m.wait_for_state(State.INTERMISSION, timeout=90.0)
            lobby_flow.run_intermission(m)
        elif state == State.INTERMISSION:
            lobby_flow.run_intermission(m)
        console.print("[green]lobby flow complete[/green]")
        return 0
    except MacroError as exc:
        console.print(f"[red]lobby flow failed: {exc}[/red]")
        m.snap("lobby_failure")
        return 2
    finally:
        m.close()


def cmd_intermission(args) -> int:
    m = _new_macro(RunSettings())
    try:
        lobby_flow.run_intermission(m)
        console.print("[green]intermission complete[/green]")
        return 0
    except MacroError as exc:
        console.print(f"[red]intermission failed: {exc}[/red]")
        m.snap("intermission_failure")
        return 2
    finally:
        m.close()


def cmd_match(args) -> int:
    from .flows import match as match_flow

    m = _new_macro(RunSettings())
    try:
        state = match_flow.run_match(m)
        if state in (State.VICTORY, State.DEFEAT):
            match_flow.parse_results_and_continue(m)
        console.print("[green]match flow complete[/green]")
        return 0
    except MacroError as exc:
        console.print(f"[red]match flow failed: {exc}[/red]")
        m.snap("match_failure")
        return 2
    finally:
        m.close()


def cmd_ui(args) -> int:
    from .ui import launch_ui

    return launch_ui(RunSettings())


def cmd_run(args) -> int:
    from .flows import runloop
    from .watchdog import HotkeyWatchdog

    settings = RunSettings()
    if args.runs:
        settings.max_runs = args.runs
    m = _new_macro(settings)
    log = RunLog(settings.log_dir)

    def _toggle_pause() -> None:
        m.paused = not m.paused
        m.log("macro paused (F6)" if m.paused else "macro resumed (F6)", "yellow" if m.paused else "green")

    def _stop() -> None:
        m.stop_requested = True
        m.paused = False
        m.log("emergency stop triggered (F8)", "red")

    wd = HotkeyWatchdog(on_pause=_toggle_pause, on_stop=_stop)
    wd.start()
    try:
        runloop.run_forever(m, log, settings)
        return 0
    except KeyboardInterrupt:
        console.print("[yellow]stopped[/yellow]")
        return 0
    except Exception as exc:
        console.print(f"[red]fatal: {exc}[/red]")
        m.snap("fatal")
        return 2
    finally:
        wd.close()
        m.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tds-macro", description="Tower Defense Simulator macro (CLI)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="check capture, OCR, window, assets")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("snap", help="save a screenshot and print OCR")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_snap)

    p = sub.add_parser("watch", help="print detected state continuously")
    p.add_argument("--interval", type=float, default=1.0)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("click", help="debug a physical click")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("lobby", help="run lobby -> matchmaking -> intermission")
    p.set_defaults(func=cmd_lobby)

    p = sub.add_parser("intermission", help="run only the intermission sequence")
    p.set_defaults(func=cmd_intermission)

    p = sub.add_parser("match", help="run only the in-match gameplay sequence")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("run", help="run the full macro loop")
    p.add_argument("--runs", type=int, default=0, help="number of runs (0 = unlimited)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ui", help="launch the dark Control Panel UI and HUD overlay")
    p.set_defaults(func=cmd_ui)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
