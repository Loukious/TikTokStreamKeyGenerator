import argparse
import json
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from Libs.XFrameSign import frame_sign, frame_sign_batch


def _read_u24_be(data):
    return int.from_bytes(data, "big")


def _write_u24_be(value):
    return int(value).to_bytes(3, "big")


def _sei_size_bytes(value):
    out = bytearray()
    while value >= 255:
        out.append(255)
        value -= 255
    out.append(value)
    return bytes(out)


def _escape_rbsp(data):
    out = bytearray()
    zeros = 0
    for byte in data:
        if zeros >= 2 and byte <= 3:
            out.append(3)
            zeros = 0
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def build_h264_sei100(payload):
    rbsp = _sei_size_bytes(100) + _sei_size_bytes(len(payload)) + payload + b"\x80"
    return b"\x06" + _escape_rbsp(rbsp)


def build_hevc_sei100(payload):
    rbsp = _sei_size_bytes(100) + _sei_size_bytes(len(payload)) + payload + b"\x80"
    return b"\x4e\x01" + _escape_rbsp(rbsp)


def inject_sei_into_tag(tag_data, sei_nals):
    if len(tag_data) < 5:
        return tag_data, False
    if isinstance(sei_nals, (bytes, bytearray)):
        sei_nals = [bytes(sei_nals)]
    packed_sei = b"".join(struct.pack(">I", len(nal)) + nal for nal in sei_nals)

    byte0 = tag_data[0]
    if byte0 & 0x80:
        packet_type = byte0 & 0x0F
        fourcc = tag_data[1:5]
        if fourcc in (b"hvc1", b"hev1") and packet_type in (1, 3):
            offset = 8 if packet_type == 1 else 5
            return tag_data[:offset] + packed_sei + tag_data[offset:], True
    else:
        codec_id = byte0 & 0x0F
        if codec_id == 7 and tag_data[1] == 1:
            return tag_data[:5] + packed_sei + tag_data[5:], True

    return tag_data, False


def _sign_result_summary(value):
    signinfo = str((value or {}).get("signinfo", "") or "") if isinstance(value, dict) else ""
    signvalue = str((value or {}).get("signvalue", "") or "") if isinstance(value, dict) else ""
    return (
        f"frametype={str((value or {}).get('frametype', '') if isinstance(value, dict) else '')} "
        f"lid={str((value or {}).get('lid', '') if isinstance(value, dict) else '')} "
        f"signinfo_len={len(signinfo)} signvalue_len={len(signvalue)} "
        f"blank={not bool(signinfo and signvalue)}"
    )


