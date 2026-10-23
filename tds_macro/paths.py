"""Application paths and resource location helpers."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# When frozen by PyInstaller, sys._MEIPASS holds the bundled resources
IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    if (base / "tds_macro" / "assets").exists():
        PACKAGE_DIR = base / "tds_macro"
    elif (base / "assets").exists():
        PACKAGE_DIR = base
    else:
        PACKAGE_DIR = base / "tds_macro"
    ROOT_DIR = base
else:
    PACKAGE_DIR = Path(__file__).resolve().parent
    ROOT_DIR = PACKAGE_DIR.parent

ASSETS_DIR = PACKAGE_DIR / "assets"
WEB_DIR = PACKAGE_DIR / "ui" / "web"

# Persistent user data directory in %LOCALAPPDATA%\FlareMacro
LOCAL_APPDATA = os.environ.get("LOCALAPPDATA")
if LOCAL_APPDATA:
    DATA_DIR = Path(LOCAL_APPDATA) / "FlareMacro"
else:
    DATA_DIR = Path.home() / ".flare_macro"

LOGS_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "ui_settings.json"
QUEUE_FILE = DATA_DIR / "queue.json"
RUNS_JSONL = LOGS_DIR / "runs.jsonl"
RUNS_CSV = LOGS_DIR / "runs.csv"

TEMP_DIR = Path(os.environ.get("TEMP", str(DATA_DIR / "tmp"))) / "flare_macro"

for _p in (DATA_DIR, LOGS_DIR, TEMP_DIR):
    _p.mkdir(parents=True, exist_ok=True)


def migrate_local_data() -> None:
    """One-time migration: copy any existing repo-local logs to the persistent user data directory."""
    old_logs = ROOT_DIR / "logs"
    if old_logs.exists() and old_logs.resolve() != LOGS_DIR.resolve():
        for item in old_logs.iterdir():
            dest = LOGS_DIR / item.name
            if not dest.exists():
                try:
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)
                except Exception:
                    pass
        old_settings = old_logs / "ui_settings.json"
        if old_settings.exists() and not SETTINGS_FILE.exists():
            try:
                shutil.copy2(old_settings, SETTINGS_FILE)
            except Exception:
                pass
        old_queue = old_logs / "queue.json"
        if old_queue.exists() and not QUEUE_FILE.exists():
            try:
                shutil.copy2(old_queue, QUEUE_FILE)
            except Exception:
                pass


# Run migration on module import
try:
    migrate_local_data()
except Exception:
    pass
