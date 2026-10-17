"""Offline protobuf, reconnect and GUI lifecycle checks; no TikTok requests."""
import contextlib
import gzip
import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from websockets.sync.server import serve
from PySide6.QtCore import QCoreApplication, QEvent
from Libs import live_chat as chat
from tests import test_client_modes as base

gui = base.gui


def integer(number, value):
    return chat._encode_varint(number << 3) + chat._encode_varint(value)


def binary(number, value):
    return chat._bytes_field(number, value)


def text(number, value):
    return binary(number, value.encode('utf-8'))


def comment(message_id=101, content='Hello 👋', room=123):
    common = integer(2, message_id) + integer(3, room) + integer(4, 1700000000)
    user = integer(1, 7651319506488886791) + text(3, 'Viewer 🎮') + text(38, 'fixture')
    payload = binary(1, common) + binary(2, user) + text(3, content)
    return text(1, 'WebcastChatMessage') + binary(2, payload) + integer(3, message_id)


def gift(message_id=201, *, count=10, kind=1, ended=True, group=7001, group_count=1,
         user_id=7651319506488886791, gift_id=5655, name='Rose 🌹', room=123, metadata=True):
    common = integer(2, message_id) + integer(3, room) + integer(4, 1700000000)
    user = integer(1, user_id) + text(3, 'Viewer 🎮') + text(38, 'fixture')
    payload = binary(1, common) + integer(2, gift_id) + integer(4, group_count)
    payload += integer(5, count) + binary(7, user) + integer(9, int(ended)) + integer(11, group)
    if metadata:
        payload += binary(15, integer(5, gift_id) + integer(11, kind) + text(16, name))
    return text(1, 'WebcastGiftMessage') + binary(2, payload) + integer(3, message_id)


def response(messages=(), *, cursor='next', ext='extension', bootstrap=False, need_ack=True):
    data = b''.join(binary(1, item) for item in messages) + text(2, cursor) + text(5, ext)
    data += integer(8, 10000) + integer(9, int(need_ack))
    if bootstrap:
        data += binary(7, text(1, 'wrss') + text(2, 'fixture-token'))
        data += text(10, 'wss://webcast16-ws-alisg.tiktokv.com' + chat.WS_PATH)
    return data


def push(payload, *, zipped=False, log_id=991):
    headers = binary(5, text(1, 'im_cursor') + text(2, 'header-cursor'))
    if zipped:
        headers += binary(5, text(1, 'compress_type') + text(2, 'gzip'))
        payload = gzip.compress(payload)
    return integer(1, 5) + integer(2, log_id) + headers + text(7, 'msg') + binary(8, payload)


