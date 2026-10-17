"""Android identity generation, encoding and direct registration from this PC."""
import copy
import base64
import gzip
import hashlib
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlencode

REGISTRATION_HOSTS = ('log-va.tiktokv.com', 'api.tiktokv.com', 'aggr32-normal.tiktokv.com', 'api-boot.tiktokv.com')


class MobileRegistrationNotIssued(ValueError):
    """The server responded but did not issue a usable Android installation."""

# Coherent model/OS/display combinations rather than independently randomized
# hardware fields. Generated values are saved once with this installation.
ANDROID_HARDWARE_PROFILES = (
    {'model': 'Pixel 8', 'brand': 'google', 'manufacturer': 'Google',
     'os_version': '14', 'os_api': '34', 'resolution': '2400x1080', 'dpi': '420'},
    {'model': 'Pixel 7', 'brand': 'google', 'manufacturer': 'Google',
     'os_version': '13', 'os_api': '33', 'resolution': '2400x1080', 'dpi': '420'},
    {'model': 'SM-S911B', 'brand': 'samsung', 'manufacturer': 'samsung',
     'os_version': '13', 'os_api': '33', 'resolution': '2340x1080', 'dpi': '420'},
    {'model': 'CPH2583', 'brand': 'OnePlus', 'manufacturer': 'OnePlus',
     'os_version': '14', 'os_api': '34', 'resolution': '3168x1440', 'dpi': '560'},
)


def generate_mobile_fingerprint():
    fingerprint = dict(secrets.choice(ANDROID_HARDWARE_PROFILES))
    fingerprint.update(secrets.choice((
        {'timezone': '0', 'timezone_name': 'Etc/UTC', 'tz_offset': 0, 'region': 'US'},
        {'timezone': '1', 'timezone_name': 'Africa/Tunis', 'tz_offset': 3600, 'region': 'TN'},
        {'timezone': '9', 'timezone_name': 'Asia/Tokyo', 'tz_offset': 32400, 'region': 'JP'},
    )))
    fingerprint.update(cpu_abi='arm64-v8a', language='en')
    return fingerprint


def generate_mobile_device(*, fingerprint=None):
    if fingerprint is not None and not isinstance(fingerprint, dict):
        raise ValueError('fingerprint must be an object')
    android_id = secrets.token_hex(8)
    return {
        'aid': '1233', 'device_id': '', 'install_id': '',
        'identifiers': {'android_id': android_id, 'openudid': android_id,
                        'clientudid': str(uuid.uuid4()), 'cdid': str(uuid.uuid4())},
        'fingerprint': {**generate_mobile_fingerprint(), **copy.deepcopy(fingerprint or {})},
    }


def complete_mobile_device_profile(record=None):
    """Fill hidden installation fields once, preserving imported/saved values."""
    local = copy.deepcopy({} if record is None else record)
    if not isinstance(local, dict):
        raise ValueError('device_profile must be an object')
    identifiers, fingerprint = local.get('identifiers', {}), local.get('fingerprint', {})
    if not isinstance(identifiers, dict) or not isinstance(fingerprint, dict):
        raise ValueError('identifiers and fingerprint must be objects')
    fingerprint = {k: v for k, v in fingerprint.items() if v not in ('', None)}
    # Reuse a matching preset when completing an imported partial fingerprint.
    preset = next((dict(p) for p in ANDROID_HARDWARE_PROFILES
                   if p['model'] == fingerprint.get('model')), None)
    generated = generate_mobile_device(fingerprint=fingerprint)
    if preset is not None:
        generated['fingerprint'].update({**preset, **fingerprint})
    generated['identifiers'].update({k: v for k, v in identifiers.items() if v})
    if identifiers.get('android_id') and not identifiers.get('openudid'):
        generated['identifiers']['openudid'] = identifiers['android_id']
    local['identifiers'], local['fingerprint'] = generated['identifiers'], generated['fingerprint']
    local.setdefault('aid', '1233')
    local.setdefault('apk_first_install_time', int(time.time() * 1000))
    return local


