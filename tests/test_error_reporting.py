"""Error attribution checks with mocked dialogs, processes and networking."""
from tests.gui_helpers import drive_workflow
import errno
import os
import io
import json
import tempfile
import threading
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from tests import test_client_modes as base
from Libs.error_reporting import (HostedSignerError, OperationError, SignerFailureKind,
                                 hosted_signer_failure, write_proxy_error, read_proxy_error)
from Libs import signers as headers_api
from Libs import XFrameSign as frames_api
from Libs import ffmpeg_sei_proxy as proxy

gui = base.gui


class ErrorReportingTests(unittest.TestCase):
    setUpClass = classmethod(base.ModeTests.setUpClass.__func__)
    setUp = base.ModeTests.setUp

    def window(self):
        with patch.object(gui.StreamKeyGeneratorWindow, 'ensure_device_identifiers', return_value=True), \
                patch.object(gui.StreamKeyGeneratorWindow, 'get_cookie_file_status', return_value=(False, 'No cookies')):
            w = gui.StreamKeyGeneratorWindow()
        def dispose():
            w.close()
            w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.addCleanup(dispose)
        return w

    def test_original_disk_full_message_stays_an_ordinary_error(self):
        w = self.window()
        message = ('The stream was blocked because the signed FFmpeg proxy could not start. '
                   'The real TikTok URL/key was not exposed.\n\n[Errno 28] No space left on device')
        with patch.object(gui.QMessageBox, 'critical') as critical, \
                patch.object(w, 'show_rapidapi_error') as api:
            w.show_error(message)
        critical.assert_called_once_with(w, 'Error', message)
        api.assert_not_called()

    def test_generic_proxy_and_local_signer_errors_do_not_imply_rapidapi(self):
        w = self.window()
        messages = [
            'Signed metadata is unavailable: [Errno 13] Permission denied',
            'Local frame-sign signer failed: invalid device profile',
            'FFmpeg proxy could not bind: address already in use',
            'FFmpeg proxy exited early: module framesign was not found',
            'Cannot write RapidAPI config file: [Errno 28] No space left on device',
            'Development signers are unavailable in production builds.',
            'HTTP 403 from webcast.tiktokv.com: request rejected',
            'HTTP 429 from TikTok: too many requests',
            'FFmpeg proxy with signed metadata exceeded its startup timeout',
            'Signature API response received successfully\n[Errno 28] No space left on device',
        ]
        for message in messages:
            with self.subTest(message=message), patch.object(w, 'get_rapidapi_key', return_value=''):
                self.assertEqual(w._rapidapi_error_kind(message), '')

    def test_typed_signer_categories_do_not_depend_on_message_words(self):
        w = self.window()
        for kind in SignerFailureKind:
            for message in ['Any wording', '[Errno 28] No space left on device', 'HTTP 429 quota subscription']:
                with self.subTest(kind=kind, message=message):
                    error = HostedSignerError(message, kind=kind)
                    self.assertEqual(w._rapidapi_error_kind(error), kind.value)
                    self.assertEqual(w._rapidapi_error_kind(message), '')

    def test_untyped_api_looking_messages_are_never_classified(self):
        w = self.window()
        for text in ['signature API failed: connection timed out', 'RapidAPI signer HTTP 429: quota exceeded',
                     'RapidAPI signer HTTP 403: not subscribed', 'frameSign response has blank signinfo/signvalue']:
            self.assertEqual(w._rapidapi_error_kind(RuntimeError(text)), '')

    def test_required_response_field_and_network_retry_exhaustion_are_not_subscription_or_quota(self):
        w = self.window()
        for message in ['signature API failed: required JSON field missing',
                        'signature API failed: Max retries exceeded with url: /signatures',
                        'RapidAPI signer HTTP 500: monthly statistics unavailable']:
            with self.subTest(message=message), patch.object(w, 'get_rapidapi_key', return_value=''):
                self.assertEqual(w._rapidapi_error_kind(HostedSignerError(message)), 'unavailable')

    def test_unrelated_proxy_log_lines_do_not_change_api_failure_kind(self):
        w = self.window()
        self.assertEqual(w._rapidapi_error_kind(HostedSignerError(
            'HTTP 403 from TikTok; disk quota exceeded\n'
            'signature API failed: connection timed out\n'
            'FFmpeg exited with code 429; file required')), 'unavailable')

    def test_real_api_error_still_opens_api_dialog(self):
        w = self.window()
        message = OperationError('FFmpeg proxy exited early', HostedSignerError('Request rejected', kind=SignerFailureKind.QUOTA))
        with patch.object(gui.QMessageBox, 'critical') as critical, \
                patch.object(w, 'show_rapidapi_error') as api:
            w.show_error(message)
        api.assert_called_once_with(message)
        critical.assert_not_called()

    def test_direct_api_dialog_call_does_not_relabel_an_unrelated_error(self):
        w = self.window()
        with patch.object(gui.QMessageBox, 'critical') as critical:
            w.show_rapidapi_error('Signed FFmpeg proxy failed: no space left on device')
        self.assertIn('no space left', critical.call_args.args[2])

    def test_proxy_disk_error_retains_cause_and_neutral_context(self):
        w = self.window()
        stream = SimpleNamespace(streamUrl='rtmp://example.invalid/live/fixture', roomId='123', streamId='456')
        disk_error = OSError(errno.ENOSPC, 'No space left on device')
        with patch.object(w, 'start_ffmpeg_proxy', side_effect=disk_error):
            with self.assertRaises(RuntimeError) as raised:
                drive_workflow(w.apply_stream_outputs(stream))
        self.assertIs(raised.exception.__cause__, disk_error)
        self.assertIn('Could not start the local FFmpeg proxy', str(raised.exception))
        self.assertIn('[Errno 28] No space left on device', str(raised.exception))
        self.assertEqual(w._rapidapi_error_kind(str(raised.exception)), '')
        self.assertFalse(w.is_live)
        self.assertEqual(w.url_output.text(), '')
        self.assertEqual(w.key_output.text(), '')

    def test_proxy_health_reports_process_and_log_without_guessing_a_signer_failure(self):
        w = self.window()
        w.local_proxy_active = True
        w.ffmpeg_proxy_process = Mock()
        w.ffmpeg_proxy_process.poll.return_value = 1
        with patch.object(gui, '_safe_log_tail', return_value='[Errno 28] No space left on device'), \
                patch.object(w, 'show_error') as report:
            w.check_ffmpeg_proxy_health()
        error = report.call_args.args[0]
        message = str(error)
        self.assertIn('FFmpeg proxy stopped with code 1', message)
        self.assertIn('Proxy log:', message)
        self.assertEqual(w._rapidapi_error_kind(error), '')

    def test_signer_type_survives_explicit_wrappers_and_signal_delivery(self):
        w = self.window()
        cause = HostedSignerError('arbitrary detail', kind=SignerFailureKind.SUBSCRIPTION)
        error = OperationError('load account', OperationError('make request', cause))
        received = []
        w.realtime_stats_failed.connect(received.append)
        worker = threading.Thread(target=lambda: w.realtime_stats_failed.emit(error))
        worker.start()
        worker.join(2)
        self.app.processEvents()
        self.assertEqual(received, [error])
        self.assertIs(hosted_signer_failure(received[0]), cause)
        self.assertEqual(w._rapidapi_error_kind(error), 'subscription')

    def test_only_explicit_cause_is_followed_and_cycles_are_safe(self):
        error = RuntimeError('local issue')
        error.__context__ = HostedSignerError('prior handled issue')
        self.assertIsNone(hosted_signer_failure(error))
        error.__cause__ = error
        self.assertIsNone(hosted_signer_failure(error))

    def test_proxy_report_recovers_typed_cause_and_never_classifies_log_text(self):
        w = self.window()
        path = str(Path(self.temp.name) / 'child-error.json')
        write_proxy_error(path, HostedSignerError('anything', kind=SignerFailureKind.QUOTA, status_code=429))
        w._proxy_error_reports['ffmpeg_proxy_process'] = path
        error = w.proxy_failure('ffmpeg_proxy_process', 'Proxy exited')
        self.assertEqual(w._rapidapi_error_kind(error), 'quota')
        self.assertFalse(Path(path).exists())
        self.assertEqual(w._rapidapi_error_kind(w.proxy_failure('ffmpeg_proxy_process', 'RapidAPI signer HTTP 429')), '')

    def test_proxy_reports_preserve_local_origin_and_reject_invalid_metadata(self):
        path = Path(self.temp.name) / 'child-error.json'
        write_proxy_error(path, OSError(errno.ENOSPC, 'RapidAPI signer HTTP 429'))
        self.assertIsNone(hosted_signer_failure(read_proxy_error(path)))
        for data in [{'version': 2}, {'version': True, 'source': 'hosted_signer', 'message': 'text', 'kind': 'quota'},
                     {'version': 1, 'source': 'hosted_signer', 'message': 'text', 'kind': 'unknown'},
                     {'version': 1, 'source': 'hosted_signer', 'message': 'text', 'kind': 'quota', 'status_code': '429'}]:
            path.write_text(json.dumps(data))
            self.assertIsNone(read_proxy_error(path))
        path.write_text('{broken')
        self.assertIsNone(read_proxy_error(path))

    def test_report_disk_error_does_not_replace_original_failure(self):
        error = OSError(errno.ENOSPC, 'No space left on device')
        with patch('Libs.error_reporting.open', side_effect=error):
            write_proxy_error(str(Path(self.temp.name) / 'error.json'), error)

    def test_proxy_entry_writes_structured_terminal_error(self):
        path = str(Path(self.temp.name) / 'child-error.json')
        error = HostedSignerError('rejected', kind=SignerFailureKind.QUOTA)
        with patch.object(proxy, '_run_proxy', side_effect=error), patch.object(gui.sys, 'argv',
                ['proxy', '--ffmpeg', 'fixture', '--listen-url', 'rtmp://127.0.0.1/live',
                 '--output-url', 'rtmp://example.invalid/live', '--error-report', path]):
            with self.assertRaises(HostedSignerError):
                proxy.main()
        self.assertEqual(hosted_signer_failure(read_proxy_error(path)).kind, SignerFailureKind.QUOTA)

    def test_proxy_log_closes_even_when_initialization_raises(self):
        captured = []
        def fail(args, log):
            captured.append(log)
            raise RuntimeError('Startup failure')
        path = Path(self.temp.name) / 'startup.log'
        args = SimpleNamespace(resolution='1920x1080', log=str(path))
        with patch.object(proxy, '_run_proxy_with_log', side_effect=fail), self.assertRaises(RuntimeError):
            proxy._run_proxy(args)
        self.assertTrue(captured[0].closed)
        path.unlink()

    def test_proxy_local_refresh_failure_keeps_its_local_type(self):
        signer = proxy.LocalSeiSigner(uid='1', device_id='2', room_id='3', aid='8311',
                                      width=1920, height=1080, log=io.StringIO())
        signer._last_sign_result = {'signinfo': 'fixture', 'signvalue': 'fixture'}
        error = OSError(errno.ENOSPC, 'No space left on device')
        with patch.object(proxy, 'frame_sign', side_effect=error):
            signer._refresh_sign_result(1700000000000, 'test')()
        with self.assertRaises(OperationError) as raised:
            signer.signed_payload(refresh_signature=False)
        self.assertIs(raised.exception.__cause__, error)
        self.assertIsNone(hosted_signer_failure(raised.exception))

    def test_actual_proxy_child_transfers_type_without_reading_words(self):
        w = self.window()
        for is_api in (True, False):
            log_path = str(Path(self.temp.name) / f'proxy-{is_api}.log')
            constructor = ("HostedSignerError('unrelated wording', kind=SignerFailureKind.QUOTA)" if is_api else
                           "RuntimeError('RapidAPI signer HTTP 429: quota exhausted')")
            script = ("import sys; from Libs.error_reporting import *; "
                      f"write_proxy_error(sys.argv[-1], {constructor}); sys.exit(1)")
            def wait_for_exit(**options):
                options['process'].wait(timeout=5)
                return False
            with open(log_path, 'w', encoding='utf-8') as log:
                w.ffmpeg_proxy_log_file = log
                with patch.object(w, 'wait_for_ffmpeg_proxy_listener', side_effect=wait_for_exit), \
                        self.assertRaises(RuntimeError) as raised:
                    drive_workflow(w._launch_sei_proxy([sys.executable, '-c', script, '--output-url', 'fixture'],
                        log, log_path, log_path + '.sei', 'ffmpeg_proxy_process'))
            self.assertEqual(w._rapidapi_error_kind(raised.exception), 'quota' if is_api else '')
            # Production shutdown deliberately reaps children off the GUI
            # thread. Wait for that contract before deleting Windows log files.
            for cleanup in w._proxy_cleanup_threads:
                cleanup.join(timeout=10)
                self.assertFalse(cleanup.is_alive())
            self.assertFalse(w._proxy_error_reports)
            self.assertFalse(list(Path(self.temp.name).glob('*.error.json')))


