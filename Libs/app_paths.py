"""Writable filesystem locations shared by the GUI and the SEI-proxy child
processes.

The app keeps its data (config, cookies, logs, caches) next to the
executable on Windows/Linux. macOS .app bundles put the executable inside
<App>.app/Contents/MacOS, which is not a durable, writable location — the
bundle is replaced on every app update and can be read-only — so user data
goes to ~/Library/Application Support/TiktokStreamKeyGenerator instead.

Every Libs module that writes to disk (rapidapi_quota, XFrameSign, signers)
resolves its paths through logs_dir() so the GUI process and the packaged
proxy children agree on the same locations.
"""
import json
import os
from pathlib import Path
import sys


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def is_macos_app_bundle() -> bool:
    return sys.platform == "darwin" and is_frozen_build()


def user_data_dir() -> str:
    if is_macos_app_bundle():
        base = os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "TiktokStreamKeyGenerator",
        )
        try:
            os.makedirs(base, exist_ok=True)
            return base
        except OSError:
            pass
    if is_frozen_build():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path() -> str:
    return os.path.join(user_data_dir(), "config.json")


def read_signer_config() -> dict:
    preferred = Path(config_path())
    app_root = Path(__file__).resolve().parents[1]
    # Older and standalone signer callers may still use these locations.
    filename = preferred.name
    for path in (preferred, app_root / filename, app_root.parent / filename, Path(filename)):
        try:
            with path.open(encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def logs_dir() -> str:
    path = os.path.join(user_data_dir(), "logs")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(os.path.expanduser("~"), "TiktokStreamKeyGenerator-logs")
        os.makedirs(fallback, exist_ok=True)
        return fallback
