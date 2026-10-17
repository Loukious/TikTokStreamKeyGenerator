"""Studio environment priority and account/store regions are independent."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import tests.test_client_modes as modes
from Libs import region_context as regions

gui = modes.gui


class RegionTests(unittest.TestCase):
    setUpClass = classmethod(modes.ModeTests.setUpClass.__func__)

    def setUp(self):
        modes.ModeTests.setUp(self)
        with regions._lock:
            regions._contexts.clear()
        Path(self.cookies).write_text(json.dumps([
            {'name': 'store-country-code', 'value': 'tw'},
            {'name': 'sessionid', 'value': 'fixture-session'},
        ]))

    def stream(self, cookies=None, kind='pc'):
        result = gui.Stream(cookies_path=cookies or self.cookies, device_type=kind,
                            device_profile={'device_id': '111', 'install_id': '222'})
        result._cached_live_studio_version = '1.37.4'
        self.addCleanup(result.s.close)
        return result

    def discover(self, stream, priority='TN', store='TW', account=''):
        with patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                patch.object(stream, '_signed_get_json', return_value={
                    'status_code': 0, 'data': {'priority_region': priority, 'store_region': store}}) as get:
            context = stream._refresh_region_context(device_id='111', install_id='222', account_region=account)
            self.assertTrue(get.call_args.args[0].endswith('/webcast/game/basic/region_check/'))
            return context

    def test_bootstrap_never_assumes_account_country_is_environment(self):
        stream = self.stream()
        self.assertEqual(stream._studio_params()['priority_region'], '')
        self.assertEqual(stream._store_region_headers(), {'x-tt-store-region': 'tw'})
        self.discover(stream)
        self.assertEqual(stream._studio_params()['priority_region'], 'tn')
        self.assertEqual(stream._store_region_headers(), {'x-tt-store-region': 'tw'})
        self.assertEqual(stream._effective_priority_region(' TW '), 'tw')
        self.assertEqual(stream._store_region_headers(), {'x-tt-store-region': 'tw'})
        self.assertNotIn('tw', stream._priority_region_candidates())
        with self.assertRaises(ValueError):
            stream._effective_priority_region('Taiwan')

    def test_cached_regions_follow_session_and_expire(self):
        stream = self.stream()
        self.discover(stream)
        self.assertEqual(self.stream()._effective_priority_region(), 'tn')
        # A different login in the same file must not inherit the old account.
        records = json.loads(Path(self.cookies).read_text())
        records[1]['value'] = 'another-session'
        Path(self.cookies).write_text(json.dumps(records))
        self.assertEqual(self.stream()._effective_priority_region(), '')
        context = regions.cached_context(stream._region_context_key)
        with patch.object(regions.time, 'monotonic', return_value=context.expires_at + 1):
            self.assertEqual(stream._effective_priority_region(), '')

    def test_account_region_wins_header_without_changing_server_priority(self):
        stream = self.stream()
        self.discover(stream, priority='TW', store='CA', account='JP')
        self.assertEqual(stream._effective_priority_region(), 'tw')
        self.assertEqual(stream._store_region_headers(), {'x-tt-store-region': 'jp'})

    def test_heartbeat_signs_priority_query_but_sends_account_header(self):
        stream = self.stream()
        self.discover(stream, priority='TN', store='TW')
        with patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                patch.object(gui, '_build_signature_headers', return_value={}) as sign, \
                patch.object(stream, '_request_json_with_webcast_fallback', return_value={'status_code': 0}) as post:
            stream.anchorHeartbeat('2', device_id='111', install_id='222', room_id='123', stream_id='456')
        request = post.call_args.kwargs
        self.assertEqual(request['params']['priority_region'], 'tn')
        self.assertEqual(request['headers']['x-tt-store-region'], 'tw')
        self.assertEqual(sign.call_args.kwargs['params']['priority_region'], 'tn')
        self.assertEqual(request['headers']['x-ss-stub'], hashlib.md5(request['data']).hexdigest())

    def test_account_refresh_discovers_environment_before_create_info(self):
        stream = self.stream()
        seen = []
        def response(url, **options):
            seen.append((url, dict(options['params'])))
            if '/passport/' in url:
                return {'status_code': 0, 'data': {'region': 'TW', 'username': 'fixture'}}
            if '/region_check/' in url:
                return {'status_code': 0, 'data': {'priority_region': 'TN', 'store_region': 'TW'}}
            return {'status_code': 0, 'data': {}}
        with patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                patch.object(gui, 'build_endpoint', return_value='https://account.test/passport/info'), \
                patch.object(stream, '_signed_get_json', side_effect=response):
            stream.getAccountInfo('111', '222')
        create = [params for url, params in seen if '/create_info/' in url]
        self.assertTrue(create)
        self.assertTrue(all(params['priority_region'] == 'tn' for params in create))

    def test_startup_discovers_missing_context_once_before_room_info(self):
        stream = self.stream()
        calls = []
        def response(url, **options):
            calls.append((url, dict(options['params'])))
            if '/region_check/' in url:
                return {'status_code': 0, 'data': {'priority_region': 'TN', 'store_region': 'TW'}}
            return {'status_code': 0, 'data': {}}
        with patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                patch.object(stream, '_signed_get_json', side_effect=response):
            stream.getCreateRoomInfo('111', '222')
            stream.getCreateRoomInfo('111', '222')
        self.assertEqual(sum('/region_check/' in url for url, _ in calls), 1)
        self.assertTrue(all(params['priority_region'] == 'tn' for url, params in calls if '/create_info/' in url))

    def test_malformed_discovery_preserves_cached_context(self):
        stream = self.stream()
        self.discover(stream)
        with self.assertRaises(ValueError):
            self.discover(stream, priority='alisg')
        self.assertEqual(stream._effective_priority_region(), 'tn')

    def test_stream_retains_discovered_priority_after_cache_expiry(self):
        from tests.gui_helpers import drive_workflow
        stream = self.stream()
        self.discover(stream)
        stream._studio_params()
        stream.streamShareUrl = ''
        window = modes.ModeTests.window(self)
        with patch.object(window, 'sync_realtime_stats_timer'), \
                patch.object(window, 'sync_audience_safety_timer'), patch.object(window, 'sync_chat'):
            drive_workflow(window.apply_stream_outputs(stream, start_proxy=False))
        context = regions.cached_context(stream._region_context_key)
        with patch.object(regions.time, 'monotonic', return_value=context.expires_at + 1):
            self.assertEqual(stream._effective_priority_region(), '')
            self.assertEqual(window.stream_priority_region, 'tn')

    def test_mobile_manual_selection_wins_over_profile_and_auto(self):
        mobile = self.stream(kind='mobile')
        mobile.client.record['request_params']['priority_region'] = 'alisg'
        self.assertNotIn('priority_region', mobile._studio_params())
        mobile.client.record['request_params']['priority_region'] = 'tn'
        self.assertEqual(mobile._studio_params()['priority_region'], 'tn')
        self.discover(mobile, priority='JP', store='TW')
        self.assertEqual(mobile._studio_params()['priority_region'], 'jp')
        self.assertEqual(mobile._studio_params(priority_region=' TW ')['priority_region'], 'tw')
        self.assertEqual(mobile._store_region_headers(), {'x-tt-store-region': 'tw'})
        self.assertEqual(mobile.priority_region_used, 'tw')

    def test_mobile_startup_discovers_using_android_params(self):
        mobile = self.stream(kind='mobile')
        calls = []
        def response(url, **options):
            calls.append((url, dict(options['params'])))
            if '/region_check/' in url:
                return {'status_code': 0, 'data': {'priority_region': 'TN', 'store_region': 'TW'}}
            return {'status_code': 0, 'data': {}}
        with patch.object(mobile, 'getServerUrl', return_value='https://webcast.test/'), \
                patch.object(mobile, '_signed_get_json', side_effect=response), \
                patch.object(mobile, '_request_json_with_webcast_fallback', return_value={}) as post:
            mobile.getCreateRoomInfo('111', '222')
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith('/region_check/'))
        self.assertTrue(all(p['device_platform'] == 'android' and p['aid'] == '1233' for _, p in calls))
        self.assertEqual(post.call_args.args[0], 'POST')
        self.assertTrue(post.call_args.args[1].endswith('/room/create_info/'))
        self.assertEqual(post.call_args.kwargs['params']['priority_region'], 'tn')

    def test_mobile_does_not_reuse_studio_context(self):
        self.discover(self.stream())
        mobile = self.stream(kind='mobile')
        self.assertEqual(mobile._effective_priority_region(), '')
        self.discover(mobile, priority='JP', store='TW')
        self.assertEqual(mobile._effective_priority_region(), 'jp')
        self.assertEqual(self.stream()._effective_priority_region(), 'tn')


if __name__ == '__main__':
    unittest.main()
