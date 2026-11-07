"""Account-bound LIVE controls. Mutations are single-attempt and never retried.

Wire formats are traced in Studio 1.37.4 and Android 47.1.4. Stream supplies
session, profile-specific common parameters, signing and host routing.
"""
from copy import deepcopy
import re


class LiveManagementError(RuntimeError):
    """A rejected, malformed, or partially applied management operation."""


def _dict(value):
    return value if isinstance(value, dict) else {}


def _boolean(value):
    if value is True or value in (1, '1', 'true'):
        return True
    if value is False or value in (0, '0', 'false'):
        return False
    return None


def _identifier(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'{label} must be a positive numeric ID.')
    value = str(value).strip()
    if len(value) > 20 or not re.fullmatch(r'[0-9]+', value) or int(value) <= 0:
        raise ValueError(f'{label} must be a positive numeric ID.')
    return value


def _checked(payload, action):
    if not isinstance(payload, dict) or 'status_code' not in payload:
        raise LiveManagementError(f'{action}: TikTok returned an unrecognized response; success is unconfirmed.')
    code = payload['status_code']
    if isinstance(code, bool) or code not in (0, '0'):
        reason = ''
        for part in (payload, _dict(payload.get('data'))):
            for key in ('prompts', 'message', 'status_msg', 'description', 'error_description'):
                value = part.get(key)
                if isinstance(value, str) and value.strip():
                    reason = value.strip()
                    break
            if reason:
                break
        raise LiveManagementError(f'{action}: {reason or "TikTok rejected the request."} (status_code={code})')
    return payload.get('data')


def chat_availability(create_info, subscription_info=None, basic_info=None):
    """Only explicit server grants enable restricted controls."""
    create, sub, basic = map(_dict, (create_info, subscription_info, basic_info))
    subscriber = (_boolean(sub.get('enable')) is True
                  or _boolean(basic.get('have_super_fans_permission')) is True)
    star = (_boolean(create.get('star_comment_qualification')) is True
            and _boolean(create.get('star_comment_permission_switch')) is True)
    return {
        'subscriber_available': subscriber,
        'subscriber_reason': '' if subscriber else 'TikTok has not granted subscriber/Super Fans chat access to this account.',
        'star_available': star,
        'star_reason': '' if star else str(create.get('star_comment_permission_switch_off_reason')
                                         or 'TikTok has not confirmed Star Comments eligibility for this account.'),
    }


def validate_capabilities(state, changes):
    """Validate enabling before any write; disabling requires no eligibility grant."""
    if changes.get('subscriber_only_chat') is True and not state.get('subscriber_available'):
        raise LiveManagementError(state.get('subscriber_reason') or 'Subscriber-only chat is unavailable.')
    if changes.get('star_comments') is True and not state.get('star_available'):
        raise LiveManagementError(state.get('star_reason') or 'Star Comments are unavailable.')
    if any(key in changes for key in ('star_grant_group', 'star_grant_level')) and not state.get('star_available'):
        raise LiveManagementError(state.get('star_reason') or 'Star Comments settings are unavailable.')


