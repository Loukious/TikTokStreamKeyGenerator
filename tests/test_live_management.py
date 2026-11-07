"""Offline management contracts: identity, authorization, wire formats and failures."""
import copy
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit

from Libs.live_management import LiveManagement, LiveManagementError, chat_availability, validate_capabilities


class FakeStream:
    def __init__(self, kind='pc'):
        self.client = SimpleNamespace(kind=kind, record={'device_id': '321', 'install_id': '654'})
        self.account = {'user_id_str': '123', 'sec_user_id': 'secure-owner'}
        self.calls = []
        self.responses = {
            'webcast/room/info/': {'id_str': '456', 'owner_user_id': '123', 'status': 2,
                'room_auth': {'Chat': True, 'ChatL2': False, 'ChatSubOnly': False},
                'star_comment_config': {'star_comment_switch': False, 'grant_group': 2, 'grant_level': 15}},
            'webcast/room/create_info/': {'star_comment_qualification': True, 'star_comment_permission_switch': True},
            'webcast/sub/privilege/get_sub_info/': {'enable': True},
            'webcast/game/basic/create_info/': {},
            'webcast/room/get_sensitive_word/': {'word': [{'id': 9, 'content': 'existing'}]},
            'webcast/room/add_sensitive_word/': {'id': 10},
            'webcast/user/admin/list/': [{'user_info': {'id_str': '777', 'nickname': 'Moderator'}}],
            'webcast/anchor/about_me/': {'about_me': {'current_template_id': '6', 'switch_status': True,
                'audit_status': 1, 'template_list': [{'id': '6', 'title': 'Intro', 'input_box_list': [
                    {'content': 'Hello', 'max_character_count': 12}]}]}},
        }
        self.failures = {}

    def _cookie_account_info(self, region=''):
        return copy.deepcopy(self.account)

    def _studio_params(self, **kwargs):
        return {'aid': '8311' if self.client.kind == 'pc' else '1233', **kwargs}

    def getServerUrl(self):
        return 'https://example.invalid/'

    def _request(self, method, url, **kwargs):
        path = urlsplit(url).path.lstrip('/')
        self.calls.append((method, path, copy.deepcopy(kwargs)))
        failure = self.failures.get(path)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        return {'status_code': 0, 'data': copy.deepcopy(self.responses.get(path, {}))}

    def _signed_get_json(self, url, **kwargs):
        return self._request('GET', url, **kwargs)

    def _signed_post_json(self, url, **kwargs):
        return self._request('JSON', url, **kwargs)

    def _signed_post_form(self, url, **kwargs):
        return self._request('FORM', url, **kwargs)

    def writes(self):
        return [call for call in self.calls if call[0] != 'GET' or call[2].get('retry') is False]


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.stream = FakeStream()
        self.manager = LiveManagement(self.stream, room_id='456', expected_user_id='123')

    def test_state_reads_booleans_grants_and_capabilities(self):
        state = self.manager.get_chat_settings()
        self.assertEqual((state['user_id'], state['room_id']), ('123', '456'))
        self.assertEqual([state[k] for k in ('allow_comments', 'filter_comments', 'subscriber_only_chat', 'star_comments')], [True, False, False, False])
        self.assertEqual((state['star_grant_group'], state['star_grant_level']), (2, 15))
        self.assertTrue(state['subscriber_available'])
        self.assertTrue(state['star_available'])
        sub = next(c for c in self.stream.calls if '/get_sub_info/' in c[1])
        self.assertEqual(sub[2]['params']['sec_anchor_id'], 'secure-owner')
        self.assertEqual(sub[2]['params']['device_id'], '321')

    def test_missing_auth_is_unknown_and_unknown_permissions_are_unavailable(self):
        self.stream.responses['webcast/room/info/']['room_auth'] = {}
        self.stream.responses['webcast/room/create_info/'] = {}
        self.stream.failures['webcast/sub/privilege/get_sub_info/'] = {'status_code': 8, 'data': {'prompts': 'No subscription access'}}
        state = self.manager.get_chat_settings()
        self.assertIsNone(state['allow_comments'])
        self.assertFalse(state['subscriber_available'])
        self.assertFalse(state['star_available'])
        self.assertIn('No subscription access', state['subscriber_reason'])

    def test_account_swap_blocks_all_account_mutations(self):
        self.stream.account['user_id_str'] = '999'
        for operation in (lambda: self.manager.add_word('new'), lambda: self.manager.delete_word('9'),
                          lambda: self.manager.set_moderator('777', True), self.manager.clear_about_me,
                          lambda: self.manager.set_about_me('6', 'Intro')):
            with self.subTest(operation=operation), self.assertRaisesRegex(LiveManagementError, 'account changed'):
                operation()
        self.assertEqual(self.stream.writes(), [])

    def test_room_owner_mismatch_blocks_moderation(self):
        self.stream.responses['webcast/room/info/']['owner_user_id'] = '999'
        with self.assertRaisesRegex(LiveManagementError, 'belongs'):
            self.manager.moderate_user('888', 'block')
        self.assertEqual(self.stream.writes(), [])

    def test_no_mutation_when_later_setting_is_ineligible(self):
        self.stream.responses['webcast/room/create_info/']['star_comment_permission_switch'] = False
        with self.assertRaisesRegex(LiveManagementError, 'Star Comments'):
            self.manager.update_chat_settings({'allow_comments': False, 'star_comments': True})
        self.assertEqual(self.stream.writes(), [])

    def test_only_changed_settings_sent_and_wire_values_are_correct(self):
        self.stream.responses['webcast/room/info/']['room_auth']['Chat'] = False
        self.manager.update_chat_settings({'allow_comments': True, 'filter_comments': True,
                                          'subscriber_only_chat': True, 'star_comments': True})
        writes = self.stream.writes()
        self.assertEqual(len(writes), 4)
        self.assertEqual([w[2]['data']['switch_type'] for w in writes[:3]], [3, 4, 7])
        self.assertEqual([w[2]['data']['switch_value'] for w in writes[:3]], ['true', 'true', 'true'])
        self.assertEqual(writes[-1][0], 'GET')
        self.assertEqual({k: writes[-1][2]['params'][k] for k in ('star_comment_switch', 'grant_group', 'grant_level')},
                         {'star_comment_switch': 'true', 'grant_group': 2, 'grant_level': 15})
        self.assertTrue(all(w[2]['retry'] is False for w in writes))

    def test_subscriber_enable_requires_comments_before_any_write(self):
        with self.assertRaisesRegex(ValueError, 'Allow comments'):
            self.manager.update_chat_settings({'allow_comments': False, 'subscriber_only_chat': True})
        self.assertEqual(self.stream.writes(), [])

    def test_context_changed_during_preflight_blocks_write(self):
        current = True
        self.manager.is_current = lambda: current
        read = self.manager.get_chat_settings
        def changed():
            nonlocal current
            result = read()
            current = False
            return result
        self.manager.get_chat_settings = changed
        with self.assertRaisesRegex(LiveManagementError, 'account or LIVE changed'):
            self.manager.update_chat_settings({'allow_comments': False})
        self.assertEqual(self.stream.writes(), [])

    def test_accepted_but_unchanged_state_is_reported(self):
        result = self.manager.update_chat_settings({'allow_comments': False})
        self.assertTrue(result['allow_comments'])
        self.assertIn('did not report the requested value', result['refresh_warning'])

    def test_noop_and_invalid_types_send_nothing(self):
        self.manager.update_chat_settings({'allow_comments': True})
        for change in ({'allow_comments': 'false'}, {'star_grant_group': 0}, {'star_grant_level': -1}, {'gift': False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.manager.update_chat_settings(change)
        self.assertEqual(self.stream.writes(), [])

    def test_partial_failure_identifies_applied_keys_without_retry(self):
        self.stream.failures['webcast/room/star_comment/update/'] = {'status_code': 88, 'data': {'prompts': 'Unavailable here'}}
        with self.assertRaisesRegex(LiveManagementError, 'Applied allow_comments.*Unavailable here'):
            self.manager.update_chat_settings({'allow_comments': False, 'star_comments': True})
        self.assertEqual(len(self.stream.writes()), 2)

    def test_missing_status_is_not_success(self):
        self.stream.failures['webcast/room/switch/update/'] = {'data': {}}
        with self.assertRaisesRegex(LiveManagementError, 'success is unconfirmed'):
            self.manager.update_chat_settings({'allow_comments': False})
        self.assertEqual(len(self.stream.writes()), 1)

    def test_failed_refresh_is_reported_as_accepted_with_warning(self):
        original = self.manager.get_chat_settings
        count = 0
        def read():
            nonlocal count
            count += 1
            if count > 1:
                raise ConnectionError('refresh unavailable')
            return original()
        self.manager.get_chat_settings = read
        result = self.manager.update_chat_settings({'allow_comments': False})
        self.assertEqual(result['applied'], ['allow_comments'])
        self.assertIn('accepted', result['refresh_warning'])

    def test_keyword_limits_duplicates_and_unknown_deletion_are_preflighted(self):
        for word in ('', '  ', 'x' * 31, '😀' * 16, 'existing'):
            with self.subTest(word=word), self.assertRaises(ValueError):
                self.manager.add_word(word)
        with self.assertRaises(ValueError):
            self.manager.delete_word('33')
        self.assertEqual(self.stream.writes(), [])
        self.assertEqual(self.manager.add_word(' new '), {'id': '10', 'word': 'new'})
        self.assertEqual(self.stream.writes()[0][2]['data']['word'], 'new')
        self.manager.delete_word('9')
        self.assertEqual(self.stream.writes()[-1][2]['data']['word_id'], '9')

    def test_android_keyword_writes_are_mutating_gets(self):
        self.stream.client.kind = 'mobile'
        self.manager.add_word('new')
        self.manager.delete_word('9')
        self.assertEqual([w[0] for w in self.stream.writes()], ['GET', 'GET'])
        self.assertTrue(all(w[2]['retry'] is False for w in self.stream.writes()))

    def test_moderation_transport_and_identity_checks(self):
        for action, mode in [('mute', 'JSON'), ('unmute', 'JSON'), ('block', 'JSON'), ('unblock', 'FORM')]:
            self.manager.moderate_user('888', action)
            self.assertEqual(self.stream.writes()[-1][0], mode)
            self.assertIs(self.stream.writes()[-1][2]['retry'], False)
        self.assertEqual(self.stream.writes()[0][2]['payload'], {'room_id': '456', 'user_id': '888', 'duration': 300, 'silence_type': 1})
        for uid in ('', '0', '-1', '1x', True):
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                self.manager.moderate_user(uid, 'mute')
        with self.assertRaises(ValueError):
            self.manager.moderate_user('123', 'block')

    def test_android_mute_resolves_target_secure_identity_and_uses_query(self):
        self.stream.client.kind = 'mobile'
        self.stream.responses['webcast/user/'] = {'id_str': '888', 'sec_uid': 'secure-viewer'}
        self.manager.moderate_user('888', 'mute')
        write = self.stream.writes()[-1]
        self.assertEqual(write[0], 'FORM')
        self.assertEqual(write[2]['data'], {})
        self.assertEqual(write[2]['params']['sec_user_id'], 'secure-viewer')
        self.assertEqual(write[2]['params']['duration'], 300)

    def test_moderator_listing_and_update_contract(self):
        self.assertEqual(self.manager.get_moderators(), [{'id': '777', 'name': 'Moderator'}])
        self.manager.set_moderator('777', True)
        self.manager.set_moderator('777', False)
        self.assertEqual([w[2]['data']['update_type'] for w in self.stream.writes()], [3, 2])
        self.assertEqual(self.stream.writes()[0][2]['data']['anchor_id'], '123')

    def test_pre_live_account_tools_follow_studio_room_omission(self):
        manager = LiveManagement(self.stream, expected_user_id='123')
        manager.get_moderators()
        self.assertNotIn('room_id', self.stream.calls[-1][2]['params'])
        manager.set_moderator('777', True)
        self.assertNotIn('current_room_id', self.stream.writes()[-1][2]['data'])
        manager.get_words()
        self.assertEqual(self.stream.calls[-1][2]['params']['room_id'], '')

    def test_about_me_uses_server_template_constraints_and_json(self):
        info = self.manager.get_about_me()
        self.assertEqual((info['user_id'], info['content'], info['current_template_id']), ('123', 'Hello', '6'))
        self.assertEqual(info['templates'][0]['max_length'], 12)
        for template, content in [('unknown', 'text'), ('6', 'x' * 13), ('6', '123'), ('6', '  ')]:
            with self.subTest(template=template, content=content), self.assertRaises(ValueError):
                self.manager.set_about_me(template, content)
        self.assertEqual(self.stream.writes(), [])
        self.manager.set_about_me('6', 'Welcome')
        self.manager.clear_about_me()
        self.assertEqual([w[2]['payload'] for w in self.stream.writes()], [
            {'template_id': '6', 'method_type': 1, 'input_content_list': ['Welcome']}, {'method_type': 2}])
        self.assertTrue(all(w[0] == 'JSON' and w[2]['retry'] is False for w in self.stream.writes()))

    def test_malformed_lists_and_about_me_are_not_silent_empty_success(self):
        for path, operation in [('webcast/room/get_sensitive_word/', self.manager.get_words),
                                ('webcast/user/admin/list/', self.manager.get_moderators),
                                ('webcast/anchor/about_me/', self.manager.get_about_me)]:
            self.stream.responses[path] = None
            with self.subTest(path=path), self.assertRaises(LiveManagementError):
                operation()

    def test_pre_live_does_not_guess_room_or_account_from_stream_attributes(self):
        self.stream.roomId = '999'
        self.stream.ownerUserId = '999'
        manager = LiveManagement(self.stream, expected_user_id='123')
        state = manager.prepare_creation({'subscriber_only_chat': True, 'star_comments': True})
        self.assertEqual(state['room_id'], '')
        self.assertIsNone(state['star_comments'])
        self.assertFalse(any(path == 'webcast/room/info/' for _, path, _ in self.stream.calls))

    def test_missing_secure_owner_is_resolved_and_mismatch_rejected(self):
        self.stream.account.pop('sec_user_id')
        self.stream.responses['webcast/user/'] = {'id_str': '999', 'sec_uid': 'wrong'}
        with self.assertRaisesRegex(LiveManagementError, 'different user'):
            self.manager.get_words()
        self.assertEqual(self.stream.writes(), [])

    def test_unproven_mobile_contracts_require_studio_management(self):
        self.stream.client.kind = 'mobile'
        for operation in (self.manager.get_chat_settings, self.manager.clear_about_me, self.manager.get_moderators):
            with self.subTest(operation=operation), self.assertRaisesRegex(LiveManagementError, 'PC/Studio'):
                operation()
        self.assertEqual(self.stream.writes(), [])

    def test_live_star_permissions_override_create_eligibility(self):
        room = self.stream.responses['webcast/room/info/']
        room['room_auth']['star_comment_permission_switch'] = {'status': 2, 'OffReason': 'Restricted during this LIVE'}
        state = self.manager.get_chat_settings()
        self.assertFalse(state['star_available'])
        self.assertIn('Restricted during this LIVE', state['star_reason'])
        with self.assertRaises(LiveManagementError):
            self.manager.update_chat_settings({'allow_comments': False, 'star_comments': True})
        self.assertEqual(self.stream.writes(), [])
        room['room_auth']['star_comment_permission_switch'] = {'status': 1}
        room['star_comment_config']['star_comment_qualification'] = False
        self.assertFalse(self.manager.get_chat_settings()['star_available'])

    def test_pre_live_preserves_only_reported_star_grants(self):
        manager = LiveManagement(self.stream, expected_user_id='123')
        self.assertIsNone(manager.get_chat_settings()['star_grant_group'])
        self.stream.responses['webcast/room/create_info/']['star_comment_config'] = {'grant_group': 3, 'grant_level': 8}
        state = manager.prepare_creation({'star_comments': True})
        self.assertEqual((state['star_grant_group'], state['star_grant_level']), (3, 8))

    def test_capability_helper_allows_disabling_without_grants(self):
        state = chat_availability({})
        validate_capabilities(state, {'subscriber_only_chat': False, 'star_comments': False})
        with self.assertRaises(LiveManagementError):
            validate_capabilities(state, {'subscriber_only_chat': True})
        self.assertTrue(chat_availability({}, basic_info={'have_super_fans_permission': True})['subscriber_available'])


if __name__ == '__main__':
    unittest.main()