def parse_mobile_registration(response):
    if not isinstance(response, dict):
        raise ValueError('Android registration response must be an object')
    data = response.get('data', response)
    if not isinstance(data, dict):
        raise ValueError('Android registration data must be an object')
    result = {}
    for name in ('device_id', 'install_id'):
        value = data.get(name + '_str') or data.get(name)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError('TikTok registration did not return a valid ' + name)
        value = str(value).strip()
        if value.isascii() and value.isdecimal() and int(value) == 0:
            raise MobileRegistrationNotIssued(
                'TikTok returned zero Android device/install IDs. The server did not issue a usable installation.')
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise ValueError('TikTok registration did not return a valid ' + name)
        result[name] = value
    # Retain registration state needed for subsequent Android requests.
    result['registration'] = {k: data[k] for k in ('device_token', 'ssid', 'cd', 'new_user') if k in data}
    return result


def build_mobile_registration(record, *, timestamp_ms=None, req_id=None,
                              host='log-va.tiktokv.com', encoding='ttencrypt'):
    """Build AppLog 2.5.14.6's registration envelope before local encoding.

    Hardware fields must describe the selected Android profile. Additional
    captured header/query fields can be supplied through registration_options.
    Live registration uses ttEncrypt over gzip-compressed JSON. The standalone
    gzip transport is retained for explicit AppLog diagnostics. json-gzip
    matches the captured TTNet format and hashes JSON before compression.
    """
    if not isinstance(record, dict):
        raise ValueError('device must be an object')
    if host not in REGISTRATION_HOSTS:
        raise ValueError('Unsupported Android registration host')
    if encoding not in ('ttencrypt', 'gzip', 'json-gzip', 'json'):
        raise ValueError('encoding must be ttencrypt, gzip, json-gzip or json')
    aid = str(record.get('aid', '1233'))
    if aid != '1233':
        raise ValueError('This registration profile requires Android aid 1233')
    ids, fp = record.get('identifiers', {}), record.get('fingerprint', {})
    if not isinstance(ids, dict) or not isinstance(fp, dict):
        raise ValueError('identifiers and fingerprint must be objects')
    android_id = str(ids.get('android_id', ''))
    if not re.fullmatch('[0-9a-fA-F]{16}', android_id):
        raise ValueError('Generate a local Android ID before registering')
    for name in ('clientudid', 'cdid'):
        try:
            uuid.UUID(str(ids[name]))
        except (KeyError, ValueError, AttributeError) as exc:
            raise ValueError('Generate a local ' + name + ' before registering') from exc
    for name in ('model', 'brand', 'os_version', 'os_api'):
        if not str(fp.get(name) or '').strip():
            raise ValueError('Enter Android ' + name + ' before registering')
    try:
        os_api = int(fp['os_api'])
        if isinstance(fp['os_api'], bool) or not 1 <= os_api <= 100:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ValueError('Android API level must be an integer between 1 and 100') from exc
    version = str(record.get('app_version', '47.1.4'))
    # Register#doRegister overwrites header version_code with dotted version.
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', version):
        raise ValueError('Android app_version must have three numeric components')
    version_code = 0
    for component in version.split('.'):
        version_code = version_code * 100 + int(component)
    install_version = int(record.get('version_code', '2024701040'))
    instant = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if isinstance(instant, bool) or not isinstance(instant, int) or instant < 0:
        raise ValueError('timestamp_ms must be a nonnegative integer')
    request_id = str(uuid.uuid4()) if req_id is None else str(uuid.UUID(str(req_id)))
    header = {
        'aid': 1233, 'app_name': 'musical_ly', 'package': 'com.zhiliaoapp.musically',
        'channel': 'googleplay', 'not_request_sender': 1, 'app_version': version,
        'version_code': version_code, 'update_version_code': install_version,
        'manifest_version_code': install_version, 'device_platform': 'android',
        'os': 'Android', 'os_version': str(fp['os_version']), 'os_api': os_api,
        'device_model': str(fp['model']), 'device_brand': str(fp['brand']),
        'openudid': str(ids.get('openudid') or android_id), 'clientudid': ids['clientudid'],
        'cdid': ids['cdid'], 'git_hash': '43cd1bf', 'sdk_version_code': 205140690,
        'sdk_target_version': 30, 'sdk_version': '2.5.14.6', 'sdk_flavor': 'i18nInner',
        'guest_mode': 0, 'is_system_app': 0, 'req_id': request_id,
        'apk_first_install_time': record.get('apk_first_install_time', instant),
    }
    for name in ('device_id', 'install_id'):
        value = record.get(name)
        if value:
            if not str(value).isascii() or not str(value).isdecimal() or int(value) <= 0:
                raise ValueError('Invalid Android ' + name)
            header[name] = str(value)
    for src, dest in (('manufacturer', 'device_manufacturer'), ('cpu_abi', 'cpu_abi'),
                      ('resolution', 'resolution'), ('dpi', 'density_dpi'),
                      ('language', 'language'), ('timezone', 'timezone'),
                      ('tz_offset', 'tz_offset'), ('rom', 'rom'), ('rom_version', 'rom_version')):
        if fp.get(src) is not None:
            header[dest] = fp[src]
    registration = record.get('registration', {})
    if isinstance(registration, dict) and registration.get('ssid'):
        header['ssid'] = registration['ssid']
    options = record.get('registration_options', {})
    if not isinstance(options, dict):
        raise ValueError('registration_options must be an object')
    extra_header, extra_query = options.get('header', {}), options.get('query', {})
    if not isinstance(extra_header, dict) or not isinstance(extra_query, dict):
        raise ValueError('registration header/query must be objects')
    # Identity and version invariants stay tied to this profile.
    for key, value in extra_header.items():
        if key in header and value != header[key]:
            raise ValueError('registration header conflicts with profile: ' + key)
        header[key] = value
    # Registration dispatch also reads platform/version from the URL.
    # The same fields inside the JSON header do not substitute for these.
    params = {'aid': aid, 'app_version': version, 'req_id': request_id,
              'device_platform': 'android', 'version_code': str(version_code)}
    if record.get('device_id'):
        params['device_id'] = str(record['device_id'])
    for key, value in extra_query.items():
        if key in params and str(value) != params[key]:
            raise ValueError('registration query conflicts with profile: ' + key)
        if key in ('tt_data', 'tt_info'):
            raise ValueError('Encoded registration query fields are generated by the registration helper')
        params[key] = value
    registered = bool(record.get('device_id') and record.get('install_id'))
    headers = {'content-type': 'application/json; charset=utf-8',
               'accept-encoding': 'gzip', 'x-tt-request-tag': 't=0;n=' + ('0' if registered else '1')}
    if encoding == 'gzip':
        params['tt_data'] = 'a'
        headers['content-type'] = 'application/octet-stream;tt-data=a'
    if encoding == 'json-gzip':
        headers['x-bd-content-encoding'] = 'gzip'
    if encoding in ('json-gzip', 'json'):
        headers['x-ss-req-ticket'] = str(instant)
    if record.get('user_agent'):
        headers['user-agent'] = str(record['user_agent'])
    return {'url': 'https://' + host + '/service/2/device_register/?' + urlencode(params),
            'headers': headers, 'payload': {'header': header, 'magic_tag': 'ss_app_log', '_gen_time': instant}}