class ProtocolTests(unittest.TestCase):
    def test_gift_schema_preserves_sender_quantity_and_group(self):
        batch = chat.decode_push(push(response([gift()]), zipped=True))
        m = batch.messages[0]
        self.assertIsInstance(m, chat.GiftMessage)
        self.assertEqual((m.user_id, m.gift_id, m.gift_name, m.quantity),
                         ('7651319506488886791', '5655', 'Rose 🌹', 10))
        self.assertEqual(m.combo_key, ('5655', '7651319506488886791', '7001', 1))
        self.assertTrue(m.completed)
        self.assertEqual(m.text, 'sent Rose 🌹 ×10')
        self.assertIsNotNone(batch.ack)

    def test_gift_without_catalog_metadata_still_has_id_and_final_quantity(self):
        m = chat.decode_response(response([gift(metadata=False)])).messages[0]
        self.assertTrue(m.completed)
        self.assertEqual(m.text, 'sent Gift #5655 ×10')
        self.assertIsNone(m.combo_key)
        m = chat.decode_response(response([gift(count=0, name='')])).messages[0]
        self.assertEqual(m.text, 'sent Gift #5655')

    def test_comment_unicode_and_64_bit_identity(self):
        batch = chat.decode_response(response([comment()]))
        self.assertEqual(len(batch.messages), 1)
        m = batch.messages[0]
        self.assertEqual((m.message_id, m.room_id, m.user_id), ('101', '123', '7651319506488886791'))
        self.assertEqual((m.nickname, m.username, m.text), ('Viewer 🎮', 'fixture', 'Hello 👋'))

    def test_gzip_frame_acks_original_log_id_and_extension(self):
        batch = chat.decode_push(push(response([comment()], ext='ack extension'), zipped=True))
        self.assertEqual(batch.cursor, 'header-cursor')
        ack = chat.fields(batch.ack)
        self.assertEqual(chat._integer(ack, 2), 991)
        self.assertEqual(chat._text(ack, 7), 'ack')
        self.assertEqual(chat._text(ack, 8), 'ack extension')
        self.assertEqual(len(batch.messages), 1)

    def test_unknown_and_bad_messages_do_not_hide_valid_comments(self):
        other = text(1, 'WebcastLikeMessage') + binary(2, b'\xff')
        malformed = text(1, 'WebcastChatMessage') + binary(2, b'\xff')
        batch = chat.decode_response(response([other, malformed, comment()]))
        self.assertEqual(len(batch.messages), 1)

    def test_control_frames_and_no_ack_requested(self):
        self.assertEqual(chat.decode_push(chat.heartbeat_frame()).messages, [])
        self.assertTrue(chat.decode_push(text(7, 'close')).closed)
        self.assertIsNone(chat.decode_push(push(response(need_ack=False))).ack)

    def test_corrupt_and_oversized_payloads_are_bounded(self):
        for data in [b'\x00', b'\x0a\x7fshort', b'\x08' + b'\xff' * 10]:
            with self.assertRaises(chat.ChatProtocolError):
                chat.fields(data)
        with patch.object(chat, 'MAX_PACKET_BYTES', 100):
            with self.assertRaises(chat.ChatProtocolError):
                chat.decode_push(push(response([comment(content='x' * 200)]), zipped=True))

    def test_returned_server_does_not_leak_cookies_to_other_hosts(self):
        for server in ['wss://example.invalid' + chat.WS_PATH,
                       'wss://webcast.tiktokv.com.evil.invalid' + chat.WS_PATH,
                       'wss://webcast.tiktokv.com:444' + chat.WS_PATH,
                       'ws://webcast.tiktokv.com' + chat.WS_PATH,
                       'wss://user@webcast.tiktokv.com' + chat.WS_PATH]:
            with self.assertRaises(chat.ChatProtocolError):
                chat.socket_url(server, {})