class SignerBoundaryTests(unittest.TestCase):
    def setUp(self):
        for module in [headers_api, frames_api]:
            for name, value in [('_rate_limit_wait_seconds', lambda: 0), ('_update_quota_headers', None),
                                ('_note_rate_limited', None), ('_clear_rate_limit', None),
                                ('_log', lambda *_: None), ('_api_base_url', lambda: 'https://example.invalid/')]:
                p = patch.object(module, name, value)
                p.start()
                self.addCleanup(p.stop)

    def call(self, module):
        return module._post_signatures({}) if module is headers_api else module._post_json('/framesign', {})

    def test_http_status_sets_category_even_when_body_words_disagree(self):
        for module in [headers_api, frames_api]:
            for status, kind in [(401, SignerFailureKind.SUBSCRIPTION), (403, SignerFailureKind.SUBSCRIPTION),
                                 (429, SignerFailureKind.QUOTA), (500, SignerFailureKind.UNAVAILABLE)]:
                response = Mock(status_code=status, headers={}, text='any message')
                response.json.return_value = {'error': 'required quota exceeded 401 429'}
                with self.subTest(module=module.__name__, status=status), \
                        patch.object(module.requests, 'post', return_value=response):
                    with self.assertRaises(HostedSignerError) as raised:
                        self.call(module)
                    self.assertEqual(raised.exception.kind, kind)
                    self.assertEqual(raised.exception.status_code, status)

    def test_local_os_errors_are_not_wrapped_as_api_errors(self):
        for module in [headers_api, frames_api]:
            error = OSError(errno.ENOSPC, 'No space left on device')
            with patch.object(module.requests, 'post', side_effect=error):
                with self.assertRaises(OSError) as raised:
                    self.call(module)
            self.assertIs(raised.exception, error)

    def test_network_failures_have_typed_api_origin(self):
        for module in [headers_api, frames_api]:
            error = module.requests.exceptions.RequestException('connection failed')
            with patch.object(module.requests, 'post', side_effect=error):
                with self.assertRaises(HostedSignerError) as raised:
                    self.call(module)
            self.assertEqual(raised.exception.kind, SignerFailureKind.UNAVAILABLE)
            self.assertIs(raised.exception.__cause__, error)

    def test_malformed_headers_are_a_typed_remote_response_failure(self):
        response = Mock(status_code=200, headers={}, text='')
        response.json.return_value = {'headers': {'x-khronos': '', 'x-ladon': '', 'x-argus': ''}}
        with patch.object(headers_api.requests, 'post', return_value=response):
            with self.assertRaises(HostedSignerError):
                self.call(headers_api)

    def test_local_response_read_error_keeps_local_type(self):
        for module in [headers_api, frames_api]:
            error = OSError(errno.ENOSPC, 'No space left on device')
            response = Mock(status_code=200, headers={}, text='')
            response.json.side_effect = error
            with patch.object(module.requests, 'post', return_value=response):
                with self.assertRaises(OSError) as raised:
                    self.call(module)
            self.assertIs(raised.exception, error)

    def test_signature_wrapper_keeps_local_exceptions_and_remote_types(self):
        for error in [OSError(errno.ENOSPC, 'no space'), HostedSignerError('detail', kind=SignerFailureKind.QUOTA)]:
            with patch.object(headers_api, '_should_use_api', return_value=True), \
                    patch.object(headers_api, '_post_signatures', side_effect=error):
                with self.assertRaises(type(error)) as raised:
                    headers_api.signature_headers(1700000000)
                self.assertIs(raised.exception, error)


if __name__ == '__main__':
    unittest.main()
