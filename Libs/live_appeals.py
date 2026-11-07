"""Account-bound LIVE appeals traced in TikTok's official LIVE Center frontend.

History details use perception/violation/info and the unified reason form.
Snapshot restrictions use eco/appeal_detail, check_appeal, then appeal.
Reading details never submits an appeal. Mutations are single-attempt.
"""
from copy import deepcopy
from urllib.parse import parse_qs, urlencode, urlsplit

from Libs.live_management import LiveManagementError, _checked, _dict, _identifier


APPEAL_STATUSES = {
    0: 'Appeal unavailable', 1: 'Not appealed', 2: 'Under review',
    3: 'Approved', 4: 'Not approved', 5: 'LIVE ended', 6: 'Penalty expired',
    7: 'Appeal deadline passed', 8: 'Related LIVE ban', 9: 'Approved; restriction remains',
}
SNAPSHOT_STATUSES = {0: 'Not appealed', 1: 'Under review', 2: 'Not approved',
                     3: 'Penalty adjusted', 4: 'Permission restored', 5: 'Approved',
                     6: 'New restriction', 7: 'Permanent restriction'}
APPEAL_REASONS = (
    ('I do not understand the reason', 'pm_mt_rulesGuidance_feedback_sheet_understand_reason'),
    ('I think the restriction is a mistake', 'pm_mt_rulesGuidance_feedback_sheet_wrong_reason'),
    ('I do not think I violated the Community Guidelines', 'pm_mt_rulesGuidance_feedback_sheet_cg_reason'),
    ('I think the penalty is too severe', 'pm_mt_rulesGuidance_feedback_sheet_harsh_reason'),
    ('Other', 'pm_mt_rulesGuidance_feedback_sheet_other_reason'),
)


def appeal_status(value):
    return APPEAL_STATUSES.get(value, 'Status unavailable') if type(value) is int else 'Status unavailable'


def record_id(record):
    punish = _dict(_dict(record).get('punish_info'))
    value = punish.get('punish_record_id_str') or punish.get('punish_record_id')
    return str(value) if value is not None else ''


def record_key(record):
    """Keep violation and punishment IDs distinct; either can identify a list row."""
    record = _dict(record)
    return (str(record.get('violation_id_str') or record.get('violation_id') or ''), record_id(record))


def _detail_link(value):
    """Unwrap official navigation without loading a URL or accepting arbitrary schemes."""
    query = {}
    for _ in range(4):
        if not isinstance(value, str) or len(value) > 16384 or any(ord(c) < 32 for c in value):
            return '', {}
        try:
            parts = urlsplit(value)
            params = parse_qs(parts.query, keep_blank_values=True)
            if any(len(v) != 1 for v in params.values()):
                return '', {}
            for key, values in params.items():
                if key != 'url':
                    if key in query and query[key] != values[0]:
                        return '', {}
                    query[key] = values[0]
            if parts.scheme in ('sslocal', 'aweme') and parts.netloc in (
                    'webview', 'webcast_webview', 'webcast_webview_popup', 'webcast_lynxview', 'webcast_lynxview_popup'):
                value = params.get('url', [''])[0]
                continue
            host = (parts.hostname or '').lower()
            if (parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443)
                    or not any(host == h or host.endswith('.' + h) for h in ('tiktok.com', 'tiktokv.com', 'tiktokcdn.com'))):
                return '', {}
            return value, query
        except ValueError:
            return '', {}
    return '', {}


