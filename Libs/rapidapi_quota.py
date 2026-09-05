"""Shared RapidAPI quota meter.

RapidAPI returns the subscription's monthly quota in response headers on
every API call (x-ratelimit-requests-*). Both signer call sites
(Libs/signers.py and Libs/XFrameSign.py) feed those headers here; the state
is persisted to logs/rapidapi_quota.json so the GUI can display it without
spending any extra API requests. This costs zero quota: the numbers are a
free byproduct of calls the app already makes.
"""
import json
import os
import threading
import time
from pathlib import Path

try:
    from Libs.app_paths import logs_dir as _app_logs_dir
except Exception:
    try:
        from app_paths import logs_dir as _app_logs_dir
    except Exception:
        _app_logs_dir = None

APP_ROOT = Path(__file__).resolve().parents[1]


def _logs_dir() -> Path:
    # macOS .app bundles must keep logs outside the bundle; see app_paths.
    if _app_logs_dir is not None:
        try:
            return Path(_app_logs_dir())
        except Exception:
            pass
    return APP_ROOT / "logs"


QUOTA_PATH = _logs_dir() / "rapidapi_quota.json"
_LOCK = threading.Lock()

# RapidAPI uses x-ratelimit-requests-* on most APIs and x-quota-* on some
# older/proxied products; accept either.
_HEADER_NAMES = {
    "limit": ("x-ratelimit-requests-limit", "x-quota-limit"),
    "remaining": ("x-ratelimit-requests-remaining", "x-quota-remaining"),
    "used": ("x-ratelimit-requests-used", "x-quota-used"),
    "reset": ("x-ratelimit-requests-reset", "x-quota-reset"),
}


def _header_value(headers, names) -> str:
    getter = getattr(headers, "get", None)
    if getter is None:
        try:
            headers = {str(k).lower(): v for k, v in headers.items()}
            getter = headers.get
        except Exception:
            return ""
    for name in names:
        try:
            value = getter(name)
        except Exception:
            value = None
        if value not in (None, ""):
            return str(value).strip()
    return ""


def update_from_headers(headers) -> dict:
    """Extract quota headers from a RapidAPI response and persist them.

    Safe to call from any process/thread; returns the snapshot or {} when
    the response carried no quota headers.
    """
    try:
        snapshot = {}
        for field, names in _HEADER_NAMES.items():
            value = _header_value(headers, names)
            if value:
                snapshot[field] = value
        if not snapshot:
            return {}
        snapshot["updated"] = int(time.time())
        with _LOCK:
            QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = QUOTA_PATH.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh)
            os.replace(tmp_path, QUOTA_PATH)
        return snapshot
    except Exception:
        return {}


def read_quota() -> dict:
    """Return the latest persisted quota snapshot ({} if none yet)."""
    try:
        with open(QUOTA_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _reset_epoch(snapshot):
    """Resolve the reset header to an absolute timestamp.

    RapidAPI's x-ratelimit-requests-reset is seconds-until-reset, not a
    Unix timestamp (it visibly counts down across consecutive responses),
    so it must be added to the snapshot time. Very large values are treated
    as already-absolute timestamps just in case the format ever changes.
    """
    reset = _to_int((snapshot or {}).get("reset"))
    if not reset:
        return None
    if reset > 100_000_000:
        return reset
    updated = _to_int((snapshot or {}).get("updated")) or int(time.time())
    return updated + reset


def format_quota(snapshot) -> str:
    """Human-readable one-liner for the UI, e.g. '9,437 / 10,000 left · resets Sep 01'."""
    if not isinstance(snapshot, dict) or not snapshot:
        return "Unknown"
    limit = _to_int(snapshot.get("limit"))
    remaining = _to_int(snapshot.get("remaining"))
    used = _to_int(snapshot.get("used"))

    parts = []
    if remaining is not None and limit:
        parts.append(f"{remaining:,} / {limit:,} left")
    elif remaining is not None:
        parts.append(f"{remaining:,} left")
    elif used is not None and limit is not None:
        parts.append(f"{max(limit - used, 0):,} / {limit:,} left")
    elif limit is not None:
        parts.append(f"monthly limit {limit:,}")

    reset = _reset_epoch(snapshot)
    if reset:
        try:
            parts.append("resets " + time.strftime("%b %d", time.localtime(reset)))
        except Exception:
            pass

    return " · ".join(parts) if parts else "Unknown"


def quota_updated_at(snapshot) -> str:
    """Timestamp string for tooltips showing how fresh the numbers are."""
    updated = _to_int((snapshot or {}).get("updated"))
    if not updated:
        return "No RapidAPI usage recorded yet."
    try:
        return "Updated " + time.strftime("%Y-%m-%d %H:%M", time.localtime(updated))
    except Exception:
        return ""


def quota_reset_at(snapshot) -> str:
    """Reset date string for tooltips, e.g. 'Resets Sep 01' ('' if unknown)."""
    reset = _reset_epoch(snapshot)
    if not reset:
        return ""
    try:
        return "Resets " + time.strftime("%b %d, %Y", time.localtime(reset))
    except Exception:
        return ""
