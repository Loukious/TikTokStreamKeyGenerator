"""Real Qt workers against fake contribution responses; no live account traffic."""
import contextlib
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QByteArray, QBuffer, QCoreApplication, QEvent, QIODevice, QObject, QUrl, Qt, Signal
from PySide6.QtGui import QFont, QImage, QTextDocument
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Libs.live_management_ui import LiveManagementDialog
from Libs.viewer_contributions_ui import ViewerContributionsDialog
from tests.test_viewer_contributions import ContributionStream, SUMMARY_PATH, EMOTE_URL


class ContributionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stream = ContributionStream()
        self.current = True
        self.worker_threads = []
        @contextlib.contextmanager
        def factory():
            self.worker_threads.append(threading.get_ident())
            yield self.stream
        self.factory = factory
        self.dialog = ViewerContributionsDialog(factory, room_id='456', viewer_id='888',
            viewer_name='<Viewer>', expected_user_id='123', is_current=lambda: self.current, auto_refresh=False)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.wait_idle()
        self.dialog.reject()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def wait_idle(self):
        deadline = time.monotonic() + 4
        while self.dialog.busy and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.dialog.busy)

    def load(self):
        self.dialog.refresh()
        self.wait_idle()
        self.assertIsNotNone(self.dialog.state, self.dialog.status.text())

    def test_all_fields_render_from_background_read(self):
        self.load()
        self.assertEqual([w.text() for w in self.dialog.metrics.values()], ['≥ 12 min', '125', '3', '8'])
        self.assertEqual(self.dialog.follow_label.text(), 'Followed you for 30 days')
        self.assertIn('<Great stream> 👀', self.dialog.comments.toPlainText())
        self.assertEqual(self.dialog.viewer_label.textFormat(), Qt.PlainText)
        self.assertIn('Updated', self.dialog.status.text())
        self.assertNotIn(threading.get_ident(), self.worker_threads)
        self.assertEqual(self.stream.writes(), [])

    def test_unavailable_fields_and_empty_comments_are_not_fabricated(self):
        self.stream.responses[SUMMARY_PATH] = {'like_count': 0, 'comment_list': []}
        self.load()
        self.assertEqual(self.dialog.metrics['like_count'].text(), '0')
        self.assertEqual(self.dialog.metrics['watch_duration'].text(), 'Unavailable')
        self.assertTrue(self.dialog.follow_label.isHidden())
        self.assertEqual(self.dialog.comments.toPlainText(), 'No recent comments.')

    def test_username_resolves_once_and_refresh_stays_on_same_id(self):
        self.dialog.viewer_id = '@viewer'
        self.stream.responses['webcast/anchor/user_search/'] = {'matched_user_list': [
            {'user_info': {'id_str': '888', 'display_id': 'viewer', 'nickname': 'The viewer'}}]}
        self.load()
        self.assertEqual(self.dialog.viewer_id, '888')
        self.assertEqual(self.dialog.viewer_label.text(), 'The viewer · @viewer')
        self.assertEqual(self.dialog.identity_label.text(), 'User ID: 888')
        self.stream.responses['webcast/anchor/user_search/']['matched_user_list'][0]['user_info']['id_str'] = '999'
        self.load()
        self.assertEqual(self.dialog.viewer_id, '888')
        self.assertEqual(sum(call[1] == 'webcast/anchor/user_search/' for call in self.stream.calls), 1)

    def test_failed_refresh_clears_previous_viewer_data(self):
        self.load()
        self.stream.failures[SUMMARY_PATH] = TimeoutError('Request timed out')
        self.dialog.refresh()
        self.wait_idle()
        self.assertIsNone(self.dialog.state)
        self.assertEqual(self.dialog.metrics['like_count'].text(), 'Unavailable')
        self.assertNotIn('Great stream', self.dialog.comments.toPlainText())
        self.assertIn('timed out', self.dialog.status.text())
        self.assertTrue(self.dialog.refresh_button.isEnabled())

    def test_context_change_clears_data_and_cannot_be_reversed(self):
        self.load()
        self.current = False
        self.dialog.update_controls()
        self.current = True
        self.dialog.update_controls()
        self.assertFalse(self.dialog.refresh_button.isEnabled())
        self.assertIsNone(self.dialog.state)
        calls = len(self.stream.calls)
        self.dialog.refresh()
        self.assertEqual(len(self.stream.calls), calls)

    def test_close_during_read_and_duplicate_refresh_are_safe(self):
        started, release = threading.Event(), threading.Event()
        request = self.stream._signed_get_json
        def delayed(url, **kwargs):
            if SUMMARY_PATH in url:
                started.set()
                release.wait(3)
            return request(url, **kwargs)
        with patch.object(self.stream, '_signed_get_json', side_effect=delayed):
            try:
                self.dialog.refresh()
                self.assertTrue(started.wait(1))
                self.dialog.refresh()
                self.assertFalse(self.dialog.refresh_button.isEnabled())
                self.dialog.reject()
                self.assertTrue(self.dialog.closed)
            finally:
                release.set()
                self.wait_idle()
        self.assertIsNone(self.dialog.state)
        self.assertEqual(sum(call[1] == SUMMARY_PATH for call in self.stream.calls), 1)

    def test_collapsing_does_not_refetch(self):
        self.load()
        calls = len(self.stream.calls)
        self.dialog.toggle.click()
        self.assertTrue(self.dialog.content.isHidden())
        self.dialog.toggle.click()
        self.assertFalse(self.dialog.content.isHidden())
        self.assertEqual(len(self.stream.calls), calls)

    def test_large_font_keeps_metrics_and_comment_text_readable(self):
        original_font = self.app.font()
        self.app.setFont(QFont(original_font.family(), 16))
        card = ViewerContributionsDialog(self.factory, room_id='456', viewer_id='888', auto_refresh=False)
        try:
            card.show()
            QTest.qWait(30)
            self.assertEqual(card.comments.document().defaultFont().pointSizeF(), 16)
            for value in card.metrics.values():
                value.setText('≥ 12 min')
            QTest.qWait(30)
            for value in card.metrics.values():
                self.assertGreaterEqual(value.height(), value.fontMetrics().height())
        finally:
            card.reject()
            card.deleteLater()
            self.app.setFont(original_font)

    def test_comments_escape_html_and_only_registered_images_render(self):
        browser = self.dialog.comments
        with patch.object(browser, 'fetch_emote') as fetch:
            browser.set_comments([[{'text': '<img src="https://attacker.test/a"> & 👀'},
                                   {'text': '[Emote]', 'emote_url': EMOTE_URL}]])
        fetch.assert_called_once_with(EMOTE_URL, 'contribution-emote:0')
        self.assertIn('<img src="https://attacker.test/a">', browser.toPlainText())
        self.assertIsNone(browser.loadResource(QTextDocument.ImageResource, QUrl('file:///private')))
        image = QImage(20, 20, QImage.Format_ARGB32)
        image.fill(Qt.red)
        browser.images['contribution-emote:0'] = image
        browser.render_comments()
        self.assertIn('contribution-emote:0', browser.toHtml())
        browser.emote_tooltip(QUrl('contribution-emote:0'))
        self.assertIn('data:image/png;base64,', browser.toolTip())
        browser.emote_tooltip(QUrl())
        self.assertEqual(browser.toolTip(), '')

    def test_management_button_binds_selected_viewer_and_current_host(self):
        management = LiveManagementDialog(self.factory, room_id='456',
            viewers=[{'id': '888', 'name': '<Viewer>'}], auto_refresh=False)
        try:
            self.assertFalse(management.contributions_button.isEnabled())
            management.user_id = '123'
            management.viewer_id.setText('@viewer.name')
            management.update_controls()
            self.assertTrue(management.contributions_button.isEnabled())
            self.assertTrue(all(not button.isEnabled() for button in management.viewer_buttons.values()))
            with patch('Libs.live_management_ui.ViewerContributionsDialog') as card:
                management.contributions_button.click()
                self.assertEqual(card.call_args.kwargs['viewer_id'], '@viewer.name')
            management.viewer_table.selectRow(0)
            management.update_controls()
            with patch('Libs.live_management_ui.ViewerContributionsDialog') as card:
                management.contributions_button.click()
                card.assert_called_once()
                values = card.call_args.kwargs
                self.assertEqual((values['room_id'], values['viewer_id'], values['expected_user_id']), ('456', '888', '123'))
                self.assertEqual(values['viewer_name'], '<Viewer>')
                card.return_value.exec.assert_called_once()
            management.room_id = ''
            management.update_controls()
            self.assertFalse(management.contributions_button.isEnabled())
        finally:
            management.reject()
            management.deleteLater()

    def test_inline_emote_download_decodes_raster_and_drops_oversized_or_cancelled_data(self):
        class Reply(QObject):
            readyRead = Signal()
            finished = Signal()
            def __init__(self, data):
                super().__init__()
                self.data, self.failed = data, False
            def setReadBufferSize(self, size):
                self.limit = size
            def readAll(self):
                data, self.data = self.data, b''
                return QByteArray(data)
            def abort(self):
                self.failed = True
                self.finished.emit()
            def error(self):
                return QNetworkReply.OperationCanceledError if self.failed else QNetworkReply.NoError
            def attribute(self, _):
                return 200

        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(Qt.green)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        browser = self.dialog.comments
        for data, cancel, valid in ((bytes(buffer.data()), False, True),
                                    (b'x' * (browser.MAX_IMAGE_BYTES + 1), False, False),
                                    (bytes(buffer.data()), True, False), (b'<svg/>', False, False)):
            with self.subTest(cancel=cancel, valid=valid, size=len(data)):
                reply = Reply(data)
                with patch.object(browser.network, 'get', return_value=reply):
                    browser.set_comments([[{'text': '[Emote]', 'emote_url': EMOTE_URL}]])
                    if cancel:
                        browser.cancel_images()
                    else:
                        reply.readyRead.emit()
                        if not reply.failed:
                            reply.finished.emit()
                self.assertEqual(bool(browser.images), valid)
                self.assertFalse(browser.pending)


class ContributionEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.test_client_modes import ModeTests
        ModeTests.setUp(self)

    def test_management_collects_audience_numeric_ids_and_reuses_saved_pc_profile(self):
        from tests import test_client_modes as base
        window = base.ModeTests.window(self)
        window.is_live = True
        window.current_room_id = '456'
        window._chat_viewers['888'] = {'id': '888', 'name': 'Recent commenter'}
        window._populate_audience_list([
            {'user': {'id_str': '999', 'display_id': 'audience_user', 'nickname': 'Audience viewer'}},
            {'user': {'id_str': '888', 'nickname': 'Same commenter'}},
            {'user': {'display_id': 'not_a_numeric_id'}},
        ], '')
        with patch.object(window, 'get_cookie_file_status', return_value=(True, 'Ready')), \
             patch.object(base.gui, 'LiveManagementDialog') as management, \
             patch.object(base.gui, 'Stream') as stream:
            window.open_live_management()
            values = management.call_args.kwargs
            self.assertEqual(values['viewers'], [{'id': '888', 'name': 'Recent commenter'},
                                                 {'id': '999', 'name': 'Audience viewer'}])
            self.assertEqual(values['room_id'], '456')
            management.call_args.args[0]()
            self.assertEqual(stream.call_args.kwargs['device_type'], 'pc')
            self.assertTrue(values['is_current']())
            window.current_room_id = '789'
            self.assertFalse(values['is_current']())
        window.is_live = False


if __name__ == '__main__':
    unittest.main()
