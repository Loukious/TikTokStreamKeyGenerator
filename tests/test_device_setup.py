"""Automatic paired identity setup and basic Fluent device dialogs."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QStyleOptionViewItem, QTableWidgetItem

from tests import test_client_modes as base
from Libs.device_profiles import has_registered_ids, prepare_device_profiles
from Libs.mobile_device_gen import (ANDROID_HARDWARE_PROFILES, build_mobile_registration,
                                   generate_mobile_device, parse_mobile_registration, MobileRegistrationNotIssued)
from Libs.fluent_ui import LineEdit, PrimaryPushButton, PushButton, TableWidget, ComboBox, ToolButton, point_font

gui = base.gui


class DeviceSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = base.QApplication.instance() or base.QApplication([])

    def setUp(self):
        base.ModeTests.setUp(self)
        self.pending = []
        queue = self.pending
        class Thread:
            def __init__(self, target, daemon):
                queue.append(target)
            def start(self):
                pass
        p = patch.object(gui.threading, 'Thread', Thread)
        p.start()
        self.addCleanup(p.stop)

    def window(self):
        return base.ModeTests.window(self)

    def finish(self):
        self.pending.pop(0)()

    @staticmethod
    def registration(profile, did, iid):
        return {**copy.deepcopy(profile), 'device_id': did, 'install_id': iid}

    def test_random_android_identity_has_coherent_hardware_and_valid_registration(self):
        first, second = generate_mobile_device(), generate_mobile_device()
        self.assertNotEqual(first['identifiers'], second['identifiers'])
        expected = next(p for p in ANDROID_HARDWARE_PROFILES if p['model'] == first['fingerprint']['model'])
        for key, value in expected.items():
            self.assertEqual(first['fingerprint'][key], value)
        draft = build_mobile_registration(first, timestamp_ms=1700000000000)
        self.assertIn('/service/2/device_register/', draft['url'])
        self.assertEqual(first['device_id'], '')
        self.assertEqual(first['install_id'], '')

    def test_pixel_font_is_converted_without_changing_its_visual_size(self):
        original = QFont()
        original.setPixelSize(24)
        original.setBold(True)
        converted = point_font(original, dpi=144)
        self.assertEqual(original.pixelSize(), 24)
        self.assertEqual(converted.pointSizeF(), 12.0)
        self.assertTrue(converted.bold())
        self.assertEqual(point_font(converted, dpi=144), converted)

    def test_table_item_font_inherits_table_size_and_retains_bold(self):
        table = TableWidget(1, 1)
        self.addCleanup(table.close)
        table_font = QFont()
        table_font.setPixelSize(24)
        table.setFont(table_font)
        item = QTableWidgetItem('Active violation')
        bold = QFont()
        bold.setBold(True)
        item.setFont(bold)
        table.setItem(0, 0, item)
        option = QStyleOptionViewItem()
        table.itemDelegate().initStyleOption(option, table.model().index(0, 0))
        self.assertAlmostEqual(option.font.pointSizeF(), 24 * 72.0 / table.logicalDpiY())
        self.assertTrue(option.font.bold())

    def test_zero_registration_ids_show_details_and_preserve_pc(self):
        for response in ({'device_id': 0, 'install_id': 0},
                         {'data': {'device_id_str': ' 0 ', 'install_id_str': '123'}},
                         {'device_id': '123', 'install_id': '000'}):
            with self.assertRaises(MobileRegistrationNotIssued):
                parse_mobile_registration(response)
        w = self.window()
        before = copy.deepcopy(w.devices['pc'])
        def rejected(**kwargs):
            return parse_mobile_registration({'device_id': 0, 'install_id': 0})
        with patch.object(gui, 'register_mobile_device_identifiers', side_effect=rejected):
            w.ensure_device_identifiers()
            self.finish()
        self.assertEqual({key: w.devices['pc'][key] for key in before}, before)
        self.assertFalse(has_registered_ids(w.devices['mobile']))
        self.assertIn('TikTok did not issue Android IDs', w.device_setup_status.text())
        self.assertFalse(w.device_setup_details_button.isHidden())
        with patch.object(gui.QMessageBox, 'information') as popup:
            w.device_setup_details_button.click()
            self.assertIn('zero Android device/install IDs', popup.call_args.args[2])
        w.devices['mobile'].update(device_id='333', install_id='444')
        w.start_device_initialization()
        self.assertTrue(w.device_setup_details_button.isHidden())

    def test_prepare_preserves_saved_ids_hardware_and_advanced_options(self):
        original = prepare_device_profiles({'pc': {'device_id': '111', 'install_id': '222'},
                                           'mobile': {'device_id': '333', 'install_id': '444',
                                                      'broadcast_type': 'screen_record', 'orientation': '2',
                                                      'create_params': {'future_option': 'keep'}}})
        before = copy.deepcopy(original)
        completed = prepare_device_profiles(original)
        self.assertEqual(completed, original)
        self.assertEqual(original, before)
        self.assertTrue(has_registered_ids(completed['pc']))
        self.assertTrue(has_registered_ids(completed['mobile']))
        self.assertNotEqual(completed['pc']['identifiers'], completed['mobile']['identifiers'])

    def test_first_run_registers_both_profiles_and_persists_independent_records(self):
        w = self.window()
        w.devices, w.device_id, w.install_id = {'pc': {}, 'mobile': {}}, '', ''
        def mobile(*, device_profile, return_profile):
            build_mobile_registration(device_profile)  # hardware/UUIDs are ready without editing a form
            return self.registration(device_profile, '333', '444')
        with patch.object(gui, 'register_desktop_device_identifiers',
                          side_effect=lambda **kw: self.registration(kw['device_profile'], '111', '222')) as pc, \
             patch.object(gui, 'register_mobile_device_identifiers', side_effect=mobile) as android:
            self.assertFalse(w.ensure_device_identifiers())
            self.assertTrue(w.device_initialization_in_flight)
            self.assertFalse(w.login_button.isEnabled())
            self.assertEqual(len(self.pending), 1)
            local = json.loads(Path(self.path).read_text())['devices']
            self.assertTrue(local['pc']['identifiers']['pc_uuid'])
            self.assertTrue(local['mobile']['identifiers']['android_id'])
            self.finish()
            pc.assert_called_once()
            android.assert_called_once()
        self.assertFalse(w.device_initialization_in_flight)
        self.assertTrue(w.login_button.isEnabled())
        self.assertEqual((w.device_id, w.install_id), ('111', '222'))
        saved = json.loads(Path(self.path).read_text())
        self.assertEqual(saved['devices']['pc']['device_id'], '111')
        self.assertEqual(saved['devices']['mobile']['device_id'], '333')
        self.assertEqual(saved['custom_future_option'], 'preserve')
        w.device_type_combo.setCurrentIndex(1)
        self.assertEqual((w.device_id, w.install_id), ('333', '444'))

    def test_existing_pc_only_initializes_android_and_preserves_pc_ids(self):
        w = self.window()
        with patch.object(gui, 'register_desktop_device_identifiers') as pc, \
             patch.object(gui, 'register_mobile_device_identifiers',
                          side_effect=lambda **kw: self.registration(kw['device_profile'], '333', '444')) as android:
            self.assertTrue(w.ensure_device_identifiers())
            self.finish()
            pc.assert_not_called()
            android.assert_called_once()
        self.assertEqual((w.device_id, w.install_id), ('111', '222'))

    def test_registered_profiles_never_register_again(self):
        w = self.window()
        w.devices['mobile'] = {'device_id': '333', 'install_id': '444'}
        with patch.object(gui, 'register_desktop_device_identifiers') as pc, \
             patch.object(gui, 'register_mobile_device_identifiers') as android:
            self.assertTrue(w.ensure_device_identifiers())
            self.assertEqual(self.pending, [])
            pc.assert_not_called()
            android.assert_not_called()

    def test_failure_does_not_discard_success_and_retry_reuses_local_identity(self):
        w = self.window()
        w.devices, w.device_id, w.install_id = {'pc': {}, 'mobile': {}}, '', ''
        attempts = []
        def pc(**kwargs):
            attempts.append(copy.deepcopy(kwargs['device_profile']))
            if len(attempts) == 1:
                raise RuntimeError('Fixture registration failure')
            return self.registration(kwargs['device_profile'], '111', '222')
        with patch.object(gui, 'register_desktop_device_identifiers', side_effect=pc), \
             patch.object(gui, 'register_mobile_device_identifiers',
                          side_effect=lambda **kw: self.registration(kw['device_profile'], '333', '444')) as android:
            w.ensure_device_identifiers()
            self.finish()
            self.assertTrue(has_registered_ids(w.devices['mobile']))
            self.assertFalse(has_registered_ids(w.devices['pc']))
            self.assertFalse(w.retry_devices_button.isHidden())
            self.assertFalse(w.login_button.isEnabled())
            w.start_device_initialization()
            self.finish()
            self.assertEqual(attempts[0]['identifiers'], attempts[1]['identifiers'])
            self.assertEqual(attempts[0]['fingerprint'], attempts[1]['fingerprint'])
            android.assert_called_once()
            self.assertTrue(w.retry_devices_button.isHidden())

    def test_android_failure_keeps_pc_usable_and_ids_are_not_reclassified(self):
        w = self.window()
        with patch.object(gui, 'register_desktop_device_identifiers') as pc, \
             patch.object(gui, 'register_mobile_device_identifiers', side_effect=RuntimeError('Offline')):
            w.ensure_device_identifiers()
            self.finish()
            pc.assert_not_called()
        w.update_stream_controls(has_cookies=True)
        self.assertTrue(w.login_button.isEnabled())
        self.assertTrue(w.go_live_button.isEnabled())
        self.assertTrue(w.campaigns_button.isEnabled())
        w.device_type_combo.setCurrentIndex(1)
        self.assertEqual((w.device_id, w.install_id), ('', ''))
        self.assertFalse(w.go_live_button.isEnabled())
        self.assertEqual(w.devices['pc']['device_id'], '111')

    def test_initialization_is_one_worker_and_locks_profile_changes_until_complete(self):
        w = self.window()
        with patch.object(gui, 'register_mobile_device_identifiers',
                          side_effect=lambda **kw: self.registration(kw['device_profile'], '333', '444')):
            w.ensure_device_identifiers()
            w.ensure_device_identifiers()
            self.assertEqual(len(self.pending), 1)
            self.assertFalse(w.device_settings_button.isEnabled())
            w.device_type_combo.setCurrentIndex(1)
            self.assertEqual(w.device_type, 'pc')
            self.finish()
        self.assertTrue(w.device_settings_button.isEnabled())
        w.device_type_combo.setCurrentIndex(1)
        self.assertEqual(w.device_type, 'mobile')

    def test_both_dialogs_only_edit_two_ids_and_do_not_mutate_hidden_fields(self):
        for kind in ('pc', 'mobile'):
            record = {'device_id': '111', 'install_id': '222', 'identifiers': {'secret_fixture': 'keep'},
                      'fingerprint': {'model': 'Existing model'}, 'broadcast_type': 'screen_record',
                      'orientation': '2', 'registration_options': {'encoding': 'ttencrypt'}}
            dialog = gui.DeviceSettingsDialog(kind, record)
            self.addCleanup(dialog.close)
            self.assertEqual(set(dialog.fields), {'device_id', 'install_id'})
            self.assertEqual(len(dialog.findChildren(LineEdit)), 2)
            self.assertFalse(hasattr(dialog, 'mobile_broadcast_options'))
            dialog.fields['device_id'].setText('333')
            dialog.fields['install_id'].setText('444')
            dialog.save_record()
            self.assertEqual(dialog.result(), base.QDialog.Accepted)
            self.assertEqual(dialog.record, {**record, 'device_id': '333', 'install_id': '444'})
            self.assertEqual(record['device_id'], '111')

    def test_invalid_id_shows_inline_error_and_cannot_save(self):
        for value in ('0', 'abc', '１２３', '-1'):
            dialog = gui.DeviceSettingsDialog('pc', {'device_id': '111', 'install_id': '222'})
            self.addCleanup(dialog.close)
            dialog.fields['device_id'].setText(value)
            dialog.save_record()
            self.assertNotEqual(dialog.result(), base.QDialog.Accepted)
            self.assertTrue(dialog.error_label.text())
            self.assertEqual(dialog.record['device_id'], '111')

    def test_manually_saved_ids_restore_controls_and_clear_failed_setup(self):
        w = self.window()
        w.device_type_combo.setCurrentIndex(1)
        w.device_initialization_attempted = True
        w.on_device_initialization_finished({'mobile': 'Registration returned zero IDs'})
        w.update_stream_controls(has_cookies=True)
        self.assertFalse(w.go_live_button.isEnabled())
        record = {**w.devices['mobile'], 'device_id': '333', 'install_id': '444'}
        with patch.object(gui, 'DeviceSettingsDialog') as dialog, \
             patch.object(w, 'get_cookie_file_status', return_value=(True, 'Fixture cookies')):
            dialog.return_value.exec.return_value = base.QDialog.Accepted
            dialog.return_value.record = record
            w.edit_device_settings()
        self.assertTrue(w.go_live_button.isEnabled())
        self.assertTrue(w.campaigns_button.isEnabled())
        self.assertTrue(w.retry_devices_button.isHidden())
        self.assertFalse(w.device_initialization_errors)
        self.assertEqual(self.pending, [])

    def test_main_controls_use_fluent_widgets_with_qt_compatible_data(self):
        w = self.window()
        self.assertIsInstance(w.title_edit, LineEdit)
        self.assertIsInstance(w.device_settings_button, ToolButton)
        self.assertIsInstance(w.go_live_button, PrimaryPushButton)
        self.assertIsInstance(w.online_audience_table_output, TableWidget)
        self.assertIsInstance(w.device_type_combo, ComboBox)
        self.assertEqual(w.device_type_combo.itemData(0), 'pc')
        self.assertEqual(w.device_type_combo.itemData(1), 'mobile')
        w.region_combo.setCurrentText('tn')
        self.assertEqual(w.region_combo.currentText(), 'tn')

    def test_workspace_has_separate_views_and_no_scroll_area(self):
        w = self.window()
        self.assertEqual(w.workspace_stack.count(), 5)
        self.assertIs(w.workspace_stack.currentWidget(), w.live_page)
        self.assertFalse(w.findChildren(gui.ScrollArea))
        self.assertTrue(w.settings_dialog.isAncestorOf(w.cookies_path_edit))
        self.assertTrue(w.settings_dialog.isAncestorOf(w.replay_checkbox))
        self.assertTrue(w.live_page.isAncestorOf(w.title_edit))
        self.assertFalse(w.live_page.isAncestorOf(w.online_audience_table_output))

    def test_view_choices_persist_and_hiding_active_view_returns_to_live(self):
        w = self.window()
        w._config_extra['ui'] = {'future_preference': 'keep'}
        w.show_workspace_view('audience')
        self.assertIs(w.workspace_stack.currentWidget(), w.workspace_pages['audience'])
        w.set_workspace_view_visible('audience', False)
        self.assertIs(w.workspace_stack.currentWidget(), w.live_page)
        self.assertFalse(w.view_actions['audience'].isChecked())
        self.assertFalse(w.context_view_actions['audience'].isChecked())
        w.show_workspace_view('stats')
        saved = json.loads(Path(self.path).read_text())
        self.assertEqual(saved['ui']['active_view'], 'stats')
        self.assertEqual(saved['ui']['visible_views'], ['chat', 'stats', 'safety'])
        self.assertEqual(saved['ui']['future_preference'], 'keep')
        other = self.window()
        self.assertIs(other.workspace_stack.currentWidget(), other.workspace_pages['stats'])
        self.assertNotIn('audience', other.visible_workspace_views)
        other.restore_workspace_views()
        self.assertEqual(other.visible_workspace_views, {'chat', 'stats', 'audience', 'safety'})
        self.assertIs(other.workspace_stack.currentWidget(), other.live_page)

    def test_settings_keep_existing_profile_and_stream_choices(self):
        w = self.window()
        records = copy.deepcopy(w.devices)
        w.settings_dialog.show()
        w.replay_checkbox.setChecked(False)
        w.age_restricted_checkbox.setChecked(True)
        w.settings_dialog.accept()
        saved = json.loads(Path(self.path).read_text())
        self.assertFalse(saved['generate_replay'])
        self.assertTrue(saved['age_restricted'])
        self.assertEqual(saved['devices']['pc']['device_id'], records['pc']['device_id'])
        self.assertIn('Age restricted', w.stream_options_summary.text())

    def test_menu_actions_follow_device_locks_and_account_mode(self):
        w = self.window()
        device_action = next(a for a, button in w.workspace_action_controls.items()
                             if button is w.device_settings_button)
        login_action = next(a for a, button in w.workspace_action_controls.items()
                            if button is w.login_button)
        self.assertTrue(login_action.isEnabled())
        w.is_live = True
        w.update_stream_controls()
        self.assertFalse(device_action.isEnabled())
        w.is_live = False
        w.device_type_combo.setCurrentIndex(1)
        self.assertFalse(login_action.isEnabled())
        self.assertTrue(device_action.isEnabled())

    def test_context_copy_uses_only_the_displayed_local_connection(self):
        w = self.window()
        w.real_stream_url = 'rtmp://private.example/never-expose'
        w.url_output.setText('rtmp://127.0.0.1:1935/live')
        w.sync_workspace_actions()
        action = next(a for a, field in w.copy_workspace_actions.items() if field is w.url_output)
        action.trigger()
        self.assertEqual(gui.QGuiApplication.clipboard().text(), w.url_output.text())
        w.url_output.clear()
        w.sync_workspace_actions()
        self.assertFalse(action.isEnabled())

    def test_stream_controls_stay_visible_on_all_views_in_compact_window(self):
        w = self.window()
        w.resize(960, 640)
        w.show()
        self.app.processEvents()
        for key in w.workspace_pages:
            w.show_workspace_view(key)
            self.app.processEvents()
            for button in (w.go_live_button, w.pause_live_button, w.resume_live_button, w.end_live_button):
                self.assertTrue(button.isVisible())
                self.assertGreater(button.width(), 60)
                position = button.mapTo(w, QPoint(0, 0))
                self.assertLess(position.y() + button.height(), w.height())

    def test_gaming_and_dual_outputs_fit_at_large_font_without_clipping(self):
        font = self.app.font()
        larger = gui.QFont(font)
        larger.setPointSize(16)
        self.app.setFont(larger)
        try:
            w = self.window()
            w.resize(960, 640)
            w.show()
            w.topic_combo.setCurrentText('Gaming')
            w.dual_layout_checkbox.setChecked(True)
            self.app.processEvents()
            self.assertLessEqual(w.height(), 640)
            for field in (w.url_output, w.key_output, w.portrait_url_output, w.portrait_key_output):
                self.assertTrue(field.isVisible())
                self.assertLessEqual(field.y() + field.height(), field.parentWidget().height())
            w.device_type_combo.setCurrentIndex(1)
            w.mobile_broadcast_options.mode_combo.setCurrentIndex(1)
            self.app.processEvents()
            self.assertLessEqual(w.height(), 640)
            orientation = w.mobile_broadcast_options.orientation_combo
            self.assertLessEqual(orientation.y() + orientation.height(), orientation.parentWidget().height())
        finally:
            self.app.setFont(font)

    def test_keyboard_view_shortcuts_respect_hidden_views(self):
        w = self.window()
        w.show()
        w.activateWindow()
        self.app.processEvents()
        QTest.keyClick(w, gui.Qt.Key_2, gui.Qt.ControlModifier)
        self.app.processEvents()
        self.assertIs(w.workspace_stack.currentWidget(), w.workspace_pages['stats'])
        w.set_workspace_view_visible('audience', False)
        QTest.keyClick(w, gui.Qt.Key_3, gui.Qt.ControlModifier)
        self.app.processEvents()
        self.assertIs(w.workspace_stack.currentWidget(), w.workspace_pages['stats'])

    def test_closing_settings_saves_pending_cookie_text_and_clears_old_account(self):
        w = self.window()
        new_path = str(Path(self.temp.name) / 'other-cookies.json')
        Path(new_path).write_text('[]')
        w.account_username.setText('old_account')
        w.settings_dialog.show()
        w.cookies_path_edit.setText(new_path)
        w.settings_dialog.accept()
        saved = json.loads(Path(self.path).read_text())
        self.assertEqual(Path(saved['cookies_path']), Path(new_path))
        self.assertEqual(w.account_username.text(), '')
        self.assertEqual(w.account_summary.text(), 'No account loaded')


if __name__ == '__main__':
    unittest.main()