def appeal_route(record):
    url, query = _detail_link(_dict(_dict(record).get('punish_info')).get('detail_url'))
    path = urlsplit(url).path if url else ''
    if query.get('snapshot_id') and ('ban_detail' in path or 'ban-detail' in path):
        snapshot = _identifier(query['snapshot_id'], 'Appeal snapshot ID')
        return {'kind': 'snapshot', 'id': snapshot, 'feature_type': query.get('feature_type', ''),
                'official_url': 'https://livecenter.tiktok.com/treco/ban_detail?' + urlencode(
                    {'snapshot_id': snapshot, 'feature_type': query.get('feature_type', '')})}
    # The public punish-detail UI fetches with record_id || punish_id.
    # Fall back to the list's explicit punishment record ID, never violation_id.
    generic_path = 'punish_detail' in path or 'punish-detail' in path
    identifier = (query.get('record_id') or query.get('punish_id')) if generic_path else record_id(record)
    if identifier:
        identifier = _identifier(identifier, 'Punishment record ID')
        return {'kind': 'general', 'id': identifier, 'official_url':
                'https://livecenter.tiktok.com/punish_detail?' + urlencode({'record_id': identifier})}
    return {'kind': 'external', 'id': '', 'official_url': url if url and not path.endswith('.js') else ''}


