"""Dual eligibility and Android Camera LIVE allocation verified on 47.1.4."""


def enabled_flag(value):
    return value is True or type(value) is int and value == 1 or value in ('1', 'true')


def successful_data(payload):
    if isinstance(payload, dict) and str(payload.get('status_code')) == '0':
        data = payload.get('data')
        if isinstance(data, dict):
            return data
    return {}


def dual_layout_info(scene_payload, threshold_payload):
    scene = successful_data(scene_payload)
    threshold = successful_data(threshold_payload)
    allow = scene.get('allow_multi_stream')
    # LIVE Studio locks only when BOTH threshold flags are false.
    # dual_canvas_used is not required for an account's first dual broadcast.
    return {
        'allow_multi_stream_scene1': None if allow is None else enabled_flag(allow),
        'dual_threshold': threshold,
        'dual_layout_unlocked': bool(enabled_flag(allow) and (
            enabled_flag(threshold.get('allowed')) or enabled_flag(threshold.get('dual_canvas_used')))),
        'dual_days_to_reach': threshold.get('days_to_reach'),
    }


def dual_create_params(params):
    result = dict(params)
    for key in ('screen_shot', 'live_room_mode', 'orientation', 'game_tag_id'):
        result.pop(key, None)
    result['live_mode'] = '6'
    return result


def distinct_push_urls(primary, secondary):
    return (isinstance(primary, str) and isinstance(secondary, str)
            and bool(primary.strip()) and bool(secondary.strip()) and primary.strip() != secondary.strip())


def secondary_stream_id(room):
    secondary = room.get('multi_stream_url')
    secondary = secondary if isinstance(secondary, dict) else {}
    for value in (secondary.get('id_str'), secondary.get('id'),
                  room.get('multi_stream_id_str'), room.get('multi_stream_id')):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        value = str(value).strip()
        if value.isascii() and value.isdecimal() and int(value) > 0:
            return value
    return ''
