"""Read-only, room-bound viewer summaries from LIVE Studio's user card API."""
import re
from urllib.parse import urlsplit

from Libs.live_management import LiveManagement, LiveManagementError, _identifier


def optional_count(value):
    """Missing/malformed counters stay unknown; never coerce them to zero."""
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        value = int(value)
    return value if type(value) is int and 0 <= value < 2**63 else None


def parse_viewer_lookup(value):
    """An explicit @ makes an all-digit handle unambiguous."""
    if type(value) is int:
        return 'id', _identifier(value, 'Viewer ID')
    if not isinstance(value, str):
        raise ValueError('Enter a TikTok username or a numeric viewer ID.')
    value = value.strip()
    if value.isascii() and value.isdigit():
        return 'id', _identifier(value, 'Viewer ID')
    handle = value.removeprefix('@')
    if not re.fullmatch(r'[A-Za-z0-9_.]{1,24}', handle) or handle.endswith('.'):
        raise ValueError('Enter a TikTok username, such as @viewer.name, or a numeric viewer ID.')
    return 'username', handle.lower()


def watch_time_text(seconds):
    if seconds is None:
        return 'Unavailable'
    if seconds == 0:
        return '0 min'
    if seconds < 300:
        return f'< {(seconds + 59) // 60} min'
    return f'≥ {seconds // 60} min'


def emote_url(value):
    """Only public TikTok image CDNs; no credentials or arbitrary resource URLs."""
    if not isinstance(value, str) or len(value) > 4096:
        return ''
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower()
        allowed = any(host.endswith('.' + suffix) for suffix in (
            'tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com',
            'byteoversea.com', 'ibytedtos.com',
        ))
        if (url.scheme == 'https' and allowed and not url.username and not url.password
                and url.port in (None, 443)):
            return value
    except ValueError:
        pass
    return ''


def comment_parts(comment):
    """Studio's code-point emote offsets include preceding emote positions."""
    content = comment.get('content')
    if not isinstance(content, str):
        content = ''
    content = content[:4096]
    emotes = comment.get('emotes')
    parts, cursor = [], 0
    for ordinal, item in enumerate(emotes[:20] if isinstance(emotes, list) else []):
        if not isinstance(item, dict):
            continue
        index = optional_count(item.get('index'))
        offset = index - ordinal if index is not None else -1
        if not cursor <= offset <= len(content):
            continue
        if offset > cursor:
            parts.append({'text': content[cursor:offset]})
        emote = item.get('emote')
        emote = emote if isinstance(emote, dict) else {}
        image = emote.get('image')
        urls = image.get('url_list') if isinstance(image, dict) else []
        url = next((clean for raw in urls[:5] if (clean := emote_url(raw))), '') if isinstance(urls, list) else ''
        parts.append({'emote_url': url, 'text': '[Emote]'})
        cursor = offset
    if cursor < len(content):
        parts.append({'text': content[cursor:]})
    return parts


def normalize_summary(data):
    if not isinstance(data, dict):
        raise LiveManagementError('TikTok returned an invalid viewer contribution summary.')
    fields = ('watch_duration', 'like_count', 'share_count', 'comment_count', 'follow_time')
    result = {key: optional_count(data.get(key)) for key in fields}
    comments = data.get('comment_list')
    result['comments'] = None
    result['warning'] = ''
    if isinstance(comments, list):
        valid = [item for item in comments[:10] if isinstance(item, dict)
                 and (isinstance(item.get('content'), str) or isinstance(item.get('emotes'), list))]
        if valid or not comments:
            result['comments'] = [comment_parts(item) for item in valid]
        if len(valid) < min(10, len(comments)):
            result['warning'] = 'Some recent comments could not be displayed.'
    if not any(result[key] is not None for key in fields) and result['comments'] is None:
        raise LiveManagementError('TikTok did not provide contributions for this viewer. '
                                  'The feature may be unavailable for this account or LIVE.')
    result['follow_days'] = None
    return result


