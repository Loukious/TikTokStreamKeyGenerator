"""Read Windows LIVE Studio's saved accounts and export one account's session.

Studio 1.37 stores AccountService.state.accountList in TTStore/services.json.
Each sessionId is copied from Studio's sessionid cookie, as verified against its
installed account-switch code. TTStore/login.json is an encrypted active-account
cache; mixing that cache into another account's export would be incorrect.
"""
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit


class StudioCookieError(RuntimeError):
    pass


_COOKIE_DOMAINS = ('tiktokv.com', 'tiktokv.us', 'tiktokv.eu', 'tiktokw.us',
                   'tiktokw.eu', 'ttapis.com', 'tiktok.com')


@dataclass(frozen=True)
class StudioAccount:
    user_id: str
    username: str
    nickname: str
    session_id: str = field(repr=False)
    cookie_domain: str = '.tiktokv.com'
    current: bool = False
    disambiguate: bool = False

    @property
    def filename(self):
        handle = self.username or self.user_id
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', handle).strip(' ._-')
        if not safe:
            safe = self.user_id
        elif safe != handle or len(safe) > 64:
            safe = safe[:64] + '_' + self.user_id
        if self.disambiguate:
            safe += '_' + self.user_id
        return 'cookies_' + safe + '.json'


def _require_windows():
    if sys.platform != 'win32':
        raise StudioCookieError('Importing LIVE Studio cookies is available only on Windows.')


def _cookie_domain(origin):
    if not origin:
        return '.tiktokv.com'
    value = str(origin)
    # Studio stores bare API hostnames as well as full HTTPS URLs.
    url = urlsplit(value if '://' in value else 'https://' + value)
    host = (url.hostname or '').lower()
    if url.scheme != 'https' or url.username or url.password:
        raise StudioCookieError('Studio stored an unsupported account domain.')
    for domain in _COOKIE_DOMAINS:
        if host == domain or host.endswith('.' + domain):
            return '.' + domain
    raise StudioCookieError('Studio stored an unsupported account domain.')


def read_studio_accounts(data_dir=None):
    """Read only the saved-account list; no browser database or network access."""
    _require_windows()
    if data_dir is None:
        roaming = os.environ.get('APPDATA')
        if not roaming:
            raise StudioCookieError('Windows AppData could not be located.')
        data_dir = Path(roaming) / 'TikTok LIVE Studio'
    source = Path(data_dir) / 'TTStore' / 'services.json'
    try:
        data = json.loads(source.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise StudioCookieError('Studio\'s saved accounts were not found. Sign in to TikTok LIVE Studio first.') from None
    except OSError:
        raise StudioCookieError('Studio\'s saved accounts could not be read. Try again after closing Studio.') from None
    except ValueError:
        raise StudioCookieError('Studio\'s saved-account file is incomplete or unsupported. Try again after Studio finishes saving.') from None
    try:
        entries = data['AccountService']['state']['accountList']
        user_info = data.get('UserService', {}).get('state', {}).get('userInfo') or {}
        current_id = str(user_info.get('user_id_str') or user_info.get('user_id') or '')
    except (KeyError, TypeError, AttributeError):
        raise StudioCookieError('This Studio version has no supported saved-account list.') from None
    if not isinstance(entries, list):
        raise StudioCookieError('This Studio version has an unsupported saved-account list.')
    accounts = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        user_id = str(entry.get('userId') or '')
        token = entry.get('sessionId')
        if (not user_id.isascii() or not user_id.isdigit() or not user_id.strip('0')
                or not isinstance(token, str) or not re.fullmatch(r'[a-fA-F0-9]{32}', token)):
            continue
        try:
            domain = _cookie_domain(entry.get('domain'))
        except (StudioCookieError, ValueError):
            continue
        if user_id not in accounts:
            accounts[user_id] = StudioAccount(
                user_id, str(entry.get('displayId') or ''), str(entry.get('nickname') or ''),
                token, domain, user_id == current_id)
    if not accounts:
        raise StudioCookieError('Studio has no saved accounts with usable sessions. Sign in to Studio and try again.')
    values = list(accounts.values())
    names = [a.filename.casefold() for a in values]
    return [replace(a, disambiguate=True) if names.count(a.filename.casefold()) > 1 else a for a in values]


def export_studio_account(account, output_dir):
    """Atomically save one saved session, never another account's ancillary cookies."""
    _require_windows()
    if (not re.fullmatch(r'[a-fA-F0-9]{32}', account.session_id)
            or not account.user_id.isascii() or not account.user_id.isdigit()
            or not account.user_id.strip('0') or account.cookie_domain.lstrip('.') not in _COOKIE_DOMAINS):
        raise StudioCookieError('The selected Studio account has no usable session.')
    records = [{'name': name, 'value': account.session_id, 'domain': account.cookie_domain,
                'path': '/', 'hostOnly': False, 'secure': True, 'httpOnly': True,
                'session': True, 'sameSite': 'no_restriction'}
               for name in ('sessionid', 'sessionid_ss', 'sid_tt')]
    target = Path(output_dir) / account.filename
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.studio-cookie-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(records, stream, indent=2)
        os.replace(temporary, target)
    except OSError:
        raise StudioCookieError('Could not save cookies beside the app. Move the app to a writable folder and try again.') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(target)
