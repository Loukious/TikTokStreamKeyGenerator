import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import urllib.parse


RAPIDAPI_SIGNER_BASE_URL = "https://tiktok-live-studio-api-signer.p.rapidapi.com"
RAPIDAPI_SIGNER_HOST = "tiktok-live-studio-api-signer.p.rapidapi.com"
RAPIDAPI_SIGNER_TIMEOUT_SECONDS = 15


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _candidate_config_paths() -> list[Path]:
    base = _runtime_base_dir()
    paths = [
        base / "config.json",
        base.parent / "config.json",
        Path.cwd() / "config.json",
    ]

    seen = set()
    out = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            out.append(path)
    return out


def _rapidapi_key() -> str:
    for env_name in ("RAPIDAPI_KEY", "RAPID_API_KEY", "TIKTOK_SIGNER_RAPIDAPI_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    for path in _candidate_config_paths():
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            continue

        if isinstance(data, dict):
            value = str(data.get("rapidapi_key", "") or "").strip()
            if value:
                return value

    return ""


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, bytearray):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _normalize_params_for_api(params: Any) -> str:
    """
    Return the exact query-string form that the remote signer should hash.

    Important:
    - If params is already a URL or query string, preserve its existing encoding/order.
    - If params is a dict/list/tuple, encode it using urllib.parse.urlencode default
      behavior, matching the old local XArgus normalizer and requests-style query encoding.
    """
    if params is None:
        return ""

    if isinstance(params, bytes):
        params = params.decode("utf-8", errors="strict")

    if isinstance(params, str):
        value = params.strip()
        split = urllib.parse.urlsplit(value)

        if split.query:
            return split.query

        return value[1:] if value.startswith("?") else value

    if isinstance(params, (dict, list, tuple)):
        return urllib.parse.urlencode(params, doseq=True)

    return str(params)


def _extract_signature(response: requests.Response) -> str:
    if not (200 <= response.status_code < 300):
        return ""

    text = response.text.strip()
    if not text:
        return ""

    try:
        data = response.json()
    except ValueError:
        return text

    if not isinstance(data, dict):
        return ""

    if data.get("success") is False:
        return ""

    signature = data.get("signature") or data.get("x-argus") or data.get("x_argus") or ""
    return str(signature).strip()


def make_x_argus(params=None, stub=None, **kwargs) -> str:
    api_key = _rapidapi_key()
    if not api_key:
        return ""

    payload = {
        "params": _normalize_params_for_api(params),
    }

    if stub is not None:
        payload["stub"] = _jsonable(stub)

    for key, value in kwargs.items():
        if value is not None:
            payload[str(key)] = _jsonable(value)

    try:
        response = requests.post(
            f"{RAPIDAPI_SIGNER_BASE_URL}/xargus",
            headers={
                "content-type": "application/json",
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": RAPIDAPI_SIGNER_HOST,
            },
            json=payload,
            timeout=RAPIDAPI_SIGNER_TIMEOUT_SECONDS,
        )
        return _extract_signature(response)
    except Exception:
        return ""


class XArgus:
    @staticmethod
    def make(*args, **kwargs) -> str:
        return make_x_argus(*args, **kwargs)

    get_sign = make