def prepare_mobile_registration(record, *, timestamp_ms=None, req_id=None,
                                host='log-va.tiktokv.com', encoding='ttencrypt', seed=None):
    """Prepare Android registration entirely in Libs, like PC registration.

    Registration is a bootstrap request. The APK's AppLog request builder adds
    content type/request tag; it does not call the Webcast/frame signing API.
    """
    draft = build_mobile_registration(record, timestamp_ms=timestamp_ms, req_id=req_id,
                                      host=host, encoding=encoding)
    raw = json.dumps(draft['payload'], separators=(',', ':'), ensure_ascii=False,
                     allow_nan=False).encode('utf-8')
    if len(raw) > 32768:
        raise ValueError('Android registration payload exceeds 32 KiB')
    # Compression belongs to the registration transport, not the byte codec.
    # TikTok replies HTTP 200 with zero IDs for encrypted uncompressed JSON.
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    compressed = compressed[:9] + b'\x00' + compressed[10:]
    if encoding == 'json':
        body = raw
    elif encoding == 'ttencrypt':
        from .mobile_log_encrypt_codec import tt_encrypt
        body = tt_encrypt(compressed, seed=seed)
    else:
        body = compressed
    headers = {**draft['headers'], 'accept': 'application/json',
               'x-ss-stub': hashlib.md5(raw if encoding == 'json-gzip' else body).hexdigest()}
    return {'success': True, 'implementation': 'mobile', 'method': 'POST',
            'url': draft['url'], 'headers': headers,
            'body_base64': base64.b64encode(body).decode('ascii')}


