"""Where the dashboard keeps its saved price, worth and skill history."""
from __future__ import annotations

import os
import platform
from pathlib import Path


def home_dir() -> Path:
    env = os.environ.get("STELLAR_DASHBOARD_HOME")
    if env:
        return Path(env).expanduser()
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "SOMiniDashboard"
    if system == "Darwin":
        return Path.home() / "Library/Application Support/SOMiniDashboard"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "so-mini-dashboard"
