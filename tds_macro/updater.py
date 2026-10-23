"""GitHub Release update checker and automated installer."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .paths import TEMP_DIR

GITHUB_REPO = "akmalriyas/TDS-Macro"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
USER_AGENT = "FlareMacro-AutoUpdater"


def _parse_semver(v_str: str) -> tuple[int, int, int]:
    m = re.search(r"(\d+)\.(\d+)\.?(\d+)?", v_str.strip())
    if not m:
        return (0, 0, 0)
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) else 0
    return (major, minor, patch)


def check_for_updates() -> dict:
    """Check GitHub Releases for newer versions."""
    req = urllib.request.Request(
        f"{API_URL}/latest",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"},
    )
    release = None
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                release = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Fall back to release list in case 'latest' isn't tagged yet
            try:
                list_req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(list_req, timeout=5.0) as resp:
                    items = json.loads(resp.read().decode("utf-8"))
                    if items and isinstance(items, list):
                        release = items[0]
            except Exception:
                pass
    except Exception as exc:
        return {
            "update_available": False,
            "error": str(exc),
            "current_version": __version__,
        }

    if not release or not isinstance(release, dict):
        return {
            "update_available": False,
            "current_version": __version__,
            "message": "No releases published yet on GitHub.",
        }

    tag = release.get("tag_name", "")
    target_ver = _parse_semver(tag)
    current_ver = _parse_semver(__version__)

    is_update = target_ver > current_ver
    is_major = target_ver[0] > current_ver[0]

    # Find primary download asset
    assets = release.get("assets", [])
    download_url = None
    asset_name = None
    for a in assets:
        name = a.get("name", "")
        if name.endswith(".exe") or name.endswith(".zip"):
            download_url = a.get("browser_download_url")
            asset_name = name
            if "setup" in name.lower() or name.endswith(".exe"):
                break

    if not download_url:
        download_url = release.get("zipball_url")
        asset_name = f"FlareMacro-{tag}.zip"

    return {
        "update_available": is_update,
        "is_major": is_major,
        "current_version": __version__,
        "latest_version": tag.lstrip("v"),
        "tag": tag,
        "title": release.get("name") or f"Release {tag}",
        "notes": release.get("body") or "No changelog provided.",
        "download_url": download_url,
        "asset_name": asset_name,
        "published_at": release.get("published_at"),
    }


def download_update(url: str, progress_cb: Optional[Callable[[int, int], None]] = None) -> Path:
    """Download the update asset to the temporary directory."""
    asset_name = url.split("/")[-1].split("?")[0] or "FlareMacro_update.bin"
    target_path = TEMP_DIR / asset_name

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 64 * 1024
        with open(target_path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(downloaded, total)

    return target_path