def _new_http_session():
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        import requests
        return requests.Session()
    return curl_requests.Session(impersonate='chrome')


def register_mobile_device(record, *, session=None, prepare=None, timeout=25):
    """Encode locally, register directly with TikTok, and return the profile.

    Like register_desktop_device_identifiers, this has no signing API or
    DevTools dependency. Caller-owned sessions stay open; our session is closed.
    The GUI persists the returned Android identity in its Android profile.
    """
    from urllib.parse import urlsplit
    if not isinstance(record, dict):
        raise ValueError('device must be an object')
    local = copy.deepcopy(record)
    if not local.get('apk_first_install_time'):
        local['apk_first_install_time'] = int(time.time() * 1000)
    options = local.get('registration_options', {})
    if not isinstance(options, dict):
        raise ValueError('registration_options must be an object')
    host, encoding = options.get('host', REGISTRATION_HOSTS[0]), options.get('encoding', 'ttencrypt')
    build_mobile_registration(local, host=host, encoding=encoding)
    prepare = prepare or prepare_mobile_registration
    prepared = prepare(local, host=host, encoding=encoding)
    if not isinstance(prepared, dict) or not prepared.get('success') or prepared.get('method') != 'POST':
        raise ValueError('Registration helper did not prepare an Android registration request')
    parts = urlsplit(prepared.get('url', ''))
    if parts.scheme != 'https' or parts.netloc != host or parts.path != '/service/2/device_register/' or parts.fragment:
        raise ValueError('Registration helper returned an unexpected registration URL')
    body = base64.b64decode(prepared.get('body_base64', ''), validate=True)
    headers = prepared.get('headers')
    if not isinstance(headers, dict):
        raise ValueError('Registration helper returned invalid registration headers')
    signing_body = body
    if encoding == 'json-gzip':
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
            signing_body = compressed.read(32769)
        if len(signing_body) > 32768 or headers.get('x-bd-content-encoding') != 'gzip':
            raise ValueError('Registration helper returned invalid compressed JSON')
    if not body or not isinstance(headers, dict) or headers.get('x-ss-stub', '').lower() != hashlib.md5(signing_body).hexdigest():
        raise ValueError('Registration helper returned invalid registration bytes')
    close_session = session is None
    client = session if session is not None else _new_http_session()
    try:
        response = client.post(prepared['url'], headers=headers, data=body,
                               timeout=timeout, allow_redirects=False)
        response.raise_for_status()
        local.update(parse_mobile_registration(response.json()))
        return local
    finally:
        if close_session:
            client.close()


def register_mobile_device_identifiers(session=None, timeout=25, *, device_profile=None,
                                       return_profile=False):
    """PC-compatible calling convention: tuple by default, profile on request."""
    local = complete_mobile_device_profile(device_profile)
    registered = register_mobile_device(local, session=session, timeout=timeout)
    if return_profile:
        return registered
    return registered['device_id'], registered['install_id']
