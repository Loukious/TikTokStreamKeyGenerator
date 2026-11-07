"""Offline startup controls: wire values, persisted GUI choices and creation."""
import contextlib
import copy
import hashlib
import itertools
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import parse_qs

from tests import test_client_modes as base
from tests.gui_helpers import drive_workflow
from Libs.live_settings import LiveSettings
from Libs.mobile_requests import create_room_form

gui = base.gui


def created_room(**auth):
    return {'status_code': 0, 'data': {'id_str': '100', 'stream_id_str': '200',
        'stream_url': {'rtmp_push_url': 'rtmp://example.invalid/live/key'},
        'room_auth': auth}}


class SettingsFieldsTests(unittest.TestCase):
    def test_comment_filters_and_star_override_use_client_specific_fields(self):
        settings = LiveSettings(filter_comments=False, subscriber_only_chat=True,
                                star_comments=False, filter_spam=False, filter_flagged=True, review_flagged=True)
        pc, mobile = (settings.room_fields(kind) for kind in ('pc', 'mobile'))
        self.assertEqual(pc['chat_l2'], '2')
        self.assertNotIn('chat_l_2', pc)
        self.assertNotIn('spam_comments', pc)
        self.assertEqual(mobile['chat_l_2'], '2')
        self.assertNotIn('chat_l2', mobile)
        self.assertEqual([mobile[k] for k in ('spam_comments', 'community_flagged_chat_auth', 'community_flagged_chat_review_auth')], ['2', '1', '1'])
        for fields in (pc, mobile):
            self.assertEqual(fields['chat_sub_only_auth'], '1')
            self.assertEqual(fields['star_comment_switch'], 'false')
        for kind in ('pc', 'mobile'):
            self.assertNotIn('star_comment_switch', LiveSettings().room_fields(kind))

    def test_imported_star_values_cannot_override_account_default(self):
        form = create_room_form({'create_params': {'star_comment_switch': 'true', 'grant_group': '3',
                    'grant_level': '30', 'star_comment_qualification': 'true', 'chat_l_2': '2',
                    'spam_comments': '2'}}, title='Fixture', hashtag_id='5')
        for key in ('star_comment_switch', 'grant_group', 'grant_level', 'star_comment_qualification'):
            self.assertNotIn(key, form)
        self.assertEqual((form['chat_l_2'], form['spam_comments']), ('1', '1'))

    def test_invalid_comment_preferences_rejected_and_config_recovered(self):
        for changes in ({'filter_comments': 2}, {'star_comments': 'on'}, {'filter_spam': None},
                        {'allow_comments': False, 'subscriber_only_chat': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                LiveSettings(**changes)
        recovered = LiveSettings.from_config({'allow_comments': False, 'subscriber_only_chat': True, 'star_comments': 'true'})
        self.assertFalse(recovered.subscriber_only_chat)
        self.assertIsNone(recovered.star_comments)

    def test_all_manual_choices_use_traced_wire_encodings(self):
        for client, gifts, comments, disclosure in itertools.product(
                ('pc', 'mobile'), (False, True), (False, True),
                ('off', 'own_brand', 'third_party', 'both')):
            with self.subTest(client=client, gifts=gifts, comments=comments, disclosure=disclosure):
                fields = LiveSettings(gifts, comments, disclosure).room_fields(client)
                self.assertEqual(fields['gift_auth'], '1' if gifts else '2')
                self.assertEqual(fields['chat_auth'], '1' if comments else '2')
                expected = {'off': ('false', 'false', 'false'),
                            'own_brand': ('true', 'true', 'false'),
                            'third_party': ('true', 'false', 'true'),
                            'both': ('true', 'true', 'true')}[disclosure]
                self.assertEqual(tuple(fields[name] for name in (
                    'open_commercial_content_toggle', 'commercial_content_promote_myself',
                    'commercial_content_promote_third_party')), expected)
                if disclosure in ('third_party', 'both'):
                    self.assertEqual(fields['ecom_bc_toggle'], '5')
                elif client == 'mobile':
                    self.assertEqual(fields['ecom_bc_toggle'], '0')
                else:
                    self.assertNotIn('ecom_bc_toggle', fields)

    def test_mobile_profile_extras_cannot_override_explicit_choices(self):
        profile = {'create_params': {'gift_auth': '1', 'chat_auth': '1',
            'open_commercial_content_toggle': 'false', 'commercial_content_promote_myself': 'false',
            'commercial_content_promote_third_party': 'false', 'ecom_bc_toggle': '4',
            'unrelated_extra': 'keep'}}
        before = copy.deepcopy(profile)
        form = create_room_form(profile, title='Fixture', hashtag_id='5',
                                allow_gifts=False, allow_comments=False, content_disclosure='both')
        self.assertEqual((form['gift_auth'], form['chat_auth']), ('2', '2'))
        self.assertEqual(form['ecom_bc_toggle'], '5')
        self.assertEqual(form['commercial_content_promote_myself'], 'true')
        self.assertEqual(form['commercial_content_promote_third_party'], 'true')
        self.assertEqual(form['unrelated_extra'], 'keep')
        self.assertEqual(profile, before)
        form = create_room_form(profile, title='Fixture', hashtag_id='5', content_disclosure='off')
        self.assertEqual(form['ecom_bc_toggle'], '0')
        self.assertEqual(form['open_commercial_content_toggle'], 'false')

    def test_invalid_api_settings_fail_instead_of_silently_changing_intent(self):
        for settings in ({'allow_gifts': 'false'}, {'allow_comments': 2},
                         {'content_disclosure': 'enabled'}, {'content_disclosure': []}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                LiveSettings(**settings)

    def test_legacy_and_malformed_configuration_loads_with_defaults(self):
        self.assertEqual(LiveSettings.from_config({}), LiveSettings())
        self.assertEqual(LiveSettings.from_config({'allow_gifts': [], 'allow_comments': None,
                                                  'content_disclosure': {}}), LiveSettings())


class SettingsIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(base.ModeTests.setUpClass.__func__)
    setUp = base.ModeTests.setUp
    window = base.ModeTests.window

    @contextlib.contextmanager
    def stream(self, kind='pc', profile=None, response=None):
        with gui.Stream(cookies_path=self.cookies, device_type=kind, device_profile={
                'device_id': '333', 'install_id': '444', **(profile or {})}) as stream, \
             patch.object(stream, '_ensure_region_context'), \
             patch.object(stream, 'getServerUrl', return_value='https://example.invalid/'), \
             patch.object(stream, '_request_json', return_value=response or created_room(Gift=False, Chat=False)) as send, \
             patch.object(stream, 'endStream', return_value=True) as finish, \
             patch.object(gui, '_build_signature_headers', return_value={'x-argus': 'fixture'}) as sign:
            yield stream, send, finish, sign

    def test_changed_settings_reach_encoded_body_and_body_stub_in_both_clients(self):
        for kind, profile in (('pc', {}), ('mobile', {'broadcast_type': 'video'}),
                              ('mobile', {'broadcast_type': 'screen_record', 'orientation': '2'})):
            with self.subTest(kind=kind, profile=profile), self.stream(kind, profile) as (stream, send, finish, sign):
                self.assertTrue(stream.createStream('A + B', '5', allow_gifts=False,
                    allow_comments=False, content_disclosure='third_party'))
                body = send.call_args.kwargs['data']
                form = parse_qs(body.decode())
                self.assertEqual(form['title'], ['A + B'])
                self.assertEqual(form['gift_auth'], ['2'])
                self.assertEqual(form['chat_auth'], ['2'])
                self.assertEqual(form['commercial_content_promote_third_party'], ['true'])
                self.assertEqual(form['ecom_bc_toggle'], ['5'])
                self.assertEqual(send.call_args.kwargs['headers']['x-ss-stub'], hashlib.md5(body).hexdigest())
                self.assertEqual(sign.call_args.kwargs['x_ss_stub'], hashlib.md5(body).hexdigest())
                finish.assert_not_called()

    def test_android_final_transport_signs_the_selected_body(self):
        with self.stream('mobile') as (stream, create, _, _):
            stream.createStream('Fixture', '5', allow_gifts=False, allow_comments=False,
                                content_disclosure='both')
            args = create.call_args
            response = Mock(status_code=200, headers={})
            response.json.return_value = created_room(Gift=False, Chat=False)
            with patch.object(stream.s, 'request', return_value=response) as send, \
                 patch.object(stream.client, 'signature_headers', return_value={'x-argus': 'fixture'}) as sign, \
                 patch.object(stream, 'save_cookies'), patch.object(gui, '_audit_webcast_request'):
                gui.Stream._request_json(stream, *args.args, **args.kwargs)
            self.assertEqual(sign.call_args.kwargs['body'], send.call_args.kwargs['data'])
            self.assertEqual(sign.call_args.kwargs['body'], args.kwargs['data'])
            self.assertEqual(parse_qs(sign.call_args.kwargs['body'].decode())['chat_auth'], ['2'])

    def test_old_positional_call_keeps_existing_defaults(self):
        with self.stream() as (stream, send, _, _):
            stream.createStream('Fixture', '5', '0', True, False, False, '', '', '333', '444', False, 1)
            form = parse_qs(send.call_args.kwargs['data'].decode())
            self.assertEqual(form['gift_auth'], ['1'])
            self.assertEqual(form['chat_auth'], ['1'])
            self.assertEqual(form['open_commercial_content_toggle'], ['false'])
            self.assertNotIn('ecom_bc_toggle', form)
            self.assertNotIn('star_comment_switch', form)

    def test_permissions_fail_before_room_creation(self):
        from Libs.live_management import LiveManagementError
        for changes in ({'subscriber_only_chat': True}, {'star_comments': True}):
            with self.subTest(changes=changes), self.stream() as (stream, send, _, _), \
                 patch.object(gui.LiveManagement, 'get_chat_settings', return_value={
                     'subscriber_available': False, 'star_available': False}):
                with self.assertRaises(LiveManagementError):
                    stream.createStream('Fixture', '5', **changes)
                send.assert_not_called()

    def test_reported_star_grants_reach_signed_create_body(self):
        for kind in ('pc', 'mobile'):
            with self.subTest(kind=kind), self.stream(kind) as (stream, send, _, sign), \
                 patch.object(stream, '_prepare_chat_preferences', return_value={'star_grant_group': 3, 'star_grant_level': 20}):
                stream.createStream('Fixture', '5', star_comments=True, subscriber_only_chat=True,
                                    filter_comments=False, filter_flagged=True)
                body = send.call_args.kwargs['data']
                form = parse_qs(body.decode())
                self.assertEqual((form['star_comment_switch'], form['grant_group'], form['grant_level']), (['true'], ['3'], ['20']))
                self.assertEqual(form['chat_sub_only_auth'], ['1'])
                self.assertEqual(form['chat_l2' if kind == 'pc' else 'chat_l_2'], ['2'])
                self.assertEqual(sign.call_args.kwargs['x_ss_stub'], hashlib.md5(body).hexdigest())

    def test_android_permissions_are_bound_to_authoritative_selected_account(self):
        with self.stream('mobile') as (stream, send, _, _), \
             patch.object(stream, '_cookie_account_info', return_value={'user_id_str': '123'}), \
             patch.object(gui, '_load_config_file', return_value={'device_id': '111', 'install_id': '222'}), \
             patch.object(gui, 'Stream') as studio_class, patch.object(gui, 'LiveManagement') as manager:
            result = stream._prepare_chat_preferences(LiveSettings(star_comments=True), '')
            studio_class.assert_called_once_with(cookies_path=self.cookies, device_type='pc',
                                                device_profile={'device_id': '111', 'install_id': '222'})
            self.assertEqual(manager.call_args.kwargs['expected_user_id'], '123')
            send.assert_not_called()
            self.assertIs(result, manager.return_value.prepare_creation.return_value)

    def test_management_mutations_bypass_transport_fallback_and_redirects(self):
        with self.stream() as (stream, send, _, _), \
             patch.object(stream, '_request_json_with_webcast_fallback') as fallback:
            stream._signed_get_json('https://example.invalid/update', params={'aid': '8311'}, retry=False)
            self.assertFalse(send.call_args.kwargs['allow_redirects'])
            stream._signed_post_form('https://example.invalid/update', params={'aid': '8311'}, data={'word': 'A + B'}, retry=False)
            self.assertFalse(send.call_args.kwargs['allow_redirects'])
            body = send.call_args.kwargs['data']
            self.assertEqual(parse_qs(body.decode())['word'], ['A + B'])
            self.assertEqual(send.call_args.kwargs['headers']['x-ss-stub'], hashlib.md5(body).hexdigest())
            fallback.assert_not_called()

    def test_comment_gui_preferences_persist_and_follow_mode(self):
        window = self.window()
        window.filter_comments_checkbox.setChecked(False)
        window.subscriber_chat_checkbox.setChecked(True)
        window.star_comments_combo.setCurrentIndex(2)
        window.spam_comments_checkbox.setChecked(False)
        window.flagged_comments_checkbox.setChecked(True)
        window.review_flagged_checkbox.setChecked(True)
        self.assertFalse(window.spam_comments_checkbox.isEnabled())
        window.device_type_combo.setCurrentIndex(1)
        self.assertTrue(window.spam_comments_checkbox.isEnabled())
        window._save_workspace_settings()
        other = self.window()
        self.assertEqual(other.live_start_settings(), LiveSettings(filter_comments=False,
            subscriber_only_chat=True, star_comments=False, filter_spam=False, filter_flagged=True, review_flagged=True))
        other.allow_comments_checkbox.setChecked(False)
        self.assertFalse(other.subscriber_chat_checkbox.isChecked())
        self.assertFalse(other.subscriber_chat_checkbox.isEnabled())

    def test_invalid_selection_stops_before_network(self):
        with self.stream() as (stream, send, _, _):
            with self.assertRaises(ValueError):
                stream.createStream('Fixture', '5', content_disclosure='invalid')
            stream._ensure_region_context.assert_not_called()
            send.assert_not_called()

    def test_explicit_server_contradiction_ends_new_room_before_success(self):
        for kind in ('pc', 'mobile'):
            with self.subTest(kind=kind), self.stream(kind, response=created_room(Gift=True, Chat=True)) as (stream, _, finish, _):
                with self.assertRaisesRegex(RuntimeError, 'left gifts and comments enabled'):
                    stream.createStream('Fixture', '5', allow_gifts=False, allow_comments=False)
                finish.assert_called_once()
                self.assertEqual(finish.call_args.kwargs['room_id'], '100')

    def test_failed_cleanup_is_reported(self):
        with self.stream(response=created_room(Chat=True)) as (stream, _, finish, _):
            finish.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'Cleanup failed; the new room may still be open'):
                stream.createStream('Fixture', '5', allow_comments=False)

    def test_reused_room_is_not_ended_for_a_settings_mismatch(self):
        with self.stream(response=created_room(Chat=True)) as (stream, _, finish, _):
            stream.roomId = '100'
            with self.assertRaisesRegex(RuntimeError, 'comments enabled'):
                stream.createStream('Fixture', '5', allow_comments=False)
            finish.assert_not_called()

    def test_gui_choices_persist_across_modes_and_restart(self):
        window = self.window()
        self.assertEqual(window.live_start_settings(), LiveSettings())
        self.assertTrue(window.settings_dialog.isAncestorOf(window.allow_gifts_checkbox))
        self.assertTrue(window.settings_dialog.isAncestorOf(window.content_disclosure_combo))
        window.allow_gifts_checkbox.setChecked(False)
        window.allow_comments_checkbox.setChecked(False)
        window.content_disclosure_combo.setCurrentIndex(window.content_disclosure_combo.findData('both'))
        window.device_type_combo.setCurrentIndex(1)
        window._save_workspace_settings()
        saved = json.loads(Path(self.path).read_text())
        self.assertIs(saved['allow_gifts'], False)
        self.assertIs(saved['allow_comments'], False)
        self.assertEqual(saved['content_disclosure'], 'both')
        self.assertEqual(saved['custom_future_option'], 'preserve')
        other = self.window()
        self.assertEqual(other.live_start_settings(), LiveSettings(False, False, 'both'))
        self.assertIn('Gifts off', other.stream_options_summary.text())
        self.assertIn('Comments off', other.stream_options_summary.text())
        other.device_type_combo.setCurrentIndex(0)
        self.assertEqual(other.live_start_settings(), LiveSettings(False, False, 'both'))

    def test_gui_creation_passes_selected_settings(self):
        window = self.window()
        window.title_edit.setText('Fixture')
        window._game_tags_loading = False
        window.games = {'1': 'Test game'}
        window.topic_combo.setCurrentText('Gaming')
        window.game_combo.addItem('Test game')
        window.game_combo.setCurrentText('Test game')
        window.allow_gifts_checkbox.setChecked(False)
        window.allow_comments_checkbox.setChecked(False)
        window.content_disclosure_combo.setCurrentIndex(window.content_disclosure_combo.findData('own_brand'))
        window.filter_comments_checkbox.setChecked(False)
        window.star_comments_combo.setCurrentIndex(2)
        window.spam_comments_checkbox.setChecked(False)
        window.flagged_comments_checkbox.setChecked(True)
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.getCreateRoomInfo.return_value = {'data': {}}
        stream.getContinuableStreamInfo.return_value = {'has_room': False}
        stream.createStream.return_value = False  # No proxy or heartbeat is started.
        with patch.object(window, 'stream_factory', return_value=lambda: stream), \
             patch.object(window, 'ensure_device_identifiers', return_value=True), \
             patch.object(window, 'ensure_rapidapi_signer', return_value=True), \
             patch.object(window, 'get_cookie_file_status', return_value=(True, 'Fixture cookies')), \
             patch.object(window, 'show_error') as error:
            drive_workflow(window.generate_stream.__wrapped__(window))
            error.assert_not_called()
        self.assertIs(stream.createStream.call_args.kwargs['allow_gifts'], False)
        self.assertIs(stream.createStream.call_args.kwargs['allow_comments'], False)
        self.assertEqual(stream.createStream.call_args.kwargs['content_disclosure'], 'own_brand')
        for key, value in {'filter_comments': False, 'star_comments': False, 'filter_spam': False, 'filter_flagged': True}.items():
            self.assertIs(stream.createStream.call_args.kwargs[key], value)


if __name__ == '__main__':
    unittest.main()
