"""Route signatures without bundling development algorithms in releases."""
import base64
import importlib
import os
import sys


def is_development():
    packaged = bool(getattr(sys, 'frozen', False) or globals().get('__compiled__'))
    mode = os.environ.get('TIKTOK_SIGNER_MODE', 'api').lower()
    if mode not in ('dev', 'api'):
        raise ValueError('TIKTOK_SIGNER_MODE must be dev or api')
    if packaged and mode == 'dev':
        raise RuntimeError('Development signers are unavailable in production builds.')
    return mode == 'dev'


def _local_mobile(record):
    return importlib.import_module('DevTools.mobile_signers').mobile_signer(record)


def validate_mobile(record, *, frame_signing=True):
    if not record.get('device_id') or not record.get('install_id'):
        raise ValueError('Enter the Android device and install IDs in Device settings.')
    if is_development():
        signer = _local_mobile(record)
        if frame_signing:
            signer.frame_sign({'aid': str(record.get('aid', '1233')),
                               'did': record['device_id'], 'uid': '', 'roomid': '',
                               'frametype': '2', 'timestamp': '1700000000'},
                              captured_rule=bool(record['frame_sdk'].get('captured_rule_1008')))
    else:
        from Libs.signers import mobile_api_ready
        mobile_api_ready()


def signature_headers(timestamp, aid='8311', *, implementation='pc', device_profile=None,
                      url=None, headers=None, body=None, install_id=None, **kwargs):
    if is_development():
        if implementation == 'mobile':
            return _local_mobile(device_profile).signature_headers(
                timestamp, url=url, params=kwargs.get('params'), headers=headers, body=body,
                x_ss_stub=kwargs.get('x_ss_stub'))
        local = importlib.import_module('DevTools.signers')
        return local.TikTokSigners.signature_headers(timestamp, aid, **kwargs)
    from Libs.signers import signature_headers as hosted
    if implementation == 'pc':
        return hosted(timestamp, aid, **kwargs)
    return hosted(timestamp, aid, implementation='mobile', url=url,
                  request_headers=headers, body_base64=base64.b64encode(body).decode() if body is not None else None,
                  install_id=install_id, **kwargs)


def frame_sign(payload, *, implementation='pc', device_profile=None, **options):
    if is_development():
        if implementation == 'mobile':
            return _local_mobile(device_profile).frame_sign(
                payload, captured_rule=bool(device_profile['frame_sdk'].get('captured_rule_1008')),
                **options)
        return importlib.import_module('DevTools.XFrameSign').frame_sign(payload, **options)
    from Libs.XFrameSign import frame_sign as hosted
    if implementation == 'pc':
        return hosted(payload, **options)
    return hosted(payload, implementation='mobile',
                  sdk_context=device_profile.get('frame_sdk', {}), **options)



def prepare_mobile_registration(record, **options):
    """Compatibility import; registration preparation is always local Libs code."""
    from Libs.mobile_device_gen import prepare_mobile_registration as prepare
    return prepare(record, **options)
