import truststore
truststore.inject_into_ssl()
import hashlib
import json
import os
import sys
import time
import webbrowser
import socket
import threading
import urllib.parse
import base64
import mimetypes
import secrets
import signal
import shutil
import subprocess
from urllib.parse import urlencode

import requests
from packaging import version
from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

if sys.platform == "win32":
    import winreg

from Libs.domain_routing import (
    attach_webcast_ntp_t0,
    build_common_headers,
    build_endpoint,
    get_synced_unix_seconds,
    resolve_webcast_base_url,
    update_ntp_from_response,
)
from Libs.device_gen import (
    build_live_studio_browser_version,
    fetch_live_studio_latest_version,
    register_desktop_device_identifiers,
)
from Libs.XLadon import make_ladon
from Libs.XArgus import make_x_argus
from Updater import VersionChecker


TOPICS = {
    "5": "Gaming",
    "6": "Music",
    "42": "Chat & Interview",
    "9": "Beauty & Fashion",
    "3": "Dance",
    "13": "Fitness & Sports",
    "4": "Food",
    "43": "News & Event",
    "45": "Education",
}

REGIONS = [""] + (
    "af ax al dz as ad ao ai aq ag ar am aw au at az bs bh bd bb by be bz bj bm bt bo bq "
    "ba bw bv br io bn bg bf bi cv kh cm ca ky cf td cl cn cx cc co km cg cd ck cr ci hr "
    "cu cw cy cz dk dj dm do ec eg sv et fk fo fj fi fr gf pf tf ga gm ge de "
    "gh gi gr gl gd gp gu gt gg gn gw gy ht hm va hn hk hu is in id ir iq ie im il it jm "
    "jp je jo kz ke ki kp kr kw kg la lv lb ls lr ly li lt lu mo mg mw my mv ml mt mh mq "
    "mr mu yt mx fm md mc mn me ms ma mz mm na nr np nl nc nz ni ne ng nu nf mk mp no om "
    "pk pw ps pa pg py pe ph pn pl pt pr qa re ro ru rw bl sh kn lc mf pm vc ws sm st sa "
    "sn rs sc sl sg sx sk si sb so za gs ss es lk sd sr sj se ch sy tw tj tz th tl tg tk "
    "to tt tn tr tm tc tv ug ua ae gb um us uy uz vu ve vn vg vi wf eh ye zm zw"
).split()

LIVE_STUDIO_CLIENT_ID = "abad793d-e940-42cb-bc89-e6939b1b3b4d"
LIVE_STUDIO_REDIRECT_URI = "live-studio-app://login/continue"
DEFAULT_OS_VERSION = "10.0.26200"
PASSPORT_WEB_SDK_VERSION = "2.1.9"
PASSPORT_LOGIN_QS = (
    "6466666a706b715a76616e5a766a7077666029646c61296160736c66605a6c6129"
    "63752969646b627064626029687069716c5a696a626c6b2976616e5a736077766c"
    "6a6b297360776c637c4375"
)
PASSPORT_LOGIN_SIGN = "80ff2d507e22c30e2e75e91b2d27d09df5ca4a4e219938c4b2317b52cdf108a1"
PASSPORT_QR_QS = (
    "6466666a706b715a76616e5a766a7077666029646c61296160736c66605a6c6129"
    "76616e5a736077766c6a6b297360776c637c4375"
)
PASSPORT_QR_SIGN = "d4042aa32cda6b69425407aac537ff76e4a10b3bdb4e1c70d8ddf78c1cd7fcc6"
PASSPORT_QR_CHECK_QS = (
    "6466666a706b715a76616e5a766a7077666029646c61296160736c66605a6c6129"
    "687069716c5a696a626c6b2976616e5a736077766c6a6b29716a6e606b297360776c637c4375"
)
PASSPORT_QR_CHECK_SIGN = "faf449d94af239a5b4ed8f2e7d72bf6a6e92b0368c18153d879006b4d11dc274"

TT_TICKET_GUARD_PUBLIC_KEY = (
    "BHTyDu4GfY+Se8QoOlL22ARkOv4aLE5LBCk8eSiJ6K5N5m8Wg3cPeVYWVYNDrJ3hs"
    "RmaVCgNl/AKbMW67VBievw="
)
TT_TICKET_GUARD_VERSION = "2"
TT_TICKET_GUARD_WEB_VERSION = "1"
TT_TICKET_GUARD_ITERATION_VERSION = "0"
LADON_LOCAL_ID = 1877999593

ANCHOR_STATUS_DEFAULT = 0
ANCHOR_STATUS_PREPARE = 1
ANCHOR_STATUS_LIVING = 2
ANCHOR_STATUS_PAUSE = 3
ANCHOR_STATUS_FINISH = 4
PING_ANCHOR_TIMEOUT_SECONDS = 2.5
ROOM_HAS_FINISHED_CODES = {"30003", "30003001"}
ROOM_IS_LIVING_CODE = "4003150"
PERCEPTION_VIOLATION_SCENES = (7, 10, 16)
LOCAL_PROXY_DEFAULT_PORT = 1935
LOCAL_PROXY_APP_NAME = "live"
LOCAL_PROXY_STREAM_KEY = "obs"
LOCAL_PROXY_LISTEN_TIMEOUT_SECONDS = 120
LOCAL_PROXY_LOG_NAME = "ffmpeg_proxy.log"


def _application_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_COOKIES_PATH = os.path.join(_application_dir(), "cookies.json")
CONFIG_PATH = os.path.join(_application_dir(), "config.json")
RAPIDAPI_SIGNER_DOCS_URL = "https://rapidapi.com/07wael/api/tiktok-live-studio-api-signer"


def _normalize_configured_path(path, default=DEFAULT_COOKIES_PATH):
    value = str(path or "").strip()
    if not value:
        value = default
    return os.path.abspath(os.path.expanduser(value))


def _load_config_file():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _configured_cookies_path(default=DEFAULT_COOKIES_PATH):
    data = _load_config_file()
    return _normalize_configured_path(data.get("cookies_path", default), default=default)


def _configured_rapidapi_key():
    data = _load_config_file()
    return str(data.get("rapidapi_key", "") or "").strip()


class WebcastError(RuntimeError):
    def __init__(self, message, *, status_code=None, payload=None, action=""):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.action = action


def _is_already_ended_payload(payload):
    if not isinstance(payload, dict):
        return False

    status_code = payload.get("status_code")
    data = payload.get("data", {})
    if not isinstance(data, dict):
        data = {}

    text = " ".join(
        str(part or "")
        for part in (
            data.get("prompts"),
            data.get("message"),
            payload.get("prompts"),
            payload.get("message"),
        )
    ).lower()

    return str(status_code) in ROOM_HAS_FINISHED_CODES and (
        "ended" in text or "finished" in text or "end" in text
    )


def _is_already_ended_error(exc):
    if isinstance(exc, WebcastError):
        return _is_already_ended_payload(exc.payload)
    text = str(exc).lower()
    return "live has ended" in text or "room has finished" in text


def _param_value(params, name, default=None):
    if params is None:
        return default
    if isinstance(params, dict):
        return params.get(name, default)
    if isinstance(params, (list, tuple)):
        for key, value in params:
            if key == name:
                return value
        return default

    value = str(params)
    split = urllib.parse.urlsplit(value)
    query = split.query if split.query else value.lstrip("?")
    parsed = urllib.parse.parse_qs(query, keep_blank_values=True)
    values = parsed.get(name)
    return values[0] if values else default


def _build_signature_headers(timestamp, aid="8311", params=None, x_ss_stub=None):
    argus_options = {"timestamp": timestamp, "aid": aid}
    device_id = _param_value(params, "device_id")
    if device_id:
        argus_options["device_id"] = str(device_id)

    return {
        "x-khronos": str(timestamp),
        "x-ladon": make_ladon(timestamp, LADON_LOCAL_ID, aid),
        "x-argus": make_x_argus(params, x_ss_stub, **argus_options),
    }


def _encode_form_body(data):
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        return data.encode()
    return urllib.parse.urlencode(
        data,
        doseq=True,
        quote_via=urllib.parse.quote,
    ).encode()


def _make_x_ss_stub(data):
    body = _encode_form_body(data)
    return hashlib.md5(body).hexdigest() if body else None


def _payload_status_code(payload):
    if not isinstance(payload, dict):
        return None
    return payload.get("status_code")


def _is_room_is_living_payload(payload):
    return str(_payload_status_code(payload)) == ROOM_IS_LIVING_CODE


def _is_update_in_lock_payload(payload):
    if not isinstance(payload, dict):
        return False
    data = payload.get("data", {})
    if not isinstance(data, dict):
        data = {}
    message = str(data.get("message") or payload.get("message") or "")
    return "StatusMessage:update_in_lock" in message


def _webcast_error_message(payload, action):
    if not isinstance(payload, dict):
        return f"{action} failed: invalid response: {payload!r}"

    status_code = payload.get("status_code", 0)
    if status_code in (0, "0", None) or str(status_code) == ROOM_IS_LIVING_CODE:
        return ""

    data = payload.get("data", {})
    if not isinstance(data, dict):
        data = {}

    message = (
        data.get("prompts")
        or data.get("message")
        or payload.get("prompts")
        or payload.get("message")
    )
    if message:
        return f"{action} failed: {message} (status_code={status_code})"

    return f"{action} failed: TikTok returned status_code={status_code}. Response={json.dumps(payload, ensure_ascii=False)[:1000]}"


def _raise_for_webcast_error(payload, action):
    message = _webcast_error_message(payload, action)
    if message:
        status_code = payload.get("status_code") if isinstance(payload, dict) else None
        raise WebcastError(message, status_code=status_code, payload=payload, action=action)


def _encode_multipart_form_data(fields, files, boundary=None):
    boundary = boundary or f"----WebKitFormBoundary{secrets.token_urlsafe(12).replace('_', 'A').replace('-', 'B')[:16]}"
    chunks = []

    for name, value in fields:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for name, filename, content_type, content in files:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(content)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(chunks)


