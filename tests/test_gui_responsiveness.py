"""Delayed workers must leave Qt timers running and restore UI state safely."""
import os
import json
from pathlib import Path
import threading
import time
from unittest.mock import Mock, MagicMock, patch
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from Libs.gui_tasks import BackgroundTask, Work, ForegroundTask
from tests import test_client_modes as base

gui = base.gui


def wait_until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not predicate():
        raise AssertionError('Qt operation did not complete')


class ResponsiveTests(unittest.TestCase):
    setUpClass = classmethod(base.ModeTests.setUpClass.__func__)
    setUp = base.ModeTests.setUp

    def window(self):
        Path(self.path).write_text(json.dumps(self.config))
        window = base.ModeTests.window(self)
        window._game_tags_loading = False
        window.device_initialization_attempted = True
        window.games = {'1': 'Test game'}
        window.topic_combo.setCurrentText('Gaming')
        window.game_combo.addItem('Test game')
        window.game_combo.setCurrentText('Test game')
        cookie_status = patch.object(window, 'get_cookie_file_status', return_value=(True, 'Fixture cookies'))
        cookie_status.start()
        self.addCleanup(cookie_status.stop)
        return window

    def hold(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        threads = []
        def delayed(*_, **__):
            threads.append(threading.get_ident())
            started.set()
            if not release.wait(3):
                raise RuntimeError('Test worker not released')
            return True
        return started, release, threads, delayed

    def check_responsive(self, window, started):
        wait_until(started.is_set)
        ticks = []
        timer = QTimer(window)
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        for _ in range(10):
            QTest.qWait(10)
        timer.stop()
        self.assertGreaterEqual(len(ticks), 3)

    def test_pause_resume_and_end_do_not_block_qt_or_allow_duplicate_actions(self):
        for method, api, paused in (('pause_stream', 'pauseStream', False),
                                   ('resume_stream', 'resumePausedStream', True),
                                   ('end_stream', 'endStream', False)):
            with self.subTest(method=method):
                w = self.window()
                w.is_live, w.is_paused = True, paused
                w.current_room_id, w.current_stream_id = '100', '200'
                started, release, threads, delayed = self.hold()
                stream = MagicMock()
                stream.__enter__.return_value = stream
                getattr(stream, api).side_effect = delayed
                with patch.object(w, 'stream_factory', return_value=lambda: stream), \
                     patch.object(w, 'ensure_rapidapi_signer', return_value=True), \
                     patch.object(w, 'show_info'), patch.object(w, 'show_error') as error, \
                     patch.object(w, 'refresh_realtime_stats'), patch.object(w, 'refresh_audience_safety'):
                    task = getattr(w, method)()
                    self.assertIsNone(getattr(w, method)())
                    self.check_responsive(w, started)
                    self.assertTrue(task.dialog.isVisible())
                    self.assertFalse(w.end_live_button.isEnabled())
                    self.assertFalse(w.device_type_combo.isEnabled())
                    release.set()
                    wait_until(lambda: w._foreground_task is None)
                    error.assert_not_called()
                    getattr(stream, api).assert_called_once()
                    self.assertNotEqual(threads[0], threading.get_ident())
                self.assertEqual(w.is_live, method != 'end_stream')
                self.assertEqual(w.is_paused, method == 'pause_stream')

    def test_stream_failure_restores_controls_and_keeps_typed_cause(self):
        from Libs.error_reporting import HostedSignerError
        w = self.window()
        w.is_live = True
        w.current_room_id, w.current_stream_id = '1', '2'
        stream = MagicMock()
        stream.__enter__.return_value = stream
        failure = HostedSignerError('Any wording')
        stream.pauseStream.side_effect = failure
        with patch.object(w, 'stream_factory', return_value=lambda: stream), \
             patch.object(w, 'show_error') as error:
            w.pause_stream()
            wait_until(lambda: w._foreground_task is None)
            error.assert_called_once_with(failure)
        self.assertTrue(w.is_live)
        self.assertFalse(w.is_paused)
        self.assertTrue(w.pause_live_button.isEnabled())
        self.assertTrue(w.end_live_button.isEnabled())

    def test_client_mode_unlocks_after_start_end_and_delayed_poll_completions(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                w = self.window()
                heartbeat_started, heartbeat_release, _, heartbeat_hold = self.hold()
                safety_started, safety_release, _, safety_hold = self.hold()
                stream = MagicMock()
                stream.__enter__.return_value = stream
                stream.getCreateRoomInfo.return_value = {'data': {}}
                stream.getContinuableStreamInfo.return_value = {'has_room': False}
                stream.createStream.return_value = True
                stream.endStream.return_value = True
                for name, value in {'roomId': '100', 'streamId': '200', 'ownerUserId': '300',
                                    'streamUrl': '', 'baseStreamUrl': '', 'streamKey': '',
                                    'multiStreamUrl': '', 'multiStreamKey': '', 'streamShareUrl': ''}.items():
                    setattr(stream, name, value)
                def heartbeat(*args, **kwargs):
                    heartbeat_hold()
                    if fail:
                        raise RuntimeError('Delayed heartbeat failure')
                    return {'data': {}}
                def safety(**kwargs):
                    safety_hold()
                    if fail:
                        raise RuntimeError('Delayed safety failure')
                    return {'status': 'OK'}
                stream.anchorHeartbeat.side_effect = heartbeat
                stream.getViolationStatus.side_effect = safety
                original_outputs = w.apply_stream_outputs
                with patch.object(w, 'stream_factory', return_value=lambda: stream), \
                     patch.object(w, 'ensure_rapidapi_signer', return_value=True), \
                     patch.object(w, 'apply_stream_outputs', side_effect=lambda stream, **options:
                                  original_outputs(stream, start_proxy=False, **options)), \
                     patch.object(w, 'show_info'), patch.object(w, 'show_error') as error:
                    w.generate_stream()
                    wait_until(lambda: w._foreground_task is None and w.is_live)
                    wait_until(lambda: heartbeat_started.is_set() and safety_started.is_set())
                    w.end_stream()
                    wait_until(lambda: w._foreground_task is None)
                    self.assertFalse(w.is_live)
                    self.assertFalse(w.device_type_combo.isEnabled())
                    heartbeat_release.set()
                    wait_until(lambda: not w.anchor_heartbeat_in_flight)
                    self.assertFalse(w.device_type_combo.isEnabled())
                    safety_release.set()
                    wait_until(lambda: not w.audience_safety_in_flight)
                    self.assertTrue(w.device_type_combo.isEnabled())
                    self.assertTrue(w.device_settings_button.isEnabled())
                    self.assertEqual(w.anchor_ping_status, gui.ANCHOR_STATUS_DEFAULT)
                    self.assertEqual(w.anchor_heartbeat_error_count, 0)
                    w.device_type_combo.setCurrentIndex(1)
                    self.assertEqual(w.device_type, 'mobile')
                    error.assert_not_called()

    def test_stats_success_and_failure_restore_mode_control_after_end(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                w = self.window()
                w.set_stream_state(is_live=True)
                w.realtime_stats_in_flight = True
                w.set_stream_state(is_live=False)
                self.assertFalse(w.device_type_combo.isEnabled())
                if failed:
                    w.realtime_stats_failed.emit(RuntimeError('Fixture stats failure'))
                else:
                    w.realtime_stats_loaded.emit({'is_live': False})
                self.assertTrue(w.device_type_combo.isEnabled())
                self.assertFalse(w.refresh_stats_button.isEnabled())
                w.device_type_combo.setCurrentIndex(1)
                self.assertEqual(w.device_type, 'mobile')

    def test_go_live_room_check_runs_in_worker(self):
        w = self.window()
        started, release, threads, delayed = self.hold()
        stream = MagicMock()
        stream.__enter__.return_value = stream
        def info(**kwargs):
            delayed()
            return {'data': {}}
        stream.getCreateRoomInfo.side_effect = info
        stream.getContinuableStreamInfo.return_value = {'has_room': False}
        stream.createStream.return_value = False
        with patch.object(w, 'stream_factory', return_value=lambda: stream), \
             patch.object(w, 'ensure_rapidapi_signer', return_value=True), \
             patch.object(w, 'show_error') as error:
            w.generate_stream()
            self.check_responsive(w, started)
            release.set()
            wait_until(lambda: w._foreground_task is None)
            error.assert_not_called()
        self.assertFalse(w.is_live)
        self.assertNotEqual(threads[0], threading.get_ident())

    def test_game_list_does_not_delay_window_construction_and_preserves_saved_id(self):
        started, release, threads, delayed = self.hold()
        def games():
            delayed()
            return {'42': 'Saved game'}
        with patch.object(gui, 'fetch_game_tags', games):
            w = base.ModeTests.window(self)
            self.assertFalse(started.is_set())
            w._config_extra['game_tag_id'] = '42'
            self.check_responsive(w, started)
            self.assertEqual(w.get_selected_game_id(), '42')
            release.set()
            wait_until(lambda: not w._game_tags_loading)
            self.assertEqual(w.game_combo.currentText(), 'Saved game')
        self.assertNotEqual(threads[0], threading.get_ident())

    def test_proxy_shutdown_is_detached_from_gui_and_waits_off_thread(self):
        w = self.window()
        started, release, threads, delayed = self.hold()
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = delayed
        w.ffmpeg_proxy_process = process
        w.ffmpeg_proxy_log_file = Mock()
        log = w.ffmpeg_proxy_log_file
        cleanup = w.stop_ffmpeg_proxy()
        self.check_responsive(w, started)
        self.assertIsNone(w.ffmpeg_proxy_process)
        self.assertTrue(cleanup.is_alive())
        release.set()
        wait_until(lambda: not cleanup.is_alive())
        log.close.assert_called_once()
        self.assertNotEqual(threads[0], threading.get_ident())

    def test_callbacks_after_owner_destruction_are_not_delivered(self):
        started, release, threads, delayed = self.hold()
        owner = QWidget()
        success, failure = Mock(), Mock()
        task = BackgroundTask(owner, Work(delayed), success, failure).start()
        wait_until(started.is_set)
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        release.set()
        QTest.qWait(50)
        success.assert_not_called()
        failure.assert_not_called()

    def test_proxy_listener_startup_keeps_loading_animation_responsive(self):
        w = self.window()
        started, release, threads, delayed = self.hold()
        process = Mock()
        process.poll.return_value = None
        with patch.object(gui, '_runtime_logs_dir', return_value=self.temp.name), \
             patch.object(gui, '_bundled_ffmpeg_path', return_value='fixture-ffmpeg'), \
             patch.object(w, 'build_ffmpeg_proxy_command', return_value=['fixture', '--output-url', 'fixture']), \
             patch.object(gui.subprocess, 'Popen', return_value=process), \
             patch.object(w, 'wait_for_ffmpeg_proxy_listener', side_effect=delayed), \
             patch.object(w, 'show_error') as error:
            task = ForegroundTask(w, w.start_ffmpeg_proxy('rtmp://example.invalid/live/fixture'), 'Starting proxy')
            w._foreground_task = task
            task.advance()
            self.check_responsive(w, started)
            self.assertTrue(task.dialog.isVisible())
            self.assertIn('signatures', task.dialog.label.text())
            self.assertFalse(w.local_proxy_active)
            release.set()
            wait_until(lambda: w._foreground_task is None)
            error.assert_not_called()
            self.assertTrue(w.local_proxy_active)
            self.assertNotEqual(threads[0], threading.get_ident())
            process.poll.return_value = 0
            cleanup = w.stop_ffmpeg_proxy()
            if cleanup:
                wait_until(lambda: not cleanup.is_alive())

    def test_browser_callback_wait_can_be_cancelled_and_restores_protocol(self):
        w = self.window()
        client = Mock()
        client.prepare_login.return_value = ('state', 'nonce', 'ticket')
        constructor_threads = []
        def factory(*args):
            constructor_threads.append(threading.get_ident())
            return client
        event, stop = threading.Event(), threading.Event()
        with patch.object(gui, 'backup_protocol_registry', return_value={'command': 'fixture'}), \
             patch.object(gui, 'register_temporary_protocol_handler', return_value=True), \
             patch.object(gui, 'restore_protocol_registry') as restore, \
             patch.object(gui, 'start_callback_server', return_value=(object(), 1, event, {'url': None})), \
             patch.object(gui, 'LiveStudioBrowserLoginClient', side_effect=factory), \
             patch.object(gui.webbrowser, 'open'), patch.object(w, 'show_error') as error:
            task = w.start_browser_login_flow()
            wait_until(lambda: 'Complete login' in task.dialog.label.text())
            started = threading.Event()
            started.set()
            self.check_responsive(w, started)
            task.dialog.cancel_button.click()
            wait_until(lambda: w._foreground_task is None)
            restore.assert_called_once_with({'command': 'fixture'})
            client.close.assert_called_once()
            client.exchange_login.assert_not_called()
            client.save_cookies.assert_not_called()
            error.assert_not_called()
        self.assertNotEqual(constructor_threads[0], threading.get_ident())

    def test_qr_poll_does_not_overlap_and_cancelled_confirmation_does_not_save(self):
        w = self.window()
        client = Mock()
        client.get_qrcode.side_effect = RuntimeError('Fixture has no QR image')
        with patch.object(gui, 'LiveStudioBrowserLoginClient', return_value=client):
            dialog = gui.LoginDialog(w)
            wait_until(lambda: not dialog._qr_busy)
            dialog.client, dialog.qr_token = client, 'fixture'
            client.qr_client_secret = 'secret'
            started, release, threads, delayed = self.hold()
            def poll(*args):
                delayed()
                return {'data': {'status': 'confirmed', 'client_secret': 'secret'}}
            client.check_qrconnect.side_effect = poll
            dialog.poll_qr_status()
            self.check_responsive(w, started)
            dialog.poll_qr_status()
            client.check_qrconnect.assert_called_once()
            dialog.reject()
            release.set()
            wait_until(lambda: client.close.call_count >= 2)
            QTest.qWait(50)
            client.save_cookies.assert_not_called()
            self.assertNotEqual(threads[0], threading.get_ident())
            dialog.deleteLater()

    def test_qr_close_ignores_delayed_result_and_closes_its_client(self):
        w = self.window()
        started, release, threads, delayed = self.hold()
        client = Mock()
        client.get_qrcode.side_effect = delayed
        with patch.object(gui, 'LiveStudioBrowserLoginClient', return_value=client):
            dialog = gui.LoginDialog(w)
            dialog.show()
            self.check_responsive(w, started)
            self.assertFalse(dialog.refresh_button.isEnabled())
            dialog.reject()
            release.set()
            wait_until(lambda: client.close.called)
            QTest.qWait(30)
            self.assertIsNone(dialog.qr_token)
            self.assertFalse(dialog.poll_timer.isActive())
            dialog.deleteLater()
        self.assertNotEqual(threads[0], threading.get_ident())


if __name__ == '__main__':
    unittest.main()