class LiveManagement:
    def __init__(self, stream, room_id='', priority_region='', expected_user_id='', is_current=lambda: True):
        self.stream = stream
        self.room_id = _identifier(room_id, 'Room ID') if room_id else ''
        self.priority_region = priority_region
        self._bound_account_id = _identifier(expected_user_id, 'Expected account ID') if expected_user_id else None
        self.is_current = is_current

    def _check_context(self):
        if not self.is_current():
            raise LiveManagementError('The account or LIVE changed. Reload LIVE management before continuing.')

    @property
    def _mobile(self):
        return self.stream.client.kind == 'mobile'

    def _require_studio(self):
        if self._mobile:
            raise LiveManagementError('Use the saved PC/Studio device profile for LIVE management, including Android-created rooms.')

    def _params(self, extra=None):
        record = self.stream.client.record
        params = self.stream._studio_params(device_id=record.get('device_id', ''),
                                            install_id=record.get('install_id', ''),
                                            priority_region=self.priority_region)
        params.update(extra or {})
        return params

    def _url(self, endpoint):
        return self.stream.getServerUrl().rstrip('/') + '/' + endpoint.lstrip('/')

    def _get(self, endpoint, extra=None, *, action='Load LIVE settings', mutation=False):
        self._check_context()
        response = self.stream._signed_get_json(self._url(endpoint), params=self._params(extra),
            priority_region=self.priority_region, timeout=20, **({'retry': False} if mutation else {}))
        return _checked(response, action)

    def _post(self, endpoint, body, *, action, mode='form'):
        self._check_context()
        request = self.stream._signed_post_json if mode == 'json' else self.stream._signed_post_form
        args = {'payload': body} if mode == 'json' else {'data': {} if mode == 'query' else body}
        response = request(self._url(endpoint), params=self._params(body if mode == 'query' else None),
            priority_region=self.priority_region, timeout=20, retry=False, **args)
        return _checked(response, action)

    def _resolve_sec(self, uid, anchor_id):
        user = _dict(self._get('webcast/user/', {'target_uid': uid, 'anchor_id': anchor_id}, action='Identify LIVE user'))
        if _identifier(user.get('id_str') or user.get('id'), 'Returned user ID') != uid:
            raise LiveManagementError('TikTok returned a different user while resolving LIVE identity.')
        sec = user.get('sec_uid')
        if not isinstance(sec, str) or not sec.strip():
            raise LiveManagementError('TikTok did not return the requested user’s secure ID.')
        return sec

    def _account(self, *, need_sec=False):
        data = _dict(self.stream._cookie_account_info(self.priority_region))
        uid = _identifier(data.get('user_id_str') or data.get('user_id'), 'Signed-in account ID')
        if self._bound_account_id is not None and self._bound_account_id != uid:
            raise LiveManagementError('The signed-in account changed. Reload LIVE management before continuing.')
        self._bound_account_id = uid
        sec = data.get('sec_user_id') or data.get('sec_uid')
        if need_sec and (not isinstance(sec, str) or not sec.strip()):
            sec = self._resolve_sec(uid, uid)
        return uid, sec

    def _room(self, account_id):
        if not self.room_id:
            raise LiveManagementError('Start or resume your LIVE before using this control.')
        data = self._get('webcast/room/info/', {'room_id': self.room_id}, action='Verify LIVE room')
        room = _dict(data)
        if isinstance(room.get('room'), dict):
            room = room['room']
        rid = room.get('id_str') or room.get('id')
        if rid is not None and str(rid) != self.room_id:
            raise LiveManagementError('TikTok returned a different LIVE room. Reload LIVE management.')
        owner = _dict(room.get('owner'))
        owner_id = room.get('owner_user_id_str') or room.get('owner_user_id') or owner.get('id_str') or owner.get('id')
        if not owner_id or str(owner_id) != account_id:
            raise LiveManagementError('Cannot verify that this LIVE room belongs to the selected account.')
        if room.get('status') in (4, '4'):
            raise LiveManagementError('This LIVE has ended. Reload LIVE management.')
        return room

    def _owner_context(self, *, need_room=False, need_sec=False):
        uid, sec = self._account(need_sec=need_sec)
        if need_room or self.room_id:
            self._room(uid)
        return uid, sec

    def get_chat_settings(self):
        self._require_studio()
        uid, sec = self._account(need_sec=True)
        room = self._room(uid) if self.room_id else {}
        auth, star = _dict(room.get('room_auth')), _dict(room.get('star_comment_config'))
        state = {'user_id': uid, 'room_id': self.room_id,
            'allow_comments': _boolean(auth.get('Chat')),
            'filter_comments': _boolean(auth.get('ChatL2')),
            'subscriber_only_chat': _boolean(auth.get('ChatSubOnly')),
            'star_comments': _boolean(star.get('star_comment_switch')),
            'star_grant_group': star.get('grant_group'), 'star_grant_level': star.get('grant_level')}
        values, errors = {}, {}
        for key, endpoint, params in (
            ('create', 'webcast/room/create_info/', {} if self._mobile else {'live_studio': '1'}),
            ('sub', 'webcast/sub/privilege/get_sub_info/', {'sec_anchor_id': sec, 'source': 'live_take_page', 'need_entrance_data': 'true'}),
            ('basic', 'webcast/game/basic/create_info/', {}),
        ):
            try:
                values[key] = _dict(self._get(endpoint, params, action='Load ' + key + ' permissions'))
            except Exception as exc:
                errors[key] = str(exc)
        state.update(chat_availability(values.get('create'), values.get('sub'), values.get('basic')))
        if not self.room_id:
            create_star = _dict(_dict(values.get('create')).get('star_comment_config'))
            state['star_grant_group'] = create_star.get('grant_group')
            state['star_grant_level'] = create_star.get('grant_level')
        if 'star_comment_qualification' in star and _boolean(star['star_comment_qualification']) is not True:
            state['star_available'] = False
            state['star_reason'] = 'Star Comments are not enabled for this LIVE room.'
        if 'star_comment_permission_switch' in auth:
            permission = _dict(auth['star_comment_permission_switch'])
            # Room permission is an enum: Unknown=0, On=1, Off=2.
            if permission.get('status') not in (1, '1'):
                state['star_available'] = False
                state['star_reason'] = str(permission.get('OffReason') or 'TikTok has not granted Star Comments permission for this LIVE room.')
        if not state['subscriber_available'] and ('sub' in errors or 'basic' in errors):
            state['subscriber_reason'] += ' ' + ' '.join(errors[k] for k in ('sub', 'basic') if k in errors)
        if not state['star_available'] and 'create' in errors:
            state['star_reason'] += ' ' + errors['create']
        state['permission_errors'] = errors
        return state

    def prepare_creation(self, changes):
        state = self.get_chat_settings()
        validate_capabilities(state, changes)
        return state

    def update_chat_settings(self, changes):
        if not isinstance(changes, dict):
            raise ValueError('Chat settings changes must be a dictionary.')
        switches = {'allow_comments': 3, 'filter_comments': 4, 'subscriber_only_chat': 7}
        booleans = set(switches) | {'star_comments'}
        unknown = set(changes) - booleans - {'star_grant_group', 'star_grant_level'}
        if unknown:
            raise ValueError('Unknown chat settings: ' + ', '.join(sorted(unknown)))
        for key in booleans & changes.keys():
            if type(changes[key]) is not bool:
                raise ValueError(f'{key} must be true or false.')
        if 'star_grant_group' in changes and (type(changes['star_grant_group']) is not int or changes['star_grant_group'] not in (1, 2, 3)):
            raise ValueError('Star Comments audience must be all users (1), user level (2), or fan level (3).')
        if 'star_grant_level' in changes and (type(changes['star_grant_level']) is not int or not 0 <= changes['star_grant_level'] <= 2147483647):
            raise ValueError('Star Comments minimum level must be a nonnegative integer.')
        if not self.room_id:
            raise LiveManagementError('Start or resume your LIVE before updating live chat settings.')
        state = self.get_chat_settings()
        changes = {key: value for key, value in changes.items() if state.get(key) != value}
        validate_capabilities(state, changes)
        if changes.get('subscriber_only_chat') is True and changes.get('allow_comments', state.get('allow_comments')) is not True:
            raise ValueError('Allow comments before enabling subscriber-only chat.')
        applied = []
        try:
            for key, switch_type in switches.items():
                if key in changes:
                    self._post('webcast/room/switch/update/', {'room_id': self.room_id,
                        'switch_type': switch_type, 'switch_value': str(changes[key]).lower()},
                        action='Update ' + key.replace('_', ' '))
                    state[key] = changes[key]
                    applied.append(key)
            star_keys = {'star_comments', 'star_grant_group', 'star_grant_level'} & changes.keys()
            if star_keys:
                params = {'room_id': self.room_id}
                for key, field in (('star_comments', 'star_comment_switch'), ('star_grant_group', 'grant_group'), ('star_grant_level', 'grant_level')):
                    value = changes.get(key, state.get(key))
                    if value is not None:
                        params[field] = str(value).lower() if type(value) is bool else value
                self._get('webcast/room/star_comment/update/', params, action='Update Star Comments', mutation=True)
                for key in sorted(star_keys):
                    state[key] = changes[key]
                    applied.append(key)
        except Exception as exc:
            if applied:
                raise LiveManagementError('Applied ' + ', '.join(applied) + '; remaining changes failed: ' + str(exc)) from exc
            raise
        if applied:
            try:
                state = self.get_chat_settings()
                unconfirmed = [key for key in applied if state.get(key) != changes[key]]
                if unconfirmed:
                    state['refresh_warning'] = ('TikTok accepted the update, but did not report the requested value for: '
                                                + ', '.join(key.replace('_', ' ') for key in unconfirmed) + '. Refresh to check again.')
            except Exception as exc:
                state['refresh_warning'] = 'TikTok accepted the update, but the settings refresh failed: ' + str(exc)
        state['applied'] = applied
        return state

    def get_words(self):
        _, sec = self._owner_context(need_sec=True)
        data = self._get('webcast/room/get_sensitive_word/', {'sec_anchor_id': sec, 'room_id': self.room_id}, action='Load blocked words')
        if not isinstance(data, dict):
            raise LiveManagementError('TikTok returned an invalid blocked-word response.')
        words = data.get('word', [])
        if not isinstance(words, list):
            raise LiveManagementError('TikTok returned an invalid blocked-word list.')
        result = []
        for entry in words:
            if not isinstance(entry, dict) or not isinstance(entry.get('content'), str) or entry.get('id') is None:
                raise LiveManagementError('TikTok returned an invalid blocked-word entry.')
            result.append({'id': str(entry['id']), 'word': entry['content']})
        return result

    def add_word(self, word):
        if not isinstance(word, str) or not word.strip():
            raise ValueError('Enter a nonempty blocked word.')
        word = word.strip()
        if len(word.encode('utf-16-le')) // 2 > 30:
            raise ValueError('A blocked word can contain at most 30 characters.')
        words = self.get_words()
        if any(entry['word'] == word for entry in words):
            raise ValueError('That blocked word already exists.')
        if len(words) >= 500:
            raise ValueError('TikTok allows at most 500 blocked words.')
        _, sec = self._owner_context(need_sec=True)
        body = {'word': word, 'sec_anchor_id': sec, 'room_id': self.room_id}
        if self._mobile:
            body.update(block_similar_versions=0, force_add='false')
            data = _dict(self._get('webcast/room/add_sensitive_word/', body, action='Add blocked word', mutation=True))
        else:
            data = _dict(self._post('webcast/room/add_sensitive_word/', body, action='Add blocked word'))
        if data.get('id') is None:
            raise LiveManagementError('TikTok accepted the request but returned no word ID. Reload the word list before retrying.')
        return {'id': str(data['id']), 'word': word}

    def delete_word(self, word_id):
        word_id = _identifier(word_id, 'Blocked word ID')
        words = self.get_words()
        if not any(entry['id'] == word_id for entry in words):
            raise ValueError('That blocked word is no longer in this account’s list. Reload the list.')
        _, sec = self._owner_context(need_sec=True)
        body = {'word_id': word_id, 'sec_anchor_id': sec, 'room_id': self.room_id}
        if self._mobile:
            self._get('webcast/room/del_sensitive_word/', body, action='Delete blocked word', mutation=True)
        else:
            self._post('webcast/room/del_sensitive_word/', body, action='Delete blocked word')

    def moderate_user(self, user_id, action, duration=300):
        user_id = _identifier(user_id, 'Viewer ID')
        if action not in ('mute', 'unmute', 'block', 'unblock'):
            raise ValueError('Choose mute, unmute, block, or unblock.')
        if action == 'mute' and (type(duration) is not int or duration < 0 or duration > 2147483647):
            raise ValueError('Mute duration must be a nonnegative number of seconds.')
        uid, _ = self._owner_context(need_room=True)
        if uid == user_id:
            raise ValueError('You cannot moderate your own account.')
        body = {'room_id': self.room_id}
        endpoints = {'mute': 'silence/', 'unmute': 'unsilence/', 'block': 'kick/user/', 'unblock': 'unkick/user/'}
        if action in ('mute', 'unmute'):
            body['user_id'] = user_id
            if self._mobile:
                body['sec_user_id'] = self._resolve_sec(user_id, uid)
            if action == 'mute':
                body.update(duration=duration, silence_type=int(duration != 0))
        else:
            body['kick_uid'] = user_id
        endpoint = 'webcast/room/' + endpoints[action]
        if self._mobile and action == 'unblock':
            return self._get(endpoint, body, action='Unblock viewer', mutation=True)
        return self._post(endpoint, body, action=action.capitalize() + ' viewer',
                          mode='query' if self._mobile else ('form' if action == 'unblock' else 'json'))

    def get_moderators(self):
        self._require_studio()
        uid, _ = self._owner_context()
        params = {'anchor_id': uid}
        if self.room_id:
            params['room_id'] = self.room_id
        data = self._get('webcast/user/admin/list/', params, action='Load moderators')
        if not isinstance(data, list):
            raise LiveManagementError('TikTok returned an invalid moderator list.')
        result = []
        for entry in data:
            user = _dict(_dict(entry).get('user_info'))
            user_id = _identifier(user.get('id_str') or user.get('id'), 'Moderator ID')
            result.append({'id': user_id, 'name': str(user.get('nickname') or user.get('display_id') or user_id)})
        return result

    def set_moderator(self, user_id, enabled):
        self._require_studio()
        user_id = _identifier(user_id, 'Moderator ID')
        if type(enabled) is not bool:
            raise ValueError('Moderator enabled must be true or false.')
        uid, _ = self._owner_context()
        if uid == user_id:
            raise ValueError('The host cannot be assigned as their own moderator.')
        body = {'anchor_id': uid, 'to_user_id': user_id, 'update_type': 3 if enabled else 2}
        if self.room_id:
            body['current_room_id'] = self.room_id
        return self._post('webcast/user/admin/update/', body,
            action='Add moderator' if enabled else 'Remove moderator')

    def get_about_me(self):
        uid, _ = self._owner_context()
        data = _dict(self._get('webcast/anchor/about_me/', action='Load LIVE intro'))
        about = data.get('about_me')
        if not isinstance(about, dict):
            raise LiveManagementError('TikTok returned an unrecognized LIVE intro response.')
        raw_templates = about.get('template_list', [])
        if not isinstance(raw_templates, list):
            raise LiveManagementError('TikTok returned invalid LIVE intro templates.')
        current_id = str(about.get('current_template_id') or '')
        templates, content = [], ''
        for template in raw_templates:
            if not isinstance(template, dict) or template.get('id') is None:
                raise LiveManagementError('TikTok returned an invalid LIVE intro template.')
            tid = str(template['id'])
            boxes = template.get('input_box_list') or []
            if not isinstance(boxes, list) or any(not isinstance(box, dict) for box in boxes):
                raise LiveManagementError('TikTok returned invalid LIVE intro inputs.')
            first = boxes[0] if boxes else {}
            limit = first.get('max_character_count', 240)
            if type(limit) is not int or limit < 1:
                raise LiveManagementError('TikTok returned an invalid LIVE intro length limit.')
            templates.append({'id': tid, 'name': str(template.get('name') or template.get('title') or f'Template {tid}'),
                              'max_length': limit, 'input_boxes': deepcopy(boxes), 'raw': deepcopy(template)})
            if tid == current_id and about.get('switch_status') is not False:
                content = str(first.get('content') or '')
        return {'user_id': uid, 'content': content, 'current_template_id': current_id, 'templates': templates,
                'audit_status': about.get('audit_status'), 'enabled': _boolean(about.get('switch_status')),
                'raw': deepcopy(about)}

    def set_about_me(self, template_id, content):
        self._require_studio()
        if not isinstance(content, str) or not content.strip():
            raise ValueError('Enter intro text, or use Clear intro to remove it.')
        if re.fullmatch(r'[0-9]+', content.strip()):
            raise ValueError('LIVE intro cannot contain only numbers.')
        info = self.get_about_me()
        template = next((entry for entry in info['templates'] if entry['id'] == str(template_id)), None)
        if template is None:
            raise ValueError('Choose a template returned by TikTok for this account.')
        if len(content.encode('utf-16-le')) // 2 > template['max_length']:
            raise ValueError(f'LIVE intro must contain at most {template["max_length"]} characters.')
        if len(template['input_boxes']) != 1:
            raise ValueError('Choose a single-input LIVE intro template.')
        return self._post('webcast/anchor/about_me/update/', {'template_id': template['id'], 'method_type': 1,
                            'input_content_list': [content]}, action='Save LIVE intro', mode='json')

    def clear_about_me(self):
        self._require_studio()
        self._owner_context()
        return self._post('webcast/anchor/about_me/update/', {'method_type': 2}, action='Clear LIVE intro', mode='json')
