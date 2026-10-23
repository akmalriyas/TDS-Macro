"""Entry point for Flare Macro standalone build."""
import os
import sys
import traceback
from pathlib import Path

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