class ViewerContributions(LiveManagement):
    def _resolve_username(self, username):
        # Studio getSearchUser: offset=(page-1)*pageSize; matched_user_list
        # contains user_info, whose display_id is the @username, not nickname.
        for page in range(5):
            data = self._get('webcast/anchor/user_search/',
                {'keyword': username, 'offset': page * 50, 'count': 50}, action='Find viewer username')
            if not isinstance(data, dict) or not isinstance(data.get('matched_user_list'), list):
                raise LiveManagementError('TikTok returned an invalid username search response.')
            matches = {}
            for entry in data['matched_user_list']:
                user = entry.get('user_info') if isinstance(entry, dict) else None
                if not isinstance(user, dict):
                    continue
                handle = user.get('display_id')
                if not isinstance(handle, str) or handle.lower() != username:
                    continue
                uid = _identifier(user.get('id_str') or user.get('id'), 'Matched viewer ID')
                matches[uid] = {'id': uid, 'username': handle, 'name': str(user.get('nickname') or '')}
            if len(matches) > 1:
                raise LiveManagementError('TikTok returned conflicting matches for this username. Use the numeric viewer ID.')
            if matches:
                return next(iter(matches.values()))
            if data.get('has_more') not in (True, 1, '1', 'true'):
                break
        raise LiveManagementError(f'No exact match for @{username} in TikTok’s returned search results. '
                                  'Check the username or use the numeric viewer ID.')

    def load(self, viewer_id):
        self._check_context()
        self._require_studio()
        lookup_kind, lookup = parse_viewer_lookup(viewer_id)
        if not self.room_id:
            raise LiveManagementError('Start or resume your LIVE before viewing contributions.')
        account_id, secure_id = self._owner_context(need_room=True)
        viewer = self._resolve_username(lookup) if lookup_kind == 'username' else {'id': lookup}
        viewer_id = viewer['id']
        data = self._get('webcast/room/interaction/user_summary',
                         {'room_id_str': self.room_id, 'user_id_str': viewer_id},
                         action='Load viewer contributions')
        # When identity fields are supplied, reject a mismatched response.
        if isinstance(data, dict):
            for key, expected in (('room_id_str', self.room_id), ('user_id_str', viewer_id)):
                if key in data and str(data[key]) != expected:
                    raise LiveManagementError('TikTok returned contributions for a different viewer or LIVE.')
        result = normalize_summary(data)
        if result['follow_time']:
            try:
                profile = self._get('webcast/user/', {'target_uid': viewer_id, 'anchor_id': account_id,
                    'current_room_id': self.room_id, 'request_from_scene': 1,
                    'need_block_status': 1, **({'sec_anchor_id': secure_id} if secure_id else {}),
                    'request_from': 'profile_card_v2', 'user_role': '{"' + viewer_id + '":1}'},
                    action='Check viewer follow status')
                if not isinstance(profile, dict) or str(profile.get('id_str') or profile.get('id')) != viewer_id:
                    raise LiveManagementError('TikTok did not confirm this viewer’s profile.')
                follow = profile.get('follow_info')
                status = optional_count(follow.get('follow_status')) if isinstance(follow, dict) else None
                # Studio FollowStatus: Following=1, MutualFollow=2, Followed=3.
                if status in (2, 3):
                    result['follow_days'] = max(1, result['follow_time'] // 86400)
                elif status is None:
                    result['warning'] = (result['warning'] + '\nFollow duration is unavailable; '
                                         'TikTok did not confirm follow status.').strip()
            except Exception:
                result['warning'] = (result['warning'] + '\nFollow duration could not be checked. '
                                     'Other contributions are shown above.').strip()
        self._check_context()
        self._account()  # Also catches cookies replaced in the same file during the request.
        self._check_context()
        result.update(account_id=account_id, viewer_id=viewer_id, room_id=self.room_id,
                      viewer_username=viewer.get('username', ''), viewer_name=viewer.get('name', ''))
        return result
