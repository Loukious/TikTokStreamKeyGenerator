import json
import hashlib
import os
import random
import string
import uuid

import requests

from .log_encrypt_codec import DEFAULT_LOG_ENCRYPT_KEY, log_encrypt
from .domain_routing import (
    attach_webcast_ntp_t0,
    build_common_headers,
    build_endpoint,
    update_ntp_from_response,
)


DEVICE_REGISTER_PATH = "/service/2/desktop/device_register/"
LIVE_STUDIO_UPDATE_ENDPOINT = os.getenv(
    "TIKTOK_TRON_UPDATE_ENDPOINT",
    "https://tron-sg.bytelemon.com/api/sdk/check_update",
)

DESKTOP_DEVICE_MODELS = (
    "z790 taichi lite",
    "rog strix b760-f",
    "b550 aorus elite",
    "prime z690-p",
    "tomahawk x670e",
)

WINDOWS_OS_VERSIONS = (
    "10.0.19045",
    "10.0.22621",
    "10.0.22631",
    "10.0.26100",
    "10.0.26200",
)

COMMON_RESOLUTIONS = (
    "1920x1080",
    "2560x1440",
    "1600x900",
    "1366x768",
)

TIMEZONE_PROFILES = (
    {
        "timezone_name": "Africa/Tunis",
        "time_zone": "GMT+0100",
        "tz_name": "Central European Standard Time",
        "tz_offset": 3600,
    },
    {
        "timezone_name": "Europe/Berlin",
        "time_zone": "GMT+0100",
        "tz_name": "W. Europe Standard Time",
        "tz_offset": 3600,
    },
    {
        "timezone_name": "Europe/London",
        "time_zone": "GMT+0000",
        "tz_name": "GMT Standard Time",
        "tz_offset": 0,
    },
    {
        "timezone_name": "America/New_York",
        "time_zone": "GMT-0500",
        "tz_name": "Eastern Standard Time",
        "tz_offset": -18000,
    },
    {
        "timezone_name": "Asia/Kolkata",
        "time_zone": "GMT+0530",
        "tz_name": "India Standard Time",
        "tz_offset": 19800,
    },
)


def fetch_live_studio_latest_version(session=None):
    params = {
        "pid": "7393277106664249610",
        "uid": "0",
        "branch": "studio/release/stable",
        "buildId": "0",
    }

    close_session = session is None
    client = session if session is not None else requests.session()
    try:
        with client.get(
            LIVE_STUDIO_UPDATE_ENDPOINT,
            params=params,
            headers=build_common_headers(client),
            timeout=15,
        ) as response:
            return response.json()["data"]["manifest"]["win32"]["version"]
    except Exception:
        return "0.99.0"
    finally:
        if close_session:
            client.close()


def build_live_studio_browser_version(version):
    return (
        "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) TikTokLIVEStudio/{version} Chrome/136.0.7103.59 "
        "Electron/36.4.0-alpha.17 "
        "TTElectron/36.4.0-alpha.17 Safari/537.36"
    )


def get_device_register_endpoint(session=None):
    return build_endpoint(
        "log.tiktokv.com",
        DEVICE_REGISTER_PATH,
        session=session,
    )


def generate_private_pc_identifiers():
    serial_chars = string.ascii_lowercase + string.digits
    pc_serial = "".join(random.choices(serial_chars, k=20))
    pc_uuid = f"{uuid.uuid4()}-{''.join(random.choices(serial_chars, k=16))}"
    return pc_uuid, pc_serial


def generate_random_mac():
    octets = [random.randint(0, 255) for _ in range(6)]
    octets[0] = (octets[0] | 0x02) & 0xFE
    return ":".join(f"{value:02x}" for value in octets)


def _split_resolution(resolution):
    width, height = resolution.split("x", 1)
    return width, height


def generate_desktop_fingerprint():
    timezone_profile = random.choice(TIMEZONE_PROFILES)
    resolution = random.choice(COMMON_RESOLUTIONS)
    screen_width, screen_height = _split_resolution(resolution)
    return {
        "mac": generate_random_mac(),
        "os_version": random.choice(WINDOWS_OS_VERSIONS),
        "device_model": random.choice(DESKTOP_DEVICE_MODELS),
        "timezone_name": timezone_profile["timezone_name"],
        "time_zone": timezone_profile["time_zone"],
        "tz_name": timezone_profile["tz_name"],
        "tz_offset": timezone_profile["tz_offset"],
        "resolution": resolution,
        "screen_width": screen_width,
        "screen_height": screen_height,
    }


