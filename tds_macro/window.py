"""Roblox window discovery, launch, and focus helpers."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time
from dataclasses import dataclass
from typing import Optional

from .config import GAME_URL, WINDOW_TITLE, ensure_dpi_aware

user32 = ctypes.WinDLL("user32", use_last_error=True)

SW_RESTORE = 9
SW_SHOW = 5
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040


@dataclass
class WindowInfo:
    hwnd: int
    rect: tuple[int, int, int, int]  # left, top, right, bottom

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def center(self) -> tuple[int, int]:
        return ((self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2)


def _ensure_default_desktop() -> None:
    try:
        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


def find_window(title: str = WINDOW_TITLE) -> Optional[WindowInfo]:
    _ensure_default_desktop()
    ensure_dpi_aware()
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        # Fall back to enumerating visible top-level windows whose title contains
        # the target (Roblox may append a suffix in some builds).
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def _enum(h, _l):
            if not user32.IsWindowVisible(h):
                return True
            n = user32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(h, buf, n + 1)
                if title.lower() in buf.value.lower():
                    found.append((h, buf.value))
            return True

        user32.EnumWindows(_enum, 0)
        if not found:
            return None
        hwnd = found[0][0]
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return WindowInfo(hwnd, (rect.left, rect.top, rect.right, rect.bottom))


def is_running(title: str = WINDOW_TITLE) -> bool:
    return find_window(title) is not None


def focus_window(info: Optional[WindowInfo] = None, topmost: bool = True) -> Optional[WindowInfo]:
    ensure_dpi_aware()
    info = info or find_window()
    if info is None:
        return None
    hwnd = info.hwnd
    user32.ShowWindow(hwnd, SW_RESTORE)
    if topmost:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    time.sleep(0.25)
    # Nudge focus if another process still owns it.
    if user32.GetForegroundWindow() != hwnd:
        # Alt-key trick: a key press releases the foreground lock.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.05)
        user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return find_window()


def open_url(url: str = GAME_URL) -> None:
    """Open a roblox:// deep link on the interactive WinSta0\\Default desktop."""
    ensure_dpi_aware()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"roblox\shell\open\command") as k:
            tpl = winreg.QueryValue(k, None)
        cmd = tpl.replace("%1", url)

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD),
                ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD),
                ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD),
                ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD),
                ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wt.HANDLE),
                ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD),
            ]

        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = "WinSta0\\Default"
        pi = PROCESS_INFORMATION()
        cmd_buf = ctypes.create_unicode_buffer(cmd)
        ok = ctypes.windll.kernel32.CreateProcessW(
            None, cmd_buf, None, None, False, 0, None, None, ctypes.byref(si), ctypes.byref(pi)
        )
        if ok:
            ctypes.windll.kernel32.CloseHandle(pi.hProcess)
            ctypes.windll.kernel32.CloseHandle(pi.hThread)
            return
    except Exception:
        pass
    os.startfile(url)  # noqa: S606 - fallback protocol handler launch


def launch(wait_s: float = 90.0) -> Optional[WindowInfo]:
    """Launch TDS through the Roblox deep link, or focus an existing window."""
    info = find_window()
    if info is not None:
        return focus_window(info)
    open_url(GAME_URL)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        info = find_window()
        if info is not None:
            time.sleep(1.0)
            return focus_window(info)
        time.sleep(0.5)
    return None


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def is_foreground(info: Optional[WindowInfo] = None) -> bool:
    info = info or find_window()
    return info is not None and user32.GetForegroundWindow() == info.hwnd
