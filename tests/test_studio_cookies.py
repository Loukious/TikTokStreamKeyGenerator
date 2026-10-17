"""Offline Studio account discovery, export isolation and Windows GUI integration."""
from tests.gui_helpers import drive_workflow
from tests.gui_helpers import wait_until
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_client_modes as base
from Libs import studio_cookies as studio
from Libs.studio_import_ui import StudioImportDialog

gui = base.gui


def fixture_accounts():
    return {'AccountService': {'state': {'accountList': [
        {'userId': '99', 'displayId': 'loukioustn', 'nickname': 'Test primary',
         'sessionId': 'a' * 32, 'domain': 'api16-normal-c-alisg.tiktokv.com'},
        {'userId': '100', 'displayId': 'second_account', 'nickname': 'Test secondary',
         'sessionId': 'b' * 32, 'domain': 'https://api16-normal-useast5.tiktokv.us'},
    ]}}, 'UserService': {'state': {'userInfo': {'user_id_str': '99'}}}}


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = gui.QApplication.instance() or gui.QApplication([])

    def setUp(self):
        base.ModeTests.setUp(self)
        self.root = Path(self.temp.name) / 'studio'
        self.store = self.root / 'TTStore'
        self.store.mkdir(parents=True)
        self.source = self.store / 'services.json'
        self.source.write_text(json.dumps(fixture_accounts()))
        platform = patch.object(studio.sys, 'platform', 'win32')
        platform.start()
        self.addCleanup(platform.stop)

    def accounts(self):
        return studio.read_studio_accounts(self.root)

    def test_two_accounts_have_separate_sessions_and_current_marker(self):
        first, second = self.accounts()
        self.assertEqual(first.filename, 'cookies_loukioustn.json')
        self.assertEqual(second.filename, 'cookies_second_account.json')
        self.assertTrue(first.current)
        self.assertFalse(second.current)
        self.assertEqual(first.cookie_domain, '.tiktokv.com')
        self.assertEqual(second.cookie_domain, '.tiktokv.us')
        self.assertNotIn('a' * 32, repr(first))

    def test_default_path_uses_roaming_profile_not_installation(self):
        root = Path(self.temp.name) / 'TikTok LIVE Studio' / 'TTStore'
        root.mkdir(parents=True)
        (root / 'services.json').write_text(json.dumps(fixture_accounts()))
        with patch.dict(os.environ, {'APPDATA': self.temp.name}):
            self.assertEqual(len(studio.read_studio_accounts()), 2)

    def test_export_secondary_never_mixes_primary_session_or_login_cache(self):
        before = self.source.read_bytes()
        login = self.store / 'login.json'
        login.write_text(json.dumps({'cookies': [{'name': 'sid_guard', 'value': 'PRIMARY_SECRET', 'encKey': 'key'}]}))
        selected = self.accounts()[1]
        path = studio.export_studio_account(selected, self.temp.name)
        self.assertEqual(Path(path).parent, Path(self.temp.name))
        self.assertEqual(Path(path).name, 'cookies_second_account.json')
        records = json.loads(Path(path).read_text())
        self.assertEqual({c['value'] for c in records}, {'b' * 32})
        self.assertEqual({c['name'] for c in records}, {'sessionid', 'sessionid_ss', 'sid_tt'})
        self.assertTrue(all(c['domain'] == '.tiktokv.us' and c['secure'] and c['httpOnly'] for c in records))
        self.assertNotIn('encKey', records[0])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertIn('PRIMARY_SECRET', login.read_text())
        window = base.ModeTests.window(self)
        self.assertEqual(len(window.load_cookie_entries_from_file(path)), 3)

    def test_overwrite_is_atomic_and_failure_preserves_previous_file(self):
        account = self.accounts()[0]
        path = Path(studio.export_studio_account(account, self.temp.name))
        old = path.read_bytes()
        with patch.object(studio.os, 'replace', side_effect=OSError('Read only')):
            with self.assertRaisesRegex(studio.StudioCookieError, 'writable folder'):
                studio.export_studio_account(account, self.temp.name)
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(list(path.parent.glob('.studio-cookie-*.tmp')), [])

    def test_windows_only(self):
        with patch.object(studio.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(studio.StudioCookieError, 'only on Windows'):
                self.accounts()
            with self.assertRaises(studio.StudioCookieError):
                studio.export_studio_account(studio.StudioAccount('99', 'test', '', 'a' * 32), self.temp.name)

    def test_filename_sanitization_cannot_escape_output_directory(self):
        account = studio.StudioAccount('99', '../../outside\\file', '', 'a' * 32)
        path = Path(studio.export_studio_account(account, self.temp.name))
        self.assertEqual(path.parent.resolve(), Path(self.temp.name).resolve())
        self.assertNotIn('/', path.name)
        self.assertNotIn('\\', path.name)
        self.assertTrue(path.name.endswith('_99.json'))

    def test_colliding_handles_get_distinct_account_id_filenames(self):
        data = fixture_accounts()
        data['AccountService']['state']['accountList'][1]['displayId'] = 'LOUKIOUSTN'
        self.source.write_text(json.dumps(data))
        first, second = self.accounts()
        self.assertNotEqual(first.filename.casefold(), second.filename.casefold())
        self.assertTrue(first.filename.endswith('_99.json'))
        self.assertTrue(second.filename.endswith('_100.json'))

    def test_unrelated_domains_invalid_sessions_and_duplicate_users_are_excluded(self):
        data = fixture_accounts()
        entries = data['AccountService']['state']['accountList']
        entries.extend([{**entries[0]}, {**entries[0], 'userId': '200', 'domain': 'https://tiktokv.com.attacker.example'},
                        {**entries[0], 'userId': '201', 'sessionId': 'not-a-session'}, None])
        self.source.write_text(json.dumps(data))
        self.assertEqual([a.user_id for a in self.accounts()], ['99', '100'])

    def test_missing_corrupt_and_unsupported_storage_give_readable_errors(self):
        self.source.unlink()
        with self.assertRaisesRegex(studio.StudioCookieError, 'Sign in'):
            self.accounts()
        for value in ('{broken', '[]', '{}', '{"AccountService":{"state":{"accountList":{}}}}'):
            self.source.write_text(value)
            with self.subTest(value=value), self.assertRaises(studio.StudioCookieError):
                self.accounts()

    def test_picker_selection_is_read_only_until_import(self):
        dialog = StudioImportDialog(self.accounts(), output_dir=self.temp.name)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.selected_account().user_id, '99')
        with patch('Libs.studio_import_ui.export_studio_account', return_value='fixture.json') as export:
            dialog.table.selectRow(1)
            export.assert_not_called()
            self.assertIn('cookies_second_account.json', dialog.destination.text())
            dialog.import_button.click()
            wait_until(lambda: not dialog.busy)
            export.assert_called_once_with(dialog.accounts[1], self.temp.name)
            self.assertEqual(dialog.result(), gui.QDialog.Accepted)
            self.assertEqual(dialog.saved_path, 'fixture.json')

    def test_picker_save_error_keeps_dialog_open_and_does_not_select_file(self):
        dialog = StudioImportDialog(self.accounts(), output_dir=self.temp.name)
        self.addCleanup(dialog.close)
        with patch('Libs.studio_import_ui.export_studio_account', side_effect=studio.StudioCookieError('Writable folder required')):
            dialog.import_button.click()
            wait_until(lambda: not dialog.busy)
        self.assertEqual(dialog.saved_path, '')
        self.assertEqual(dialog.result(), 0)
        self.assertIn('Writable', dialog.error_label.text())

    def test_main_window_windows_action_and_import_load_selected_file(self):
        window = base.ModeTests.window(self)
        window.update_stream_controls(has_cookies=False)
        self.assertTrue(window.studio_import_button.isEnabled())
        self.assertIn('Import from LIVE Studio…', [a.text() for a in window.account_menu.actions()])
        with patch('Libs.studio_cookies.read_studio_accounts', return_value=self.accounts()), \
             patch('Libs.studio_import_ui.StudioImportDialog') as dialog, \
             patch.object(gui, '_runtime_base_dir', return_value=self.temp.name), \
             patch.object(window, 'set_cookies_path') as load, patch.object(window, 'refresh_account_info') as refresh:
            dialog.return_value.exec.return_value = gui.QDialog.Accepted
            dialog.return_value.saved_path = str(Path(self.temp.name) / 'cookies_second_account.json')
            drive_workflow(gui.StreamKeyGeneratorWindow.import_studio_cookies.__wrapped__(window))
            self.assertEqual(dialog.call_args.kwargs['output_dir'], self.temp.name)
            load.assert_called_once_with(dialog.return_value.saved_path, save=True, refresh=True)
            refresh.assert_called_once_with(show_errors=True)

    def test_cancel_and_live_state_do_not_export_or_change_loaded_account(self):
        window = base.ModeTests.window(self)
        with patch('Libs.studio_cookies.read_studio_accounts', return_value=self.accounts()) as read, \
             patch('Libs.studio_import_ui.StudioImportDialog') as dialog, patch.object(window, 'set_cookies_path') as load:
            dialog.return_value.exec.return_value = gui.QDialog.Rejected
            drive_workflow(gui.StreamKeyGeneratorWindow.import_studio_cookies.__wrapped__(window))
            load.assert_not_called()
            read.reset_mock()
            window.is_live = True
            window.update_stream_controls()
            self.assertFalse(window.studio_import_button.isEnabled())
            drive_workflow(gui.StreamKeyGeneratorWindow.import_studio_cookies.__wrapped__(window))
            read.assert_not_called()

    def test_non_windows_does_not_add_the_menu_action(self):
        with patch.object(gui.sys, 'platform', 'linux'):
            window = base.ModeTests.window(self)
            self.assertIsNone(window.studio_import_button)
            self.assertNotIn('Import from LIVE Studio…', [a.text() for a in window.account_menu.actions()])


if __name__ == '__main__':
    unittest.main()