def _build_device_register_query_params(version, pc_uuid, pc_serial, browser_version, fingerprint):
    return [
        ("aid", "8311"),
        ("channel", "studio"),
        ("os", "Windows"),
        ("os_version", fingerprint["os_version"]),
        ("device_type", "PC"),
        ("device_platform", "PC"),
        ("version_code", version),
        ("pc_uuid", pc_uuid),
        ("pc_serial", pc_serial),
        ("aid", "8311"),
        ("app_name", "tiktok_live_studio"),
        ("device_id", "0"),
        ("install_id", "0"),
        ("channel", "studio"),
        ("version_code", version),
        ("device_platform", "windows"),
        ("timezone_name", fingerprint["timezone_name"]),
        ("screen_width", fingerprint["screen_width"]),
        ("screen_height", fingerprint["screen_height"]),
        ("browser_language", "en-US"),
        ("browser_platform", "Win32"),
        ("browser_name", "Mozilla"),
        ("browser_version", browser_version),
        ("language", "en"),
        ("app_language", "en"),
        ("webcast_language", "en"),
        ("webcast_sdk_version", version.replace(".", "")),
        ("live_mode", "6"),
    ]


def _build_device_register_payload(version, pc_uuid, pc_serial, fingerprint):
    return {
        "header": {
            "device_id": 0,
            "install_id": 0,
            "os": "Windows",
            "device_platform": "PC",
            "sdk_version": "1.0.2",
            "aid": "8311",
            "mc": fingerprint["mac"],
            "channel": "studio",
            "package": "tiktok_live_studio",
            "language": "en-US",
            "app_version": version,
            "os_version": fingerprint["os_version"],
            "device_model": fingerprint["device_model"],
            "time_zone": fingerprint["time_zone"],
            "tz_name": fingerprint["tz_name"],
            "tz_offset": fingerprint["tz_offset"],
            "resolution": fingerprint["resolution"],
            "app_region": "",
            "app_language": "",
            "display_name": "tiktok_live_studio",
            "pc_uuid": pc_uuid,
            "pc_serial": pc_serial,
        },
        "_gen_time": 0,
        "magic_tag": "ss_app_log",
    }


def register_desktop_device_identifiers(session=None, timeout=25):
    close_session = session is None
    client = session if session is not None else requests.session()
    try:
        client.headers.update(build_common_headers(client))

        version = fetch_live_studio_latest_version(client)
        pc_uuid, pc_serial = generate_private_pc_identifiers()
        fingerprint = generate_desktop_fingerprint()
        browser_version = build_live_studio_browser_version(version)

        params = _build_device_register_query_params(
            version,
            pc_uuid,
            pc_serial,
            browser_version,
            fingerprint,
        )
        payload = _build_device_register_payload(version, pc_uuid, pc_serial, fingerprint)
        payload_text = json.dumps(payload, separators=(",", ":"))

        encrypted_payload = log_encrypt(
            payload_text,
            magic_number=29795,
            version=3,
            sub_version=3,
            key=DEFAULT_LOG_ENCRYPT_KEY,
        )

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "user-agent": "TTNetwork PC",
            "x-ss-dp": "",
            "sdk_aid": "8311",
            "x-ss-stub": hashlib.md5(encrypted_payload).hexdigest(),
        }
        t0_ms = attach_webcast_ntp_t0(headers)

        device_register_endpoint = get_device_register_endpoint(client)

        response = client.post(
            device_register_endpoint,
            params=params,
            headers=headers,
            data=encrypted_payload,
            timeout=timeout,
        )
        update_ntp_from_response(t0_ms, response)
        response.raise_for_status()

        response_data = response.json()
        source = response_data.get("data", response_data)
        device_id = str(source.get("device_id", "")).strip()
        install_id = str(source.get("install_id", "")).strip()

        if not device_id or device_id == "0" or not install_id or install_id == "0":
            raise RuntimeError(f"Device registration failed: {response_data}")

        return device_id, install_id
    finally:
        if close_session:
            client.close()
