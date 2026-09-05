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
import os
import sys


def _is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def is_macos_app_bundle() -> bool:
    return sys.platform == "darwin" and _is_frozen_build()


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
    # Non-bundle builds: the app root (parent of Libs/) is where the
    # executable lives and is user-writable.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def logs_dir() -> str:
    path = os.path.join(user_data_dir(), "logs")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(os.path.expanduser("~"), "TiktokStreamKeyGenerator-logs")
        os.makedirs(fallback, exist_ok=True)
        return fallback
