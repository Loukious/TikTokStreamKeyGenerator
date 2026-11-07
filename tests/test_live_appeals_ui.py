"""Appeal UI: explicit submission, worker delivery, stale context and Safety selection."""
import copy
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Libs.live_appeals_ui import ViolationAppealDialog
from tests.test_live_appeals import AppealStream, violation
from tests import test_client_modes as base


class AppealUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stream = AppealStream()
        self.current = True
        self.threads = []
        def factory():
            self.threads.append(threading.get_ident())
            return self.stream
        self.dialog = ViolationAppealDialog(factory, copy.deepcopy(self.stream.record),
            is_current=lambda: self.current, auto_refresh=False)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.wait_idle()
        self.dialog.reject()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def wait_idle(self):
        deadline = time.monotonic() + 3
        while self.dialog.busy and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.dialog.busy)

    def load(self):
        self.dialog.refresh()
        self.wait_idle()
        self.assertEqual(self.dialog.user_id, '123', self.dialog.status.text())

    def test_loading_selecting_typing_and_refresh_never_submit(self):
        self.load()
        self.dialog.reason.setCurrentIndex(5)
        self.dialog.explanation.setPlainText('Please review this restriction.')
        self.dialog.refresh()
        self.wait_idle()
        self.assertTrue(self.dialog.submit_button.isEnabled())
        self.assertEqual(self.stream.submissions(), [])
        self.assertNotIn(threading.get_ident(), self.threads)

    def test_submit_is_explicit_and_success_cannot_be_repeated(self):
        self.load()
        self.assertFalse(self.dialog.submit_button.isEnabled())
        self.dialog.reason.setCurrentIndex(2)
        self.dialog.submit_button.click()
        self.wait_idle()
        self.assertEqual(len(self.stream.submissions()), 1)
        self.assertIn('Appeal submitted', self.dialog.status.text())
        self.assertFalse(self.dialog.submit_button.isEnabled())
        self.dialog.refresh()
        self.wait_idle()
        self.dialog.submit()
        self.assertEqual(len(self.stream.submissions()), 1)

    def test_other_requires_text_with_utf16_limit(self):
        self.load()
        self.dialog.reason.setCurrentIndex(5)
        self.assertFalse(self.dialog.submit_button.isEnabled())
        self.dialog.explanation.setPlainText('😀' * 71)
        self.assertFalse(self.dialog.submit_button.isEnabled())
        self.dialog.explanation.setPlainText('😀' * 70)
        self.assertTrue(self.dialog.submit_button.isEnabled())
        self.assertEqual(self.dialog.character_count.text(), '140 / 140 characters')

    def test_expired_session_prevents_writes_even_if_context_changes_back(self):
        self.load()
        self.dialog.reason.setCurrentIndex(1)
        self.current = False
        self.dialog.update_controls()
        self.current = True
        self.dialog.update_controls()
        self.dialog.submit()
        self.assertFalse(self.dialog.submit_button.isEnabled())
        self.assertEqual(self.stream.submissions(), [])

    def test_account_changed_in_same_cookie_path_rejected(self):
        self.load()
        self.dialog.reason.setCurrentIndex(1)
        self.stream.account['user_id_str'] = '999'
        self.dialog.submit_button.click()
        self.wait_idle()
        self.assertIn('account changed', self.dialog.status.text())
        self.assertEqual(self.stream.submissions(), [])

    def test_failed_submission_requires_refresh_and_does_not_auto_retry(self):
        self.load()
        self.stream.failures['webcast/perception/appeal/'] = ConnectionError('timeout')
        self.dialog.reason.setCurrentIndex(1)
        self.dialog.submit_button.click()
        self.wait_idle()
        self.assertFalse(self.dialog.submit_button.isEnabled())
        self.assertTrue(self.dialog.needs_refresh)
        self.dialog.submit()
        self.assertEqual(len(self.stream.submissions()), 1)

    def test_busy_prevents_duplicate_submission_and_close(self):
        self.load()
        self.dialog.reason.setCurrentIndex(1)
        started, release = threading.Event(), threading.Event()
        original = self.stream._signed_post_json
        def post(*args, **kwargs):
            started.set()
            release.wait(2)
            return original(*args, **kwargs)
        with patch.object(self.stream, '_signed_post_json', side_effect=post):
            try:
                self.dialog.submit_button.click()
                self.assertTrue(started.wait(1))
                self.dialog.submit()
                self.dialog.reject()
                self.assertFalse(self.dialog.closed)
            finally:
                release.set()
                self.wait_idle()
        self.assertEqual(len(self.stream.submissions()), 1)

    def test_copyright_uses_explicit_official_page_action(self):
        self.stream.responses['webcast/perception/violation/info/']['detail']['punish_type_id'] = 99
        with patch('Libs.live_appeals_ui.QDesktopServices.openUrl', return_value=True) as open_url:
            self.load()
            open_url.assert_not_called()
            self.assertFalse(self.dialog.submit_button.isEnabled())
            self.dialog.official_button.click()
            self.wait_idle()
            open_url.assert_called_once()
            self.assertEqual(open_url.call_args.args[0].toString(), 'https://livecenter.tiktok.com/punish_detail?record_id=200')
            self.assertIn('same account', self.dialog.status.text())
        self.assertEqual(self.stream.submissions(), [])

    def test_snapshot_shows_confirmation_without_unsupported_reason_fields(self):
        self.stream.record['punish_info']['detail_url'] = 'https://livecenter.tiktok.com/treco/ban_detail?snapshot_id=300&feature_type=ranking'
        self.load()
        self.assertTrue(self.dialog.reason.isHidden())
        self.assertTrue(self.dialog.submit_button.isEnabled())
        self.assertEqual(self.stream.submissions(), [])
        self.dialog.submit_button.click()
        self.wait_idle()
        self.assertEqual(self.stream.submissions()[0][2]['payload'], {'snapshot_id': '300'})


class SafetyAppealIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(base.ModeTests.setUpClass.__func__)
    setUp = base.ModeTests.setUp
    window = base.ModeTests.window

    def test_safety_selection_preserved_and_never_opens_or_submits_on_refresh(self):
        window = self.window()
        with patch.object(window, 'get_cookie_file_status', return_value=(True, 'Fixture')), \
             patch.object(base.gui, 'ViolationAppealDialog') as dialog:
            records = [violation(), violation(2)]
            records[1]['violation_id_str'] = '101'
            records[1]['punish_info']['punish_record_id_str'] = '201'
            window._populate_violation_table({'history_violation_records': records})
            window.violation_details_output.selectRow(1)
            self.assertTrue(window.appeal_violation_button.isEnabled())
            window._populate_violation_table({'history_violation_records': list(reversed(records))})
            self.assertEqual(window.selected_violation()['violation_id_str'], '101')
            dialog.assert_not_called()
            window.appeal_violation_button.click()
            self.assertEqual(dialog.call_args.args[1]['violation_id_str'], '101')
            self.assertIs(dialog.call_args.kwargs['submitted'], window._submitted_appeals)

    def test_empty_safety_row_cannot_be_appealed(self):
        window = self.window()
        window._populate_violation_table({})
        window.violation_details_output.selectRow(0)
        self.assertIsNone(window.selected_violation())
        self.assertFalse(window.appeal_violation_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