class WorkerTests(unittest.TestCase):
    def client(self, **kwargs):
        return chat.LiveChatClient('123', Mock(), Mock(), Mock(), Mock(), **kwargs)

    def delivered(self, client):
        return [m for call in client.on_messages.call_args_list for m in call.args[0]]

    def test_small_gift_streak_emits_only_final_count(self):
        client = self.client()
        for i in range(1, 11):
            client._deliver(chat.decode_response(response([gift(200 + i, count=i, ended=False)])))
        client.on_messages.assert_not_called()
        client._deliver(chat.decode_response(response([gift(220, count=10)])))
        received = self.delivered(client)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].quantity, 10)

    def test_same_id_intermediate_does_not_hide_final_gift(self):
        client = self.client()
        client._deliver(chat.decode_response(response([gift(201, count=1, ended=False)])))
        client._deliver(chat.decode_response(response([gift(201, count=10)])))
        self.assertEqual([m.quantity for m in self.delivered(client)], [10])

    def test_replayed_final_group_with_new_message_id_is_suppressed(self):
        client = self.client()
        client._deliver(chat.decode_response(response([gift(201)])))
        client._deliver(chat.decode_response(response([gift(201), gift(202)])))
        self.assertEqual(len(self.delivered(client)), 1)

    def test_distinct_sender_gift_group_and_group_count_are_not_merged(self):
        client = self.client()
        client._deliver(chat.decode_response(response([
            gift(201), gift(202, user_id=99), gift(203, gift_id=1234),
            gift(204, group=7002), gift(205, group_count=2)])))
        self.assertEqual(len(self.delivered(client)), 5)

    def test_absent_group_ids_do_not_merge_unrelated_gifts(self):
        client = self.client()
        client._deliver(chat.decode_response(response([gift(201, group=0), gift(202, group=0)])))
        self.assertEqual(len(self.delivered(client)), 2)

    def test_studio_large_face_and_music_gifts_do_not_wait_for_repeat_end(self):
        client = self.client()
        client._deliver(chat.decode_response(response([
            gift(201, kind=2, ended=False), gift(202, kind=4, ended=False),
            gift(203, kind=22, ended=False), gift(204, kind=3, ended=False)])))
        self.assertEqual([m.gift_type for m in self.delivered(client)], [2, 4, 22])

    def test_mixed_events_keep_order_and_other_room_gifts_are_ignored(self):
        client = self.client()
        malformed = text(1, 'WebcastGiftMessage') + binary(2, b'\xff')
        client._deliver(chat.decode_response(response([
            comment(), gift(201, room=999), malformed, gift(202), comment(102)])))
        self.assertEqual([m.message_id for m in self.delivered(client)], ['101', '202', '102'])

    def test_gift_combo_memory_is_bounded(self):
        client = self.client()
        for i in range(2001):
            client._deliver(chat.decode_response(response([gift(10000 + i, group=10000 + i)])))
        self.assertEqual(len(client._finished_gift_combos), 2000)
        self.assertEqual(len(client._seen), 2000)

    def test_reconnect_deduplicates_and_ignores_other_rooms(self):
        client = self.client()
        client._deliver(chat.decode_response(response([comment(), comment(room=999)])))
        client._deliver(chat.decode_response(response([comment(), comment(102)], cursor='resume')))
        messages = [m for call in client.on_messages.call_args_list for m in call.args[0]]
        self.assertEqual([m.message_id for m in messages], ['101', '102'])
        self.assertEqual(client.cursor, 'resume')

    def test_stop_aborts_socket_and_drops_late_batch(self):
        client = self.client()
        client._socket = Mock()
        client.stop()
        client._socket.close_socket.assert_called_once()
        client._deliver(chat.decode_response(response([comment()])))
        client.on_messages.assert_not_called()

    def test_bootstrap_signs_exact_query_and_only_reads(self):
        client = self.client()
        stream = Mock()
        stream.getServerUrl.return_value = 'https://webcast16-normal.tiktokv.com/'
        stream._webcast_candidate_urls.side_effect = lambda url: [url]
        stream.s.get.return_value = SimpleNamespace(status_code=200, headers={},
            content=response(bootstrap=True))
        client.cursor, client.internal_ext = 'resume cursor', 'extension + test'
        params = chat.studio_params('123', '111', '5.0 fixture')
        client.signature_builder.return_value = {'X-Argus': 'fixture-signature'}
        client._bootstrap(stream, params)
        args = stream.s.get.call_args
        query = args.args[0].split('?', 1)[1]
        self.assertEqual(client.signature_builder.call_args.kwargs['params'], query)
        self.assertIn('cursor=resume%20cursor', query)
        self.assertIn('internal_ext=extension%20%2B%20test', query)
        self.assertEqual(args.kwargs['headers']['X-Argus'], 'fixture-signature')
        self.assertFalse(args.kwargs['allow_redirects'])
        stream.s.post.assert_not_called()

    def test_reconnect_refreshes_tokens_and_preserves_cursor(self):
        stream = SimpleNamespace(client=SimpleNamespace(record={'device_id': '111'}),
                                 s=SimpleNamespace(headers={'user-agent': 'fixture'}, cookies=requests.cookies.RequestsCookieJar()),
                                 _apply_live_studio_headers=lambda: ('1.37.4', '5.0 fixture'))
        client = self.client(retry_delays=(0,))
        client.stream_factory = lambda: contextlib.nullcontext(stream)
        first = Mock()
        first.__enter__ = Mock(return_value=first)
        first.__exit__ = Mock(return_value=False)
        first.recv.side_effect = [push(response([comment()], cursor='first')), ConnectionError('drop')]
        second = Mock()
        second.__enter__ = Mock(return_value=second)
        second.__exit__ = Mock(return_value=False)
        def last_recv(**kwargs):
            client._stop.set()
            return chat.heartbeat_frame()
        second.recv.side_effect = last_recv
        client.connector = Mock(side_effect=[first, second])
        cursors = []
        def bootstrap(_stream, _params):
            cursors.append(client.cursor)
            return chat.decode_response(response([comment()], cursor='boot' + str(len(cursors)), bootstrap=True))
        client._bootstrap = bootstrap
        client._run()
        self.assertEqual(len(cursors), 2)
        self.assertEqual(cursors[1], 'header-cursor')
        self.assertEqual(client.connector.call_count, 2)
        self.assertEqual(sum(len(c.args[0]) for c in client.on_messages.call_args_list), 1)
        sent_types = [chat._text(chat.fields(c.args[0]), 7) for c in first.send.call_args_list]
        self.assertEqual(sent_types, ['hb', 'ack'])
        self.assertTrue(any('Reconnecting' in c.args[0] for c in client.on_status.call_args_list))

    def test_retry_delay_grows_and_stop_interrupts_backoff(self):
        client = self.client(retry_delays=(1, 2, 4))
        client.stream_factory.side_effect = RuntimeError('private token URL')
        delays = []
        def wait(delay):
            delays.append(delay)
            return len(delays) == 4
        with patch.object(client._stop, 'wait', side_effect=wait):
            client._run()
        self.assertEqual(delays, [1, 2, 4, 4])
        self.assertNotIn('private token', str(client.on_status.call_args_list))

    def test_idle_socket_reconnects(self):
        # Clock reaches the idle limit after the first receive timeout.
        client = self.client(clock=Mock(side_effect=[0, 0, 0, 46, 46]), retry_delays=(1,))
        stream = SimpleNamespace(client=SimpleNamespace(record={}),
            s=SimpleNamespace(headers={}, cookies=requests.cookies.RequestsCookieJar()),
            _apply_live_studio_headers=lambda: ('1.37.4', 'fixture'))
        client.stream_factory = lambda: contextlib.nullcontext(stream)
        ws = Mock()
        ws.__enter__ = Mock(return_value=ws)
        ws.__exit__ = Mock(return_value=False)
        ws.recv.side_effect = TimeoutError()
        client.connector = Mock(return_value=ws)
        client._bootstrap = lambda *_: chat.decode_response(response(bootstrap=True))
        with patch.object(client._stop, 'wait', return_value=True):
            client._run()
        self.assertTrue(any('Reconnecting' in c.args[0] for c in client.on_status.call_args_list))

    def test_real_local_socket_disconnect_reconnect_gzip_ack_and_stop(self):
        """Exercise the installed websocket library without a TikTok server."""
        listener = socket.create_server(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        complete = threading.Event()
        acknowledged = threading.Event()
        received, acknowledgements, requests_seen, errors = [], [], [], []
        stream = SimpleNamespace(client=SimpleNamespace(record={'device_id': '111'}),
            s=SimpleNamespace(headers={'user-agent': 'fixture'}, cookies=requests.cookies.RequestsCookieJar()),
            _apply_live_studio_headers=lambda: ('1.37.4', 'fixture'))
        client = self.client(retry_delays=(0.01,))
        client.stream_factory = lambda: contextlib.nullcontext(stream)
        client._bootstrap = lambda *_: chat.decode_response(response(bootstrap=True))
        def on_messages(messages):
            received.extend(m.message_id for m in messages)
            if received == ['101', '201', '102']:
                complete.set()
        client.on_messages = on_messages
        def handler(ws):
            try:
                requests_seen.append(ws.request)
                sequence = len(requests_seen)
                messages = ([comment(), gift(201, count=1, ended=False)] if sequence == 1 else
                            [comment(), gift(201, count=10), gift(202, count=10), comment(102)])
                ws.send(push(response(messages), zipped=True, log_id=sequence))
                while True:
                    frame = chat.fields(ws.recv(timeout=3))
                    if chat._text(frame, 7) == 'ack':
                        acknowledgements.append(chat._integer(frame, 2))
                        if sequence == 2:
                            acknowledged.set()
                        break
                # First close forces a reconnect, second waits for client stop.
                if sequence == 1:
                    ws.close()
                else:
                    try:
                        ws.recv(timeout=3)
                    except Exception:
                        pass
            except Exception as exc:
                errors.append(type(exc).__name__)
        with serve(handler, sock=listener, ping_interval=None) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                with patch.object(chat, 'socket_url', side_effect=lambda _server, params:
                        f'ws://127.0.0.1:{port}/chat?' + chat.urlencode(params)), \
                        patch.object(client, 'connector', side_effect=lambda url, **kwargs:
                            chat.connect(url, proxy=None, **kwargs)):
                    client.start()
                    self.assertTrue(complete.wait(5), 'Local chat did not reconnect')
                    # Delivery follows send(), but the peer may not have read
                    # the ACK yet. stop() intentionally aborts the socket.
                    self.assertTrue(acknowledged.wait(5), 'Server did not receive the second ACK')
                    client.stop()
                    client._thread.join(3)
                    self.assertFalse(client._thread.is_alive())
            finally:
                client.stop()
                server.shutdown()
                server_thread.join(3)
        self.assertEqual(received, ['101', '201', '102'])
        self.assertEqual(acknowledgements, [1, 2])
        self.assertEqual(errors, [])
        self.assertEqual(len(requests_seen), 2)
        self.assertTrue(all(r.headers.get('Origin') == 'file://' for r in requests_seen))


class GuiTests(unittest.TestCase):
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

    def live(self, w, room='123'):
        w.current_room_id = room
        with patch.object(w, 'sync_anchor_heartbeat_timer'), patch.object(w, 'sync_audience_safety_timer'), \
                patch.object(w, 'sync_realtime_stats_timer'):
            w.set_stream_state(is_live=True)

    def test_read_only_panel_starts_and_stops_with_live(self):
        w = self.window()
        self.assertTrue(w.chat_output.isReadOnly())
        self.assertEqual(w.chat_output.maximumBlockCount(), 1000)
        self.assertIsNone(w.chat_client)
        self.live(w)
        self.assertIsNotNone(w.chat_client)
        self.assertTrue(w.chat_reconnect_button.isEnabled())
        w.set_stream_state(is_live=False)
        self.assertIsNone(w.chat_client)
        self.assertEqual(w.chat_status.text(), 'LIVE ended')

    def test_notification_sound_defaults_off_and_can_be_enabled_then_disabled(self):
        w = self.window()
        self.live(w)
        self.assertFalse(w.chat_sound_checkbox.isChecked())
        self.assertTrue(w.settings_dialog.isAncestorOf(w.chat_sound_checkbox))
        with patch.object(gui.QApplication, 'beep') as beep:
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([comment()])).messages))
            beep.assert_not_called()
            w.chat_sound_checkbox.setChecked(True)
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([comment(102)])).messages))
            beep.assert_called_once()
            w.chat_sound_checkbox.setChecked(False)
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([comment(103)])).messages))
            beep.assert_called_once()

    def test_notification_sound_is_saved_on_settings_close_and_restored(self):
        w = self.window()
        w.chat_sound_checkbox.setChecked(True)
        w.settings_dialog.done(0)
        other = self.window()
        self.assertTrue(other.chat_sound_checkbox.isChecked())
        other.chat_sound_checkbox.setChecked(False)
        other.settings_dialog.done(0)
        self.assertFalse(self.window().chat_sound_checkbox.isChecked())

    def test_notifications_ignore_replays_empty_batches_and_old_room_callbacks(self):
        w = self.window()
        self.live(w)
        w.chat_sound_checkbox.setChecked(True)
        token = w._chat_generation
        messages = chat.decode_response(response([comment(), comment(102), gift()])).messages
        with patch.object(gui.QApplication, 'beep') as beep:
            w.on_chat_messages((token, messages))
            beep.assert_called_once()  # Burst produces one notification.
            w.reconnect_chat()
            w.on_chat_messages((w._chat_generation, messages))
            w.on_chat_messages((w._chat_generation, []))
            w.on_chat_messages((token, chat.decode_response(response([comment(103)])).messages))
            beep.assert_called_once()
            self.assertEqual(w.chat_output.toPlainText().count('Hello'), 2)

    def test_gifts_notify_only_when_final_and_new_room_resets_replay_memory(self):
        w = self.window()
        self.live(w)
        w.chat_sound_checkbox.setChecked(True)
        with patch.object(gui.QApplication, 'beep') as beep:
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([gift(201, ended=False)])).messages))
            beep.assert_not_called()
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([gift(201)])).messages))
            beep.assert_called_once()
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([gift(202)])).messages))
            beep.assert_called_once()
            self.live(w, '456')
            self.assertFalse(w._chat_displayed_message_ids)
            w.on_chat_messages((w._chat_generation, chat.decode_response(response([gift(201, room=456)])).messages))
            self.assertEqual(beep.call_count, 2)

    def test_pause_keeps_connection_and_room_change_discards_old_callbacks(self):
        w = self.window()
        self.live(w)
        client = w.chat_client
        token = w._chat_generation
        w.set_stream_state(is_live=True, is_paused=True)
        self.assertIs(w.chat_client, client)
        self.live(w, '456')
        w.on_chat_messages((token, chat.decode_response(response([comment()])).messages))
        w.on_chat_status((token, 'stale'))
        self.assertEqual(w.chat_output.toPlainText(), '')
        self.assertNotEqual(w.chat_status.text(), 'stale')

    def test_comments_are_plain_text_and_reconnect_keeps_history(self):
        w = self.window()
        self.live(w)
        messages = chat.decode_response(response([comment(content='<b>Hello</b>\nnext')])).messages
        w.on_chat_messages((w._chat_generation, messages))
        self.assertIn('Viewer 🎮: <b>Hello</b> next', w.chat_output.toPlainText())
        first = w.chat_client
        w.reconnect_chat()
        self.assertIsNot(first, w.chat_client)
        self.assertIn('Hello', w.chat_output.toPlainText())
        w.clear_chat()
        self.assertEqual(w.chat_output.toPlainText(), '')

    def test_gift_entry_shows_server_count_and_survives_manual_reconnect(self):
        w = self.window()
        self.live(w)
        m = chat.decode_response(response([gift(name='<Rose> 🌹')])).messages
        w.on_chat_messages((w._chat_generation, m))
        self.assertIn('🎁 Viewer 🎮 sent <Rose> 🌹 ×10', w.chat_output.toPlainText())
        w.reconnect_chat()
        w.on_chat_messages((w._chat_generation, m))
        self.assertIn('sent <Rose> 🌹 ×10', w.chat_output.toPlainText())
        self.assertEqual(w.chat_output.toPlainText().count('sent <Rose>'), 1)
        self.live(w, '456')
        self.assertEqual(w.chat_output.toPlainText(), '')
        self.assertEqual(len(w._chat_displayed_gifts), 0)

    def test_chat_uses_separate_pc_transport_for_mobile_room(self):
        w = self.window()
        w.device_type = 'mobile'
        self.live(w)
        with patch.object(gui, 'Stream') as stream:
            w.chat_client.stream_factory()
        self.assertEqual(stream.call_args.kwargs['device_type'], 'pc')
        self.assertEqual(stream.call_args.kwargs['device_profile']['device_id'], '111')

    def test_cookie_change_and_close_discard_old_callbacks(self):
        w = self.window()
        self.live(w)
        previous = w.chat_client
        token = w._chat_generation
        w.set_cookies_path(self.cookies + '.other', save=False, refresh=False)
        self.assertTrue(previous._stop.is_set())
        w.on_chat_status((token, 'old account'))
        self.assertNotEqual(w.chat_status.text(), 'old account')
        client = w.chat_client
        w.close()
        self.assertTrue(client._stop.is_set())

    def test_chat_view_migrates_existing_preferences_and_stays_hidden_if_chosen(self):
        w = self.window()
        w.load_workspace_preferences({'visible_views': ['stats']})
        self.assertIn('chat', w.visible_workspace_views)
        w.set_workspace_view_visible('chat', False)
        w.save_config(False)
        other = self.window()
        self.assertNotIn('chat', other.visible_workspace_views)


if __name__ == '__main__':
    unittest.main()
