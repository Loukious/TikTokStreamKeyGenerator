"""Offline contracts for current-room contribution reads and display data."""
import copy
import unittest

from Libs.live_management import LiveManagementError
from Libs.viewer_contributions import (
    ViewerContributions, comment_parts, emote_url, normalize_summary, parse_viewer_lookup, watch_time_text,
)
from tests.test_live_management import FakeStream


SUMMARY_PATH = 'webcast/room/interaction/user_summary'
EMOTE_URL = 'https://p16-webcast.tiktokcdn.com/example.png'


class ContributionStream(FakeStream):
    def __init__(self):
        super().__init__()
        self.responses[SUMMARY_PATH] = {'watch_duration': 725, 'like_count': 125,
            'share_count': 3, 'comment_count': 8, 'follow_time': 30 * 86400,
            'comment_list': [{'content': '<Great stream> 👀'}, {'content': 'Hello!'}]}
        self.responses['webcast/user/'] = {'id_str': '888', 'follow_info': {'follow_status': 3}}


class ContributionTests(unittest.TestCase):
    def setUp(self):
        self.stream = ContributionStream()
        self.service = ViewerContributions(self.stream, room_id='456', expected_user_id='123', priority_region='TN')

    def test_current_room_contract_and_follow_duration(self):
        result = self.service.load('888')
        self.assertEqual((result['account_id'], result['viewer_id'], result['room_id']), ('123', '888', '456'))
        self.assertEqual((result['watch_duration'], result['like_count'], result['share_count'], result['comment_count']),
                         (725, 125, 3, 8))
        self.assertEqual(result['follow_days'], 30)
        summary = next(call for call in self.stream.calls if call[1] == SUMMARY_PATH)
        self.assertEqual(summary[0], 'GET')
        self.assertEqual({k: summary[2]['params'][k] for k in ('room_id_str', 'user_id_str', 'aid', 'device_id')},
                         {'room_id_str': '456', 'user_id_str': '888', 'aid': '8311', 'device_id': '321'})
        self.assertNotIn('room_id', summary[2]['params'])
        self.assertEqual(self.stream.writes(), [])
        self.assertFalse(any('latest_room' in call[1] for call in self.stream.calls))

    def test_invalid_ids_offline_room_and_wrong_profile_send_no_summary(self):
        for viewer in ('', 'two names', '@@name', 'name.', '0', True, '１２３', '1' * 21):
            with self.subTest(viewer=viewer), self.assertRaises(ValueError):
                self.service.load(viewer)
        self.assertEqual(self.stream.calls, [])
        self.service.room_id = ''
        with self.assertRaisesRegex(LiveManagementError, 'Start or resume'):
            self.service.load('888')
        self.stream.client.kind = 'mobile'
        with self.assertRaisesRegex(LiveManagementError, 'PC/Studio'):
            self.service.load('888')
        self.assertEqual(self.stream.calls, [])

    def test_account_room_and_end_status_are_verified(self):
        for change, message in (({'owner_user_id': '999'}, 'belongs'), ({'id_str': '999'}, 'different LIVE'),
                                ({'status': 4}, 'ended')):
            with self.subTest(change=change):
                self.setUp()
                self.stream.responses['webcast/room/info/'].update(change)
                with self.assertRaisesRegex(LiveManagementError, message):
                    self.service.load('888')
                self.assertFalse(any(call[1] == SUMMARY_PATH for call in self.stream.calls))
        self.setUp()
        self.stream.account['user_id_str'] = '999'
        with self.assertRaisesRegex(LiveManagementError, 'account changed'):
            self.service.load('888')

    def test_context_and_cookie_changes_during_request_discard_result(self):
        for cookie_change in (False, True):
            with self.subTest(cookie_change=cookie_change):
                self.setUp()
                current = True
                self.service.is_current = lambda: current
                request = self.stream._signed_get_json
                def changed(url, **kwargs):
                    nonlocal current
                    result = request(url, **kwargs)
                    if SUMMARY_PATH in url:
                        if cookie_change:
                            self.stream.account['user_id_str'] = '999'
                        else:
                            current = False
                    return result
                self.stream._signed_get_json = changed
                with self.assertRaisesRegex(LiveManagementError, 'changed'):
                    self.service.load('888')

    def test_server_errors_and_mismatched_identity_never_become_zero(self):
        self.stream.failures[SUMMARY_PATH] = {'status_code': 8, 'data': {'prompts': 'Not available'}}
        with self.assertRaisesRegex(LiveManagementError, 'Not available'):
            self.service.load('888')
        self.stream.failures.clear()
        for key in ('room_id_str', 'user_id_str'):
            with self.subTest(key=key):
                self.stream.responses[SUMMARY_PATH][key] = '999'
                with self.assertRaisesRegex(LiveManagementError, 'different viewer or LIVE'):
                    self.service.load('888')
                del self.stream.responses[SUMMARY_PATH][key]

    def test_following_viewer_does_not_mean_they_follow_host(self):
        for status, days in ((0, None), (1, None), (2, 30), (3, 30), ('3', 30)):
            self.stream.responses['webcast/user/']['follow_info']['follow_status'] = status
            self.assertEqual(self.service.load('888')['follow_days'], days)
        self.stream.responses[SUMMARY_PATH]['follow_time'] = 100
        self.assertEqual(self.service.load('888')['follow_days'], 1)

    def test_follow_profile_failure_preserves_other_stats(self):
        self.stream.failures['webcast/user/'] = TimeoutError('Timed out')
        result = self.service.load('888')
        self.assertIsNone(result['follow_days'])
        self.assertEqual(result['like_count'], 125)
        self.assertTrue(result['warning'])

    def test_missing_follow_time_does_not_fetch_profile(self):
        del self.stream.responses[SUMMARY_PATH]['follow_time']
        self.service.load('888')
        self.assertFalse(any(call[1] == 'webcast/user/' for call in self.stream.calls))

    def test_partial_and_empty_values_are_distinguished(self):
        result = normalize_summary({'like_count': '0', 'watch_duration': True, 'share_count': -1,
                                    'comment_count': 2.5, 'comment_list': []})
        self.assertEqual(result['like_count'], 0)
        self.assertEqual(result['comments'], [])
        for key in ('watch_duration', 'share_count', 'comment_count', 'follow_time'):
            self.assertIsNone(result[key])
        self.assertIsNone(normalize_summary({'like_count': 1})['comments'])
        for data in ({}, None, [], {'watch_duration': 'bad'}, {'like_count': 2**63}):
            with self.subTest(data=data), self.assertRaises(LiveManagementError):
                normalize_summary(data)

    def test_watch_time_ranges_match_studio_and_zero_stays_zero(self):
        for seconds, text in ((None, 'Unavailable'), (0, '0 min'), (1, '< 1 min'), (61, '< 2 min'),
                              (299, '< 5 min'), (300, '≥ 5 min'), (725, '≥ 12 min')):
            self.assertEqual(watch_time_text(seconds), text)

    def test_malformed_comments_are_unavailable_instead_of_reported_as_empty(self):
        result = normalize_summary({'like_count': 2, 'comment_list': [None, {'content': 123}]})
        self.assertIsNone(result['comments'])
        self.assertTrue(result['warning'])
        result = normalize_summary({'comment_list': [None, {'content': 'Readable'}]})
        self.assertEqual(result['comments'], [[{'text': 'Readable'}]])
        self.assertTrue(result['warning'])

    def test_unicode_offsets_and_comment_limit(self):
        item = {'content': '👀ab', 'emotes': [{'index': 1, 'emote': {'image': {'url_list': [EMOTE_URL]}}},
                                           {'index': 3, 'emote': {}}]}
        original = copy.deepcopy(item)
        parts = comment_parts(item)
        self.assertEqual(parts, [{'text': '👀'}, {'emote_url': EMOTE_URL, 'text': '[Emote]'},
                                 {'text': 'a'}, {'emote_url': '', 'text': '[Emote]'}, {'text': 'b'}])
        self.assertEqual(item, original)
        result = normalize_summary({'comment_list': [item] * 15})
        self.assertEqual(len(result['comments']), 10)

    def test_remote_emotes_are_bounded_to_public_cdn_urls(self):
        self.assertEqual(emote_url(EMOTE_URL), EMOTE_URL)
        for url in ('file:///tmp/a', 'http://p16.tiktokcdn.com/a', 'https://tiktokcdn.com.attacker.test/a',
                    'https://p16.tiktokcdn.com:444/a', 'https://user:secret@p16.tiktokcdn.com/a',
                    'https://localhost/a', 'https://[bad', None):
            with self.subTest(url=url):
                self.assertEqual(emote_url(url), '')

    def test_username_lookup_matches_handle_not_display_name_or_first_result(self):
        self.stream.responses['webcast/anchor/user_search/'] = {'matched_user_list': [
            {'user_info': {'id_str': '777', 'nickname': 'viewer.name', 'display_id': 'similar.viewer'}},
            {'user_info': {'id_str': '888', 'nickname': 'Actual viewer', 'display_id': 'Viewer.Name'}},
        ], 'has_more': False}
        result = self.service.load(' @viewer.name ')
        self.assertEqual((result['viewer_id'], result['viewer_username'], result['viewer_name']),
                         ('888', 'Viewer.Name', 'Actual viewer'))
        search = next(call for call in self.stream.calls if call[1] == 'webcast/anchor/user_search/')
        self.assertEqual({k: search[2]['params'][k] for k in ('keyword', 'offset', 'count')},
                         {'keyword': 'viewer.name', 'offset': 0, 'count': 50})
        summary = next(call for call in self.stream.calls if call[1] == SUMMARY_PATH)
        self.assertEqual(summary[2]['params']['user_id_str'], '888')
        self.assertEqual(self.stream.writes(), [])

    def test_numeric_handle_needs_at_prefix_and_normal_ids_skip_search(self):
        self.assertEqual(parse_viewer_lookup('@12345'), ('username', '12345'))
        self.assertEqual(parse_viewer_lookup('12345'), ('id', '12345'))
        self.assertEqual(parse_viewer_lookup('Viewer.Name'), ('username', 'viewer.name'))
        self.service.load('888')
        self.assertFalse(any(call[1] == 'webcast/anchor/user_search/' for call in self.stream.calls))

    def test_no_exact_match_never_requests_another_users_summary(self):
        self.stream.responses['webcast/anchor/user_search/'] = {'matched_user_list': [
            {'user_info': {'id_str': '777', 'display_id': 'somebody_else', 'nickname': 'viewer'}}]}
        with self.assertRaisesRegex(LiveManagementError, 'No exact match'):
            self.service.load('@viewer')
        self.assertFalse(any(call[1] == SUMMARY_PATH for call in self.stream.calls))

    def test_conflicting_username_matches_are_rejected(self):
        self.stream.responses['webcast/anchor/user_search/'] = {'matched_user_list': [
            {'user_info': {'id_str': uid, 'display_id': 'viewer'}} for uid in ('777', '888')]}
        with self.assertRaisesRegex(LiveManagementError, 'conflicting'):
            self.service.load('viewer')
        self.assertFalse(any(call[1] == SUMMARY_PATH for call in self.stream.calls))

    def test_username_search_paginates_and_stops_at_a_bound(self):
        self.stream.responses['webcast/anchor/user_search/'] = {'matched_user_list': [], 'has_more': True}
        with self.assertRaisesRegex(LiveManagementError, 'returned search results'):
            self.service.load('viewer')
        searches = [call for call in self.stream.calls if call[1] == 'webcast/anchor/user_search/']
        self.assertEqual([call[2]['params']['offset'] for call in searches], [0, 50, 100, 150, 200])
        original = self.stream._signed_get_json
        def page_two(url, **kwargs):
            if 'user_search' in url and kwargs['params']['offset'] == 50:
                return {'status_code': 0, 'data': {'matched_user_list': [
                    {'user_info': {'id_str': '888', 'display_id': 'viewer'}}]}}
            return original(url, **kwargs)
        self.stream._signed_get_json = page_two
        self.assertEqual(self.service.load('@viewer')['viewer_id'], '888')

    def test_username_search_errors_and_context_change_cannot_return_summary(self):
        self.stream.failures['webcast/anchor/user_search/'] = {'status_code': 8, 'data': {'prompts': 'Search unavailable'}}
        with self.assertRaisesRegex(LiveManagementError, 'Search unavailable'):
            self.service.load('viewer')
        self.stream.failures.clear()
        with self.assertRaisesRegex(LiveManagementError, 'invalid username search'):
            self.service.load('viewer')
        original = self.stream._signed_get_json
        current = True
        self.service.is_current = lambda: current
        def changed(url, **kwargs):
            nonlocal current
            if 'user_search' in url:
                current = False
                return {'status_code': 0, 'data': {'matched_user_list': [
                    {'user_info': {'id_str': '888', 'display_id': 'viewer'}}]}}
            return original(url, **kwargs)
        self.stream._signed_get_json = changed
        with self.assertRaisesRegex(LiveManagementError, 'changed'):
            self.service.load('viewer')
        self.assertFalse(any(call[1] == SUMMARY_PATH for call in self.stream.calls))


if __name__ == '__main__':
    unittest.main()