class LocalSeiSigner:
    def __init__(self, *, uid, device_id, room_id, aid, width, height, log=None):
        self.uid = str(uid or "")
        self.device_id = str(device_id or "")
        self.room_id = str(room_id or "")
        self.aid = str(aid or "8311")
        self.width = int(width)
        self.height = int(height)
        self.log = log
        self.index = -1
        self._last_sign_result = None
        self._last_signed_ms = 0
        self._next_refresh_flv_ts = None
        self._sign_lock = threading.Lock()
        self._sign_refreshing = False
        self._sign_cache = {}
        self._sign_cache_until_ts = 0

    def _log_sign_result(self, source, now_ms, result):
        if self.log is None:
            return
        self.log.write(
            f"[framesign] source={source} ts_s={now_ms // 1000} "
            f"uid_set={bool(self.uid)} did_set={bool(self.device_id)} roomid_set={bool(self.room_id)} "
            f"{_sign_result_summary(result)}\n"
        )
        self.log.flush()

    def _build_sign_input(self, now_ms):
        return {
            "aid": self.aid,
            "uid": self.uid,
            "did": self.device_id,
            "roomid": self.room_id,
            "frametype": "2",
            "timestamp": str(now_ms // 1000),
        }

    def _log_cache(self, message):
        if self.log is not None:
            self.log.write(f"[framesign_cache] {message}\n")
            self.log.flush()

    def _set_sign_result(self, source, now_ms, result):
        with self._sign_lock:
            self._last_sign_result = result
            self._last_signed_ms = now_ms
            self._sign_refreshing = False
        self._log_sign_result(source, now_ms, result)

    def _store_sign_batch(self, source, items):
        stored = 0
        max_ts = 0
        with self._sign_lock:
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                try:
                    timestamp = int(item.get("timestamp", 0))
                except (TypeError, ValueError):
                    continue
                result = item.get("signResult")
                if not isinstance(result, dict):
                    continue
                self._sign_cache[timestamp] = result
                max_ts = max(max_ts, timestamp)
                stored += 1
            if max_ts:
                self._sign_cache_until_ts = max(self._sign_cache_until_ts, max_ts)
            self._sign_refreshing = False
        self._log_cache(f"source={source} stored={stored} cache_until={self._sign_cache_until_ts}")

    def _prefetch_sign_batch(self, start_ts, *, blocking=False, count=10, step_seconds=30):
        with self._sign_lock:
            if self._sign_refreshing:
                return
            self._sign_refreshing = True

        def fetch():
            try:
                base_ms = int(start_ts) * 1000
                items = frame_sign_batch(
                    self._build_sign_input(base_ms),
                    start_timestamp=int(start_ts),
                    count=count,
                    step_seconds=step_seconds,
                    include_startup=True,
                )
                self._store_sign_batch("batch", items)
            except Exception as exc:
                with self._sign_lock:
                    self._sign_refreshing = False
                self._log_cache(f"batch failed error={type(exc).__name__}: {exc}")

        if blocking:
            fetch()
        else:
            threading.Thread(target=fetch, daemon=True).start()

    def _take_cached_sign(self, now_ms):
        now_ts = int(now_ms // 1000)
        with self._sign_lock:
            if not self._sign_cache:
                return None
            candidates = [timestamp for timestamp in self._sign_cache if timestamp <= now_ts]
            if not candidates:
                timestamp = min(self._sign_cache)
            else:
                timestamp = max(candidates)
            result = self._sign_cache.get(timestamp)
            for old_ts in list(self._sign_cache):
                if old_ts < timestamp - 60:
                    self._sign_cache.pop(old_ts, None)
            cache_until = self._sign_cache_until_ts
        if cache_until - now_ts <= 60:
            self._prefetch_sign_batch(cache_until + 30, blocking=False)
        return result

    def _refresh_sign_result_background(self, now_ms):
        cached = self._take_cached_sign(now_ms)
        if cached is not None:
            self._set_sign_result("signed_payload_cache", now_ms, cached)
            return

        self._prefetch_sign_batch(now_ms // 1000, blocking=False)

    def _current_sign_result(self):
        with self._sign_lock:
            return self._last_sign_result, self._last_signed_ms

    def has_sign_result(self):
        with self._sign_lock:
            return self._last_sign_result is not None or bool(self._sign_cache)

    def start_initial_prefetch(self):
        self._prefetch_sign_batch(int(time.time()), blocking=True)

    def _next_index(self):
        self.index += 1
        return self.index

    def signed_payload(self, now_ms=None, refresh_signature=True):
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        sign_result, signed_ms = self._current_sign_result()
        if sign_result is None:
            self._prefetch_sign_batch(now_ms // 1000, blocking=True)
            sign_result = self._take_cached_sign(now_ms)
            if sign_result is None:
                sign_result = frame_sign(self._build_sign_input(now_ms))
            self._set_sign_result("signed_payload_initial", now_ms, sign_result)
            signed_ms = now_ms
        elif refresh_signature:
            self._refresh_sign_result_background(now_ms)
        value = {
            "live_sei_game_moment": {"timestamp": now_ms},
            "live_sei_mute_mic": {"is_mute_mic": 0},
            "push_video_height": self.height,
            "push_video_width": self.width,
            "sei_index": self._next_index(),
            "signResult": sign_result,
            "ts": str(now_ms),
            "ttls_live_scene": "live_studio",
        }
        return b"JSON" + json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def startup_signed_payload(self, now_ms=None):
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        sign_result, _ = self._current_sign_result()
        if sign_result is None:
            self._prefetch_sign_batch(now_ms // 1000, blocking=True)
            sign_result = self._take_cached_sign(now_ms)
            if sign_result is None:
                sign_result = frame_sign(self._build_sign_input(now_ms))
            self._set_sign_result("startup", now_ms, sign_result)
        value = {
            "live_sei_mute_mic": {"is_mute_mic": 0},
            "push_video_height": self.height,
            "push_video_width": self.width,
            "sei_index": self._next_index(),
            "signResult": sign_result,
            "ttls_live_scene": "live_studio",
        }
        return b"JSON" + json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def reused_signed_payload(self):
        _, signed_ms = self._current_sign_result()
        return self.signed_payload(now_ms=signed_ms or int(time.time() * 1000), refresh_signature=False)

    def small_payload(self, now_ms=None):
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        value = {
            "sei_index": self._next_index(),
            "video_e2e_delay": {
                "capture_window": now_ms,
                "encode": now_ms + 110,
            },
        }
        return b"JSON" + json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def payload(self):
        return self.signed_payload(refresh_signature=True)

    def should_refresh_signature(self, flv_timestamp, interval_ms=30000):
        if self._last_sign_result is None:
            self._next_refresh_flv_ts = int(flv_timestamp) + interval_ms
            return True
        if self._next_refresh_flv_ts is None:
            self._next_refresh_flv_ts = int(flv_timestamp) + interval_ms
            return False
        if self._next_refresh_flv_ts is not None and int(flv_timestamp) >= self._next_refresh_flv_ts:
            while int(flv_timestamp) >= self._next_refresh_flv_ts:
                self._next_refresh_flv_ts += interval_ms
            return True
        return False


class StudioSeiPacer:
    """
    Observed official cadence:
    startup signed + small at the first video timestamp, then a repeating
    two-second cycle of signed + small on the boundary plus two more signed
    messages inside the same window.
    """

    OFFSETS_MS = (0, 0, 16, 700, 1000)
    KINDS = ("signed_reuse", "small", "signed_new", "signed_reuse", "signed_new")

    def __init__(self):
        self.base_timestamp = None
        self.next_slot = 0
        self.startup_done = False

    def due(self, flv_timestamp):
        if self.base_timestamp is None:
            self.base_timestamp = flv_timestamp

        elapsed = max(0, int(flv_timestamp) - self.base_timestamp)
        due = []
        while True:
            cycle = self.next_slot // len(self.OFFSETS_MS)
            offset = self.OFFSETS_MS[self.next_slot % len(self.OFFSETS_MS)]
            target = cycle * 2000 + offset
            if elapsed < target:
                break
            kind = self.KINDS[self.next_slot % len(self.KINDS)]
            if kind.startswith("signed") and not self.startup_done:
                kind = "startup"
                self.startup_done = True
            due.append(kind)
            self.next_slot += 1
        return due


def bind_listen_url(url):
    return str(url).replace("rtmp://127.0.0.1:", "rtmp://0.0.0.0:").replace("rtmp://localhost:", "rtmp://0.0.0.0:")


def ffmpeg_listen_cmd(ffmpeg, listen_url, timeout):
    listen_timeout = max(1, int(timeout))
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "info",
        "-stats_period",
        "5",
        "-listen",
        "1",
        "-timeout",
        str(listen_timeout),
        "-i",
        bind_listen_url(listen_url),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-bsf:v",
        "filter_units=remove_types=6",
        "-map_metadata",
        "-1",
        "-f",
        "flv",
        "pipe:1",
    ]


def ffmpeg_push_cmd(ffmpeg, output_url):
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "info",
        "-stats_period",
        "5",
        "-f",
        "flv",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-f",
        "flv",
        output_url,
    ]


def pump_stderr(name, proc, log):
    for raw in proc.stderr:
        line = raw.decode("utf-8", errors="replace")
        log.write(f"[{name}] {line}")
        log.flush()


def inject_stream(src, dst, signer, fps, log):
    pacer = StudioSeiPacer()
    video_tags = 0
    injected = 0
    signed = 0
    small = 0

    header = src.read(9)
    if len(header) < 9:
        raise RuntimeError("No FLV header from local RTMP input.")
    try:
        dst.write(header)
    except (BrokenPipeError, OSError) as exc:
        log.write(f"[sei] output closed while writing FLV header: {exc}\n")
        log.flush()
        return
    previous_size = src.read(4)
    if len(previous_size) == 4:
        try:
            dst.write(previous_size)
        except (BrokenPipeError, OSError) as exc:
            log.write(f"[sei] output closed while writing FLV previous tag size: {exc}\n")
            log.flush()
            return

    while True:
        tag_header = src.read(11)
        if len(tag_header) < 11:
            break
        data_size = _read_u24_be(tag_header[1:4])
        tag_data = src.read(data_size)
        src.read(4)
        if len(tag_data) < data_size:
            break

        out_data = tag_data
        if tag_header[0] == 9:
            video_tags += 1
            timestamp = int.from_bytes(tag_header[7:8] + tag_header[4:7], "big")
            due = pacer.due(timestamp)
            if due:
                hevc = bool(tag_data and (tag_data[0] & 0x80))
                nals = []
                for kind in due:
                    now_ms = int(time.time() * 1000)
                    if kind == "startup":
                        payload = signer.startup_signed_payload(now_ms=now_ms)
                        signed += 1
                    elif kind == "small":
                        payload = signer.small_payload(now_ms=now_ms)
                        small += 1
                    elif kind == "signed_reuse":
                        payload = signer.reused_signed_payload()
                        signed += 1
                    else:
                        refresh = signer.should_refresh_signature(timestamp)
                        payload = signer.signed_payload(
                            now_ms=now_ms,
                            refresh_signature=refresh,
                        )
                        signed += 1
                    nals.append(build_hevc_sei100(payload) if hevc else build_h264_sei100(payload))

                out_data, ok = inject_sei_into_tag(tag_data, nals)
                if ok:
                    injected += len(nals)
                    if injected <= 8 or injected % 60 == 0:
                        log.write(
                            f"[sei] injected total={injected} signed={signed} small={small} "
                            f"video_tag={video_tags} flv_ts={timestamp} kinds={','.join(due)}\n"
                        )
                        log.flush()

        try:
            dst.write(tag_header[:1] + _write_u24_be(len(out_data)) + tag_header[4:])
            dst.write(out_data)
            dst.write(struct.pack(">I", len(out_data) + 11))
            dst.flush()
        except (BrokenPipeError, OSError) as exc:
            log.write(f"[sei] output closed while writing FLV tag: {exc}\n")
            log.flush()
            break

    log.write(f"[sei] finished video_tags={video_tags} injected={injected} signed={signed} small={small}\n")
    log.flush()


def _terminate_process(proc):
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


def _relay_once(args, signer, log):
    listen_proc = None
    input_stream = sys.stdin.buffer
    if args.input_flv == "listen":
        listen_proc = subprocess.Popen(
            ffmpeg_listen_cmd(args.ffmpeg, args.listen_url, args.timeout),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        input_stream = listen_proc.stdout

    push_proc = subprocess.Popen(
        ffmpeg_push_cmd(args.ffmpeg, args.output_url),
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if listen_proc is not None:
        threading.Thread(target=pump_stderr, args=("listen", listen_proc, log), daemon=True).start()
    threading.Thread(target=pump_stderr, args=("push", push_proc, log), daemon=True).start()

    try:
        inject_stream(input_stream, push_proc.stdin, signer, args.fps, log)
    finally:
        _terminate_process(listen_proc)
        _terminate_process(push_proc)

    listen_code = listen_proc.wait() if listen_proc is not None else 0
    push_code = push_proc.wait()
    return push_code or listen_code or 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--input-flv", choices=("listen", "pipe"), default="listen")
    parser.add_argument("--listen-url", default="")
    parser.add_argument("--output-url", required=True)
    parser.add_argument("--uid", default="")
    parser.add_argument("--device-id", default="")
    parser.add_argument("--room-id", default="")
    parser.add_argument("--aid", default="8311")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--log", default="")
    args = parser.parse_args()

    if args.input_flv == "listen" and not args.listen_url:
        parser.error("--listen-url is required when --input-flv=listen")

    width, height = args.resolution.lower().replace("*", "x").split("x", 1)
    args.width = int(width)
    args.height = int(height)
    log_path = Path(args.log) if args.log else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("w", encoding="utf-8", errors="replace")
    else:
        log = sys.stderr
    signer = LocalSeiSigner(
        uid=args.uid,
        device_id=args.device_id,
        room_id=args.room_id,
        aid=args.aid,
        width=args.width,
        height=args.height,
        log=log,
    )
    signer.start_initial_prefetch()

    try:
        if args.input_flv == "pipe":
            return _relay_once(args, signer, log)

        attempt = 0
        while True:
            attempt += 1
            log.write(f"[proxy] waiting for OBS/local RTMP connection attempt={attempt}\n")
            log.flush()
            code = _relay_once(args, signer, log)
            log.write(f"[proxy] local RTMP session ended code={code}; reopening listener\n")
            log.flush()
            time.sleep(1)
    finally:
        if log is not sys.stderr:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
