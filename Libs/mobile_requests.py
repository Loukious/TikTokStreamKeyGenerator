"""Android room fields traced in TikTok 47.1.4 X.0gEE.LIZIZ.

Camera LIVE supports single or Studio dual canvas. SCREEN_RECORD sets screen_shot,
live_room_mode=4, orientation and game_tag_id; orientation must come from
the Android profile, rather than the desktop dual-layout checkbox.
"""
import time

# X.0gFM.LJII maps GameLandScapeOrientationChannel to 2 when true, else 1;
# X.0gEE.LIZIZ sends that value as the screen-record orientation.
MOBILE_BROADCAST_MODES = (('Camera LIVE', 'video'), ('Mobile gaming (screen capture)', 'screen_record'))
MOBILE_ORIENTATIONS = (('Portrait', '1'), ('Landscape', '2'))


def create_room_form(record, *, title, hashtag_id, game_tag_id='0', gen_replay=True,
                     age_restricted=False, cover_uri='', multi_stream_scene=False, multi_stream_source=1):
    if multi_stream_scene and record.get('broadcast_type', 'video') != 'video':
        raise ValueError('Android Dual Layout requires Camera LIVE; screen capture uses a single canvas.')
    if multi_stream_scene and str(multi_stream_source) != '1':
        raise ValueError('Android Dual Layout requires multi_stream_source=1')
    form = {
        'title': title, 'cover_uri': cover_uri, 'hashtag_id': str(hashtag_id),
        'gen_replay': str(bool(gen_replay)).lower(), 'chat_auth': '1', 'gift_auth': '1',
        'age_restricted': '4' if age_restricted else '0',
        'live_agreement': '0', 'game': '', 'tags': '',
        'has_commerce_goods': 'false', 'deco_list': '',
        'hold_living_room': '1', 'create_source': '0', 'chat_l_2': '1',
        'open_commercial_content_toggle': 'false',
        'commercial_content_promote_myself': 'false',
        'commercial_content_promote_third_party': 'false',
        'timestamp': str(int(time.time() * 1000)),
    }
    form.update({k: str(v) for k, v in record.get('create_params', {}).items()})
    if record.get('broadcast_type', 'video') == 'screen_record':
        orientation = record.get('orientation')
        if orientation is None or not str(orientation).isdigit():
            raise ValueError('Screen capture requires the orientation value from your Android request.')
        form.update(screen_shot='1', live_room_mode='4', orientation=str(orientation),
                    game_tag_id=str(game_tag_id))
    else:
        for key in ('screen_shot', 'live_room_mode', 'orientation', 'game_tag_id'):
            form.pop(key, None)
    # Imported extras cannot select Studio mode; only the explicit dual option can.
    for key in ('live_studio', 'multi_stream_scene', 'multi_stream_source',
                'close_room_when_close_stream', 'chat_l2', 'rtc_net_enabled'):
        form.pop(key, None)
    form.update(title=title, hashtag_id=str(hashtag_id), cover_uri=cover_uri,
                gen_replay=str(bool(gen_replay)).lower(),
                age_restricted='4' if age_restricted else '0')
    if multi_stream_scene:
        form.pop('live_mode', None)
        form.update(live_studio='1', multi_stream_scene='1', multi_stream_source='1')
    return form
