"""System requirements verification, first-launch setup, and environment diagnostics."""
from __future__ import annotations

import glob
import json
import os
import platform
import subprocess
import sys
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__
from .paths import DATA_DIR, atomic_write_json, safe_read_json

SETUP_STATE_FILE = DATA_DIR / "setup_state.json"


@dataclass
class CheckItem:
    id: str
    name: str
    category: str
    passed: bool
    critical: bool
    status: str
    detail: str
    fix_action: Optional[str] = None
    fix_label: Optional[str] = None


def _check_os() -> CheckItem:
    is_win = sys.platform == "win32"
    is_64 = sys.maxsize > 2**32
    win_ver = platform.version()
    passed = is_win and is_64
    return CheckItem(
        id="os",
        name="Operating System",
        category="System",
        passed=passed,
        critical=True,
        status="PASS" if passed else "FAIL",
        detail=f"Windows {platform.release()} ({win_ver}, 64-bit)" if is_win else "Non-Windows OS",
    )


def _check_webview2() -> CheckItem:
    import winreg
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    version = None
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as k:
                val, _ = winreg.QueryValueEx(k, "pv")
                if val:
                    version = val
                    break
        except Exception:
            pass
    passed = bool(version)
    return CheckItem(
        id="webview2",
        name="Edge WebView2 Runtime",
        category="Prerequisites",
        passed=passed,
        critical=True,
        status="PASS" if passed else "MISSING",
        detail=f"Build {version}" if passed else "WebView2 Runtime is required to render the control panel.",
        fix_action="install_webview2" if not passed else None,
        fix_label="Install WebView2" if not passed else None,
    )


def _check_ocr() -> CheckItem:
    try:
        import winocr
        langs = [l.language_tag for l in winocr.OcrEngine.available_recognizer_languages]
        has_en = any("en" in l.lower() for l in langs)
        if has_en:
            return CheckItem(
                id="ocr",
                name="Windows OCR Language Pack",
                category="Prerequisites",
                passed=True,
                critical=True,
                status="PASS",
                detail=f"English OCR engine active ({', '.join(langs[:3])})",
            )
    except Exception as exc:
        return CheckItem(
            id="ocr",
            name="Windows OCR Language Pack",
            category="Prerequisites",
            passed=False,
            critical=True,
            status="ERROR",
            detail=f"OCR initialization error: {exc}",
            fix_action="install_ocr",
            fix_label="Install English OCR",
        )

    return CheckItem(
        id="ocr",
        name="Windows OCR Language Pack",
        category="Prerequisites",
        passed=False,
        critical=True,
        status="MISSING",
        detail="English OCR language capability is not installed in Windows.",
        fix_action="install_ocr",
        fix_label="Install English OCR",
    )


def _check_roblox() -> CheckItem:
    local_app = os.environ.get("LOCALAPPDATA", "")
    matches = glob.glob(os.path.join(local_app, "Roblox", "Versions", "*", "RobloxPlayerBeta.exe"))
    passed = len(matches) > 0
    return CheckItem(
        id="roblox",
        name="Roblox Player Client",
        category="Environment",
        passed=passed,
        critical=True,
        status="PASS" if passed else "NOT FOUND",
        detail="Roblox Player detected" if passed else "RobloxPlayerBeta.exe was not found in standard directories.",
        fix_action="open_roblox" if not passed else None,
        fix_label="Download Roblox" if not passed else None,
    )


def _check_display() -> CheckItem:
    from . import viewport
    st = viewport.status()
    level = st.get("level", "ok")
    passed = level != "error"
    return CheckItem(
        id="display",
        name="Display Resolution & Aspect",
        category="Display",
        passed=passed,
        critical=False,
        status="PASS" if level == "ok" else ("WARN" if level == "warn" else "FAIL"),
        detail=st.get("message", "16:9 Standard Aspect"),
    )


def _check_capture() -> CheckItem:
    try:
        from .capture import Capture

        cap = Capture()
        frame = cap.grab()
        if frame is not None and frame.size > 0:
            method = "DXGI" if getattr(cap, "camera", None) is not None else "Direct"
            return CheckItem(
                id="capture",
                name="Screen Capture Pipeline",
                category="Diagnostics",
                passed=True,
                critical=True,
                status="PASS",
                detail=f"{method} capture active ({frame.shape[1]}x{frame.shape[0]})",
            )
    except Exception:
        pass

    try:
        from PIL import ImageGrab

        test_frame = ImageGrab.grab()
        if test_frame is not None and test_frame.size[0] > 0:
            return CheckItem(
                id="capture",
                name="Screen Capture Pipeline",
                category="Diagnostics",
                passed=True,
                critical=True,
                status="PASS",
                detail=f"Desktop capture active ({test_frame.size[0]}x{test_frame.size[1]})",
            )
    except Exception as exc:
        return CheckItem(
            id="capture",
            name="Screen Capture Pipeline",
            category="Diagnostics",
            passed=False,
            critical=True,
            status="FAIL",
            detail=f"Capture pipeline failed: {exc}",
        )

    return CheckItem(
        id="capture",
        name="Screen Capture Pipeline",
        category="Diagnostics",
        passed=False,
        critical=True,
        status="FAIL",
        detail="Capture returned a blank or invalid frame.",
    )


def check_all() -> dict:
    """Run all system checks and return structured status."""
    checks = [
        _check_os(),
        _check_webview2(),
        _check_ocr(),
        _check_roblox(),
        _check_display(),
        _check_capture(),
    ]
    critical_passed = all(c.passed for c in checks if c.critical)
    all_passed = all(c.passed for c in checks)
    return {
        "all_passed": all_passed,
        "critical_passed": critical_passed,
        "checks": [asdict(c) for c in checks],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def is_setup_completed() -> bool:
    data = safe_read_json(SETUP_STATE_FILE)
    if isinstance(data, dict):
        return bool(data.get("completed", False))
    return False


def mark_setup_completed() -> None:
    data = {
        "completed": True,
        "version": __version__,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(SETUP_STATE_FILE, data)


def fix_requirement(action_id: str) -> dict:
    """Execute an automated fix or launch installation helper."""
    if action_id == "install_ocr":
        cmd = 'Start-Process powershell -Verb RunAs -ArgumentList "-Command Add-WindowsCapability -Online -Name Language.OCR~~~en-US~0.0.1.0"'
        try:
            subprocess.Popen(["powershell", "-Command", cmd])
            return {"ok": True, "message": "Launched elevated English OCR capability installer."}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action_id == "install_webview2":
        url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
        webbrowser.open(url)
        return {"ok": True, "message": "Opened official Microsoft Edge WebView2 installer download."}

    elif action_id == "open_roblox":
        webbrowser.open("https://www.roblox.com/download")
        return {"ok": True, "message": "Opened Roblox download page in default browser."}

    return {"ok": False, "message": f"Unknown fix action: {action_id}"}
