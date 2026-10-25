"""Offline GUI/profile/transport tests. Real config and network are never used."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

import TiktokStreamKeyGenerator as gui
from Libs.client_profiles import ClientImplementation, device_records, mobile_record_defaults
from Libs.mobile_requests import create_room_form
from Libs import signing_backend as backend
from Libs import signers as hosted_headers


class ModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'config.json')
        self.cookies = str(Path(self.temp.name) / 'cookies.json')
        Path(self.cookies).write_text('[]')
        self.config = {'device_id': '111', 'install_id': '222', 'cookies_path': self.cookies,
                       'dual_layout_supported': True, 'custom_future_option': 'preserve', 'suppress_donation_reminder': True}
        Path(self.path).write_text(json.dumps(self.config))
        p = patch.object(gui.LiveChatClient, 'start')
        p.start()
        self.addCleanup(p.stop)
        for name, value in [('CONFIG_PATH', self.path), ('DEFAULT_COOKIES_PATH', self.cookies),
                            ('fetch_game_tags', lambda: {'1': 'Test game'})]:
            p = patch.object(gui, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'dev'})
        p.start()
        self.addCleanup(p.stop)
        # Any accidental real network request fails immediately.
        for target in ('requests.sessions.Session.request', 'curl_cffi.requests.Session.request'):
            p = patch(target, side_effect=AssertionError('Unexpected network call'))
            p.start()
            self.addCleanup(p.stop)

    def window(self):
        with patch.object(gui.StreamKeyGeneratorWindow, 'ensure_device_identifiers', return_value=True), \
             patch.object(gui.StreamKeyGeneratorWindow, 'get_cookie_file_status', return_value=(False, 'No cookies')):
            window = gui.StreamKeyGeneratorWindow()
        def dispose():
            window.close()
            window.deleteLater()
            # Closed windows otherwise retain delayed startup callbacks that
            # can run under a later test's mocked Thread constructor.
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.addCleanup(dispose)
        return window

    def test_legacy_ids_remain_pc_even_if_mode_mobile(self):
        records = device_records({**self.config, 'device_type': 'mobile'})
        self.assertEqual(records['pc']['device_id'], '111')
        self.assertNotIn('mobile', records)

    def test_gui_switch_roundtrip_preserves_both_records(self):
        w = self.window()
        self.assertEqual(w.device_type, 'pc')
        self.assertTrue(w.dual_layout_checkbox.isEnabled())
        w.device_type_combo.setCurrentIndex(1)
        self.assertEqual((w.device_id, w.install_id), ('', ''))
        self.assertFalse(w.dual_layout_checkbox.isEnabled())
        self.assertFalse(w.login_button.isEnabled())
        self.assertFalse(w.close_room_checkbox.isEnabled())
        w.device_id, w.install_id = '333', '444'
        w.save_config(False)
        w.device_type_combo.setCurrentIndex(0)
        self.assertEqual((w.device_id, w.install_id), ('111', '222'))
        self.assertTrue(w.dual_layout_checkbox.isEnabled())
        w.device_type_combo.setCurrentIndex(1)
        self.assertEqual((w.device_id, w.install_id), ('333', '444'))
        data = json.loads(Path(self.path).read_text())
        self.assertEqual(data['devices']['pc']['device_id'], '111')
        self.assertEqual(data['devices']['mobile']['device_id'], '333')
        self.assertEqual(data['custom_future_option'], 'preserve')
        other = self.window()
        self.assertEqual((other.device_type, other.device_id), ('mobile', '333'))

    def test_mode_changes_blocked_while_live_or_registering(self):
        w = self.window()
        for attribute in ('is_live', 'device_initialization_in_flight'):
            setattr(w, attribute, True)
            w.device_type_combo.setCurrentIndex(1)
            self.assertEqual(w.device_type, 'pc')
            self.assertEqual(w.device_type_combo.currentData(), 'pc')
            setattr(w, attribute, False)

    def test_mode_switch_reloads_account_and_discards_superseded_refresh(self):
        w = self.window()
        w.devices['mobile'].update(device_id='333', install_id='444')
        with patch.object(w, 'get_cookie_file_status', return_value=(True, 'Fixture cookies')), \
             patch.object(w, 'refresh_account_info') as refresh:
            w.device_type_combo.setCurrentIndex(1)
            self.app.processEvents()
            refresh.assert_called_once_with(show_errors=False)
            refresh.reset_mock()
            w.device_type_combo.setCurrentIndex(0)
            w.device_type_combo.setCurrentIndex(1)
            self.app.processEvents()
            refresh.assert_called_once_with(show_errors=False)

    def test_tool_buttons_and_tooltips_use_valid_point_fonts(self):
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtCore import QSize, qInstallMessageHandler
        from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QStyleOptionMenuItem, QToolTip
        from Libs.fluent_ui import ToolButton, style_controls
        container = gui.QWidget()
        button = ToolButton(parent=container)
        button.setToolTip('Device settings')
        # Fluent's constructor uses a pixel font. Exercise the native drawing
        # path that reads pointSize(), after applying our normalization.
        style_controls(container)
        self.assertGreater(button.font().pointSize(), 0)
        self.assertGreater(QToolTip.font().pointSize(), 0)
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
        try:
            image = QPixmap(100, 100)
            image.fill()
            painter = QPainter(image)
            painter.setFont(button.font())
            option = QStyleOptionToolButton()
            option.initFrom(button)
            option.subControls = QStyle.SC_ToolButton | QStyle.SC_ToolButtonMenu
            option.features = QStyleOptionToolButton.HasMenu | QStyleOptionToolButton.MenuButtonPopup
            button.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, button)
            menu = QStyleOptionMenuItem()
            menu.font = button.font()
            menu.menuItemType = QStyleOptionMenuItem.SubMenu
            button.style().sizeFromContents(QStyle.CT_MenuItem, menu, QSize(100, 30), button)
            painter.end()
        finally:
            qInstallMessageHandler(previous)
        self.assertFalse(any('QFont::setPointSize' in message for message in messages))

    def test_mobile_missing_ids_never_registers_pc(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        with patch.object(gui, 'register_desktop_device_identifiers') as registration, \
             patch.object(w, 'start_device_initialization') as initialize:
            self.assertFalse(w.ensure_device_identifiers())
        initialize.assert_called_once()
        registration.assert_not_called()

    def test_device_dialog_saves_ids_and_preserves_hidden_fingerprint_and_queries(self):
        record = {'fingerprint': {'model': 'Phone model'}, 'request_params': {'region': 'tn'}}
        dialog = gui.DeviceSettingsDialog('mobile', record)
        dialog.fields['device_id'].setText('333')
        dialog.fields['install_id'].setText('444')
        dialog.save_record()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(set(dialog.fields), {'device_id', 'install_id'})
        self.assertEqual(dialog.record['fingerprint']['model'], 'Phone model')
        self.assertEqual(dialog.record['request_params']['region'], 'tn')
        self.assertEqual(record, {'fingerprint': {'model': 'Phone model'}, 'request_params': {'region': 'tn'}})

    def test_mobile_broadcast_selectors_persist_and_map_room_fields(self):
        w = self.window()
        self.assertTrue(w.mobile_broadcast_options.isHidden())
        w.device_type_combo.setCurrentIndex(1)
        controls = w.mobile_broadcast_options
        self.assertFalse(controls.isHidden())
        self.assertEqual(controls.mode_combo.currentData(), 'video')
        self.assertTrue(controls.orientation_row.isHidden())
        w.topic_combo.setCurrentText('Gaming')
        self.assertTrue(w.game_combo.isHidden())
        controls.mode_combo.setCurrentIndex(1)
        controls.orientation_combo.setCurrentIndex(1)
        self.assertFalse(controls.orientation_row.isHidden())
        self.assertFalse(w.game_combo.isHidden())
        data = json.loads(Path(self.path).read_text())
        profile = data['devices']['mobile']
        self.assertEqual((profile['broadcast_type'], profile['orientation']), ('screen_record', '2'))
        self.assertEqual(data['devices']['pc']['device_id'], '111')
        form = create_room_form(profile, title='Test', hashtag_id='5', game_tag_id='9')
        self.assertEqual((form['screen_shot'], form['live_room_mode'], form['orientation'], form['game_tag_id']),
                         ('1', '4', '2', '9'))
        w.device_type_combo.setCurrentIndex(0)
        self.assertTrue(controls.isHidden())
        w.device_type_combo.setCurrentIndex(1)
        self.assertEqual((controls.mode_combo.currentData(), controls.orientation_combo.currentData()), ('screen_record', '2'))
        controls.mode_combo.setCurrentIndex(0)
        self.assertTrue(controls.orientation_row.isHidden())
        self.assertTrue(w.game_combo.isHidden())
        form = create_room_form(w.saved_device_records()['mobile'], title='Test', hashtag_id='5')
        for field in ('screen_shot', 'live_room_mode', 'orientation', 'game_tag_id'):
            self.assertNotIn(field, form)
        other = self.window()
        self.assertEqual(other.mobile_broadcast_options.mode_combo.currentData(), 'video')
        other.mobile_broadcast_options.mode_combo.setCurrentIndex(1)
        self.assertEqual(other.mobile_broadcast_options.orientation_combo.currentData(), '2')

    def test_mobile_broadcast_changes_locked_while_busy(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        controls = w.mobile_broadcast_options
        controls.mode_combo.setCurrentIndex(1)
        for attribute in ('is_live', 'local_proxy_starting', 'account_info_in_flight',
                          'realtime_stats_in_flight', 'audience_safety_in_flight', 'anchor_heartbeat_in_flight'):
            with self.subTest(attribute=attribute):
                before = Path(self.path).read_bytes()
                setattr(w, attribute, True)
                w.update_stream_controls(has_cookies=False)
                self.assertFalse(controls.isEnabled())
                controls.mode_combo.setCurrentIndex(0)
                controls.orientation_combo.setCurrentIndex(1)
                self.assertEqual((controls.mode_combo.currentData(), controls.orientation_combo.currentData()), ('screen_record', '1'))
                self.assertEqual(Path(self.path).read_bytes(), before)
                setattr(w, attribute, False)
                w.update_stream_controls(has_cookies=False)
                self.assertTrue(controls.isEnabled())

    def test_device_dialog_has_no_broadcast_or_advanced_inputs(self):
        record = {'identifiers': {'android_id': 'abcdef0123456789'},
                  'broadcast_type': 'screen_record', 'orientation': '2',
                  'create_params': {'captured_field': 'value'}, 'request_params': {'region': 'tn'}}
        dialog = gui.DeviceSettingsDialog('mobile', record)
        self.assertFalse(hasattr(dialog, 'mobile_broadcast_options'))
        self.assertFalse(hasattr(dialog, 'params'))
        self.assertFalse(hasattr(dialog, 'registration_settings'))
        dialog.save_record()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.record['broadcast_type'], 'screen_record')
        self.assertEqual(dialog.record['orientation'], '2')
        self.assertEqual(dialog.record['create_params'], {'captured_field': 'value'})
        self.assertEqual(dialog.record['request_params'], {'region': 'tn'})

    def test_selectors_preserve_existing_captured_orientation(self):
        record = {'broadcast_type': 'screen_record', 'orientation': '0', 'create_params': {'captured': 'field'}}
        controls = gui.MobileBroadcastOptions(record)
        self.assertEqual(controls.orientation_combo.currentData(), '0')
        controls.update_record(record)
        self.assertEqual(record['orientation'], '0')
        self.assertEqual(record['create_params'], {'captured': 'field'})

    def test_android_query_spelling_and_identity_protection(self):
        record = mobile_record_defaults({'device_id': '333', 'install_id': '444',
                    'fingerprint': {'model': 'Phone', 'brand': 'Brand', 'os_api': '35'},
                    'request_params': {'iid': 'bad', 'aid': '8311', 'live_studio': '1', 'region': 'tn'}})
        params = ClientImplementation('mobile', record).mobile_params(device_id='333', install_id='444')
        self.assertEqual((params['aid'], params['iid'], params['device_type']), ('1233', '444', 'Phone'))
        self.assertEqual(params['region'], 'tn')
        self.assertNotIn('install_id', params)
        self.assertNotIn('live_studio', params)
        self.assertNotIn('live_mode', params)
        self.assertEqual(params['version_code'], '470104')
        self.assertEqual(params['manifest_version_code'], '2024701040')
        self.assertEqual(params['update_version_code'], '2024701040')

    def test_android_app_and_build_versions_stay_distinct(self):
        record = mobile_record_defaults({'app_version': '47.2.5', 'version_code': '2024702050',
                    'request_params': {'version_code': '8311', 'version_name': '1.27.0'}})
        params = ClientImplementation('mobile', record).mobile_params(device_id='333', install_id='444')
        self.assertEqual((params['version_name'], params['version_code']), ('47.2.5', '470205'))
        self.assertEqual((params['manifest_version_code'], params['update_version_code']),
                         ('2024702050', '2024702050'))
        self.assertEqual(record['version_code'], '2024702050')

    def test_other_mobile_endpoints_sign_corrected_common_query(self):
        cases = (
            ('GET', 'passport/account/info/v2/'),
            ('GET', 'webcast/room/hashtag/list/'),
            ('GET', 'webcast/game/basic/create_info/'),
            ('GET', 'webcast/game/studio/realtime_stats/'),
            ('GET', 'webcast/room/info/'),
            ('GET', 'webcast/ranklist/online_audience/'),
            ('POST', 'webcast/room/create_info/'),
            ('POST', 'webcast/room/ping/anchor/'),
            ('POST', 'webcast/room/create/'),
        )
        with gui.Stream(cookies_path=self.cookies, device_type='mobile', device_profile={
                'device_id': '333', 'install_id': '444'}) as stream, \
             patch.object(stream.client, 'signature_headers', return_value={'x-argus': 'fixture'}) as sign, \
             patch.object(stream.s, 'request', return_value=Mock(status_code=200, headers={},
                 json=lambda: {'status_code': 0})), patch.object(stream, 'save_cookies'):
            for method, path in cases:
                with self.subTest(path=path):
                    stream._request_json(method, 'https://example.test/' + path,
                        params={'version_code': '2024701040', 'device_platform': 'PC'},
                        data=b'{}' if method == 'POST' else None)
                    query = parse_qs(urlsplit(sign.call_args.kwargs['url']).query)
                    self.assertEqual(query['device_platform'], ['android'])
                    self.assertEqual(query['version_code'], ['470104'])
                    self.assertEqual(query['manifest_version_code'], ['2024701040'])
                    self.assertEqual(query['update_version_code'], ['2024701040'])

    def test_room_form_mobile_camera_and_screen_capture(self):
        form = create_room_form({}, title='Title', hashtag_id='5', game_tag_id='9', age_restricted=True)
        self.assertEqual((form['age_restricted'], form['chat_l_2']), ('4', '1'))
        self.assertNotIn('chat_l2', form)
        self.assertNotIn('game_tag_id', form)
        self.assertGreater(int(form['timestamp']), 10**12)
        with self.assertRaises(ValueError):
            create_room_form({'broadcast_type': 'screen_record'}, title='', hashtag_id='5')
        form = create_room_form({'broadcast_type': 'screen_record', 'orientation': '1',
                                 'create_params': {'multi_stream_scene': '1', 'live_studio': '1'}},
                                 title='T', hashtag_id='5', game_tag_id='9')
        self.assertEqual((form['screen_shot'], form['live_room_mode'], form['game_tag_id']), ('1', '4', '9'))
        self.assertNotIn('multi_stream_scene', form)
        self.assertNotIn('live_studio', form)

    def test_mobile_signs_exact_url_cookie_body_per_host(self):
        with gui.Stream(cookies_path=self.cookies, device_type='mobile', device_profile={
                'device_id': '333', 'install_id': '444'}) as stream:
            stream.s.cookies.update({'sessionid': 'test-only'})
            response = unittest.mock.Mock(status_code=200, headers={}, text='{}')
            response.json.return_value = {'data': {}}
            with patch.object(stream.client, 'signature_headers', return_value={'x-gorgon': 'test'}) as sign, \
                 patch.object(stream.s, 'request', return_value=response) as send, \
                 patch.object(stream, 'save_cookies'), patch.object(gui, '_audit_webcast_request'):
                for host in ('webcast-a.example', 'webcast-b.example'):
                    stream._request_json('POST', f'https://{host}/webcast/room/create/',
                        params={'title': 'A B+é', 'aid': '8311'}, data={'title': 'A B+é'})
                    sent = send.call_args.kwargs
                    signed = sign.call_args.kwargs
                    self.assertEqual(sent['url'], signed['url'])
                    self.assertEqual(sent['data'], signed['body'])
                    self.assertEqual(sent['headers']['Cookie'], signed['headers']['Cookie'])
                    self.assertIn('sessionid=test-only', signed['headers']['Cookie'])
                    self.assertFalse(sent['allow_redirects'])
                    self.assertIsNone(sent['params'])
                    q = parse_qs(urlsplit(sent['url']).query)
                    self.assertEqual((q['aid'], q['iid'], q['device_id']), (['1233'], ['444'], ['333']))
                self.assertEqual(sign.call_count, 2)
                self.assertNotEqual(sign.call_args_list[0].kwargs['url'], sign.call_args_list[1].kwargs['url'])

    def test_create_info_mobile_body_and_pc_query_remain_distinct(self):
        for kind in ('pc', 'mobile'):
            with gui.Stream(cookies_path=self.cookies, device_type=kind,
                            device_profile={'device_id': '333', 'install_id': '444'}) as stream, \
                 patch.object(stream, 'getServerUrl', return_value='https://test/'), \
                 patch.object(stream, 'getLiveStudioLatestVersion', return_value='1.27.0'), \
                 patch.object(stream, '_signed_get_json', return_value={}) as get, \
                 patch.object(stream, '_request_json_with_webcast_fallback', return_value={}) as post:
                stream.getCreateRoomInfo('333', '444', last_time_hashtag_id='6')
                if kind == 'mobile':
                    get.assert_not_called()
                    self.assertEqual(post.call_args.args[0], 'POST')
                    args = post.call_args.kwargs
                    body = json.loads(args['data'])
                    self.assertEqual((body['last_time_hashtag_id'], body['live_studio']), (6, 0))
                    self.assertNotIn('last_time_hashtag_id', args['params'])
                else:
                    post.assert_not_called()
                    self.assertEqual(get.call_args.kwargs['params']['live_studio'], '1')

    def test_mobile_account_identity_comes_from_cookie_account(self):
        account = {'user_id_str': '99', 'username': 'fixture-account'}
        capability = {'status_code': 0, 'data': {'block_status': 0,
                      'owner': {'username': 'wrong-owner'}, 'ban_status': {'is_ban': False}}}
        with gui.Stream(cookies_path=self.cookies, device_type='mobile', device_profile={
                'device_id': '333', 'install_id': '444'}) as stream, \
             patch.object(gui, 'build_endpoint', return_value='https://api.test/passport/account/info/v2/'), \
             patch.object(stream, '_signed_get_json', return_value={'message': 'success', 'data': account}) as get, \
             patch.object(stream, 'getCreateRoomInfo', return_value=capability):
            info = stream.getAccountInfo('333', '444')
            self.assertEqual(info['account'], account)
            self.assertTrue(info['can_go_live'])
            self.assertEqual(get.call_args.kwargs['params']['aid'], '1233')
            w = self.window()
            w.apply_account_info(info)
            self.assertEqual(w.account_username.text(), 'fixture-account')
            self.assertEqual(w.account_user_id_value, '99')
            capability['data']['ban_status']['is_ban'] = True
            self.assertFalse(stream.getAccountInfo('333', '444')['can_go_live'])

    def test_mobile_invalid_cookies_do_not_look_like_ready_account(self):
        with gui.Stream(cookies_path=self.cookies, device_type='mobile', device_profile={
                'device_id': '333', 'install_id': '444'}) as stream, \
             patch.object(gui, 'build_endpoint', return_value='https://api.test/'), \
             patch.object(stream, 'getCreateRoomInfo') as create:
            for payload in ({'message': 'error', 'data': {'error_code': 9, 'user_id': 0}},
                            {'message': 'success', 'data': {}}, {'data': []}):
                with patch.object(stream, '_signed_get_json', return_value=payload), \
                     self.assertRaisesRegex(RuntimeError, 'Cannot identify the signed-in account'):
                    stream.getAccountInfo('333', '444')
            create.assert_not_called()

    def test_domain_dispatch_uses_android_identity_without_pc_cache(self):
        from Libs import domain_routing as routing
        with gui.Stream(cookies_path=self.cookies, device_type='mobile', device_profile={
                'device_id': '333', 'install_id': '444'}) as stream, \
             patch.object(routing, '_fetch_strategy_maps', return_value=[{'a': 'b'}]) as fetch, \
             patch.dict(routing._DISPATCH_CACHE, {'strategy_maps': [{'pc': 'cached'}], 'fetched_at': 10**12}):
            params = routing._tnc_discovery_params(stream.s)
            self.assertEqual((params['aid'], params['device_platform'], params['iid']), ('1233', 'android', '444'))
            self.assertEqual(params['version_code'], '470104')
            self.assertEqual(params['ttnet_version'], '4.2.243.64-tiktok')
            self.assertEqual(params['cronet_version'], 'eeeffe19_2026-08-31')
            self.assertNotIn('ttwebview_version', params)
            self.assertNotIn('sec-ch-ua-platform', routing.build_common_headers(stream.s))
            self.assertEqual(routing._get_strategy_maps(stream.s), [{'a': 'b'}])
            routing._get_strategy_maps(stream.s)
            fetch.assert_called_once()

    def test_pc_registration_saves_the_actual_fingerprint(self):
        from Libs import device_gen
        fingerprint = device_gen.generate_desktop_fingerprint()
        session = unittest.mock.Mock(headers={})
        session.post.return_value.json.return_value = {'device_id': '111', 'install_id': '222'}
        with patch.object(device_gen, 'generate_private_pc_identifiers', return_value=('uuid', 'serial')), \
             patch.object(device_gen, 'generate_desktop_fingerprint', return_value=fingerprint), \
             patch.object(device_gen, 'fetch_live_studio_latest_version', return_value='1.27.0'), \
             patch.object(device_gen, 'get_device_register_endpoint', return_value='https://test/'), \
             patch.object(device_gen, 'update_ntp_from_response'):
            record = device_gen.register_desktop_device_identifiers(session, return_profile=True)
            self.assertEqual(record['fingerprint'], fingerprint)
            self.assertEqual(record['identifiers'], {'pc_uuid': 'uuid', 'pc_serial': 'serial'})
            query = dict(session.post.call_args.kwargs['params'])
            self.assertEqual(query['screen_width'], fingerprint['screen_width'])
            self.assertEqual(query['timezone_name'], fingerprint['timezone_name'])

    def test_proxy_uses_selected_signature_and_single_mobile_canvas(self):
        from Libs import ffmpeg_sei_proxy as proxy
        outputs = {'signinfo': 'i', 'signvalue': 'v', 'signversion': '2.0', 'lid': '123'}
        with patch.object(proxy, 'frame_sign', return_value=outputs) as sign:
            mobile = proxy.LocalSeiSigner(uid='1', device_id='333', room_id='2', aid='1233',
                         width=1080, height=1920, implementation='mobile', device_profile={'install_id': '444'})
            payload = json.loads(mobile.startup_signed_payload(now_ms=1700000000000)[4:])
            self.assertNotIn('ttls_live_scene', payload)
            self.assertEqual(payload['signResult']['signversion'], '2.0')
            self.assertEqual(sign.call_args.kwargs['implementation'], 'mobile')
            pc = proxy.LocalSeiSigner(uid='1', device_id='111', room_id='2', aid='8311', width=1920, height=1080)
            payload = json.loads(pc.startup_signed_payload(now_ms=1700000000000)[4:])
            self.assertEqual(payload['ttls_live_scene'], 'live_studio')
            self.assertEqual(sign.call_args.kwargs['implementation'], 'pc')



    def test_production_has_no_local_fallback(self):
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api'}), \
             patch.object(hosted_headers, 'signature_headers', side_effect=RuntimeError('API down')), \
             patch.object(backend.importlib, 'import_module') as local:
            with self.assertRaisesRegex(RuntimeError, 'API down'):
                backend.signature_headers(1700000000)
            local.assert_not_called()

    def test_packaged_app_refuses_dev_mode(self):
        with patch.object(backend.sys, 'frozen', True, create=True):
            with self.assertRaisesRegex(RuntimeError, 'production'):
                backend.is_development()

    def test_mobile_production_is_gated_until_api_updated(self):
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api', 'TIKTOK_MOBILE_API_ENABLED': '0'}), \
             patch('Libs.signers._post_signatures') as send:
            with self.assertRaisesRegex(RuntimeError, 'hosted API yet'):
                backend.validate_mobile({'device_id': '333', 'install_id': '444'})
            send.assert_not_called()

    def test_future_mobile_api_contract_and_required_gorgon(self):
        output = {'x-khronos': '1700000000', 'x-argus': 'a', 'x-ladon': 'l', 'x-gorgon': 'g'}
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api', 'TIKTOK_MOBILE_API_ENABLED': '1'}), \
             patch('Libs.signers._should_use_api', return_value=True), \
             patch('Libs.signers._post_signatures', return_value=output) as api:
            backend.signature_headers(1700000000, '1233', implementation='mobile', url='https://test/',
                                      headers={'Cookie': 'test'}, body=b'ab', install_id='444')
            payload = api.call_args.args[0]
            self.assertEqual((payload['implementation'], payload['body_base64'], payload['install_id']),
                             ('mobile', 'YWI=', '444'))
            output.pop('x-gorgon')
            with self.assertRaisesRegex(RuntimeError, 'x-gorgon'):
                backend.signature_headers(1700000000, '1233', implementation='mobile')

    def test_future_mobile_frames_never_use_pc_batch_cache(self):
        from Libs import XFrameSign as hosted
        result = {'signversion': '2.0', 'signinfo': 'i', 'signvalue': 'v', 'lid': '123'}
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api', 'TIKTOK_MOBILE_API_ENABLED': '1'}), \
             patch.object(hosted_headers, '_should_use_api', return_value=True), \
             patch.object(hosted, '_post_json', return_value=result) as api, \
             patch.object(hosted, '_frame_sign_from_cache') as cache:
            backend.frame_sign({'aid': '1233'}, implementation='mobile', device_profile={'frame_sdk': {}})
            self.assertEqual(api.call_args.args[1]['implementation'], 'mobile')
            cache.assert_not_called()
            result['signversion'] = '1.0'
            with self.assertRaisesRegex(RuntimeError, '2.0'):
                backend.frame_sign({'aid': '1233'}, implementation='mobile', device_profile={'frame_sdk': {}})


    def test_public_android_registration_sends_prepared_bytes_and_retains_identity(self):
        import base64
        import copy
        import hashlib
        from Libs.mobile_device_gen import generate_mobile_device, register_mobile_device
        record = generate_mobile_device(fingerprint={'model': 'fixture-model', 'brand': 'fixture-brand', 'os_version': '14', 'os_api': '34'})
        original = copy.deepcopy(record)
        body = b'prepared fixture bytes'
        wire = {'success': True, 'method': 'POST', 'url': 'https://log-va.tiktokv.com/service/2/device_register/?aid=1233',
                'body_base64': base64.b64encode(body).decode(), 'headers': {'x-ss-stub': hashlib.md5(body).hexdigest()}}
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'device_id_str': '333', 'install_id_str': '444', 'device_token': 'fixture-token'}
        class Session:
            def post(self, url, **options):
                self.sent = url, options
                return Response()
        client = Session()
        result = register_mobile_device(record, session=client, prepare=lambda *args, **kwargs: wire)
        self.assertEqual(client.sent[1]['data'], body)
        self.assertFalse(client.sent[1]['allow_redirects'])
        self.assertEqual((result['device_id'], result['install_id']), ('333', '444'))
        self.assertEqual(result['identifiers'], record['identifiers'])
        self.assertEqual(result['registration']['device_token'], 'fixture-token')
        self.assertEqual(record, original)
        wire['url'] = 'https://example.test/service/2/device_register/'
        with self.assertRaisesRegex(ValueError, 'unexpected registration URL'):
            register_mobile_device(record, session=client, prepare=lambda *args, **kwargs: wire)

    def test_android_registration_is_local_in_dev_and_packaged_prod(self):
        import base64
        import gzip
        import hashlib
        from Libs.mobile_device_gen import generate_mobile_device, prepare_mobile_registration
        from Libs.mobile_log_encrypt_codec import tt_decrypt
        record = generate_mobile_device(fingerprint={'model': 'fixture-model', 'brand': 'fixture-brand', 'os_version': '14', 'os_api': '34'})
        for mode in ('dev', 'api'):
            with self.subTest(mode=mode), \
                 patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': mode, 'TIKTOK_MOBILE_API_ENABLED': '0', 'RAPIDAPI_KEY': ''}), \
                 patch.object(backend.sys, 'frozen', mode == 'api', create=True), \
                 patch('Libs.XFrameSign._post_json', side_effect=AssertionError('Registration used API')), \
                 patch.object(hosted_headers, 'mobile_api_ready', side_effect=AssertionError('Registration required API')), \
                 patch.object(backend.importlib, 'import_module', side_effect=AssertionError('Registration imported DevTools')):
                decoded = []
                for encoding in ('gzip', 'ttencrypt'):
                    options = dict(timestamp_ms=1700000000000, req_id='00000000-0000-0000-0000-000000000001',
                                   encoding=encoding, seed=b'\x01' * 32)
                    result = prepare_mobile_registration(record, **options)
                    self.assertEqual(result, backend.prepare_mobile_registration(record, **options))
                    body = base64.b64decode(result['body_base64'])
                    self.assertEqual(result['headers']['x-ss-stub'], hashlib.md5(body).hexdigest())
                    self.assertEqual(result['headers']['x-tt-request-tag'], 't=0;n=1')
                    self.assertEqual(parse_qs(urlsplit(result['url']).query)['device_platform'], ['android'])
                    self.assertEqual(parse_qs(urlsplit(result['url']).query)['version_code'], ['470104'])
                    decoded.append(json.loads(gzip.decompress(body if encoding == 'gzip' else tt_decrypt(body))))
                self.assertEqual(decoded[0], decoded[1])
                self.assertEqual(decoded[0]['header']['openudid'], record['identifiers']['android_id'])
                self.assertEqual(decoded[0]['header']['version_code'], 470104)

    def test_captured_registration_transport_sends_gzip_but_hashes_json(self):
        import base64
        import gzip
        import hashlib
        from Libs.mobile_device_gen import generate_mobile_device, prepare_mobile_registration, register_mobile_device
        record = generate_mobile_device(fingerprint={'model': 'fixture-model', 'brand': 'fixture-brand', 'os_version': '14', 'os_api': '34'})
        record['registration_options'] = {'encoding': 'json-gzip', 'host': 'aggr32-normal.tiktokv.com'}
        prepared = prepare_mobile_registration(record, encoding='json-gzip', host='aggr32-normal.tiktokv.com', timestamp_ms=1700000000000)
        wire = base64.b64decode(prepared['body_base64'])
        self.assertEqual(prepared['headers']['x-ss-stub'], hashlib.md5(gzip.decompress(wire)).hexdigest())
        self.assertNotEqual(prepared['headers']['x-ss-stub'], hashlib.md5(wire).hexdigest())
        self.assertEqual(prepared['headers']['x-bd-content-encoding'], 'gzip')
        self.assertNotIn('tt_data=', prepared['url'])
        client = Mock()
        client.post.return_value.json.return_value = {'device_id': '333', 'install_id': '444'}
        registered = register_mobile_device(record, session=client, prepare=lambda *a, **kw: prepared)
        self.assertEqual((registered['device_id'], registered['install_id']), ('333', '444'))
        self.assertEqual(client.post.call_args.kwargs['data'], wire)
        record['registration_options'] = {'encoding': 'json', 'host': 'api-boot.tiktokv.com'}
        prepared = prepare_mobile_registration(record, encoding='json', host='api-boot.tiktokv.com', timestamp_ms=1700000000000)
        raw = base64.b64decode(prepared['body_base64'])
        self.assertEqual(json.loads(raw)['magic_tag'], 'ss_app_log')
        self.assertEqual(prepared['headers']['x-ss-stub'], hashlib.md5(raw).hexdigest())
        self.assertNotIn('x-bd-content-encoding', prepared['headers'])
        registered = register_mobile_device(record, session=client, prepare=lambda *a, **kw: prepared)
        self.assertEqual(registered['device_id'], '333')
        self.assertEqual(client.post.call_args.kwargs['data'], raw)

    def test_public_registration_codec_matches_native_reference_vector(self):
        import hashlib
        from Libs.mobile_log_encrypt_codec import tt_encrypt, tt_decrypt
        raw = b'a' * 16
        encoded = tt_encrypt(raw, seed=bytes([12345678 & 255]) * 32)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         '4cd42c6b1db433a09d3fbe9736acf8525c5859cf3c8210290990079fd18b0a5e')
        self.assertEqual(tt_decrypt(encoded), raw)

    def test_mobile_registration_matches_pc_interface_and_preserves_identity(self):
        import copy
        import gzip
        from Libs.mobile_log_encrypt_codec import tt_decrypt
        from unittest.mock import Mock
        from Libs.device_gen import register_mobile_device_identifiers
        profile = {'fingerprint': {'model': 'fixture-model', 'brand': 'fixture-brand', 'os_version': '14', 'os_api': '34'},
                   'identifiers': {'android_id': 'abcdef0123456789'}}
        original = copy.deepcopy(profile)
        client = Mock()
        client.post.return_value.json.return_value = {'device_id_str': '9876543210987654321',
            'install_id_str': '8765432109876543210', 'device_token': 'fixture-token', 'ssid': 'fixture-ssid'}
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api', 'TIKTOK_MOBILE_API_ENABLED': '0'}), \
             patch.object(backend.sys, 'frozen', True, create=True):
            ids = register_mobile_device_identifiers(client, 7, device_profile=profile)
            self.assertEqual(ids, ('9876543210987654321', '8765432109876543210'))
            result = register_mobile_device_identifiers(client, device_profile=profile, return_profile=True)
        self.assertEqual(profile, original)
        self.assertEqual(result['identifiers']['android_id'], profile['identifiers']['android_id'])
        self.assertEqual(result['identifiers']['openudid'], profile['identifiers']['android_id'])
        self.assertTrue(result['identifiers']['clientudid'])
        self.assertTrue(result['identifiers']['cdid'])
        self.assertEqual(result['registration']['device_token'], 'fixture-token')
        self.assertGreater(result['apk_first_install_time'], 0)
        sent = json.loads(gzip.decompress(tt_decrypt(client.post.call_args.kwargs['data'])))
        self.assertEqual(client.post.call_args.kwargs['headers']['content-type'], 'application/json; charset=utf-8')
        self.assertNotIn('tt_data=', client.post.call_args.args[0])
        self.assertEqual(sent['header']['clientudid'], result['identifiers']['clientudid'])
        self.assertFalse(client.post.call_args.kwargs['allow_redirects'])
        client.close.assert_not_called()

    def test_mobile_registration_closes_owned_session_on_success_and_failure(self):
        from unittest.mock import Mock
        from Libs.mobile_device_gen import generate_mobile_device, register_mobile_device
        record = generate_mobile_device(fingerprint={'model': 'fixture-model', 'brand': 'fixture-brand', 'os_version': '14', 'os_api': '34'})
        for outcome in ('success', 'http_error', 'invalid_ids'):
            with self.subTest(outcome=outcome):
                client = Mock()
                client.post.return_value.json.return_value = {'device_id_str': '333', 'install_id_str': '444'}
                if outcome == 'http_error':
                    client.post.return_value.raise_for_status.side_effect = requests.HTTPError('fixture failure')
                elif outcome == 'invalid_ids':
                    client.post.return_value.json.return_value = {'device_id': 0, 'install_id': 0}
                with patch('Libs.mobile_device_gen._new_http_session', return_value=client):
                    if outcome == 'success':
                        self.assertEqual(register_mobile_device(record)['device_id'], '333')
                    else:
                        with self.assertRaises((requests.HTTPError, ValueError)):
                            register_mobile_device(record)
                client.close.assert_called_once()

    def test_mobile_registration_rejects_invalid_profile_before_network(self):
        from Libs.device_gen import register_mobile_device_identifiers
        with patch('Libs.mobile_device_gen._new_http_session') as session:
            for profile in ([], {'identifiers': []}, {'fingerprint': []}, {'fingerprint': {'os_api': 'bad'}}):
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    register_mobile_device_identifiers(device_profile=profile)
            session.assert_not_called()

    def test_mobile_signing_uses_existing_routes_without_internal_health_requests(self):
        from Libs import XFrameSign as frames
        headers = {'x-khronos': '1700000000', 'x-argus': 'a', 'x-ladon': 'l', 'x-gorgon': 'g'}
        frame = {'signversion': '2.0', 'signinfo': 'i', 'signvalue': 'v', 'lid': '123'}
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api'}), \
             patch('Libs.signers._should_use_api', return_value=True), \
             patch('Libs.signers.requests.get', side_effect=AssertionError('Internal endpoint requested')) as get, \
             patch.object(hosted_headers, '_post_signatures', return_value=headers) as sign, \
             patch.object(frames, '_post_json', return_value=frame) as frame_sign:
            os.environ.pop('TIKTOK_MOBILE_API_ENABLED', None)
            backend.validate_mobile({'device_id': '333', 'install_id': '444'})
            backend.validate_mobile({'device_id': '333', 'install_id': '444'})
            sign.assert_not_called()
            frame_sign.assert_not_called()
            self.assertEqual(backend.signature_headers(1700000000, '1233', implementation='mobile',
                                                      url='https://fixture.test/'), headers)
            self.assertEqual(backend.frame_sign({'aid': '1233'}, implementation='mobile',
                                               device_profile={'frame_sdk': {}})['signversion'], '2.0')
            self.assertEqual(sign.call_count, 1)
            frame_sign.assert_called_once()
            self.assertEqual(frame_sign.call_args.args[0], '/framesign')
            get.assert_not_called()

    def test_mobile_preflight_requires_credentials_even_with_legacy_enable_flag(self):
        from Libs.error_reporting import HostedSignerError, SignerFailureKind
        with patch.dict(os.environ, {'TIKTOK_SIGNER_MODE': 'api'}), \
             patch.object(hosted_headers, '_should_use_api', return_value=False), \
             patch.object(hosted_headers.requests, 'get') as get:
            for flag in (None, '1'):
                with self.subTest(flag=flag):
                    if flag is None:
                        os.environ.pop('TIKTOK_MOBILE_API_ENABLED', None)
                    else:
                        os.environ['TIKTOK_MOBILE_API_ENABLED'] = flag
                    with self.assertRaises(HostedSignerError) as error:
                        backend.validate_mobile({'device_id': '333', 'install_id': '444'})
                    self.assertEqual(error.exception.kind, SignerFailureKind.SUBSCRIPTION)
            get.assert_not_called()

    def test_gui_registration_saves_mobile_identity_separately(self):
        from Libs.mobile_device_gen import generate_mobile_device
        record = generate_mobile_device()
        record.update(device_id='333', install_id='444', registration={'device_token': 'fixture-token'})
        w = self.window()
        w.on_device_registered('mobile', record)
        data = json.loads(Path(self.path).read_text())
        self.assertEqual(data['devices']['pc']['device_id'], '111')
        self.assertEqual(data['devices']['mobile']['device_id'], '333')
        self.assertEqual(data['devices']['mobile']['identifiers'], record['identifiers'])
        self.assertEqual(data['devices']['mobile']['registration']['device_token'], 'fixture-token')



if __name__ == '__main__':
    unittest.main()
