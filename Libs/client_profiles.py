"""Saved PC/mobile identities and signing contexts for the GUI."""
import copy
import re
from Libs.region_context import country_code


# Network stack versions from the pinned TikTok 47.1.4 Android capture.
ANDROID_TTNET_VERSION = '4.2.243.64-tiktok'
ANDROID_CRONET_VERSION = 'eeeffe19_2026-08-31'


def mobile_version_params(record):
    version = str(record['app_version'])
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', version):
        raise ValueError('Android app_version must have three numeric components')
    code = 0
    for component in version.split('.'):
        code = code * 100 + int(component)
    # Saved version_code is historically the APK build code. Keep saved
    # profiles compatible, but use the app code for the wire version_code.
    build = str(record['version_code'])
    return {'version_name': version, 'version_code': str(code),
            'manifest_version_code': str(record.get('manifest_version_code', build)),
            'update_version_code': str(record.get('update_version_code', build))}


def normalize_device_type(value):
    value = str(value or 'pc').strip().lower()
    if value not in ('pc', 'mobile'):
        raise ValueError('device_type must be pc or mobile')
    return value


def selected_device_type(args, config):
    return normalize_device_type(getattr(args, 'device_type', None) or config.get('device_type', 'pc'))


def device_records(config):
    """Migrate old top-level IDs into their original implementation only."""
    records = copy.deepcopy(config.get('devices', {}))
    if not isinstance(records, dict) or any(not isinstance(v, dict) for v in records.values()):
        raise ValueError('config.devices must contain objects keyed by pc/mobile')
    # Before this feature the project only generated PC IDs. Merely setting
    # device_type=mobile in an old config cannot reclassify those IDs.
    previous = 'pc' if 'devices' not in config else normalize_device_type(config.get('device_type', 'pc'))
    if previous not in records and any(config.get(k) for k in ('device_id', 'install_id')):
        records[previous] = {k: config[k] for k in ('device_id', 'install_id') if k in config}
    return records


def mobile_record_defaults(record):
    result = copy.deepcopy(record)
    if 'identifiers' not in result:
        result['identifiers'] = {}
    result.setdefault('fingerprint', {})
    result.setdefault('aid', '1233')
    result.setdefault('app_version', '47.1.4')
    result.setdefault('version_code', '2024701040')
    result.setdefault('ttnet_version', ANDROID_TTNET_VERSION)
    result.setdefault('cronet_version', ANDROID_CRONET_VERSION)
    result.setdefault('request_params', {})
    # Captured offline SDK state, not live provisioning state.
    result.setdefault('frame_sdk', {
        'sdk_version': 'v05.03.01-ov-android', 'rk_k': 0,
        'metadata_field6': 270088, 'metadata_field7': 4,
        'captured_rule_1008': False,
    })
    return result


class ClientImplementation:
    def __init__(self, kind='pc', record=None):
        self.kind = normalize_device_type(kind)
        self.record = copy.deepcopy(record or {})
        self.aid = str(self.record.get('aid', '1233' if self.kind == 'mobile' else '8311'))

    def validate(self, *, frame_signing=True):
        from Libs.signing_backend import validate_mobile
        if self.kind == 'mobile':
            validate_mobile(self.record, frame_signing=frame_signing)

    def frame_sign(self, payload, **options):
        from Libs.signing_backend import frame_sign
        return frame_sign(payload, implementation=self.kind, device_profile=self.record, **options)

    def signature_headers(self, timestamp, *, url, params=None, headers=None, body=None):
        from Libs.signing_backend import signature_headers
        return signature_headers(timestamp, self.aid, url=url, params=params, headers=headers,
                                 body=body, device_id=self.record.get('device_id'),
                                 install_id=self.record.get('install_id'),
                                 implementation=self.kind, device_profile=self.record)

    def mobile_params(self, *, device_id, install_id, priority_region=''):
        fp = self.record.get('fingerprint', {})
        identifiers = self.record.get('identifiers', {})
        params = {
            'aid': self.aid, 'app_name': 'musical_ly',
            'device_platform': 'android', 'channel': 'googleplay',
            **mobile_version_params(self.record),
            'ttnet_version': self.record.get('ttnet_version', ANDROID_TTNET_VERSION),
            'cronet_version': self.record.get('cronet_version', ANDROID_CRONET_VERSION),
            'language': 'en', 'app_language': 'en', 'webcast_language': 'en',
        }
        for source, dest in (('model', 'device_type'), ('brand', 'device_brand'),
                             ('os_version', 'os_version'), ('os_api', 'os_api'),
                             ('resolution', 'resolution'), ('dpi', 'dpi'),
                             ('timezone_name', 'timezone_name'), ('region', 'region'),
                             ('android_id', 'android_id'), ('clientudid', 'clientudid')):
            value = fp.get(source) or identifiers.get(source)
            if value:
                params[dest] = str(value)
        params.update(self.record.get('request_params', {}))
        # The resolved/explicit request context wins over a stale profile capture.
        region = country_code(priority_region or params.get('priority_region'))
        if region:
            params['priority_region'] = region
        else:
            params.pop('priority_region', None)
        # Android registration uses iid; install_id is the PC query spelling.
        for key in ('install_id', 'live_studio', 'live_mode', 'browser_name',
                    'browser_version', 'browser_platform', 'browser_language',
                    'screen_width', 'screen_height', 'multi_stream_scene', 'multi_stream_source'):
            params.pop(key, None)
        params.update(aid=self.aid, device_id=str(device_id), iid=str(install_id),
                      device_platform='android', **mobile_version_params(self.record))
        return params

    def mobile_headers(self):
        return {
            'user-agent': self.record.get('user_agent') or f'TikTok/{self.record["app_version"]} (Android)',
            'accept': 'application/json', 'accept-language': 'en-US',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'sdk_aid': self.aid, 'X-SS-DP': self.aid,
        }
