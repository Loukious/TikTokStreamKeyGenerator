import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAPIDAPI_URL = "https://tiktok-live-studio-api-signer1.p.rapidapi.com/"
DEFAULT_RAPIDAPI_HOST = "tiktok-live-studio-api-signer1.p.rapidapi.com"
LOG_PATH = APP_ROOT / "logs" / "frame_sign_api.log"
FRAME_SIGN_CACHE_SECONDS = 300
FRAME_SIGN_CACHE_REFRESH_MARGIN_SECONDS = 60
FRAME_SIGN_BATCH_STEP_SECONDS = 1
FRAME_SIGN_NEAREST_TOLERANCE_SECONDS = 1
_CACHE_LOCK = threading.Lock()
_CACHE = {}


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
    if response.status_code >= 400:
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("error") or data.get("message") or data.get("detail") or "")
        detail = detail.strip() or response.text[:500].strip()
        raise RuntimeError(
            f"RapidAPI signer HTTP {response.status_code}: {detail or 'request rejected'}"
        )
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


def _payload_timestamp(payload: dict) -> int:
    try:
        return int(payload.get("timestamp") or time.time())
    except (TypeError, ValueError):
        return int(time.time())


def _select_batch_item(items: list[dict], target_timestamp: int) -> dict | None:
    if not items:
        return None
    by_ts = {}
    for item in items:
        try:
            by_ts[int(item["timestamp"])] = item
        except (KeyError, TypeError, ValueError):
            continue
    if not by_ts:
        return None
    if target_timestamp in by_ts:
        return by_ts[target_timestamp]
    nearest_ts = min(by_ts, key=lambda value: abs(value - target_timestamp))
    if abs(nearest_ts - target_timestamp) > FRAME_SIGN_NEAREST_TOLERANCE_SECONDS:
        return None
    return by_ts[nearest_ts]


def _cache_key(payload: dict) -> tuple:
    return (
        str(payload.get("aid", "8311")),
        str(payload.get("uid", "")),
        str(payload.get("did", payload.get("device_id", ""))),
        str(payload.get("roomid", payload.get("room_id", ""))),
        str(payload.get("frametype", "2")),
    )


def _store_cache(key: tuple, items: list[dict]) -> int:
    stored = {}
    max_ts = 0
    for item in items:
        try:
            timestamp = int(item["timestamp"])
            result = item["signResult"]
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(result, dict):
            continue
        stored[timestamp] = result
        max_ts = max(max_ts, timestamp)

    with _CACHE_LOCK:
        current = _CACHE.setdefault(key, {"items": {}, "until": 0, "refreshing": False})
        current["items"].update(stored)
        current["until"] = max(int(current.get("until", 0)), max_ts)
        current["refreshing"] = False
    return len(stored)


def _cached_result(key: tuple, target_timestamp: int) -> dict | None:
    with _CACHE_LOCK:
        state = _CACHE.get(key) or {}
        items = dict(state.get("items") or {})

    if not items:
        return None
    if target_timestamp in items:
        return items[target_timestamp]

    nearest_ts = min(items, key=lambda value: abs(value - target_timestamp))
    if abs(nearest_ts - target_timestamp) <= FRAME_SIGN_NEAREST_TOLERANCE_SECONDS:
        return items[nearest_ts]
    return None


def _cache_until(key: tuple) -> int:
    with _CACHE_LOCK:
        return int((_CACHE.get(key) or {}).get("until", 0))


def _begin_refresh(key: tuple) -> bool:
    with _CACHE_LOCK:
        state = _CACHE.setdefault(key, {"items": {}, "until": 0, "refreshing": False})
        if state.get("refreshing"):
            return False
        state["refreshing"] = True
        return True


def _clear_refreshing(key: tuple) -> None:
    with _CACHE_LOCK:
        state = _CACHE.setdefault(key, {"items": {}, "until": 0, "refreshing": False})
        state["refreshing"] = False


def _fetch_batch_cache(payload: dict, start_timestamp: int) -> int:
    key = _cache_key(payload)
    request_payload = dict(payload)
    request_payload["timestamp"] = str(int(start_timestamp))
    data = _post_json(
        "/framesign/batch",
        {
            "payload": request_payload,
            "start_timestamp": int(start_timestamp),
            "duration_seconds": FRAME_SIGN_CACHE_SECONDS,
            "step_seconds": FRAME_SIGN_BATCH_STEP_SECONDS,
        },
        timeout=30,
    )
    items = _extract_batch_items(data, request_payload)
    stored = _store_cache(key, items)
    _log(
        "batch-cache ok "
        f"start_ts={int(start_timestamp)} stored={stored} "
        f"until={_cache_until(key)}"
    )
    if not stored:
        raise ValueError("frameSign batch returned no usable items")
    return stored


def _refresh_cache_background(payload: dict, start_timestamp: int) -> None:
    key = _cache_key(payload)
    if not _begin_refresh(key):
        return

    def refresh():
        try:
            _fetch_batch_cache(payload, start_timestamp)
        except Exception as exc:
            _clear_refreshing(key)
            _log(f"batch-cache background failed: {exc}")

    threading.Thread(target=refresh, daemon=True).start()


def _frame_sign_from_cache(payload: dict) -> dict:
    target_timestamp = _payload_timestamp(payload)
    key = _cache_key(payload)

    result = _cached_result(key, target_timestamp)
    if result is not None:
        if _cache_until(key) - target_timestamp <= FRAME_SIGN_CACHE_REFRESH_MARGIN_SECONDS:
            _refresh_cache_background(payload, _cache_until(key) + 1)
        _log(f"batch-cache hit target_ts={target_timestamp} until={_cache_until(key)}")
        return result

    if not _begin_refresh(key):
        deadline = time.time() + 3
        while time.time() < deadline:
            time.sleep(0.05)
            result = _cached_result(key, target_timestamp)
            if result is not None:
                _log(f"batch-cache waited target_ts={target_timestamp} until={_cache_until(key)}")
                return result
        raise TimeoutError(f"frameSign cache refresh is still pending for timestamp={target_timestamp}")

    try:
        _fetch_batch_cache(payload, target_timestamp)
    except Exception:
        _clear_refreshing(key)
        raise

    result = _cached_result(key, target_timestamp)
    if result is None:
        raise ValueError(f"no frameSign cache item near timestamp={target_timestamp}")
    _log(f"batch-cache miss-filled target_ts={target_timestamp} until={_cache_until(key)}")
    return result


def _frame_sign_from_api(payload: dict) -> dict:
    data = _post_json("/framesign", {"payload": payload}, timeout=20)
    result = _normalize_sign_result(data, payload)
    _log(f"direct ok target_ts={_payload_timestamp(payload)}")
    return result


def frame_sign(input_json, **kwargs) -> dict:
    payload = _json_payload(input_json)
    if kwargs:
        raise RuntimeError("API frame signing does not accept local signer options")
    if not _should_use_api():
        raise RuntimeError("RapidAPI frame-signing key is required")
    try:
        return _frame_sign_from_cache(payload)
    except Exception as exc:
        _log(f"batch-cache api failed; no local fallback in production mode: {exc}")
        raise


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

    if kwargs:
        raise RuntimeError("API frame-signing does not accept local signer options")
    if not _should_use_api():
        raise RuntimeError("RapidAPI frame-signing key is required")

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
        _log(f"batch api failed; no local fallback in production mode: {exc}")
        raise


class XFrameSign:
    sign = staticmethod(frame_sign)
    make = staticmethod(frame_sign)
    batch = staticmethod(frame_sign_batch)
