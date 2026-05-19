import json
import os
import sys
from pathlib import Path

import requests

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

    signature = data.get("signature") or data.get("x-ladon") or data.get("x_ladon") or ""
    return str(signature).strip()


def make_ladon(x_khronos: int, local_id: int, aid: str = "8311", prefix16=None) -> str:
    api_key = _rapidapi_key()
    if not api_key:
        return ""

    payload = {
        "timestamp": int(x_khronos),
        "license_id": int(local_id),
        "aid": str(aid),
    }

    try:
        response = requests.post(
            f"{RAPIDAPI_SIGNER_BASE_URL}/xladon",
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


def ladon_encrypt(timestamp: int, license_id: int = 1877999593, aid: int | str = "8311", random_bytes=None) -> str:
    prefix16 = None
    if random_bytes is not None:
        try:
            if len(random_bytes) != 4:
                return ""
            prefix16 = int.from_bytes(random_bytes[:2], "little")
        except Exception:
            return ""
    return make_ladon(timestamp, license_id, str(aid), prefix16=prefix16)


class Ladon:
    @staticmethod
    def encrypt(timestamp: int, license_id: int = 1877999593, aid: int | str = "8311") -> str:
        return make_ladon(timestamp, license_id, str(aid))
