"""Offline official appeal contracts, eligibility and account isolation."""
import copy
import unittest
from urllib.parse import urlencode

from Libs.live_appeals import APPEAL_REASONS, LiveAppeals, appeal_route, appeal_status
from Libs.live_management import LiveManagementError
from tests.test_live_management import FakeStream


def violation(status=1):
    return {'violation_id_str': '100', 'live_info': {'title': 'My LIVE'},
            'punish_info': {'punish_record_id_str': '200', 'punish_title': 'LIVE visibility restriction',
                'punish_reason': 'Community Guidelines', 'appeal_status': status,
                'detail_url': 'https://livecenter.tiktok.com/punish_detail?record_id=200'}}


class AppealStream(FakeStream):
    def __init__(self):
        super().__init__()
        self.record = violation()
        self.records = [self.record]
        self.responses['webcast/perception/violation/info/'] = {'violation_record': self.record,
                                                             'detail': {'punish_type_id': 29}}
        self.responses['webcast/eco/appeal_detail/'] = {'user_id_str': '123', 'punish_id_str': '200',
            'status': 0, 'show_appeal_button': True, 'violation_reason': ['Community Guidelines']}
        self.responses['webcast/eco/check_appeal/'] = {'status': True, 'check_status': 1}

    def getEcoViolationList(self, **kwargs):
        self.calls.append(('LIST', 'eco-list', kwargs))
        return {'records': copy.deepcopy(self.records)}

    def submissions(self):
        return [c for c in self.calls if c[1] in ('webcast/perception/appeal/', 'webcast/eco/appeal/')]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class AppealTests(unittest.TestCase):
    def setUp(self):
        self.stream = AppealStream()
        self.service = LiveAppeals(self.stream, copy.deepcopy(self.stream.record), expected_user_id='123')

    def snapshot(self):
        self.stream.record['punish_info']['detail_url'] = 'https://livecenter.tiktok.com/treco/ban_detail?snapshot_id=9000000000000000001&feature_type=ranking'
        return self.service.load()

    def test_reading_details_never_submits_and_uses_record_id(self):
        state = self.service.load()
        self.assertTrue(state['can_submit'])
        call = next(c for c in self.stream.calls if '/violation/info/' in c[1])
        self.assertEqual(call[2]['params']['punish_id'], '200')
        self.assertEqual(call[2]['params']['language'], 'en')
        self.assertEqual(self.stream.submissions(), [])

    def test_generic_submit_uses_fresh_id_reason_key_and_exact_json(self):
        route = self.service.load()['route']
        result = self.service.submit(route, APPEAL_REASONS[-1][1], '  Please review this restriction.  ')
        self.assertTrue(result['submitted'])
        call, = self.stream.submissions()
        self.assertEqual(call[0], 'JSON')
        self.assertIs(call[2]['retry'], False)
        self.assertEqual(call[2]['payload'], {'punish_id': '200',
            'text_evidence_title': APPEAL_REASONS[-1][1], 'text_evidence_desc': 'Please review this restriction.',
            'appeal_req_scene': 4, 'enter_from': 'rg_violation_list', 'language': 'en'})

    def test_regular_reason_has_no_hidden_explanation(self):
        self.service.submit(self.service.load()['route'], APPEAL_REASONS[0][1], 'Old text')
        self.assertEqual(self.stream.submissions()[0][2]['payload']['text_evidence_desc'], '')

    def test_lookup_alias_never_replaces_verified_submission_record_id(self):
        self.stream.record['punish_info']['detail_url'] = 'https://livecenter.tiktok.com/punish_detail?punish_id=999'
        state = self.service.load()
        self.assertEqual(state['route']['id'], '999')
        self.assertEqual(state['route']['submission_id'], '200')
        self.service.submit(state['route'], APPEAL_REASONS[0][1])
        self.assertEqual(self.stream.submissions()[0][2]['payload']['punish_id'], '200')

    def test_validation_of_reason_and_utf16_length_before_submission(self):
        route = self.service.load()['route']
        for key, text in [('', ''), ('unknown', 'text'), (APPEAL_REASONS[-1][1], '  '),
                          (APPEAL_REASONS[-1][1], '😀' * 71)]:
            with self.subTest(key=key, text=text), self.assertRaises(ValueError):
                self.service.submit(route, key, text)
        self.assertEqual(self.stream.submissions(), [])

    def test_all_noneligible_statuses_and_copyright_cannot_use_generic_submit(self):
        for status in [0, 2, 3, 4, 5, 6, 7, 8, 9, 500, '1', None, True]:
            self.stream.record['punish_info']['appeal_status'] = status
            state = self.service.load()
            self.assertFalse(state['can_submit'])
            with self.assertRaises(LiveManagementError):
                self.service.submit(state['route'], APPEAL_REASONS[0][1])
        self.stream.record['punish_info']['appeal_status'] = 1
        for kind in (45, 99):
            self.stream.responses['webcast/perception/violation/info/']['detail']['punish_type_id'] = kind
            state = self.service.load()
            self.assertFalse(state['can_submit'])
            self.assertIn('copyright', state['reason'])
            self.assertIn('/punish_detail?', state['route']['official_url'])
        self.assertEqual(self.stream.submissions(), [])

    def test_stale_eligibility_rechecked_before_submit(self):
        route = self.service.load()['route']
        self.stream.record['punish_info']['appeal_status'] = 2
        with self.assertRaises(LiveManagementError):
            self.service.submit(route, APPEAL_REASONS[0][1])
        self.assertEqual(self.stream.submissions(), [])

    def test_cookie_account_swap_and_missing_membership_block_submission(self):
        route = self.service.load()['route']
        self.stream.account['user_id_str'] = '999'
        with self.assertRaisesRegex(LiveManagementError, 'account changed'):
            self.service.submit(route, APPEAL_REASONS[0][1])
        self.stream.account['user_id_str'] = '123'
        self.stream.records = [violation()]
        self.stream.records[0]['violation_id_str'] = '999'
        with self.assertRaisesRegex(LiveManagementError, 'could not be verified'):
            self.service.submit(route, APPEAL_REASONS[0][1])
        self.assertEqual(self.stream.submissions(), [])

    def test_wrong_detail_record_is_rejected(self):
        self.stream.responses['webcast/perception/violation/info/']['violation_record'] = violation()
        self.stream.responses['webcast/perception/violation/info/']['violation_record']['punish_info']['punish_record_id_str'] = '999'
        with self.assertRaisesRegex(LiveManagementError, 'different violation'):
            self.service.load()

    def test_snapshot_uses_actual_url_snapshot_with_separate_status_enum(self):
        state = self.snapshot()
        self.assertEqual(state['status'], 'Not appealed')
        self.assertTrue(state['can_submit'])
        self.assertEqual(self.stream.submissions(), [])
        self.service.submit(state['route'])
        call, = self.stream.submissions()
        self.assertEqual(call[1], 'webcast/eco/appeal/')
        self.assertEqual(call[2]['payload'], {'snapshot_id': '9000000000000000001'})
        detail = next(c for c in self.stream.calls if c[1] == 'webcast/eco/appeal_detail/')
        self.assertEqual(detail[2]['payload'], {'snapshot_id': '9000000000000000001', 'feature_type': 'ranking', 'version_code': 1})

    def test_snapshot_check_enum_overrides_legacy_flag_and_blocks_repeat(self):
        state = self.snapshot()
        for status in (2, 3, 4, 99, True):
            self.stream.responses['webcast/eco/check_appeal/'] = {'status': True, 'check_status': status}
            self.assertFalse(self.service.load()['can_submit'])
            with self.assertRaises(LiveManagementError):
                self.service.submit(state['route'])
        self.stream.responses['webcast/eco/check_appeal/'] = {'status': True}
        self.assertTrue(self.service.load()['can_submit'])
        self.assertEqual(self.stream.submissions(), [])

    def test_snapshot_needs_server_button_and_matching_owner(self):
        self.snapshot()
        detail = self.stream.responses['webcast/eco/appeal_detail/']
        detail['show_appeal_button'] = False
        self.assertFalse(self.service.load()['can_submit'])
        detail['user_id_str'] = '999'
        with self.assertRaisesRegex(LiveManagementError, 'do not belong'):
            self.service.load()

    def test_context_change_prevents_write_and_route_change_needs_review(self):
        route = self.service.load()['route']
        self.service.is_current = lambda: False
        with self.assertRaises(LiveManagementError):
            self.service.submit(route, APPEAL_REASONS[0][1])
        self.service.is_current = lambda: True
        self.snapshot()
        with self.assertRaisesRegex(LiveManagementError, 'route changed'):
            self.service.submit(route, APPEAL_REASONS[0][1])
        self.assertEqual(self.stream.submissions(), [])

    def test_rejection_or_timeout_never_retries_or_claims_success(self):
        route = self.service.load()['route']
        for failure in [ConnectionError('timeout'), {'data': {}}, {'status_code': 9, 'data': {'prompts': 'Appeal closed'}}]:
            self.stream.calls.clear()
            self.stream.failures['webcast/perception/appeal/'] = failure
            with self.assertRaises(Exception):
                self.service.submit(route, APPEAL_REASONS[0][1])
            self.assertEqual(len(self.stream.submissions()), 1)

    def test_refresh_failure_after_acceptance_preserves_receipt(self):
        route = self.service.load()['route']
        original = self.stream._signed_post_json
        def post(*args, **kwargs):
            result = original(*args, **kwargs)
            self.stream.failures['webcast/perception/violation/info/'] = ConnectionError('refresh failed')
            return result
        self.stream._signed_post_json = post
        result = self.service.submit(route, APPEAL_REASONS[0][1])
        self.assertTrue(result['submitted'])
        self.assertIn('accepted', result['refresh_warning'])

    def test_navigation_unwraps_official_urls_and_rejects_untrusted_fallbacks(self):
        record = violation()
        url = record['punish_info']['detail_url']
        record['punish_info']['detail_url'] = 'sslocal://webcast_webview?' + urlencode({'url': url})
        self.assertEqual(appeal_route(record)['id'], '200')
        record['punish_info'].pop('punish_record_id_str')
        for url in ('javascript:alert(1)', 'file:///tmp/foo', 'https://tiktok.com.evil.test/punish_detail?record_id=999',
                    'https://user:secret@livecenter.tiktok.com/foo', 'https://livecenter.tiktok.com:8000/foo'):
            record['punish_info']['detail_url'] = url
            self.assertEqual(appeal_route(record), {'kind': 'external', 'id': '', 'official_url': ''})
        self.assertEqual(appeal_status(True), 'Status unavailable')


if __name__ == '__main__':
    unittest.main()
