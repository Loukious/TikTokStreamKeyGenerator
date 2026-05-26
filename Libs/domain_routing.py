import time
import os
import re

import requests
try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None


def _new_http_session():
    if curl_requests is not None:
        return curl_requests.Session(impersonate="chrome")
    return requests.session()


DEFAULT_TIKTOK_USER_AGENT = os.getenv(
    "TIKTOK_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) TikTokLIVEStudio/1.27.0 Chrome/136.0.7103.59 "
    "Electron/36.4.0-alpha.17 "
    "TTElectron/36.4.0-alpha.17 Safari/537.36",
)


def _load_tnc_endpoints():
    configured_endpoints = os.getenv("TIKTOK_TNC_ENDPOINTS", "").strip()
    if configured_endpoints:
        endpoints = [item.strip() for item in configured_endpoints.split(",") if item.strip()]
        if endpoints:
            return tuple(endpoints)

    return (
        "https://tnc0-normal-alisg.tiktokv.com/get_domains/v4/",
        "https://tnc16-platform-useast1a.tiktokv.com/get_domains/v4/",
        "https://tnc16-platform-alisg.tiktokv.com/get_domains/v4/",
    )


TNC_DISCOVERY_ENDPOINTS = _load_tnc_endpoints()

TNC_DISCOVERY_PARAMS = {
    "aid": "8311",
    "ttwebview_version": "1130022001",
    "device_platform": "win",
    "tnc_src": "6",
}

_DISPATCH_CACHE = {
    "fetched_at": 0.0,
    "strategy_maps": None,
}

_CACHE_TTL_SECONDS = 300

_NTP_SYNC_STATE = {
    "time_updated": False,
    "half_rtt_ms": float("inf"),
    "server_time_ms": 0.0,
    "perf_updated_ms": 0.0,
    "path": "",
    "log_id": "",
}


def _perf_now_ms():
    return time.perf_counter() * 1000.0


def get_tiktok_user_agent(session=None):
    if session is not None:
        candidate = session.headers.get("user-agent") or session.headers.get("User-Agent")
        if candidate and not candidate.lower().startswith("python-requests/"):
            return candidate

    return DEFAULT_TIKTOK_USER_AGENT


def _live_studio_version_from_user_agent(session=None):
    user_agent = get_tiktok_user_agent(session)
    match = re.search(r"TikTokLIVEStudio/([0-9]+(?:\.[0-9]+){1,3})", user_agent)
    if match:
        return match.group(1)
    return "1.27.0"


def build_common_headers(session=None):
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US",
        "user-agent": get_tiktok_user_agent(session),
        "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


def attach_webcast_ntp_t0(headers):
    t0_ms = _perf_now_ms()
    headers["webcast-ntp-t0"] = f"{t0_ms:.3f}"
    return t0_ms


def update_ntp_from_response(t0_ms, response):
    if response is None:
        return False

    try:
        t2_header = response.headers.get("webcast-ntp-t2")
        t3_header = response.headers.get("webcast-ntp-t3")
        if not t2_header or not t3_header:
            return False

        t2_ms = float(t2_header)
        t3_ms = float(t3_header)
        t4_ms = _perf_now_ms()

        half_rtt_ms = (t4_ms - t0_ms - (t3_ms - t2_ms)) / 2.0
        server_time_ms = t3_ms + half_rtt_ms
        if server_time_ms <= 0:
            return False

        if (
            not _NTP_SYNC_STATE["time_updated"]
            or (half_rtt_ms < _NTP_SYNC_STATE["half_rtt_ms"] and half_rtt_ms <= 500)
        ):
            _NTP_SYNC_STATE["time_updated"] = True
            _NTP_SYNC_STATE["half_rtt_ms"] = half_rtt_ms
            _NTP_SYNC_STATE["server_time_ms"] = server_time_ms
            _NTP_SYNC_STATE["perf_updated_ms"] = t4_ms
            _NTP_SYNC_STATE["path"] = getattr(response.request, "url", "")
            _NTP_SYNC_STATE["log_id"] = response.headers.get("x-tt-logid", "")
        return True
    except Exception:
        return False


def get_synced_unix_seconds():
    if _NTP_SYNC_STATE["time_updated"]:
        elapsed_ms = _perf_now_ms() - _NTP_SYNC_STATE["perf_updated_ms"]
        now_ms = _NTP_SYNC_STATE["server_time_ms"] + elapsed_ms
        if now_ms > 0:
            return int(now_ms / 1000.0)

    return int(time.time())


