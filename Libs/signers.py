import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

try:
    from Libs.rapidapi_quota import update_from_headers as _update_quota_headers
except Exception:
    try:
        from rapidapi_quota import update_from_headers as _update_quota_headers
    except Exception:
        _update_quota_headers = None

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAPIDAPI_URL = "https://tiktok-live-studio-api-signer1.p.rapidapi.com/"
DEFAULT_RAPIDAPI_HOST = "tiktok-live-studio-api-signer1.p.rapidapi.com"
LOG_PATH = APP_ROOT / "logs" / "signature_api.log"


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


def _headers(base_url: str) -> dict:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }
    host = urlparse(base_url).netloc or DEFAULT_RAPIDAPI_HOST
    if "rapidapi.com" in host:
        key = _rapidapi_key()
        if key:
            headers["X-RapidAPI-Key"] = key
        headers["X-RapidAPI-Host"] = host
    return headers


def _should_use_api() -> bool:
    base_url = _api_base_url()
    if "rapidapi.com" in urlparse(base_url).netloc:
        return bool(_rapidapi_key())
    return bool(base_url)


def _normalize_headers(value) -> dict[str, str]:
    if isinstance(value, dict) and isinstance(value.get("headers"), dict):
        value = value["headers"]
    if not isinstance(value, dict):
        raise ValueError("signature API response is not an object")
    headers = {
        "x-khronos": _string_header(value.get("x-khronos")),
        "x-ladon": _string_header(value.get("x-ladon")),
        "x-argus": _string_header(value.get("x-argus")),
    }
    if not headers["x-khronos"] or not headers["x-ladon"] or not headers["x-argus"]:
        raise ValueError(
            "signature API response has blank x-khronos/x-ladon/x-argus"
        )
    return headers


def _string_header(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _fallback_khronos(timestamp=None) -> str:
    try:
        if timestamp is not None:
            return str(int(timestamp))
    except (TypeError, ValueError):
        pass
    return str(int(time.time()))


def _post_signatures(payload: dict, *, timeout: int = 20) -> dict[str, str]:
    base_url = _api_base_url()
    started = time.perf_counter()
    response = requests.post(
        urljoin(base_url, "signatures"),
        headers=_headers(base_url),
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
        impersonate="chrome",
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if _update_quota_headers is not None:
        try:
            _update_quota_headers(response.headers)
        except Exception:
            pass
    try:
        data = response.json()
    except Exception:
        data = {"success": False, "error": response.text[:500]}

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

    headers = _normalize_headers(data)
    _log(
        "path=/signatures "
        f"status={response.status_code} elapsed_ms={elapsed_ms} "
        f"khronos={headers['x-khronos']} "
        f"ladon_len={len(headers['x-ladon'])} argus_len={len(headers['x-argus'])} "
        f"params_type={type(payload.get('params')).__name__} "
        f"stub_len={len(str(payload.get('stub') or ''))} "
        f"device_id_set={bool(str(payload.get('device_id') or ''))}"
    )
    return headers


def signature_headers(
    timestamp,
    aid="8311",
    params=None,
    x_ss_stub=None,
    device_id=None,
    local_id=1877999593,
):
    khronos = _fallback_khronos(timestamp)
    if not _should_use_api():
        _log("missing RapidAPI key; refusing to send blank signature headers")
        raise RuntimeError("RapidAPI signer key is required for request signing")

    payload = {
        "timestamp": int(khronos),
        "aid": str(aid),
        "device_id": str(device_id or ""),
        "license_id": int(local_id),
        "params": params or "",
        "stub": x_ss_stub or "",
    }
    try:
        headers = _post_signatures(payload)
        if not headers["x-khronos"]:
            headers["x-khronos"] = khronos
        return headers
    except Exception as exc:
        _log(f"signature API failed; refusing to send blank signatures: {exc}")
        raise RuntimeError(f"signature API failed: {exc}") from exc


def make_ladon(x_khronos: int, local_id: int, aid: str = "8311", **_kwargs):
    return signature_headers(x_khronos, aid=aid, local_id=local_id)["x-ladon"]


def make_x_argus(params=None, stub=None, **kwargs):
    timestamp = kwargs.get("timestamp")
    if timestamp is None:
        timestamp = int(time.time())
    return signature_headers(
        timestamp,
        aid=kwargs.get("aid", "8311"),
        params=params,
        x_ss_stub=stub,
        device_id=kwargs.get("device_id"),
        local_id=kwargs.get("license_id", kwargs.get("local_id", 1877999593)),
    )["x-argus"]


def build_x_argus(params=None, stub=None, **kwargs):
    return {
        "x-argus": make_x_argus(params, stub, **kwargs),
    }


class Ladon:
    @staticmethod
    def encrypt(timestamp: int, license_id: int = 1877999593, aid: int | str = "8311") -> str:
        return make_ladon(timestamp, license_id, str(aid))


class XArgus:
    @staticmethod
    def make(*args, **kwargs):
        return make_x_argus(*args, **kwargs)

    @staticmethod
    def build(*args, **kwargs):
        return build_x_argus(*args, **kwargs)

    get_sign = make


class TikTokSigners:
    ladon = staticmethod(make_ladon)
    x_argus = staticmethod(make_x_argus)
    build_x_argus = staticmethod(build_x_argus)
    signature_headers = staticmethod(signature_headers)

    Ladon = Ladon
    XArgus = XArgus
