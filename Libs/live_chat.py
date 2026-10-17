"""Read-only Studio Webcast IM transport and the small protobuf subset it uses.

Wire fields were checked against LIVE Studio's bundled IM definitions and the
local Charles captures. No comment publishing or moderation endpoints are used.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import gzip
import io
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit, quote

import requests
from websockets.sync.client import connect

from Libs.domain_routing import attach_webcast_ntp_t0, get_synced_unix_seconds, update_ntp_from_response

MAX_PACKET_BYTES = 8 * 1024 * 1024
WS_PATH = '/webcast/im/ws_proxy/ws_reuse_supplement/'


class ChatProtocolError(ValueError):
    pass


def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ChatProtocolError('Truncated protobuf integer')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if value >= 1 << 64:
                break
            return value, offset
    raise ChatProtocolError('Invalid protobuf integer')


def fields(data):
    """Return repeated wire values, skipping unknown fixed-width fields."""
    if len(data) > MAX_PACKET_BYTES:
        raise ChatProtocolError('Chat packet is too large')
    result = {}
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ChatProtocolError('Invalid protobuf field')
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, offset = _varint(data, offset)
            else:
                size = 8 if wire == 1 else 4
            if offset + size > len(data):
                raise ChatProtocolError('Truncated protobuf field')
            value, offset = data[offset:offset + size], offset + size
        else:
            raise ChatProtocolError('Unsupported protobuf wire type')
        result.setdefault(number, []).append(value)
    return result


def _value(record, key, default=b''):
    return record.get(key, [default])[-1]


def _text(record, key):
    value = _value(record, key)
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else ''


def _integer(record, key):
    value = _value(record, key, 0)
    return value if isinstance(value, int) else 0


def _encode_varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _bytes_field(number, data):
    return _encode_varint((number << 3) | 2) + _encode_varint(len(data)) + data


def heartbeat_frame():
    return _bytes_field(7, b'hb')


def ack_frame(log_id, internal_ext):
    return (_encode_varint(2 << 3) + _encode_varint(log_id) +
            _bytes_field(7, b'ack') + _bytes_field(8, internal_ext.encode('utf-8')))


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    user_id: str
    nickname: str
    username: str
    text: str
    timestamp: int
    room_id: str


@dataclass(frozen=True)
class GiftMessage:
    message_id: str
    user_id: str
    nickname: str
    username: str
    timestamp: int
    room_id: str
    gift_id: str
    gift_name: str
    gift_type: int
    quantity: int
    repeat_end: bool
    group_id: str
    group_count: int

    @property
    def completed(self):
        # LIVE Studio GiftService pushes gifts into the chat buffer on
        # repeatEnd OR type BIG(2), FACE_RECOGNITION(4), MUSIC_GIFT(22).
        return self.repeat_end or self.gift_type in (2, 4, 22)

    @property
    def combo_key(self):
        # Studio GiftService.handleMsgGiftSmall uses giftId, sender id,
        # groupId and groupCount. Never merge groups using an absent ID.
        if self.gift_type == 1 and self.gift_id and self.user_id and self.group_id:
            return (self.gift_id, self.user_id, self.group_id, self.group_count)
        return None

    @property
    def text(self):
        label = self.gift_name or (f'Gift #{self.gift_id}' if self.gift_id else 'a gift')
        count = f' ×{self.quantity}' if self.quantity > 0 else ''
        return f'sent {label}{count}'


@dataclass
class ChatBatch:
    messages: list
    cursor: str = ''
    internal_ext: str = ''
    heartbeat_ms: int = 0
    need_ack: bool = False
    push_server: str = ''
    route_params: dict = field(default_factory=dict)
    ack: bytes = None
    closed: bool = False


def decode_response(data):
    response = fields(data)
    messages = []
    for raw in response.get(1, []):
        try:
            envelope = fields(raw)
            method = _text(envelope, 1)
            if method not in ('ChatMessage', 'WebcastChatMessage', 'GiftMessage', 'WebcastGiftMessage'):
                continue
            payload = fields(_value(envelope, 2))
            common = fields(_value(payload, 1))
            message_id = _integer(envelope, 3) or _integer(common, 2)
            if method in ('GiftMessage', 'WebcastGiftMessage'):
                user = fields(_value(payload, 7))
                gift = fields(_value(payload, 15))
                gift_id = _integer(payload, 2) or _integer(gift, 5)
                group_id = _integer(payload, 11)
                messages.append(GiftMessage(
                    str(message_id) if message_id else '', str(_integer(user, 1) or ''),
                    _text(user, 3)[:100], _text(user, 38)[:100],
                    _integer(common, 4), str(_integer(common, 3) or ''),
                    str(gift_id) if gift_id else '', _text(gift, 16)[:200], _integer(gift, 11),
                    _integer(payload, 5), bool(_integer(payload, 9)),
                    str(group_id) if group_id else '', _integer(payload, 4),
                ))
                continue
            user = fields(_value(payload, 2))
            text = _text(payload, 3)
            if not text:
                continue
            messages.append(ChatMessage(
                str(message_id) if message_id else '', str(_integer(user, 1) or ''),
                _text(user, 3)[:100], _text(user, 38)[:100], text[:4096],
                _integer(common, 4), str(_integer(common, 3) or ''),
            ))
        except (ChatProtocolError, TypeError):
            # A malformed message must not hide other events in the batch.
            continue
    routes = {}
    for raw in response.get(7, []):
        entry = fields(raw)
        routes[_text(entry, 1)] = _text(entry, 2)
    return ChatBatch(messages, _text(response, 2), _text(response, 5),
                     _integer(response, 8), bool(_integer(response, 9)),
                     _text(response, 10), routes)


def decode_push(data):
    frame = fields(data)
    kind = _text(frame, 7)
    if kind in ('hb', 'ack'):
        return ChatBatch([])
    if kind == 'close':
        return ChatBatch([], closed=True)
    if kind != 'msg':
        return ChatBatch([])
    headers = {}
    for raw in frame.get(5, []):
        item = fields(raw)
        headers[_text(item, 1)] = _text(item, 2)
    payload = _value(frame, 8)
    if not isinstance(payload, bytes):
        raise ChatProtocolError('Invalid chat payload')
    if headers.get('compress_type') == 'gzip' or _text(frame, 6) == 'gzip':
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as zipped:
                payload = zipped.read(MAX_PACKET_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise ChatProtocolError('Invalid compressed chat payload') from exc
    batch = decode_response(payload)
    batch.cursor = headers.get('im_cursor') or batch.cursor
    if batch.need_ack:
        batch.ack = ack_frame(_integer(frame, 2), batch.internal_ext)
    return batch


def socket_url(push_server, params):
    """Use only TikTok Webcast websocket hosts supplied by the bootstrap."""
    parsed = urlsplit(push_server)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'wss' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not host.startswith('webcast')
            or not any(host.endswith('.' + suffix) for suffix in ('tiktokv.com', 'tiktokv.us', 'tiktokv.eu'))
            or parsed.path.rstrip('/') != WS_PATH.rstrip('/')):
        raise ChatProtocolError('Invalid chat server in connection details')
    return urlunsplit(('wss', parsed.netloc, parsed.path,
                      urlencode(params, quote_via=quote), ''))


def studio_params(room_id, device_id, browser_version, timezone_name='Africa/Tunis'):
    return {
        'aid': '8311', 'app_language': 'en', 'app_name': 'tiktok_live_studio',
        'browser_language': 'en-US', 'browser_name': 'Mozilla', 'browser_online': 'true',
        'browser_platform': 'Win32', 'browser_version': browser_version, 'channel': 'studio',
        'cookie_enabled': 'true', 'cursor': '', 'debug': 'false', 'device_id': str(device_id or '0'),
        'device_platform': 'web', 'did_rule': '0', 'fetch_rule': '1', 'force_https': 'false',
        'history_comment_cursor': '', 'host': 'https://webcast.tiktokv.com', 'identity': 'anchor',
        'internal_ext': '', 'last_rtt': '0', 'live_id': '12', 'resp_content_type': 'protobuf',
        'room_id': str(room_id), 'screen_height': '1080', 'screen_width': '1920',
        'sup_ws_ds_opt': '1', 'tz_name': timezone_name, 'version_code': '300400',
    }


class LiveChatClient:
    """One cancellable worker per room; callbacks must marshal to the GUI thread.

    Uses Studio's web IM transport for PC and Android-created LIVE rooms. The
    factory supplies an independent Studio session with the selected account's
    cookies and PC profile. It never changes the room's streaming client mode.
    """
    def __init__(self, room_id, stream_factory, signature_builder, on_messages, on_status, *,
                 connector=connect, clock=time.monotonic, retry_delays=(1, 2, 4, 8, 15, 30)):
        self.room_id = str(room_id)
        self.stream_factory = stream_factory
        self.signature_builder = signature_builder
        self.on_messages = on_messages
        self.on_status = on_status
        self.connector = connector
        self.clock = clock
        self.retry_delays = retry_delays
        self._stop = threading.Event()
        self._socket = None
        self._socket_lock = threading.Lock()
        self._thread = None
        self._seen = OrderedDict()
        self._finished_gift_combos = OrderedDict()
        self.cursor = ''
        self.internal_ext = ''

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='live-chat', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._socket_lock:
            ws = self._socket
        if ws is not None:
            # Abort the underlying socket so shutdown doesn't block the GUI on
            # a websocket close handshake; recv/worker closes its session next.
            try:
                ws.close_socket()
            except Exception:
                pass

    def _deliver(self, batch):
        if self._stop.is_set():
            return
        self.cursor = batch.cursor or self.cursor
        self.internal_ext = batch.internal_ext or self.internal_ext
        fresh = []
        for message in batch.messages:
            if message.room_id and message.room_id != self.room_id:
                continue
            if isinstance(message, GiftMessage):
                if not message.completed:
                    continue
                if message.combo_key is not None and message.combo_key in self._finished_gift_combos:
                    continue
            if message.message_id:
                if message.message_id in self._seen:
                    continue
                self._seen[message.message_id] = None
                if len(self._seen) > 2000:
                    self._seen.popitem(last=False)
            if isinstance(message, GiftMessage) and message.combo_key is not None:
                self._finished_gift_combos[message.combo_key] = None
                if len(self._finished_gift_combos) > 2000:
                    self._finished_gift_combos.popitem(last=False)
            fresh.append(message)
        if fresh:
            self.on_messages(fresh)

    def _bootstrap(self, stream, params):
        # Preserve cursor on reconnect to recover comments missed during a drop.
        params.update(cursor=self.cursor, internal_ext=self.internal_ext)
        base = stream.getServerUrl().rstrip('/') + '/webcast/im/fetch/'
        candidates = stream._webcast_candidate_urls(base)
        for index, candidate in enumerate(candidates):
            if self._stop.is_set():
                raise InterruptedError()
            query = urlencode(params, quote_via=quote)
            headers = {'accept': '*/*', 'pragma': 'no-cache', 'cache-control': 'no-cache',
                       **self.signature_builder(get_synced_unix_seconds(), '8311', params=query)}
            t0 = attach_webcast_ntp_t0(headers)
            response = stream.s.get(candidate + '?' + query, headers=headers,
                                    timeout=12, allow_redirects=False)
            update_ntp_from_response(t0, response)
            if response.status_code != 200:
                if index + 1 < len(candidates) and response.status_code in (403, 404, 421, 500, 502, 503, 504):
                    continue
                raise ChatProtocolError(f'Chat connection returned HTTP {response.status_code}')
            batch = decode_response(response.content)
            if not batch.push_server or not (batch.route_params or {}).get('wrss'):
                raise ChatProtocolError('Chat connection details are unavailable')
            return batch
        raise ChatProtocolError('Chat server is unavailable')

    def _run(self):
        failures = 0
        while not self._stop.is_set():
            opened_at = None
            try:
                self.on_status('Connecting…')
                with self.stream_factory() as stream:
                    _, browser = stream._apply_live_studio_headers()
                    record = stream.client.record
                    params = studio_params(self.room_id, record.get('device_id'), browser,
                                           record.get('fingerprint', {}).get('timezone_name', 'Africa/Tunis'))
                    bootstrap = self._bootstrap(stream, params)
                    self._deliver(bootstrap)
                    if self._stop.is_set():
                        break
                    params.update(cursor=self.cursor, internal_ext=self.internal_ext, compress='gzip',
                                  heartbeatDuration='0', imprp='', update_version_code='1.3.0',
                                  webcast_sdk_version='1.3.0')
                    for key in ('resp_content_type', 'fetch_rule', 'history_comment_cursor', 'last_rtt'):
                        params.pop(key, None)
                    # Only routing tokens, never arbitrary bootstrap overrides.
                    params['wrss'] = bootstrap.route_params['wrss']
                    url = socket_url(bootstrap.push_server, params)
                    jar = getattr(stream.s.cookies, 'jar', stream.s.cookies)
                    cookie_request = requests.Request('GET', url.replace('wss://', 'https://', 1)).prepare()
                    cookie = requests.cookies.get_cookie_header(jar, cookie_request)
                    headers = {'Pragma': 'no-cache', 'Cache-Control': 'no-cache', 'Accept-Language': 'en-US'}
                    if cookie:
                        headers['Cookie'] = cookie
                    with self.connector(url, additional_headers=headers, origin='file://',
                                        user_agent_header=stream.s.headers.get('user-agent'),
                                        open_timeout=10, close_timeout=1, max_size=MAX_PACKET_BYTES,
                                        ping_interval=None) as ws:
                        with self._socket_lock:
                            self._socket = ws
                        if self._stop.is_set():
                            break
                        opened_at = self.clock()
                        self.on_status('Connected · Waiting for messages')
                        heartbeat = max(5, min(60, (bootstrap.heartbeat_ms or 10000) / 1000))
                        next_heartbeat, last_received = 0, self.clock()
                        while not self._stop.is_set():
                            now = self.clock()
                            if now >= next_heartbeat:
                                ws.send(heartbeat_frame())
                                next_heartbeat = now + heartbeat
                            try:
                                packet = ws.recv(timeout=1)
                            except TimeoutError:
                                if self.clock() - last_received > max(45, heartbeat * 3):
                                    raise TimeoutError('Chat connection stopped responding')
                                continue
                            last_received = self.clock()
                            if not isinstance(packet, bytes):
                                continue
                            batch = decode_push(packet)
                            if batch.closed:
                                raise ConnectionError('Chat server closed the connection')
                            if batch.ack is not None:
                                ws.send(batch.ack)
                            self._deliver(batch)
            except Exception as exc:
                if self._stop.is_set():
                    break
                # Do not expose websocket URLs, tokens or server response bodies
                # through exception strings in the GUI.
                reason = str(exc) if isinstance(exc, ChatProtocolError) else type(exc).__name__
                if opened_at is not None and self.clock() - opened_at >= 30:
                    failures = 0
                delay = self.retry_delays[min(failures, len(self.retry_delays) - 1)]
                failures += 1
                self.on_status(f'Reconnecting in {delay}s · {reason}')
                if self._stop.wait(delay):
                    break
            finally:
                with self._socket_lock:
                    self._socket = None
