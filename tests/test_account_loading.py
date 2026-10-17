"""Account loading indicators across queued, active and completed refreshes."""
import unittest
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent
import tests.test_client_modes as modes
import TiktokStreamKeyGenerator as gui


class AccountLoadingTests(unittest.TestCase):
    setUpClass = classmethod(modes.ModeTests.setUpClass.__func__)
    setUp = modes.ModeTests.setUp

    def window(self, startup_cookies=False):
        with patch.object(gui.StreamKeyGeneratorWindow, 'ensure_device_identifiers', return_value=True), \
                patch.object(gui.StreamKeyGeneratorWindow, 'get_cookie_file_status',
                             return_value=(startup_cookies, 'Fixture')):
            window = gui.StreamKeyGeneratorWindow()
        self.addCleanup(self.dispose, window)
        return window

    @staticmethod
    def dispose(window):
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def start_refresh(self, window):
        with patch.object(window, 'get_cookie_file_status', return_value=(True, 'Fixture')), \
                patch.object(window, 'ensure_device_identifiers', return_value=True), \
                patch.object(gui.threading, 'Thread') as thread:
            window.refresh_account_info(show_errors=False)
            thread.return_value.start.assert_called_once()

    def test_initial_load_shows_loading_before_and_during_request_then_account(self):
        w = self.window(startup_cookies=True)
        self.assertEqual(w.account_summary.text(), 'Loading account…')
        self.assertEqual(w.account_username.placeholderText(), 'Loading…')
        self.start_refresh(w)
        self.assertEqual(w.account_summary.text(), 'Loading account…')
        self.assertEqual(w.account_status.placeholderText(), 'Loading…')
        self.assertFalse(w.refresh_account_button.isEnabled())
        w.apply_account_info({'account': {'username': 'fixture', 'user_id_str': '99'},
                              'status': 'Ready', 'can_go_live': True})
        self.assertEqual(w.account_summary.text(), '@fixture')
        self.assertEqual(w.account_status.text(), 'Ready')
        self.assertEqual(w.account_username.placeholderText(), '')

    def test_failed_silent_load_leaves_a_clear_failure_state_and_retry_can_load(self):
        w = self.window()
        self.start_refresh(w)
        w.handle_account_info_error('')
        self.assertEqual(w.account_summary.text(), 'Account load failed')
        self.assertEqual(w.account_status.placeholderText(), '')
        self.assertEqual(w.refresh_account_button.text(), 'Refresh Account Info')
        self.start_refresh(w)
        self.assertEqual(w.account_summary.text(), 'Loading account…')

    def test_refreshing_an_existing_account_preserves_its_name_and_signals_refresh(self):
        w = self.window()
        w.account_username.setText('fixture')
        self.start_refresh(w)
        self.assertEqual(w.account_summary.accessibleName(), '@fixture · Refreshing…')
        self.assertEqual(w.account_username.text(), 'fixture')
        w.handle_account_info_error('')
        self.assertEqual(w.account_summary.accessibleName(), '@fixture · Refresh failed')

    def test_cancelled_queued_refresh_does_not_leave_loading_without_cookies(self):
        w = self.window()
        w.schedule_account_refresh(900)
        self.assertEqual(w.account_summary.text(), 'Loading account…')
        with patch.object(w, 'get_cookie_file_status', return_value=(False, 'No cookies')):
            w.refresh_account_info(show_errors=False)
        self.assertEqual(w.account_summary.text(), 'No account loaded')
        self.assertEqual(w.account_username.placeholderText(), '')

    def test_android_pc_android_can_switch_during_each_load_and_ignore_both_old_results(self):
        w = self.window()
        w.devices['mobile'].update(device_id='333', install_id='444')
        workers, sent_profiles = [], []

        def thread_factory(*, target, daemon):
            return Mock(start=lambda: workers.append(target))

        def stream_factory(**options):
            sent_profiles.append(options)
            stream = MagicMock()
            stream.__enter__.return_value = stream
            if options['device_type'] == 'pc':
                stream.getAccountInfo.side_effect = RuntimeError('Old PC load failed')
            else:
                username = 'old_android' if len(sent_profiles) == 1 else 'latest_android'
                stream.getAccountInfo.return_value = {
                    'account': {'username': username, 'user_id_str': '99'}, 'can_go_live': True,
                    'allow_multi_stream_scene1': True, 'dual_layout_unlocked': True,
                }
            return stream

        with patch.object(w, 'get_cookie_file_status', return_value=(True, 'Fixture')), \
                patch.object(w, 'ensure_device_identifiers', return_value=True), \
                patch.object(gui.threading, 'Thread', side_effect=thread_factory), \
                patch.object(gui, 'Stream', side_effect=stream_factory), \
                patch.object(w, 'show_error') as show_error:
            for index in (1, 0, 1):
                w.device_type_combo.setCurrentIndex(index)
                self.app.processEvents()
                self.assertTrue(w.device_type_combo.isEnabled())
                self.assertTrue(w.account_info_in_flight)
                self.assertFalse(w.device_settings_button.isEnabled())
            self.assertEqual(len(workers), 3)
            workers[0]()  # Outdated Android success must not complete the latest Android load.
            self.assertEqual(w.account_username.text(), '')
            self.assertTrue(w.account_info_in_flight)
            workers[1]()  # Outdated PC failure must not unlock/mark the latest load failed.
            self.assertTrue(w.account_info_in_flight)
            self.assertFalse(w.account_load_failed)
            self.assertEqual(w.account_summary.text(), 'Loading account…')
            workers[2]()
            self.assertFalse(w.account_info_in_flight)
            self.assertEqual(w.account_username.text(), 'latest_android')
            self.assertTrue(w.device_type_combo.isEnabled())
            self.assertTrue(w.device_settings_button.isEnabled())
            self.assertFalse(w.account_refresh_timeout.isActive())
            show_error.assert_not_called()
        self.assertEqual([p['device_type'] for p in sent_profiles], ['mobile', 'pc', 'mobile'])
        self.assertEqual([p['device_profile']['device_id'] for p in sent_profiles], ['333', '111', '333'])

    def test_timeout_restores_controls_and_discards_the_late_result(self):
        w = self.window()
        self.start_refresh(w)
        token = w._account_request_id
        with patch.object(w, 'get_cookie_file_status', return_value=(True, 'Fixture')):
            w.on_account_refresh_timeout()
        self.assertFalse(w.account_info_in_flight)
        self.assertTrue(w.device_type_combo.isEnabled())
        self.assertTrue(w.refresh_account_button.isEnabled())
        self.assertEqual(w.account_summary.text(), 'Account load failed')
        w.account_info_loaded.emit((token, {'account': {'username': 'too_late'}}))
        self.assertEqual(w.account_username.text(), '')
        self.assertEqual(w.account_summary.text(), 'Account load failed')

    def test_cookie_change_invalidates_a_load_even_without_changing_client(self):
        w = self.window()
        self.start_refresh(w)
        token = w._account_request_id
        w.set_cookies_path(self.cookies + '.other', save=False, refresh=False)
        w.account_info_loaded.emit((token, {'account': {'username': 'old_cookie_account'}}))
        self.assertFalse(w.account_info_in_flight)
        self.assertEqual(w.account_username.text(), '')
        self.assertFalse(w.account_refresh_timeout.isActive())

    def test_failed_thread_start_also_releases_loading_state(self):
        w = self.window()
        with patch.object(w, 'get_cookie_file_status', return_value=(True, 'Fixture')), \
                patch.object(w, 'ensure_device_identifiers', return_value=True), \
                patch.object(gui.threading, 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('Cannot start thread')
            w.refresh_account_info(show_errors=False)
        self.assertFalse(w.account_info_in_flight)
        self.assertTrue(w.device_type_combo.isEnabled())
        self.assertFalse(w.account_refresh_timeout.isActive())
        self.assertEqual(w.account_summary.text(), 'Account load failed')

    def test_malformed_response_releases_loading_state(self):
        w = self.window()
        self.start_refresh(w)
        w.account_info_loaded.emit((w._account_request_id, {'account': []}))
        self.assertFalse(w.account_info_in_flight)
        self.assertTrue(w.device_type_combo.isEnabled())
        self.assertFalse(w.account_refresh_timeout.isActive())
        self.assertEqual(w.account_summary.text(), 'Account load failed')

    def test_account_http_calls_obey_the_remaining_request_budget(self):
        with gui.Stream(cookies_path=self.cookies, device_type='pc', device_profile={}) as stream, \
                patch.object(stream.s, 'request', return_value=Mock(status_code=200, headers={},
                    json=lambda: {'status_code': 0})) as send, \
                patch.object(stream, 'save_cookies'), patch.object(gui, '_audit_webcast_request'), \
                patch.object(gui.time, 'monotonic', return_value=50):
            stream.account_info_deadline = 55
            stream._request_json('GET', 'https://example.invalid/')
            self.assertEqual(send.call_args.kwargs['timeout'], 5)
            stream._request_json('GET', 'https://example.invalid/', timeout=2)
            self.assertEqual(send.call_args.kwargs['timeout'], 2)
            send.reset_mock()
            stream.account_info_deadline = 49
            with self.assertRaisesRegex(TimeoutError, 'Account refresh timed out'):
                stream._request_json('GET', 'https://example.invalid/')
            send.assert_not_called()

    def test_superseded_request_stops_before_network_or_cookie_save(self):
        with gui.Stream(cookies_path=self.cookies, device_type='pc', device_profile={}) as stream, \
                patch.object(stream.s, 'request') as send, patch.object(stream, 'save_cookies') as save:
            cancel = stream.account_info_cancel = threading.Event()
            cancel.set()
            with self.assertRaisesRegex(TimeoutError, 'superseded'):
                stream._request_json('GET', 'https://example.invalid/')
            send.assert_not_called()
            save.assert_not_called()
            cancel.clear()
            def finish_after_switch(**options):
                cancel.set()
                return Mock(status_code=200, headers={}, json=lambda: {'status_code': 0})
            send.side_effect = finish_after_switch
            with self.assertRaisesRegex(TimeoutError, 'superseded'):
                stream._request_json('GET', 'https://example.invalid/')
            save.assert_not_called()

    def test_cookie_save_replaces_complete_json_and_preserves_it_on_write_failure(self):
        with gui.Stream(cookies_path=self.cookies, device_type='pc', device_profile={}) as stream:
            stream.s.cookies.update({'sessionid': 'fixture-only'})
            stream.save_cookies()
            original = Path(self.cookies).read_bytes()
            self.assertEqual(json.loads(original)[0]['value'], 'fixture-only')
            stream.s.cookies.update({'sessionid': 'new-fixture'})
            with patch.object(gui.os, 'replace', side_effect=OSError('Fixture failure')):
                with self.assertRaises(OSError):
                    stream.save_cookies()
            self.assertEqual(Path(self.cookies).read_bytes(), original)
            self.assertEqual(list(Path(self.cookies).parent.glob('.cookies-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
