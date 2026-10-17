"""LIVE Campaign Center contracts; signing stays in the selected backend."""
import json
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


class CampaignFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Campaign:
    activity_id: str
    title: str
    description: str
    state: str
    start_time: int
    end_time: int
    url: str
    resource_id: str = ''


def campaign_url(schema):
    """Unwrap TikTok webview/lynx schemes, never launch a native scheme."""
    value = str(schema or '')
    for _ in range(5):
        parts = urlsplit(value)
        if parts.scheme == 'https':
            host = (parts.hostname or '').lower()
            if host == 'tiktok.com' or host.endswith('.tiktok.com'):
                return value
            return ''
        values = parse_qs(parts.query)
        value = (values.get('url') or values.get('fallback_url') or [''])[0]
        if not value:
            break
    return ''


def _field(data, *names, default=''):
    return next((data[n] for n in names if n in data and data[n] is not None), default)


def _seconds(value):
    try:
        return max(0, int(value or 0))
    except (ValueError, TypeError):
        return 0


def normalize_campaigns(payload, *, now):
    """Handle current PascalCase center data and captured LIVE Studio cards."""
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise CampaignFormatError('Campaign response has no data object.')
    pack = _field(data, 'PackData', 'pack_data', default=None)
    if isinstance(pack, dict):
        cards = _field(pack, 'CardInfoList', 'card_info_list', default=None)
    else:
        cards = _field(data, 'cards', default=None)
    if not isinstance(cards, list):
        raise CampaignFormatError('Campaign response has no supported card list.')
    states = {1: 'Ongoing', 2: 'Upcoming', 3: 'Ended', 5: 'Agency ongoing',
              6: 'Agency upcoming', 7: 'Agency ended', 8: 'Registration', 9: 'Offline'}
    result, seen = [], set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        url = campaign_url(_field(card, 'SchemaURL', 'schema_url'))
        activity_id = str(_field(card, 'ActivityIDV2', 'activity_id_v2', 'activity_id')).strip()
        if not activity_id and url:
            query = parse_qs(urlsplit(url).query)
            activity_id = (query.get('activityId') or query.get('activity_id') or [''])[0]
        # Keep banners as well, but they cannot report a visit without an ID.
        resource = str(_field(card, 'ResourceID', 'resource_id'))
        title = str(_field(card, 'Title', 'title', 'activity_name') or activity_id or 'Campaign banner')
        key = (activity_id, resource, title, url)
        if key in seen:
            continue
        seen.add(key)
        start = _seconds(_field(card, 'StartTime', 'start_time'))
        end = _seconds(_field(card, 'EndTime', 'end_time'))
        extra = _field(card, 'CampaignCenterCardExtra', 'campaign_center_card_extra', default={})
        tag = _seconds(_field(extra, 'Tag', 'tag')) if isinstance(extra, dict) else 0
        state = states.get(tag) or ('Ended' if end and end <= now else
                                   'Upcoming' if start > now else 'Ongoing' if start else 'Available')
        result.append(Campaign(activity_id, title, str(_field(card, 'SubTitle', 'sub_title')),
                               state, start, end, url, resource))
    return result


def center_params(aid, user_id):
    # x.request serializes nested query values as JSON. The center uses this
    # PascalCase schema with jsonFormatOption=1 on Android.
    user_base = {'AppID': str(aid), 'LiveID': '', 'UserID': str(user_id), 'DeviceID': ''}
    return {'UserBase': json.dumps(user_base, separators=(',', ':')), 'EnterFromScene': '2'}


def visit_request(activity_id, user_id, timestamp, aid):
    activity_id, user_id = str(activity_id).strip(), str(user_id).strip()
    if not activity_id.isascii() or not activity_id.isdigit():
        raise ValueError('A numeric campaign activity ID is required.')
    if not user_id.isascii() or not user_id.isdigit() or int(user_id) == 0:
        raise ValueError('A signed-in account ID is required.')
    return ({'activity': 'op_component-open-2-' + activity_id, 'aid': str(aid)},
            {'event_type': 'visit_specific_campaign_page', 'user_id': user_id,
             'event_time': int(timestamp), 'event_data': {}})
