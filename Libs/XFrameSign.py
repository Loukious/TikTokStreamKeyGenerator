import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

from DevTools.XFrameSign import (
    XFrameSign as LocalXFrameSign,
    build_frame_sign_input,
    build_plain149,
    frame_sign as local_frame_sign,
)


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAPIDAPI_URL = "https://tiktok-live-studio-api-signer1.p.rapidapi.com/"
DEFAULT_RAPIDAPI_HOST = "tiktok-live-studio-api-signer1.p.rapidapi.com"
LOG_PATH = APP_ROOT / "logs" / "frame_sign_api.log"


def _read_config() -> dict:
    for path in (
        APP_ROOT / "config.json",
        APP_ROOT.parent / "config.json",
        Path.cwd() / "config.json",
    ):
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as fh:
                    value = json.load(fh)
                if isinstance(value, dict):
                    return value
        except Exception:
            continue
    return {}


def _config_value(*names: str) -> str:
    config = _read_config()
    for name in names:
        value = os.environ.get(name)
        if value:
            return str(value).strip()
        value = config.get(name)
        if value:
            return str(value).strip()
    return ""


def _api_base_url() -> str:
    value = _config_value("signer_api_url", "TIKTOK_SIGNER_API_URL")
    if not value:
        value = DEFAULT_RAPIDAPI_URL
    return value if value.endswith("/") else value + "/"


def _rapidapi_key() -> str:
    return _config_value("rapidapi_key", "RAPIDAPI_KEY")


def _log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except Exception:
        pass


def _json_payload(value):
    if isinstance(value, (str, bytes)):
        return json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
    return dict(value)


def _headers(base_url: str) -> dict:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }
    parsed = urlparse(base_url)
    host = parsed.netloc or DEFAULT_RAPIDAPI_HOST
    if "rapidapi.com" in host:
        key = _rapidapi_key()
        if key:
            headers["X-RapidAPI-Key"] = key
        headers["X-RapidAPI-Host"] = host
    return headers


def _post_json(path: str, payload: dict, *, timeout: int = 20) -> dict:
    base_url = _api_base_url()
    started = time.perf_counter()
    response = requests.post(
        urljoin(base_url, path.lstrip("/")),
        headers=_headers(base_url),
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
        impersonate="chrome",
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    try:
        data = response.json()
    except Exception:
        data = {"success": False, "error": response.text[:500]}
    _log(f"path={path} status={response.status_code} elapsed_ms={elapsed_ms} keys={list(data) if isinstance(data, dict) else type(data).__name__}")
    response.raise_for_status()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(str(data.get("error") or data))
    return data


def _normalize_sign_result(value, template=None) -> dict:
    if isinstance(value, dict) and isinstance(value.get("signResult"), dict):
        value = value["signResult"]
    if not isinstance(value, dict):
        raise ValueError("frameSign response item is not an object")
    result = {
        "frametype": str(value.get("frametype") or (template or {}).get("frametype", "2")),
        "lid": str(value.get("lid", "1877999593")),
        "signinfo": str(value.get("signinfo", "")),
        "signvalue": str(value.get("signvalue", "")),
        "signversion": str(value.get("signversion", "1.0")),
    }
    if not result["signinfo"] or not result["signvalue"]:
        raise ValueError("frameSign response has blank signinfo/signvalue")
    return result


def _normalize_batch_item(item, template=None):
    if not isinstance(item, dict):
        return None
    raw_ts = item.get("timestamp")
    if raw_ts is None and isinstance(item.get("signResult"), dict):
        raw_ts = item["signResult"].get("timestamp")
    try:
        timestamp = int(raw_ts)
    except (TypeError, ValueError):
        return None
    out = {
        "timestamp": timestamp,
        "signResult": _normalize_sign_result(item, template),
    }
    if item.get("startup"):
        out["startup"] = True
    return out


def _extract_batch_items(data: dict, template=None) -> list[dict]:
    raw_items = []
    startup = data.get("startup") if isinstance(data, dict) else None
    if isinstance(startup, dict):
        startup = dict(startup)
        startup["startup"] = True
        raw_items.append(startup)
    if isinstance(data, dict):
        for name in ("signatures", "results", "data"):
            value = data.get(name)
            if isinstance(value, list):
                raw_items.extend(value)
                break
    elif isinstance(data, list):
        raw_items.extend(data)

    items = []
    for raw in raw_items:
        try:
            item = _normalize_batch_item(raw, template)
        except Exception as exc:
            _log(f"batch item skipped: {exc}")
            item = None
        if item:
            items.append(item)
    return items


def _should_use_api() -> bool:
    base_url = _api_base_url()
    if "rapidapi.com" in urlparse(base_url).netloc:
        return bool(_rapidapi_key())
    return bool(base_url)


def frame_sign(input_json, **kwargs) -> dict:
    payload = _json_payload(input_json)
    if _should_use_api() and not kwargs:
        try:
            data = _post_json("/framesign", {"payload": payload})
            result = _normalize_sign_result(data, payload)
            _log(f"single ok signinfo_len={len(result['signinfo'])} signvalue_len={len(result['signvalue'])}")
            return result
        except Exception as exc:
            _log(f"single api failed; using local: {exc}")
    return local_frame_sign(payload, **kwargs)


def frame_sign_batch(
    input_json,
    *,
    start_timestamp=None,
    count=10,
    step_seconds=30,
    include_startup=True,
    **kwargs,
) -> list[dict]:
    template = _json_payload(input_json)
    if start_timestamp is None:
        start_timestamp = int(time.time())
    start_timestamp = int(start_timestamp)
    count = max(1, int(count))
    step_seconds = max(1, int(step_seconds))

    if _should_use_api() and not kwargs:
        payload = {
            "payload": template,
            "start_timestamp": start_timestamp,
            "count": count,
            "step_seconds": step_seconds,
            "include_startup": bool(include_startup),
        }
        try:
            data = _post_json("/framesign/batch", payload, timeout=30)
            items = _extract_batch_items(data, template)
            if items:
                _log(f"batch ok requested={count} got={len(items)} first_ts={items[0]['timestamp']} last_ts={items[-1]['timestamp']}")
                return items
            raise ValueError(f"no usable batch items in response keys={list(data) if isinstance(data, dict) else type(data).__name__}")
        except Exception as exc:
            _log(f"batch api failed; using local: {exc}")

    items = []
    if include_startup:
        startup_payload = dict(template)
        startup_payload["timestamp"] = str(start_timestamp)
        items.append(
            {
                "timestamp": start_timestamp,
                "signResult": local_frame_sign(startup_payload, **kwargs),
                "startup": True,
            }
        )

    for index in range(count):
        timestamp = start_timestamp + index * step_seconds
        payload = dict(template)
        payload["timestamp"] = str(timestamp)
        items.append(
            {
                "timestamp": timestamp,
                "signResult": local_frame_sign(payload, **kwargs),
            }
        )
    return items


class XFrameSign(LocalXFrameSign):
    sign = staticmethod(frame_sign)
    make = staticmethod(frame_sign)
    batch = staticmethod(frame_sign_batch)
    frame_sign_input = staticmethod(build_frame_sign_input)
    plain149 = staticmethod(build_plain149)