class LiveAppeals:
    def __init__(self, stream, record, *, priority_region='', expected_user_id='', is_current=lambda: True):
        self.stream = stream
        self.selected = deepcopy(record)
        self.priority_region = priority_region
        self.user_id = str(expected_user_id or '')
        self.is_current = is_current

    def _context(self):
        if not self.is_current():
            raise LiveManagementError('The selected account changed. Reopen this violation.')
        if self.stream.client.kind != 'pc':
            raise LiveManagementError('Use the saved PC device profile for LIVE appeals.')

    def _account(self):
        self._context()
        account = _dict(self.stream._cookie_account_info(self.priority_region))
        uid = _identifier(account.get('user_id_str') or account.get('user_id'), 'Signed-in account ID')
        if self.user_id and uid != self.user_id:
            raise LiveManagementError('The signed-in account changed. Reopen this violation.')
        self.user_id = uid

    def _request(self, endpoint, fields, *, post=False):
        self._context()
        profile = self.stream.client.record
        params = self.stream._studio_params(device_id=profile.get('device_id', ''),
            install_id=profile.get('install_id', ''), priority_region=self.priority_region)
        url = self.stream.getServerUrl().rstrip('/') + '/webcast/' + endpoint
        if post:
            response = self.stream._signed_post_json(url, params=params, payload=fields,
                priority_region=self.priority_region, timeout=20, retry=False)
        else:
            fields = {**fields, 'language': 'en'}
            params.update(fields)
            response = self.stream._signed_get_json(url, params=params,
                priority_region=self.priority_region, timeout=20)
        return _checked(response, 'LIVE appeal')

    def _fresh_record(self):
        self._account()
        key = record_key(self.selected)
        if not any(key):
            raise ValueError('This violation has no usable record identifier.')
        profile = self.stream.client.record
        errors = []
        for kind in (0, 1):
            try:
                result = self.stream.getEcoViolationList(device_id=profile.get('device_id', ''),
                    install_id=profile.get('install_id', ''), priority_region=self.priority_region, violation_list_type=kind)
            except Exception as exc:
                errors.append(str(exc))
                continue
            for record in result.get('records', []):
                if record_key(record) == key:
                    return deepcopy(record)
        raise LiveManagementError('This violation could not be verified in the selected account. Refresh Safety.'
                                  + (' ' + errors[0] if errors else ''))

    def load(self):
        record = self._fresh_record()
        route = appeal_route(record)
        state = {'user_id': self.user_id, 'record': record, 'route': route, 'can_submit': False,
                 'reason': 'Open TikTok’s official details for this type of restriction.'}
        if route['kind'] == 'snapshot':
            data = self._request('eco/appeal_detail/', {'snapshot_id': route['id'],
                'feature_type': route['feature_type'], 'version_code': 1}, post=True)
            if not isinstance(data, dict):
                raise LiveManagementError('TikTok returned unrecognized appeal details.')
            detail_uid = data.get('user_id_str') or data.get('user_id')
            if not detail_uid or str(detail_uid) != self.user_id:
                raise LiveManagementError('The appeal details do not belong to the selected account.')
            allowed, reason = False, 'TikTok is not offering an appeal for this restriction.'
            if data.get('show_appeal_button') is True:
                check = self._request('eco/check_appeal/', {'snapshot_id': route['id']}, post=True)
                if not isinstance(check, dict):
                    raise LiveManagementError('TikTok did not confirm appeal eligibility.')
                status = check.get('check_status')
                allowed = (type(status) is int and status == 1) if status else check.get('status') is True
                reason = '' if allowed else {
                    2: 'A related LIVE ban prevents this appeal.', 3: 'This restriction has already been appealed.',
                    4: 'This permission has already been restored.'}.get(status, 'TikTok is not allowing this appeal.')
            state.update(detail=data, can_submit=allowed,
                         status=(SNAPSHOT_STATUSES.get(data['status'], 'Status unavailable')
                                 if type(data.get('status')) is int else 'Status unavailable'), reason=reason)
        elif route['kind'] == 'general':
            listed_id = record_id(record)
            data = self._request('perception/violation/info/', {'punish_id': route['id']})
            if not isinstance(data, dict) or not isinstance(data.get('violation_record'), dict):
                raise LiveManagementError('TikTok returned unrecognized violation details.')
            record = data['violation_record']
            original_violation, _ = record_key(self.selected)
            detail_violation, _ = record_key(record)
            submission_id = record_id(record)
            if (not submission_id or (listed_id and submission_id != listed_id) or
                    (not listed_id and (not original_violation or original_violation != detail_violation)) or
                    (original_violation and detail_violation and original_violation != detail_violation)):
                raise LiveManagementError('TikTok returned a different violation. Refresh Safety.')
            # A detail URL can use an alias; the official form submits the
            # verified record ID returned by detail, not that lookup alias.
            route['submission_id'] = _identifier(submission_id, 'Punishment record ID')
            route['official_url'] = 'https://livecenter.tiktok.com/punish_detail?' + urlencode({'record_id': submission_id})
            detail, punish = _dict(data.get('detail')), _dict(record.get('punish_info'))
            status = punish.get('appeal_status')
            specialized = detail.get('punish_type_id', punish.get('punish_type_id')) in (45, 99)
            can_submit = type(status) is int and status == 1 and not specialized
            state.update(record=record, detail=detail, status=appeal_status(status), can_submit=can_submit,
                         reason=('This copyright restriction requires TikTok’s official evidence form.' if specialized
                                 else '' if can_submit else 'TikTok is not offering a new appeal for this violation.'))
        else:
            state['status'] = appeal_status(_dict(record.get('punish_info')).get('appeal_status'))
        return state

    def submit(self, expected_route, reason_key='', explanation=''):
        state = self.load()  # Fresh account, membership, details and eligibility before any mutation.
        route = state['route']
        if route != expected_route:
            raise LiveManagementError('The appeal route changed. Refresh the details before submitting.')
        if not state['can_submit']:
            raise LiveManagementError(state['reason'] or 'This restriction cannot be appealed again.')
        if route['kind'] == 'snapshot':
            endpoint, body = 'eco/appeal/', {'snapshot_id': route['id']}
        else:
            if reason_key not in {key for _, key in APPEAL_REASONS}:
                raise ValueError('Select a reason for your appeal.')
            if not isinstance(explanation, str):
                raise ValueError('The appeal explanation must be text.')
            explanation = explanation.strip()
            if len(explanation.encode('utf-16-le')) // 2 > 140:
                raise ValueError('The appeal explanation can contain at most 140 characters.')
            if reason_key == APPEAL_REASONS[-1][1]:
                if not explanation:
                    raise ValueError('Explain your appeal when selecting Other.')
            else:
                explanation = ''  # Official form exposes an explanation only for Other.
            endpoint, body = 'perception/appeal/', {'punish_id': route['submission_id'], 'text_evidence_title': reason_key,
                'text_evidence_desc': explanation, 'appeal_req_scene': 4, 'enter_from': 'rg_violation_list', 'language': 'en'}
        self._account()
        self._request(endpoint, body, post=True)
        result = {'user_id': self.user_id, 'submitted': True, 'state': state}
        try:
            result['state'] = self.load()
        except Exception as exc:
            result['refresh_warning'] = 'TikTok accepted the appeal, but the status refresh failed: ' + str(exc)
        return result
