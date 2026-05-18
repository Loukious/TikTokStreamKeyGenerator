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

ENABLE_X_GORGON_MARKER = os.getenv("TIKTOK_X_GORGON_MARKER", "1").strip() != "0"

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
    def __init__(self):
        self.s = requests.session()
        self.s.headers.update(build_common_headers(self.s))
        self.roomId = ""
        self.streamId = ""
        with open("cookies.json", "r", encoding="utf-8") as file:
            cookies_file = json.load(file)

        cookies = {}
        for cookie in cookies_file:
            cookies[cookie["name"]] = cookie["value"]
        self.s.cookies.update(cookies)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.s.close()

    def save_cookies(self, path="cookies.json"):
        cookies = _export_cookie_jar(self.s.cookies)
        if cookies:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(cookies, file, indent=2)
        return cookies

    def getLiveStudioLatestVersion(self):
        return fetch_live_studio_latest_version(self.s)

    def _studio_params(self, *, device_id="", install_id="", priority_region=""):
        version = self.getLiveStudioLatestVersion()
        browser_version = build_live_studio_browser_version(version)
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
        timestamp = get_synced_unix_seconds()
        headers = _build_signature_headers(
            timestamp,
            params.get("aid", "8311"),
            params=params,
            x_ss_stub=None,
        )
        if priority_region:
            headers["x-tt-store-region"] = priority_region
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
        include_x_gorgon_marker=False,
        headers=None,
    ):
        request_headers = dict(headers or {})
        t0_ms = attach_webcast_ntp_t0(request_headers)
        if include_x_gorgon_marker and ENABLE_X_GORGON_MARKER:
            request_headers["x-gorgon"] = "1"

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
        version = self.getLiveStudioLatestVersion()
        browser_version = build_live_studio_browser_version(version)
        user_agent = f"Mozilla/{browser_version}"

        self.s.headers = {
            "user-agent": user_agent,
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "sec-fetch-storage-access": "active",
            "X-SS-DP": "",
            "sdk_aid": aid,
            "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

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
        if priority_region:
            request_headers["x-tt-store-region"] = priority_region

        streamInfo = self._request_json(
            "POST",
            base_url + "webcast/room/create/",
            params=params,
            data=body_encoded,
            headers=request_headers,
            include_x_gorgon_marker=True,
        )
        self.lastCreateStreamResponse = streamInfo

        try:
            self.streamUrl = streamInfo["data"]["stream_url"]["rtmp_push_url"]
            split_index = self.streamUrl.rfind("/")
            self.baseStreamUrl = self.streamUrl[:split_index]
            self.streamKey = self.streamUrl[split_index + 1 :]
            multi_stream_url = streamInfo["data"].get("multi_stream_url") or {}
            self.multiStreamUrl = multi_stream_url.get("rtmp_push_url", "")
            if self.multiStreamUrl:
                split_index = self.multiStreamUrl.rfind("/")
                self.multiBaseStreamUrl = self.multiStreamUrl[:split_index]
                self.multiStreamKey = self.multiStreamUrl[split_index + 1 :]
            else:
                self.multiBaseStreamUrl = ""
                self.multiStreamKey = ""
            self.multiStreamScene = streamInfo["data"].get("multi_stream_scene")
            self.multiStreamId = streamInfo["data"].get("multi_stream_id_str") or str(
                streamInfo["data"].get("multi_stream_id", "")
            )
            self.roomId = streamInfo["data"].get("id_str") or str(streamInfo["data"].get("id", ""))
            self.streamId = streamInfo["data"].get("stream_id_str") or str(streamInfo["data"].get("stream_id", ""))
            self.streamShareUrl = streamInfo["data"]["share_url"]
            return True
        except KeyError as exc:
            prompt = streamInfo.get("data", {}).get("prompts") or streamInfo.get("prompts")
            if not prompt:
                prompt = "Failed to create stream: " + json.dumps(streamInfo, ensure_ascii=False)[:1000]
            raise RuntimeError(prompt) from exc

    def endStream(self, device_id="", install_id="", priority_region="", room_id="", stream_id=""):
        base_url = self.getServerUrl()
        room_id = str(room_id or self.roomId or "").strip()
        stream_id = str(stream_id or self.streamId or "").strip()
        if not room_id or not stream_id:
            raise RuntimeError("Missing room_id or stream_id. Create a stream before ending it.")

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

        data = {
            "status": "4",
            "room_id": room_id,
            "stream_id": stream_id,
        }
        body_encoded = _encode_form_body(data)
        x_ss_stub = _make_x_ss_stub(body_encoded)
        streamInfo = None
        for _ in range(2):
            request_headers = {
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-ss-stub": x_ss_stub,
                **_build_signature_headers(
                    get_synced_unix_seconds(),
                    params["aid"],
                    params=params,
                    x_ss_stub=x_ss_stub,
                ),
            }
            if priority_region:
                request_headers["x-tt-store-region"] = priority_region

            streamInfo = self._request_json(
                "POST",
                base_url + "webcast/room/ping/anchor/",
                params=params,
                data=body_encoded,
                headers=request_headers,
                include_x_gorgon_marker=True,
            )

        if "data" in streamInfo and "prompts" in streamInfo["data"]:
            raise RuntimeError(streamInfo["data"]["prompts"])

        return True

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
        if priority_region:
            request_headers["x-tt-store-region"] = priority_region

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

    def save_cookies(self, path="cookies.json"):
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

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Stream Key Generator")

        self.games = fetch_game_tags()
        self.device_id = ""
        self.install_id = ""
        self.current_room_id = ""
        self.current_stream_id = ""
        self.is_live = False
        self.suppress_donation_reminder = False

        self._build_ui()
        self.update_checked.connect(self.handle_update_check)
        self.account_info_loaded.connect(self.apply_account_info)
        self.account_info_failed.connect(self.handle_account_info_error)
        self.check_cookies()
        self.load_config()
        self.ensure_device_identifiers(show_popup=True)
        if os.path.exists("cookies.json"):
            QTimer.singleShot(900, lambda: self.refresh_account_info(show_errors=False))
        QTimer.singleShot(3000, self.show_donation_reminder)
        QTimer.singleShot(6000, self.check_updates_on_startup)


    def _build_ui(self):
        root_layout = QGridLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(10, 8, 10, 8)

        input_group = QGroupBox("Input")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(5)

        # Title
        title_label = QLabel("Title:")
        title_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(title_label)

        self.title_edit = QLineEdit()
        self.title_edit.setFixedHeight(28)
        input_layout.addWidget(self.title_edit)

        # Topic
        topic_label = QLabel("Topic:")
        topic_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(topic_label)

        self.topic_combo = QComboBox()
        self.topic_combo.addItems([""] + list(TOPICS.values()))
        self.topic_combo.currentTextChanged.connect(self.on_topic_changed)
        self.topic_combo.setFixedHeight(28)
        input_layout.addWidget(self.topic_combo)

        # Game
        self.game_label = QLabel("Game:")
        self.game_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(self.game_label)

        self.game_combo = QComboBox()
        self.game_combo.setEditable(True)
        self.game_combo.addItems([""] + list(self.games.values()))
        self.game_combo.setFixedHeight(28)

        game_completer = QCompleter(list(self.games.values()), self)
        game_completer.setCaseSensitivity(Qt.CaseInsensitive)
        game_completer.setFilterMode(Qt.MatchContains)
        self.game_combo.setCompleter(game_completer)

        input_layout.addWidget(self.game_combo)

        # Region
        region_label = QLabel("Region:")
        region_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(region_label)

        self.region_combo = QComboBox()
        self.region_combo.setEditable(True)
        self.region_combo.addItems(REGIONS)
        self.region_combo.setFixedHeight(28)
        input_layout.addWidget(self.region_combo)

        # Options
        options_label = QLabel("Options:")
        options_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(options_label)

        options_row = QHBoxLayout()
        options_row.setSpacing(12)
        self.replay_checkbox = QCheckBox("Generate Replay")
        self.replay_checkbox.setChecked(True)
        options_row.addWidget(self.replay_checkbox)

        self.close_room_checkbox = QCheckBox("Close Room When Close Stream")
        options_row.addWidget(self.close_room_checkbox)

        self.age_restricted_checkbox = QCheckBox("Age Restricted")
        options_row.addWidget(self.age_restricted_checkbox)
        options_row.addStretch()
        input_layout.addLayout(options_row)

        # Thumbnail
        thumbnail_label = QLabel("Selected Thumbnail:")
        thumbnail_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(thumbnail_label)

        thumbnail_row = QHBoxLayout()
        thumbnail_row.setSpacing(5)

        self.thumbnail_edit = QLineEdit()
        self.thumbnail_edit.setReadOnly(True)
        self.thumbnail_edit.setFixedHeight(28)
        thumbnail_row.addWidget(self.thumbnail_edit)

        browse_button = QPushButton("Browse")
        browse_button.setFixedHeight(28)
        browse_button.clicked.connect(self.browse_image)
        thumbnail_row.addWidget(browse_button)

        input_layout.addLayout(thumbnail_row)

        root_layout.addWidget(input_group, 0, 0)

        account_group = QGroupBox("Account")
        account_layout = QGridLayout(account_group)
        account_layout.setHorizontalSpacing(8)
        account_layout.setVerticalSpacing(5)

        def add_account_field(row, column, label_text, widget):
            label = QLabel(label_text)
            label.setMinimumWidth(70)
            account_layout.addWidget(label, row, column)
            account_layout.addWidget(widget, row, column + 1)

        self.cookies_status_label = QLabel("Checking cookies...")
        account_layout.addWidget(QLabel("Cookies:"), 0, 0)
        account_layout.addWidget(self.cookies_status_label, 0, 1, 1, 3)

        self.account_username = QLineEdit()
        self.account_username.setReadOnly(True)
        self.account_username.setFixedHeight(28)
        add_account_field(1, 0, "Username", self.account_username)

        self.can_go_live_output = QLineEdit()
        self.can_go_live_output.setReadOnly(True)
        self.can_go_live_output.setFixedHeight(28)
        add_account_field(1, 2, "Can Go Live", self.can_go_live_output)

        self.account_user_id = QLineEdit()
        self.account_user_id.setReadOnly(True)
        self.account_user_id.setFixedHeight(28)
        add_account_field(2, 0, "User ID", self.account_user_id)

        self.account_status = QLineEdit()
        self.account_status.setReadOnly(True)
        self.account_status.setFixedHeight(28)
        add_account_field(2, 2, "Status", self.account_status)

        self.device_id_display = QLineEdit()
        self.device_id_display.setReadOnly(True)
        self.device_id_display.setFixedHeight(28)
        add_account_field(3, 0, "Device ID", self.device_id_display)

        self.install_id_display = QLineEdit()
        self.install_id_display.setReadOnly(True)
        self.install_id_display.setFixedHeight(28)
        add_account_field(4, 0, "Install ID", self.install_id_display)

        self.refresh_account_button = QPushButton("Refresh Account Info")
        self.refresh_account_button.clicked.connect(lambda: self.refresh_account_info())
        self.refresh_account_button.setFixedHeight(30)
        account_layout.addWidget(self.refresh_account_button, 3, 2, 2, 2)

        account_layout.setColumnStretch(1, 1)
        account_layout.setColumnStretch(3, 1)
        root_layout.addWidget(account_group, 1, 0)

        output_group = QGroupBox("Outputs")
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(5)

        # Buttons row
        button_row = QHBoxLayout()
        button_row.setSpacing(5)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.start_login)
        self.login_button.setFixedHeight(32)
        button_row.addWidget(self.login_button)

        self.go_live_button = QPushButton("Go Live")
        self.go_live_button.clicked.connect(self.generate_stream)
        self.go_live_button.setFixedHeight(32)
        button_row.addWidget(self.go_live_button)

        self.end_live_button = QPushButton("End Live")
        self.end_live_button.setEnabled(False)
        self.end_live_button.clicked.connect(self.end_stream)
        self.end_live_button.setFixedHeight(32)
        button_row.addWidget(self.end_live_button)

        output_layout.addLayout(button_row)

        self.url_output = QLineEdit()
        self.url_output.setReadOnly(True)
        self.url_output.setFixedHeight(28)

        self.key_output = QLineEdit()
        self.key_output.setReadOnly(True)
        self.key_output.setFixedHeight(28)

        self.share_url_output = QLineEdit()
        self.share_url_output.setReadOnly(True)
        self.share_url_output.setFixedHeight(28)

        def add_output_row(label_text, output_widget, copy_label):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            output_layout.addWidget(label)
            row = QHBoxLayout()
            row.setSpacing(5)
            row.addWidget(output_widget)
            copy_button = QPushButton(copy_label)
            copy_button.setFixedHeight(28)
            copy_button.clicked.connect(lambda: self.copy_to_clipboard(output_widget.text()))
            row.addWidget(copy_button)
            output_layout.addLayout(row)

        add_output_row("Stream URL:", self.url_output, "Copy")
        add_output_row("Stream Key:", self.key_output, "Copy")
        add_output_row("Share URL:", self.share_url_output, "Copy")

        output_layout.addStretch()

        # Bottom buttons
        bottom_buttons = QHBoxLayout()
        bottom_buttons.setSpacing(5)

        self.save_config_button = QPushButton("Save Config")
        self.save_config_button.clicked.connect(lambda: self.save_config())
        self.save_config_button.setFixedHeight(32)
        bottom_buttons.addWidget(self.save_config_button)

        self.donate_button = QPushButton("Donate")
        self.donate_button.setToolTip("Support development")
        self.donate_button.clicked.connect(self.open_donation_url)
        self.donate_button.setFixedHeight(32)
        bottom_buttons.addWidget(self.donate_button)

        output_layout.addLayout(bottom_buttons)

        root_layout.addWidget(output_group, 0, 1, 2, 1)

        root_layout.setColumnStretch(0, 1)
        root_layout.setColumnStretch(1, 1)

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

    def copy_to_clipboard(self, content):
        QGuiApplication.clipboard().setText(content)
        self.show_info("Content copied to clipboard.")

    def clear_output_fields(self):
        self.url_output.clear()
        self.key_output.clear()
        self.share_url_output.clear()

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

    def check_cookies(self):
        has_cookies = os.path.exists("cookies.json")
        if has_cookies:
            self.cookies_status_label.setText("Cookies are loaded")
        else:
            self.cookies_status_label.setText("No cookies found")

        self.login_button.setEnabled(True)
        self.go_live_button.setEnabled(has_cookies and not self.is_live)
        self.end_live_button.setEnabled(self.is_live)

    def refresh_account_info(self, show_errors=True):
        if not os.path.exists("cookies.json"):
            if show_errors:
                self.show_error("cookies.json not found. Please login first.")
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
        self.can_go_live_output.setText(str(info.get("can_go_live", False)))

        self.go_live_button.setEnabled(bool(info.get("can_go_live", False)) and os.path.exists("cookies.json") and not self.is_live)

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
            self.refresh_device_identifier_fields()
            return

        loaded_device_id = data.get("device_id", "")
        loaded_install_id = data.get("install_id", data.get("iid", ""))
        self.device_id = str(loaded_device_id).strip() if loaded_device_id is not None else ""
        self.install_id = str(loaded_install_id).strip() if loaded_install_id is not None else ""
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
            client.save_cookies()
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

        stream_created = False
        self.go_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)

        try:
            with Stream() as stream:
                created = stream.createStream(
                    self.title_edit.text(),
                    topic_id,
                    game_id,
                    self.replay_checkbox.isChecked(),
                    self.close_room_checkbox.isChecked(),
                    self.age_restricted_checkbox.isChecked(),
                    self.region_combo.currentText(),
                    self.thumbnail_edit.text(),
                    self.device_id,
                    self.install_id,
                )

                if created:
                    stream_created = True
                    self.is_live = True
                    self.show_info("Stream created successfully.")
                    self.clear_output_fields()
                    self.url_output.setText(stream.baseStreamUrl)
                    self.key_output.setText(stream.streamKey)
                    self.share_url_output.setText(stream.streamShareUrl)
                    self.current_room_id = stream.roomId
                    self.current_stream_id = stream.streamId
                    self.go_live_button.setEnabled(False)
                    self.end_live_button.setEnabled(True)
        except FileNotFoundError:
            self.show_error("cookies.json not found. Please login first.")
        except RuntimeError as exc:
            self.show_error(str(exc))
        except Exception as exc:
            self.show_error(f"Failed to create stream: {exc}")
        finally:
            if not stream_created:
                self.is_live = False
                self.go_live_button.setEnabled(os.path.exists("cookies.json"))
                self.end_live_button.setEnabled(False)

    def end_stream(self):
        if not self.is_live:
            self.show_error("No active stream to end.")
            return

        stream_ended = False
        self.end_live_button.setEnabled(False)

        try:
            with Stream() as stream:
                if stream.endStream(
                    device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.region_combo.currentText(),
                    room_id=self.current_room_id,
                    stream_id=self.current_stream_id,
                ):
                    stream_ended = True
                    self.is_live = False
                    self.current_room_id = ""
                    self.current_stream_id = ""
                    self.show_info("Stream ended successfully.")
                    self.clear_output_fields()
                    self.go_live_button.setEnabled(os.path.exists("cookies.json"))
                    self.end_live_button.setEnabled(False)
        except FileNotFoundError:
            self.show_error("cookies.json not found. Please login first.")
        except RuntimeError as exc:
            self.show_error(str(exc))
        except Exception as exc:
            self.show_error(f"Failed to end stream: {exc}")
        finally:
            if not stream_ended:
                self.end_live_button.setEnabled(self.is_live)


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
