import argparse
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Production SEI signatures are obtained from the hosted RapidAPI signer.
# Local-only testing note: in a source checkout, temporarily change this to
# `from DevTools.XFrameSign import frame_sign`. Do not include that development
# module in a production build.
from Libs.XFrameSign import frame_sign


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


def video_tag_accepts_sei(tag_data):
    if len(tag_data) < 5:
        return False
    byte0 = tag_data[0]
    if byte0 & 0x80:
        packet_type = byte0 & 0x0F
        fourcc = tag_data[1:5]
        return fourcc in (b"hvc1", b"hev1") and packet_type in (1, 3)
    return (byte0 & 0x0F) == 7 and len(tag_data) >= 2 and tag_data[1] == 1


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

    def _refresh_sign_result(self, now_ms, source):
        with self._sign_lock:
            if self._sign_refreshing:
                return None
            self._sign_refreshing = True

        def refresh():
            try:
                sign_result = frame_sign(self._build_sign_input(now_ms))
                self._set_sign_result(source, now_ms, sign_result)
            except Exception as exc:
                with self._sign_lock:
                    self._sign_refreshing = False
                self._log_cache(f"direct failed error={type(exc).__name__}: {exc}")

        return refresh

    def _refresh_sign_result_background(self, now_ms):
        refresh = self._refresh_sign_result(now_ms, "signed_payload_direct")
        if refresh is not None:
            threading.Thread(target=refresh, daemon=True).start()

    def _current_sign_result(self):
        with self._sign_lock:
            return self._last_sign_result, self._last_signed_ms

    def has_sign_result(self):
        with self._sign_lock:
            return self._last_sign_result is not None

    def start_initial_prefetch(self):
        refresh = self._refresh_sign_result(int(time.time() * 1000), "startup_direct")
        if refresh is not None:
            refresh()

    def _next_index(self):
        self.index += 1
        return self.index

    def signed_payload(self, now_ms=None, refresh_signature=True):
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        sign_result, signed_ms = self._current_sign_result()
        if sign_result is None:
            sign_result = frame_sign(self._build_sign_input(now_ms))
            self._set_sign_result("signed_payload_initial_direct", now_ms, sign_result)
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
    Cadence used by the standalone mirror: startup signed + small, followed by
    signed and small messages distributed through a repeating two-second cycle.
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
    return str(url)


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


class TeeOutput:
    def __init__(self, primary, dump_file, log):
        self.primary = primary
        self.dump_file = dump_file
        self.log = log

    def write(self, data):
        self.primary.write(data)
        if self.dump_file is None:
            return
        try:
            self.dump_file.write(data)
        except OSError as exc:
            self.log.write(f"[dump] disabled after write failure: {exc}\n")
            self.log.flush()
            try:
                self.dump_file.close()
            except Exception:
                pass
            self.dump_file = None

    def flush(self):
        self.primary.flush()
        if self.dump_file is not None:
            try:
                self.dump_file.flush()
            except OSError as exc:
                self.log.write(f"[dump] disabled after flush failure: {exc}\n")
                self.log.flush()
                try:
                    self.dump_file.close()
                except Exception:
                    pass
                self.dump_file = None


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
            due = pacer.due(timestamp) if video_tag_accepts_sei(tag_data) else []
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


def _subprocess_creationflags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _unique_dump_path(path):
    dump_path = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    nonce = f"{os.getpid()}-{time.time_ns() % 1000000:06d}"
    return dump_path.with_name(f"{dump_path.stem}.{stamp}.{nonce}{dump_path.suffix or '.flv'}")


def _relay_once(args, signer, log):
    listen_proc = None
    dump_file = None
    input_stream = sys.stdin.buffer
    if args.input_flv == "listen":
        listen_proc = subprocess.Popen(
            ffmpeg_listen_cmd(args.ffmpeg, args.listen_url, args.timeout),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_subprocess_creationflags(),
        )
        input_stream = listen_proc.stdout

    push_proc = subprocess.Popen(
        ffmpeg_push_cmd(args.ffmpeg, args.output_url),
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_subprocess_creationflags(),
    )
    if listen_proc is not None:
        threading.Thread(target=pump_stderr, args=("listen", listen_proc, log), daemon=True).start()
    threading.Thread(target=pump_stderr, args=("push", push_proc, log), daemon=True).start()

    try:
        output_stream = push_proc.stdin
        if args.dump_output_flv:
            dump_path = _unique_dump_path(args.dump_output_flv)
            dump_path.parent.mkdir(parents=True, exist_ok=True)
            dump_file = dump_path.open("wb")
            log.write(f"[dump] writing post-SEI outbound FLV to {dump_path}\n")
            log.flush()
            output_stream = TeeOutput(output_stream, dump_file, log)
        inject_stream(input_stream, output_stream, signer, args.fps, log)
    finally:
        if dump_file is not None:
            try:
                dump_file.close()
            except Exception:
                pass
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
    parser.add_argument("--dump-output-flv", default="")
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
    log.write("[framesign] implementation=rapidapi\n")
    log.flush()
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
