import sys

# Enable native crash traces before importing Qt or any other extension during
# the offline packaged-runtime check. Normal launches never create this file.
_release_smoke_log = None
if '--smoke-test' in sys.argv:
    import faulthandler
    import os
    if os.environ.get('TIKTOK_SMOKE_REPORT'):
        _release_smoke_log = open(os.environ['TIKTOK_SMOKE_REPORT'], 'w', encoding='utf-8')
        faulthandler.enable(file=_release_smoke_log, all_threads=True)
        print('Starting packaged module imports', file=_release_smoke_log, flush=True)

import truststore
import hashlib
import copy
from collections import OrderedDict
from datetime import datetime
import json
import os
import sys
import time
import webbrowser
import socket
import threading
import tempfile
import urllib.parse
import base64
import mimetypes
import secrets
import shutil
import subprocess
from urllib.parse import urlencode

import requests
try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import exceptions as curl_exceptions
except Exception:
    curl_requests = None
    curl_exceptions = None
from packaging import version
from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QPixmap
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
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QHeaderView,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

if sys.platform == "win32":
    import winreg

truststore.inject_into_ssl()

from Libs.fluent_ui import (
    CheckBox as QCheckBox, ComboBox as QComboBox, EditableComboBox, LineEdit as QLineEdit,
    PlainTextEdit as QPlainTextEdit,
    PushButton as QPushButton, TableWidget as QTableWidget, PrimaryPushButton, ScrollArea,
    TitleLabel, CaptionLabel, FluentIcon, ToolButton, Action, CheckableMenu, DropDownPushButton,
    Pivot, RoundMenu, LiveStatusBadge, AccentWindow, AccentDialog as QDialog, AccentMessageBox as QMessageBox,
    configure_fluent_theme, install_font_diagnostics, section, style_controls,
)
from Libs.gui_tasks import BackgroundTask, Work, foreground, reap_processes, single_shot, wait_for_login_callback
from Libs.region_context import country_code, session_key, cached_context, remember_context
from Libs.device_profiles import has_registered_ids, prepare_device_profiles

from Libs.domain_routing import (
    attach_webcast_ntp_t0,
    build_common_headers,
    build_endpoint,
    get_synced_unix_seconds,
    resolve_api_host_candidates,
    resolve_webcast_base_url,
    resolve_webcast_host_candidates,
    update_ntp_from_response,
)
from Libs.device_gen import (
    build_live_studio_browser_version,
    fetch_live_studio_latest_version,
    register_desktop_device_identifiers,
    register_mobile_device_identifiers,
)
from Libs.signing_backend import signature_headers, is_development
from Libs.client_profiles import ClientImplementation, device_records, mobile_record_defaults, normalize_device_type
from Libs.mobile_requests import create_room_form, MOBILE_BROADCAST_MODES, MOBILE_ORIENTATIONS
from Libs.mobile_dual_layout import dual_layout_info, dual_create_params, distinct_push_urls, secondary_stream_id
from Libs.campaigns import CampaignFormatError, center_params, normalize_campaigns, visit_request
from Libs.campaign_ui import CampaignsDialog
from Libs.live_chat import GiftMessage, LiveChatClient
from Libs.error_reporting import OperationError, hosted_signer_failure, read_proxy_error
from Libs.rapidapi_quota import (
    quota_reset_at,
    quota_updated_at,
    read_quota,
)
from Updater import VersionChecker


CURL_CFFI_IMPERSONATE = "chrome"


def _new_http_session():
    if curl_requests is not None:
        return curl_requests.Session(impersonate=CURL_CFFI_IMPERSONATE)
    return requests.Session()


def _http_get(url, **kwargs):
    if curl_requests is not None:
        return curl_requests.get(url, impersonate=CURL_CFFI_IMPERSONATE, **kwargs)
    return requests.get(url, **kwargs)


def _is_http_timeout(exc):
    timeout_types = [requests.Timeout]
    if curl_exceptions is not None:
        timeout_types.append(curl_exceptions.Timeout)
    return isinstance(exc, tuple(timeout_types))


def _is_http_connection_error(exc):
    connection_types = [requests.ConnectionError, requests.Timeout]
    if curl_exceptions is not None:
        connection_types.extend([curl_exceptions.ConnectionError, curl_exceptions.Timeout])
    return isinstance(exc, tuple(connection_types))


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
PASSPORT_APP_KEY = "884c28a44b61b78f9d837fc8b0967178"

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
ACCOUNT_INFO_TIMEOUT_MS = 60000
LOCAL_PROXY_DEFAULT_PORT = 19350
LOCAL_PROXY_APP_NAME = "live"
LOCAL_PROXY_STREAM_KEY = "obs"
LOCAL_PROXY_LISTEN_TIMEOUT_SECONDS = 120
LOCAL_PROXY_LOG_NAME = "ffmpeg_proxy.log"
# Dual layout: second signed listener for the portrait (vertical) canvas.
LOCAL_PROXY_PORTRAIT_DEFAULT_PORT = 19351
LOCAL_PROXY_PORTRAIT_APP_NAME = "live"
LOCAL_PROXY_PORTRAIT_STREAM_KEY = "portrait"
LOCAL_PROXY_PORTRAIT_LOG_NAME = "ffmpeg_proxy_portrait.log"
ENABLE_STUDIO_STATS_POLLING = True
ENABLE_ONLINE_AUDIENCE_POLLING = True
ENABLE_SAFETY_DETAIL_POLLING = True
# Polling while unfocused: every webcast call costs one RapidAPI /signatures
# request (~2,660/hour focused while live, which trips the provider-side
# hourly rate limit and burns the daily quota). When the window is not the
# active one, display-only pollers stop; the violation monitor keeps
# running, slower. The anchor heartbeat always runs: pausing it mid-stream
# risks TikTok tearing the room down server-side.
UNFOCUSED_VIOLATION_POLL_SECONDS = 60


def _is_frozen_build():
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def _application_dir():
    if _is_frozen_build():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _application_icon():
    # Bundled assets follow __file__, including onefile extraction directories;
    # they are separate from the writable config directory beside the executable.
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
    icon = QIcon(os.path.join(assets, 'app-icon.ico'))
    icon.addFile(os.path.join(assets, 'app-icon.png'))
    return icon


def _is_macos_app_bundle():
    # Nuitka --macos-create-app-bundle puts the executable inside
    # <App>.app/Contents/MacOS. That is not a place for user data: the
    # bundle is replaced on every app update and can be read-only (App
    # Translocation, /Applications installs owned by another admin).
    return sys.platform == "darwin" and _is_frozen_build()


def _user_data_dir():
    # Config, the default cookies file, and logs live next to the
    # executable on Windows/Linux (portable style). macOS .app bundles use
    # the standard per-user Application Support folder instead.
    if _is_macos_app_bundle():
        base = os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "TiktokStreamKeyGenerator",
        )
        try:
            os.makedirs(base, exist_ok=True)
            return base
        except OSError:
            pass
    return _application_dir()


DEFAULT_COOKIES_PATH = os.path.join(_user_data_dir(), "cookies.json")
CONFIG_PATH = os.path.join(_user_data_dir(), "config.json")
RAPIDAPI_SIGNER_DOCS_URL = "https://rapidapi.com/Loukious/api/tiktok-live-studio-api-signer1"


def _normalize_configured_path(path, default=DEFAULT_COOKIES_PATH):
    value = str(path or "").strip()
    if not value:
        value = default
    value = os.path.expanduser(value)
    if not os.path.isabs(value):
        # Resolve relative paths against the app's data directory, not the
        # process CWD — a Finder-launched macOS .app has CWD "/", where
        # neither reading nor writing makes sense.
        value = os.path.join(os.path.dirname(default), value)
    return os.path.abspath(value)


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


def _audit_webcast_request(method, url, params, headers, status_code):
    try:
        split = urllib.parse.urlsplit(url)
        request_headers = headers or {}
        khronos = str(request_headers.get("x-khronos", "") or "")
        ladon = str(request_headers.get("x-ladon", "") or "")
        argus = str(request_headers.get("x-argus", "") or "")
        stub = str(request_headers.get("x-ss-stub", "") or "")
        device_id = _param_value(params, "device_id")
        line = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"method={method} path={split.path} status={status_code} "
            f"khronos={khronos} ladon_len={len(ladon)} argus_len={len(argus)} "
            f"stub_len={len(stub)} device_id_set={bool(device_id)}\n"
        )
        path = os.path.join(_runtime_logs_dir(), "webcast_requests.log")
        with open(path, "a", encoding="utf-8", errors="replace") as file:
            file.write(line)
    except Exception:
        pass


