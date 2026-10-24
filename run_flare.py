"""Entry point for Flare Macro standalone build."""
import os
import sys
import traceback
from pathlib import Path


def _unblock_self() -> None:
    """Silently remove Windows Mark-of-the-Web (Zone.Identifier) so .NET CLR loads DLLs cleanly."""
    if sys.platform != "win32":
        return
    try:
        base_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.lower().endswith((".dll", ".exe", ".json", ".config", ".pyd")):
                    stream_path = os.path.join(root, file) + ":Zone.Identifier"
                    if os.path.exists(stream_path):
                        try:
                            os.remove(stream_path)
                        except Exception:
                            pass
    except Exception:
        pass


_unblock_self()

# Global exception logger for windowed execution
try:
    _appdata = os.environ.get("LOCALAPPDATA")
    if _appdata:
        _crash_dir = Path(_appdata) / "FlareMacro" / "logs"
    else:
        _crash_dir = Path.home() / ".flare_macro" / "logs"
    _crash_dir.mkdir(parents=True, exist_ok=True)
    _crash_file = _crash_dir / "crash.log"

    def _on_exception(exc_type, exc_value, exc_tb):
        err = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(_crash_file, "a", encoding="utf-8") as f:
                f.write(err + "\n")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _on_exception
except Exception:
    pass

from tds_macro.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
