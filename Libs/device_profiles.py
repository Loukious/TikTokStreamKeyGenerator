"""Prepare independent PC/Android installations without exposing hardware forms."""
import copy

from .client_profiles import mobile_record_defaults
from .device_gen import generate_desktop_fingerprint, generate_private_pc_identifiers
from .mobile_device_gen import complete_mobile_device_profile


def has_registered_ids(record):
    for key in ('device_id', 'install_id'):
        value = str(record.get(key) or '')
        if not value.isascii() or not value.isdigit() or int(value) <= 0:
            return False
    return True


def prepare_device_profiles(records):
    """Generate missing local fields; never rotate an existing installation."""
    result = copy.deepcopy(records)
    pc = result.setdefault('pc', {})
    fingerprint = pc.get('fingerprint', {})
    identifiers = pc.get('identifiers', {})
    if not isinstance(fingerprint, dict) or not isinstance(identifiers, dict):
        raise ValueError('PC fingerprint and identifiers must be objects')
    generated_uuid, generated_serial = generate_private_pc_identifiers()
    pc['identifiers'] = {'pc_uuid': generated_uuid, 'pc_serial': generated_serial,
                         **{k: v for k, v in identifiers.items() if v not in ('', None)}}
    pc['fingerprint'] = {**generate_desktop_fingerprint(),
                         **{k: v for k, v in fingerprint.items() if v not in ('', None)}}
    result['mobile'] = mobile_record_defaults(complete_mobile_device_profile(result.get('mobile', {})))
    return result