def _extract_strategy_maps(response_json):
    data = response_json.get("data") if isinstance(response_json, dict) else None
    actions = data.get("ttnet_dispatch_actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return []

    # Live Studio's domain response contains both load-balancing candidate rules
    # and final IDC rewrite rules. For this tool we want the deterministic final
    # host, for example webcast.tiktokv.com -> webcast16-normal-c-alisg.tiktokv.com.
    # Turning candidate rules into mappings can incorrectly select webcast19 or a
    # region host before the IDC rewrite is applied, so keep direct string maps only.
    strategy_maps = []
    for action in sorted(actions, key=lambda item: int(item.get("act_priority") or 0)):
        if not isinstance(action, dict):
            continue
        params = action.get("param")
        if not isinstance(params, dict):
            continue
        strategy_info = params.get("strategy_info")
        if not isinstance(strategy_info, dict) or not strategy_info:
            continue

        direct_map = {
            _canonicalize_tiktok_host(key): _canonicalize_tiktok_host(value)
            for key, value in strategy_info.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if direct_map:
            strategy_maps.append(direct_map)

    return strategy_maps


def _tnc_discovery_params(session):
    params = dict(TNC_DISCOVERY_PARAMS)
    params["version_code"] = _live_studio_version_from_user_agent(session)
    device_id = _session_cookie_value(session, "device_id") or _session_cookie_value(session, "ttwid") or ""
    if device_id:
        params["device_id"] = str(device_id)
    region = _session_cookie_value(session, "store-country-code") or ""
    if region:
        params["region"] = str(region).lower()
    return params


def _fetch_strategy_maps(session, timeout):
    headers = build_common_headers(session)
    for endpoint in TNC_DISCOVERY_ENDPOINTS:
        try:
            response = session.get(
                endpoint,
                params=_tnc_discovery_params(session),
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            strategy_maps = _extract_strategy_maps(response.json())
            if strategy_maps:
                return strategy_maps
        except Exception:
            continue

    return []


def _get_strategy_maps(session, timeout=12):
    now = time.time()
    cached = _DISPATCH_CACHE.get("strategy_maps")
    cached_at = _DISPATCH_CACHE.get("fetched_at", 0.0)
    if cached and now - cached_at < _CACHE_TTL_SECONDS:
        return cached

    fresh_maps = _fetch_strategy_maps(session, timeout)
    if fresh_maps:
        _DISPATCH_CACHE["strategy_maps"] = fresh_maps
        _DISPATCH_CACHE["fetched_at"] = now
        return fresh_maps

    return cached or []


def _session_cookie_value(session, name):
    if session is None:
        return None

    try:
        value = session.cookies.get(name)
        if value:
            return value
    except Exception:
        pass

    cookie_header = session.headers.get("cookie") or session.headers.get("Cookie")
    if not cookie_header:
        return None

    for chunk in cookie_header.split(";"):
        key, separator, value = chunk.strip().partition("=")
        if separator and key == name:
            return value
    return None


def _canonical_idc_segment(idc):
    value = str(idc or "").strip().lower()
    if not value:
        return ""

    aliases = {
        "alisg": "c-alisg",
    }
    return aliases.get(value, value)


def _canonicalize_tiktok_host(host):
    value = str(host or "").strip().lower()
    if not value:
        return value

    if value.startswith("webcast16-normal-alisg."):
        return "webcast16-normal-c-alisg.tiktokv.com"

    if value.startswith("api16-normal-alisg."):
        return "api16-normal-c-alisg.tiktokv.com"

    if value.startswith("webcast16-ws-alisg."):
        return "webcast16-ws-c-alisg.tiktokv.com"

    return value


def _suffix_for_idc(idc_segment, target_idc="", store_country=""):
    segment = str(idc_segment or "").lower()
    target_idc = str(target_idc or "").lower()
    store_country = str(store_country or "").lower()

    if segment == "c-alisg":
        return "tiktokv.com"

    if segment.startswith("useast"):
        return "tiktokv.us"

    if segment.startswith("no"):
        return "tiktokv.eu"

    eu_regions = {
        "at", "be", "bg", "ch", "cy", "cz", "de", "dk", "ee", "es", "fi", "fr", "gb",
        "gr", "hr", "hu", "ie", "is", "it", "li", "lt", "lu", "lv", "mt", "nl", "no",
        "pl", "pt", "ro", "se", "si", "sk",
    }

    if target_idc.startswith("eu") or store_country in eu_regions:
        return "tiktokv.eu"

    return "tiktokv.com"


def _authenticated_idc_segment(session):
    return _canonical_idc_segment(_session_cookie_value(session, "store-idc"))


def _authenticated_webcast_host(session):
    idc_segment = _authenticated_idc_segment(session)
    if not idc_segment:
        return None

    target_idc = _session_cookie_value(session, "tt-target-idc") or ""
    store_country = _session_cookie_value(session, "store-country-code") or ""
    suffix = _suffix_for_idc(idc_segment, target_idc, store_country)
    return _canonicalize_tiktok_host(f"webcast16-normal-{idc_segment}.{suffix}")


def _region_webcast_host(session):
    store_country = str(_session_cookie_value(session, "store-country-code") or "").strip().lower()
    target_idc = str(_session_cookie_value(session, "tt-target-idc") or "").strip().lower()

    eu_regions = {
        "at", "be", "bg", "ch", "cy", "cz", "de", "dk", "ee", "es", "fi", "fr", "gb",
        "gr", "hr", "hu", "ie", "is", "it", "li", "lt", "lu", "lv", "mt", "nl", "no",
        "pl", "pt", "ro", "se", "si", "sk",
    }

    if target_idc.startswith("eu") or store_country in eu_regions:
        return "webcast16-normal-no1a.tiktokv.eu"

    if store_country == "us" or target_idc.startswith("useast"):
        return "webcast16-normal-useast5.tiktokv.us"

    return None


def _authenticated_api_host(session):
    idc_segment = _authenticated_idc_segment(session)
    if not idc_segment:
        return None

    target_idc = _session_cookie_value(session, "tt-target-idc") or ""
    store_country = _session_cookie_value(session, "store-country-code") or ""
    suffix = _suffix_for_idc(idc_segment, target_idc, store_country)
    return _canonicalize_tiktok_host(f"api16-normal-{idc_segment}.{suffix}")


def resolve_host(seed_host, session=None, timeout=12, max_hops=8):
    seed_host = _canonicalize_tiktok_host(seed_host)

    if seed_host in {"webcast-normal.tiktokv.com", "webcast.tiktokv.com"}:
        authenticated_host = _authenticated_webcast_host(session)
        if authenticated_host:
            return authenticated_host

    if seed_host in {"api.tiktokv.com", "api16-normal.tiktokv.com"}:
        authenticated_host = _authenticated_api_host(session)
        if authenticated_host:
            return authenticated_host

    close_session = session is None
    client = session if session is not None else _new_http_session()
    try:
        strategy_maps = _get_strategy_maps(client, timeout=timeout)

        current_host = seed_host
        for _ in range(max_hops):
            next_host = None
            for strategy_map in strategy_maps:
                candidate = strategy_map.get(current_host)
                if candidate:
                    next_host = _canonicalize_tiktok_host(candidate)
                    break

            if not next_host or next_host == current_host:
                break
            current_host = next_host

        return _canonicalize_tiktok_host(current_host)
    finally:
        if close_session:
            client.close()


def _dedupe_hosts(hosts):
    seen = set()
    out = []
    for host in hosts:
        host = _canonicalize_tiktok_host(host)
        if host and host not in seen:
            seen.add(host)
            out.append(host)
    return out


def build_endpoint(seed_host, path, session=None, timeout=12):
    host = resolve_host(seed_host, session=session, timeout=timeout)
    normalized_path = "/" + path.lstrip("/")
    return f"https://{host}{normalized_path}"


def resolve_webcast_base_url(session=None, timeout=12):
    host = resolve_host("webcast-normal.tiktokv.com", session=session, timeout=timeout)
    return f"https://{host}/"


def resolve_log_base_url(session=None, timeout=12):
    host = resolve_host("log.tiktokv.com", session=session, timeout=timeout)
    return f"https://{host}/"


def resolve_api_base_url(session=None, timeout=12):
    host = resolve_host("api.tiktokv.com", session=session, timeout=timeout)
    return f"https://{host}/"


def resolve_api_host_candidates(session=None, timeout=12):
    candidates = [
        _authenticated_api_host(session),
    ]

    seed_candidates = [
        "api.tiktokv.com",
        "api16-normal-c-alisg.tiktokv.com",
        "api16-normal-no1a.tiktokv.eu",
        "api16-normal-useast8.tiktokv.us",
        "api16-normal-useast5.tiktokv.us",
    ]

    for seed_host in seed_candidates:
        try:
            candidates.append(resolve_host(seed_host, session=session, timeout=timeout))
        except Exception:
            candidates.append(seed_host)

    return _dedupe_hosts(candidates)


def resolve_webcast_host_candidates(session=None, timeout=12):
    # Prefer the account/IDC route over UI region. A user may choose priority_region=fr
    # while their logged-in session is stored in alisg; forcing no1a causes 403s.
    authenticated = _authenticated_webcast_host(session)
    if authenticated:
        return _dedupe_hosts([authenticated, _region_webcast_host(session)])

    candidates = []
    seed_candidates = [
        "webcast-normal.tiktokv.com",
        "webcast.tiktokv.com",
        "webcast16-normal.tiktokv.com",
    ]

    for seed_host in seed_candidates:
        try:
            candidates.append(resolve_host(seed_host, session=session, timeout=timeout))
        except Exception:
            candidates.append(seed_host)

    # Region-based fallback is last-resort only, never first.
    candidates.append(_region_webcast_host(session))

    return _dedupe_hosts(candidates)
