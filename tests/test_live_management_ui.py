"""Offline GUI integration with real workers and a fake, account-bound transport."""
import contextlib
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from Libs.live_management_ui import LiveManagementDialog
from tests.test_live_management import FakeStream


class ManagementUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stream = FakeStream()
        self.current = True
        self.worker_threads = []
        @contextlib.contextmanager
        def factory():
            self.worker_threads.append(threading.get_ident())
            yield self.stream
        self.dialog = LiveManagementDialog(factory, room_id='456',
            viewers=[{'id': '888', 'name': '<Viewer>'}], is_current=lambda: self.current,
            auto_refresh=False)
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
        self.assertFalse(self.dialog.busy, 'Worker did not finish')

    def load(self, page='comments'):
        self.dialog.refresh()
        self.wait_idle()
        if page != 'comments':
            self.dialog.navigation.setCurrentItem(page)
            self.wait_idle()

    def test_initial_load_and_tab_selection_never_write(self):
        self.assertFalse(self.dialog.apply_comments_button.isEnabled())
        self.load()
        self.assertEqual(self.dialog.user_id, '123')
        for page in ('words', 'moderators', 'about', 'viewers', 'comments'):
            self.dialog.navigation.setCurrentItem(page)
            self.wait_idle()
        self.assertEqual(self.stream.writes(), [])
        self.assertTrue(self.worker_threads)
        self.assertNotIn(threading.get_ident(), self.worker_threads)

    def test_comments_apply_sends_only_explicit_changes(self):
        self.load()
        self.dialog.comment_controls['allow_comments'].setChecked(False)
        self.assertEqual(self.stream.writes(), [])
        self.dialog.apply_comments_button.click()
        self.wait_idle()
        self.assertEqual(len(self.stream.writes()), 1)
        self.assertEqual(self.stream.writes()[0][2]['data']['switch_value'], 'false')
        self.assertIn('did not report', self.dialog.status.text())

    def test_star_audience_and_level_are_sent_on_apply(self):
        self.load()
        self.dialog.comment_controls['star_comments'].setChecked(True)
        self.dialog.star_group.setCurrentIndex(self.dialog.star_group.findData(3))
        self.dialog.star_level.setCurrentIndex(self.dialog.star_level.findData(20))
        self.dialog.apply_comments_button.click()
        self.wait_idle()
        params = self.stream.writes()[0][2]['params']
        self.assertEqual((params['grant_group'], params['grant_level'], params['star_comment_switch']), (3, 20, 'true'))

    def test_partial_failure_requires_refresh_before_reapply(self):
        self.load()
        self.stream.failures['webcast/room/star_comment/update/'] = ConnectionError('timeout')
        self.dialog.comment_controls['allow_comments'].setChecked(False)
        self.dialog.comment_controls['star_comments'].setChecked(True)
        self.dialog.apply_comments_button.click()
        self.wait_idle()
        self.assertIn('Applied allow_comments', self.dialog.status.text())
        self.assertFalse(self.dialog.apply_comments_button.isEnabled())
        self.dialog.apply_comments()
        self.assertEqual(len(self.stream.writes()), 2)
        self.dialog.refresh()
        self.wait_idle()
        self.assertTrue(self.dialog.apply_comments_button.isEnabled())

    def test_account_switch_same_cookie_file_rejected(self):
        self.load('words')
        self.stream.account['user_id_str'] = '999'
        self.dialog.word_input.setText('new')
        self.dialog.add_word_button.click()
        self.wait_idle()
        self.assertEqual(self.stream.writes(), [])
        self.assertIn('account changed', self.dialog.status.text())

    def test_context_invalidation_is_permanent(self):
        self.load('viewers')
        self.dialog.viewer_table.selectRow(0)
        self.assertEqual(self.dialog.viewer_id.text(), '888')
        self.current = False
        self.dialog.update_controls()
        self.current = True
        self.dialog.update_controls()
        self.assertFalse(self.dialog.viewer_buttons['mute'].isEnabled())
        self.dialog.moderate('mute')
        self.assertEqual(self.stream.writes(), [])

    def test_busy_blocks_duplicate_action_and_close(self):
        self.load('viewers')
        self.dialog.viewer_id.setText('888')
        started, release = threading.Event(), threading.Event()
        request = self.stream._signed_post_json
        def delayed(*args, **kwargs):
            started.set()
            release.wait(2)
            return request(*args, **kwargs)
        with patch.object(self.stream, '_signed_post_json', side_effect=delayed):
            try:
                self.dialog.viewer_buttons['mute'].click()
                self.assertTrue(started.wait(1))
                self.dialog.moderate('mute')
                self.dialog.reject()
                self.assertFalse(self.dialog.closed)
                self.assertFalse(self.dialog.viewer_buttons['mute'].isEnabled())
            finally:
                release.set()
                self.wait_idle()
        self.assertEqual(len(self.stream.writes()), 1)

    def test_template_limits_and_explicit_save(self):
        self.load('about')
        self.dialog.about_text.setPlainText('😀' * 7)
        self.assertFalse(self.dialog.save_about_button.isEnabled())
        self.dialog.about_text.setPlainText('Welcome')
        self.assertEqual(self.stream.writes(), [])
        self.dialog.save_about_button.click()
        self.wait_idle()
        self.assertEqual(self.stream.writes()[0][2]['payload']['input_content_list'], ['Welcome'])

    def test_unknown_permissions_disable_restricted_controls(self):
        self.stream.responses['webcast/room/create_info/'] = {}
        self.stream.responses['webcast/sub/privilege/get_sub_info/'] = {}
        self.load()
        for key in ('subscriber_only_chat', 'star_comments'):
            self.assertFalse(self.dialog.comment_controls[key].isEnabled())
        self.assertFalse(self.dialog.star_group.isEnabled())


if __name__ == '__main__':
    unittest.main()
