"""Account/session/client-scoped Webcast region discovery, shared by GUI workers."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import threading
import time


def country_code(value):
    value = str(value or '').strip().lower()
    return value if len(value) == 2 and value.isascii() and value.isalpha() else ''


def session_key(cookies_path, kind, cookie_value):
    # Never store authentication cookies in the cache or logs. Re-authentication
    # and account switching must not reuse the previous session's region.
    session = cookie_value('sessionid') or cookie_value('sessionid_ss') or cookie_value('sid_guard') or cookie_value('sid_tt')
    identity = '\0'.join((str(session), str(cookie_value('uid_tt')), str(cookie_value('uid_tt_ss'))))
    return (str(cookies_path), kind, hashlib.sha256(identity.encode()).digest())


@dataclass(frozen=True)
class RegionContext:
    priority_region: str
    store_region: str
    expires_at: float


_contexts = OrderedDict()
_lock = threading.Lock()


def cached_context(key):
    with _lock:
        result = _contexts.get(key)
        if result and result.expires_at > time.monotonic():
            return result
        _contexts.pop(key, None)
    return None


def remember_context(key, priority_region, store_region):
    result = RegionContext(country_code(priority_region), country_code(store_region),
                           time.monotonic() + 20 * 60)
    with _lock:
        _contexts[key] = result
        _contexts.move_to_end(key)
        while len(_contexts) > 128:
            _contexts.popitem(last=False)
    return result