def _audit_violation_list(violation_list_type, data, records, summaries):
    try:
        line = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"type={violation_list_type} server_active={data.get('active_count')} "
            f"server_history={data.get('history_count')} records={len(records)} "
            f"summaries={json.dumps(summaries[:3], ensure_ascii=False)}\n"
        )
        path = os.path.join(_runtime_logs_dir(), "violation_list.log")
        with open(path, "a", encoding="utf-8", errors="replace") as file:
            file.write(line)
    except Exception:
        pass


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
    # Android signs the final URL, cookies and body immediately before transport.
    if _param_value(params, 'device_platform') == 'android':
        return {}
    device_id = _param_value(params, "device_id")
    return signature_headers(
        timestamp,
        aid,
        params=params,
        x_ss_stub=x_ss_stub,
        device_id=device_id,
        local_id=LADON_LOCAL_ID,
    )


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
    def __init__(self, cookies_path=None, *, device_type=None, device_profile=None):
        config = _load_config_file()
        kind = normalize_device_type(device_type or config.get('device_type', 'pc'))
        record = device_profile if device_profile is not None else device_records(config).get(kind, {})
        if kind == 'mobile':
            record = mobile_record_defaults(record)
        self.client = ClientImplementation(kind, record)
        self.s = _new_http_session()
        self.s.headers.update(build_common_headers(self.s))
        if self.client.kind == 'mobile':
            self.s._tiktok_tnc_params = {key: value for key, value in self.client.mobile_params(
                device_id=self.client.record.get('device_id', ''),
                install_id=self.client.record.get('install_id', '')).items()
                if key in ('aid', 'device_id', 'iid', 'device_platform', 'version_code', 'version_name',
                           'ttnet_version', 'cronet_version')}
            self._apply_live_studio_headers()
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
        self._region_context_key = session_key(self.cookies_path, self.client.kind, self._cookie_value)
        self._account_region = ''
        self._region_lookup_attempted = False

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
            temporary = None
            try:
                # Other profile loads may read this file while it is updated.
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                        dir=os.path.dirname(path), prefix='.cookies-', suffix='.tmp', delete=False) as file:
                    temporary = file.name
                    json.dump(cookies, file, indent=2)
                os.replace(temporary, path)
            finally:
                if temporary is not None and os.path.exists(temporary):
                    os.remove(temporary)
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
        explicit = str(priority_region or '').strip()
        if explicit:
            region = country_code(explicit)
            if not region:
                raise ValueError('Region must be a two-letter country code, such as tw, or blank for Auto.')
            return region
        context = cached_context(self._region_context_key)
        if context:
            return context.priority_region
        # A captured Android priority is a fallback when discovery is unavailable;
        # the account/store country is not an environment priority for either client.
        if self.client.kind == 'mobile':
            return country_code(self.client.record.get('request_params', {}).get('priority_region'))
        # Studio's account/store country is not its environment priority region.
        # Bootstrap with an empty priority until region_check provides one.
        return ''

    def _store_region_headers(self):
        context = cached_context(self._region_context_key)
        region = (country_code(self._account_region)
                  or (context.store_region if context else '')
                  or country_code(self._cookie_value('store-country-code')))
        return {'x-tt-store-region': region} if region else {}

    def _refresh_region_context(self, *, device_id='', install_id='', account_region=''):
        self._region_lookup_attempted = True
        self._account_region = country_code(account_region) or self._account_region
        params = self._studio_params(device_id=device_id, install_id=install_id)
        payload = self._signed_get_json(
            self.getServerUrl() + 'webcast/game/basic/region_check/',
            params=params, timeout=12)
        _raise_for_webcast_error(payload, 'LIVE Studio region check')
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not country_code(data.get('priority_region')):
            raise ValueError('LIVE Studio region check did not return a valid priority_region.')
        return remember_context(self._region_context_key, data['priority_region'],
                                self._account_region or data.get('store_region')
                                or self._cookie_value('store-country-code'))

    def _ensure_region_context(self, priority_region='', *, device_id='', install_id='', refresh=False):
        if not refresh and (priority_region or self._region_lookup_attempted
                            or cached_context(self._region_context_key)):
            return
        # Region discovery is part of authenticated account/room setup. Avoid
        # extra discovery traffic when no login session has been loaded.
        if not any(self._cookie_value(name) for name in ('sessionid', 'sessionid_ss', 'sid_guard', 'sid_tt')):
            return
        try:
            self._refresh_region_context(device_id=device_id, install_id=install_id)
        except Exception:
            cancel = getattr(self, 'account_info_cancel', None)
            if cancel is not None and cancel.is_set():
                raise

    def _priority_region_candidates(self, priority_region=""):
        candidates = []
        for candidate in (priority_region, self._effective_priority_region(), ''):
            candidate = str(candidate or '').strip().lower()
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _apply_live_studio_headers(self):
        if self.client.kind == 'mobile':
            for key in list(self.s.headers):
                if key.lower().startswith(('sec-ch-', 'sec-fetch-')):
                    self.s.headers.pop(key, None)
            self.s.headers.update(self.client.mobile_headers())
            return self.client.record['app_version'], ''
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
        if self.client.kind == 'mobile':
            params = self.client.mobile_params(device_id=device_id, install_id=install_id,
                                               priority_region=self._effective_priority_region(priority_region))
            self.priority_region_used = params.get('priority_region', '')
            return params
        version = self.getLiveStudioLatestVersion()
        browser_version = build_live_studio_browser_version(version)
        priority_region = self._effective_priority_region(priority_region)
        self.priority_region_used = priority_region
        return {
            "aid": "8311",
            "app_name": "tiktok_live_studio",
            "device_id": str(device_id) if device_id else "0",
            "install_id": str(install_id) if install_id else "0",
            "channel": "studio",
            "version_code": version,
            "device_platform": "windows",
            "timezone_name": str(self.client.record.get('fingerprint', {}).get('timezone_name', 'Africa/Tunis')),
            "screen_width": str(self.client.record.get('fingerprint', {}).get('screen_width', '1920')),
            "screen_height": str(self.client.record.get('fingerprint', {}).get('screen_height', '1080')),
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

    def _webcast_candidate_urls(self, url, priority_region=""):
        split = urllib.parse.urlsplit(url)
        current_host = split.netloc
        if not current_host or "webcast" not in current_host:
            return [url]

        # Do not route Webcast by priority_region. Live Studio gets the real IDC
        # from TNC/domain dispatch and session cookies. For alisg accounts, forcing
        # priority_region=fr to no1a produces HTTP 403 on heartbeat/safety endpoints.
        hosts = []
        try:
            hosts.extend(resolve_webcast_host_candidates(self.s))
        except Exception:
            pass
        hosts.append(current_host)

        urls = []
        seen_hosts = set()
        for host in hosts:
            host = str(host or "").strip().lower()
            if not host or host in seen_hosts:
                continue
            seen_hosts.add(host)
            urls.append(
                urllib.parse.urlunsplit(
                    (
                        split.scheme or "https",
                        host,
                        split.path,
                        split.query,
                        split.fragment,
                    )
                )
            )
        return urls or [url]

    def _is_retryable_request_error(self, exc):
        if _is_http_connection_error(exc):
            return True
        if isinstance(exc, WebcastError):
            if exc.status_code in (403, 404, 421, 429, 500, 502, 503, 504):
                return True
            # Invalid/empty non-JSON responses usually come from the wrong IDC.
            return exc.status_code is None
        return False

    def _signed_get_json(self, url, *, params, priority_region="", extra_headers=None, timeout=None):
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
        headers.update(self._store_region_headers())
        headers.update(extra_headers or {})
        return self._request_json_with_webcast_fallback("GET", url, params=params, headers=headers, timeout=timeout)

    def _signed_post_json(self, url, *, params, payload, priority_region="", timeout=20, retry=True):
        self._apply_live_studio_headers()
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        x_ss_stub = _make_x_ss_stub(body)
        timestamp = get_synced_unix_seconds()
        headers = {
            "content-type": "application/json",
            "pragma": "no-cache",
            "cache-control": "no-cache",
            "x-ss-stub": x_ss_stub,
            **_build_signature_headers(
                timestamp,
                params.get("aid", "8311"),
                params=params,
                x_ss_stub=x_ss_stub,
            ),
        }
        headers.update(self._store_region_headers())
        request = self._request_json_with_webcast_fallback if retry else self._request_json
        return request(
            "POST",
            url,
            params=params,
            data=body,
            headers=headers,
            timeout=timeout,
            **({"allow_redirects": False} if not retry else {}),
        )

    def _cookie_account_info(self, priority_region=""):
        """Resolve the current cookie account, never a cached GUI account ID."""
        if self.client.kind == 'pc':
            params = _apply_passport_sdk_signature({
                'device_id': str(self.client.record.get('device_id') or '0'),
                'aid': self.client.aid, 'account_sdk_source': 'web',
                'sdk_version': PASSPORT_WEB_SDK_VERSION,
                'verifyFp': 'verify_' + str(self.client.record.get('device_id') or '0'),
            })
        else:
            params = self._studio_params(device_id=self.client.record.get('device_id', ''),
                                         install_id=self.client.record.get('install_id', ''),
                                         priority_region=priority_region)
        payload = self._signed_get_json(
            build_endpoint('api.tiktokv.com', 'passport/account/info/v2/', self.s),
            params=params, priority_region=priority_region, timeout=20)
        _raise_for_webcast_error(payload, 'Account info')
        data = payload.get('data') or {}
        if not isinstance(data, dict) or data.get('error_code') not in (None, 0, '0'):
            raise RuntimeError('Cannot identify the signed-in account. Check the selected cookies file.')
        user_id = str(data.get('user_id_str') or data.get('user_id') or '')
        if not user_id.isascii() or not user_id.isdigit() or int(user_id) == 0:
            raise RuntimeError('Cannot identify the signed-in account. Check the selected cookies file.')
        return data

    def _campaign_account_id(self, priority_region=""):
        data = self._cookie_account_info(priority_region)
        return str(data.get('user_id_str') or data['user_id'])

    def getCampaigns(self, *, priority_region=""):
        user_id = self._campaign_account_id(priority_region)
        params = self._studio_params(device_id=self.client.record.get('device_id', ''),
                                     install_id=self.client.record.get('install_id', ''),
                                     priority_region=priority_region)
        params.update(center_params(self.client.aid, user_id))
        prefix = 'ls/' if self.client.kind == 'pc' else ''
        base = self.getServerUrl()
        try:
            payload = self._signed_get_json(
                base + 'webcast/activity/resource_exposure/' + prefix + 'get_campaign_center_page_data/',
                params=params, priority_region=priority_region,
                extra_headers={'campaign-center-lang': 'en'}, timeout=20)
            _raise_for_webcast_error(payload, 'Campaign list')
            campaigns = normalize_campaigns(payload, now=get_synced_unix_seconds())
        except (CampaignFormatError, WebcastError) as exc:
            # Legacy Studio has a captured list endpoint. Authentication and
            # server errors must remain visible rather than look like no cards.
            if self.client.kind != 'pc' or (isinstance(exc, WebcastError) and exc.status_code != 404):
                raise
            legacy_params = {k: v for k, v in params.items() if k not in ('UserBase', 'EnterFromScene')}
            payload = self._signed_get_json(base + 'webcast/activity/resource_exposure/ls/pack_data/',
                                            params=legacy_params, priority_region=priority_region, timeout=20)
            _raise_for_webcast_error(payload, 'Campaign list')
            campaigns = normalize_campaigns(payload, now=get_synced_unix_seconds())
        return {'user_id': user_id, 'campaigns': campaigns}

    def reportCampaignView(self, activity_id, *, expected_user_id, priority_region=""):
        user_id = self._campaign_account_id(priority_region)
        if user_id != str(expected_user_id):
            raise RuntimeError('The cookies now belong to a different account. Refresh the campaign list first.')
        event_params, payload = visit_request(activity_id, user_id, get_synced_unix_seconds(), self.client.aid)
        params = self._studio_params(device_id=self.client.record.get('device_id', ''),
                                     install_id=self.client.record.get('install_id', ''),
                                     priority_region=priority_region)
        params.update(event_params)
        response = self._signed_post_json(self.getServerUrl() + 'webcast/activity/event/',
                                         params=params, payload=payload, priority_region=priority_region,
                                         timeout=20, retry=False)
        if not isinstance(response, dict) or 'status_code' not in response:
            raise RuntimeError('The view request returned an unrecognized response; receipt is unconfirmed.')
        _raise_for_webcast_error(response, 'Campaign view')
        if response['status_code'] not in (0, '0'):
            raise RuntimeError('TikTok did not confirm the campaign view event.')
        return response

    def _signed_post_form(self, url, *, params, data, priority_region="", timeout=20):
        self._apply_live_studio_headers()
        body = _encode_form_body(data)
        x_ss_stub = _make_x_ss_stub(body)
        timestamp = get_synced_unix_seconds()
        headers = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "pragma": "no-cache",
            "cache-control": "no-cache",
            "x-ss-stub": x_ss_stub,
            **_build_signature_headers(
                timestamp,
                params.get("aid", "8311"),
                params=params,
                x_ss_stub=x_ss_stub,
            ),
        }
        headers.update(self._store_region_headers())
        return self._request_json_with_webcast_fallback(
            "POST",
            url,
            params=params,
            data=body,
            headers=headers,
            timeout=timeout,
        )

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
        allow_redirects=None,
    ):
        cancel = getattr(self, 'account_info_cancel', None)
        if cancel is not None and cancel.is_set():
            raise TimeoutError('Account refresh was superseded.')
        request_headers = dict(headers or {})
        t0_ms = attach_webcast_ntp_t0(request_headers)

        mobile = self.client.kind == 'mobile'
        if mobile:
            common = self.client.mobile_params(device_id=self.client.record.get('device_id', ''),
                                               install_id=self.client.record.get('install_id', ''))
            params = {**common, **(params or {})}
            # Version metadata must remain tied to the selected Android app,
            # including callers carrying old PC/build-code query values.
            for key in ('version_name', 'version_code', 'manifest_version_code', 'update_version_code'):
                params[key] = common[key]
            params.update(aid=self.client.aid, device_id=self.client.record.get('device_id', ''),
                          iid=self.client.record.get('install_id', ''), device_platform='android')
            for key in ('install_id', 'live_studio', 'multi_stream_scene', 'multi_stream_source'):
                params.pop(key, None)
            if urllib.parse.urlsplit(url).path.endswith('/webcast/room/create/') and str(params.get('live_mode')) == '6':
                params = dual_create_params(params)
            self._apply_live_studio_headers()
            request_headers = dict(requests.structures.CaseInsensitiveDict(
                {**dict(self.s.headers), **request_headers}))
            # Strip any signatures/stubs from earlier requests before serializing.
            for key in list(request_headers):
                if key.lower() in ('x-argus', 'x-gorgon', 'x-khronos', 'x-ladon', 'x-ss-stub'):
                    request_headers.pop(key)
            prepared = requests.Request(method, url, params=params, data=data, files=files,
                                        headers=request_headers).prepare()
            jar = getattr(self.s.cookies, 'jar', self.s.cookies)
            cookie = requests.cookies.get_cookie_header(jar, prepared)
            if cookie and 'Cookie' not in prepared.headers:
                prepared.headers['Cookie'] = cookie
            exact_body = prepared.body
            if isinstance(exact_body, str):
                exact_body = exact_body.encode('utf-8')
            elif exact_body is not None and not isinstance(exact_body, bytes):
                raise TypeError('Mobile signing requires serialized request bytes')
            prepared.headers.update(self.client.signature_headers(
                get_synced_unix_seconds(), url=prepared.url,
                headers=dict(prepared.headers), body=exact_body))
            url, params, data, files = prepared.url, None, exact_body, None
            request_headers = dict(prepared.headers)

        deadline = getattr(self, 'account_info_deadline', None)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Account refresh timed out.')
            timeout = min(20 if timeout is None else timeout, remaining)

        response = self.s.request(
            **({'allow_redirects': False} if mobile else
               {'allow_redirects': allow_redirects} if allow_redirects is not None else {}),
            method=method,
            url=url,
            params=params,
            data=data,
            files=files,
            headers=request_headers,
            verify=verify,
            timeout=timeout,
        )
        if cancel is not None and cancel.is_set():
            raise TimeoutError('Account refresh was superseded.')
        update_ntp_from_response(t0_ms, response)
        _audit_webcast_request(method, url, params, request_headers, response.status_code)
        try:
            self.save_cookies()
        except Exception:
            pass

        if not (200 <= response.status_code < 300):
            text = (response.text or "").strip()
            if len(text) > 500:
                text = text[:500] + "..."
            raise WebcastError(
                f"HTTP {response.status_code} from {urllib.parse.urlsplit(url).netloc}: {text or response.reason}",
                status_code=response.status_code,
                payload=None,
                action=f"{method} {url}",
            )

        try:
            return response.json()
        except ValueError as exc:
            text = (response.text or "").strip()
            if len(text) > 500:
                text = text[:500] + "..."
            raise WebcastError(
                f"Invalid JSON from {urllib.parse.urlsplit(url).netloc}: {text or exc}",
                status_code=response.status_code,
                payload=None,
                action=f"{method} {url}",
            ) from exc

    def _request_json_with_webcast_fallback(self, method, url, **kwargs):
        candidate_urls = self._webcast_candidate_urls(
            url,
            priority_region=(kwargs.get("params") or {}).get("priority_region", ""),
        )
        last_error = None

        for index, candidate_url in enumerate(candidate_urls):
            try:
                return self._request_json(method, candidate_url, **kwargs)
            except Exception as exc:
                last_error = exc
                if index >= len(candidate_urls) - 1 or not self._is_retryable_request_error(exc):
                    raise
                continue

        if last_error:
            raise last_error
        raise RuntimeError(f"No candidate URL was available for {url}")

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
        mobile_dual = self.client.kind == 'mobile' and bool(multi_stream_scene)
        previous_room_id = self.roomId
        if mobile_dual and self.client.record.get('broadcast_type', 'video') != 'video':
            raise ValueError('Android Dual Layout requires Camera LIVE; screen capture uses a single canvas.')
        self._ensure_region_context(priority_region, device_id=device_id, install_id=install_id)
        base_url = self.getServerUrl()
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

        if self.client.kind == 'mobile':
            data = create_room_form(self.client.record, title=title, hashtag_id=hashtag_id,
                                    game_tag_id=game_tag_id, gen_replay=gen_replay,
                                    age_restricted=age_restricted, multi_stream_scene=multi_stream_scene,
                                    multi_stream_source=multi_stream_source)
            if mobile_dual and not self._get_dual_layout_info(params)['dual_layout_unlocked']:
                raise RuntimeError('Dual Layout is not unlocked for this account, or its eligibility check failed. No room was created.')
        if age_restricted:
            data["age_restricted"] = "4"

        if thumbnail_path:
            uri = self.uploadThumbnail(thumbnail_path, base_url, params)
            data["cover_uri"] = uri

        if mobile_dual:
            params = dual_create_params(params)

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
        request_headers.update(self._store_region_headers())

        streamInfo = self._request_json(
            "POST",
            base_url + "webcast/room/create/",
            params=params,
            data=body_encoded,
            headers=request_headers,
        )
        self.lastCreateStreamResponse = streamInfo
        if mobile_dual:
            _raise_for_webcast_error(streamInfo, 'Create Android dual stream')
            if not isinstance(streamInfo, dict) or str(streamInfo.get('status_code')) != '0':
                raise RuntimeError('Android dual creation returned no success status.')
            room = streamInfo.get('data')
            if not isinstance(room, dict):
                raise RuntimeError('Android dual creation returned no room.')
            ready = self._apply_room_info(room, require_stream_url=True)
            if not (ready and distinct_push_urls(self.streamUrl, self.multiStreamUrl) and secondary_stream_id(room)):
                message = 'TikTok did not allocate two distinct push URLs and a secondary stream ID for Android Dual Layout.'
                if self.roomId and self.streamId and self.roomId != previous_room_id:
                    try:
                        self.endStream(device_id=device_id, install_id=install_id,
                                       priority_region=priority_region,
                                       room_id=self.roomId, stream_id=self.streamId)
                    except Exception as exc:
                        raise RuntimeError(message + ' Cleanup failed; the new room may still be open.') from exc
                    message += ' The new room was ended before either proxy started.'
                raise RuntimeError(message)
            self.multiStreamId = secondary_stream_id(room)
            return True

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
        self._ensure_region_context(priority_region, device_id=device_id, install_id=install_id)
        base_url = self.getServerUrl()
        params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )
        if self.client.kind == 'mobile':
            record = self.client.record
            info = {'last_time_hashtag_id': int(last_time_hashtag_id or '5'),
                    'live_studio': 0, 'screen_shot': int(record.get('broadcast_type') == 'screen_record'),
                    'live_audio': 0, 'third_party': 0, 'is_teen': False,
                    'first_open_go_live_page': True, 'has_entered_try_mode': False}
            info.update(record.get('create_info_params', {}))
            info['live_studio'] = 0
            body = json.dumps(info, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
            self._apply_live_studio_headers()
            return self._request_json_with_webcast_fallback(
                'POST', base_url + 'webcast/room/create_info/', params=params, data=body,
                headers={'content-type': 'application/json; charset=UTF-8'})
        params.update(
            {
                "last_time_hashtag_id": str(last_time_hashtag_id or "5"),
                **({"live_studio": "1"} if self.client.kind == "pc" else {}),
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
            if self.client.kind == 'mobile':
                params.update(enable_http_dns='0', reconnect_guide_scene='0')
                params.update(self.client.record.get('continue_params', {}))
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
        self._ensure_region_context(priority_region, device_id=device_id, install_id=install_id)
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
            request_headers.update(self._store_region_headers())

            try:
                streamInfo = self._request_json_with_webcast_fallback(
                    "POST",
                    base_url + "webcast/room/ping/anchor/",
                    params=params,
                    data=body_encoded,
                    headers=request_headers,
                    timeout=PING_ANCHOR_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                if not _is_http_timeout(exc):
                    raise
                streamInfo = self._request_json_with_webcast_fallback(
                    "POST",
                    base_url + "webcast/room/ping/anchor/",
                    params=params,
                    data=body_encoded,
                    headers=request_headers,
                    timeout=PING_ANCHOR_TIMEOUT_SECONDS,
                )

            if _is_update_in_lock_payload(streamInfo):
                streamInfo = self._request_json_with_webcast_fallback(
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
        # This pre-finish endpoint is advisory. Some IDCs/accounts return a raw
        # 403 for it even when the finish ping works, so do not block End Live
        # on this call.
        try:
            self._signed_get_json(
                base_url + "webcast/room/anchor_pre_finish/",
                params={**params, "room_id": room_id},
                priority_region=priority_region,
            )
        except Exception:
            pass

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

    def getEcoViolationList(self, device_id="", install_id="", priority_region="", violation_list_type=1):
        # Captured Live Studio-compatible request uses aid=8311 for this endpoint.
        # violation_list_type=0 returns active violations; type=1 returns history.
        # The response may return records even when counters are 0, so keep both
        # server counters and actual record counts for display.
        violation_list_type = int(violation_list_type)
        params = {
            "aid": "8311",
            "violation_list_type": str(violation_list_type),
        }
        if device_id:
            params["device_id"] = str(device_id)
        if install_id:
            params["iid"] = str(install_id)
        if self.client.kind == 'mobile':
            params = {**self._studio_params(device_id=device_id, install_id=install_id,
                                            priority_region=priority_region),
                      'violation_list_type': str(violation_list_type)}
        url = self.getServerUrl() + "webcast/eco/violation_list/"
        payload = self._signed_get_json(
            url,
            params=params,
            priority_region=self._effective_priority_region(priority_region),
        )
        _raise_for_webcast_error(payload, "Eco violation list")

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}

        records = data.get("records") or []
        if not isinstance(records, list):
            records = []

        active_records = records if violation_list_type == 0 else []
        active_ids = [
            self._eco_violation_id(record)
            for record in active_records
            if self._eco_violation_id(record)
        ]
        recent_ids = [
            self._eco_violation_id(record)
            for record in records
            if isinstance(record, dict) and self._eco_violation_id(record)
        ]
        active_summaries = [self._format_eco_violation_record(record) for record in active_records]
        recent_summaries = [self._format_eco_violation_record(record) for record in records if isinstance(record, dict)]
        _audit_violation_list(violation_list_type, data, records, active_summaries if violation_list_type == 0 else recent_summaries)

        return {
            "violation_list_type": violation_list_type,
            "server_active_count": data.get("active_count"),
            "active_count": len(active_records),
            "server_history_count": data.get("history_count"),
            "history_count": data.get("history_count"),
            "record_count": len(records),
            "recent_count": len(records),
            "is_eea": data.get("is_eea"),
            "has_more": data.get("has_more"),
            "records": records,
            "recent_records": records,
            "active_records": active_records,
            "active_ids": active_ids,
            "recent_ids": recent_ids,
            "active_summaries": active_summaries,
            "recent_summaries": recent_summaries,
            "raw": payload,
        }

    def getViolationStatus(
        self,
        device_id="",
        install_id="",
        priority_region="",
        room_id="",
        last_time_hashtag_id="5",
        include_details=True,
    ):
        room_id = str(room_id or self.roomId or "").strip()
        errors = []
        create_data = {}
        # include_details=False (app unfocused) skips create_info/room_info;
        # the violation lists below are what the safety feature needs.
        if ENABLE_SAFETY_DETAIL_POLLING and include_details:
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
        if ENABLE_SAFETY_DETAIL_POLLING and include_details and room_id:
            try:
                room_info = self.getRoomInfo(
                    device_id=device_id,
                    install_id=install_id,
                    priority_region=priority_region,
                    room_id=room_id,
                )
            except Exception as exc:
                errors.append(f"room_info: {exc}")

        active_eco_violation_list = {
            "active_records": [],
            "active_ids": [],
            "active_summaries": [],
            "active_count": 0,
            "server_active_count": None,
            "server_history_count": None,
            "history_count": None,
            "record_count": 0,
            "recent_count": 0,
            "recent_records": [],
            "recent_summaries": [],
        }
        history_eco_violation_list = {
            "active_records": [],
            "active_ids": [],
            "active_summaries": [],
            "active_count": 0,
            "server_active_count": None,
            "server_history_count": None,
            "history_count": None,
            "record_count": 0,
            "recent_count": 0,
            "recent_records": [],
            "recent_summaries": [],
        }
        try:
            active_eco_violation_list = self.getEcoViolationList(
                device_id=device_id,
                install_id=install_id,
                priority_region=priority_region,
                violation_list_type=0,
            )
        except Exception as exc:
            errors.append(f"active_eco_violation_list: {exc}")
        try:
            history_eco_violation_list = self.getEcoViolationList(
                device_id=device_id,
                install_id=install_id,
                priority_region=priority_region,
                violation_list_type=1,
            )
        except Exception as exc:
            errors.append(f"history_eco_violation_list: {exc}")

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

        active_eco_records = active_eco_violation_list.get("active_records") or []
        active_eco_summaries = active_eco_violation_list.get("active_summaries") or []
        history_eco_records = history_eco_violation_list.get("recent_records") or history_eco_violation_list.get("records") or []
        active_violation_ids = set(active_eco_violation_list.get("active_ids") or [])

        if active_eco_records:
            status = "Active violation"
        elif ban_active or blocked or locale_restricted:
            status = "Restricted"
        elif community_flagged or community_review or violations_entrance:
            status = "Warning"
        else:
            status = "OK"

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
            "eco_violation_list": history_eco_violation_list,
            "active_eco_violation_list": active_eco_violation_list,
            "history_eco_violation_list": history_eco_violation_list,
            "active_violation_records": active_eco_records,
            "history_violation_records": history_eco_records,
            "active_violation_count": len(active_eco_records),
            "active_violation_ids": sorted(active_violation_ids),
            "active_violation_summaries": active_eco_summaries,
            "history_violation_count": (
                history_eco_violation_list.get("history_count")
                if history_eco_violation_list.get("history_count") not in (None, "")
                else active_eco_violation_list.get("history_count")
            ),
            "recent_violation_count": history_eco_violation_list.get("record_count", 0),
            "recent_violation_summaries": history_eco_violation_list.get("recent_summaries", []),
            "errors": errors,
            "raw": {
                "create_info": create_data,
                "room_info": room_info,
                "active_eco_violation_list": active_eco_violation_list,
                "history_eco_violation_list": history_eco_violation_list,
            },
        }

    def getServerUrl(self):
        return resolve_webcast_base_url(self.s)

    def getAccountInfo(self, device_id="", install_id="", priority_region="", last_time_hashtag_id="5"):
        if self.client.kind == 'mobile':
            return self._get_mobile_account_info(device_id, install_id, priority_region, last_time_hashtag_id)
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
        account_params = _apply_passport_sdk_signature(
            {
                "device_id": str(device_id) if device_id else "0",
                "aid": "8311",
                "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
                "verifyFp": verify_fp,
            }
        )
        account_payload = self._signed_get_json(
            build_endpoint("api.tiktokv.com", "passport/account/info/v2/", self.s),
            params=account_params,
            priority_region=priority_region,
        )
        account_data = account_payload.get("data", {}) if isinstance(account_payload, dict) else {}
        self._account_region = country_code(account_data.get('region'))
        self._ensure_region_context(device_id=device_id, install_id=install_id, refresh=True)
        common_params = self._studio_params(
            device_id=device_id,
            install_id=install_id,
            priority_region=priority_region,
        )

        create_params = dict(common_params)
        create_params.update(
            {
                "last_time_hashtag_id": str(last_time_hashtag_id or "5"),
                **({"live_studio": "1"} if self.client.kind == "pc" else {}),
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

        # Scene=1 is what TikTok LIVE Studio queries to decide whether the
        # dual layout button is shown at all; verified against Charles
        # captures: accounts with dual access return allow_multi_stream=true
        # here, accounts without return false.
        dual_params = dict(common_params)
        dual_params["scene"] = "1"
        dual_create_info = self._signed_get_json(
            base_url + "webcast/game/basic/create_info/",
            params=dual_params,
            priority_region=priority_region,
        )

        create_data = create_info.get("data", {}) if isinstance(create_info, dict) else {}
        game_data = game_create_info.get("data", {}) if isinstance(game_create_info, dict) else {}
        dual_data = dual_create_info.get("data", {}) if isinstance(dual_create_info, dict) else {}

        # New-user sensitive-feature restriction: dual layout stays locked
        # until the account has gone LIVE enough 25-minute sessions.
        # /webcast/anchor_tool/threshold/check/ -> {allowed, dual_canvas_used,
        # days_to_reach}. Trailing slash avoids a 301 redirect.
        threshold = {}
        try:
            threshold_payload = self._signed_get_json(
                base_url + "webcast/anchor_tool/threshold/check/",
                params=dict(common_params),
                priority_region=priority_region,
            )
            if isinstance(threshold_payload, dict):
                threshold = threshold_payload.get("data") or {}
        except Exception:
            threshold = {}

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
            # Dual layout account-level gate (scene=1), the same signal
            # LIVE Studio uses to show/hide the dual layout button.
            "allow_multi_stream_scene1": dual_data.get("allow_multi_stream"),
            # Sensitive-feature restriction state, mirroring LIVE Studio's
            # logic: the restriction applies only when
            #   dualEnable = !allowed && !dual_canvas_used
            # so an account is unlocked when allowed OR dual_canvas_used
            # (verified live: a never-used dual-layout account returns
            # allowed=true, days_to_reach=0, dual_canvas_used=false and the
            # button is fully enabled in LIVE Studio).
            "dual_threshold": threshold,
            "dual_layout_unlocked": bool(
                dual_data.get("allow_multi_stream")
                and (threshold.get("allowed") or threshold.get("dual_canvas_used"))
            ),
            "dual_days_to_reach": threshold.get("days_to_reach"),
        }

    def _get_dual_layout_info(self, params):
        base_url = self.getServerUrl()
        scene = self._signed_get_json(base_url + 'webcast/game/basic/create_info/',
                                      params={**params, 'scene': '1'}, timeout=20)
        threshold = None
        try:
            threshold = self._signed_get_json(base_url + 'webcast/anchor_tool/threshold/check/',
                                              params=dict(params), timeout=20)
        except Exception:
            pass
        return dual_layout_info(scene, threshold)

    def _get_mobile_account_info(self, device_id, install_id, priority_region, hashtag_id):
        # LIVE create-info describes eligibility and usually has no profile.
        # Passport resolves the identity authenticated by the selected cookies.
        user = self._cookie_account_info(priority_region)
        self._account_region = country_code(user.get('region'))
        self._ensure_region_context(device_id=device_id, install_id=install_id, refresh=True)
        payload = self.getCreateRoomInfo(device_id, install_id, priority_region, hashtag_id)
        _raise_for_webcast_error(payload, 'Mobile create info')
        data = payload.get('data') or {}
        banned = bool((data.get('ban_status') or {}).get('is_ban') or
                      (data.get('advanced_live_ban_status') or {}).get('is_ban'))
        allowed = not (banned or data.get('golive_locale_restricted') or data.get('block_status') not in (0, '0', None, ''))
        if 'can_go_live' in data:
            allowed = allowed and data['can_go_live'] in (True, 1, '1', 'true')
        try:
            dual = self._get_dual_layout_info(self._studio_params(
                device_id=device_id, install_id=install_id, priority_region=priority_region))
        except Exception:
            dual = dual_layout_info(None, None)
        return {'account': user, 'create_info': data, 'can_go_live': allowed,
                'status': 'Ready' if allowed else 'Restricted', 'device_type': 'mobile',
                'allow_multi_stream': dual.get('allow_multi_stream_scene1'), **dual}

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
        request_headers.update(self._store_region_headers())

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


def _passport_xor5_qs(keys):
    raw = ",".join(keys).encode("utf-8")
    return "".join(f"{byte ^ 5:02x}" for byte in raw)


def _passport_stringify_value(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _passport_sorted_string(values, limit=-1):
    """
    Python port of the Account SDK signing helper from the bundled JS.

    The SDK sorts request keys, keeps the first 10 param keys, builds
    key=value pairs without URL encoding, then signs:

        param_string + "&" + body_string + "&app_key=" + appKey

    In Live Studio's wrappers, navigation-only fields such as next/baseURL
    are passed to SDK methods but are not part of the signed Passport params.
    """
    if not isinstance(values, dict):
        return "", []

    ignored = {"sign", "qs", "isResend", "next", "baseURL", "extra_params"}
    keys = sorted(
        str(key)
        for key, value in values.items()
        if value is not None and str(key) not in ignored
    )
    if limit >= 0:
        keys = keys[:limit]

    parts = []
    for key in keys:
        parts.append(f"{key}={_passport_stringify_value(values.get(key))}")
    return "&".join(parts), keys


def _passport_sdk_signature(params, data=None, app_key=PASSPORT_APP_KEY):
    if not app_key:
        return {}

    param_string, signed_keys = _passport_sorted_string(params or {}, limit=10)
    body_string, _ = _passport_sorted_string(data or {}, limit=-1)
    base = f"{param_string}&{body_string}&app_key={app_key}"
    return {
        "sign": hashlib.md5(base.encode("utf-8")).hexdigest(),
        "qs": _passport_xor5_qs(signed_keys),
    }


def _apply_passport_sdk_signature(params, data=None):
    signed = dict(params or {})
    signed.pop("sign", None)
    signed.pop("qs", None)
    signed.update(_passport_sdk_signature(signed, data=data))
    return signed


def _random_qr_client_secret(length=8):
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _inject_qr_client_secret(qrcode_index_url, client_secret):
    if not qrcode_index_url or not client_secret:
        return qrcode_index_url

    decoded = urllib.parse.unquote(str(qrcode_index_url))
    base, separator, query = decoded.partition("?")
    if not separator:
        return qrcode_index_url

    values = urllib.parse.parse_qs(query, keep_blank_values=True)
    next_url = (values.get("next_url") or [""])[0]
    if not next_url:
        return qrcode_index_url

    joiner = "&" if "?" in next_url else "?"
    values["next_url"] = [f"{next_url}{joiner}client_secret={urllib.parse.quote(client_secret)}"]
    return base + "?" + urllib.parse.urlencode(values, doseq=True)


def _qrcode_png_base64(value):
    if not value:
        return ""
    try:
        import io
        import qrcode

        image = qrcode.make(value)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return ""


def _dedupe_hosts(hosts):
    seen = set()
    out = []
    for host in hosts:
        host = str(host or "").strip()
        if host and host not in seen:
            seen.add(host)
            out.append(host)
    return out


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
    iterable = getattr(cookie_jar, "jar", cookie_jar)

    for cookie in iterable:
        if isinstance(cookie, str):
            value = cookie_jar.get(cookie) if hasattr(cookie_jar, "get") else ""
            if value is None:
                continue
            cookies.append(
                {
                    "name": cookie,
                    "value": value,
                    "domain": "",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": False,
                    "secure": False,
                }
            )
            continue

        rest = getattr(cookie, "_rest", None) or {}
        http_only = bool(rest.get("HttpOnly") or rest.get("httponly"))
        entry = {
            "name": getattr(cookie, "name", ""),
            "value": getattr(cookie, "value", ""),
            "domain": getattr(cookie, "domain", "") or "",
            "path": getattr(cookie, "path", "") or "/",
            "expires": getattr(cookie, "expires", None) if getattr(cookie, "expires", None) is not None else -1,
            "httpOnly": http_only,
            "secure": bool(getattr(cookie, "secure", False)),
        }
        same_site = rest.get("SameSite") or rest.get("samesite")
        if same_site:
            entry["sameSite"] = same_site
        if entry["name"]:
            cookies.append(entry)
    return cookies


class LiveStudioBrowserLoginClient:
    def __init__(self, device_id, install_id):
        self.session = _new_http_session()
        self.version = fetch_live_studio_latest_version(self.session)
        self.browser_version = build_live_studio_browser_version(self.version)
        self.user_agent = f"Mozilla/{self.browser_version}"
        self.device_id = str(device_id).strip() if device_id else "0"
        self.install_id = str(install_id).strip() if install_id else "0"
        self.qr_client_secret = ""
        self.qr_domain = ""
        self._passport_domain = ""

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
        verify_fp = f"verify_{self.device_id}"
        params = _apply_passport_sdk_signature(
            {
                "next": "https://www.tiktok.com",
                "device_id": self.device_id,
                "aid": "8311",
                "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
                "verifyFp": verify_fp,
            }
        )

        preferred_hosts = [
            "api16-normal-no1a.tiktokv.eu",
            "api16-normal-c-alisg.tiktokv.com",
        ]
        candidate_hosts = _dedupe_hosts(preferred_hosts + resolve_api_host_candidates(self.session))
        last_payload = None
        last_error = None

        for host in candidate_hosts:
            url = f"https://{host}/passport/web/get_qrcode/"
            try:
                payload = self._signed_request_json(
                    "GET",
                    url,
                    params=params,
                    include_x_ss_stub=False,
                    headers={
                        "accept": "application/json, text/javascript",
                        "content-type": "application/x-www-form-urlencoded",
                        "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
                    },
                )
            except Exception as exc:
                last_error = exc
                continue

            last_payload = payload
            data_payload = payload.get("data", {}) if isinstance(payload, dict) else {}
            token = data_payload.get("token")
            qrcode_index_url = data_payload.get("qrcode_index_url") or ""
            qrcode_b64 = data_payload.get("qrcode") or ""
            if not token or not (qrcode_index_url or qrcode_b64):
                continue

            client_secret = _random_qr_client_secret()
            patched_qrcode_index_url = _inject_qr_client_secret(qrcode_index_url, client_secret)
            patched_qrcode_b64 = _qrcode_png_base64(patched_qrcode_index_url)

            self.qr_client_secret = client_secret if patched_qrcode_b64 else ""
            self.qr_domain = ""
            self._passport_domain = host

            data_payload = dict(data_payload)
            data_payload["qrcode_index_url_original"] = qrcode_index_url
            data_payload["qrcode_index_url"] = patched_qrcode_index_url or qrcode_index_url
            data_payload["clientSecret"] = self.qr_client_secret
            data_payload["domain"] = host
            if patched_qrcode_b64:
                data_payload["qrcode"] = patched_qrcode_b64
            return data_payload

        if last_error:
            raise last_error
        raise RuntimeError(f"QR login setup failed: {last_payload}")

    def check_qrconnect(self, token):
        verify_fp = f"verify_{self.device_id}"
        params = _apply_passport_sdk_signature(
            {
                "next": "https://www.tiktok.com",
                "token": token,
                "multi_login": "1",
                "device_id": self.device_id,
                "aid": "8311",
                "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
                "verifyFp": verify_fp,
            }
        )

        preferred_hosts = [
            self.qr_domain,
            self._passport_domain,
            "api16-normal-c-alisg.tiktokv.com",
            "api16-normal-useast8.tiktokv.us",
            "api16-normal-useast5.tiktokv.us",
            "api16-normal-no1a.tiktokv.eu",
        ]
        candidate_hosts = _dedupe_hosts(preferred_hosts + resolve_api_host_candidates(self.session))
        expected_secret = str(self.qr_client_secret or "")
        best_payload = None
        best_rank = -1
        last_error = None

        for host in candidate_hosts:
            url = f"https://{host}/passport/web/check_qrconnect/"
            try:
                payload = self._signed_request_json(
                    "GET",
                    url,
                    params=params,
                    include_x_ss_stub=False,
                    headers={
                        "accept": "application/json, text/javascript",
                        "content-type": "application/x-www-form-urlencoded",
                        "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
                    },
                )
            except Exception as exc:
                last_error = exc
                continue

            if not isinstance(payload, dict):
                continue
            data = payload.get("data", {})
            if not isinstance(data, dict):
                data = {}

            status = data.get("status") or data.get("qr_status") or data.get("state")
            client_secret = str(data.get("client_secret") or "")
            secret_matches = bool(expected_secret and client_secret == expected_secret)
            data["client_secret_match"] = secret_matches
            data["domain"] = host
            payload["data"] = data

            if status == "confirmed" and (secret_matches or not expected_secret):
                self.qr_domain = host
                self._passport_domain = host
                return payload

            if status == "scanned" and secret_matches:
                rank = 4
            elif status == "scanned":
                rank = 3
            elif status == "confirmed":
                # A confirmed response with the wrong/empty client_secret can happen on
                # another IDC. Keep polling for the domain that saw our QR secret.
                rank = 2 if expected_secret else 5
            elif status == "new":
                rank = 1
            else:
                rank = 0

            if rank > best_rank:
                best_rank = rank
                best_payload = payload

        if best_payload is not None:
            return best_payload
        if last_error:
            raise last_error
        return {"data": {"status": "new"}, "message": "No QR status response"}

    def account_info(self):
        host = self.qr_domain or self._passport_domain or "api16-normal-c-alisg.tiktokv.com"
        url = f"https://{host}/passport/account/info/v2/"
        verify_fp = f"verify_{self.device_id}"
        params = _apply_passport_sdk_signature(
            {
                "device_id": self.device_id,
                "aid": "8311",
                "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
                "verifyFp": verify_fp,
            }
        )
        return self._signed_request_json(
            "GET",
            url,
            params=params,
            include_x_ss_stub=False,
            headers={
                "accept": "application/json, text/javascript",
                "content-type": "application/x-www-form-urlencoded",
                "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
            },
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
        host = self._passport_domain or "api16-normal-c-alisg.tiktokv.com"
        url = f"https://{host}/passport/oidc/login/"
        verify_fp = f"verify_{self.device_id}"
        data = {
            "id_token": id_token,
            "ticket": ticket,
            "state": state,
        }
        params = _apply_passport_sdk_signature(
            {
                "device_id": self.device_id,
                "aid": "8311",
                "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
                "verifyFp": verify_fp,
                "fp": verify_fp,
                "language": "en",
                "multi_login": "1",
            },
            data=data,
        )

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
        response = _http_get(
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
    if _is_packaged_app():
        return os.path.dirname(_app_executable_path())
    return os.path.dirname(os.path.abspath(__file__))


def _is_packaged_app():
    return _is_frozen_build()


def _app_executable_path():
    candidates = [
        sys.argv[0] if sys.argv else "",
        sys.executable,
    ]
    for candidate in candidates:
        if candidate:
            path = os.path.abspath(candidate)
            if os.path.exists(path):
                return path
    return os.path.abspath(sys.executable)


def _runtime_logs_dir():
    # macOS .app bundles keep logs with the other user data; the bundle
    # itself is not a durable, writable location.
    base = _user_data_dir() if _is_macos_app_bundle() else _runtime_base_dir()
    preferred = os.path.join(base, "logs")
    try:
        os.makedirs(preferred, exist_ok=True)
        return preferred
    except OSError:
        fallback = os.path.join(os.path.expanduser("~"), "TiktokStreamKeyGenerator-logs")
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
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - 128 * 1024))
            return "".join(file.readlines()[-max_lines:]).strip()
    except OSError:
        return ""


def _mask_stream_url(value):
    if not value.startswith("rtmp://"):
        return value
    if "?" not in value:
        return value
    return value.split("?", 1)[0] + "?..."


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
    """Register live-studio-app to call this script with --protocol-callback and port.

    script_path may be None for frozen/compiled builds, where the executable
    itself handles --protocol-callback.
    """
    if sys.platform != "win32":
        return False
    try:
        if script_path:
            command = f'"{python_exe}" "{script_path}" --protocol-callback {port} "%1"'
        else:
            command = f'"{python_exe}" --protocol-callback {port} "%1"'

        root_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\live-studio-app")
        winreg.SetValue(root_key, "", winreg.REG_SZ, "URL:live-studio-app")
        winreg.SetValueEx(root_key, "URL Protocol", 0, winreg.REG_SZ, "")

        shell_key = winreg.CreateKey(root_key, r"shell\open\command")
        winreg.SetValue(shell_key, "", winreg.REG_SZ, command)

        # Verify the write round-tripped before telling the caller it worked —
        # a silently failed registration means the browser redirect goes
        # nowhere and login times out.
        check_key = winreg.OpenKey(shell_key, "", 0, winreg.KEY_READ)
        written, _ = winreg.QueryValueEx(check_key, "")
        winreg.CloseKey(check_key)
        winreg.CloseKey(shell_key)
        winreg.CloseKey(root_key)
        if written != command:
            print(f"Protocol registration verification mismatch: {written!r} != {command!r}")
            return False

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


def start_callback_server(stop_event=None):
    """Create a listening socket and return (server_thread, port, callback_event, result_container).

    Keeps accepting connections until one delivers a valid "URL:<...>" payload
    (starts with live-studio-app: and carries an id_token) or the stop event is
    set. Stray/partial connections (browser pre-connects, probes, truncated
    sends) are rejected without consuming the listener, so the real callback
    can still arrive afterwards.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(5)
    server_socket.settimeout(0.5)
    port = server_socket.getsockname()[1]

    result = {"url": None}
    event = threading.Event()
    if stop_event is None:
        stop_event = threading.Event()

    def wait_for_callback():
        try:
            while not stop_event.is_set() and not event.is_set():
                try:
                    conn, addr = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    # Read until the sender closes or we have the whole URL:
                    # id_token JWTs are several KB and a single recv() can
                    # truncate them.
                    conn.settimeout(5)
                    chunks = []
                    while True:
                        try:
                            chunk = conn.recv(4096)
                        except socket.timeout:
                            break
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if sum(len(c) for c in chunks) > 65536:
                            break
                    data = b"".join(chunks).decode("utf-8", "replace")
                except Exception:
                    data = ""
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                if data.startswith("URL:") and "id_token" in data:
                    result["url"] = data[4:].strip()
                    event.set()
                # Anything else (junk, partial, missing token) is dropped and
                # we keep listening for the real callback.
        except Exception:
            pass
        finally:
            event.set()
            try:
                server_socket.close()
            except Exception:
                pass

    thread = threading.Thread(target=wait_for_callback, daemon=True)
    thread.start()
    return thread, port, event, result


# ----------------------------------------------------------------------
# Main GUI Window
# ----------------------------------------------------------------------
class MobileBroadcastOptions(QWidget):
    changed = Signal()

    def __init__(self, record=None, parent=None):
        super().__init__(parent)
        self.updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('Broadcast:'))
        self.mode_combo = QComboBox()
        for label, value in MOBILE_BROADCAST_MODES:
            self.mode_combo.addItem('Mobile gaming' if value == 'screen_record' else label, value)
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)
        self.orientation_row = QWidget()
        orientation_layout = QHBoxLayout(self.orientation_row)
        orientation_layout.setContentsMargins(0, 0, 0, 0)
        orientation_layout.setSizeConstraint(QHBoxLayout.SetMinimumSize)
        orientation_layout.addWidget(QLabel('Orientation:'))
        self.orientation_combo = QComboBox()
        orientation_layout.addWidget(self.orientation_combo, 1)
        layout.addWidget(self.orientation_row)
        self.set_record(record or {})
        self.mode_combo.currentIndexChanged.connect(self.on_changed)
        self.orientation_combo.currentIndexChanged.connect(self.on_changed)

    def set_record(self, record):
        self.updating = True
        try:
            index = self.mode_combo.findData(record.get('broadcast_type', 'video'))
            self.mode_combo.setCurrentIndex(max(0, index))
            orientation = str(record.get('orientation', '1'))
            self.orientation_combo.clear()
            for label, value in MOBILE_ORIENTATIONS:
                self.orientation_combo.addItem(label, value)
            index = self.orientation_combo.findData(orientation)
            if index < 0:
                self.orientation_combo.addItem('Saved orientation (' + orientation + ')', orientation)
                index = self.orientation_combo.count() - 1
            self.orientation_combo.setCurrentIndex(index)
            self.orientation_row.setVisible(self.mode_combo.currentData() == 'screen_record')
        finally:
            self.updating = False

    def update_record(self, record):
        record['broadcast_type'] = self.mode_combo.currentData()
        # Keep the gaming orientation when switching to camera and back.
        record['orientation'] = self.orientation_combo.currentData()

    def on_changed(self):
        if self.updating:
            return
        self.orientation_row.setVisible(self.mode_combo.currentData() == 'screen_record')
        self.changed.emit()


class StreamKeyGeneratorWindow(AccentWindow):
    chat_messages_received = Signal(object)
    chat_status_changed = Signal(object)
    update_checked = Signal(object)
    account_info_loaded = Signal(object)
    account_info_failed = Signal(object)
    realtime_stats_loaded = Signal(object)
    realtime_stats_failed = Signal(object)
    audience_safety_loaded = Signal(object)
    audience_safety_failed = Signal(object)
    stream_ended_remotely = Signal(str)
    new_violation_detected = Signal(str)
    device_registered = Signal(str, object)
    device_initialization_finished = Signal(object)

    def __init__(self):
        super().__init__()
        configure_fluent_theme()
        self.setWindowTitle("TikTok Stream Key Generator")
        self.setWindowIcon(_application_icon())
        self.setMinimumSize(900, 580)
        self._workspace_restoring = True
        self.device_initialization_in_flight = False
        self.device_initialization_attempted = False
        self.device_initialization_errors = {}

        self.games = {}
        self._game_tags_loading = True
        self._closing = False
        self._foreground_task = None
        self._proxy_cleanup_threads = []
        self.device_id = ""
        self.install_id = ""
        self.device_type = 'pc'
        self.devices = {'pc': {}, 'mobile': {'device_id': '', 'install_id': ''}}
        self._config_extra = {}
        self.current_room_id = ""
        self.chat_client = None
        self._chat_generation = 0
        self._chat_identity = None
        self._chat_display_room = ''
        self._chat_displayed_gifts = OrderedDict()
        self._chat_displayed_message_ids = OrderedDict()
        self.current_stream_id = ""
        self.stream_priority_region = ""
        self.is_live = False
        # Cached dual-layout capability probe result for the current account:
        # None = never probed, True/False = last probe outcome.
        self.dual_layout_supported = None
        self.is_paused = False
        self.account_can_go_live = None
        self.account_info_in_flight = False
        self._account_request_id = 0
        self._account_request_cancel = None
        self._account_refresh_show_errors = False
        self.account_refresh_timeout = QTimer(self)
        self.account_refresh_timeout.setSingleShot(True)
        self.account_refresh_timeout.timeout.connect(self.on_account_refresh_timeout)
        self.account_load_failed = False
        self.account_refresh_timer = QTimer(self)
        self.account_refresh_timer.setSingleShot(True)
        self.account_refresh_timer.timeout.connect(lambda: self.refresh_account_info(show_errors=False))
        self.suppress_donation_reminder = False
        self.anchor_heartbeat_in_flight = False
        self.anchor_heartbeat_error_count = 0
        self.anchor_ping_status = ANCHOR_STATUS_DEFAULT
        # Focus tracking for polling throttling (True until first
        # changeEvent says otherwise, so startup behaves like focused).
        self.app_in_focus = True
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
        self.ffmpeg_proxy_watch_timer = QTimer(self)
        self.ffmpeg_proxy_watch_timer.setInterval(3000)
        self.ffmpeg_proxy_watch_timer.timeout.connect(self.check_ffmpeg_proxy_health)
        self.current_anchor_id = ""
        self.ffmpeg_proxy_process = None
        self.ffmpeg_proxy_log_file = None
        self.ffmpeg_proxy_log_path = ""
        self._proxy_error_reports = {}
        self.local_proxy_port = LOCAL_PROXY_DEFAULT_PORT
        self.local_proxy_server_url = ""
        self.local_proxy_stream_key = LOCAL_PROXY_STREAM_KEY
        self.local_proxy_active = False
        self.local_proxy_starting = False
        # Dual layout: second signed listener for the portrait canvas.
        self.dual_layout_active = False
        self.ffmpeg_proxy_portrait_process = None
        self.ffmpeg_proxy_portrait_log_file = None
        self.ffmpeg_proxy_portrait_log_path = ""
        self.ffmpeg_proxy_portrait_sei_log_path = ""
        self.local_portrait_proxy_port = LOCAL_PROXY_PORTRAIT_DEFAULT_PORT
        self.local_portrait_proxy_server_url = ""
        self.local_portrait_proxy_stream_key = LOCAL_PROXY_PORTRAIT_STREAM_KEY
        self.local_portrait_proxy_active = False
        self.show_real_stream_credentials = False
        self.real_stream_url = ""
        self.real_base_stream_url = ""
        self.real_stream_key = ""
        self.real_multi_stream_url = ""
        self.real_multi_stream_key = ""
        self.real_share_url = ""
        self.active_violation_ids = set()
        self.last_active_violation_count = 0
        self.cookie_file_path = _configured_cookies_path()
        self.rapidapi_key = _configured_rapidapi_key()

        self._build_ui()
        self.chat_messages_received.connect(self.on_chat_messages)
        self.chat_status_changed.connect(self.on_chat_status)
        self.update_checked.connect(self.handle_update_check)
        self.account_info_loaded.connect(self.on_account_info_loaded)
        self.account_info_failed.connect(self.on_account_info_failed)
        self.realtime_stats_loaded.connect(self.apply_realtime_stats)
        self.realtime_stats_failed.connect(self.handle_realtime_stats_error)
        self.audience_safety_loaded.connect(self.apply_audience_safety)
        self.audience_safety_failed.connect(self.handle_audience_safety_error)
        self.stream_ended_remotely.connect(self.handle_stream_ended_remotely)
        self.new_violation_detected.connect(self.handle_new_violation_detected)
        self.device_registered.connect(self.on_device_registered)
        self.device_initialization_finished.connect(self.on_device_initialization_finished)
        self.load_config()
        self._workspace_restoring = False
        self.update_stream_options_summary()
        self.update_device_mode_controls()
        self.check_cookies()
        self.ensure_device_identifiers(show_popup=True)
        has_startup_cookies, _ = self.get_cookie_file_status()
        if has_startup_cookies:
            self.schedule_account_refresh(900)
        single_shot(self, 0, self.load_game_tags)
        single_shot(self, 3000, self.show_donation_reminder)
        single_shot(self, 6000, self.check_updates_on_startup)


    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 16, 20, 16)
        outer_layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(TitleLabel('TikTok LIVE'))
        header.addStretch(1)
        from qfluentwidgets import IndeterminateProgressRing
        self.activity_spinner = IndeterminateProgressRing(self)
        self.activity_spinner.setFixedSize(22, 22)
        self.activity_spinner.hide()
        self.activity_spinner.setToolTip('Loading…')
        header.addWidget(self.activity_spinner)
        self.account_menu_button = DropDownPushButton('Account')
        self.views_menu_button = DropDownPushButton('Views')
        self.settings_button = QPushButton(FluentIcon.SETTING, 'Settings')
        self.settings_button.clicked.connect(lambda: self.open_settings('stream'))
        header.addWidget(self.account_menu_button)
        header.addWidget(self.views_menu_button)
        header.addWidget(self.settings_button)
        outer_layout.addLayout(header)
        navigation_row = QHBoxLayout()
        self.workspace_navigation = Pivot(self)
        navigation_row.addWidget(self.workspace_navigation)
        navigation_row.addStretch(1)
        self.account_summary = QLabel('No account loaded')
        self.account_summary.setTextFormat(Qt.PlainText)
        navigation_row.addWidget(self.account_summary)
        outer_layout.addLayout(navigation_row)
        self.workspace_stack = QStackedWidget(self)
        outer_layout.addWidget(self.workspace_stack, 1)
        self.live_page = QWidget()
        root_layout = QHBoxLayout(self.live_page)
        root_layout.setSpacing(12)
        root_layout.setContentsMargins(0, 0, 0, 0)

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

        input_group, input_layout = section("Stream Setup", grid=True)
        input_group.setMinimumWidth(0)
        input_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        input_layout.setSpacing(6)
        input_layout.setColumnStretch(1, 1)

        # Title
        title_label = QLabel("Title:")
        title_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(title_label)
        input_layout.addWidget(title_label, 0, 0)

        self.title_edit = QLineEdit()
        self.title_edit.setFixedHeight(36)
        allow_horizontal_shrink(self.title_edit)
        input_layout.addWidget(self.title_edit, 0, 1, 1, 2)

        # Topic
        topic_label = QLabel("Topic:")
        topic_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(topic_label)
        input_layout.addWidget(topic_label, 1, 0)

        self.topic_combo = QComboBox()
        self.topic_combo.addItems([""] + list(TOPICS.values()))
        self.topic_combo.currentTextChanged.connect(self.on_topic_changed)
        self.topic_combo.setFixedHeight(36)
        allow_horizontal_shrink(self.topic_combo)
        input_layout.addWidget(self.topic_combo, 1, 1, 1, 2)

        # Game
        self.game_label = QLabel("Game:")
        self.game_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(self.game_label)
        input_layout.addWidget(self.game_label, 2, 0)

        self.game_combo = EditableComboBox()
        self.game_combo.addItems([""] + list(self.games.values()))
        self.game_combo.setFixedHeight(36)
        allow_horizontal_shrink(self.game_combo)

        game_completer = QCompleter(list(self.games.values()), self)
        game_completer.setCaseSensitivity(Qt.CaseInsensitive)
        game_completer.setFilterMode(Qt.MatchContains)
        self.game_combo.setCompleter(game_completer)

        input_layout.addWidget(self.game_combo, 2, 1, 1, 2)

        mode_row = QHBoxLayout()
        client_label = QLabel('Client mode:')
        client_label.setStyleSheet('font-weight: bold;')
        input_layout.addWidget(client_label, 3, 0)
        self.device_type_combo = QComboBox()
        self.device_type_combo.addItem('PC (Studio)', 'pc')
        self.device_type_combo.addItem('Android', 'mobile')
        self.device_type_combo.currentIndexChanged.connect(self.on_device_type_changed)
        mode_row.addWidget(self.device_type_combo, 1)
        self.device_settings_button = ToolButton(FluentIcon.SETTING)
        self.device_settings_button.setAccessibleName('Device settings')
        self.device_settings_button.setToolTip('Device settings')
        self.device_settings_button.setFixedSize(36, 36)
        self.device_settings_button.clicked.connect(self.edit_device_settings)
        mode_row.addWidget(self.device_settings_button)
        input_layout.addLayout(mode_row, 3, 1, 1, 2)
        self.device_setup_status = QLabel('')
        self.device_setup_status.setWordWrap(True)
        self.device_setup_status.setTextFormat(Qt.PlainText)
        self.device_setup_status.hide()
        # Setup feedback stays visible below every workspace view.
        self.retry_devices_button = QPushButton('Retry device setup')
        self.retry_devices_button.clicked.connect(self.start_device_initialization)
        self.retry_devices_button.hide()
        self.device_setup_details_button = QPushButton('Details')
        self.device_setup_details_button.clicked.connect(self.show_device_setup_details)
        self.device_setup_details_button.hide()

        self.mobile_broadcast_options = MobileBroadcastOptions(parent=self)
        self.mobile_broadcast_options.changed.connect(self.on_mobile_broadcast_changed)
        input_layout.addWidget(self.mobile_broadcast_options, 4, 0, 1, 3)

        # Region
        region_label = QLabel("Region:")
        region_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(region_label)
        input_layout.addWidget(region_label, 5, 0)

        self.region_combo = EditableComboBox()
        self.region_combo.addItems(REGIONS)
        self.region_combo.setPlaceholderText('Auto (detected region)')
        self.region_combo.setToolTip('Leave blank to detect the region for the selected client. Enter a two-letter country code to override it; this does not change your account country or server.')
        self.region_combo.setFixedHeight(36)
        allow_horizontal_shrink(self.region_combo)
        input_layout.addWidget(self.region_combo, 5, 1, 1, 2)
        self.stream_options_summary = QLabel('')
        self.stream_options_summary.setWordWrap(True)
        input_layout.addWidget(self.stream_options_summary, 6, 0, 1, 3)
        input_layout.setRowStretch(7, 1)
        self.stream_options_panel, options_layout = section('Stream preferences')

        # Options
        options_label = QLabel("Options:")
        options_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(options_label)
        options_layout.addWidget(options_label)

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

        self.dual_layout_checkbox = QCheckBox("Dual Layout (Portrait + Landscape)")
        self.dual_layout_checkbox.setMinimumWidth(0)
        self.dual_layout_checkbox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.dual_layout_checkbox.setEnabled(False)
        self.dual_layout_checkbox.setToolTip(
            "Create a multi_stream_scene=1 room with two canvases. The existing Stream URL/Key "
            "stays on the landscape canvas and a second portrait endpoint is added for the "
            "vertical canvas. Only enabled once Refresh Account Info confirms this account "
            "has dual layout access (Can Dual Layout = True)."
        )
        options_grid.addWidget(self.dual_layout_checkbox, 2, 0, 1, 2)

        self.chat_sound_checkbox = QCheckBox('Chat notification sound')
        self.chat_sound_checkbox.setChecked(False)
        self.chat_sound_checkbox.setToolTip('Play the system notification sound for new comments and gifts. Off by default.')
        options_grid.addWidget(self.chat_sound_checkbox, 3, 0, 1, 2)

        options_grid.setColumnStretch(0, 1)
        options_grid.setColumnStretch(1, 1)
        options_layout.addLayout(options_grid)

        # Thumbnail
        thumbnail_label = QLabel("Selected Thumbnail:")
        thumbnail_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(thumbnail_label)
        options_layout.addWidget(thumbnail_label)

        thumbnail_row = QHBoxLayout()
        thumbnail_row.setSpacing(5)

        self.thumbnail_edit = QLineEdit()
        self.thumbnail_edit.setReadOnly(True)
        self.thumbnail_edit.setFixedHeight(36)
        allow_horizontal_shrink(self.thumbnail_edit)
        thumbnail_row.addWidget(self.thumbnail_edit)

        browse_button = QPushButton("Browse")
        browse_button.setFixedHeight(36)
        keep_button_visible(browse_button)
        browse_button.clicked.connect(self.browse_image)
        thumbnail_row.addWidget(browse_button)

        options_layout.addLayout(thumbnail_row)
        options_layout.addStretch(1)
        for checkbox in (self.replay_checkbox, self.age_restricted_checkbox,
                         self.close_room_checkbox, self.dual_layout_checkbox):
            checkbox.toggled.connect(self.update_stream_options_summary)

        root_layout.addWidget(input_group, 1)

        account_group, account_layout = section("Account")
        account_group.setMinimumWidth(0)
        account_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        account_layout.setContentsMargins(12, 16, 12, 12)
        account_layout.setSpacing(6)
        account_layout.setAlignment(Qt.AlignTop)

        session_label = QLabel("Cookies JSON")
        session_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(session_label)
        account_layout.addWidget(session_label)

        cookies_row = QHBoxLayout()
        cookies_row.setSpacing(6)

        self.cookies_path_edit = QLineEdit()
        self.cookies_path_edit.setFixedHeight(36)
        self.cookies_path_edit.setPlaceholderText("cookies.json")
        self.cookies_path_edit.editingFinished.connect(self.apply_cookies_path_from_input)
        allow_horizontal_shrink(self.cookies_path_edit)
        cookies_row.addWidget(self.cookies_path_edit, 1)

        self.browse_cookies_button = QPushButton("Browse")
        self.browse_cookies_button.setFixedHeight(36)
        keep_button_visible(self.browse_cookies_button)
        self.browse_cookies_button.clicked.connect(self.browse_cookies_file)
        cookies_row.addWidget(self.browse_cookies_button)
        account_layout.addLayout(cookies_row)
        self.studio_import_button = None
        if sys.platform == 'win32':
            self.studio_import_button = QPushButton('Import from LIVE Studio…', self)
            self.studio_import_button.clicked.connect(self.import_studio_cookies)
            self.studio_import_button.hide()

        rapidapi_label = QLabel("RapidAPI Key")
        rapidapi_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(rapidapi_label)
        account_layout.addWidget(rapidapi_label)

        rapidapi_row = QHBoxLayout()
        rapidapi_row.setSpacing(6)

        self.rapidapi_key_edit = QLineEdit()
        self.rapidapi_key_edit.setFixedHeight(36)
        self.rapidapi_key_edit.setEchoMode(QLineEdit.Password)
        self.rapidapi_key_edit.setPlaceholderText("Paste your RapidAPI key")
        self.rapidapi_key_edit.editingFinished.connect(self.apply_rapidapi_key_from_input)
        allow_horizontal_shrink(self.rapidapi_key_edit)
        rapidapi_row.addWidget(self.rapidapi_key_edit, 1)

        self.rapidapi_help_button = QPushButton("?")
        self.rapidapi_help_button.setFixedHeight(36)
        self.rapidapi_help_button.setToolTip("Open RapidAPI signer page")
        keep_button_visible(self.rapidapi_help_button, minimum_width=32)
        self.rapidapi_help_button.clicked.connect(self.open_rapidapi_signer_page)
        rapidapi_row.addWidget(self.rapidapi_help_button)

        account_layout.addLayout(rapidapi_row)
        if is_development():
            for widget in (rapidapi_label, self.rapidapi_key_edit, self.rapidapi_help_button):
                widget.hide()

        # Read-only account facts, two label/field pairs per row to save
        # vertical space (QLineEdit has no built-in legend or title).
        facts_grid = QGridLayout()
        facts_grid.setHorizontalSpacing(6)
        facts_grid.setVerticalSpacing(6)

        def make_fact_field():
            field = QLineEdit()
            field.setReadOnly(True)
            field.setFixedHeight(36)
            allow_horizontal_shrink(field)
            return field

        def add_account_fact(row, col, label_text, widget, tooltip=None):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            # Minimum (not Ignored) so the grid can never squeeze the label
            # to zero width when the fields claim the stretch.
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            if tooltip:
                label.setToolTip(tooltip)
                widget.setToolTip(tooltip)
            facts_grid.addWidget(label, row, col * 2)
            facts_grid.addWidget(widget, row, col * 2 + 1)

        self.account_username = make_fact_field()
        self.can_go_live_output = make_fact_field()
        self.dual_layout_output = make_fact_field()
        self.account_status = make_fact_field()

        # Quota meter: a progress bar that drains as the monthly RapidAPI
        # allowance is spent (full bar = full quota left). Styled explicitly
        # because the native Windows 11 style renders the chunk as a 3px
        # hairline that reads as plain text; palette() roles keep it
        # theme-aware.
        self.rapidapi_quota_bar = QProgressBar()
        self.rapidapi_quota_bar.setTextVisible(True)
        self.rapidapi_quota_bar.setFixedHeight(20)
        self.rapidapi_quota_bar.setRange(0, 1)
        self.rapidapi_quota_bar.setValue(0)
        self.rapidapi_quota_bar.setFormat("Unknown")
        self.rapidapi_quota_bar.setStyleSheet(
            "QProgressBar {"
            " border: 1px solid palette(mid);"
            " border-radius: 4px;"
            " background: palette(window);"
            " text-align: center;"
            " color: palette(text);"
            "}"
            "QProgressBar::chunk {"
            " border-radius: 3px;"
            " background: palette(highlight);"
            "}"
        )

        dual_layout_tip = (
            "allow_multi_stream from game/basic/create_info?scene=1 - the same "
            "account-level flag TikTok LIVE Studio uses to show or hide its dual "
            "layout button. Updated by Refresh Account Info."
        )
        add_account_fact(0, 0, "Username", self.account_username)
        add_account_fact(0, 1, "Can Go Live", self.can_go_live_output)
        add_account_fact(1, 0, "Can Dual Layout", self.dual_layout_output, dual_layout_tip)
        add_account_fact(1, 1, "Status", self.account_status)
        quota_tip = (
            "Remaining monthly RapidAPI signer requests, taken from the quota "
            "headers of the signer calls this app already makes (no extra "
            "requests are spent). The bar empties as the allowance is used; "
            "hover shows the reset date and when it was last updated."
        )
        quota_label = QLabel("RapidAPI Quota")
        quota_label.setStyleSheet("font-weight: bold;")
        quota_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        quota_label.setToolTip(quota_tip)
        self.rapidapi_quota_bar.setToolTip(quota_tip)
        facts_grid.addWidget(quota_label, 2, 0)
        # Span both field columns (and the second pair's label column) so the
        # meter gets the full row width instead of a single column.
        facts_grid.addWidget(self.rapidapi_quota_bar, 2, 1, 1, 3)
        if is_development():
            quota_label.hide()
            self.rapidapi_quota_bar.hide()
        facts_grid.setColumnStretch(1, 1)
        facts_grid.setColumnStretch(3, 1)
        account_layout.addLayout(facts_grid)

        # Re-read the persisted quota snapshot every minute; signer calls in
        # this or the proxy child processes refresh the underlying file.
        self.rapidapi_quota_timer = QTimer(self)
        self.rapidapi_quota_timer.setInterval(60_000)
        self.rapidapi_quota_timer.timeout.connect(self.update_rapidapi_quota_display)
        self.rapidapi_quota_timer.start()
        self.update_rapidapi_quota_display()

        self.refresh_account_button = QPushButton("Refresh Account Info")
        self.refresh_account_button.clicked.connect(lambda: self.refresh_account_info())
        self.refresh_account_button.setFixedHeight(36)
        allow_button_shrink(self.refresh_account_button)
        account_layout.addWidget(self.refresh_account_button)

        self.campaigns_button = QPushButton("LIVE Campaigns")
        self.campaigns_button.clicked.connect(self.open_campaigns)
        self.campaigns_button.setFixedHeight(36)
        allow_button_shrink(self.campaigns_button)
        self.campaigns_button.setParent(self)
        self.campaigns_button.hide()

        self.account_panel = account_group

        output_group, output_layout = section("Stream Connection")
        output_group.setMinimumWidth(0)
        output_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_layout.setSpacing(5)
        self.output_layout = output_layout

        primary_controls_row = QHBoxLayout()
        primary_controls_row.setSpacing(8)
        self.main_live_status = LiveStatusBadge()
        primary_controls_row.addWidget(self.main_live_status, 0, Qt.AlignVCenter)
        primary_controls_row.addStretch(1)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.start_login)
        self.login_button.setFixedHeight(36)
        allow_button_shrink(self.login_button)
        self.login_button.setParent(self)
        self.login_button.hide()

        self.go_live_button = PrimaryPushButton("Go Live")
        self.go_live_button.clicked.connect(self.generate_stream)
        self.go_live_button.setFixedHeight(36)
        keep_button_visible(self.go_live_button)
        primary_controls_row.addWidget(self.go_live_button)

        live_controls_row = QHBoxLayout()
        live_controls_row.setSpacing(5)

        self.pause_live_button = QPushButton("Pause")
        self.pause_live_button.setEnabled(False)
        self.pause_live_button.clicked.connect(self.pause_stream)
        self.pause_live_button.setFixedHeight(36)
        keep_button_visible(self.pause_live_button)
        live_controls_row.addWidget(self.pause_live_button)

        self.resume_live_button = QPushButton("Resume")
        self.resume_live_button.setEnabled(False)
        self.resume_live_button.clicked.connect(self.resume_stream)
        self.resume_live_button.setFixedHeight(36)
        keep_button_visible(self.resume_live_button)
        live_controls_row.addWidget(self.resume_live_button)

        self.end_live_button = QPushButton("End Live")
        self.end_live_button.setEnabled(False)
        self.end_live_button.clicked.connect(self.end_stream)
        self.end_live_button.setFixedHeight(36)
        keep_button_visible(self.end_live_button)
        live_controls_row.addWidget(self.end_live_button)

        primary_controls_row.addLayout(live_controls_row)

        self.url_output = QLineEdit()
        self.url_output.setReadOnly(True)
        self.url_output.setFixedHeight(36)
        allow_horizontal_shrink(self.url_output)

        self.key_output = QLineEdit()
        self.key_output.setReadOnly(True)
        self.key_output.setFixedHeight(36)
        allow_horizontal_shrink(self.key_output)

        self.share_url_output = QLineEdit()
        self.share_url_output.setReadOnly(True)
        self.share_url_output.setFixedHeight(36)
        allow_horizontal_shrink(self.share_url_output)

        def add_output_row(label_text, output_widget):
            # A container per row so the label, field and copy button can be
            # hidden/shown and reordered as one unit.
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            container_layout.setSizeConstraint(QHBoxLayout.SetMinimumSize)
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            label.setWordWrap(True)
            label.setFixedWidth(round(145 * max(12.0, QApplication.instance().font().pointSizeF()) / 12))
            container_layout.addWidget(label)
            output_widget.setMinimumWidth(100)
            container_layout.addWidget(output_widget, 1)
            copy_button = ToolButton(FluentIcon.COPY)
            copy_button.setFixedSize(36, 36)
            copy_button.setToolTip("Copy")
            copy_button.setAccessibleName('Copy ' + label_text.rstrip(':'))
            copy_button.setProperty("copy_icon_button", True)
            copy_button.clicked.connect(
                lambda checked=False, widget=output_widget, button=copy_button: self.copy_to_clipboard(
                    widget.text(),
                    button,
                )
            )
            container_layout.addWidget(copy_button)
            output_layout.addWidget(container)
            return container, label

        self.stream_url_container, self.stream_url_label = add_output_row("Stream URL:", self.url_output)
        self.stream_key_container, self.stream_key_label = add_output_row("Stream Key:", self.key_output)
        self.share_url_container, _share_label = add_output_row("Share URL:", self.share_url_output)

        self.portrait_url_output = QLineEdit()
        self.portrait_url_output.setReadOnly(True)
        self.portrait_url_output.setFixedHeight(36)
        allow_horizontal_shrink(self.portrait_url_output)

        self.portrait_key_output = QLineEdit()
        self.portrait_key_output.setReadOnly(True)
        self.portrait_key_output.setFixedHeight(36)
        allow_horizontal_shrink(self.portrait_key_output)

        self.portrait_url_container, self.portrait_url_label = add_output_row("Portrait Stream URL:", self.portrait_url_output)
        self.portrait_key_container, self.portrait_key_label = add_output_row("Portrait Stream Key:", self.portrait_key_output)
        self.portrait_url_container.hide()
        self.portrait_key_container.hide()

        # Checking/unchecking Dual Layout relabels the primary rows, shows or
        # hides the portrait rows, and moves the Share URL to the bottom.
        self.dual_layout_checkbox.toggled.connect(
            lambda checked: self.refresh_stream_credentials_display()
        )

        proxy_row = QHBoxLayout()
        proxy_row.setSpacing(5)
        proxy_label = QLabel("Proxy Status:")
        proxy_label.setStyleSheet("font-weight: bold;")
        allow_label_shrink(proxy_label)
        proxy_row.addWidget(proxy_label)
        self.proxy_status_output = QLineEdit()
        self.proxy_status_output.setReadOnly(True)
        self.proxy_status_output.setFixedHeight(36)
        allow_horizontal_shrink(self.proxy_status_output)
        proxy_row.addWidget(self.proxy_status_output)
        self.toggle_stream_credentials_button = QPushButton("Real TikTok URL hidden")
        self.toggle_stream_credentials_button.setEnabled(False)
        self.toggle_stream_credentials_button.setFixedHeight(36)
        allow_button_shrink(self.toggle_stream_credentials_button)
        self.toggle_stream_credentials_button.clicked.connect(self.toggle_stream_credentials_display)
        # Retain this compatibility control for stream-state code; the GUI
        # exposes only the local connection fields and never the real endpoint.
        self.toggle_stream_credentials_button.setParent(self)
        self.toggle_stream_credentials_button.hide()
        output_layout.addLayout(proxy_row)

        stats_group, stats_layout = section("Realtime Stats", grid=True)
        stats_layout.setHorizontalSpacing(8)
        stats_layout.setVerticalSpacing(5)

        def add_stats_field(row, column, label_text, widget):
            label = QLabel(label_text)
            label.setMinimumWidth(70)
            stats_layout.addWidget(label, row, column)
            stats_layout.addWidget(widget, row, column + 1)

        self.live_status_stats_output = QLineEdit()
        self.live_status_stats_output.setReadOnly(True)
        self.live_status_stats_output.setFixedHeight(36)
        allow_horizontal_shrink(self.live_status_stats_output)
        add_stats_field(0, 0, "Live", self.live_status_stats_output)

        self.live_viewer_count_output = QLineEdit()
        self.live_viewer_count_output.setReadOnly(True)
        self.live_viewer_count_output.setFixedHeight(36)
        allow_horizontal_shrink(self.live_viewer_count_output)
        add_stats_field(0, 2, "Live Viewers", self.live_viewer_count_output)

        self.viewer_count_output = QLineEdit()
        self.viewer_count_output.setReadOnly(True)
        self.viewer_count_output.setFixedHeight(36)
        allow_horizontal_shrink(self.viewer_count_output)
        add_stats_field(1, 0, "Views", self.viewer_count_output)

        self.like_count_output = QLineEdit()
        self.like_count_output.setReadOnly(True)
        self.like_count_output.setFixedHeight(36)
        allow_horizontal_shrink(self.like_count_output)
        add_stats_field(1, 2, "Likes", self.like_count_output)

        self.comment_count_output = QLineEdit()
        self.comment_count_output.setReadOnly(True)
        self.comment_count_output.setFixedHeight(36)
        allow_horizontal_shrink(self.comment_count_output)
        add_stats_field(2, 0, "Comments", self.comment_count_output)

        self.share_count_output = QLineEdit()
        self.share_count_output.setReadOnly(True)
        self.share_count_output.setFixedHeight(36)
        allow_horizontal_shrink(self.share_count_output)
        add_stats_field(2, 2, "Shares", self.share_count_output)

        self.new_fans_count_output = QLineEdit()
        self.new_fans_count_output.setReadOnly(True)
        self.new_fans_count_output.setFixedHeight(36)
        allow_horizontal_shrink(self.new_fans_count_output)
        add_stats_field(3, 0, "New Fans", self.new_fans_count_output)

        self.refresh_stats_button = QPushButton("Refresh Stats")
        self.refresh_stats_button.clicked.connect(lambda: self.refresh_realtime_stats(force=True))
        self.refresh_stats_button.setFixedHeight(36)
        allow_button_shrink(self.refresh_stats_button)
        stats_layout.addWidget(self.refresh_stats_button, 4, 0, 1, 4)

        stats_layout.setColumnStretch(1, 1)
        stats_layout.setColumnStretch(3, 1)

        audience_summary_group, audience_summary_layout = section("Online Audience", grid=True)
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
        self.online_audience_total_output.setFixedHeight(36)
        allow_horizontal_shrink(self.online_audience_total_output)
        add_audience_field(0, 0, "Total", self.online_audience_total_output)

        self.online_audience_preview_output = QLineEdit()
        self.online_audience_preview_output.setReadOnly(True)
        self.online_audience_preview_output.setFixedHeight(36)
        allow_horizontal_shrink(self.online_audience_preview_output)
        add_audience_field(0, 2, "Preview", self.online_audience_preview_output)

        self.online_audience_table_output = QTableWidget(0, 5)
        self.online_audience_table_output.setHorizontalHeaderLabels(["#", "Username", "Nickname", "Score", "Badges"])
        self.online_audience_table_output.setAlternatingRowColors(True)
        self.online_audience_table_output.setMinimumHeight(150)
        self.online_audience_table_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.online_audience_table_output.verticalHeader().setVisible(False)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.online_audience_table_output.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.online_audience_table_output.setWordWrap(False)
        self.online_audience_table_output.setTextElideMode(Qt.ElideRight)
        audience_summary_layout.addWidget(QLabel("Visible Audience"), 1, 0, 1, 4)
        audience_summary_layout.addWidget(self.online_audience_table_output, 2, 0, 1, 4)
        audience_summary_layout.setColumnStretch(1, 1)
        audience_summary_layout.setColumnStretch(3, 1)

        safety_group, safety_layout = section("Safety", grid=True)
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
        self.violation_status_output.setFixedHeight(36)
        allow_horizontal_shrink(self.violation_status_output)
        add_safety_field(0, 0, "Status", self.violation_status_output)

        self.community_status_output = QLineEdit()
        self.community_status_output.setReadOnly(True)
        self.community_status_output.setFixedHeight(36)
        allow_horizontal_shrink(self.community_status_output)
        add_safety_field(0, 2, "Community", self.community_status_output)

        self.ban_status_output = QLineEdit()
        self.ban_status_output.setReadOnly(True)
        self.ban_status_output.setFixedHeight(36)
        allow_horizontal_shrink(self.ban_status_output)
        add_safety_field(1, 0, "Ban", self.ban_status_output)

        self.violation_details_output = QTableWidget(0, 5)
        self.violation_details_output.setHorizontalHeaderLabels(["Room", "Violation", "Reason", "Start", "End"])
        self.violation_details_output.setAlternatingRowColors(True)
        self.violation_details_output.setMinimumHeight(170)
        self.violation_details_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.violation_details_output.verticalHeader().setVisible(False)
        header = self.violation_details_output.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.violation_details_output.setWordWrap(True)
        self.violation_details_output.setTextElideMode(Qt.ElideRight)
        safety_layout.addWidget(QLabel("Violations"), 2, 0, 1, 4)
        safety_layout.addWidget(self.violation_details_output, 3, 0, 1, 4)

        self.refresh_audience_safety_button = QPushButton("Refresh Audience / Safety")
        self.refresh_audience_safety_button.clicked.connect(lambda: self.refresh_audience_safety(force=True))
        self.refresh_audience_safety_button.setFixedHeight(36)
        allow_button_shrink(self.refresh_audience_safety_button)
        safety_layout.addWidget(self.refresh_audience_safety_button, 4, 0, 1, 4)
        safety_layout.setColumnStretch(1, 1)
        safety_layout.setColumnStretch(3, 1)
        output_layout.addStretch()

        # Bottom buttons
        self.save_config_button = QPushButton("Save Config")
        self.save_config_button.setFixedHeight(36)
        allow_button_shrink(self.save_config_button)
        self.save_config_button.setParent(self)
        self.save_config_button.hide()

        self.donate_button = QPushButton("Donate")
        self.donate_button.setToolTip("Support development")
        self.donate_button.clicked.connect(self.open_donation_url)
        self.donate_button.setFixedHeight(36)
        allow_button_shrink(self.donate_button)
        self.donate_button.setParent(self)
        self.donate_button.hide()
        account_layout.addStretch(1)
        root_layout.addWidget(output_group, 1)
        self.workspace_pages = {'live': self.live_page}
        self.workspace_titles = {'live': 'LIVE', 'chat': 'Chat', 'stats': 'Stats', 'audience': 'Audience', 'safety': 'Safety'}
        self.visible_workspace_views = {'chat', 'stats', 'audience', 'safety'}
        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_group, chat_content = section('LIVE chat')
        chat_header = QHBoxLayout()
        self.chat_status = CaptionLabel('Start a LIVE to read chat')
        self.chat_status.setWordWrap(True)
        chat_header.addWidget(self.chat_status, 1)
        self.chat_reconnect_button = QPushButton('Reconnect')
        self.chat_reconnect_button.setEnabled(False)
        self.chat_reconnect_button.clicked.connect(self.reconnect_chat)
        chat_header.addWidget(self.chat_reconnect_button)
        chat_clear_button = QPushButton('Clear')
        chat_clear_button.clicked.connect(self.clear_chat)
        chat_header.addWidget(chat_clear_button)
        chat_content.addLayout(chat_header)
        self.chat_output = QPlainTextEdit()
        self.chat_output.setReadOnly(True)
        self.chat_output.setPlaceholderText('Viewer comments and gifts will appear here during your LIVE.')
        self.chat_output.setAccessibleName('LIVE chat messages and gifts')
        self.chat_output.setMaximumBlockCount(1000)
        chat_content.addWidget(self.chat_output, 1)
        chat_layout.addWidget(chat_group)
        self.workspace_pages['chat'] = chat_page
        for key, card in (('stats', stats_group), ('audience', audience_summary_group), ('safety', safety_group)):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(card)
            if key == 'stats':
                layout.addStretch(1)
            self.workspace_pages[key] = page
        for key, page in self.workspace_pages.items():
            self.workspace_stack.addWidget(page)
            self.workspace_navigation.addItem(key, self.workspace_titles[key])
        self.workspace_navigation.currentItemChanged.connect(self.show_workspace_view)
        self.workspace_navigation.setCurrentItem('live')
        outer_layout.addLayout(primary_controls_row)
        setup_feedback = QHBoxLayout()
        setup_feedback.addWidget(self.device_setup_status, 1)
        setup_feedback.addWidget(self.device_setup_details_button)
        setup_feedback.addWidget(self.retry_devices_button)
        outer_layout.addLayout(setup_feedback)
        self._build_settings_dialog()
        self._build_workspace_menus()
        self.account_username.textChanged.connect(self.update_account_summary)
        self.account_status.textChanged.connect(self.update_account_summary)
        style_controls(self)
        self.on_topic_changed(self.topic_combo.currentText())

    def _build_settings_dialog(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle('Settings')
        self.settings_dialog.resize(760, 570)
        self.settings_dialog.setMinimumWidth(640)
        layout = QVBoxLayout(self.settings_dialog)
        layout.setContentsMargins(20, 16, 20, 16)
        navigation = Pivot(self.settings_dialog)
        self.settings_stack = QStackedWidget(self.settings_dialog)
        self.settings_navigation = navigation
        layout.addWidget(navigation)
        layout.addWidget(self.settings_stack, 1)
        for key, title, page in (('account', 'Account', self.account_panel),
                                 ('stream', 'Stream', self.stream_options_panel)):
            page.setObjectName(key)
            self.settings_stack.addWidget(page)
            navigation.addItem(key, title)
        navigation.currentItemChanged.connect(
            lambda key: self.settings_stack.setCurrentWidget(
                self.account_panel if key == 'account' else self.stream_options_panel))
        navigation.setCurrentItem('stream')
        footer = QHBoxLayout()
        footer.addWidget(CaptionLabel('Settings are saved when you close this window.'))
        footer.addStretch(1)
        done = PrimaryPushButton('Done')
        done.setDefault(True)
        done.clicked.connect(self.settings_dialog.accept)
        footer.addWidget(done)
        layout.addLayout(footer)
        self.settings_dialog.finished.connect(self._save_workspace_settings)
        self.save_config_button.clicked.connect(lambda: self.save_config())
        style_controls(self.settings_dialog)

    def open_settings(self, page='stream'):
        self.settings_navigation.setCurrentItem('account' if page == 'account' else 'stream')
        self.settings_dialog.exec()

    def _save_workspace_settings(self):
        typed_path = _normalize_configured_path(self.cookies_path_edit.text().strip() or DEFAULT_COOKIES_PATH)
        if typed_path != self.get_cookies_path():
            self.set_cookies_path(typed_path, save=False, refresh=True)
        self.update_stream_options_summary()
        self.save_config(show_message=False)

    def _build_workspace_menus(self):
        self.workspace_action_controls = {}

        def control_action(text, button, shortcut=None):
            action = Action(text, self)
            action.triggered.connect(button.click)
            if shortcut:
                action.setShortcut(shortcut)
                self.addAction(action)
            self.workspace_action_controls[action] = button
            return action

        self.account_menu = RoundMenu('Account', self)
        self.account_menu.addAction(control_action('Log in with QR code', self.login_button))
        self.account_menu.addAction(control_action('Import cookies…', self.browse_cookies_button))
        if self.studio_import_button is not None:
            self.account_menu.addAction(control_action('Import from LIVE Studio…', self.studio_import_button))
        self.account_menu.addAction(control_action('Refresh account', self.refresh_account_button))
        self.account_menu.addAction(control_action('LIVE campaigns…', self.campaigns_button))
        self.account_menu.addSeparator()
        account_settings = Action('Account settings…', self)
        account_settings.triggered.connect(lambda: self.open_settings('account'))
        self.account_menu.addAction(account_settings)
        self.account_menu.addSeparator()
        self.account_menu.addAction(control_action('Support development', self.donate_button))
        self.account_menu_button.setMenu(self.account_menu)

        self.views_menu = CheckableMenu('Views', self)
        self.view_actions = {}
        for key in ('chat', 'stats', 'audience', 'safety'):
            action = Action(self.workspace_titles[key], self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda visible, view=key: self.set_workspace_view_visible(view, visible))
            self.view_actions[key] = action
            self.views_menu.addAction(action)
        self.views_menu.addSeparator()
        restore = Action('Restore default views', self)
        restore.triggered.connect(self.restore_workspace_views)
        self.views_menu.addAction(restore)
        self.views_menu_button.setMenu(self.views_menu)

        self.workspace_menu = RoundMenu('Workspace', self)
        self.workspace_menu.addAction(control_action('Device settings…', self.device_settings_button))
        settings = Action(FluentIcon.SETTING, 'Stream settings…', self)
        settings.setShortcut('Ctrl+,')
        settings.triggered.connect(lambda: self.open_settings('stream'))
        self.addAction(settings)
        self.workspace_menu.addAction(settings)
        self.workspace_menu.addAction(control_action('Save settings', self.save_config_button, 'Ctrl+S'))
        self.workspace_menu.addSeparator()
        self.workspace_menu.addAction(control_action('Refresh stats', self.refresh_stats_button))
        self.workspace_menu.addAction(control_action('Refresh audience / safety', self.refresh_audience_safety_button))
        context_views = CheckableMenu('Views', self.workspace_menu)
        self.context_view_actions = {}
        for key in self.view_actions:
            action = Action(self.workspace_titles[key], self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda visible, view=key: self.set_workspace_view_visible(view, visible))
            self.context_view_actions[key] = action
            context_views.addAction(action)
        self.workspace_menu.addMenu(context_views)
        self.copy_workspace_actions = {}
        for name, field in (('Stream URL', self.url_output), ('Stream key', self.key_output),
                            ('Share URL', self.share_url_output)):
            action = Action(FluentIcon.COPY, 'Copy ' + name, self)
            action.triggered.connect(lambda checked=False, widget=field: self.copy_to_clipboard(widget.text()))
            self.copy_workspace_actions[action] = field
            self.workspace_menu.addAction(action)
        # The visible Views/Settings controls expose everything offered here.
        for widget in (self.workspace_stack, *self.workspace_pages.values()):
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda point, target=widget: self.show_workspace_context_menu(target.mapToGlobal(point)))
        # Keep existing shortcuts stable; the new Chat view uses Ctrl+5.
        for index, key in enumerate(('live', 'stats', 'audience', 'safety', 'chat'), 1):
            action = Action(self.workspace_titles[key], self)
            action.setShortcut('Ctrl+' + str(index))
            action.triggered.connect(lambda checked=False, view=key: self.show_workspace_view(view))
            self.addAction(action)

    def show_workspace_context_menu(self, position):
        self.sync_workspace_actions()
        self.workspace_menu.exec(position)

    def sync_workspace_actions(self):
        if not hasattr(self, 'workspace_action_controls'):
            return
        for action, button in self.workspace_action_controls.items():
            action.setEnabled(button.isEnabled())
        for action, field in self.copy_workspace_actions.items():
            action.setEnabled(bool(field.text()))
        username = self.account_username.text().strip()
        self.account_menu_button.setToolTip('Loading account details…' if self.account_is_loading() else
                                            'Account: ' + username if username else 'Log in, import cookies or manage your account')

    def show_workspace_view(self, key):
        if key not in self.workspace_pages or (key != 'live' and key not in self.visible_workspace_views):
            return
        changed = self.workspace_stack.currentWidget() is not self.workspace_pages[key]
        self.workspace_stack.setCurrentWidget(self.workspace_pages[key])
        self.workspace_navigation.blockSignals(True)
        self.workspace_navigation.setCurrentItem(key)
        self.workspace_navigation.blockSignals(False)
        if changed and not self._workspace_restoring:
            self.save_config(show_message=False)

    def set_workspace_view_visible(self, key, visible):
        if key not in self.view_actions:
            return
        if visible:
            self.visible_workspace_views.add(key)
        else:
            self.visible_workspace_views.discard(key)
            if self.workspace_stack.currentWidget() is self.workspace_pages[key]:
                self.show_workspace_view('live')
        self.workspace_navigation.items[key].setVisible(visible)
        for action in (self.view_actions[key], self.context_view_actions[key]):
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        if not self._workspace_restoring:
            self.save_config(show_message=False)

    def restore_workspace_views(self):
        for key in self.view_actions:
            self.set_workspace_view_visible(key, True)
        self.show_workspace_view('live')

    def load_workspace_preferences(self, preferences):
        preferences = preferences if isinstance(preferences, dict) else {}
        visible = preferences.get('visible_views', list(self.view_actions))
        if not isinstance(visible, list):
            visible = list(self.view_actions)
        # Existing installations should see the newly added Chat view once.
        known = preferences.get('known_views')
        if not isinstance(known, list):
            known = []
        if 'chat' not in known and 'chat' not in visible:
            visible = [*visible, 'chat']
        for key in self.view_actions:
            self.set_workspace_view_visible(key, key in visible)
        active = preferences.get('active_view', 'live')
        if not isinstance(active, str) or active not in self.workspace_pages or (active != 'live' and active not in self.visible_workspace_views):
            active = 'live'
        self.show_workspace_view(active)

    def account_is_loading(self):
        return (self.account_info_in_flight or self.account_refresh_timer.isActive() or
                (self.device_initialization_in_flight and self.get_cookie_file_status()[0]))

    def schedule_account_refresh(self, delay_ms=0):
        self.account_load_failed = False
        self.account_refresh_timer.start(delay_ms)
        self.update_account_summary()

    def update_account_summary(self):
        username = self.account_username.text().strip()
        loading = self.account_is_loading()
        if loading:
            text = ('@' + username.lstrip('@') + ' · Refreshing…') if username else 'Loading account…'
        elif self.account_load_failed:
            text = ('@' + username.lstrip('@') + ' · Refresh failed') if username else 'Account load failed'
        else:
            text = '@' + username.lstrip('@') if username else 'No account loaded'
        self.account_summary.setText(
            self.account_summary.fontMetrics().elidedText(text, Qt.ElideRight, 240) if username else text)
        self.account_summary.setAccessibleName(text)
        self.account_summary.setToolTip(text + '\n' + self.account_status.text())
        for field in (self.account_username, self.account_status, self.can_go_live_output, self.dual_layout_output):
            field.setPlaceholderText('Loading…' if loading else '')

    def update_stream_options_summary(self):
        if not hasattr(self, 'stream_options_summary') or not hasattr(self, 'dual_layout_checkbox'):
            return
        options = ['Replay on' if self.replay_checkbox.isChecked() else 'Replay off',
                   'Dual layout' if self.dual_layout_checkbox.isChecked() else 'Single canvas']
        if self.age_restricted_checkbox.isChecked():
            options.append('Age restricted')
        self.stream_options_summary.setText(' · '.join(options))
        self.stream_options_summary.setToolTip('Change these options in Settings → Stream.')

    def _rapidapi_error_kind(self, message):
        failure = hosted_signer_failure(message)
        return failure.kind.value if failure is not None else ''

    def show_rapidapi_error(self, message):
        kind = self._rapidapi_error_kind(message)
        if not kind:
            QMessageBox.critical(self, "Error", str(message))
            return
        if kind == "quota":
            title = "RapidAPI request limit reached"
            body = (
                "The signing service has reached a rate or quota limit.\n\n"
                "The app cannot safely continue without fresh signatures. "
                "Upgrade the RapidAPI plan or wait for the quota to reset, then try again."
            )
        elif kind == "subscription":
            title = "RapidAPI key or subscription error"
            body = (
                "The signing service requires a valid API key and subscription.\n\n"
                "Subscribe to the free tier on the TikTok LIVE Studio API Signer page, "
                "copy your RapidAPI key, and paste it into the app."
            )
        else:
            title = "RapidAPI signer unavailable"
            body = (
                "The RapidAPI signer could not provide valid signatures.\n\n"
                "Check your RapidAPI key, subscription, network connection, and remaining quota. "
                "The app will not forward video without valid signatures."
            )

        details = str(message or "").strip()
        if len(details) > 800:
            details = details[:800] + "..."

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Critical)
        dialog.setWindowTitle(title)
        dialog.setText(body)
        if details:
            dialog.setInformativeText(f"Details:\n{details}")
        open_button = dialog.addButton("Open RapidAPI signer", QMessageBox.AcceptRole)
        dialog.addButton(QMessageBox.Close)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(RAPIDAPI_SIGNER_DOCS_URL))

    def show_error(self, message):
        if self._rapidapi_error_kind(message):
            self.show_rapidapi_error(message)
            return
        QMessageBox.critical(self, "Error", str(message))

    def show_info(self, message):
        QMessageBox.information(self, "Info", message)

    def get_selected_topic_id(self):
        selected = self.topic_combo.currentText().strip().lower()
        for topic_id, topic_name in TOPICS.items():
            if topic_name.lower() == selected:
                return topic_id
        return ""

    def get_selected_game_id(self):
        if self._game_tags_loading:
            return str(self._config_extra.get('game_tag_id') or '')
        selected = self.game_combo.currentText().strip().lower()
        for game_id, game_name in self.games.items():
            if game_name.lower() == selected:
                return game_id
        return ""

    def on_topic_changed(self, topic_name):
        mobile_video = self.device_type == 'mobile' and self.devices.get('mobile', {}).get('broadcast_type', 'video') == 'video'
        is_gaming = topic_name == "Gaming" and not mobile_video
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
        if button.property('copy_icon_button'):
            button.setIcon(FluentIcon.ACCEPT)
        else:
            button.setText("✓")
        button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.restore_copy_button(button, original_text))

    def restore_copy_button(self, button, original_text):
        try:
            button.setText(original_text)
            if button.property('copy_icon_button'):
                button.setIcon(FluentIcon.COPY)
            button.setEnabled(True)
        except RuntimeError:
            pass

    def clear_output_fields(self):
        self.url_output.clear()
        self.key_output.clear()
        self.portrait_url_output.clear()
        self.portrait_key_output.clear()
        self.share_url_output.clear()
        self.clear_realtime_stats_fields()
        self.clear_audience_safety_fields()
        self.real_stream_url = ""
        self.real_base_stream_url = ""
        self.real_stream_key = ""
        self.real_multi_stream_url = ""
        self.real_multi_stream_key = ""
        self.real_share_url = ""
        self.active_violation_ids = set()
        self.last_active_violation_count = 0
        self.local_proxy_server_url = ""
        self.local_proxy_stream_key = LOCAL_PROXY_STREAM_KEY
        self.local_portrait_proxy_server_url = ""
        self.local_portrait_proxy_stream_key = LOCAL_PROXY_PORTRAIT_STREAM_KEY
        self.dual_layout_active = False
        self.local_proxy_starting = False
        self.show_real_stream_credentials = False
        self.toggle_stream_credentials_button.setText("Real TikTok URL hidden")
        self.toggle_stream_credentials_button.setEnabled(False)
        if hasattr(self, "proxy_status_output") and not self.local_proxy_active:
            self.proxy_status_output.clear()
        if hasattr(self, "stream_url_label"):
            self.refresh_stream_credentials_display()

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
        self.violation_details_output.setRowCount(0)

    def format_stat_value(self, value):
        if value in (None, ""):
            return ""
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)

    def sync_realtime_stats_timer(self):
        # Focus gating: the stats/trends endpoints are display-only; while
        # the window is unfocused the timer stays stopped so no RapidAPI
        # /signatures calls are spent on numbers nobody is looking at.
        if ENABLE_STUDIO_STATS_POLLING and self.app_in_focus:
            should_run = bool(self.is_live and self.current_room_id)
            if should_run:
                if not self.realtime_stats_timer.isActive():
                    self.realtime_stats_timer.start()
            else:
                self.realtime_stats_timer.stop()
            return

        self.realtime_stats_timer.stop()

    def refresh_realtime_stats(self, force=False):
        self.sync_realtime_stats_timer()
        if not ENABLE_STUDIO_STATS_POLLING:
            # Keep the Studio stats/trends endpoints quiet while using the local
            # RTMP proxy. They are not needed for stream health and are a strong
            # integrity-signal suspect compared with the mirror path.
            if force and hasattr(self, "refresh_stats_button"):
                self.refresh_stats_button.setEnabled(True)
                self.refresh_stats_button.setText("Refresh Stats")
            return

        if force and hasattr(self, "refresh_stats_button"):
            self.refresh_stats_button.setEnabled(True)
            self.refresh_stats_button.setText("Refresh Stats")

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
        # Unfocused and not user-forced: no stats refresh; sync_polling_focus
        # re-fires this with the timer restarted on refocus.
        if not self.app_in_focus and not force:
            return

        self.realtime_stats_in_flight = True
        self.sync_activity_spinner()
        if force:
            self.refresh_stats_button.setEnabled(False)
            self.refresh_stats_button.setText("Refreshing...")

        room_id = self.current_room_id
        priority_region = self.stream_priority_region or self.region_combo.currentText()

        factory = self.stream_factory()
        device_id, install_id = self.device_id, self.install_id

        def worker():
            try:
                with factory() as stream:
                    stats = stream.getRealtimeStats(
                        device_id=device_id,
                        install_id=install_id,
                        priority_region=priority_region,
                        room_id=room_id,
                    )
                    try:
                        trends = stream.getTrendsStats(
                            device_id=device_id,
                            install_id=install_id,
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
                self.realtime_stats_failed.emit(exc)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self.handle_realtime_stats_error(exc)

    def apply_realtime_stats(self, stats):
        self.realtime_stats_in_flight = False
        self.update_stream_controls()
        self.refresh_stats_button.setText("Refresh Stats")
        is_live = stats.get("is_live")
        if is_live is True:
            self.live_status_stats_output.setText("Live")
        elif is_live is False:
            self.live_status_stats_output.setText("Offline")
        else:
            self.live_status_stats_output.setText("")
        self.live_viewer_count_output.setText(self.format_stat_value(stats.get("live_viewer_count")))
        self.viewer_count_output.setText(self.format_stat_value(stats.get("watch_count")))
        self.like_count_output.setText(self.format_stat_value(stats.get("like_count")))
        self.comment_count_output.setText(self.format_stat_value(stats.get("comment_count")))
        self.share_count_output.setText(self.format_stat_value(stats.get("share_count")))
        self.new_fans_count_output.setText(self.format_stat_value(stats.get("new_fans_count")))

    def handle_realtime_stats_error(self, message):
        self.realtime_stats_in_flight = False
        self.update_stream_controls()
        self.refresh_stats_button.setText("Refresh Stats")
        if message:
            print(f"Realtime stats refresh failed: {message}")

    def sync_audience_safety_timer(self):
        has_cookies = self.get_cookie_file_status()[0]
        should_run = bool(has_cookies)
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

    def _set_table_item(self, table, row, column, text):
        item = QTableWidgetItem(str(text or ""))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, column, item)
        return item

    def _add_safety_detail_row(self, detail_type, status, details):
        row = self.violation_details_output.rowCount()
        self.violation_details_output.insertRow(row)
        self._set_table_item(self.violation_details_output, row, 0, "")
        self._set_table_item(self.violation_details_output, row, 1, detail_type)
        self._set_table_item(self.violation_details_output, row, 2, details)
        self._set_table_item(self.violation_details_output, row, 3, "")
        self._set_table_item(self.violation_details_output, row, 4, "")

    def _format_violation_epoch(self, value):
        if value in (None, "", 0, "0"):
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(value)))
        except (TypeError, ValueError, OSError):
            return str(value)

    def _violation_record_id(self, record):
        if not isinstance(record, dict):
            return ""
        return (
            record.get("violation_id_str")
            or record.get("violation_id")
            or (record.get("punish_info") or {}).get("punish_record_id_str")
            or (record.get("punish_info") or {}).get("punish_record_id")
            or ""
        )

    def _style_active_violation_row(self, row):
        highlight = QBrush(QColor(80, 64, 24))
        text = QBrush(QColor(255, 230, 180))
        bold_font = QFont(self.violation_details_output.font())
        bold_font.setBold(True)
        for column in range(self.violation_details_output.columnCount()):
            item = self.violation_details_output.item(row, column)
            if item is None:
                continue
            item.setBackground(highlight)
            item.setForeground(text)
            item.setFont(bold_font)

    def _add_violation_row(self, record, is_active=False):
        if not isinstance(record, dict):
            return
        punish = record.get("punish_info") or {}
        live = record.get("live_info") or {}
        row = self.violation_details_output.rowCount()
        self.violation_details_output.insertRow(row)
        room_title = live.get("title") or ""
        self._set_table_item(self.violation_details_output, row, 0, room_title)
        self._set_table_item(
            self.violation_details_output,
            row,
            1,
            punish.get("punish_title") or punish.get("perception_code") or punish.get("violation_type") or "Violation",
        )
        self._set_table_item(
            self.violation_details_output,
            row,
            2,
            punish.get("punish_reason") or punish.get("moderation_info") or punish.get("perception_code") or "",
        )
        self._set_table_item(
            self.violation_details_output,
            row,
            3,
            self._format_violation_epoch(punish.get("punish_start_time") or live.get("start_time")),
        )
        self._set_table_item(
            self.violation_details_output,
            row,
            4,
            self._format_violation_epoch(
                punish.get("punish_real_end_time")
                or punish.get("punish_expected_end_time")
                or punish.get("punish_end_time")
            ),
        )
        if is_active:
            self._style_active_violation_row(row)

    def _populate_violation_table(self, safety):
        self.violation_details_output.setRowCount(0)
        self.violation_details_output.clearSpans()

        active_records = safety.get("active_violation_records") or []
        history_records = safety.get("history_violation_records") or []
        active_ids = {str(self._violation_record_id(record)) for record in active_records if self._violation_record_id(record)}

        for record in active_records:
            self._add_violation_row(record, is_active=True)
        for record in history_records:
            record_id = str(self._violation_record_id(record))
            if record_id and record_id in active_ids:
                continue
            self._add_violation_row(record, is_active=False)

        if self.violation_details_output.rowCount() == 0:
            self.violation_details_output.insertRow(0)
            self.violation_details_output.setSpan(0, 0, 1, 5)
            self._set_table_item(self.violation_details_output, 0, 0, "No violations returned by violation_list.")
        self.violation_details_output.resizeRowsToContents()

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
        if not self.get_cookie_file_status()[0]:
            self.sync_audience_safety_timer()
            return

        self.audience_safety_in_flight = True
        self.sync_activity_spinner()
        if force:
            self.refresh_audience_safety_button.setEnabled(False)
            self.refresh_audience_safety_button.setText("Refreshing...")

        room_id = self.current_room_id
        # Focus gating: while the window is unfocused, skip the display-only
        # audience fetch — the violation checks below still run.
        can_fetch_audience = bool(
            ENABLE_ONLINE_AUDIENCE_POLLING
            and self.is_live
            and room_id
            and self.app_in_focus
        )
        if not can_fetch_audience:
            room_id = ""
        anchor_id = self.current_anchor_id or getattr(self, "account_user_id_value", "")
        priority_region = self.stream_priority_region or self.region_combo.currentText()
        topic_id = self.get_selected_topic_id() or "5"
        fetch_safety_details = bool(ENABLE_SAFETY_DETAIL_POLLING and self.app_in_focus)

        factory = self.stream_factory()
        device_id, install_id = self.device_id, self.install_id

        def worker():
            try:
                with factory() as stream:
                    if can_fetch_audience:
                        audience = stream.getOnlineAudience(
                            device_id=device_id,
                            install_id=install_id,
                            priority_region=priority_region,
                            room_id=room_id,
                            anchor_id=anchor_id,
                        )
                    else:
                        audience = {
                            "total": None,
                            "preview_count": None,
                            "ranks": [],
                            "bottom_notice": (
                                "Not live. Audience data is unavailable."
                                if not self.is_live
                                else "Audience panel paused (app not focused). Violations are still monitored."
                            ),
                        }
                    safety = stream.getViolationStatus(
                        device_id=device_id,
                        install_id=install_id,
                        priority_region=priority_region,
                        room_id=room_id,
                        last_time_hashtag_id=topic_id,
                        include_details=fetch_safety_details,
                    )
                self.audience_safety_loaded.emit({"audience": audience, "safety": safety})
            except Exception as exc:
                self.audience_safety_failed.emit(exc)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self.handle_audience_safety_error(exc)

    def apply_audience_safety(self, result):
        self.audience_safety_in_flight = False
        self.update_stream_controls()
        self.refresh_audience_safety_button.setText("Refresh Audience / Safety")

        audience = result.get("audience") or {}
        safety = result.get("safety") or {}

        self.online_audience_total_output.setText(self.format_stat_value(audience.get("total")))
        self.online_audience_preview_output.setText(self.format_stat_value(audience.get("preview_count")))
        ranks = audience.get("ranks") or []
        self._populate_audience_list(ranks, audience.get("bottom_notice"))

        status_text = str(safety.get("status") or "OK")
        self.community_status_output.setText(self._format_community_status(safety))
        self.ban_status_output.setText(self._format_ban_status(safety))

        active_summaries = safety.get("active_violation_summaries") or []
        active_ids = set(safety.get("active_violation_ids") or [])
        new_ids = active_ids - self.active_violation_ids
        active_count = safety.get("active_violation_count", 0) or 0
        if new_ids:
            first_summary = active_summaries[0] if active_summaries else "A new LIVE violation was detected."
            self.new_violation_detected.emit(first_summary)
        elif active_count > 0 and self.last_active_violation_count == 0:
            self.flash_taskbar()
        self.active_violation_ids = active_ids
        self.last_active_violation_count = active_count
        self.violation_status_output.setText(status_text)
        self._populate_violation_table(safety)

    def handle_audience_safety_error(self, message):
        self.audience_safety_in_flight = False
        self.update_stream_controls()
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
        # Device/Install IDs are no longer displayed in the UI; kept as a
        # no-op for existing call sites.
        pass

    def saved_device_records(self):
        import copy
        records = copy.deepcopy(self.devices)
        records.setdefault(self.device_type, {}).update(device_id=self.device_id, install_id=self.install_id)
        records[self.device_type]['dual_layout_supported'] = self.dual_layout_supported
        if self.device_type == 'mobile':
            records['mobile'] = mobile_record_defaults(records['mobile'])
        return records

    def stream_factory(self):
        from functools import partial
        return partial(Stream, cookies_path=self.get_cookies_path(), device_type=self.device_type,
                       device_profile=self.saved_device_records()[self.device_type])

    def new_stream(self):
        return self.stream_factory()()

    def load_game_tags(self):
        if self._closing:
            return
        self.game_combo.setPlaceholderText('Loading games…')
        self.game_combo.setEnabled(False)
        BackgroundTask(self, Work(fetch_game_tags), self.on_game_tags_loaded,
                       lambda error: self.on_game_tags_loaded({})).start()

    def on_game_tags_loaded(self, games):
        if self._closing:
            return
        selected = self.get_selected_game_id() or str(self._config_extra.get('game_tag_id') or '')
        self.games = games
        self._game_tags_loading = False
        self.game_combo.setEnabled(True)
        self.game_combo.clear()
        self.game_combo.addItems([''] + list(games.values()))
        if selected in games:
            self.game_combo.setCurrentText(games[selected])
        self.game_combo.setPlaceholderText('Select a game' if games else 'Games unavailable; reopen the app to retry')
        completer = QCompleter(list(games.values()), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.game_combo.setCompleter(completer)
        self.sync_activity_spinner()

    def open_campaigns(self):
        if not self.get_cookie_file_status()[0] or not self.ensure_device_identifiers():
            return
        # Freeze the mode and identity for every request made by this dialog.
        kind, record = self.device_type, self.saved_device_records()[self.device_type]
        cookies_path, region = self.get_cookies_path(), self.region_combo.currentText()
        def factory():
            return Stream(cookies_path=cookies_path, device_type=kind, device_profile=record)
        dialog = CampaignsDialog(factory, kind=kind, priority_region=region,
                                 viewed_cache_path=os.path.join(os.path.dirname(CONFIG_PATH), 'campaign_views.json'), parent=self)
        dialog.exec()

    def update_device_mode_controls(self):
        mobile = self.device_type == 'mobile'
        self.mobile_broadcast_options.set_record(self.devices.get('mobile', {}))
        self.mobile_broadcast_options.setVisible(mobile)
        self.mobile_broadcast_options.setEnabled(not self.device_settings_busy())
        self.close_room_checkbox.setEnabled(not mobile)
        self.login_button.setEnabled(not mobile)
        self.login_button.setToolTip('Import Android cookies for mobile mode.' if mobile else '')
        self.rapidapi_key_edit.setEnabled(not is_development())
        self.update_dual_layout_status()

    def device_settings_busy(self, include_account_refresh=True):
        return (getattr(self, '_foreground_task', None) is not None or self.is_live or self.local_proxy_starting or self.device_initialization_in_flight or
                (include_account_refresh and self.account_info_in_flight) or
                any(getattr(self, key, False) for key in (
                    'realtime_stats_in_flight', 'audience_safety_in_flight', 'anchor_heartbeat_in_flight')))

    def on_mobile_broadcast_changed(self):
        if self.device_type != 'mobile' or self.device_settings_busy():
            self.mobile_broadcast_options.set_record(self.devices.get('mobile', {}))
            return
        self.mobile_broadcast_options.update_record(self.devices.setdefault('mobile', {}))
        self.update_dual_layout_status()
        self.on_topic_changed(self.topic_combo.currentText())
        self.save_config(show_message=False)

    def on_device_type_changed(self):
        kind = self.device_type_combo.currentData()
        if kind == self.device_type:
            return
        if self.device_settings_busy(include_account_refresh=False):
            self.device_type_combo.blockSignals(True)
            self.device_type_combo.setCurrentIndex(1 if self.device_type == 'mobile' else 0)
            self.device_type_combo.blockSignals(False)
            return
        self.invalidate_account_refresh()
        self.devices = self.saved_device_records()
        self.device_type = kind
        record = self.devices.setdefault(kind, {})
        self.device_id = str(record.get('device_id') or '')
        self.install_id = str(record.get('install_id') or '')
        self.account_can_go_live = None
        self.dual_layout_supported = record.get('dual_layout_supported')
        self.account_username.clear()
        self.account_status.clear()
        self.can_go_live_output.clear()
        self.clear_output_fields()
        self.update_device_mode_controls()
        self.on_topic_changed(self.topic_combo.currentText())
        self.update_stream_controls()
        self.save_config(show_message=False)

        # Switching profiles clears eligibility, but the selected cookies
        # still identify the account. Reload it once the new mode is applied.
        if self.has_device_identifiers() and self.get_cookie_file_status()[0]:
            self.schedule_account_refresh()

    def edit_device_settings(self):
        if self.device_settings_busy() or not self.device_settings_button.isEnabled():
            return
        dialog = DeviceSettingsDialog(self.device_type, self.saved_device_records()[self.device_type], self)
        if dialog.exec() != QDialog.Accepted:
            return
        record = dialog.record
        self.devices[self.device_type] = record
        self.device_id, self.install_id = record['device_id'], record['install_id']
        self.update_device_mode_controls()
        self.on_topic_changed(self.topic_combo.currentText())
        self.save_config(show_message=False)
        self.start_device_initialization()
        self.update_stream_controls()

    def has_device_identifiers(self):
        return has_registered_ids({'device_id': self.device_id, 'install_id': self.install_id})

    def ensure_device_identifiers(self, show_popup=False):
        if not self.device_initialization_attempted and not self.device_initialization_in_flight:
            self.start_device_initialization()
        ready = self.has_device_identifiers()
        if not ready and show_popup and not self.device_initialization_in_flight:
            self.show_error('Device setup could not finish. Use Retry device setup or enter the IDs in Device settings.')
        return ready

    def start_device_initialization(self):
        if self.device_initialization_in_flight or self.is_live or self.local_proxy_starting:
            return
        self.device_initialization_attempted = True
        try:
            self.devices = prepare_device_profiles(self.saved_device_records())
        except (TypeError, ValueError) as exc:
            self.device_initialization_errors = {'setup': str(exc)}
            self.device_setup_status.setText('Device setup failed: ' + str(exc))
            self.device_setup_status.show()
            self.device_setup_details_button.show()
            self.retry_devices_button.show()
            return
        # Save the local fingerprints before network I/O so a failed attempt or
        # a restart reuses the same installation instead of rotating its UUIDs.
        self.save_config(show_message=False)
        missing = [kind for kind in ('pc', 'mobile') if not has_registered_ids(self.devices[kind])]
        self.device_initialization_errors = {}
        if not missing:
            self.device_setup_status.clear()
            self.device_setup_status.hide()
            self.retry_devices_button.hide()
            self.device_setup_details_button.hide()
            return
        import copy
        pending = {kind: copy.deepcopy(self.devices[kind]) for kind in missing}
        self.device_initialization_in_flight = True
        self.device_setup_status.setText('Creating device IDs for ' + ', '.join('PC' if k == 'pc' else 'Android' for k in missing) + '…')
        self.device_setup_status.show()
        self.device_setup_details_button.hide()
        self.retry_devices_button.hide()
        self.update_stream_controls()

        def worker():
            errors = {}
            for kind, profile in pending.items():
                register = register_desktop_device_identifiers if kind == 'pc' else register_mobile_device_identifiers
                try:
                    record = register(device_profile=profile, return_profile=True)
                    if not has_registered_ids(record):
                        raise ValueError('Registration did not return valid device/install IDs.')
                    self.device_registered.emit(kind, record)
                except Exception as exc:
                    errors[kind] = str(exc)
            self.device_initialization_finished.emit(errors)
        threading.Thread(target=worker, daemon=True).start()

    def on_device_registered(self, kind, record):
        self.devices[kind] = {**self.devices[kind], **record}
        if kind == self.device_type:
            self.device_id, self.install_id = str(record['device_id']), str(record['install_id'])
        self.save_config(show_message=False)
        self.update_stream_controls()

    def on_device_initialization_finished(self, errors):
        self.device_initialization_in_flight = False
        self.device_initialization_errors = errors
        if errors:
            names = ', '.join('PC' if k == 'pc' else 'Android' for k in errors)
            zero_ids = errors.get('mobile', '').startswith('TikTok returned zero Android')
            self.device_setup_status.setText(
                'TikTok did not issue Android IDs. Use valid Android IDs or PC mode.' if zero_ids and len(errors) == 1
                else names + ' device setup failed. Open Details for the reason.')
            self.device_setup_status.setToolTip('\n'.join(('PC' if k == 'pc' else 'Android') + ': ' + str(v) for k, v in errors.items()))
            self.device_setup_status.show()
            self.retry_devices_button.show()
            self.device_setup_details_button.show()
        else:
            self.device_setup_status.clear()
            self.device_setup_status.hide()
            self.retry_devices_button.hide()
            self.device_setup_details_button.hide()
        self.update_device_mode_controls()
        self.update_stream_controls()
        if self.has_device_identifiers() and self.get_cookie_file_status()[0]:
            self.schedule_account_refresh()

    def show_device_setup_details(self):
        if not self.device_initialization_errors:
            return
        details = '\n\n'.join(
            ('PC' if key == 'pc' else 'Android' if key == 'mobile' else 'Device setup') + ': ' + str(message)
            for key, message in self.device_initialization_errors.items())
        QMessageBox.information(self, 'Device setup details', details)

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
        new_path = _normalize_configured_path(path or DEFAULT_COOKIES_PATH)
        if new_path != getattr(self, "cookie_file_path", None):
            self.invalidate_account_refresh()
            self.stop_chat()
            self.clear_chat()
            self._chat_displayed_gifts.clear()
            self._chat_displayed_message_ids.clear()
            # Account switch: the cached dual-layout capability result no
            # longer applies to the new cookies file.
            self.dual_layout_supported = None
            self.account_can_go_live = None
            self.account_load_failed = False
            self.account_username.clear()
            self.account_status.clear()
            self.can_go_live_output.clear()
            self.update_dual_layout_status()
        self.cookie_file_path = new_path
        if hasattr(self, "cookies_path_edit"):
            self.cookies_path_edit.blockSignals(True)
            self.cookies_path_edit.setText(self.cookie_file_path)
            self.cookies_path_edit.blockSignals(False)
        if save:
            self.save_config(show_message=False)
        if refresh:
            self.check_cookies()
        self.sync_chat()

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

    @foreground('Reading LIVE Studio accounts…')
    def import_studio_cookies(self):
        if sys.platform != 'win32' or self.is_live or self.device_initialization_in_flight:
            return
        from Libs.studio_cookies import StudioCookieError, read_studio_accounts
        from Libs.studio_import_ui import StudioImportDialog
        try:
            accounts = (yield Work(read_studio_accounts, label='Reading LIVE Studio accounts…'))
        except StudioCookieError as exc:
            self.show_error(exc)
            return
        dialog = StudioImportDialog(accounts, output_dir=_runtime_base_dir(), parent=self)
        if dialog.exec() != QDialog.Accepted or not dialog.saved_path:
            return
        self.set_cookies_path(dialog.saved_path, save=True, refresh=True)
        self.refresh_account_info(show_errors=True)

    def get_rapidapi_key(self):
        if hasattr(self, "rapidapi_key_edit"):
            return self.rapidapi_key_edit.text().strip()
        return str(getattr(self, "rapidapi_key", "") or "").strip()

    def ensure_rapidapi_signer(self):
        try:
            if self.device_type == 'mobile':
                ClientImplementation('mobile', mobile_record_defaults(self.saved_device_records()['mobile'])).validate()
            if is_development():
                return True
        except Exception as exc:
            self.show_error(exc)
            return False
        if self.get_rapidapi_key():
            return True
        self.show_rapidapi_error("RapidAPI signer key is required for request and frame signing.")
        return False

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
            self.cookies_path_edit.setError(not has_cookies)
        if not has_cookies:
            self.account_can_go_live = None

        self.login_button.setEnabled(self.device_type == 'pc')
        self.update_stream_controls(has_cookies=has_cookies)
        self.sync_audience_safety_timer()

    def set_proxy_status(self, message):
        if hasattr(self, "proxy_status_output"):
            self.proxy_status_output.setText(str(message or ""))

    def toggle_stream_credentials_display(self):
        # The real TikTok destination is intentionally never exposed by the GUI.
        self.show_real_stream_credentials = False
        self.refresh_stream_credentials_display()

    def refresh_stream_credentials_display(self):
        self.share_url_output.setText(self.real_share_url)
        self.share_url_output.setCursorPosition(0)
        has_local_credentials = bool(self.local_proxy_active and self.local_proxy_server_url)
        has_portrait_credentials = bool(self.local_portrait_proxy_active and self.local_portrait_proxy_server_url)
        self.show_real_stream_credentials = False
        self.toggle_stream_credentials_button.setEnabled(False)
        self.toggle_stream_credentials_button.setText("Real TikTok URL hidden")

        # Dual rows follow the checkbox (pre-live) as well as the actual
        # room state (post go-live), so checking the option immediately
        # reveals the Landscape/Portrait output rows.
        dual_requested = self.dual_layout_active or (
            getattr(self, "dual_layout_checkbox", None) is not None
            and self.dual_layout_checkbox.isChecked()
        )

        if dual_requested:
            self.stream_url_label.setText("Landscape Stream URL:")
            self.stream_key_label.setText("Landscape Stream Key:")
        else:
            self.stream_url_label.setText("Stream URL:")
            self.stream_key_label.setText("Stream Key:")

        if dual_requested:
            self.portrait_url_container.show()
            self.portrait_key_container.show()
        else:
            self.portrait_url_container.hide()
            self.portrait_key_container.hide()

        # With dual layout on, the Share URL moves below the portrait rows;
        # otherwise it sits right below the primary Stream URL/Key rows.
        layout = self.output_layout
        share_index = layout.indexOf(self.share_url_container)
        if dual_requested and share_index < layout.indexOf(self.portrait_key_container):
            layout.removeWidget(self.share_url_container)
            layout.insertWidget(layout.indexOf(self.portrait_key_container) + 1, self.share_url_container)
        elif not dual_requested and share_index > layout.indexOf(self.portrait_url_container):
            layout.removeWidget(self.share_url_container)
            layout.insertWidget(layout.indexOf(self.portrait_url_container), self.share_url_container)

        if self.local_proxy_starting:
            self.url_output.clear()
            self.key_output.clear()
            self.portrait_url_output.clear()
            self.portrait_key_output.clear()
            return

        if not has_local_credentials:
            self.url_output.clear()
            self.key_output.clear()
        else:
            self.url_output.setText(self.local_proxy_server_url)
            self.key_output.setText(self.local_proxy_stream_key)
            self.url_output.setCursorPosition(0)
            self.key_output.setCursorPosition(0)

        if not has_portrait_credentials:
            self.portrait_url_output.clear()
            self.portrait_key_output.clear()
        else:
            self.portrait_url_output.setText(self.local_portrait_proxy_server_url)
            self.portrait_key_output.setText(self.local_portrait_proxy_stream_key)
            self.portrait_url_output.setCursorPosition(0)
            self.portrait_key_output.setCursorPosition(0)

    def ffmpeg_proxy_is_running(self):
        return self.ffmpeg_proxy_process is not None and self.ffmpeg_proxy_process.poll() is None

    def wait_for_ffmpeg_proxy_listener(self, timeout_seconds=25, process=None, sei_log_path=None):
        marker = "waiting for OBS/local RTMP connection"
        if process is None:
            process = self.ffmpeg_proxy_process
        if sei_log_path is None:
            sei_log_path = getattr(self, "ffmpeg_proxy_sei_log_path", "")
        deadline = time.monotonic() + max(1, timeout_seconds)
        while time.monotonic() < deadline:
            if process is None:
                return False
            return_code = process.poll()
            if return_code is not None:
                return False
            if sei_log_path and os.path.exists(sei_log_path):
                try:
                    with open(sei_log_path, "r", encoding="utf-8", errors="replace") as file:
                        if marker in file.read(256 * 1024):
                            return True
                except Exception:
                    pass
            time.sleep(0.1)
        return False

    def build_ffmpeg_proxy_command(
        self,
        ffmpeg_path,
        local_input_url,
        tiktok_output_url,
        log_path="",
        resolution="1920x1080",
    ):
        if not log_path:
            log_path = getattr(self, "ffmpeg_proxy_sei_log_path", "")
        proxy_args = [
            "--ffmpeg",
            ffmpeg_path,
            "--listen-url",
            local_input_url,
            "--output-url",
            tiktok_output_url,
            "--uid",
            str(self.current_anchor_id or ""),
            "--device-id",
            str(self.device_id or ""),
            "--room-id",
            str(self.current_room_id or ""),
            "--aid",
            str(self.devices.get(self.device_type, {}).get('aid', '1233' if self.device_type == 'mobile' else '8311')),
            "--device-type",
            self.device_type,
            "--config-path",
            CONFIG_PATH,
            "--fps",
            "60",
            "--resolution",
            resolution,
            "--timeout",
            str(LOCAL_PROXY_LISTEN_TIMEOUT_SECONDS),
            "--log",
            log_path,
        ]

        if _is_packaged_app():
            return [_app_executable_path(), "--sei-proxy", *proxy_args]

        sei_proxy = os.path.join(_runtime_base_dir(), "Libs", "ffmpeg_sei_proxy.py")
        if os.path.exists(sei_proxy):
            self.ffmpeg_proxy_sei_log_path = os.path.join(_runtime_logs_dir(), "ffmpeg_proxy_sei.log")
            return [sys.executable, sei_proxy, *proxy_args]

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

    def _launch_sei_proxy(self, command, log_file, log_path, sei_log_path, process_attribute):
        # process_attribute: "ffmpeg_proxy_process" or "ffmpeg_proxy_portrait_process"
        if '--output-url' in command:
            # Unique to this launch, so a prior crash cannot label a new one.
            report_path = log_path + '.' + secrets.token_hex(8) + '.error.json'
            self._proxy_error_reports[process_attribute] = report_path
            command = [*command, '--error-report', report_path]
        log_file.write(
            "[proxy] command: "
            + " ".join(_mask_stream_url(str(part)) for part in command)
            + "\n"
        )
        log_file.flush()
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Hand the RapidAPI key to the proxy child through its environment.
        # Without this the child re-reads config.json from disk on every
        # signing call, which fails when the config lives outside the app
        # dir (macOS .app bundles keep it in ~/Library/Application Support)
        # or while save_config is mid-rewrite. _config_value checks the
        # environment first, so the child never needs the file for the key.
        child_env = os.environ.copy()
        rapidapi_key = self.get_rapidapi_key()
        if rapidapi_key:
            child_env["RAPIDAPI_KEY"] = rapidapi_key
        setattr(self, process_attribute, (yield Work(subprocess.Popen, command,
            cwd=_runtime_base_dir(),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=child_env, label='Preparing local FFmpeg proxy signatures…')))

        (yield Work(time.sleep, 0.35, label='Preparing local FFmpeg proxy signatures…'))
        process = getattr(self, process_attribute)
        return_code = process.poll()
        if return_code is not None:
            tail = (yield Work(_safe_log_tail, log_path, label='Preparing local FFmpeg proxy signatures…'))
            details = f"\n\nFFmpeg log tail:\n{tail}" if tail else ""
            error = self.proxy_failure(process_attribute, f"FFmpeg proxy exited early with code {return_code}.{details}")
            self.stop_ffmpeg_proxy(clear_status=False)
            raise error

        self.set_proxy_status("Preparing local FFmpeg proxy signatures...")
        if not (yield Work(self.wait_for_ffmpeg_proxy_listener, timeout_seconds=25,
            process=process,
            sei_log_path=sei_log_path, label='Preparing local FFmpeg proxy signatures…')):
            return_code = process.poll() if process is not None else None
            tail = (yield Work(_safe_log_tail, sei_log_path, label='Preparing local FFmpeg proxy signatures…'))
            details = f"\n\nSEI proxy log tail:\n{tail}" if tail else ""
            if return_code is not None:
                error = self.proxy_failure(process_attribute, f"FFmpeg proxy exited before the local listener was ready with code {return_code}.{details}")
            else:
                error = RuntimeError(f"FFmpeg proxy did not open the local listener in time.{details}")
            self.stop_ffmpeg_proxy(clear_status=False)
            raise error

    def proxy_failure(self, process_attribute, message):
        path = self._proxy_error_reports.pop(process_attribute, '')
        cause = read_proxy_error(path)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        return OperationError(message, cause) if cause is not None else RuntimeError(message)

    def start_ffmpeg_proxy(self, tiktok_output_url, defer_display=False):
        # defer_display: dual layout suppresses the reveal of the landscape
        # URL/key fields here so they appear at the same moment as the
        # portrait fields (the portrait proxy's start performs the single
        # combined refresh once both listeners are up).
        self.stop_ffmpeg_proxy(clear_status=False)
        for cleanup in self._proxy_cleanup_threads:
            yield Work(cleanup.join, label='Stopping previous FFmpeg proxy…')
        self._proxy_cleanup_threads.clear()
        if not tiktok_output_url:
            raise RuntimeError("Missing TikTok RTMP URL for local FFmpeg proxy.")

        self.local_proxy_starting = True
        self.show_real_stream_credentials = False
        self.refresh_stream_credentials_display()

        ffmpeg_path = _bundled_ffmpeg_path()
        try:
            self.local_proxy_port = _pick_local_proxy_port(LOCAL_PROXY_DEFAULT_PORT)
            self.local_proxy_stream_key = LOCAL_PROXY_STREAM_KEY
            self.local_proxy_server_url = f"rtmp://127.0.0.1:{self.local_proxy_port}/{LOCAL_PROXY_APP_NAME}"
            local_input_url = f"{self.local_proxy_server_url}/{self.local_proxy_stream_key}"
            self.ffmpeg_proxy_log_path = os.path.join(_runtime_logs_dir(), LOCAL_PROXY_LOG_NAME)
            self.ffmpeg_proxy_sei_log_path = os.path.join(_runtime_logs_dir(), "ffmpeg_proxy_sei.log")
            self.ffmpeg_proxy_log_file = open(self.ffmpeg_proxy_log_path, "w", encoding="utf-8", errors="replace")

            command = self.build_ffmpeg_proxy_command(ffmpeg_path, local_input_url, tiktok_output_url)
            (yield from self._launch_sei_proxy(
                command,
                self.ffmpeg_proxy_log_file,
                self.ffmpeg_proxy_log_path,
                self.ffmpeg_proxy_sei_log_path,
                "ffmpeg_proxy_process",
            ))

            self.local_proxy_active = True
            self.local_proxy_starting = False
            self.show_real_stream_credentials = False
            self.ffmpeg_proxy_watch_timer.start()
            if not defer_display:
                self.set_proxy_status("Proxy ready. Start streaming in OBS.")
                self.refresh_stream_credentials_display()
            return True
        finally:
            self.local_proxy_starting = False

    def start_portrait_ffmpeg_proxy(self, tiktok_output_url):
        # Dual layout: second signed listener forwarding to the portrait
        # (main stream_url) canvas. Signing args are identical to the primary.
        if not tiktok_output_url:
            raise RuntimeError("Missing TikTok RTMP URL for the portrait FFmpeg proxy.")

        ffmpeg_path = _bundled_ffmpeg_path()
        self.local_portrait_proxy_port = _pick_local_proxy_port(LOCAL_PROXY_PORTRAIT_DEFAULT_PORT)
        if self.local_portrait_proxy_port == self.local_proxy_port:
            # Never share a port with the primary listener.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                self.local_portrait_proxy_port = int(sock.getsockname()[1])
        self.local_portrait_proxy_stream_key = LOCAL_PROXY_PORTRAIT_STREAM_KEY
        self.local_portrait_proxy_server_url = f"rtmp://127.0.0.1:{self.local_portrait_proxy_port}/{LOCAL_PROXY_PORTRAIT_APP_NAME}"
        portrait_input_url = f"{self.local_portrait_proxy_server_url}/{self.local_portrait_proxy_stream_key}"
        self.ffmpeg_proxy_portrait_log_path = os.path.join(_runtime_logs_dir(), LOCAL_PROXY_PORTRAIT_LOG_NAME)
        self.ffmpeg_proxy_portrait_sei_log_path = os.path.join(_runtime_logs_dir(), "ffmpeg_proxy_portrait_sei.log")
        self.ffmpeg_proxy_portrait_log_file = open(self.ffmpeg_proxy_portrait_log_path, "w", encoding="utf-8", errors="replace")

        command = self.build_ffmpeg_proxy_command(
            ffmpeg_path,
            portrait_input_url,
            tiktok_output_url,
            log_path=self.ffmpeg_proxy_portrait_sei_log_path,
            # Portrait canvas is vertical; the SEI declares the push
            # dimensions, so report 1080x1920 rather than the landscape
            # default.
            resolution="1080x1920",
        )
        (yield from self._launch_sei_proxy(
            command,
            self.ffmpeg_proxy_portrait_log_file,
            self.ffmpeg_proxy_portrait_log_path,
            self.ffmpeg_proxy_portrait_sei_log_path,
            "ffmpeg_proxy_portrait_process",
        ))

        self.local_portrait_proxy_active = True
        self.set_proxy_status("Dual proxies ready. Start streaming in OBS.")
        # The landscape proxy deferred its display refresh, so this single
        # refresh is what reveals BOTH endpoints' URL/key fields — they
        # populate at the same moment instead of trickling in one after
        # the other.
        self.refresh_stream_credentials_display()
        return True

    def stop_ffmpeg_proxy(self, clear_status=True):
        processes = (
            (self.ffmpeg_proxy_process, self.ffmpeg_proxy_log_file),
            (self.ffmpeg_proxy_portrait_process, self.ffmpeg_proxy_portrait_log_file),
        )
        self.ffmpeg_proxy_process = None
        self.ffmpeg_proxy_portrait_process = None
        self.local_proxy_active = False
        self.local_portrait_proxy_active = False
        self.local_proxy_starting = False
        reports = tuple(self._proxy_error_reports.values())
        self._proxy_error_reports.clear()
        self.ffmpeg_proxy_log_file = None
        self.ffmpeg_proxy_portrait_log_file = None
        cleanup = None
        if any(process is not None or log is not None for process, log in processes) or reports:
            cleanup = threading.Thread(target=reap_processes, args=(processes, reports), daemon=True,
                                       name='proxy-cleanup')
            cleanup.start()
            self._proxy_cleanup_threads = [t for t in self._proxy_cleanup_threads if t.is_alive()]
            self._proxy_cleanup_threads.append(cleanup)

        if clear_status:
            self.set_proxy_status("")
        if hasattr(self, "ffmpeg_proxy_watch_timer"):
            self.ffmpeg_proxy_watch_timer.stop()
        self.refresh_stream_credentials_display()
        return cleanup

    def check_ffmpeg_proxy_health(self):
        if self._foreground_task is not None:
            return  # Startup checks own both listeners until the workflow ends.
        if not self.local_proxy_active and not self.local_portrait_proxy_active:
            self.ffmpeg_proxy_watch_timer.stop()
            return

        primary_name = "landscape" if self.dual_layout_active else "primary"
        checks = (
            (primary_name, self.ffmpeg_proxy_process, getattr(self, "ffmpeg_proxy_sei_log_path", "")),
            ("portrait", self.ffmpeg_proxy_portrait_process, getattr(self, "ffmpeg_proxy_portrait_sei_log_path", "")),
        )
        for endpoint_name, process, sei_log_path in checks:
            if process is None:
                continue
            return_code = process.poll()
            if return_code is None:
                continue

            self.local_proxy_active = False
            self.local_portrait_proxy_active = False
            self.ffmpeg_proxy_watch_timer.stop()
            details = _safe_log_tail(sei_log_path)
            error = self.proxy_failure(
                'ffmpeg_proxy_portrait_process' if endpoint_name == 'portrait' else 'ffmpeg_proxy_process',
                f"The {endpoint_name} FFmpeg proxy stopped with code {return_code}." +
                (f"\n\nProxy log:\n{details}" if details else ''))
            self.set_stream_state(is_live=False)
            self.clear_output_fields()
            self.set_proxy_status(f"{endpoint_name.capitalize()} FFmpeg proxy stopped with code {return_code}.")
            self.refresh_stream_credentials_display()
            self.show_error(error)
            return

    def sync_activity_spinner(self):
        self.activity_spinner.setVisible(bool(self._foreground_task or self._game_tags_loading or
            self.account_info_in_flight or self.device_initialization_in_flight or
            self.realtime_stats_in_flight or self.audience_safety_in_flight))

    def update_stream_controls(self, has_cookies=None):
        busy = self.device_settings_busy()
        self.device_type_combo.setEnabled(not self.device_settings_busy(include_account_refresh=False))
        self.device_settings_button.setEnabled(not busy)
        self.retry_devices_button.setEnabled(not busy)
        if self.studio_import_button is not None:
            self.studio_import_button.setEnabled(not busy)
        self.mobile_broadcast_options.setEnabled(not busy)
        self.login_button.setEnabled(self.device_type == "pc" and self.has_device_identifiers())
        if has_cookies is None:
            has_cookies = self.get_cookie_file_status()[0]

        self.campaigns_button.setEnabled(has_cookies and self.has_device_identifiers())
        self.refresh_account_button.setEnabled(
            has_cookies and self.has_device_identifiers() and not getattr(self, 'account_info_in_flight', False))

        can_start = has_cookies and self.has_device_identifiers() and not self.is_live

        self.go_live_button.setEnabled(can_start)
        self.pause_live_button.setEnabled(self.device_type == "pc" and has_cookies and self.is_live and not self.is_paused)
        self.resume_live_button.setEnabled(self.device_type == "pc" and has_cookies and self.is_live and self.is_paused)
        self.end_live_button.setEnabled(has_cookies and self.is_live)
        self.main_live_status.set_state('paused' if self.is_paused else
                                        'live' if self.is_live else 'offline')
        self.refresh_stats_button.setEnabled(has_cookies and bool(self.current_room_id))
        self.chat_reconnect_button.setEnabled(self.is_live and bool(self.current_room_id))
        if hasattr(self, "refresh_audience_safety_button"):
            self.refresh_audience_safety_button.setEnabled(has_cookies)
        if hasattr(self, "toggle_stream_credentials_button"):
            self.toggle_stream_credentials_button.setEnabled(False)
        if getattr(self, '_foreground_task', None) is not None:
            for control in (self.go_live_button, self.pause_live_button, self.resume_live_button,
                            self.end_live_button, self.login_button, self.campaigns_button,
                            self.refresh_account_button, self.refresh_stats_button,
                            self.refresh_audience_safety_button, self.browse_cookies_button,
                            self.cookies_path_edit):
                control.setEnabled(False)
        else:
            self.browse_cookies_button.setEnabled(True)
            self.cookies_path_edit.setEnabled(True)
        self.sync_activity_spinner()
        self.sync_workspace_actions()
        self.update_account_summary()

    def apply_stream_outputs(self, stream, priority_region="", start_proxy=True, dual_layout=False):
        if dual_layout and not distinct_push_urls(getattr(stream, 'streamUrl', ''), getattr(stream, 'multiStreamUrl', '')):
            raise RuntimeError('Dual Layout requires two distinct push URLs before either proxy can start.')
        self.clear_output_fields()
        # Set after clear_output_fields, which resets dual_layout_active.
        self.dual_layout_active = bool(dual_layout and getattr(stream, "multiStreamUrl", ""))
        self.real_stream_url = getattr(stream, "streamUrl", "")
        self.real_base_stream_url = getattr(stream, "baseStreamUrl", "")
        self.real_stream_key = getattr(stream, "streamKey", "")
        self.real_multi_stream_url = getattr(stream, "multiStreamUrl", "")
        self.real_multi_stream_key = getattr(stream, "multiStreamKey", "")
        self.real_share_url = getattr(stream, "streamShareUrl", "")
        self.current_room_id = getattr(stream, "roomId", "")
        self.current_stream_id = getattr(stream, "streamId", "")
        self.current_anchor_id = getattr(stream, "ownerUserId", "")
        self.active_violation_ids = set()
        self.stream_priority_region = country_code(
            priority_region or getattr(stream, 'priority_region_used', ''))

        self.share_url_output.setText(self.real_share_url)
        self.refresh_stream_credentials_display()

        if start_proxy and (self.real_stream_url or self.real_multi_stream_url):
            try:
                # Dual layout: the primary (existing) endpoint forwards to
                # multi_stream_url (landscape canvas) and the portrait
                # endpoint forwards to the main stream_url (portrait canvas).
                primary_target = self.real_multi_stream_url if self.dual_layout_active else self.real_stream_url
                # Dual layout: the landscape start defers its display
                # refresh; the portrait start's final refresh reveals both
                # endpoints at the same time.
                (yield from self.start_ffmpeg_proxy(primary_target, defer_display=self.dual_layout_active))
                if self.dual_layout_active:
                    (yield from self.start_portrait_ffmpeg_proxy(self.real_stream_url))
            except Exception as exc:
                self.set_stream_state(is_live=False)
                self.clear_output_fields()
                self.set_proxy_status("Local FFmpeg proxy failed to start.")
                self.refresh_stream_credentials_display()
                raise RuntimeError(
                    "Could not start the local FFmpeg proxy:\n\n"
                    f"{exc}"
                ) from exc

        self.sync_realtime_stats_timer()
        self.sync_audience_safety_timer()
        self.sync_chat()

    def changeEvent(self, event):
        # Track activation/minimize to throttle display-only polling. Both
        # event types must be watched: clicking another window fires
        # ActivationChange, minimizing fires WindowStateChange (with no
        # activation event on the way down on some platforms).
        if event.type() in (QEvent.ActivationChange, QEvent.WindowStateChange):
            focused = self.isActiveWindow() and not self.isMinimized()
            if focused != self.app_in_focus:
                self.app_in_focus = focused
                self.sync_polling_focus()
        super().changeEvent(event)

    def sync_polling_focus(self):
        """Re-evaluate poller states after a focus change.

        Unfocused: stats/audience/safety-detail pollers stop, the violation
        monitor slows to UNFOCUSED_VIOLATION_POLL_SECONDS. Refocused: normal
        cadence resumes and one immediate catch-up refresh updates the
        display-only panels so the numbers are current the moment the user
        looks at the app again.
        """
        if self.app_in_focus:
            if self.realtime_stats_timer.isActive():
                self.realtime_stats_timer.setInterval(5000)
            elif ENABLE_STUDIO_STATS_POLLING and self.is_live and self.current_room_id:
                self.sync_realtime_stats_timer()
            self.audience_safety_timer.setInterval(15000)
            if not self.audience_safety_timer.isActive():
                self.sync_audience_safety_timer()
            if self.is_live:
                # Catch-up: refresh the now-visible panels right away
                # instead of waiting out the next (long) interval.
                self.refresh_realtime_stats()
                self.refresh_audience_safety()
        else:
            if self.realtime_stats_timer.isActive():
                self.realtime_stats_timer.stop()
            # QTimer intervals are milliseconds — without the * 1000 this
            # becomes a 60ms timer that, gated only by the in-flight flag,
            # polls violation_list back-to-back (~35 refreshes/min) and
            # burns the RapidAPI hourly rate limit in minutes.
            self.audience_safety_timer.setInterval(UNFOCUSED_VIOLATION_POLL_SECONDS * 1000)
        # The audience-safety worker reads app_in_focus when it runs, to
        # skip the audience/ranklist and create_info/room_info detail calls.
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
        self.sync_chat()
        self.update_stream_controls()

    def clear_chat(self):
        self.chat_output.clear()

    def stop_chat(self):
        self._chat_generation += 1
        client, self.chat_client = self.chat_client, None
        self._chat_identity = None
        if client is not None:
            client.stop()

    def sync_chat(self, force=False):
        if not self.is_live or not self.current_room_id:
            self.stop_chat()
            self.chat_status.setText('LIVE ended' if self._chat_display_room else 'Start a LIVE to read chat')
            return
        identity = (str(self.current_room_id), self.get_cookies_path())
        if not force and self.chat_client is not None and self._chat_identity == identity:
            return
        self.stop_chat()
        if self._chat_display_room != identity[0]:
            self.clear_chat()
            self._chat_displayed_gifts.clear()
            self._chat_displayed_message_ids.clear()
            self._chat_display_room = identity[0]
        self._chat_identity = identity
        generation = self._chat_generation
        # Chat uses the captured Studio web IM protocol even for rooms created
        # with Android. Keep PC chat identity separate from Android stream IDs.
        record = copy.deepcopy(self.saved_device_records().get('pc', {}))
        cookies_path = identity[1]

        def factory():
            return Stream(cookies_path=cookies_path, device_type='pc', device_profile=record)

        def emit(signal, value):
            try:
                signal.emit((generation, value))
            except RuntimeError:
                pass  # Window was destroyed while a request was finishing.

        self.chat_client = LiveChatClient(identity[0], factory, _build_signature_headers,
            lambda messages: emit(self.chat_messages_received, messages),
            lambda status: emit(self.chat_status_changed, status))
        self.chat_status.setText('Connecting…')
        try:
            self.chat_client.start()
        except Exception:
            self.stop_chat()
            self.chat_status.setText('Could not start chat. Use Reconnect to retry.')

    def reconnect_chat(self):
        self.sync_chat(force=True)

    def on_chat_status(self, result):
        generation, status = result
        if generation == self._chat_generation and self.chat_client is not None:
            self.chat_status.setText(status)

    def on_chat_messages(self, result):
        generation, messages = result
        if generation != self._chat_generation or self.chat_client is None:
            return
        scroll = self.chat_output.verticalScrollBar()
        at_bottom = scroll.value() >= scroll.maximum() - 2
        position = scroll.value()
        lines = []
        for message in messages:
            if message.message_id and message.message_id in self._chat_displayed_message_ids:
                continue
            try:
                stamp = datetime.fromtimestamp(message.timestamp).strftime('%H:%M:%S') if message.timestamp else datetime.now().strftime('%H:%M:%S')
            except (ValueError, OverflowError, OSError):
                stamp = datetime.now().strftime('%H:%M:%S')
            name = message.nickname or message.username or message.user_id or 'Viewer'
            if isinstance(message, GiftMessage):
                if not message.completed:
                    continue
                # A manual reconnect replaces the worker while retaining the
                # feed. Remember gifts actually displayed, not worker events
                # that may still be queued for a superseded GUI generation.
                key = message.combo_key or (('message', message.message_id) if message.message_id else None)
                if key is not None:
                    if key in self._chat_displayed_gifts:
                        continue
                    self._chat_displayed_gifts[key] = None
                    if len(self._chat_displayed_gifts) > 2000:
                        self._chat_displayed_gifts.popitem(last=False)
                lines.append(f'[{stamp}] 🎁 {" ".join(name.split())} {" ".join(message.text.split())}')
            else:
                lines.append(f'[{stamp}] {" ".join(name.split())}: {" ".join(message.text.split())}')
            if message.message_id:
                self._chat_displayed_message_ids[message.message_id] = None
                if len(self._chat_displayed_message_ids) > 2000:
                    self._chat_displayed_message_ids.popitem(last=False)
        if lines:
            self.chat_output.appendPlainText('\n'.join(lines))
            scroll.setValue(scroll.maximum() if at_bottom else position)
            self.chat_status.setText('Connected')
            if self.chat_sound_checkbox.isChecked():
                # One system sound per incoming batch; a replay or stale
                # callback must not notify again. Uses Qt on every platform.
                QApplication.beep()

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

        factory = self.stream_factory()
        device_id, install_id = self.device_id, self.install_id

        context = (self.device_type, device_id, install_id, room_id, stream_id, status)

        def worker():
            with factory() as stream:
                return stream.anchorHeartbeat(
                    status, device_id=device_id, install_id=install_id,
                    priority_region=priority_region, room_id=room_id,
                    stream_id=stream_id, action="Anchor heartbeat")

        BackgroundTask(self, Work(worker),
                       lambda payload: self.on_anchor_heartbeat_finished(context, payload),
                       lambda error: self.on_anchor_heartbeat_finished(context, error=error)).start()

    def on_anchor_heartbeat_finished(self, context, payload=None, error=None):
        self.anchor_heartbeat_in_flight = False
        self.update_stream_controls()
        # A request from a finished room must not advance a new room's ping
        # state or accumulate failures against another selected client.
        current = (self.device_type, self.device_id, self.install_id,
                   self.current_room_id, self.current_stream_id)
        if not self.is_live or tuple(context[:5]) != current:
            return
        status = context[5]
        if error is None:
            self.anchor_heartbeat_error_count = 0
            if (status == ANCHOR_STATUS_PREPARE and
                    self.anchor_ping_status == ANCHOR_STATUS_PREPARE and
                    _is_room_is_living_payload(payload)):
                self.anchor_ping_status = ANCHOR_STATUS_LIVING
            return
        label = {
            ANCHOR_STATUS_PREPARE: "Prepare", ANCHOR_STATUS_LIVING: "Live",
            ANCHOR_STATUS_PAUSE: "Paused", ANCHOR_STATUS_FINISH: "Finish",
        }.get(status, "Anchor")
        print(f"{label} heartbeat failed: {error}")
        if _is_already_ended_error(error):
            self.anchor_heartbeat_error_count += 1
            if self.anchor_heartbeat_error_count >= 3:
                self.stream_ended_remotely.emit("TikTok reports that this LIVE has already ended.")
        else:
            self.anchor_heartbeat_error_count = 0

    def handle_stream_ended_remotely(self, message):
        self.set_stream_state(is_live=False)
        self.clear_output_fields()
        if message:
            self.show_info(message)

    def invalidate_account_refresh(self):
        # A monotonically increasing token also distinguishes Android -> PC
        # -> Android from the earlier Android request still running.
        self._account_request_id += 1
        if self._account_request_cancel is not None:
            self._account_request_cancel.set()
        self._account_request_cancel = None
        self.account_refresh_timeout.stop()
        self.account_refresh_timer.stop()
        self.account_info_in_flight = False
        self.account_load_failed = False
        self.refresh_account_button.setText('Refresh Account Info')

    def on_account_info_loaded(self, response):
        request_id, info = response
        if request_id != self._account_request_id or not self.account_info_in_flight:
            return
        if not isinstance(info, dict) or not isinstance(info.get('account', {}), dict):
            self.handle_account_info_error('Account information returned an invalid response.'
                                           if self._account_refresh_show_errors else '')
            return
        self.apply_account_info(info)

    def on_account_info_failed(self, response):
        request_id, message = response
        if request_id != self._account_request_id or not self.account_info_in_flight:
            return
        self.handle_account_info_error(message)

    def on_account_refresh_timeout(self):
        if not self.account_info_in_flight:
            return
        show_errors = self._account_refresh_show_errors
        self.invalidate_account_refresh()
        self.handle_account_info_error(
            'Account information took too long to load. Try Refresh Account Info again.' if show_errors else '')

    def refresh_account_info(self, show_errors=True):
        self.account_refresh_timer.stop()
        if not self.get_cookie_file_status()[0]:
            self.update_account_summary()
            if show_errors:
                self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
            return

        if not self.ensure_device_identifiers(show_popup=show_errors):
            self.update_account_summary()
            return

        if self.account_info_in_flight:
            return
        self._account_request_id += 1
        request_id = self._account_request_id
        cancel = self._account_request_cancel = threading.Event()
        self._account_refresh_show_errors = show_errors
        self.account_info_in_flight = True
        self.account_load_failed = False
        self.account_refresh_timeout.start(ACCOUNT_INFO_TIMEOUT_MS)
        self.update_stream_controls()
        self.refresh_account_button.setText("Refreshing...")
        # No widget/current-profile reads in the worker: switching clients is
        # allowed while this snapshot is loading.
        kind = self.device_type
        record = self.saved_device_records()[kind]
        cookies_path = self.get_cookies_path()
        device_id, install_id = self.device_id, self.install_id
        topic_id = self.get_selected_topic_id() or "5"
        priority_region = self.region_combo.currentText()
        deadline = time.monotonic() + ACCOUNT_INFO_TIMEOUT_MS / 1000

        def worker():
            try:
                with Stream(cookies_path=cookies_path, device_type=kind, device_profile=record) as stream:
                    stream.account_info_deadline = deadline
                    stream.account_info_cancel = cancel
                    info = stream.getAccountInfo(
                        device_id=device_id, install_id=install_id,
                        priority_region=priority_region, last_time_hashtag_id=topic_id,
                    )
            except Exception as exc:
                message = OperationError("Failed to load account info", exc) if show_errors else ""
                try:
                    self.account_info_failed.emit((request_id, message))
                except RuntimeError:
                    pass  # The window was destroyed while the request ran.
            else:
                try:
                    self.account_info_loaded.emit((request_id, info))
                except RuntimeError:
                    pass

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self.on_account_info_failed((request_id, OperationError("Could not start account refresh", exc) if show_errors else ''))

    def apply_account_info(self, info):
        self.account_refresh_timeout.stop()
        self.account_info_in_flight = False
        self.account_load_failed = False
        self.refresh_account_button.setEnabled(True)
        self.refresh_account_button.setText("Refresh Account Info")

        account = info.get("account", {})

        username = account.get("username") or account.get("screen_name") or account.get("name") or "Unknown"
        user_id = account.get("user_id_str") or str(account.get("user_id") or "")

        self.account_username.setText(username)
        # Keep the beginning of the text visible when it overflows the field.
        self.account_username.setCursorPosition(0)
        # Kept as a plain attribute (no longer shown in the UI) for callers
        # that need the anchor id, e.g. realtime stats.
        self.account_user_id_value = user_id
        self.account_status.setText(info.get("status", "Unknown"))
        self.account_can_go_live = bool(info.get("can_go_live", False))
        self.can_go_live_output.setText(str(self.account_can_go_live))

        # Update the cached dual-layout capability. The account is dual-layout
        # ready only when both server gates pass: allow_multi_stream (scene=1,
        # the flag LIVE Studio uses to show the button) AND no new-user
        # sensitive-feature restriction (threshold allowed OR dual_canvas_used,
        # mirroring LIVE Studio's dualEnable = !allowed && !dual_canvas_used).
        allow_dual = info.get("allow_multi_stream_scene1")
        self.dual_layout_supported = None if allow_dual is None else bool(allow_dual and info.get("dual_layout_unlocked"))
        if allow_dual is not None:
            if not self.dual_layout_supported:
                self.dual_layout_checkbox.setChecked(False)
                days_to_reach = info.get("dual_days_to_reach")
                if allow_dual and days_to_reach:
                    self.dual_layout_output.setToolTip(
                        "This account has dual layout access, but it is still locked by the "
                        f"new-user restriction: go LIVE {days_to_reach} more time(s) for 25 "
                        "minutes each on LIVE Studio to unlock it (validation may take up to "
                        "48 hours)."
                    )
                else:
                    self.dual_layout_output.setToolTip(
                        "allow_multi_stream from game/basic/create_info?scene=1 - the same "
                        "account-level flag TikTok LIVE Studio uses to show or hide its dual "
                        "layout button. Updated by Refresh Account Info."
                    )
        self.update_dual_layout_status()

        # The account refresh just made several signed requests, so the
        # quota snapshot on disk is fresh; reflect it immediately instead
        # of waiting for the minute timer.
        self.update_rapidapi_quota_display()
        self.update_stream_controls()

    def handle_account_info_error(self, message):
        self.account_refresh_timeout.stop()
        self.account_info_in_flight = False
        self.account_load_failed = True
        self.refresh_account_button.setEnabled(True)
        self.refresh_account_button.setText("Refresh Account Info")
        self.update_stream_controls()
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
            "device_type": self.device_type,
            "devices": self.saved_device_records(),
            "device_id": self.device_id,
            "install_id": self.install_id,
            "cookies_path": self.get_cookies_path() if hasattr(self, "get_cookies_path") else _configured_cookies_path(),
            "rapidapi_key": self.get_rapidapi_key() if hasattr(self, "get_rapidapi_key") else _configured_rapidapi_key(),
            "suppress_donation_reminder": self.suppress_donation_reminder,
            "dual_layout_supported": self.dual_layout_supported,
            "chat_notification_sound": self.chat_sound_checkbox.isChecked(),
            "ui": {
                **(self._config_extra.get('ui', {}) if isinstance(self._config_extra.get('ui'), dict) else {}),
                "visible_views": [key for key in self.view_actions if key in self.visible_workspace_views],
                "active_view": self.workspace_navigation.currentRouteKey() or 'live',
                "known_views": list(self.view_actions),
            },
        }

        data = {**self._config_extra, **data}
        # CONFIG_PATH is absolute (app data dir); a CWD-relative "config.json"
        # would resolve to "/" for Finder-launched macOS .app bundles.
        # The write is atomic (temp file + os.replace): the SEI proxy child
        # reads config.json from disk on every signing call, and a plain
        # truncate-and-write leaves a window where the child sees a partial
        # file, loses the RapidAPI key, and kills the live proxies.
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp_path = CONFIG_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
            os.replace(tmp_path, CONFIG_PATH)
        except OSError as exc:
            if show_message:
                self.show_error(f"Could not save settings to {CONFIG_PATH}: {exc}")
            return

        if show_message:
            self.show_info("Settings saved.")

    def load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            self.device_id = ""
            self.install_id = ""
            self.cookie_file_path = _normalize_configured_path(DEFAULT_COOKIES_PATH)
            self.rapidapi_key = ""
            self.dual_layout_supported = None
            self.update_dual_layout_status()
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

        self._config_extra = dict(data)
        self.devices = device_records(data)
        self.devices.setdefault('pc', {})
        self.devices.setdefault('mobile', {'device_id': '', 'install_id': ''})
        self.device_type = normalize_device_type(data.get('device_type', 'pc'))
        self.device_type_combo.blockSignals(True)
        self.device_type_combo.setCurrentIndex(1 if self.device_type == 'mobile' else 0)
        self.device_type_combo.blockSignals(False)
        selected = self.devices[self.device_type]
        self.dual_layout_supported = selected.get('dual_layout_supported', data.get('dual_layout_supported') if self.device_type == 'pc' else None)
        self.update_device_mode_controls()
        loaded_device_id = selected.get("device_id", "")
        loaded_install_id = selected.get("install_id", selected.get("iid", ""))
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
        self.dual_layout_supported = selected.get('dual_layout_supported', data.get('dual_layout_supported') if self.device_type == 'pc' else None)
        self.update_dual_layout_status()

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
        self.chat_sound_checkbox.setChecked(data.get('chat_notification_sound') is True)
        self.load_workspace_preferences(data.get('ui', {}))

    def open_donation_url(self):
        QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/loukious"))

    def show_donation_reminder(self):
        if self._foreground_task is not None:
            single_shot(self, 1000, self.show_donation_reminder)
            return
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
        if getattr(self, '_foreground_task', None) is not None:
            single_shot(self, 1000, lambda: self.handle_update_check(update_info))
            return
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

    @foreground('Logging in…', cancellable=True)
    def start_browser_login_flow(self):
        if self.device_type == 'mobile':
            self.show_error('Browser login uses PC identities. Import cookies from your Android session for mobile mode.')
            return
        if not self.ensure_device_identifiers(show_popup=True):
            return

        self.login_button.setEnabled(False)
        # 1. Backup existing protocol registration
        backup = (yield Work(backup_protocol_registry, label='Preparing browser login…'))
        stop_listening = threading.Event()

        # 2. Start local callback server
        server_thread, port, callback_event, result = (yield Work(start_callback_server, stop_event=stop_listening, label='Preparing browser login…'))
        if not server_thread:
            self.show_error("Could not start local callback server.")
            (yield Work(restore_protocol_registry, backup, label='Restoring browser login settings…'))
            self.login_button.setEnabled(True)
            return

        # 3. Register temporary protocol handler. In a frozen/compiled build
        #    (PyInstaller/Nuitka) there is no script file to run — the
        #    executable itself handles --protocol-callback.
        python_exe = sys.executable
        if getattr(sys, "frozen", False):
            script_path = None
        else:
            script_path = os.path.abspath(__file__)
        if not (yield Work(register_temporary_protocol_handler, python_exe, script_path, port, label='Preparing browser login…')):
            stop_listening.set()
            self.show_error(
                "Failed to register the temporary protocol handler.\n"
                "Try running the app as the same user you log in with, and check that "
                "antivirus software is not blocking registry writes."
            )
            (yield Work(restore_protocol_registry, backup, label='Restoring browser login settings…'))
            self.login_button.setEnabled(True)
            return

        client = None
        try:
            client = (yield Work(LiveStudioBrowserLoginClient, self.device_id, self.install_id, label='Preparing login…'))
            if self._foreground_task.cancel_event.is_set():
                return
            state, nonce, ticket = (yield Work(client.prepare_login, label='Logging in…'))
            if self._foreground_task.cancel_event.is_set():
                return
            login_url = _build_onetap_auth_url(state, nonce, ticket)
            (yield Work(webbrowser.open, login_url, label='Logging in…'))

            callback_received = (yield Work(wait_for_login_callback, callback_event, self._foreground_task.cancel_event, timeout=180, label='Complete login in your browser…'))
            if self._foreground_task.cancel_event.is_set():
                return
            if not callback_received or not result["url"]:
                raise RuntimeError(
                    "No login callback was received within 3 minutes. Possible causes:\n"
                    "- The browser blocked the live-studio-app:// redirect (look for a "
                    "confirmation popup in the browser or taskbar and allow it).\n"
                    "- Windows or antivirus prevented the temporary protocol handler "
                    "from launching.\n"
                    "- The login page was closed before completing the flow.\n"
                    "Nothing was modified on your account; you can try again."
                )

            # Parse callback URL (query or fragment)
            print(f"[DEBUG] Received callback URL ({len(result['url'])} chars)")
            parsed = urllib.parse.urlparse(result["url"])
            query_string = parsed.query
            if not query_string and parsed.fragment:
                query_string = parsed.fragment
            query_params = urllib.parse.parse_qs(query_string)

            id_token = query_params.get("id_token", [None])[0]
            state_from_callback = query_params.get("state", [None])[0]

            if not id_token or not state_from_callback:
                raise RuntimeError(
                    "Invalid callback URL: missing id_token or state. "
                    f"Received {len(result['url'])} chars."
                )

            (yield Work(client.exchange_login, id_token, state_from_callback, ticket, label='Logging in…'))
            (yield Work(client.save_cookies, self.get_cookies_path(), label='Logging in…'))
            self.show_info("Login successful! Cookies have been saved.")
            self.check_cookies()
            self.refresh_account_info()

        except Exception as exc:
            self.show_error(OperationError("Login failed", exc))
        finally:
            stop_listening.set()
            if client is not None:
                yield Work(client.close)
            (yield Work(restore_protocol_registry, backup, label='Restoring browser login settings…'))
            self.login_button.setEnabled(True)

    def update_rapidapi_quota_display(self):
        bar = getattr(self, "rapidapi_quota_bar", None)
        if bar is None:
            return
        snapshot = read_quota()

        def to_int(value):
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                return None

        limit = to_int(snapshot.get("limit"))
        remaining = to_int(snapshot.get("remaining"))

        low_quota = False
        if limit and remaining is not None:
            remaining = max(0, min(remaining, limit))
            bar.setRange(0, limit)
            bar.setValue(remaining)
            bar.setFormat(f"{remaining:,} / {limit:,} left")
            low_quota = remaining / limit <= 0.1
        elif remaining is not None:
            # Limit unknown: nothing to measure a bar against.
            bar.setRange(0, 1)
            bar.setValue(1)
            bar.setFormat(f"{remaining:,} left")
        else:
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat("Unknown")

        # Full stylesheet both ways: a chunk-only override would lose the
        # groove/border and render as a hairline again.
        chunk_color = "#d9534f" if low_quota else "palette(highlight)"
        bar.setStyleSheet(
            "QProgressBar {"
            " border: 1px solid palette(mid);"
            " border-radius: 4px;"
            " background: palette(window);"
            " text-align: center;"
            " color: palette(text);"
            "}"
            "QProgressBar::chunk {"
            " border-radius: 3px;"
            f" background: {chunk_color};"
            "}"
        )

        tooltip_parts = [
            part
            for part in (
                quota_reset_at(snapshot),
                quota_updated_at(snapshot),
            )
            if part
        ]
        bar.setToolTip("\n".join(tooltip_parts) or "No RapidAPI usage recorded yet.")

    def update_dual_layout_status(self):
        supported = getattr(self, 'dual_layout_supported', None)
        mobile_camera = (self.device_type != 'mobile' or
                         self.devices.get('mobile', {}).get('broadcast_type', 'video') == 'video')
        field = getattr(self, 'dual_layout_output', None)
        if field is not None:
            field.setText(('Unknown' if supported is None else str(bool(supported)))
                          if mobile_camera else 'Camera LIVE only')
            field.setCursorPosition(0)
        checkbox = getattr(self, 'dual_layout_checkbox', None)
        if checkbox is not None:
            enabled = mobile_camera and supported is True
            checkbox.setEnabled(enabled)
            if not mobile_camera:
                checkbox.setToolTip('Android Dual Layout requires Camera LIVE. Mobile gaming screen capture uses one canvas.')
            elif self.device_type == 'mobile':
                checkbox.setToolTip('Create a Camera LIVE dual room. Landscape uses the secondary endpoint; portrait uses the main endpoint. Requires account unlock checks.')
            else:
                checkbox.setToolTip('Create a dual room with portrait and landscape canvases. Requires account unlock checks.')
            if not enabled:
                checkbox.setChecked(False)

    @foreground('Starting LIVE…')
    def generate_stream(self):
        topic_id = self.get_selected_topic_id()
        if not topic_id:
            self.show_error("Please select a topic.")
            return

        if topic_id == "5" and (self.device_type == "pc" or self.devices.get("mobile", {}).get("broadcast_type") == "screen_record"):
            game_id = self.get_selected_game_id()
            if not game_id:
                self.show_error("Please select a game tag.")
                return
        else:
            game_id = "0"

        if not self.ensure_device_identifiers(show_popup=True):
            return

        if not self.ensure_rapidapi_signer():
            return
        self.save_config(show_message=False)

        stream_started = False
        self.go_live_button.setEnabled(False)
        self.pause_live_button.setEnabled(False)
        self.resume_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)
        self.device_type_combo.setEnabled(False)
        self.device_settings_button.setEnabled(False)
        self.mobile_broadcast_options.setEnabled(False)

        try:
            with (yield Work(self.stream_factory())) as stream:
                selected_region = self.region_combo.currentText()

                create_info_payload = (yield Work(stream.getCreateRoomInfo, device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=selected_region,
                    last_time_hashtag_id=topic_id, label='Starting LIVE…'))
                create_data = create_info_payload.get("data", {}) if isinstance(create_info_payload, dict) else {}
                live_status = create_data.get("live_status")
                last_room_id = create_data.get("last_room_id_str") or str(create_data.get("last_room_id") or "")
                already_live_hint = str(live_status) == "2"

                continuable = (yield Work(stream.getContinuableStreamInfo, device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=selected_region, label='Starting LIVE…'))

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
                        (yield Work(stream.resumeStream, device_id=self.device_id,
                            install_id=self.install_id,
                            priority_region=effective_region,
                            room_id=room_id,
                            stream_id=stream_id, label='Starting LIVE…'))
                        resume_dual = bool(self.dual_layout_checkbox.isChecked() and distinct_push_urls(stream.streamUrl, stream.multiStreamUrl))
                        if self.dual_layout_checkbox.isChecked() and not resume_dual:
                            self.show_info(
                                "Dual Layout was requested, but the resumed room has no landscape "
                                "(multi_stream_url) push URL. Continuing with the main canvas only."
                            )
                        (yield from self.apply_stream_outputs(
                            stream,
                            priority_region=effective_region,
                            dual_layout=resume_dual,
                        ))
                        stream_started = True
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

                        (yield Work(stream.endStream, device_id=self.device_id,
                            install_id=self.install_id,
                            priority_region=effective_region,
                            room_id=room_id,
                            stream_id=stream_id, label='Starting LIVE…'))
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

                dual_layout_requested = self.dual_layout_checkbox.isChecked()

                created = (yield Work(stream.createStream, self.title_edit.text(),
                    topic_id,
                    game_id,
                    self.replay_checkbox.isChecked(),
                    self.close_room_checkbox.isChecked(),
                    self.age_restricted_checkbox.isChecked(),
                    selected_region,
                    self.thumbnail_edit.text(),
                    self.device_id,
                    self.install_id,
                    multi_stream_scene=dual_layout_requested, label='Starting LIVE…'))

                if dual_layout_requested and created and not distinct_push_urls(stream.streamUrl, stream.multiStreamUrl):
                    # The room exists but has no second canvas; end it so the
                    # user is not left with a half-configured live room.
                    try:
                        (yield Work(stream.endStream, device_id=self.device_id,
                            install_id=self.install_id,
                            priority_region=selected_region,
                            room_id=stream.roomId,
                            stream_id=stream.streamId, label='Starting LIVE…'))
                    except Exception:
                        pass
                    self.set_stream_state(is_live=False)
                    self.clear_output_fields()
                    self.show_error(
                        "Dual Layout was requested but TikTok did not return a landscape "
                        "(multi_stream_url) push URL, so this account/room is not allowed "
                        "dual layout. The created room was ended; retry with Dual Layout "
                        "unchecked."
                    )
                    return

                if created:
                    (yield from self.apply_stream_outputs(
                        stream,
                        priority_region=selected_region,
                        dual_layout=dual_layout_requested,
                    ))
                    stream_started = True
                    self.anchor_ping_status = ANCHOR_STATUS_PREPARE
                    self.set_stream_state(is_live=True, is_paused=False)
                    self.start_anchor_ping_loop(ANCHOR_STATUS_PREPARE, send_immediately=True)
                    self.refresh_realtime_stats(force=True)
                    self.refresh_audience_safety(force=True)
                    self.show_info("Stream created successfully. Use the local OBS credentials shown in the output fields.")
        except FileNotFoundError:
            self.show_error("Cookies JSON file not found or invalid. Select a valid cookies JSON file first.")
        except RuntimeError as exc:
            self.show_error(exc)
        except Exception as exc:
            self.show_error(OperationError("Failed to create or resume stream", exc))
        finally:
            if not stream_started:
                self.set_stream_state(is_live=False)
                self.clear_output_fields()

    @foreground('Pausing LIVE…')
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
            with (yield Work(self.stream_factory())) as stream:
                (yield Work(stream.pauseStream, device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    room_id=self.current_room_id,
                    stream_id=self.current_stream_id, label='Pausing LIVE…'))
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
            self.show_error(exc)
        except Exception as exc:
            self.show_error(OperationError("Failed to pause stream", exc))
        finally:
            if not stream_paused:
                self.sync_anchor_heartbeat_timer()
                self.update_stream_controls()

    @foreground('Resuming LIVE…')
    def resume_stream(self):
        if not self.is_live:
            self.show_error("No paused stream to resume. Use Go Live to check for a continuable stream.")
            return
        if not self.is_paused:
            self.show_error("The stream is not paused.")
            return
        if not self.ensure_rapidapi_signer():
            return

        stream_resumed = False
        self.anchor_heartbeat_timer.stop()
        self.pause_live_button.setEnabled(False)
        self.resume_live_button.setEnabled(False)
        self.end_live_button.setEnabled(False)

        try:
            with (yield Work(self.stream_factory())) as stream:
                room_id = self.current_room_id
                stream_id = self.current_stream_id

                if not room_id or not stream_id:
                    if not (yield Work(stream.getContinuableStream, device_id=self.device_id,
                        install_id=self.install_id,
                        priority_region=self.stream_priority_region or self.region_combo.currentText(), label='Resuming LIVE…')):
                        raise RuntimeError("No continuable stream found.")
                    (yield from self.apply_stream_outputs(stream, priority_region=self.region_combo.currentText()))
                    room_id = self.current_room_id
                    stream_id = self.current_stream_id

                (yield Work(stream.resumePausedStream, device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    room_id=room_id,
                    stream_id=stream_id, label='Resuming LIVE…'))
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
                self.show_error(exc)
        except Exception as exc:
            self.show_error(OperationError("Failed to resume stream", exc))
        finally:
            if not stream_resumed:
                self.sync_anchor_heartbeat_timer()
                self.update_stream_controls()

    @foreground('Ending LIVE…')
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
            with (yield Work(self.stream_factory())) as stream:
                if (yield Work(stream.endStream, device_id=self.device_id,
                    install_id=self.install_id,
                    priority_region=self.stream_priority_region or self.region_combo.currentText(),
                    room_id=self.current_room_id,
                    stream_id=self.current_stream_id, label='Ending LIVE…')):
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
                self.show_error(exc)
        except Exception as exc:
            self.show_error(OperationError("Failed to end stream", exc))
        finally:
            if not stream_ended:
                self.sync_anchor_heartbeat_timer()
                self.update_stream_controls()

    def closeEvent(self, event):
        if self._foreground_task is not None:
            # Keep room creation/end and protocol restoration atomic. The
            # window remains responsive, and can close after this operation.
            self._close_after_task = True
            if self._foreground_task.dialog.cancel_callback is not None:
                self._foreground_task.cancel()
            event.ignore()
            return
        self._closing = True
        self.stop_chat()
        self.invalidate_account_refresh()
        if self.settings_dialog.isVisible():
            self.settings_dialog.reject()
        self.stop_ffmpeg_proxy(clear_status=True)
        super().closeEvent(event)



class DeviceSettingsDialog(QDialog):
    """Only the editable server IDs belong in device settings."""
    def __init__(self, kind, record, parent=None):
        super().__init__(parent)
        import copy
        self.kind = kind
        self.record = copy.deepcopy(record)
        self.setWindowTitle('Android device settings' if kind == 'mobile' else 'PC device settings')
        self.setMinimumWidth(440)
        self.resize(480, 340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(TitleLabel('Android device' if kind == 'mobile' else 'PC device'))
        hint = QLabel('Edit the IDs for this installation.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.fields = {}
        for key, title in [('device_id', 'Device ID'), ('install_id', 'Install ID')]:
            label = QLabel(title)
            field = QLineEdit(str(self.record.get(key) or ''))
            field.setPlaceholderText('Created automatically')
            field.setAccessibleName(title)
            field.setMinimumHeight(36)
            label.setBuddy(field)
            self.fields[key] = field
            layout.addWidget(label)
            layout.addWidget(field)
        self.error_label = QLabel('')
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error_label)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = PrimaryPushButton('Save')
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save_record)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        QWidget.setTabOrder(self.fields['device_id'], self.fields['install_id'])
        QWidget.setTabOrder(self.fields['install_id'], self.cancel_button)
        QWidget.setTabOrder(self.cancel_button, self.save_button)
        style_controls(self)

    def collect_record(self):
        import copy
        record = copy.deepcopy(self.record)
        for key, title in [('device_id', 'Device ID'), ('install_id', 'Install ID')]:
            value = self.fields[key].text().strip()
            if value and (not value.isascii() or not value.isdigit() or int(value) == 0):
                self.fields[key].setError(True)
                self.fields[key].setFocus()
                raise ValueError(title + ' must be a nonzero decimal number, or blank to create it again.')
            self.fields[key].setError(False)
            record[key] = value
        return record

    def save_record(self):
        try:
            record = self.collect_record()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.record = record
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.client = None
        self.qr_token = None
        self._qr_generation = 0
        self._qr_busy = False
        self._qr_cancel = threading.Event()
        self.finished.connect(lambda *_: self.cleanup())
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
        from qfluentwidgets import IndeterminateProgressRing
        self.qr_spinner = IndeterminateProgressRing(self)
        self.qr_spinner.setFixedSize(24, 24)
        self.qr_spinner.hide()
        layout.addWidget(self.qr_spinner, alignment=Qt.AlignCenter)

        button_row = QHBoxLayout()

        self.refresh_button = QPushButton("Refresh QR Code")
        self.refresh_button.clicked.connect(self.load_qr_code)
        button_row.addWidget(self.refresh_button)

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
        self._qr_generation += 1
        self._qr_cancel.set()
        client, self.client = self.client, None
        if client is not None and not self._qr_busy:
            threading.Thread(target=client.close, daemon=True).start()

    def _run_qr(self, action, success):
        if self._qr_busy or self.client is None:
            return
        generation, client, cancel = self._qr_generation, self.client, self._qr_cancel
        self._qr_busy = True
        self.qr_spinner.show()
        self.refresh_button.setEnabled(False)
        def work():
            try:
                return action(client)
            finally:
                if cancel.is_set():
                    client.close()
        def finish(result=None, error=None):
            if generation != self._qr_generation:
                return
            self._qr_busy = False
            self.qr_spinner.hide()
            self.refresh_button.setEnabled(True)
            if error is not None:
                self.poll_timer.stop()
                self.status_label.setText('QR login failed: ' + str(error))
            else:
                success(result)
        BackgroundTask(self, Work(work), finish, lambda exc: finish(error=exc)).start()

    def load_qr_code(self):
        if self._qr_busy:
            return
        self.cleanup()
        self._qr_cancel = threading.Event()
        cancel, generation = self._qr_cancel, self._qr_generation
        device_id, install_id = self.parent_window.device_id, self.parent_window.install_id
        self.qr_token = None
        self.qr_label.clear()
        self.qr_label.setText('Loading QR code…')
        self.status_label.setText('Scan with the TikTok app.')
        self._qr_busy = True
        self.qr_spinner.show()
        self.refresh_button.setEnabled(False)
        def load():
            client = LiveStudioBrowserLoginClient(device_id, install_id)
            try:
                return client, client.get_qrcode()
            except Exception:
                client.close()
                raise
            finally:
                if cancel.is_set():
                    client.close()
        def loaded(result):
            if generation != self._qr_generation:
                # Cancellation can arrive after the worker emitted its result.
                threading.Thread(target=result[0].close, daemon=True).start()
                return
            self._qr_busy = False
            self.qr_spinner.hide()
            self.refresh_button.setEnabled(True)
            self.client, qr_data = result
            try:
                pixmap = QPixmap()
                if not pixmap.loadFromData(base64.b64decode(qr_data['qrcode'])):
                    raise RuntimeError('TikTok returned an unreadable QR code.')
                self.qr_token = qr_data['token']
                self.qr_label.setPixmap(pixmap.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.poll_timer.start(2500)
            except Exception as exc:
                self.status_label.setText(str(exc))
        def failed(error):
            if generation == self._qr_generation:
                self._qr_busy = False
                self.qr_spinner.hide()
                self.refresh_button.setEnabled(True)
                self.status_label.setText('QR login failed: ' + str(error))
        BackgroundTask(self, Work(load), loaded, failed).start()

    def poll_qr_status(self):
        if not self.client or not self.qr_token or self._qr_busy:
            return
        token, cookies_path = self.qr_token, self.parent_window.get_cookies_path()
        cancel = self._qr_cancel
        def poll(client):
            payload = client.check_qrconnect(token)
            data = payload.get('data', {})
            status = data.get('status') or data.get('qr_status') or data.get('state')
            if status == 'confirmed':
                expected = getattr(client, 'qr_client_secret', '')
                returned = str(data.get('client_secret') or '')
                if not expected or returned == expected or data.get('client_secret_match'):
                    if not cancel.is_set():
                        client.save_cookies(cookies_path)
            return payload
        self._run_qr(poll, self.on_qr_status)

    def on_qr_status(self, payload):
        data = payload.get('data', {})
        status = data.get('status') or data.get('qr_status') or data.get('state')
        if status == 'new':
            self.status_label.setText('Scan with the TikTok app.')
        elif status == 'scanned':
            self.status_label.setText('Confirm login on your phone.')
        elif status == 'confirmed':
            expected = getattr(self.client, 'qr_client_secret', '')
            if expected and str(data.get('client_secret') or '') != expected and not data.get('client_secret_match'):
                self.status_label.setText('Waiting for the matching login confirmation…')
                return
            self.cleanup()
            self.accept()
            self.parent_window.check_cookies()
            self.parent_window.refresh_account_info()
            self.parent_window.show_info('Login successful! Cookies have been saved.')
        elif status in {'expired', 'timeout'}:
            self.poll_timer.stop()
            self.status_label.setText('QR code expired. Refresh it and try again.')
        elif status:
            self.status_label.setText(f'QR login status: {status}')
        else:
            self.status_label.setText(payload.get('message') or payload.get('status_msg') or str(payload))

    def open_browser_login(self):
        self.cleanup()
        self.accept()
        self.parent_window.start_browser_login_flow()


def handle_protocol_callback(port, url):
    """Send the received URL to the main process via TCP socket."""
    payload = f"URL:{url}".encode()
    last_error = None
    # The main app's listener keeps running after a junk connection, so retry
    # briefly rather than failing on the first refused/failed send.
    for _ in range(3):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", int(port)))
            sock.sendall(payload)
            # Give the listener a moment to drain the payload before closing.
            try:
                sock.shutdown(socket.SHUT_WR)
                sock.recv(64)
            except Exception:
                pass
            sock.close()
            return
        except Exception as e:
            last_error = e
            try:
                sock.close()
            except Exception:
                pass
            time.sleep(0.3)
    print(f"Failed to send callback to main process: {last_error}")


def main():
    if len(sys.argv) == 2 and sys.argv[1] == '--smoke-test':
        from Libs.release_smoke import run
        raise SystemExit(run(log=_release_smoke_log))

    if len(sys.argv) >= 2 and sys.argv[1] == "--sei-proxy":
        log_path = None
        try:
            log_path = os.path.join(_runtime_logs_dir(), "sei_proxy_boot.log")
            with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} child entry argv={sys.argv[1:]}\n")

            from Libs.ffmpeg_sei_proxy import main as sei_proxy_main

            sys.argv = [sys.argv[0], *sys.argv[2:]]
            raise SystemExit(sei_proxy_main())
        except SystemExit:
            raise
        except Exception as exc:
            try:
                if log_path:
                    with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
                        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} child failed: {exc!r}\n")
            except Exception:
                pass
            raise

    # Check if this invocation is for protocol callback
    if len(sys.argv) >= 3 and sys.argv[1] == "--protocol-callback":
        port = sys.argv[2]
        url = sys.argv[3] if len(sys.argv) > 3 else ""
        handle_protocol_callback(port, url)
        return

    # Normal GUI mode
    install_font_diagnostics(os.path.join(_runtime_logs_dir(), 'qt-font-warnings.log'))
    app = QApplication(sys.argv)
    app.setWindowIcon(_application_icon())
    window = StreamKeyGeneratorWindow()
    window.resize(1040, 640)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