class Stream:
    def __init__(self, cookies_path=None):
        self.s = requests.session()
        self.s.headers.update(build_common_headers(self.s))
        self.roomId = ""
        self.streamId = ""
        self._cached_live_studio_version = None
        self.cookies_path = _normalize_configured_path(cookies_path or _configured_cookies_path())
        with open(self.cookies_path, "r", encoding="utf-8") as file:
            cookies_file = json.load(file)

        cookies = {}
        for cookie in cookies_file:
            cookies[cookie["name"]] = cookie["value"]
        self.s.cookies.update(cookies)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.s.close()

    def _apply_room_info(self, room, *, require_stream_url=True):
        living_room_attrs = room.get("living_room_attrs") or {}
        self.roomId = (
            living_room_attrs.get("room_id_str")
            or str(living_room_attrs.get("room_id", ""))
            or room.get("id_str")
            or str(room.get("id", ""))
        )
        self.streamId = room.get("stream_id_str") or str(room.get("stream_id", ""))
        self.streamUrl = (room.get("stream_url") or {}).get("rtmp_push_url", "")
        if self.streamUrl:
            split_index = self.streamUrl.rfind("/")
            self.baseStreamUrl = self.streamUrl[:split_index]
            self.streamKey = self.streamUrl[split_index + 1 :]
        else:
            self.baseStreamUrl = ""
            self.streamKey = ""

        multi_stream_url = room.get("multi_stream_url") or {}
        self.multiStreamUrl = multi_stream_url.get("rtmp_push_url", "")
        if self.multiStreamUrl:
            split_index = self.multiStreamUrl.rfind("/")
            self.multiBaseStreamUrl = self.multiStreamUrl[:split_index]
            self.multiStreamKey = self.multiStreamUrl[split_index + 1 :]
        else:
            self.multiBaseStreamUrl = ""
            self.multiStreamKey = ""

        self.multiStreamScene = room.get("multi_stream_scene")
        self.multiStreamId = (
            room.get("multi_stream_id_str")
            or str(room.get("multi_stream_id", ""))
            or multi_stream_url.get("id_str")
            or str(multi_stream_url.get("id", ""))
        )
        self.streamShareUrl = room.get("share_url", "")
        self.roomStatus = room.get("status")
        owner = room.get("owner") or {}
        self.ownerUserId = (
            room.get("owner_user_id_str")
            or str(room.get("owner_user_id") or "")
            or owner.get("id_str")
            or str(owner.get("id") or "")
        )
        has_ids = bool(self.roomId and self.streamId)
        has_push_url = bool(self.streamUrl)
        return has_ids and (has_push_url or not require_stream_url)

    def save_cookies(self, path=None):
        path = _normalize_configured_path(path or getattr(self, "cookies_path", "") or _configured_cookies_path())
        cookies = _export_cookie_jar(self.s.cookies)
        if cookies:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(cookies, file, indent=2)
        return cookies

    def getLiveStudioLatestVersion(self):
        if not self._cached_live_studio_version:
            self._cached_live_studio_version = fetch_live_studio_latest_version(self.s)
        return self._cached_live_studio_version

    def _cookie_value(self, name, default=""):
        try:
            return self.s.cookies.get(name) or default
        except Exception:
            return default

    def _effective_priority_region(self, priority_region=""):
        region = str(priority_region or "").strip().lower()
        if region:
            return region

        cookie_region = str(self._cookie_value("store-country-code", "") or "").strip().lower()
        if len(cookie_region) == 2:
            return cookie_region

        return ""

    def _priority_region_candidates(self, priority_region=""):
        candidates = []
        for candidate in (
            priority_region,
            self._effective_priority_region(priority_region),
            self._cookie_value("store-country-code", ""),
            "",
        ):
            candidate = str(candidate or "").strip().lower()
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _apply_live_studio_headers(self):
        version = self.getLiveStudioLatestVersion()
        browser_version = build_live_studio_browser_version(version)
        self.s.headers.update(
            {
                "user-agent": f"Mozilla/{browser_version}",
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-US",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "sec-fetch-storage-access": "active",
                "X-SS-DP": "",
                "sdk_aid": "8311",
                "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        )
        return version, browser_version

    def _studio_params(self, *, device_id="", install_id="", priority_region=""):
        version = self.getLiveStudioLatestVersion()
        browser_version = build_live_studio_browser_version(version)
        priority_region = self._effective_priority_region(priority_region)
        return {
            "aid": "8311",
            "app_name": "tiktok_live_studio",
            "device_id": str(device_id) if device_id else "0",
            "install_id": str(install_id) if install_id else "0",
            "channel": "studio",
            "version_code": version,
            "device_platform": "windows",
            "timezone_name": "Africa/Tunis",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "en-US",
            "browser_platform": "Win32",
            "browser_name": "Mozilla",
            "browser_version": browser_version,
            "language": "en",
            "app_language": "en",
            "webcast_language": "en",
            "priority_region": priority_region,
            "webcast_sdk_version": version.replace(".", ""),
            "live_mode": "6",
        }

    def _signed_get_json(self, url, *, params, priority_region=""):
        self._apply_live_studio_headers()
        timestamp = get_synced_unix_seconds()
        headers = {
            "pragma": "no-cache",
            "cache-control": "no-cache",
            **_build_signature_headers(
                timestamp,
                params.get("aid", "8311"),
                params=params,
                x_ss_stub=None,
            ),
        }
        region = params.get("priority_region") or self._effective_priority_region(priority_region)
        if region:
            headers["x-tt-store-region"] = region
        return self._request_json("GET", url, params=params, headers=headers)

    def _request_json(
        self,
        method,
        url,
        *,
        params=None,
        data=None,
        files=None,
        verify=True,
        timeout=None,
        headers=None,
    ):
        request_headers = dict(headers or {})
        t0_ms = attach_webcast_ntp_t0(request_headers)

        response = self.s.request(
            method=method,
            url=url,
            params=params,
            data=data,
            files=files,
            headers=request_headers,
            verify=verify,
            timeout=timeout,
        )
        update_ntp_from_response(t0_ms, response)
        try:
            self.save_cookies()
        except Exception:
            pass
        return response.json()

    def createStream(
        self,
        title,
        hashtag_id,
        game_tag_id="0",
        gen_replay=True,
        close_room_when_close_stream=False,
        age_restricted=False,
        priority_region="",
        thumbnail_path="",
        device_id="",
        install_id="",
        multi_stream_scene=False,
        multi_stream_source=1,
    ):
        base_url = self.getServerUrl()
        aid = "8311"
        self._apply_live_studio_headers()

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )

        data = {
            "title": title,
            "live_studio": "1",
            "gen_replay": str(gen_replay).lower(),
            "chat_auth": "1",
            "age_restricted": "0",
            "cover_uri": "",
            "close_room_when_close_stream": str(close_room_when_close_stream).lower(),
            "hashtag_id": str(hashtag_id),
            "game_tag_id": str(game_tag_id),
            "game_bitrate_type": "high",
            "screenshot_cover_status": "1",
            "live_sub_only": "0",
            "chat_sub_only_auth": "2",
            "multi_stream_scene": "1" if multi_stream_scene else "0",
            "gift_auth": "1",
            "chat_l2": "1",
            "star_comment_switch": "true",
            "multi_stream_source": str(multi_stream_source),
            "is_group_live_session": "false",
            "open_commercial_content_toggle": "false",
            "commercial_content_promote_myself": "false",
            "commercial_content_promote_third_party": "false",
            "rtc_net_enabled": "false",
        }

        if age_restricted:
            data["age_restricted"] = "4"

        if thumbnail_path:
            uri = self.uploadThumbnail(thumbnail_path, base_url, params)
            data["cover_uri"] = uri

        timestamp = get_synced_unix_seconds()
        body_encoded = _encode_form_body(data)
        x_ss_stub = _make_x_ss_stub(body_encoded)

        request_headers = {
            "x-ss-stub": x_ss_stub,
            **_build_signature_headers(
                timestamp,
                params["aid"],
                params=params,
                x_ss_stub=x_ss_stub,
            ),
        }
        if params.get("priority_region"):
            request_headers["x-tt-store-region"] = params["priority_region"]

        streamInfo = self._request_json(
            "POST",
            base_url + "webcast/room/create/",
            params=params,
            data=body_encoded,
            headers=request_headers,
        )
        self.lastCreateStreamResponse = streamInfo

        try:
            if not self._apply_room_info(streamInfo["data"], require_stream_url=True):
                raise KeyError("stream_url")
            return True
        except KeyError as exc:
            prompt = streamInfo.get("data", {}).get("prompts") or streamInfo.get("prompts")
            if not prompt:
                prompt = "Failed to create stream: " + json.dumps(streamInfo, ensure_ascii=False)[:1000]
            raise RuntimeError(prompt) from exc

    def getCreateRoomInfo(self, device_id="", install_id="", priority_region="", last_time_hashtag_id="5"):
        base_url = self.getServerUrl()
        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        params.update(
            {
                "last_time_hashtag_id": str(last_time_hashtag_id or "5"),
                "live_studio": "1",
            }
        )
        return self._signed_get_json(
            base_url + "webcast/room/create_info/",
            params=params,
            priority_region=params.get("priority_region", ""),
        )

    def getContinuableStreamInfo(self, device_id="", install_id="", priority_region=""):
        base_url = self.getServerUrl()
        last_payload = None
        last_reason = "No continuable stream was returned."

        for candidate_region in self._priority_region_candidates(priority_region):
            params = self._studio_params(
                device_id=device_id,
                install_id=install_id,
                priority_region=candidate_region,
            )
            payload = self._signed_get_json(
                base_url + "webcast/room/continue/",
                params=params,
                priority_region=params.get("priority_region", ""),
            )
            last_payload = payload
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            room = data.get("room") if isinstance(data, dict) else None
            if not isinstance(room, dict) or not room:
                message = (
                    payload.get("message")
                    or data.get("message") if isinstance(data, dict) else None
                )
                last_reason = message or last_reason
                continue

            self._apply_room_info(room, require_stream_url=False)
            has_ids = bool(self.roomId and self.streamId)
            has_push_url = bool(self.streamUrl)
            reason = ""
            if not has_ids:
                reason = "The continuable room did not include room_id and stream_id."
            elif not has_push_url:
                reason = "The continuable room did not include an RTMP push URL."

            return {
                "payload": payload,
                "data": data,
                "room": room,
                "has_room": True,
                "can_resume": has_ids and has_push_url,
                "reason": reason,
                "room_id": self.roomId,
                "stream_id": self.streamId,
                "stream_url": self.streamUrl,
                "priority_region": params.get("priority_region", ""),
                "continue_scene": data.get("continue_scene"),
                "cross_device_continue_scene": data.get("cross_device_continue_scene"),
                "link_mic_user_num": data.get("link_mic_user_num"),
            }

        return {
            "payload": last_payload,
            "data": {},
            "room": None,
            "has_room": False,
            "can_resume": False,
            "reason": last_reason,
            "room_id": "",
            "stream_id": "",
            "stream_url": "",
            "priority_region": "",
            "continue_scene": None,
            "cross_device_continue_scene": None,
            "link_mic_user_num": None,
        }

    def getContinuableStream(self, device_id="", install_id="", priority_region="", require_stream_url=True):
        info = self.getContinuableStreamInfo(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        if not info.get("has_room"):
            return None
        if require_stream_url and not info.get("can_resume"):
            return None
        return info.get("room")

    def _pingAnchorStatus(
        self,
        status,
        *,
        device_id="",
        install_id="",
        priority_region="",
        room_id="",
        stream_id="",
        repeat=1,
    ):
        self._apply_live_studio_headers()
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        stream_id = str(stream_id or self.streamId or "").strip()
        if not room_id or not stream_id:
            raise RuntimeError("Missing room_id or stream_id.")

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        data = {
            "status": str(status),
            "room_id": room_id,
            "stream_id": stream_id,
        }
        body_encoded = _encode_form_body(data)
        x_ss_stub = _make_x_ss_stub(body_encoded)
        streamInfo = None
        for _ in range(max(1, int(repeat))):
            request_headers = {
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "pragma": "no-cache",
                "cache-control": "no-cache",
                "x-ss-stub": x_ss_stub,
                **_build_signature_headers(
                    get_synced_unix_seconds(),
                    params["aid"],
                    params=params,
                    x_ss_stub=x_ss_stub,
                ),
            }
            region = params.get("priority_region")
            if region:
                request_headers["x-tt-store-region"] = region

            try:
                streamInfo = self._request_json(
                    "POST",
                    base_url + "webcast/room/ping/anchor/",
                    params=params,
                    data=body_encoded,
                    headers=request_headers,
                    timeout=PING_ANCHOR_TIMEOUT_SECONDS,
                )
            except requests.Timeout:
                streamInfo = self._request_json(
                    "POST",
                    base_url + "webcast/room/ping/anchor/",
                    params=params,
                    data=body_encoded,
                    headers=request_headers,
                    timeout=PING_ANCHOR_TIMEOUT_SECONDS,
                )

            if _is_update_in_lock_payload(streamInfo):
                streamInfo = self._request_json(
                    "POST",
                    base_url + "webcast/room/ping/anchor/",
                    params=params,
                    data=body_encoded,
                    headers=request_headers,
                    timeout=PING_ANCHOR_TIMEOUT_SECONDS,
                )

        return streamInfo

    def anchorHeartbeat(self, status, device_id="", install_id="", priority_region="", room_id="", stream_id="", action="Anchor heartbeat"):
        streamInfo = self._pingAnchorStatus(
            status,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
        )
        _raise_for_webcast_error(streamInfo, action)
        return streamInfo

    def prepareStream(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        # Official Live Studio starts anchor pings in prepare state.
        # It only switches to living after the backend reports RoomIsLiving or after SDK connection.
        return self.anchorHeartbeat(
            ANCHOR_STATUS_PREPARE,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
            action="Prepare stream",
        )

    def pauseStream(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        return self.anchorHeartbeat(
            ANCHOR_STATUS_PAUSE,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
            action="Pause stream",
        )

    def pausedHeartbeat(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        return self.anchorHeartbeat(
            ANCHOR_STATUS_PAUSE,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
            action="Paused heartbeat",
        )

    def resumeStream(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        # Resume-existing after /continue/ behaves like Live Studio startup: start from prepare.
        if not room_id or not stream_id:
            self.getContinuableStream(device_id=device_id, install_id=install_id, priority_region=priority_region)

        return self.prepareStream(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
        )

    def resumePausedStream(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        return self.anchorHeartbeat(
            ANCHOR_STATUS_LIVING,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
            action="Resume stream",
        )

    def liveHeartbeat(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        return self.anchorHeartbeat(
            ANCHOR_STATUS_LIVING,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
            action="Live heartbeat",
        )

    def endStream(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        stream_id = str(stream_id or self.streamId or "").strip()
        if not room_id or not stream_id:
            raise RuntimeError("Missing room_id or stream_id. Create or resume a stream before ending it.")

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        self._signed_get_json(
            base_url + "webcast/room/anchor_pre_finish/",
            params={**params, "room_id": room_id},
            priority_region=priority_region,
        )
        streamInfo = self._pingAnchorStatus(
            ANCHOR_STATUS_FINISH,
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
            room_id=room_id,
            stream_id=stream_id,
            repeat=2,
        )

        _raise_for_webcast_error(streamInfo, "End stream")

        return True

    def getRealtimeStats(self, device_id="", install_id="", priority_region="", room_id=""):
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        if not room_id:
            raise RuntimeError("Missing room_id. Create or resume a stream before loading realtime stats.")

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        params["room_id"] = room_id

        payload = self._signed_get_json(
            base_url + "webcast/game/studio/realtime_stats/",
            params=params,
            priority_region=params.get("priority_region", ""),
        )
        _raise_for_webcast_error(payload, "Realtime stats")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        room_stats = data.get("room_stats") or {}

        return {
            "is_live": data.get("is_live"),
            "room_id": room_stats.get("room_id") or room_id,
            "watch_count": room_stats.get("live_watch_cnt"),
            "comment_count": room_stats.get("live_comment_cnt"),
            "like_count": room_stats.get("live_like_cnt"),
            "share_count": room_stats.get("room_share_cnt"),
            "total_coin": room_stats.get("total_score"),
            "consume_user_count": room_stats.get("live_consume_ucnt"),
            "new_fans_count": room_stats.get("live_new_fans_ucnt"),
            "new_subscribers_count": room_stats.get("new_subscribers_cnt"),
            "fans_club_count": room_stats.get("fans_club_ucnt"),
            "new_fans_club_count": room_stats.get("live_new_fans_club_ucnt"),
            "raw": payload,
        }

    def getTrendsStats(self, device_id="", install_id="", priority_region="", room_id=""):
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        if not room_id:
            raise RuntimeError("Missing room_id. Create or resume a stream before loading trends stats.")

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        params["room_id"] = room_id

        payload = self._signed_get_json(
            base_url + "webcast/game/studio/trends_stats/",
            params=params,
            priority_region=params.get("priority_region", ""),
        )
        _raise_for_webcast_error(payload, "Trends stats")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        trends = data.get("room_trends_stats") or {}

        return {
            "room_id": room_id,
            "current_viewers": trends.get("room_user_count"),
            "current_viewers_followed": trends.get("room_user_followed_count"),
            "current_viewers_trends": trends.get("current_viewers_trends"),
            "total_viewers_trends": trends.get("total_viewers_trends"),
            "raw": payload,
        }

    def _payload_data(self, payload):
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    def _summarize_payload(self, payload):
        if not isinstance(payload, dict):
            return "No response"

        data = payload.get("data")
        candidates = []
        if isinstance(data, dict):
            candidates.append(data)
            for key in ("record", "latest_record", "ban_record", "violation", "perception_info", "count_down", "countdown"):
                value = data.get(key)
                if isinstance(value, dict):
                    candidates.append(value)
                elif isinstance(value, list) and value:
                    candidates.append(value[0])
            for key in ("records", "record_list", "violations", "ban_records", "list"):
                value = data.get(key)
                if isinstance(value, list) and value:
                    candidates.append(value[0])
        elif isinstance(data, list) and data:
            candidates.append(data[0])

        message_keys = (
            "prompts",
            "message",
            "msg",
            "title",
            "reason",
            "violation_reason",
            "ban_reason",
            "punish_reason",
            "content",
            "text",
            "description",
            "toast",
        )
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in message_keys:
                value = candidate.get(key)
                if value not in (None, "", []):
                    return str(value)[:220]

        status_code = payload.get("status_code")
        if status_code in (0, "0", None):
            return "None"
        return f"status_code={status_code}"

    def _safe_signed_get(self, endpoint, *, params, priority_region="", action="Request"):
        try:
            payload = self._signed_get_json(
                self.getServerUrl() + endpoint,
                params=params,
                priority_region=priority_region,
            )
            _raise_for_webcast_error(payload, action)
            return {"ok": True, "payload": payload, "summary": self._summarize_payload(payload), "error": ""}
        except Exception as exc:
            return {"ok": False, "payload": None, "summary": "Unavailable", "error": str(exc)}

    def getRoomInfo(self, device_id="", install_id="", priority_region="", room_id=""):
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        if not room_id:
            raise RuntimeError("Missing room_id. Create or resume a stream before loading room info.")

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        params["room_id"] = room_id

        payload = self._signed_get_json(
            base_url + "webcast/room/info/",
            params=params,
            priority_region=params.get("priority_region", ""),
        )
        _raise_for_webcast_error(payload, "Room info")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        room = data.get("room") if isinstance(data, dict) else None
        if not isinstance(room, dict):
            room = data if isinstance(data, dict) else {}

        return {
            "room_id": room_id,
            "room": room,
            "perception_info": room.get("perception_info") or {},
            "room_auth": room.get("room_auth") or {},
            "raw": payload,
        }

    def getOnlineAudience(self, device_id="", install_id="", priority_region="", room_id="", anchor_id=""):
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        anchor_id = str(anchor_id or getattr(self, "ownerUserId", "") or "").strip()
        if not room_id:
            raise RuntimeError("Missing room_id. Create or resume a stream before loading online audience.")

        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        params.update(
            {
                "room_id": room_id,
                "source": "0",
            }
        )
        if anchor_id:
            params["anchor_id"] = anchor_id

        payload = self._signed_get_json(
            base_url + "webcast/ranklist/online_audience/",
            params=params,
            priority_region=params.get("priority_region", ""),
        )
        _raise_for_webcast_error(payload, "Online audience")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}

        return {
            "total": data.get("total"),
            "preview_count": data.get("preview_count"),
            "bottom_notice": data.get("bottom_notice", ""),
            "currency": data.get("currency", ""),
            "ranks": data.get("ranks") or [],
            "display_config": data.get("display_config") or {},
            "raw": payload,
        }

    def _active_eco_violation_records(self, payload):
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
        records = data.get("records") or []
        now_ms = (payload.get("extra") or {}).get("now") if isinstance(payload, dict) else None
        try:
            now_seconds = int(now_ms) / 1000 if now_ms else time.time()
        except (TypeError, ValueError):
            now_seconds = time.time()

        active_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            punish = record.get("punish_info") or {}
            if not isinstance(punish, dict):
                punish = {}

            if punish.get("is_permanent_punish"):
                active_records.append(record)
                continue

            start_time = punish.get("punish_start_time") or 0
            try:
                start_time = int(start_time or 0)
            except (TypeError, ValueError):
                start_time = 0

            end_candidates = [
                punish.get("punish_end_time"),
                punish.get("punish_expected_end_time"),
                punish.get("punish_real_end_time"),
            ]
            end_times = []
            for end_time in end_candidates:
                try:
                    end_time = int(end_time or 0)
                except (TypeError, ValueError):
                    end_time = 0
                if end_time > 0:
                    end_times.append(end_time)

            # The endpoint returns history records too. Only keep punishments that are active now.
            if not end_times:
                if start_time and start_time <= now_seconds:
                    active_records.append(record)
                continue

            latest_end = max(end_times)
            if (not start_time or start_time <= now_seconds) and latest_end > now_seconds:
                active_records.append(record)

        return active_records

    def _eco_violation_id(self, record):
        punish = record.get("punish_info") or {}
        return str(
            record.get("violation_id_str")
            or record.get("violation_id")
            or punish.get("punish_record_id_str")
            or punish.get("punish_record_id")
            or punish.get("punish_id")
            or ""
        )

    def _format_epoch_seconds(self, value):
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            value = 0
        if not value:
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
        except Exception:
            return str(value)

    def _format_eco_violation_record(self, record):
        punish = record.get("punish_info") or {}
        live_info = record.get("live_info") or {}
        title = punish.get("punish_title") or "Violation"
        reason = punish.get("punish_reason") or punish.get("perception_code") or "Unknown reason"
        room_title = live_info.get("title") or ""
        end_time = self._format_epoch_seconds(
            punish.get("punish_end_time")
            or punish.get("punish_expected_end_time")
            or punish.get("punish_real_end_time")
        )
        parts = [str(title), str(reason)]
        if room_title:
            parts.append(f"Room: {room_title}")
        if end_time:
            parts.append(f"Until: {end_time}")
        return " | ".join(parts)

    def _is_active_perception_status(self, item):
        status = item.get("status")
        punish = item.get("punish_event") or {}
        if status not in (0, "0", None, ""):
            return True
        for key in ("punish_id", "punish_reason", "punish_type", "show_reason"):
            if punish.get(key):
                return True
        end_time = punish.get("end_time")
        try:
            return bool(end_time and int(end_time) > int(time.time()))
        except (TypeError, ValueError):
            return False

    def _format_perception_violation_status(self, item):
        scene = item.get("scene")
        if item.get("active"):
            punish = item.get("punish_event") or {}
            reason = punish.get("show_reason") or punish.get("punish_reason") or punish.get("punish_type") or "Active"
            end_time = self._format_epoch_seconds(punish.get("end_time"))
            if end_time:
                return f"Scene {scene}: {reason} until {end_time}"
            return f"Scene {scene}: {reason}"
        return f"Scene {scene}: OK"

    def getPerceptionViolationStatus(self, device_id="", install_id="", priority_region="", scene=10):
        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        params["scene"] = str(scene)

        payload = self._signed_get_json(
            self.getServerUrl() + "webcast/perception/violation/status/",
            params=params,
            priority_region=params.get("priority_region", ""),
        )
        _raise_for_webcast_error(payload, f"Perception violation status scene {scene}")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
        punish = data.get("punish_event") or {}
        item = {
            "scene": scene,
            "status": data.get("status"),
            "punish_event": punish,
            "active": False,
            "raw": payload,
        }
        item["active"] = self._is_active_perception_status(item)
        item["summary"] = self._format_perception_violation_status(item)
        return item

    def getEcoViolationList(self, device_id="", install_id="", priority_region="", violation_list_type=1):
        # This endpoint uses the eco/live-center app id from the official request, not aid 8311.
        params = {
            "aid": "8311",
            "violation_list_type": str(violation_list_type),
        }
        url = build_endpoint("webcast16-normal-no1a.tiktokv.eu", "webcast/eco/violation_list/", self.s)
        payload = self._signed_get_json(
            url,
            params=params,
            priority_region=self._effective_priority_region(priority_region),
        )
        _raise_for_webcast_error(payload, "Eco violation list")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
        active_records = self._active_eco_violation_records(payload)
        return {
            "active_count": data.get("active_count", len(active_records)),
            "history_count": data.get("history_count"),
            "is_eea": data.get("is_eea"),
            "has_more": data.get("has_more"),
            "records": data.get("records") or [],
            "active_records": active_records,
            "active_ids": [self._eco_violation_id(record) for record in active_records if self._eco_violation_id(record)],
            "active_summaries": [self._format_eco_violation_record(record) for record in active_records],
            "raw": payload,
        }

    def getViolationStatus(self, device_id="", install_id="", priority_region="", room_id="", last_time_hashtag_id="5"):
        room_id = str(room_id or self.roomId or "").strip()
        errors = []
        create_data = {}
        try:
            create_info = self.getCreateRoomInfo(
                device_id=device_id,
                install_id=install_id,
                priority_region=priority_region,
                last_time_hashtag_id=last_time_hashtag_id,
            )
            create_data = self._payload_data(create_info)
        except Exception as exc:
            errors.append(f"create_info: {exc}")

        room_info = {"room": {}, "perception_info": {}, "room_auth": {}}
        if room_id:
            try:
                room_info = self.getRoomInfo(
                    device_id=device_id,
                    install_id=install_id,
                    priority_region=priority_region,
                    room_id=room_id,
                )
            except Exception as exc:
                errors.append(f"room_info: {exc}")

        perception_statuses = []
        for scene in PERCEPTION_VIOLATION_SCENES:
            try:
                perception_statuses.append(
                    self.getPerceptionViolationStatus(
                        device_id=device_id,
                        install_id=install_id,
                        priority_region=priority_region,
                        scene=scene,
                    )
                )
            except Exception as exc:
                errors.append(f"perception_scene_{scene}: {exc}")

        perception_countdown = self._safe_signed_get(
            "webcast/perception/count_down/",
            params=self._studio_params(
                device_id=device_id,
                install_id=install_id,
                priority_region=priority_region,
            ),
            priority_region=priority_region,
            action="Perception countdown",
        )
        if not perception_countdown.get("ok") and perception_countdown.get("error"):
            errors.append(f"perception_countdown: {perception_countdown['error']}")

        eco_violation_list = {"active_records": [], "active_ids": [], "active_summaries": [], "active_count": 0, "history_count": None}
        try:
            eco_violation_list = self.getEcoViolationList(
                device_id=device_id,
                install_id=install_id,
                priority_region=priority_region,
                violation_list_type=1,
            )
        except Exception as exc:
            errors.append(f"eco_violation_list: {exc}")

        ban_status = create_data.get("ban_status") or {}
        advanced_ban_status = create_data.get("advanced_live_ban_status") or {}
        block_status = create_data.get("block_status", 0)
        locale_restricted = bool(create_data.get("golive_locale_restricted", False))
        ban_active = bool(ban_status.get("is_ban") or advanced_ban_status.get("is_ban"))
        blocked = block_status not in (0, "0", None, "")

        room_auth = room_info.get("room_auth") or {}
        perception_info = room_info.get("perception_info") or {}
        community_flagged = bool(room_auth.get("CommunityFlagged"))
        community_review = bool(room_auth.get("CommunityFlaggedReview"))
        violations_entrance = bool(perception_info.get("show_violations_entrance"))
        violations_entrance_end_time = perception_info.get("violations_entrance_end_time")

        active_perception_statuses = [item for item in perception_statuses if item.get("active")]
        active_eco_records = eco_violation_list.get("active_records") or []
        active_eco_summaries = eco_violation_list.get("active_summaries") or []
        active_violation_ids = set(eco_violation_list.get("active_ids") or [])
        for item in active_perception_statuses:
            active_violation_ids.add(f"perception_scene_{item.get('scene')}")

        status = "OK"
        if active_eco_records or active_perception_statuses or ban_active or blocked or locale_restricted:
            status = "Restricted"
        elif community_flagged or community_review or violations_entrance:
            status = "Warning"

        return {
            "status": status,
            "ban_active": ban_active,
            "ban_summary": self._summarize_payload({"data": ban_status}) if ban_status else "None",
            "advanced_ban_active": bool(advanced_ban_status.get("is_ban")),
            "advanced_ban_summary": self._summarize_payload({"data": advanced_ban_status}) if advanced_ban_status else "None",
            "block_status": block_status,
            "locale_restricted": locale_restricted,
            "community_flagged": community_flagged,
            "community_review": community_review,
            "violations_entrance": violations_entrance,
            "violations_entrance_end_time": violations_entrance_end_time,
            "perception_summary": perception_countdown.get("summary", "Unavailable"),
            "perception_violation_statuses": perception_statuses,
            "active_perception_statuses": active_perception_statuses,
            "eco_violation_list": eco_violation_list,
            "active_violation_count": len(active_eco_records) + len(active_perception_statuses),
            "active_violation_ids": sorted(active_violation_ids),
            "active_violation_summaries": active_eco_summaries + [item.get("summary", "") for item in active_perception_statuses],
            "history_violation_count": eco_violation_list.get("history_count"),
            "errors": errors,
            "raw": {
                "create_info": create_data,
                "room_info": room_info,
                "perception_countdown": perception_countdown,
                "perception_violation_statuses": perception_statuses,
                "eco_violation_list": eco_violation_list,
            },
        }

    def getServerUrl(self):
        return resolve_webcast_base_url(self.s)

    def getAccountInfo(self, device_id="", install_id="", priority_region="", last_time_hashtag_id="5"):
        base_url = self.getServerUrl()
        version = self.getLiveStudioLatestVersion()
        browser_version = build_live_studio_browser_version(version)
        self.s.headers.update(
            {
                "user-agent": f"Mozilla/{browser_version}",
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-US",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "sec-fetch-storage-access": "active",
                "X-SS-DP": "",
                "sdk_aid": "8311",
                "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        )

        verify_fp = f"verify_{device_id}" if device_id else "verify_0"
        account_params = {
            "device_id": str(device_id) if device_id else "0",
            "aid": "8311",
            "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "verifyFp": verify_fp,
            "sign": PASSPORT_QR_SIGN,
            "qs": PASSPORT_QR_QS,
        }
        account_payload = self._signed_get_json(
            build_endpoint("api16-normal-no1a.tiktokv.eu", "passport/account/info/v2/", self.s),
            params=account_params,
            priority_region=priority_region,
        )
        account_data = account_payload.get("data", {}) if isinstance(account_payload, dict) else {}
        common_params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )

        create_params = dict(common_params)
        create_params.update(
            {
                "last_time_hashtag_id": str(last_time_hashtag_id or "5"),
                "live_studio": "1",
            }
        )
        create_info = self._signed_get_json(
            base_url + "webcast/room/create_info/",
            params=create_params,
            priority_region=priority_region,
        )

        game_params = dict(common_params)
        game_params["scene"] = "2"
        game_create_info = self._signed_get_json(
            base_url + "webcast/game/basic/create_info/",
            params=game_params,
            priority_region=priority_region,
        )

        create_data = create_info.get("data", {}) if isinstance(create_info, dict) else {}
        game_data = game_create_info.get("data", {}) if isinstance(game_create_info, dict) else {}

        ban_status = create_data.get("ban_status") or {}
        advanced_ban_status = create_data.get("advanced_live_ban_status") or {}
        block_status = create_data.get("block_status", 0)
        can_go_live = all(
            [
                not create_data.get("golive_locale_restricted", False),
                not ban_status.get("is_ban", False),
                not advanced_ban_status.get("is_ban", False),
                block_status in (0, "0", None),
                game_data.get("has_live_studio_login", False),
            ]
        )

        status_parts = []
        if can_go_live:
            status_parts.append("Ready")
        else:
            status_parts.append("Restricted")
        if ban_status.get("is_ban") or advanced_ban_status.get("is_ban"):
            status_parts.append("Banned")
        if block_status not in (0, "0", None):
            status_parts.append(f"Blocked {block_status}")
        if create_data.get("golive_locale_restricted"):
            status_parts.append("Locale restricted")

        return {
            "account": account_data,
            "create_info": create_data,
            "game_create_info": game_data,
            "can_go_live": can_go_live,
            "status": " / ".join(status_parts),
            "allow_multi_stream": game_data.get("allow_multi_stream", False),
        }

    def uploadThumbnail(self, file_path, base_url, params):
        filename = os.path.basename(file_path)
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as file_obj:
            boundary, multipart_body = _encode_multipart_form_data(
                [],
                [("image", filename, content_type, file_obj.read())],
            )

        timestamp = get_synced_unix_seconds()
        x_ss_stub = hashlib.md5(multipart_body).hexdigest()
        request_headers = {
            "content-type": f"multipart/form-data; boundary={boundary}",
            "x-ss-stub": x_ss_stub,
            **_build_signature_headers(
                timestamp,
                params.get("aid", "8311"),
                params=params,
                x_ss_stub=x_ss_stub,
            ),
            "pragma": "no-cache",
            "cache-control": "no-cache",
        }
        priority_region = params.get("priority_region")
        if params.get("priority_region"):
            request_headers["x-tt-store-region"] = params["priority_region"]

        thumbnailInfo = self._request_json(
            "POST",
            base_url + "webcast/room/upload/image/",
            params=params,
            data=multipart_body,
            headers=request_headers,
        )

        return thumbnailInfo.get("data", {}).get("uri", "")


def _build_ticket_guard_headers():
    return {
        "tt-ticket-guard-public-key": TT_TICKET_GUARD_PUBLIC_KEY,
        "tt-ticket-guard-version": TT_TICKET_GUARD_VERSION,
        "tt-ticket-guard-web-version": TT_TICKET_GUARD_WEB_VERSION,
        "tt-ticket-guard-iteration-version": TT_TICKET_GUARD_ITERATION_VERSION,
    }


def _build_onetap_auth_url(state, nonce, ticket):
    params = {
        "state": state,
        "nonce": nonce,
        "ticket": ticket,
        "client_id": LIVE_STUDIO_CLIENT_ID,
        "redirect_uri": LIVE_STUDIO_REDIRECT_URI,
    }
    return "https://www.tiktok.com/ucenter_web/onetap_auth?" + urlencode(params)


def _export_cookie_jar(cookie_jar):
    cookies = []
    for cookie in cookie_jar:
        rest = cookie._rest or {}
        http_only = bool(rest.get("HttpOnly") or rest.get("httponly"))
        entry = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or "",
            "path": cookie.path or "/",
            "expires": cookie.expires if cookie.expires is not None else -1,
            "httpOnly": http_only,
            "secure": bool(cookie.secure),
        }
        same_site = rest.get("SameSite") or rest.get("samesite")
        if same_site:
            entry["sameSite"] = same_site
        cookies.append(entry)
    return cookies


class LiveStudioBrowserLoginClient:
    def __init__(self, device_id, install_id):
        self.session = requests.Session()
        self.version = fetch_live_studio_latest_version(self.session)
        self.browser_version = build_live_studio_browser_version(self.version)
        self.user_agent = f"Mozilla/{self.browser_version}"
        self.device_id = str(device_id).strip() if device_id else "0"
        self.install_id = str(install_id).strip() if install_id else "0"

        self.base_headers = {
            "user-agent": self.user_agent,
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "sec-fetch-storage-access": "active",
            "X-SS-DP": "",
            "sdk_aid": "8311",
            "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def close(self):
        self.session.close()

    def _build_common_params(self):
        return {
            "aid": "8311",
            "app_name": "tiktok_live_studio",
            "device_id": self.device_id,
            "install_id": self.install_id,
            "channel": "studio",
            "version_code": self.version,
            "device_platform": "windows",
            "timezone_name": "Africa/Tunis",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "en-US",
            "browser_platform": "Win32",
            "browser_name": "Mozilla",
            "browser_version": self.browser_version,
            "language": "en",
            "app_language": "en",
            "webcast_language": "en",
            "webcast_sdk_version": self.version.replace(".", ""),
            "live_mode": "6",
        }

    def _signed_request_json(
        self,
        method,
        url,
        *,
        params,
        data=None,
        timeout=20,
        headers=None,
        include_x_ss_stub=True,
    ):
        body_encoded = _encode_form_body(data)
        x_ss_stub = _make_x_ss_stub(body_encoded) if include_x_ss_stub else None
        timestamp = get_synced_unix_seconds()
        request_headers = dict(self.base_headers)
        request_headers.update(_build_ticket_guard_headers())
        if headers:
            request_headers.update(headers)
        if x_ss_stub:
            request_headers["x-ss-stub"] = x_ss_stub
        request_headers.update(
            _build_signature_headers(
                timestamp,
                params.get("aid", "8311"),
                params=params,
                x_ss_stub=x_ss_stub,
            )
        )

        t0_ms = attach_webcast_ntp_t0(request_headers)
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            data=body_encoded,
            headers=request_headers,
            timeout=timeout,
        )
        update_ntp_from_response(t0_ms, response)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("Login request did not return JSON.") from exc

    def get_qrcode(self):
        url = build_endpoint("api16-normal-c-alisg.tiktokv.com", "passport/web/get_qrcode/", self.session)
        verify_fp = f"verify_{self.device_id}"
        params = {
            "next": "https://www.tiktok.com",
            "device_id": self.device_id,
            "aid": "8311",
            "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "verifyFp": verify_fp,
            "sign": PASSPORT_QR_SIGN,
            "qs": PASSPORT_QR_QS,
        }
        payload = self._signed_request_json(
            "GET",
            url,
            params=params,
            include_x_ss_stub=False,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        data_payload = payload.get("data", {})
        token = data_payload.get("token")
        qrcode = data_payload.get("qrcode")
        if not token or not qrcode:
            raise RuntimeError(f"QR login setup failed: {payload}")
        return data_payload

    def check_qrconnect(self, token):
        url = build_endpoint("api16-normal-no1a.tiktokv.eu", "passport/web/check_qrconnect/", self.session)
        verify_fp = f"verify_{self.device_id}"
        params = {
            "next": "https://www.tiktok.com",
            "token": token,
            "multi_login": "1",
            "device_id": self.device_id,
            "aid": "8311",
            "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "verifyFp": verify_fp,
            "sign": PASSPORT_QR_CHECK_SIGN,
            "qs": PASSPORT_QR_CHECK_QS,
        }
        payload = self._signed_request_json(
            "GET",
            url,
            params=params,
            include_x_ss_stub=False,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        return payload

    def account_info(self):
        url = build_endpoint("api16-normal-no1a.tiktokv.eu", "passport/account/info/v2/", self.session)
        verify_fp = f"verify_{self.device_id}"
        params = {
            "device_id": self.device_id,
            "aid": "8311",
            "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "verifyFp": verify_fp,
            "sign": PASSPORT_QR_SIGN,
            "qs": PASSPORT_QR_QS,
        }
        return self._signed_request_json(
            "GET",
            url,
            params=params,
            include_x_ss_stub=False,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    def prepare_login(self):
        base_url = resolve_webcast_base_url(self.session)
        url = base_url + "passport/oidc/prepare/"
        params = self._build_common_params()
        data = {
            "channel": "studio",
            "app_name": "tiktok_live_studio",
            "device_type": "PC",
            "os_version": DEFAULT_OS_VERSION,
        }

        payload = self._signed_request_json("POST", url, params=params, data=data)
        data_payload = payload.get("data", {})
        state = data_payload.get("state")
        nonce = data_payload.get("nonce")
        ticket = data_payload.get("ticket")
        if not state or not nonce or not ticket:
            raise RuntimeError(f"Login prepare failed: {payload}")
        return state, nonce, ticket

    def exchange_login(self, id_token, state, ticket):
        url = build_endpoint("api16-normal-no1a.tiktokv.eu", "passport/oidc/login/", self.session)
        verify_fp = f"verify_{self.device_id}"
        params = {
            "device_id": self.device_id,
            "aid": "8311",
            "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "verifyFp": verify_fp,
            "fp": verify_fp,
            "language": "en",
            "multi_login": "1",
            "sign": PASSPORT_LOGIN_SIGN,
            "qs": PASSPORT_LOGIN_QS,
        }
        data = {
            "id_token": id_token,
            "ticket": ticket,
            "state": state,
        }

        payload = self._signed_request_json(
            "POST",
            url,
            params=params,
            data=data,
            headers={
                "accept": "application/json, text/javascript",
                "content-type": "application/x-www-form-urlencoded",
                "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
            },
        )
        message = payload.get("message")
        if message and message != "success":
            error_code = payload.get("error_code") or payload.get("data", {}).get("error_code")
            error_description = (
                payload.get("description")
                or payload.get("data", {}).get("description")
                or payload.get("data", {}).get("oidc_error_message")
            )
            details = ": ".join(str(part) for part in (error_code, error_description) if part)
            raise RuntimeError(f"Login failed: {message}{f' ({details})' if details else ''}")
        return payload

    def save_cookies(self, path=None):
        path = _normalize_configured_path(path or _configured_cookies_path())
        cookies = _export_cookie_jar(self.session.cookies)
        session_names = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "multi_sids"}
        if not any(cookie.get("name") in session_names for cookie in cookies):
            raise RuntimeError("Login succeeded but no session cookies were returned.")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(cookies, file, indent=2)
        return cookies


def fetch_game_tags():
    base_url = resolve_webcast_base_url()
    url = base_url + "webcast/room/hashtag/list/"
    try:
        headers = build_common_headers()
        t0_ms = attach_webcast_ntp_t0(headers)
        response = requests.get(
            url,
            headers=headers,
            timeout=15,
        )
        update_ntp_from_response(t0_ms, response)
        game_tags = response.json()["data"]["game_tag_list"]
        return {game["id"]: game["show_name"] for game in game_tags}
    except Exception as exc:
        print(f"Failed to fetch game tags: {exc}")
        return {}



def _runtime_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _runtime_logs_dir():
    preferred = os.path.join(_runtime_base_dir(), "logs")
    try:
        os.makedirs(preferred, exist_ok=True)
        return preferred
    except OSError:
        fallback = os.path.join(os.getcwd(), "logs")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _bundled_ffmpeg_path():
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    base_dir = _runtime_base_dir()
    candidates = [
        os.path.join(base_dir, "bin", exe_name),
        os.path.join(base_dir, exe_name),
        os.path.join(os.getcwd(), "bin", exe_name),
        os.path.join(os.getcwd(), exe_name),
    ]
    found_in_path = shutil.which("ffmpeg")
    if found_in_path:
        candidates.append(found_in_path)

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    raise FileNotFoundError(
        "FFmpeg was not found. Put ffmpeg in the app's bin folder or add it to PATH."
    )


def _is_tcp_port_available(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, int(port)))
            return True
        except OSError:
            return False


def _pick_local_proxy_port(preferred_port=LOCAL_PROXY_DEFAULT_PORT):
    if preferred_port and _is_tcp_port_available("127.0.0.1", preferred_port):
        return int(preferred_port)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _safe_log_tail(path, max_lines=30):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return "".join(file.readlines()[-max_lines:]).strip()
    except OSError:
        return ""


# ----------------------------------------------------------------------
# Protocol hijacking helpers (Windows only)
# ----------------------------------------------------------------------
def backup_protocol_registry():
    """Backup current live-studio-app registry entry to a dict."""
    if sys.platform != "win32":
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app", 0, winreg.KEY_READ)
        command_key = winreg.OpenKey(key, r"shell\open\command", 0, winreg.KEY_READ)
        command, _ = winreg.QueryValueEx(command_key, "")
        winreg.CloseKey(command_key)
        winreg.CloseKey(key)
        return {"command": command}
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Backup error: {e}")
        return None


def register_temporary_protocol_handler(python_exe, script_path, port):
    """Register live-studio-app to call this script with --protocol-callback and port."""
    if sys.platform != "win32":
        return False
    try:
        root_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app")
        winreg.SetValue(root_key, "", winreg.REG_SZ, "URL:live-studio-app")
        winreg.SetValueEx(root_key, "URL Protocol", 0, winreg.REG_SZ, "")

        shell_key = winreg.CreateKey(root_key, r"shell\open\command")
        command = f'"{python_exe}" "{script_path}" --protocol-callback {port} "%1"'
        winreg.SetValue(shell_key, "", winreg.REG_SZ, command)

        winreg.CloseKey(shell_key)
        winreg.CloseKey(root_key)

        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        return True
    except Exception as e:
        print(f"Failed to register protocol: {e}")
        return False


def restore_protocol_registry(backup):
    """Restore original registry entry or delete if backup is None."""
    if sys.platform != "win32":
        return
    # Delete temporary key – ignore all errors
    try:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app\shell\open\command")
        except Exception:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app\shell\open")
        except Exception:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app\shell")
        except Exception:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app")
        except Exception:
            pass
    except Exception as e:
        print(f"Cleanup error (ignored): {e}")

    # Restore original if it existed
    if backup and "command" in backup:
        try:
            root_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app")
            winreg.SetValue(root_key, "", winreg.REG_SZ, "URL:live-studio-app")
            winreg.SetValueEx(root_key, "URL Protocol", 0, winreg.REG_SZ, "")
            shell_key = winreg.CreateKey(root_key, r"shell\open\command")
            winreg.SetValue(shell_key, "", winreg.REG_SZ, backup["command"])
            winreg.CloseKey(shell_key)
            winreg.CloseKey(root_key)
        except Exception as e:
            print(f"Restore error: {e}")


def start_callback_server():
    """Create a listening socket and return (server_thread, port, callback_event, result_container)."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(1)
    port = server_socket.getsockname()[1]

    result = {"url": None}
    event = threading.Event()

    def wait_for_callback():
        try:
            conn, addr = server_socket.accept()
            data = conn.recv(4096).decode()
            if data.startswith("URL:"):
                result["url"] = data[4:]
            conn.close()
        except Exception:
            pass
        finally:
            event.set()
            server_socket.close()

    thread = threading.Thread(target=wait_for_callback, daemon=True)
    thread.start()
    return thread, port, event, result


# ----------------------------------------------------------------------
# Main GUI Window
# ----------------------------------------------------------------------
class StreamKeyGeneratorWindow(QWidget):
    update_checked = Signal(object)
    account_info_loaded = Signal(object)
    account_info_failed = Signal(str)
    realtime_stats_loaded = Signal(object)
    realtime_stats_failed = Signal(str)
    audience_safety_loaded = Signal(object)
    audience_safety_failed = Signal(str)
    stream_ended_remotely = Signal(str)
    new_violation_detected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Stream Key Generator")

        self.games = fetch_game_tags()
        self.device_id = ""
        self.install_id = ""
        self.current_room_id = ""
        self.current_stream_id = ""
        self.stream_priority_region = ""
        self.is_live = False
        self.is_paused = False
        self.account_can_go_live = None
        self.suppress_donation_reminder = False
        self.anchor_heartbeat_in_flight = False
        self.anchor_heartbeat_error_count = 0
        self.anchor_ping_status = ANCHOR_STATUS_DEFAULT
        self.anchor_heartbeat_timer = QTimer(self)
        self.anchor_heartbeat_timer.setInterval(5000)
        self.anchor_heartbeat_timer.timeout.connect(self.send_anchor_heartbeat)
        self.realtime_stats_in_flight = False
        self.realtime_stats_timer = QTimer(self)
        self.realtime_stats_timer.setInterval(5000)
        self.realtime_stats_timer.timeout.connect(self.refresh_realtime_stats)
        self.audience_safety_in_flight = False
        self.audience_safety_timer = QTimer(self)
        self.audience_safety_timer.setInterval(15000)
        self.audience_safety_timer.timeout.connect(self.refresh_audience_safety)
        self.current_anchor_id = ""
        self.ffmpeg_proxy_process = None
        self.ffmpeg_proxy_log_file = None
        self.ffmpeg_proxy_log_path = ""
        self.local_proxy_port = LOCAL_PROXY_DEFAULT_PORT
        self.local_proxy_server_url = ""
        self.local_proxy_stream_key = LOCAL_PROXY_STREAM_KEY
        self.local_proxy_active = False
        self.show_real_stream_credentials = False
        self.real_stream_url = ""
        self.real_base_stream_url = ""
        self.real_stream_key = ""
        self.real_share_url = ""
        self.active_violation_ids = set()
        self.cookie_file_path = _configured_cookies_path()
        self.rapidapi_key = _configured_rapidapi_key()

        self._build_ui()
        self.update_checked.connect(self.handle_update_check)
        self.account_info_loaded.connect(self.apply_account_info)
        self.account_info_failed.connect(self.handle_account_info_error)
        self.realtime_stats_loaded.connect(self.apply_realtime_stats)
        self.realtime_stats_failed.connect(self.handle_realtime_stats_error)
        self.audience_safety_loaded.connect(self.apply_audience_safety)
        self.audience_safety_failed.connect(self.handle_audience_safety_error)
        self.stream_ended_remotely.connect(self.handle_stream_ended_remotely)
        self.new_violation_detected.connect(self.handle_new_violation_detected)
        self.load_config()
        self.check_cookies()
        self.ensure_device_identifiers(show_popup=True)
        has_startup_cookies, _ = self.get_cookie_file_status()
        if has_startup_cookies:
            QTimer.singleShot(900, lambda: self.refresh_account_info(show_errors=False))
        QTimer.singleShot(3000, self.show_donation_reminder)
        QTimer.singleShot(6000, self.check_updates_on_startup)


    def _build_ui(self):
        root_layout = QGridLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(10, 8, 10, 8)
        root_layout.setColumnMinimumWidth(0, 0)
        root_layout.setColumnMinimumWidth(1, 0)
        root_layout.setColumnMinimumWidth(2, 0)

        def allow_horizontal_shrink(widget, vertical_policy=QSizePolicy.Fixed):
            widget.setMinimumWidth(0)
            widget.setMinimumSize(0, widget.minimumHeight())
            widget.setSizePolicy(QSizePolicy.Ignored, vertical_policy)

        def allow_label_shrink(label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        def allow_button_shrink(button):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        def keep_button_visible(button, minimum_width=72):
            button.setMinimumWidth(minimum_width)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        input_group = QGroupBox("Stream Setup")
        input_group.setMinimumWidth(0)
        input_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(5)

        # Title
        title_label = QLabel("Title:")
        title_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(title_label)
        input_layout.addWidget(title_label)

        self.title_edit = QLineEdit()
        self.title_edit.setFixedHeight(28)
        allow_horizontal_shrink(self.title_edit)
        input_layout.addWidget(self.title_edit)

        # Topic
        topic_label = QLabel("Topic:")
        topic_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(topic_label)
        input_layout.addWidget(topic_label)

        self.topic_combo = QComboBox()
        self.topic_combo.addItems([""] + list(TOPICS.values()))
        self.topic_combo.currentTextChanged.connect(self.on_topic_changed)
        self.topic_combo.setFixedHeight(28)
        allow_horizontal_shrink(self.topic_combo)
        input_layout.addWidget(self.topic_combo)

        # Game
        self.game_label = QLabel("Game:")
        self.game_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(self.game_label)
        input_layout.addWidget(self.game_label)

        self.game_combo = QComboBox()
        self.game_combo.setEditable(True)
        self.game_combo.addItems([""] + list(self.games.values()))
        self.game_combo.setFixedHeight(28)
        allow_horizontal_shrink(self.game_combo)

        game_completer = QCompleter(list(self.games.values()), self)
        game_completer.setCaseSensitivity(Qt.CaseInsensitive)
        game_completer.setFilterMode(Qt.MatchContains)
        self.game_combo.setCompleter(game_completer)

        input_layout.addWidget(self.game_combo)

        # Region
        region_label = QLabel("Region:")
        region_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(region_label)
        input_layout.addWidget(region_label)

        self.region_combo = QComboBox()
        self.region_combo.setEditable(True)
        self.region_combo.addItems(REGIONS)
        self.region_combo.setFixedHeight(28)
        allow_horizontal_shrink(self.region_combo)
        input_layout.addWidget(self.region_combo)

        # Options
        options_label = QLabel("Options:")
        options_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(options_label)
        input_layout.addWidget(options_label)

        options_grid = QGridLayout()
        options_grid.setHorizontalSpacing(8)
        options_grid.setVerticalSpacing(4)
        self.replay_checkbox = QCheckBox("Generate Replay")
        self.replay_checkbox.setChecked(True)
        self.replay_checkbox.setMinimumWidth(0)
        self.replay_checkbox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        options_grid.addWidget(self.replay_checkbox, 0, 0)

        self.age_restricted_checkbox = QCheckBox("Age Restricted")
        self.age_restricted_checkbox.setMinimumWidth(0)
        self.age_restricted_checkbox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        options_grid.addWidget(self.age_restricted_checkbox, 0, 1)

        self.close_room_checkbox = QCheckBox("Close Room When Close Stream")
        self.close_room_checkbox.setMinimumWidth(0)
        self.close_room_checkbox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        options_grid.addWidget(self.close_room_checkbox, 1, 0, 1, 2)
        options_grid.setColumnStretch(0, 1)
        options_grid.setColumnStretch(1, 1)
        input_layout.addLayout(options_grid)

        # Thumbnail
        thumbnail_label = QLabel("Selected Thumbnail:")
        thumbnail_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(thumbnail_label)
        input_layout.addWidget(thumbnail_label)

        thumbnail_row = QHBoxLayout()
        thumbnail_row.setSpacing(5)

        self.thumbnail_edit = QLineEdit()
        self.thumbnail_edit.setReadOnly(True)
        self.thumbnail_edit.setFixedHeight(28)
        allow_horizontal_shrink(self.thumbnail_edit)
        thumbnail_row.addWidget(self.thumbnail_edit)

        browse_button = QPushButton("Browse")
        browse_button.setFixedHeight(28)
        keep_button_visible(browse_button)
        browse_button.clicked.connect(self.browse_image)
        thumbnail_row.addWidget(browse_button)

        input_layout.addLayout(thumbnail_row)

        root_layout.addWidget(input_group, 0, 0)

        account_group = QGroupBox("Account")
        account_group.setMinimumWidth(0)
        account_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        account_layout = QVBoxLayout(account_group)
        account_layout.setContentsMargins(12, 16, 12, 12)
        account_layout.setSpacing(6)
        account_layout.setAlignment(Qt.AlignTop)

        def add_account_field(label_text, widget):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            allow_label_shrink(label)
            account_layout.addWidget(label)
            account_layout.addWidget(widget)

        session_label = QLabel("Cookies JSON")
        session_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(session_label)
        account_layout.addWidget(session_label)

        cookies_row = QHBoxLayout()
        cookies_row.setSpacing(6)

        self.cookies_path_edit = QLineEdit()
        self.cookies_path_edit.setFixedHeight(28)
        self.cookies_path_edit.setPlaceholderText("cookies.json")
        self.cookies_path_edit.editingFinished.connect(self.apply_cookies_path_from_input)
        allow_horizontal_shrink(self.cookies_path_edit)
        cookies_row.addWidget(self.cookies_path_edit, 1)

        self.browse_cookies_button = QPushButton("Browse")
        self.browse_cookies_button.setFixedHeight(28)
        keep_button_visible(self.browse_cookies_button)
        self.browse_cookies_button.clicked.connect(self.browse_cookies_file)
        cookies_row.addWidget(self.browse_cookies_button)
        account_layout.addLayout(cookies_row)

        rapidapi_label = QLabel("RapidAPI Key")
        rapidapi_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(rapidapi_label)
        account_layout.addWidget(rapidapi_label)

        rapidapi_row = QHBoxLayout()
        rapidapi_row.setSpacing(6)

        self.rapidapi_key_edit = QLineEdit()
        self.rapidapi_key_edit.setFixedHeight(28)
        self.rapidapi_key_edit.setEchoMode(QLineEdit.Password)
        self.rapidapi_key_edit.setPlaceholderText("Paste your RapidAPI key")
        self.rapidapi_key_edit.editingFinished.connect(self.apply_rapidapi_key_from_input)
        allow_horizontal_shrink(self.rapidapi_key_edit)
        rapidapi_row.addWidget(self.rapidapi_key_edit, 1)

        self.rapidapi_help_button = QPushButton("?")
        self.rapidapi_help_button.setFixedHeight(28)
        self.rapidapi_help_button.setToolTip("Open RapidAPI signer page")
        keep_button_visible(self.rapidapi_help_button, minimum_width=32)
        self.rapidapi_help_button.clicked.connect(self.open_rapidapi_signer_page)
        rapidapi_row.addWidget(self.rapidapi_help_button)

        account_layout.addLayout(rapidapi_row)

        self.account_username = QLineEdit()
        self.account_username.setReadOnly(True)
        self.account_username.setFixedHeight(28)
        allow_horizontal_shrink(self.account_username)
        add_account_field("Username", self.account_username)

        self.account_user_id = QLineEdit()
        self.account_user_id.setReadOnly(True)
        self.account_user_id.setFixedHeight(28)
        allow_horizontal_shrink(self.account_user_id)
        add_account_field("User ID", self.account_user_id)

        self.can_go_live_output = QLineEdit()
        self.can_go_live_output.setReadOnly(True)
        self.can_go_live_output.setFixedHeight(28)
        allow_horizontal_shrink(self.can_go_live_output)
        add_account_field("Can Go Live", self.can_go_live_output)

        self.account_status = QLineEdit()
        self.account_status.setReadOnly(True)
        self.account_status.setFixedHeight(28)
        allow_horizontal_shrink(self.account_status)
        add_account_field("Status", self.account_status)

        self.device_id_display = QLineEdit()
        self.device_id_display.setReadOnly(True)
        self.device_id_display.setFixedHeight(28)
        allow_horizontal_shrink(self.device_id_display)
        add_account_field("Device ID", self.device_id_display)

        self.install_id_display = QLineEdit()
        self.install_id_display.setReadOnly(True)
        self.install_id_display.setFixedHeight(28)
        allow_horizontal_shrink(self.install_id_display)
        add_account_field("Install ID", self.install_id_display)

        self.refresh_account_button = QPushButton("Refresh Account Info")
        self.refresh_account_button.clicked.connect(lambda: self.refresh_account_info())
        self.refresh_account_button.setFixedHeight(30)
        allow_button_shrink(self.refresh_account_button)
        account_layout.addWidget(self.refresh_account_button)

        account_layout.addStretch(1)
        root_layout.addWidget(account_group, 1, 0)

        output_group = QGroupBox("Stream Output and Monitoring")
        output_group.setMinimumWidth(0)
        output_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(5)

        controls_label = QLabel("Stream Controls")
        controls_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(controls_label)
        output_layout.addWidget(controls_label)

        primary_controls_row = QHBoxLayout()
        primary_controls_row.setSpacing(5)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.start_login)
        self.login_button.setFixedHeight(32)
        allow_button_shrink(self.login_button)
        primary_controls_row.addWidget(self.login_button)

        self.go_live_button = QPushButton("Go Live")
        self.go_live_button.clicked.connect(self.generate_stream)
        self.go_live_button.setFixedHeight(32)
        allow_button_shrink(self.go_live_button)
        primary_controls_row.addWidget(self.go_live_button)

        output_layout.addLayout(primary_controls_row)

        live_controls_row = QHBoxLayout()
        live_controls_row.setSpacing(5)

        self.pause_live_button = QPushButton("Pause")
        self.pause_live_button.setEnabled(False)
        self.pause_live_button.clicked.connect(self.pause_stream)
        self.pause_live_button.setFixedHeight(32)
        allow_button_shrink(self.pause_live_button)
        live_controls_row.addWidget(self.pause_live_button)

        self.resume_live_button = QPushButton("Resume")
        self.resume_live_button.setEnabled(False)
        self.resume_live_button.clicked.connect(self.resume_stream)
        self.resume_live_button.setFixedHeight(32)
        allow_button_shrink(self.resume_live_button)
        live_controls_row.addWidget(self.resume_live_button)

        self.end_live_button = QPushButton("End Live")
        self.end_live_button.setEnabled(False)
        self.end_live_button.clicked.connect(self.end_stream)
        self.end_live_button.setFixedHeight(32)
        allow_button_shrink(self.end_live_button)
        live_controls_row.addWidget(self.end_live_button)

        output_layout.addLayout(live_controls_row)

        self.url_output = QLineEdit()
        self.url_output.setReadOnly(True)
        self.url_output.setFixedHeight(28)
        allow_horizontal_shrink(self.url_output)

        self.key_output = QLineEdit()
        self.key_output.setReadOnly(True)
        self.key_output.setFixedHeight(28)
        allow_horizontal_shrink(self.key_output)

        self.share_url_output = QLineEdit()
        self.share_url_output.setReadOnly(True)
        self.share_url_output.setFixedHeight(28)
        allow_horizontal_shrink(self.share_url_output)

        def add_output_row(label_text, output_widget, copy_label):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            output_layout.addWidget(label)
            row = QHBoxLayout()
            row.setSpacing(5)
            row.addWidget(output_widget)
            copy_button = QPushButton(copy_label)
            copy_button.setFixedHeight(28)
            copy_button.setProperty("copy_default_text", copy_label)
            allow_button_shrink(copy_button)
            copy_button.clicked.connect(
                lambda checked=False, widget=output_widget, button=copy_button: self.copy_to_clipboard(
                    widget.text(),
                    button,
                )
            )
            row.addWidget(copy_button)
            output_layout.addLayout(row)

        add_output_row("Stream URL:", self.url_output, "Copy")
        add_output_row("Stream Key:", self.key_output, "Copy")
        add_output_row("Share URL:", self.share_url_output, "Copy")

        proxy_row = QHBoxLayout()
        proxy_row.setSpacing(5)
        proxy_label = QLabel("Proxy Status:")
        proxy_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(proxy_label)
        proxy_row.addWidget(proxy_label)
        self.proxy_status_output = QLineEdit()
        self.proxy_status_output.setReadOnly(True)
        self.proxy_status_output.setFixedHeight(28)
        allow_horizontal_shrink(self.proxy_status_output)
        proxy_row.addWidget(self.proxy_status_output)
        self.toggle_stream_credentials_button = QPushButton("Show Real TikTok URL")
        self.toggle_stream_credentials_button.setEnabled(False)
        self.toggle_stream_credentials_button.setFixedHeight(28)
        allow_button_shrink(self.toggle_stream_credentials_button)
        self.toggle_stream_credentials_button.clicked.connect(self.toggle_stream_credentials_display)
        proxy_row.addWidget(self.toggle_stream_credentials_button)
        output_layout.addLayout(proxy_row)

        stats_group = QGroupBox("Realtime Stats")
        stats_layout = QGridLayout(stats_group)
        stats_layout.setHorizontalSpacing(8)
        stats_layout.setVerticalSpacing(5)

        def add_stats_field(row, column, label_text, widget):
            label = QLabel(label_text)
            label.setMinimumWidth(70)
            stats_layout.addWidget(label, row, column)
            stats_layout.addWidget(widget, row, column + 1)

        self.live_status_stats_output = QLineEdit()
        self.live_status_stats_output.setReadOnly(True)
        self.live_status_stats_output.setFixedHeight(28)
        allow_horizontal_shrink(self.live_status_stats_output)
        add_stats_field(0, 0, "Live", self.live_status_stats_output)

        self.live_viewer_count_output = QLineEdit()
        self.live_viewer_count_output.setReadOnly(True)
        self.live_viewer_count_output.setFixedHeight(28)
        allow_horizontal_shrink(self.live_viewer_count_output)
        add_stats_field(0, 2, "Live Viewers", self.live_viewer_count_output)

        self.viewer_count_output = QLineEdit()
        self.viewer_count_output.setReadOnly(True)
        self.viewer_count_output.setFixedHeight(28)
        allow_horizontal_shrink(self.viewer_count_output)
        add_stats_field(1, 0, "Views", self.viewer_count_output)

        self.like_count_output = QLineEdit()
        self.like_count_output.setReadOnly(True)
        self.like_count_output.setFixedHeight(28)
        allow_horizontal_shrink(self.like_count_output)
        add_stats_field(1, 2, "Likes", self.like_count_output)

        self.comment_count_output = QLineEdit()
        self.comment_count_output.setReadOnly(True)
        self.comment_count_output.setFixedHeight(28)
        allow_horizontal_shrink(self.comment_count_output)
        add_stats_field(2, 0, "Comments", self.comment_count_output)

        self.share_count_output = QLineEdit()
        self.share_count_output.setReadOnly(True)
        self.share_count_output.setFixedHeight(28)
        allow_horizontal_shrink(self.share_count_output)
        add_stats_field(2, 2, "Shares", self.share_count_output)

        self.new_fans_count_output = QLineEdit()
        self.new_fans_count_output.setReadOnly(True)
        self.new_fans_count_output.setFixedHeight(28)
        allow_horizontal_shrink(self.new_fans_count_output)
        add_stats_field(3, 0, "New Fans", self.new_fans_count_output)

        self.refresh_stats_button = QPushButton("Refresh Stats")
        self.refresh_stats_button.clicked.connect(lambda: self.refresh_realtime_stats(force=True))
        self.refresh_stats_button.setFixedHeight(28)
        allow_button_shrink(self.refresh_stats_button)
        stats_layout.addWidget(self.refresh_stats_button, 4, 0, 1, 4)

        stats_layout.setColumnStretch(1, 1)
        stats_layout.setColumnStretch(3, 1)
        output_layout.addWidget(stats_group)

        monitoring_group = QGroupBox("Audience and Safety")
        monitoring_group.setMinimumWidth(0)
        monitoring_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        monitoring_layout = QVBoxLayout(monitoring_group)
        monitoring_layout.setSpacing(8)

        audience_summary_group = QGroupBox("Online Audience")
        audience_summary_layout = QGridLayout(audience_summary_group)
        audience_summary_layout.setHorizontalSpacing(8)
        audience_summary_layout.setVerticalSpacing(5)

        def add_audience_field(row, column, label_text, widget):
            label = QLabel(label_text)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            audience_summary_layout.addWidget(label, row, column)
            audience_summary_layout.addWidget(widget, row, column + 1)

        self.online_audience_total_output = QLineEdit()
        self.online_audience_total_output.setReadOnly(True)
        self.online_audience_total_output.setFixedHeight(28)
        allow_horizontal_shrink(self.online_audience_total_output)
        add_audience_field(0, 0, "Total", self.online_audience_total_output)

        self.online_audience_preview_output = QLineEdit()
        self.online_audience_preview_output.setReadOnly(True)
        self.online_audience_preview_output.setFixedHeight(28)
        allow_horizontal_shrink(self.online_audience_preview_output)
        add_audience_field(0, 2, "Preview", self.online_audience_preview_output)

        self.online_audience_table_output = QTableWidget(0, 5)
        self.online_audience_table_output.setHorizontalHeaderLabels(["#", "Display ID", "Nickname", "Score", "Badges"])
        self.online_audience_table_output.setAlternatingRowColors(True)
        self.online_audience_table_output.setMinimumHeight(150)
        self.online_audience_table_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.online_audience_table_output.verticalHeader().setVisible(False)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.online_audience_table_output.setWordWrap(False)
        self.online_audience_table_output.setTextElideMode(Qt.ElideRight)
        audience_summary_layout.addWidget(QLabel("Visible Audience"), 1, 0, 1, 4)
        audience_summary_layout.addWidget(self.online_audience_table_output, 2, 0, 1, 4)
        audience_summary_layout.setColumnStretch(1, 1)
        audience_summary_layout.setColumnStretch(3, 1)
        monitoring_layout.addWidget(audience_summary_group)

        safety_group = QGroupBox("Safety")
        safety_layout = QGridLayout(safety_group)
        safety_layout.setHorizontalSpacing(8)
        safety_layout.setVerticalSpacing(5)

        def add_safety_field(row, column, label_text, widget):
            label = QLabel(label_text)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            safety_layout.addWidget(label, row, column)
            safety_layout.addWidget(widget, row, column + 1)

        self.violation_status_output = QLineEdit()
        self.violation_status_output.setReadOnly(True)
        self.violation_status_output.setFixedHeight(28)
        allow_horizontal_shrink(self.violation_status_output)
        add_safety_field(0, 0, "Status", self.violation_status_output)

        self.community_status_output = QLineEdit()
        self.community_status_output.setReadOnly(True)
        self.community_status_output.setFixedHeight(28)
        allow_horizontal_shrink(self.community_status_output)
        add_safety_field(0, 2, "Community", self.community_status_output)

        self.ban_status_output = QLineEdit()
        self.ban_status_output.setReadOnly(True)
        self.ban_status_output.setFixedHeight(28)
        allow_horizontal_shrink(self.ban_status_output)
        add_safety_field(1, 0, "Ban", self.ban_status_output)

        self.perception_status_output = QLineEdit()
        self.perception_status_output.setReadOnly(True)
        self.perception_status_output.setFixedHeight(28)
        allow_horizontal_shrink(self.perception_status_output)
        add_safety_field(1, 2, "Perception", self.perception_status_output)

        self.violation_details_output = QTableWidget(0, 3)
        self.violation_details_output.setHorizontalHeaderLabels(["Type", "Status", "Details"])
        self.violation_details_output.setAlternatingRowColors(True)
        self.violation_details_output.setMinimumHeight(170)
        self.violation_details_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.violation_details_output.verticalHeader().setVisible(False)
        self.violation_details_output.horizontalHeader().setStretchLastSection(True)
        self.violation_details_output.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.violation_details_output.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.violation_details_output.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.violation_details_output.setWordWrap(True)
        self.violation_details_output.setTextElideMode(Qt.ElideRight)
        safety_layout.addWidget(QLabel("Details"), 2, 0, 1, 4)
        safety_layout.addWidget(self.violation_details_output, 3, 0, 1, 4)

        self.refresh_audience_safety_button = QPushButton("Refresh Audience / Safety")
        self.refresh_audience_safety_button.clicked.connect(lambda: self.refresh_audience_safety(force=True))
        self.refresh_audience_safety_button.setFixedHeight(28)
        allow_button_shrink(self.refresh_audience_safety_button)
        safety_layout.addWidget(self.refresh_audience_safety_button, 4, 0, 1, 4)
        safety_layout.setColumnStretch(1, 1)
        safety_layout.setColumnStretch(3, 1)
        monitoring_layout.addWidget(safety_group)
        monitoring_layout.addStretch()


        output_layout.addStretch()

        # Bottom buttons
        bottom_buttons = QHBoxLayout()
        bottom_buttons.setSpacing(5)

        self.save_config_button = QPushButton("Save Config")
        self.save_config_button.clicked.connect(lambda: self.save_config())
        self.save_config_button.setFixedHeight(32)
        allow_button_shrink(self.save_config_button)
        bottom_buttons.addWidget(self.save_config_button)

        self.donate_button = QPushButton("Donate")
        self.donate_button.setToolTip("Support development")
        self.donate_button.clicked.connect(self.open_donation_url)
        self.donate_button.setFixedHeight(32)
        allow_button_shrink(self.donate_button)
        bottom_buttons.addWidget(self.donate_button)

        output_layout.addLayout(bottom_buttons)

        root_layout.addWidget(output_group, 0, 1, 2, 1)
        root_layout.addWidget(monitoring_group, 0, 2, 2, 1)

        root_layout.setColumnStretch(0, 1)
        root_layout.setColumnStretch(1, 1)
        root_layout.setColumnStretch(2, 1)

        self.on_topic_changed(self.topic_combo.currentText())

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message):
        QMessageBox.information(self, "Info", message)

    def get_selected_topic_id(self):
        selected = self.topic_combo.currentText().strip().lower()
        for topic_id, topic_name in TOPICS.items():
            if topic_name.lower() == selected:
                return topic_id
        return ""

    def get_selected_game_id(self):
        selected = self.game_combo.currentText().strip().lower()
        for game_id, game_name in self.games.items():
            if game_name.lower() == selected:
                return game_id
        return ""

    def on_topic_changed(self, topic_name):
        is_gaming = topic_name == "Gaming"
        self.game_label.setVisible(is_gaming)
        self.game_combo.setVisible(is_gaming)

    def browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select an Image",
            "",
            "Images (*.png *.jpg *.jpeg);;All files (*.*)",
        )
        if file_path:
            self.thumbnail_edit.setText(file_path)

    def copy_to_clipboard(self, content, button=None):
        QGuiApplication.clipboard().setText(content)
        if button is None:
            return

        original_text = button.property("copy_default_text") or button.text()
        button.setProperty("copy_default_text", original_text)
        button.setText("Copied!")
        button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.restore_copy_button(button, original_text))

    def restore_copy_button(self, button, original_text):
        try:
            button.setText(original_text)
            button.setEnabled(True)
        except RuntimeError:
            pass

    def clear_output_fields(self):
        self.url_output.clear()
        self.key_output.clear()
        self.share_url_output.clear()
        self.clear_realtime_stats_fields()
        self.clear_audience_safety_fields()
        self.real_stream_url = ""
        self.real_base_stream_url = ""
        self.real_stream_key = ""
        self.real_share_url = ""
        self.active_violation_ids = set()
        self.local_proxy_server_url = ""
        self.local_proxy_stream_key = LOCAL_PROXY_STREAM_KEY
        self.show_real_stream_credentials = False
        self.toggle_stream_credentials_button.setText("Show Real TikTok URL")
        self.toggle_stream_credentials_button.setEnabled(False)
        if hasattr(self, "proxy_status_output") and not self.local_proxy_active:
            self.proxy_status_output.clear()

    def clear_realtime_stats_fields(self):
        self.live_status_stats_output.clear()
        self.live_viewer_count_output.clear()
        self.viewer_count_output.clear()
        self.like_count_output.clear()
        self.comment_count_output.clear()
        self.share_count_output.clear()
        self.new_fans_count_output.clear()

    def clear_audience_safety_fields(self):
        if not hasattr(self, "online_audience_total_output"):
            return
        self.online_audience_total_output.clear()
        self.online_audience_preview_output.clear()
        self.online_audience_table_output.setRowCount(0)
        self.violation_status_output.clear()
        self.community_status_output.clear()
        self.ban_status_output.clear()
        self.perception_status_output.clear()
        self.violation_details_output.setRowCount(0)

    def format_stat_value(self, value):
        if value in (None, ""):
            return ""
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)

    def sync_realtime_stats_timer(self):
        should_run = bool(self.is_live and self.current_room_id)
        if should_run:
            if not self.realtime_stats_timer.isActive():
                self.realtime_stats_timer.start()
        else:
            self.realtime_stats_timer.stop()

    def refresh_realtime_stats(self, force=False):
        if self.realtime_stats_in_flight:
            return
        if not self.current_room_id:
            self.sync_realtime_stats_timer()
            return
        if not self.is_live and not force:
            self.sync_realtime_stats_timer()
            return
        if not self.get_cookie_file_status()[0]:
            return

        self.realtime_stats_in_flight = True
        if force:
            self.refresh_stats_button.setEnabled(False)
            self.refresh_stats_button.setText("Refreshing...")

        room_id = self.current_room_id
        priority_region = self.stream_priority_region or self.region_combo.currentText()

        def worker():
            try:
                with Stream() as stream:
                    stats = stream.getRealtimeStats(
                        device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=priority_region,
                        room_id=room_id,
                    )
                    try:
                        trends = stream.getTrendsStats(
                            device_id=self.device_id,
                            install_id=self.install_id,
                            priority_region=priority_region,
                            room_id=room_id,
                        )
                        stats["live_viewer_count"] = trends.get("current_viewers")
                        stats["live_viewer_followed_count"] = trends.get("current_viewers_followed")
                        stats["current_viewers_trends"] = trends.get("current_viewers_trends")
                        stats["total_viewers_trends"] = trends.get("total_viewers_trends")
                    except Exception as trends_exc:
                        stats["trends_error"] = str(trends_exc)
                self.realtime_stats_loaded.emit(stats)
            except Exception as exc:
                self.realtime_stats_failed.emit(str(exc))
            finally:
                self.realtime_stats_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def apply_realtime_stats(self, stats):
        self.refresh_stats_button.setEnabled(True)
        self.refresh_stats_button.setText("Refresh Stats")
        is_live = stats.get("is_live")
        if is_live is True:
            self.live_status_stats_output.setText("Yes")
        elif is_live is False:
            self.live_status_stats_output.setText("No")
        else:
            self.live_status_stats_output.setText("")
        self.live_viewer_count_output.setText(self.format_stat_value(stats.get("live_viewer_count")))
        self.viewer_count_output.setText(self.format_stat_value(stats.get("watch_count")))
        self.like_count_output.setText(self.format_stat_value(stats.get("like_count")))
        self.comment_count_output.setText(self.format_stat_value(stats.get("comment_count")))
        self.share_count_output.setText(self.format_stat_value(stats.get("share_count")))
        self.new_fans_count_output.setText(self.format_stat_value(stats.get("new_fans_count")))

    def handle_realtime_stats_error(self, message):
        self.refresh_stats_button.setEnabled(True)
        self.refresh_stats_button.setText("Refresh Stats")
        if message:
            print(f"Realtime stats refresh failed: {message}")

    def sync_audience_safety_timer(self):
        should_run = bool(self.is_live and self.current_room_id)
        if should_run:
            if not self.audience_safety_timer.isActive():
                self.audience_safety_timer.start()
        else:
            self.audience_safety_timer.stop()

    def _audience_entry_user(self, entry):
        if not isinstance(entry, dict):
            return {}
        user = (
            entry.get("user")
            or entry.get("user_info")
            or entry.get("owner")
            or entry.get("account")
            or entry.get("user_data")
            or {}
        )
        return user if isinstance(user, dict) else {}

    def _audience_badge_text(self, entry, user):
        badge_values = []

        def add_badge(value):
            value = str(value or "").strip()
            if value and value not in badge_values:
                badge_values.append(value)

        for source in (entry, user):
            if not isinstance(source, dict):
                continue

            pay_grade = source.get("pay_grade") or {}
            if isinstance(pay_grade, dict):
                level = pay_grade.get("level") or pay_grade.get("grade")
                if level not in (None, "", 0, "0"):
                    add_badge(f"Lv {level}")

            fans_club = source.get("fans_club_info") or source.get("fansclub_info") or {}
            if isinstance(fans_club, dict):
                level = fans_club.get("fans_level") or fans_club.get("level")
                name = fans_club.get("fans_club_name") or fans_club.get("club_name")
                if name and level not in (None, "", 0, "0"):
                    add_badge(f"{name} Lv {level}")
                elif name:
                    add_badge(name)
                elif level not in (None, "", 0, "0"):
                    add_badge(f"Fans Lv {level}")

            for badge in source.get("badge_list") or source.get("badges") or []:
                if not isinstance(badge, dict):
                    continue
                combine = badge.get("combine") or {}
                if isinstance(combine, dict):
                    add_badge(combine.get("str") or combine.get("text"))
                add_badge(
                    badge.get("name")
                    or badge.get("title")
                    or badge.get("text")
                    or badge.get("display_text")
                    or badge.get("level")
                )

        return ", ".join(badge_values[:4])

    def _audience_entry_fields(self, entry, index):
        if not isinstance(entry, dict):
            return {
                "rank": index,
                "display_id": str(entry),
                "nickname": "",
                "score": "",
                "badges": "",
            }

        user = self._audience_entry_user(entry)
        display_id = (
            user.get("display_id")
            or user.get("unique_id")
            or user.get("username")
            or entry.get("display_id")
            or entry.get("unique_id")
            or entry.get("username")
            or user.get("id_str")
            or entry.get("id_str")
            or "Unknown"
        )
        nickname = (
            user.get("nickname")
            or user.get("nick_name")
            or entry.get("nickname")
            or entry.get("nick_name")
            or ""
        )
        score = (
            entry.get("score")
            or entry.get("rank_score")
            or entry.get("coin_count")
            or entry.get("contribution")
            or entry.get("value")
            or entry.get("room_score")
            or ""
        )
        rank = entry.get("rank") or entry.get("rank_index") or entry.get("rank_num") or index
        return {
            "rank": rank,
            "display_id": display_id,
            "nickname": nickname,
            "score": score,
            "badges": self._audience_badge_text(entry, user),
        }

    def _format_community_status(self, safety):
        parts = []
        if safety.get("community_flagged"):
            parts.append("Flagged")
        if safety.get("community_review"):
            parts.append("Review")
        return " / ".join(parts) if parts else "OK"

    def _format_ban_status(self, safety):
        parts = []
        if safety.get("ban_active"):
            parts.append("Banned")
        if safety.get("advanced_ban_active"):
            parts.append("Advanced ban")
        block_status = safety.get("block_status")
        if block_status not in (0, "0", None, ""):
            parts.append(f"Blocked {block_status}")
        if safety.get("locale_restricted"):
            parts.append("Locale restricted")
        return " / ".join(parts) if parts else "None"

    def _format_perception_status(self, safety):
        active = safety.get("active_perception_statuses") or []
        if active:
            return f"Active ({len(active)})"
        if safety.get("violations_entrance"):
            end_time = safety.get("violations_entrance_end_time")
            return f"Warning until {end_time}" if end_time else "Warning"
        summary = safety.get("perception_summary")
        if summary and summary not in ("None", "Unavailable"):
            return summary[:120]
        return "OK"

    def _set_table_item(self, table, row, column, text):
        item = QTableWidgetItem(str(text or ""))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, column, item)

    def _add_safety_detail_row(self, detail_type, status, details):
        row = self.violation_details_output.rowCount()
        self.violation_details_output.insertRow(row)
        self._set_table_item(self.violation_details_output, row, 0, detail_type)
        self._set_table_item(self.violation_details_output, row, 1, status)
        self._set_table_item(self.violation_details_output, row, 2, details)

    def _populate_audience_list(self, ranks, notice):
        self.online_audience_table_output.setRowCount(0)
        self.online_audience_table_output.clearSpans()

        if ranks:
            for index, entry in enumerate(ranks[:50]):
                fields = self._audience_entry_fields(entry, index + 1)
                row = self.online_audience_table_output.rowCount()
                self.online_audience_table_output.insertRow(row)
                self._set_table_item(self.online_audience_table_output, row, 0, fields.get("rank"))
                self._set_table_item(self.online_audience_table_output, row, 1, fields.get("display_id"))
                self._set_table_item(self.online_audience_table_output, row, 2, fields.get("nickname"))
                self._set_table_item(self.online_audience_table_output, row, 3, fields.get("score"))
                self._set_table_item(self.online_audience_table_output, row, 4, fields.get("badges"))

            if len(ranks) > 50:
                row = self.online_audience_table_output.rowCount()
                self.online_audience_table_output.insertRow(row)
                self.online_audience_table_output.setSpan(row, 0, 1, 5)
                self._set_table_item(self.online_audience_table_output, row, 0, f"... {len(ranks) - 50} more entries")
            return

        row = self.online_audience_table_output.rowCount()
        self.online_audience_table_output.insertRow(row)
        self.online_audience_table_output.setSpan(row, 0, 1, 5)
        self._set_table_item(self.online_audience_table_output, row, 0, notice or "No visible audience entries.")

    def refresh_audience_safety(self, force=False):
        if self.audience_safety_in_flight:
            return
        if not self.current_room_id:
            self.sync_audience_safety_timer()
            return
        if not self.is_live and not force:
            self.sync_audience_safety_timer()
            return
        if not self.get_cookie_file_status()[0]:
            return

        self.audience_safety_in_flight = True
        if force:
            self.refresh_audience_safety_button.setEnabled(False)
            self.refresh_audience_safety_button.setText("Refreshing...")

        room_id = self.current_room_id
        anchor_id = self.current_anchor_id or self.account_user_id.text().strip()
        priority_region = self.stream_priority_region or self.region_combo.currentText()
        topic_id = self.get_selected_topic_id() or "5"

        def worker():
            try:
                with Stream() as stream:
                    audience = stream.getOnlineAudience(
                        device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=priority_region,
                        room_id=room_id,
                        anchor_id=anchor_id,
                    )
                    safety = stream.getViolationStatus(
                        device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=priority_region,
                        room_id=room_id,
                        last_time_hashtag_id=topic_id,
                    )
                self.audience_safety_loaded.emit({"audience": audience, "safety": safety})
            except Exception as exc:
                self.audience_safety_failed.emit(str(exc))
            finally:
                self.audience_safety_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def apply_audience_safety(self, result):
        self.refresh_audience_safety_button.setEnabled(True)
        self.refresh_audience_safety_button.setText("Refresh Audience / Safety")

        audience = result.get("audience") or {}
        safety = result.get("safety") or {}

        self.online_audience_total_output.setText(self.format_stat_value(audience.get("total")))
        self.online_audience_preview_output.setText(self.format_stat_value(audience.get("preview_count")))
        ranks = audience.get("ranks") or []
        self._populate_audience_list(ranks, audience.get("bottom_notice"))

        self.violation_status_output.setText(str(safety.get("status") or "Unknown"))
        self.community_status_output.setText(self._format_community_status(safety))
        self.ban_status_output.setText(self._format_ban_status(safety))
        self.perception_status_output.setText(self._format_perception_status(safety))

        active_summaries = safety.get("active_violation_summaries") or []
        active_ids = set(safety.get("active_violation_ids") or [])
        new_ids = active_ids - self.active_violation_ids
        if new_ids:
            first_summary = active_summaries[0] if active_summaries else "A new LIVE violation was detected."
            self.new_violation_detected.emit(first_summary)
        self.active_violation_ids = active_ids

        active_count = safety.get("active_violation_count", 0) or 0
        history_count = safety.get("history_violation_count")
        self.violation_details_output.setRowCount(0)
        self._add_safety_detail_row("Active", self.format_stat_value(active_count), "No active violations" if not active_count else "Active moderation item detected")
        if history_count not in (None, ""):
            self._add_safety_detail_row("History", self.format_stat_value(history_count), "Past records hidden from active status")

        if active_summaries:
            for line in active_summaries[:8]:
                self._add_safety_detail_row("Violation", "Active", line)
            if len(active_summaries) > 8:
                self._add_safety_detail_row("Violation", "More", f"{len(active_summaries) - 8} more active items")

        perception_statuses = safety.get("perception_violation_statuses") or []
        for item in perception_statuses[:8]:
            scene = item.get("scene", "")
            status = item.get("status", "")
            summary = item.get("summary", "")
            self._add_safety_detail_row(f"Scene {scene}", status if status not in (None, "") else "OK", summary)

        perception_countdown = safety.get("perception_summary") or "None"
        if perception_countdown not in ("None", "Unavailable", ""):
            self._add_safety_detail_row("Countdown", "Active", perception_countdown)

        errors = safety.get("errors") or []
        for error in errors[:4]:
            self._add_safety_detail_row("Optional", "Unavailable", error)
        if len(errors) > 4:
            self._add_safety_detail_row("Optional", "More", f"{len(errors) - 4} more optional checks unavailable")

        if self.violation_details_output.rowCount() == 0:
            self._add_safety_detail_row("Status", "OK", "No safety details available yet")
        self.violation_details_output.resizeRowsToContents()

    def handle_audience_safety_error(self, message):
        self.refresh_audience_safety_button.setEnabled(True)
        self.refresh_audience_safety_button.setText("Refresh Audience / Safety")
        if message:
            print(f"Audience/safety refresh failed: {message}")

    def flash_taskbar(self):
        try:
            QApplication.alert(self, 0)
        except Exception:
            pass

        if sys.platform != "win32":
            return

        try:
            import ctypes

            hwnd = int(self.winId())
            FLASHW_TRAY = 0x00000002
            FLASHW_TIMERNOFG = 0x0000000C

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("hwnd", ctypes.c_void_p),
                    ("dwFlags", ctypes.c_uint),
                    ("uCount", ctypes.c_uint),
                    ("dwTimeout", ctypes.c_uint),
                ]

            info = FLASHWINFO(
                ctypes.sizeof(FLASHWINFO),
                ctypes.c_void_p(hwnd),
                FLASHW_TRAY | FLASHW_TIMERNOFG,
                5,
                0,
            )
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception as exc:
            print(f"Failed to flash taskbar: {exc}")

    def handle_new_violation_detected(self, summary):
        self.flash_taskbar()
        if summary:
            print(f"New active LIVE violation detected: {summary}")

    def refresh_device_identifier_fields(self):
        self.device_id_display.setText(self.device_id)
        self.install_id_display.setText(self.install_id)

    def has_device_identifiers(self):
        return bool(self.device_id and self.install_id)

    def ensure_device_identifiers(self, show_popup=False):
        if self.has_device_identifiers():
            self.refresh_device_identifier_fields()
            return True

        progress = None
        if show_popup:
            progress = QProgressDialog(
                "Generating secure device identifiers...",
                None,
                0,
                0,
                self,
            )
            progress.setWindowTitle("Initializing")
            progress.setWindowModality(Qt.ApplicationModal)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.show()
            QApplication.processEvents()

        try:
            self.device_id, self.install_id = register_desktop_device_identifiers()
            self.refresh_device_identifier_fields()
            self.save_config(show_message=False)
            return True
        except Exception as exc:
            self.show_error(f"Failed to initialize device identifiers: {exc}")
            return False
        finally:
            if progress is not None:
                progress.close()

    def normalize_cookie_payload(self, payload):
        if isinstance(payload, dict):
            if isinstance(payload.get("cookies"), list):
                payload = payload["cookies"]
            elif isinstance(payload.get("Cookie"), list):
                payload = payload["Cookie"]
            elif "name" in payload and "value" in payload:
                payload = [payload]
            else:
                raise RuntimeError("JSON file does not look like a cookies export.")

        if not isinstance(payload, list):
            raise RuntimeError("Cookies JSON must be a list of cookie objects.")

        cookies = []
        for index, cookie in enumerate(payload, 1):
            if not isinstance(cookie, dict):
                raise RuntimeError(f"Cookie entry #{index} is not an object.")

            name = cookie.get("name")
            value = cookie.get("value")
            if name in (None, "") or value is None:
                continue

            entry = dict(cookie)
            entry["name"] = str(name)
            entry["value"] = str(value)

            if "expires" not in entry:
                for key in ("expirationDate", "expiry", "expiration_date"):
                    if key in entry:
                        try:
                            entry["expires"] = int(float(entry[key]))
                        except (TypeError, ValueError):
                            pass
                        break

            if "httpOnly" not in entry and "http_only" in entry:
                entry["httpOnly"] = bool(entry.get("http_only"))
            if "sameSite" not in entry and "same_site" in entry:
                entry["sameSite"] = entry.get("same_site")

            cookies.append(entry)

        if not cookies:
            raise RuntimeError("No usable cookies with name/value fields were found.")

        return cookies

    def load_cookie_entries_from_file(self, path):
        with open(path, "r", encoding="utf-8-sig") as file:
            payload = json.load(file)
        return self.normalize_cookie_payload(payload)

    def get_cookies_path(self):
        return _normalize_configured_path(getattr(self, "cookie_file_path", "") or DEFAULT_COOKIES_PATH)

    def set_cookies_path(self, path, *, save=True, refresh=True):
        self.cookie_file_path = _normalize_configured_path(path or DEFAULT_COOKIES_PATH)
        if hasattr(self, "cookies_path_edit"):
            self.cookies_path_edit.blockSignals(True)
            self.cookies_path_edit.setText(self.cookie_file_path)
            self.cookies_path_edit.blockSignals(False)
        if save:
            self.save_config(show_message=False)
        if refresh:
            self.check_cookies()

    def get_cookie_file_status(self):
        cookie_path = self.get_cookies_path()
        if not os.path.exists(cookie_path):
            return False, f"Cookies file not found: {cookie_path}"

        try:
            cookies = self.load_cookie_entries_from_file(cookie_path)
        except Exception as exc:
            return False, f"Invalid cookies file: {exc}"

        return True, f"Using {os.path.basename(cookie_path)} ({len(cookies)} cookies)"

    def apply_cookies_path_from_input(self):
        typed_path = self.cookies_path_edit.text().strip() if hasattr(self, "cookies_path_edit") else ""
        self.set_cookies_path(typed_path or DEFAULT_COOKIES_PATH, save=True, refresh=True)
        has_cookies, _ = self.get_cookie_file_status()
        if has_cookies:
            self.refresh_account_info(show_errors=False)

    def browse_cookies_file(self):
        start_dir = os.path.dirname(self.get_cookies_path())
        if not os.path.isdir(start_dir):
            start_dir = ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cookies JSON",
            start_dir,
            "JSON files (*.json);;All files (*.*)",
        )
        if not file_path:
            return

        try:
            self.load_cookie_entries_from_file(file_path)
        except Exception as exc:
            self.show_error(f"Invalid cookies JSON: {exc}")
            return

        self.set_cookies_path(file_path, save=True, refresh=True)
        self.refresh_account_info(show_errors=False)

    def get_rapidapi_key(self):
        if hasattr(self, "rapidapi_key_edit"):
            return self.rapidapi_key_edit.text().strip()
        return str(getattr(self, "rapidapi_key", "") or "").strip()

    def set_rapidapi_key(self, key, *, save=True):
        self.rapidapi_key = str(key or "").strip()
        if hasattr(self, "rapidapi_key_edit"):
            self.rapidapi_key_edit.blockSignals(True)
            self.rapidapi_key_edit.setText(self.rapidapi_key)
            self.rapidapi_key_edit.blockSignals(False)
        if save:
            self.save_config(show_message=False)

    def apply_rapidapi_key_from_input(self):
        self.set_rapidapi_key(self.get_rapidapi_key(), save=True)

    def open_rapidapi_signer_page(self):
        QDesktopServices.openUrl(QUrl(RAPIDAPI_SIGNER_DOCS_URL))

    def check_cookies(self):
        has_cookies, status_text = self.get_cookie_file_status()
        if hasattr(self, "cookies_path_edit"):
            self.cookies_path_edit.setToolTip(status_text)
            self.cookies_path_edit.setStyleSheet("" if has_cookies else "border: 1px solid #c0392b;")
        if not has_cookies:
            self.account_can_go_live = None

        self.login_button.setEnabled(True)
        self.update_stream_controls(has_cookies=has_cookies)

    def set_proxy_status(self, message):
        if hasattr(self, "proxy_status_output"):
            self.proxy_status_output.setText(str(message or ""))

    def toggle_stream_credentials_display(self):
        if not self.real_stream_url:
            return
        self.show_real_stream_credentials = not self.show_real_stream_credentials
        self.refresh_stream_credentials_display()

    def refresh_stream_credentials_display(self):
        self.share_url_output.setText(self.real_share_url)
        has_real_credentials = bool(self.real_base_stream_url and self.real_stream_key)
        has_local_credentials = bool(self.local_proxy_active and self.local_proxy_server_url)
        self.toggle_stream_credentials_button.setEnabled(has_real_credentials and has_local_credentials)

        if self.show_real_stream_credentials or not has_local_credentials:
            self.url_output.setText(self.real_base_stream_url)
            self.key_output.setText(self.real_stream_key)
            self.toggle_stream_credentials_button.setText("Show Local OBS URL")
            return

        self.url_output.setText(self.local_proxy_server_url)
        self.key_output.setText(self.local_proxy_stream_key)
        self.toggle_stream_credentials_button.setText("Show Real TikTok URL")

    def ffmpeg_proxy_is_running(self):
        return self.ffmpeg_proxy_process is not None and self.ffmpeg_proxy_process.poll() is None

    def build_ffmpeg_proxy_command(self, ffmpeg_path, local_input_url, tiktok_output_url):
        return [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-rtmp_listen",
            "1",
            "-timeout",
            str(LOCAL_PROXY_LISTEN_TIMEOUT_SECONDS),
            "-i",
            local_input_url,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-f",
            "flv",
            tiktok_output_url,
        ]

    def start_ffmpeg_proxy(self, tiktok_output_url):
        self.stop_ffmpeg_proxy(clear_status=False)
        if not tiktok_output_url:
            raise RuntimeError("Missing TikTok RTMP URL for local FFmpeg proxy.")

        ffmpeg_path = _bundled_ffmpeg_path()
        self.local_proxy_port = _pick_local_proxy_port(LOCAL_PROXY_DEFAULT_PORT)
        self.local_proxy_stream_key = LOCAL_PROXY_STREAM_KEY
        self.local_proxy_server_url = f"rtmp://127.0.0.1:{self.local_proxy_port}/{LOCAL_PROXY_APP_NAME}"
        local_input_url = f"{self.local_proxy_server_url}/{self.local_proxy_stream_key}"
        self.ffmpeg_proxy_log_path = os.path.join(_runtime_logs_dir(), LOCAL_PROXY_LOG_NAME)
        self.ffmpeg_proxy_log_file = open(self.ffmpeg_proxy_log_path, "w", encoding="utf-8", errors="replace")

        command = self.build_ffmpeg_proxy_command(ffmpeg_path, local_input_url, tiktok_output_url)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.ffmpeg_proxy_process = subprocess.Popen(
            command,
            cwd=_runtime_base_dir(),
            stdin=subprocess.DEVNULL,
            stdout=self.ffmpeg_proxy_log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        time.sleep(0.35)
        return_code = self.ffmpeg_proxy_process.poll()
        if return_code is not None:
            tail = _safe_log_tail(self.ffmpeg_proxy_log_path)
            self.stop_ffmpeg_proxy(clear_status=False)
            details = f"\n\nFFmpeg log tail:\n{tail}" if tail else ""
            raise RuntimeError(f"FFmpeg proxy exited early with code {return_code}.{details}")

        self.local_proxy_active = True
        self.show_real_stream_credentials = False
        self.set_proxy_status("Proxy ready. Start streaming in OBS.")
        self.refresh_stream_credentials_display()
        return True

    def stop_ffmpeg_proxy(self, clear_status=True):
        process = self.ffmpeg_proxy_process
        self.ffmpeg_proxy_process = None
        self.local_proxy_active = False

        if process is not None and process.poll() is None:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass

        if self.ffmpeg_proxy_log_file is not None:
            try:
                self.ffmpeg_proxy_log_file.close()
            except Exception:
                pass
            self.ffmpeg_proxy_log_file = None

        if clear_status:
            self.set_proxy_status("")
        self.refresh_stream_credentials_display()

    def update_stream_controls(self, has_cookies=None):
        if has_cookies is None:
            has_cookies = self.get_cookie_file_status()[0]

        can_start = has_cookies and not self.is_live

        self.go_live_button.setEnabled(can_start)
        self.pause_live_button.setEnabled(has_cookies and self.is_live and not self.is_paused)
        self.resume_live_button.setEnabled(has_cookies and self.is_live and self.is_paused)
        self.end_live_button.setEnabled(has_cookies and self.is_live)
        self.refresh_stats_button.setEnabled(has_cookies and bool(self.current_room_id))
        if hasattr(self, "refresh_audience_safety_button"):
            self.refresh_audience_safety_button.setEnabled(has_cookies and bool(self.current_room_id))
        if hasattr(self, "toggle_stream_credentials_button"):
            self.toggle_stream_credentials_button.setEnabled(
                bool(self.real_stream_url and self.local_proxy_active and self.local_proxy_server_url)
            )

    def apply_stream_outputs(self, stream, priority_region="", start_proxy=True):
        self.clear_output_fields()
        self.real_stream_url = getattr(stream, "streamUrl", "")
        self.real_base_stream_url = getattr(stream, "baseStreamUrl", "")
        self.real_stream_key = getattr(stream, "streamKey", "")
        self.real_share_url = getattr(stream, "streamShareUrl", "")
        self.current_room_id = getattr(stream, "roomId", "")
        self.current_stream_id = getattr(stream, "streamId", "")
        self.current_anchor_id = getattr(stream, "ownerUserId", "")
        self.active_violation_ids = set()
        if priority_region:
            self.stream_priority_region = str(priority_region).strip().lower()

        self.share_url_output.setText(self.real_share_url)
        self.refresh_stream_credentials_display()

        if start_proxy and self.real_stream_url:
            try:
                self.start_ffmpeg_proxy(self.real_stream_url)
            except Exception as exc:
                self.local_proxy_active = False
                self.show_real_stream_credentials = True
                self.set_proxy_status("Proxy failed. Showing real TikTok URL.")
                self.refresh_stream_credentials_display()
                self.show_error(
                    "The local FFmpeg proxy could not start, so the real TikTok URL/key is shown instead.\n\n"
                    f"{exc}"
                )

        self.sync_realtime_stats_timer()
        self.sync_audience_safety_timer()

    def sync_anchor_heartbeat_timer(self):
        should_run = bool(
            self.is_live
            and self.current_room_id
            and self.current_stream_id
            and self.anchor_ping_status not in (ANCHOR_STATUS_DEFAULT, ANCHOR_STATUS_FINISH)
        )
        if should_run:
            if not self.anchor_heartbeat_timer.isActive():
                self.anchor_heartbeat_timer.start()
        else:
            self.anchor_heartbeat_timer.stop()

    def set_stream_state(self, *, is_live, is_paused=False):
        previous_live = self.is_live
        previous_paused = self.is_paused
        self.is_live = bool(is_live)
        self.is_paused = bool(is_paused) if self.is_live else False
        if previous_live != self.is_live or previous_paused != self.is_paused:
            self.anchor_heartbeat_error_count = 0
        if not self.is_live:
            self.current_room_id = ""
            self.current_stream_id = ""
            self.current_anchor_id = ""
            self.active_violation_ids = set()
            self.stream_priority_region = ""
            self.anchor_ping_status = ANCHOR_STATUS_DEFAULT
            self.stop_ffmpeg_proxy(clear_status=True)
        elif self.is_paused:
            self.anchor_ping_status = ANCHOR_STATUS_PAUSE
        elif self.anchor_ping_status in (ANCHOR_STATUS_DEFAULT, ANCHOR_STATUS_FINISH, ANCHOR_STATUS_PAUSE):
            self.anchor_ping_status = ANCHOR_STATUS_PREPARE
        self.sync_anchor_heartbeat_timer()
        self.sync_realtime_stats_timer()
        self.sync_audience_safety_timer()
        self.update_stream_controls()

    def start_anchor_ping_loop(self, status=ANCHOR_STATUS_PREPARE, send_immediately=True):
        self.anchor_ping_status = status
        self.anchor_heartbeat_error_count = 0
        self.sync_anchor_heartbeat_timer()
        if send_immediately:
            self.send_anchor_heartbeat(force=True)

    def send_anchor_heartbeat(self, force=False):
        if self.anchor_heartbeat_in_flight or not self.is_live:
            return

        room_id = self.current_room_id
        stream_id = self.current_stream_id
        if not room_id or not stream_id:
            self.sync_anchor_heartbeat_timer()
            return

        status = ANCHOR_STATUS_PAUSE if self.is_paused else self.anchor_ping_status
        if status in (ANCHOR_STATUS_DEFAULT, ANCHOR_STATUS_FINISH):
            self.sync_anchor_heartbeat_timer()
            return

        self.anchor_heartbeat_in_flight = True
        priority_region = self.stream_priority_region or self.region_combo.currentText()

        def worker():
            try:
                with Stream() as stream:
                    payload = stream.anchorHeartbeat(
                        status,
                        device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=priority_region,
                        room_id=room_id,
                        stream_id=stream_id,
                        action="Anchor heartbeat",
                    )

                self.anchor_heartbeat_error_count = 0
                if _is_room_is_living_payload(payload) and self.anchor_ping_status == ANCHOR_STATUS_PREPARE:
                    self.anchor_ping_status = ANCHOR_STATUS_LIVING
            except Exception as exc:
                label = {
                    ANCHOR_STATUS_PREPARE: "Prepare",
                    ANCHOR_STATUS_LIVING: "Live",
                    ANCHOR_STATUS_PAUSE: "Paused",
                    ANCHOR_STATUS_FINISH: "Finish",
                }.get(status, "Anchor")
                print(f"{label} heartbeat failed: {exc}")
                if _is_already_ended_error(exc):
                    self.anchor_heartbeat_error_count += 1
                    if self.anchor_heartbeat_error_count >= 3:
                        self.stream_ended_remotely.emit("TikTok reports that this LIVE has already ended.")
                else:
                    # Official Studio logs unknown ping errors and keeps the loop alive.
                    self.anchor_heartbeat_error_count = 0
            finally:
                self.anchor_heartbeat_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def handle_stream_ended_remotely(self, message):
        self.set_stream_state(is_live=False)
        self.clear_output_fields()
        if message:
            self.show_info(message)

    def refresh_account_info(self, show_errors=True):
        if not self.get_cookie_file_status()[0]:
            if show_errors:
                self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
            return

        if not self.ensure_device_identifiers(show_popup=show_errors):
            return

        self.refresh_account_button.setEnabled(False)
        self.refresh_account_button.setText("Refreshing...")
        topic_id = self.get_selected_topic_id() or "5"
        priority_region = self.region_combo.currentText()

        def worker():
            try:
                with Stream() as stream:
                    info = stream.getAccountInfo(
                        device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=priority_region,
                        last_time_hashtag_id=topic_id,
                    )
                self.account_info_loaded.emit(info)
            except Exception as exc:
                if show_errors:
                    self.account_info_failed.emit(f"Failed to load account info: {exc}")
                else:
                    self.account_info_failed.emit("")

        threading.Thread(target=worker, daemon=True).start()

    def apply_account_info(self, info):
        self.refresh_account_button.setEnabled(True)
        self.refresh_account_button.setText("Refresh Account Info")

        account = info.get("account", {})

        username = account.get("username") or account.get("screen_name") or account.get("name") or "Unknown"
        user_id = account.get("user_id_str") or str(account.get("user_id") or "")

        self.account_username.setText(username)
        self.account_user_id.setText(user_id)
        self.account_status.setText(info.get("status", "Unknown"))
        self.account_can_go_live = bool(info.get("can_go_live", False))
        self.can_go_live_output.setText(str(self.account_can_go_live))

        self.update_stream_controls()

    def handle_account_info_error(self, message):
        self.refresh_account_button.setEnabled(True)
        self.refresh_account_button.setText("Refresh Account Info")
        if message:
            self.show_error(message)

    def save_config(self, show_message=True):
        game_id = self.get_selected_game_id() if self.topic_combo.currentText() == "Gaming" else ""
        topic_id = self.get_selected_topic_id()

        data = {
            "title": self.title_edit.text(),
            "game_tag_id": game_id,
            "hashtag_id": topic_id,
            "priority_region": self.region_combo.currentText(),
            "generate_replay": self.replay_checkbox.isChecked(),
            "close_room_when_close_stream": self.close_room_checkbox.isChecked(),
            "age_restricted": self.age_restricted_checkbox.isChecked(),
            "device_id": self.device_id,
            "install_id": self.install_id,
            "cookies_path": self.get_cookies_path() if hasattr(self, "get_cookies_path") else _configured_cookies_path(),
            "rapidapi_key": self.get_rapidapi_key() if hasattr(self, "get_rapidapi_key") else _configured_rapidapi_key(),
            "suppress_donation_reminder": self.suppress_donation_reminder,
        }

        with open("config.json", "w", encoding="utf-8") as file:
            json.dump(data, file)

        if show_message:
            self.show_info("Settings saved.")

    def load_config(self):
        try:
            with open("config.json", "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            self.device_id = ""
            self.install_id = ""
            self.cookie_file_path = _normalize_configured_path(DEFAULT_COOKIES_PATH)
            self.rapidapi_key = ""
            if hasattr(self, "cookies_path_edit"):
                self.cookies_path_edit.blockSignals(True)
                self.cookies_path_edit.setText(self.cookie_file_path)
                self.cookies_path_edit.blockSignals(False)
            if hasattr(self, "rapidapi_key_edit"):
                self.rapidapi_key_edit.blockSignals(True)
                self.rapidapi_key_edit.setText(self.rapidapi_key)
                self.rapidapi_key_edit.blockSignals(False)
            self.refresh_device_identifier_fields()
            return

        loaded_device_id = data.get("device_id", "")
        loaded_install_id = data.get("install_id", data.get("iid", ""))
        self.device_id = str(loaded_device_id).strip() if loaded_device_id is not None else ""
        self.install_id = str(loaded_install_id).strip() if loaded_install_id is not None else ""
        self.cookie_file_path = _normalize_configured_path(data.get("cookies_path", self.cookie_file_path or DEFAULT_COOKIES_PATH))
        self.rapidapi_key = str(data.get("rapidapi_key", "") or "").strip()
        if hasattr(self, "cookies_path_edit"):
            self.cookies_path_edit.blockSignals(True)
            self.cookies_path_edit.setText(self.cookie_file_path)
            self.cookies_path_edit.blockSignals(False)
        if hasattr(self, "rapidapi_key_edit"):
            self.rapidapi_key_edit.blockSignals(True)
            self.rapidapi_key_edit.setText(self.rapidapi_key)
            self.rapidapi_key_edit.blockSignals(False)
        self.suppress_donation_reminder = data.get("suppress_donation_reminder", False)

        if self.device_id == "0":
            self.device_id = ""
        if self.install_id == "0":
            self.install_id = ""

        self.refresh_device_identifier_fields()

        self.title_edit.setText(data.get("title", ""))

        topic_name = TOPICS.get(data.get("hashtag_id", ""), "")
        self.topic_combo.setCurrentText(topic_name)
        self.on_topic_changed(self.topic_combo.currentText())

        if self.topic_combo.currentText() == "Gaming":
            game_name = self.games.get(data.get("game_tag_id", ""), "")
            self.game_combo.setCurrentText(game_name)

        self.region_combo.setCurrentText(data.get("priority_region", ""))
        self.replay_checkbox.setChecked(data.get("generate_replay", True))
        self.close_room_checkbox.setChecked(data.get("close_room_when_close_stream", False))
        self.age_restricted_checkbox.setChecked(data.get("age_restricted", False))

    def open_donation_url(self):
        QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/loukious"))

    def show_donation_reminder(self):
        if self.suppress_donation_reminder:
            return

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Support Development")
        msg.setText("Enjoying this app? Consider supporting its development.")

        dont_show_again = QCheckBox("Never show this message again")
        msg.setCheckBox(dont_show_again)

        donate_button = msg.addButton("Donate Now", QMessageBox.AcceptRole)
        msg.addButton(QMessageBox.Ok)
        donate_button.setStyleSheet("font-weight: bold;")

        msg.exec()

        if dont_show_again.isChecked():
            self.suppress_donation_reminder = True
            self.save_config(show_message=False)

        if msg.clickedButton() == donate_button:
            self.open_donation_url()

    def check_updates_on_startup(self):
        def worker():
            self.update_checked.emit(VersionChecker.check_update())

        threading.Thread(target=worker, daemon=True).start()

    def handle_update_check(self, update_info):
        if not update_info:
            return

        try:
            has_update = version.parse(update_info["latest"]) > version.parse(update_info["current"])
        except Exception:
            return

        if not has_update:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Update Available")
        msg.setText(
            f"Version {update_info['latest']} is available!\n\n"
            f"Current version: {update_info['current']}\n\n"
            "Would you like to download it now?"
        )
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)

        if msg.exec() == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(update_info["url"]))

    def start_login(self):
        if not self.ensure_device_identifiers(show_popup=True):
            return

        dialog = LoginDialog(self)
        dialog.exec()

    def start_browser_login_flow(self):
        if not self.ensure_device_identifiers(show_popup=True):
            return

        self.login_button.setEnabled(False)
        progress = QProgressDialog("Starting login flow...", None, 0, 0, self)
        progress.setWindowTitle("Login")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        # 1. Backup existing protocol registration
        backup = backup_protocol_registry()

        # 2. Start local callback server
        server_thread, port, callback_event, result = start_callback_server()
        if not server_thread:
            self.show_error("Could not start local callback server.")
            self.login_button.setEnabled(True)
            progress.close()
            return

        # 3. Register temporary protocol handler
        python_exe = sys.executable
        script_path = os.path.abspath(__file__)
        if not register_temporary_protocol_handler(python_exe, script_path, port):
            self.show_error("Failed to register temporary protocol handler. Try running as administrator?")
            restore_protocol_registry(backup)
            self.login_button.setEnabled(True)
            progress.close()
            return

        client = LiveStudioBrowserLoginClient(self.device_id, self.install_id)
        try:
            state, nonce, ticket = client.prepare_login()
            login_url = _build_onetap_auth_url(state, nonce, ticket)
            webbrowser.open(login_url)

            progress.setLabelText("Complete login in your browser...")
            QApplication.processEvents()
            callback_received = callback_event.wait(timeout=180)
            if not callback_received or not result["url"]:
                raise RuntimeError("Timeout or no callback received. Login aborted.")

            # Parse callback URL (query or fragment)
            print(f"[DEBUG] Received callback URL: {result['url']}")
            parsed = urllib.parse.urlparse(result["url"])
            query_string = parsed.query
            if not query_string and parsed.fragment:
                query_string = parsed.fragment
            query_params = urllib.parse.parse_qs(query_string)

            id_token = query_params.get("id_token", [None])[0]
            state_from_callback = query_params.get("state", [None])[0]

            if not id_token or not state_from_callback:
                raise RuntimeError(f"Invalid callback URL: missing id_token or state. URL={result['url']}")

            client.exchange_login(id_token, state_from_callback, ticket)
            client.save_cookies(self.get_cookies_path())
            self.show_info("Login successful! Cookies have been saved.")
            self.check_cookies()
            self.refresh_account_info()

        except Exception as exc:
            self.show_error(f"Login failed: {exc}")
        finally:
            client.close()
            restore_protocol_registry(backup)
            progress.close()
            self.login_button.setEnabled(True)

    def generate_stream(self):
        topic_id = self.get_selected_topic_id()
        if not topic_id:
            self.show_error("Please select a topic.")
            return

        if topic_id == "5":
            game_id = self.get_selected_game_id()
            if not game_id:
                self.show_error("Please select a game tag.")
                return
        else:
            game_id = "0"

        if not self.ensure_device_identifiers(show_popup=True):
            return

        stream_started = False
        self.go_live_button.setEnabled(False)
        self.pause_live_button.setEnabled(False)
        self.resume_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)

        try:
            with Stream() as stream:
                selected_region = self.region_combo.currentText()

                create_info_payload = stream.getCreateRoomInfo(
                    device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=selected_region,
                    last_time_hashtag_id=topic_id,
                )
                create_data = create_info_payload.get("data", {}) if isinstance(create_info_payload, dict) else {}
                live_status = create_data.get("live_status")
                last_room_id = create_data.get("last_room_id_str") or str(create_data.get("last_room_id") or "")
                already_live_hint = str(live_status) == "2"

                continuable = stream.getContinuableStreamInfo(
                    device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=selected_region,
                )

                if continuable.get("has_room"):
                    room = continuable.get("room") or {}
                    title = room.get("title") or "Untitled"
                    room_id = continuable.get("room_id") or stream.roomId
                    stream_id = continuable.get("stream_id") or stream.streamId
                    effective_region = continuable.get("priority_region") or selected_region

                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Question)
                    msg.setWindowTitle("Existing Live Room")
                    details = [
                        "TikTok reports an existing LIVE room.",
                        "",
                        f"Title: {title}",
                        f"Room ID: {room_id}",
                    ]
                    if continuable.get("can_resume"):
                        details.append("")
                        details.append("You can resume this room or end it.")
                    else:
                        details.append("")
                        details.append("This room was detected, but TikTok did not return a reusable RTMP push URL.")
                        if continuable.get("reason"):
                            details.append(continuable["reason"])
                        details.append("You can end it if the room_id and stream_id were returned.")
                    msg.setText("\n".join(details))

                    resume_button = None
                    if continuable.get("can_resume"):
                        resume_button = msg.addButton("Resume Existing", QMessageBox.AcceptRole)

                    end_button = None
                    if room_id and stream_id:
                        end_button = msg.addButton("End Existing", QMessageBox.DestructiveRole)

                    cancel_button = msg.addButton(QMessageBox.Cancel)
                    msg.setDefaultButton(resume_button or cancel_button)
                    msg.exec()

                    clicked = msg.clickedButton()
                    if clicked == cancel_button:
                        return

                    if resume_button is not None and clicked == resume_button:
                        stream.resumeStream(
                            device_id=self.device_id,
                            install_id=self.install_id,
                            priority_region=effective_region,
                            room_id=room_id,
                            stream_id=stream_id,
                        )
                        stream_started = True
                        self.apply_stream_outputs(stream, priority_region=effective_region)
                        self.anchor_ping_status = ANCHOR_STATUS_PREPARE
                        self.set_stream_state(is_live=True, is_paused=False)
                        self.start_anchor_ping_loop(ANCHOR_STATUS_PREPARE, send_immediately=True)
                        self.refresh_audience_safety(force=True)
                        self.show_info("Existing stream resumed successfully. Use the local OBS credentials shown in the output fields.")
                        return

                    if end_button is not None and clicked == end_button:
                        confirm = QMessageBox.question(
                            self,
                            "End Existing Live Room",
                            "End the existing LIVE room now?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No,
                        )
                        if confirm != QMessageBox.Yes:
                            return

                        stream.endStream(
                            device_id=self.device_id,
                            install_id=self.install_id,
                            priority_region=effective_region,
                            room_id=room_id,
                            stream_id=stream_id,
                        )
                        self.set_stream_state(is_live=False)
                        self.clear_output_fields()
                        self.show_info("Existing stream ended successfully.")
                        return

                if already_live_hint:
                    hint_parts = [
                        "TikTok reports that your account already has an active LIVE room, but this app could not recover the stream_id/RTMP details from /webcast/room/continue/.",
                    ]
                    if last_room_id and last_room_id != "0":
                        hint_parts.append(f"Last room ID: {last_room_id}")
                    if continuable.get("reason"):
                        hint_parts.append(f"Continue check: {continuable['reason']}")
                    hint_parts.append("")
                    hint_parts.append("End the LIVE from the device/platform that started it, or try again after selecting the same region used by Live Studio.")
                    self.show_error("\n".join(hint_parts))
                    return

                created = stream.createStream(
                    self.title_edit.text(),
                    topic_id,
                    game_id,
                    self.replay_checkbox.isChecked(),
                    self.close_room_checkbox.isChecked(),
                    self.age_restricted_checkbox.isChecked(),
                    selected_region,
                    self.thumbnail_edit.text(),
                    self.device_id,
                    self.install_id,
                )

                if created:
                    stream_started = True
                    self.apply_stream_outputs(stream, priority_region=selected_region)
                    self.anchor_ping_status = ANCHOR_STATUS_PREPARE
                    self.set_stream_state(is_live=True, is_paused=False)
                    self.start_anchor_ping_loop(ANCHOR_STATUS_PREPARE, send_immediately=True)
                    self.refresh_realtime_stats(force=True)
                    self.refresh_audience_safety(force=True)
                    self.show_info("Stream created successfully. Use the local OBS credentials shown in the output fields.")
        except FileNotFoundError:
            self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
        except RuntimeError as exc:
            self.show_error(str(exc))
        except Exception as exc:
            self.show_error(f"Failed to create or resume stream: {exc}")
        finally:
            if not stream_started:
                self.set_stream_state(is_live=False)
                self.clear_output_fields()

    def pause_stream(self):
        if not self.is_live:
            self.show_error("No active stream to pause.")
            return
        if self.is_paused:
            self.show_error("The stream is already paused.")
            return

        stream_paused = False
        self.anchor_heartbeat_timer.stop()
        self.pause_live_button.setEnabled(False)
        self.resume_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)

        try:
            with Stream() as stream:
                stream.pauseStream(
                    device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    room_id=self.current_room_id,
                    stream_id=self.current_stream_id,
                )
                stream_paused = True
                self.anchor_heartbeat_error_count = 0
                self.anchor_ping_status = ANCHOR_STATUS_PAUSE
                self.set_stream_state(is_live=True, is_paused=True)
                self.refresh_realtime_stats(force=True)
                self.refresh_audience_safety(force=True)
                self.show_info("Stream paused successfully.")
        except FileNotFoundError:
            self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
        except RuntimeError as exc:
            self.show_error(str(exc))
        except Exception as exc:
            self.show_error(f"Failed to pause stream: {exc}")
        finally:
            if not stream_paused:
                self.sync_anchor_heartbeat_timer()
                self.update_stream_controls()

    def resume_stream(self):
        if not self.is_live:
            self.show_error("No paused stream to resume. Use Go Live to check for a continuable stream.")
            return
        if not self.is_paused:
            self.show_error("The stream is not paused.")
            return

        stream_resumed = False
        self.anchor_heartbeat_timer.stop()
        self.pause_live_button.setEnabled(False)
        self.resume_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)

        try:
            with Stream() as stream:
                room_id = self.current_room_id
                stream_id = self.current_stream_id

                if not room_id or not stream_id:
                    if not stream.getContinuableStream(
                        device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    ):
                        raise RuntimeError("No continuable stream found.")
                    self.apply_stream_outputs(stream, priority_region=self.region_combo.currentText())
                    room_id = self.current_room_id
                    stream_id = self.current_stream_id

                stream.resumePausedStream(
                    device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    room_id=room_id,
                    stream_id=stream_id,
                )
                stream_resumed = True
                self.anchor_heartbeat_error_count = 0
                self.anchor_ping_status = ANCHOR_STATUS_LIVING
                self.set_stream_state(is_live=True, is_paused=False)
                self.refresh_realtime_stats(force=True)
                self.refresh_audience_safety(force=True)
                self.show_info("Stream resumed successfully.")
        except FileNotFoundError:
            self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
        except RuntimeError as exc:
            if _is_already_ended_error(exc):
                self.set_stream_state(is_live=False)
                self.clear_output_fields()
                self.show_error(f"Resume failed because TikTok says this LIVE has already ended: {exc}")
            else:
                self.show_error(str(exc))
        except Exception as exc:
            self.show_error(f"Failed to resume stream: {exc}")
        finally:
            if not stream_resumed:
                self.sync_anchor_heartbeat_timer()
                self.update_stream_controls()

    def end_stream(self):
        if not self.is_live:
            self.show_error("No active stream to end.")
            return

        stream_ended = False
        self.anchor_heartbeat_timer.stop()
        self.pause_live_button.setEnabled(False)
        self.resume_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)

        try:
            with Stream() as stream:
                if stream.endStream(
                    device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    room_id=self.current_room_id,
                    stream_id=self.current_stream_id,
                ):
                    stream_ended = True
                    self.set_stream_state(is_live=False)
                    self.show_info("Stream ended successfully.")
                    self.clear_output_fields()
        except FileNotFoundError:
            self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
        except RuntimeError as exc:
            if _is_already_ended_error(exc):
                stream_ended = True
                self.set_stream_state(is_live=False)
                self.clear_output_fields()
                self.show_info("TikTok reports that this LIVE has already ended, so the local stream state was cleared.")
            else:
                self.show_error(str(exc))
        except Exception as exc:
            self.show_error(f"Failed to end stream: {exc}")
        finally:
            if not stream_ended:
                self.sync_anchor_heartbeat_timer()
                self.update_stream_controls()

    def closeEvent(self, event):
        self.stop_ffmpeg_proxy(clear_status=True)
        super().closeEvent(event)



class LoginDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.client = None
        self.qr_token = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_qr_status)

        self.setWindowTitle("Login")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.qr_label = QLabel("Loading QR code...")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setMinimumSize(260, 260)
        layout.addWidget(self.qr_label)

        self.status_label = QLabel("Scan with the TikTok app.")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()

        refresh_button = QPushButton("Refresh QR Code")
        refresh_button.clicked.connect(self.load_qr_code)
        button_row.addWidget(refresh_button)

        browser_button = QPushButton("Login in Browser")
        browser_button.clicked.connect(self.open_browser_login)
        button_row.addWidget(browser_button)

        layout.addLayout(button_row)
        self.load_qr_code()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self):
        self.poll_timer.stop()
        if self.client is not None:
            self.client.close()
            self.client = None

    def load_qr_code(self):
        self.poll_timer.stop()
        if self.client is not None:
            self.client.close()

        self.client = LiveStudioBrowserLoginClient(
            self.parent_window.device_id,
            self.parent_window.install_id,
        )
        self.qr_token = None
        self.qr_label.setText("Loading QR code...")
        self.status_label.setText("Scan with the TikTok app.")
        QApplication.processEvents()

        try:
            qr_data = self.client.get_qrcode()
            qrcode_b64 = qr_data["qrcode"]
            self.qr_token = qr_data["token"]

            pixmap = QPixmap()
            if not pixmap.loadFromData(base64.b64decode(qrcode_b64)):
                raise RuntimeError("TikTok returned an unreadable QR code.")

            self.qr_label.setPixmap(
                pixmap.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.poll_timer.start(2500)
        except Exception as exc:
            self.qr_label.setText("QR login unavailable.")
            self.status_label.setText(str(exc))

    def poll_qr_status(self):
        if not self.client or not self.qr_token:
            return

        try:
            payload = self.client.check_qrconnect(self.qr_token)
            data = payload.get("data", {})
            status = data.get("status") or data.get("qr_status") or data.get("state")

            if status == "new":
                self.status_label.setText("Scan with the TikTok app.")
            elif status == "scanned":
                self.status_label.setText("Confirm login on your phone.")
            elif status == "confirmed":
                self.client.save_cookies()
                self.parent_window.check_cookies()
                self.parent_window.refresh_account_info()
                self.parent_window.show_info("Login successful! Cookies have been saved.")
                self.cleanup()
                self.accept()
            elif status in {"expired", "timeout"}:
                self.poll_timer.stop()
                self.status_label.setText("QR code expired. Refresh it and try again.")
            elif status:
                self.status_label.setText(f"QR login status: {status}")
            else:
                message = payload.get("message") or payload.get("status_msg") or str(payload)
                self.status_label.setText(message)
        except Exception as exc:
            self.poll_timer.stop()
            self.status_label.setText(f"QR login check failed: {exc}")

    def open_browser_login(self):
        self.cleanup()
        self.accept()
        self.parent_window.start_browser_login_flow()


def handle_protocol_callback(port, url):
    """Send the received URL to the main process via TCP socket."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", int(port)))
        sock.sendall(f"URL:{url}".encode())
        sock.close()
    except Exception as e:
        print(f"Failed to send callback to main process: {e}")


def main():
    # Check if this invocation is for protocol callback
    if len(sys.argv) >= 3 and sys.argv[1] == "--protocol-callback":
        port = sys.argv[2]
        url = sys.argv[3] if len(sys.argv) > 3 else ""
        handle_protocol_callback(port, url)
        return

    # Normal GUI mode
    app = QApplication(sys.argv)
    window = StreamKeyGeneratorWindow()
    window.resize(1040, 500)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
