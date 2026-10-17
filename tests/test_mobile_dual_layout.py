"""Offline Android dual-room and GUI checks; no real account or media used."""
from tests.gui_helpers import drive_workflow
import contextlib
import hashlib
from unittest.mock import Mock, patch
import unittest
from urllib.parse import parse_qs, urlsplit

import tests.test_client_modes as modes
import TiktokStreamKeyGenerator as gui
from PySide6.QtCore import QCoreApplication, QEvent
from Libs.mobile_dual_layout import dual_layout_info
from Libs.mobile_requests import create_room_form


def gates(*, allow=True, allowed=True, used=False, status=0):
    return ({'status_code': status, 'data': {'allow_multi_stream': allow}},
            {'status_code': status, 'data': {'allowed': allowed, 'dual_canvas_used': used}})


def room(secondary='rtmp://example.invalid/live/secondary', secondary_id='222'):
    return {'status_code': 0, 'data': {'id_str': '100', 'stream_id_str': '111',
        'stream_url': {'rtmp_push_url': 'rtmp://example.invalid/live/main'},
        'multi_stream_url': {'id_str': secondary_id, 'rtmp_push_url': secondary},
        'multi_stream_scene': 1, 'multi_stream_source': 0}}


class MobileDualTests(unittest.TestCase):
    setUpClass = classmethod(modes.ModeTests.setUpClass.__func__)
    setUp = modes.ModeTests.setUp

    def window(self):
        with patch.object(gui.StreamKeyGeneratorWindow, 'ensure_device_identifiers', return_value=True), \
                patch.object(gui.StreamKeyGeneratorWindow, 'get_cookie_file_status', return_value=(False, 'No cookies')):
            window = gui.StreamKeyGeneratorWindow()
        self.addCleanup(self.dispose_window, window)
        return window

    @staticmethod
    def dispose_window(window):
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def account(self, **options):
        return {'account': {'user_id_str': '99', 'username': 'fixture'}, 'can_go_live': True,
                'status': 'Ready', **dual_layout_info(*gates(**options))}

    @contextlib.contextmanager
    def stream(self, profile=None):
        with gui.Stream(cookies_path=self.cookies, device_type='mobile', device_profile={
                'device_id': '333', 'install_id': '444', **(profile or {})}) as stream, \
                patch.object(stream, 'getServerUrl', return_value='https://example.invalid/'), \
                patch.object(stream, '_signed_get_json', side_effect=gates()) as checks, \
                patch.object(stream, '_request_json', return_value=room()) as create, \
                patch.object(stream, 'endStream', return_value=True) as finish:
            yield stream, checks, create, finish

    def create(self, stream):
        return stream.createStream('Title + test', '5', device_id='333', install_id='444', multi_stream_scene=True)

    def test_mobile_camera_enabled_after_account_unlock_refresh(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        self.assertFalse(w.dual_layout_checkbox.isEnabled())
        w.apply_account_info(self.account())
        self.assertTrue(w.dual_layout_checkbox.isEnabled())
        self.assertEqual(w.dual_layout_output.text(), 'True')
        w.dual_layout_checkbox.setChecked(True)
        self.assertTrue(w.dual_layout_checkbox.isChecked())

    def test_screen_capture_disables_dual_then_camera_restores_capability(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        w.apply_account_info(self.account())
        w.dual_layout_checkbox.setChecked(True)
        w.mobile_broadcast_options.mode_combo.setCurrentIndex(1)
        self.assertFalse(w.dual_layout_checkbox.isEnabled())
        self.assertFalse(w.dual_layout_checkbox.isChecked())
        self.assertEqual(w.dual_layout_output.text(), 'Camera LIVE only')
        w.mobile_broadcast_options.mode_combo.setCurrentIndex(0)
        self.assertTrue(w.dual_layout_checkbox.isEnabled())
        self.assertFalse(w.dual_layout_checkbox.isChecked())

    def test_locked_mobile_account_keeps_dual_disabled(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        w.apply_account_info(self.account(allowed=False, used=False))
        self.assertFalse(w.dual_layout_checkbox.isEnabled())
        self.assertEqual(w.dual_layout_output.text(), 'False')

    def test_unknown_mobile_capability_clears_stale_selection(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        w.apply_account_info(self.account())
        w.dual_layout_checkbox.setChecked(True)
        w.apply_account_info({'account': {}, **dual_layout_info(None, None)})
        self.assertFalse(w.dual_layout_checkbox.isEnabled())
        self.assertFalse(w.dual_layout_checkbox.isChecked())
        self.assertEqual(w.dual_layout_output.text(), 'Unknown')

    def test_mobile_capability_survives_save_reload_and_stays_separate_from_pc(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        w.apply_account_info(self.account())
        w.save_config(False)
        other = self.window()
        self.assertEqual(other.device_type, 'mobile')
        self.assertTrue(other.dual_layout_checkbox.isEnabled())
        w.device_type_combo.setCurrentIndex(0)
        w.apply_account_info(self.account(allow=False))
        self.assertFalse(w.dual_layout_checkbox.isEnabled())
        w.device_type_combo.setCurrentIndex(1)
        self.assertTrue(w.dual_layout_checkbox.isEnabled())

    def test_mobile_account_refresh_queries_both_unlock_endpoints(self):
        with self.stream() as (stream, checks, _, _), \
                patch.object(stream, '_cookie_account_info', return_value={'user_id_str': '99'}), \
                patch.object(stream, 'getCreateRoomInfo', return_value={'status_code': 0, 'data': {'block_status': 0}}):
            info = stream.getAccountInfo('333', '444')
        self.assertTrue(info['dual_layout_unlocked'])
        self.assertTrue(info['can_go_live'])
        self.assertEqual(checks.call_args_list[0].kwargs['params']['scene'], '1')
        self.assertTrue(checks.call_args_list[1].args[0].endswith('/threshold/check/'))
        self.assertTrue(all(c.kwargs['params']['aid'] == '1233' for c in checks.call_args_list))

    def test_android_create_uses_camera_form_and_explicit_studio_mode(self):
        with self.stream({'create_params': {'live_studio': '0', 'multi_stream_source': '2',
                                          'live_room_mode': '4'}}) as (stream, checks, create, finish):
            self.assertTrue(self.create(stream))
            params = create.call_args.kwargs['params']
            body = parse_qs(create.call_args.kwargs['data'].decode())
            self.assertEqual(params['live_mode'], '6')
            self.assertEqual(params['aid'], '1233')
            self.assertEqual(params['version_code'], '470104')
            self.assertEqual(body['live_studio'], ['1'])
            self.assertEqual(body['multi_stream_scene'], ['1'])
            self.assertEqual(body['multi_stream_source'], ['1'])
            for key in ('screen_shot', 'live_room_mode', 'orientation', 'game_tag_id'):
                self.assertNotIn(key, body)
            self.assertEqual(checks.call_count, 2)
            self.assertNotIn('live_mode', stream._studio_params(device_id='333', install_id='444'))
            finish.assert_not_called()

    def test_transport_signs_mode_six_after_merging_saved_capture_overrides(self):
        profile = {'request_params': {'live_room_mode': '4', 'screen_shot': '1', 'orientation': '2'}}
        with self.stream(profile) as (stream, _, create, _):
            self.create(stream)
            args = create.call_args
            stream.s.cookies.update({'sessionid': 'fixture-cookie'})
            response = Mock(status_code=200, headers={})
            response.json.return_value = room()
            with patch.object(stream.s, 'request', return_value=response) as send, \
                    patch.object(stream.client, 'signature_headers', return_value={'x-argus': 'fixture'}) as sign, \
                    patch.object(stream, 'save_cookies'), patch.object(gui, '_audit_webcast_request'):
                gui.Stream._request_json(stream, 'POST', args.args[1], **args.kwargs)
            signed = sign.call_args.kwargs
            query = parse_qs(urlsplit(signed['url']).query)
            self.assertEqual(query['live_mode'], ['6'])
            self.assertEqual(query['version_name'], ['47.1.4'])
            self.assertEqual(query['iid'], ['444'])
            self.assertEqual(query['aid'], ['1233'])
            for key in profile['request_params']:
                self.assertNotIn(key, query)
            self.assertEqual(signed['body'], send.call_args.kwargs['data'])
            self.assertEqual(signed['url'], send.call_args.kwargs['url'])
            self.assertIn('sessionid=fixture-cookie', signed['headers']['Cookie'])
            self.assertEqual(send.call_args.kwargs['headers']['x-argus'], 'fixture')
            self.assertEqual(hashlib.md5(signed['body']).hexdigest(), args.kwargs['headers']['x-ss-stub'])
            self.assertEqual(stream.client.record['request_params'], profile['request_params'])

    def test_screen_capture_cannot_create_dual_even_without_gui(self):
        with self.stream({'broadcast_type': 'screen_record', 'orientation': '2'}) as (stream, checks, create, _):
            with self.assertRaisesRegex(ValueError, 'Camera LIVE'):
                self.create(stream)
            checks.assert_not_called()
            create.assert_not_called()

    def test_single_canvas_mobile_still_omits_dual_and_studio_flags(self):
        with self.stream() as (stream, checks, create, _):
            self.assertTrue(stream.createStream('Title', '5'))
            body = parse_qs(create.call_args.kwargs['data'].decode())
            self.assertNotIn('live_studio', body)
            self.assertNotIn('multi_stream_scene', body)
            self.assertNotIn('live_mode', create.call_args.kwargs['params'])
            checks.assert_not_called()

    def test_failed_or_locked_unlock_check_prevents_room_creation(self):
        for options in ({'allowed': False, 'used': False}, {'allow': 'false'}, {'status': 5}):
            with self.subTest(options=options), self.stream() as (stream, checks, create, finish):
                checks.side_effect = gates(**options)
                with self.assertRaisesRegex(RuntimeError, 'not unlocked'):
                    self.create(stream)
                create.assert_not_called()
                finish.assert_not_called()

    def test_partial_allocation_finishes_new_room_before_proxies(self):
        for url, identifier in (('', '0'), ('rtmp://example.invalid/live/main', '222'),
                                ('rtmp://example.invalid/live/secondary', '0')):
            with self.subTest(url=url, identifier=identifier), self.stream() as (stream, _, create, finish):
                create.return_value = room(url, identifier)
                with self.assertRaisesRegex(RuntimeError, 'ended before either proxy started'):
                    self.create(stream)
                finish.assert_called_once_with(device_id='333', install_id='444', priority_region='',
                                               room_id='100', stream_id='111')

    def test_cleanup_failure_is_reported_and_existing_room_is_preserved(self):
        with self.stream() as (stream, checks, create, finish):
            create.return_value = room('', '0')
            finish.side_effect = RuntimeError('fixture timeout')
            with self.assertRaisesRegex(RuntimeError, 'Cleanup failed'):
                self.create(stream)
            finish.reset_mock()
            checks.side_effect = gates()
            with self.assertRaisesRegex(RuntimeError, 'did not allocate'):
                self.create(stream)  # Same room is already known to this client.
            finish.assert_not_called()

    def test_both_obs_outputs_use_normal_dual_mapping_for_mobile(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        with self.stream() as (stream, _, _, _):
            stream._apply_room_info(room()['data'])
            with patch.object(w, 'start_ffmpeg_proxy') as landscape, \
                    patch.object(w, 'start_portrait_ffmpeg_proxy') as portrait:
                drive_workflow(w.apply_stream_outputs(stream, dual_layout=True))
            landscape.assert_called_once_with(stream.multiStreamUrl, defer_display=True)
            portrait.assert_called_once_with(stream.streamUrl)
            self.assertTrue(w.dual_layout_active)
            stream.multiStreamUrl = stream.streamUrl
            with patch.object(w, 'start_ffmpeg_proxy') as landscape, \
                    self.assertRaisesRegex(RuntimeError, 'two distinct push URLs'):
                drive_workflow(w.apply_stream_outputs(stream, dual_layout=True))
            landscape.assert_not_called()


class DualPermissionTests(unittest.TestCase):
    def test_threshold_uses_allowed_or_previously_used(self):
        for allowed, used in ((True, False), (False, True), (True, True)):
            self.assertTrue(dual_layout_info(*gates(allowed=allowed, used=used))['dual_layout_unlocked'])
        self.assertFalse(dual_layout_info(*gates(allowed=False, used=False))['dual_layout_unlocked'])

    def test_missing_or_failed_checks_fail_closed(self):
        for scene, threshold in ((None, gates()[1]), (gates()[0], None),
                                 (gates(status=5)[0], gates()[1]), (gates()[0], gates(status=5)[1])):
            self.assertFalse(dual_layout_info(scene, threshold)['dual_layout_unlocked'])

    def test_string_false_is_not_treated_as_enabled(self):
        self.assertFalse(dual_layout_info(*gates(allow='false'))['dual_layout_unlocked'])
        self.assertFalse(dual_layout_info(*gates(allowed='false', used='0'))['dual_layout_unlocked'])
        self.assertTrue(dual_layout_info(*gates(allow='true', allowed='1', used='false'))['dual_layout_unlocked'])

    def test_camera_single_form_cannot_inherit_dual_flags(self):
        form = create_room_form({'create_params': {'live_studio': '1', 'multi_stream_scene': '1'}},
                                title='test', hashtag_id='5')
        self.assertNotIn('live_studio', form)
        self.assertNotIn('multi_stream_scene', form)


if __name__ == '__main__':
    unittest.main()
