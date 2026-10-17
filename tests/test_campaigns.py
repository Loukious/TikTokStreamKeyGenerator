"""Offline campaign contracts and GUI tests; no real cookies or network."""
from tests.gui_helpers import wait_until
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from tests import test_client_modes as base
from Libs.campaigns import Campaign, CampaignFormatError, campaign_url, normalize_campaigns, visit_request
from Libs.campaign_ui import CampaignsDialog
from Libs.campaign_cache import load_viewed_ids, save_viewed_ids

gui = base.gui


class CampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = base.QApplication.instance() or base.QApplication([])

    def setUp(self):
        base.ModeTests.setUp(self)

    def stream(self, kind='pc'):
        stream = gui.Stream(cookies_path=self.cookies, device_type=kind,
                            device_profile={'device_id': '111', 'install_id': '222'})
        self.addCleanup(stream.s.close)
        stream._cached_live_studio_version = '1.0.0'
        return stream

    def card_response(self):
        return {'status_code': 0, 'data': {'PackData': {'CardInfoList': [
            {'ActivityIDV2': '123', 'Title': 'Campaign A', 'SubTitle': 'Details',
             'SchemaURL': 'https://www.tiktok.com/campaign?activityId=123',
             'CampaignCenterCardExtra': {'Tag': 1}, 'StartTime': 10, 'EndTime': 5000},
            {'ActivityIDV2': '456', 'Title': 'Campaign B', 'CampaignCenterCardExtra': {'Tag': 6}},
            {'Title': 'Information banner'},
        ]}}}



    def test_center_states_and_dedup_preserve_distinct_resources(self):
        response = self.card_response()
        cards = response['data']['PackData']['CardInfoList']
        cards.extend([dict(cards[0]), {**cards[0], 'ResourceID': 'other'}])
        campaigns = normalize_campaigns(response, now=100)
        self.assertEqual(len(campaigns), 4)
        self.assertEqual([c.state for c in campaigns[:2]], ['Ongoing', 'Agency upcoming'])
        self.assertEqual(campaigns[2].activity_id, '')

    def test_schema_unwrap_and_id_extraction_reject_external_launches(self):
        schema = 'sslocal://webcast_webview?url=https%3A%2F%2Fwww.tiktok.com%2Fcampaign%3FactivityId%3D123'
        self.assertEqual(campaign_url(schema), 'https://www.tiktok.com/campaign?activityId=123')
        for url in ('javascript:alert(1)', 'https://tiktok.com.attacker.test/', 'https://attacker.test/',
                    'file:///C:/test', 'http://www.tiktok.com/campaign'):
            self.assertEqual(campaign_url(url), '')
        campaign = normalize_campaigns({'data': {'cards': [{'schema_url': schema, 'title': 'Test'}]}}, now=1)[0]
        self.assertEqual(campaign.activity_id, '123')

    def test_empty_supported_list_is_valid_but_unknown_schema_is_error(self):
        self.assertEqual(normalize_campaigns({'data': {'PackData': {'CardInfoList': []}}}, now=1), [])
        for response in ({}, {'data': {}}, {'data': {'cards': None}}):
            with self.assertRaises(CampaignFormatError):
                normalize_campaigns(response, now=1)

    def test_visit_matches_frontend_contract_seconds_and_prefix(self):
        params, payload = visit_request('123', '99', 1700000000, '1233')
        self.assertEqual(params, {'activity': 'op_component-open-2-123', 'aid': '1233'})
        self.assertEqual(payload, {'event_type': 'visit_specific_campaign_page', 'user_id': '99',
                                   'event_time': 1700000000, 'event_data': {}})
        for activity, user in [('', '99'), ('*', '99'), ('op_component-open-2-1', '99'), ('123', ''),
                               ('123', '0'), ('１２３', '99')]:
            with self.assertRaises(ValueError):
                visit_request(activity, user, 1, '8311')

    def test_list_uses_selected_profile_and_never_posts(self):
        for kind, prefix, aid in [('pc', 'ls/', '8311'), ('mobile', '', '1233')]:
            with self.subTest(kind=kind):
                stream = self.stream(kind)
                with patch.object(stream, '_campaign_account_id', return_value='99'), \
                     patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                     patch.object(stream, '_signed_get_json', return_value=self.card_response()) as get, \
                     patch.object(stream, '_signed_post_json') as post:
                    result = stream.getCampaigns()
                self.assertEqual(result['user_id'], '99')
                self.assertEqual(len(result['campaigns']), 3)
                self.assertTrue(get.call_args.args[0].endswith(prefix + 'get_campaign_center_page_data/'))
                params = get.call_args.kwargs['params']
                self.assertEqual(params['aid'], aid)
                self.assertEqual(json.loads(params['UserBase'])['UserID'], '99')
                self.assertEqual(params['EnterFromScene'], '2')
                self.assertEqual(get.call_args.kwargs['extra_headers']['campaign-center-lang'], 'en')
                self.assertEqual(params['device_platform'], 'android' if kind == 'mobile' else 'windows')
                self.assertNotIn('install_id' if kind == 'mobile' else 'iid', params)
                post.assert_not_called()

    def test_pc_legacy_fallback_only_for_unsupported_contract(self):
        stream = self.stream()
        legacy = {'status_code': 0, 'data': {'cards': []}}
        with patch.object(stream, '_campaign_account_id', return_value='99'), \
             patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
             patch.object(stream, '_signed_get_json', side_effect=[{'data': {}}, legacy]) as get:
            self.assertEqual(stream.getCampaigns()['campaigns'], [])
            self.assertTrue(get.call_args.args[0].endswith('/ls/pack_data/'))
            self.assertNotIn('UserBase', get.call_args.kwargs['params'])
        for error in (gui.WebcastError('Auth', status_code=403),
                      {'status_code': 1001, 'data': {'message': 'Not allowed'}}):
            with patch.object(stream, '_campaign_account_id', return_value='99'), \
                 patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                 patch.object(stream, '_signed_get_json', side_effect=[error]) as get:
                with self.assertRaises(gui.WebcastError):
                    stream.getCampaigns()
                self.assertEqual(get.call_count, 1)

    def test_mobile_unknown_list_contract_never_uses_pc_endpoint(self):
        stream = self.stream('mobile')
        with patch.object(stream, '_campaign_account_id', return_value='99'), \
             patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
             patch.object(stream, '_signed_get_json', return_value={'data': {}}) as get:
            with self.assertRaises(CampaignFormatError):
                stream.getCampaigns()
        self.assertEqual(get.call_count, 1)

    def test_account_lookup_has_profile_specific_aid_and_rejects_missing_identity(self):
        for kind, aid in [('pc', '8311'), ('mobile', '1233')]:
            stream = self.stream(kind)
            with patch.object(gui, 'build_endpoint', return_value='https://api.test/passport/account/info/v2/'), \
                 patch.object(stream, '_signed_get_json', return_value={'data': {'user_id_str': '99'}}) as get:
                self.assertEqual(stream._campaign_account_id(), '99')
                self.assertEqual(get.call_args.kwargs['params']['aid'], aid)
            with patch.object(gui, 'build_endpoint', return_value='https://api.test/'), \
                 patch.object(stream, '_signed_get_json', return_value={'data': {}}):
                with self.assertRaises(RuntimeError):
                    stream._campaign_account_id()

    def test_view_blocks_changed_cookie_account_before_post(self):
        stream = self.stream()
        with patch.object(stream, '_campaign_account_id', return_value='100'), \
             patch.object(stream, '_signed_post_json') as post:
            with self.assertRaisesRegex(RuntimeError, 'different account'):
                stream.reportCampaignView('123', expected_user_id='99')
        post.assert_not_called()

    def test_pc_view_serializes_one_signed_post_without_redirect_or_fallback(self):
        stream = self.stream()
        with patch.object(stream, '_campaign_account_id', return_value='99'), \
             patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
             patch.object(gui, 'get_synced_unix_seconds', return_value=1700000000), \
             patch.object(gui, '_build_signature_headers', return_value={'x-test-signature': 'test'}) as sign, \
             patch.object(stream, '_request_json', return_value={'status_code': 0}) as post, \
             patch.object(stream, '_request_json_with_webcast_fallback') as fallback:
            stream.reportCampaignView('123', expected_user_id='99')
        fallback.assert_not_called()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args, ('POST', 'https://webcast.test/webcast/activity/event/'))
        options = post.call_args.kwargs
        self.assertFalse(options['allow_redirects'])
        self.assertEqual(options['params']['aid'], '8311')
        self.assertEqual(json.loads(options['data'])['event_time'], 1700000000)
        self.assertEqual(options['headers']['x-ss-stub'], hashlib.md5(options['data']).hexdigest())
        self.assertEqual(sign.call_args.kwargs['x_ss_stub'], options['headers']['x-ss-stub'])

    def test_mobile_view_signs_exact_url_and_body_with_mobile_identity(self):
        stream = self.stream('mobile')
        response = Mock(status_code=200)
        response.json.return_value = {'status_code': 0}
        response.headers = {}
        with patch.object(stream, '_campaign_account_id', return_value='99'), \
             patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
             patch.object(gui, '_build_signature_headers', return_value={'x-argus': 'stale'}), \
             patch.object(gui, 'attach_webcast_ntp_t0', return_value=1), \
             patch.object(gui, 'update_ntp_from_response'), patch.object(gui, '_audit_webcast_request'), \
             patch.object(stream.client, 'signature_headers', return_value={'x-argus': 'mobile'}) as sign, \
             patch.object(stream.s, 'request', return_value=response) as post:
            stream.reportCampaignView('123', expected_user_id='99')
        self.assertEqual(post.call_count, 1)
        request = post.call_args.kwargs
        query = parse_qs(urlsplit(request['url']).query)
        self.assertEqual(query['aid'], ['1233'])
        self.assertEqual(query['device_id'], ['111'])
        self.assertEqual(query['iid'], ['222'])
        self.assertNotIn('install_id', query)
        self.assertEqual(request['headers']['x-argus'], 'mobile')
        self.assertFalse(request['allow_redirects'])
        self.assertEqual(sign.call_args.kwargs['url'], request['url'])
        self.assertEqual(sign.call_args.kwargs['body'], request['data'])

    def test_view_error_is_not_retried_or_reported_as_success(self):
        stream = self.stream()
        for response in ({}, {'status_code': 7}, {'status_code': gui.ROOM_IS_LIVING_CODE}):
            with patch.object(stream, '_campaign_account_id', return_value='99'), \
                 patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
                 patch.object(gui, '_build_signature_headers', return_value={}), \
                 patch.object(stream, '_request_json', return_value=response) as post:
                with self.assertRaises((RuntimeError, gui.WebcastError)):
                    stream.reportCampaignView('123', expected_user_id='99')
                self.assertEqual(post.call_count, 1)

    def test_view_timeout_is_propagated_after_one_post(self):
        stream = self.stream()
        with patch.object(stream, '_campaign_account_id', return_value='99'), \
             patch.object(stream, 'getServerUrl', return_value='https://webcast.test/'), \
             patch.object(gui, '_build_signature_headers', return_value={}), \
             patch.object(stream, '_request_json', side_effect=base.requests.Timeout('Unconfirmed')) as post, \
             patch.object(stream, '_request_json_with_webcast_fallback') as fallback:
            with self.assertRaises(base.requests.Timeout):
                stream.reportCampaignView('123', expected_user_id='99')
        self.assertEqual(post.call_count, 1)
        fallback.assert_not_called()

    def dialog(self):
        dialog = CampaignsDialog(Mock(), kind='mobile', auto_refresh=False,
                                 viewed_cache_path=str(Path(self.temp.name) / 'campaign_views.json'))
        self.addCleanup(dialog.close)
        wait_until(lambda: not dialog.busy)
        return dialog

    def test_gui_filters_and_banner_clicks_do_not_send(self):
        dialog = self.dialog()
        dialog.on_completed('list', {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)})
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertFalse(hasattr(dialog, 'details'))
        self.assertFalse(hasattr(dialog, 'open_button'))
        dialog.state.setCurrentText('Agency upcoming')
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.selected_campaign().activity_id, '456')
        dialog.state.setCurrentText('All states')
        dialog.search.setText('Information')
        self.assertEqual(dialog.table.rowCount(), 1)
        with patch.object(dialog, '_run') as run:
            dialog.table.cellDoubleClicked.emit(0, 0)
            run.assert_not_called()
        dialog.search.setText('does not exist')
        self.assertEqual(dialog.table.rowCount(), 0)
        self.assertFalse(dialog.view_button.isEnabled())

    def test_gui_single_click_selects_and_double_click_reports_once(self):
        dialog = self.dialog()
        stream = Mock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        dialog.stream_factory = Mock(return_value=stream)
        stream.getCampaigns.return_value = {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)}
        pending = []
        class Thread:
            def __init__(self, target, daemon):
                pending.append(target)
            def start(self):
                pass
        with patch('Libs.campaign_ui.threading.Thread', Thread):
            dialog.refresh()
            dialog.refresh()
            self.assertEqual(len(pending), 1)
            self.assertFalse(dialog.close_button.isEnabled())
            pending.pop()()
            stream.reportCampaignView.assert_not_called()
            dialog.table.cellClicked.emit(0, 0)
            dialog.table.cellActivated.emit(0, 0)
            self.assertEqual(len(pending), 0)
            stream.reportCampaignView.assert_not_called()
            dialog.table.cellDoubleClicked.emit(0, 0)
            dialog.table.cellActivated.emit(0, 0)
            dialog.table.cellDoubleClicked.emit(0, 0)
            self.assertEqual(len(pending), 1)
            self.assertFalse(dialog.view_button.isEnabled())
            pending.pop()()
            self.assertEqual(dialog.table.item(0, 5).text(), 'Yes')
            dialog.table.cellDoubleClicked.emit(0, 0)
            self.assertEqual(len(pending), 0)
            dialog.filter_campaigns()
            self.assertEqual(dialog.table.item(0, 5).text(), 'Yes')
            self.assertEqual(len(pending), 0)
        stream.reportCampaignView.assert_called_once_with('123', expected_user_id='99', priority_region='')

    def test_double_click_without_page_marks_the_clicked_row(self):
        dialog = self.dialog()
        dialog.on_completed('list', {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)})
        self.assertEqual(dialog.selected_campaign().activity_id, '123')
        with patch.object(dialog, '_run') as run:
            dialog.table.cellDoubleClicked.emit(1, 0)
            self.assertEqual(dialog.selected_campaign().activity_id, '456')
            stream = Mock()
            self.assertEqual(run.call_args.args[1](stream), ('99', '456'))
            stream.reportCampaignView.assert_called_once_with('456', expected_user_id='99', priority_region='')

    def test_gui_error_restores_controls_and_refresh_failure_invalidates_old_account(self):
        dialog = self.dialog()
        result = {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)}
        dialog.on_completed('list', result)
        dialog.busy = True
        dialog.on_failed('view', 'Timeout')
        self.assertFalse(dialog.busy)
        self.assertTrue(dialog.refresh_button.isEnabled())
        self.assertIn('not retried automatically', dialog.status.text())
        self.assertEqual(dialog.table.item(0, 5).text(), '')
        self.assertEqual(load_viewed_ids(dialog.viewed_cache_path), set())
        self.assertTrue(dialog.table.isEnabled())
        dialog.on_failed('list', 'Login expired')
        self.assertEqual(dialog.user_id, '')
        self.assertEqual(dialog.table.rowCount(), 0)
        with patch.object(dialog, '_run') as run:
            dialog.send_view()
            run.assert_not_called()

    def test_view_button_marks_selected_campaign(self):
        dialog = self.dialog()
        dialog.on_completed('list', {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)})
        with patch.object(dialog, '_run') as run:
            dialog.view_button.click()
            self.assertEqual(run.call_args.args[0], 'view')
            stream = Mock()
            self.assertEqual(run.call_args.args[1](stream), ('99', '123'))
            stream.reportCampaignView.assert_called_once_with('123', expected_user_id='99', priority_region='')

    def test_view_cache_survives_reopen_and_is_scoped_to_account(self):
        result = {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)}
        first = self.dialog()
        first.on_completed('list', result)
        first.on_completed('view', ('99', '123'))
        wait_until(lambda: not first.busy)
        reopened = self.dialog()
        reopened.on_completed('list', result)
        self.assertEqual(reopened.table.item(0, 5).text(), 'Yes')
        self.assertFalse(reopened.view_button.isEnabled())
        with patch.object(reopened, '_run') as run:
            reopened.table.cellDoubleClicked.emit(0, 0)
            run.assert_not_called()
            reopened.on_completed('list', {**result, 'user_id': '100'})
            self.assertEqual(reopened.table.item(0, 5).text(), '')
            reopened.table.cellDoubleClicked.emit(0, 0)
            run.assert_called_once()
        first.on_failed('view', 'Unconfirmed')
        self.assertEqual(load_viewed_ids(first.viewed_cache_path), {('99', '123')})

    def test_view_cache_merges_and_ignores_invalid_entries(self):
        path = Path(self.temp.name) / 'nested' / 'campaign_views.json'
        save_viewed_ids(path, {('99', '123')})
        save_viewed_ids(path, {('100', '456')})
        self.assertEqual(load_viewed_ids(path), {('99', '123'), ('100', '456')})
        path.write_text(json.dumps({'version': 1, 'viewed': {
            '99': ['123', 456, '0', 'abc', '１２３'], '100': '456', 'bad': ['123']}}))
        self.assertEqual(load_viewed_ids(path), {('99', '123')})
        path.write_text('{invalid json')
        self.assertEqual(load_viewed_ids(path), set())
        save_viewed_ids(path, {('99', '456')})
        self.assertEqual(load_viewed_ids(path), {('99', '456')})

    def test_view_cache_write_failure_keeps_confirmed_view_in_session(self):
        dialog = self.dialog()
        dialog.on_completed('list', {'user_id': '99', 'campaigns': normalize_campaigns(self.card_response(), now=100)})
        with patch('Libs.campaign_ui.save_viewed_ids', side_effect=OSError('Read-only')):
            dialog.on_completed('view', ('99', '123'))
            wait_until(lambda: not dialog.busy)
        self.assertEqual(dialog.table.item(0, 5).text(), 'Yes')
        self.assertIn('only for this session', dialog.status.text())
        self.assertFalse(dialog.view_button.isEnabled())
        self.assertEqual(load_viewed_ids(dialog.viewed_cache_path), set())

    def test_atomic_cache_failure_preserves_saved_views(self):
        path = Path(self.temp.name) / 'campaign_views.json'
        save_viewed_ids(path, {('99', '123')})
        with patch('Libs.campaign_cache.os.replace', side_effect=OSError('Read-only')):
            with self.assertRaises(OSError):
                save_viewed_ids(path, {('99', '456')})
        self.assertEqual(load_viewed_ids(path), {('99', '123')})
        self.assertEqual(list(path.parent.glob('campaign_views.json.*.tmp')), [])

    def test_main_window_has_campaign_menu_and_cookie_enablement(self):
        window = base.ModeTests.window(self)
        window.update_stream_controls(has_cookies=False)
        self.assertFalse(window.campaigns_button.isEnabled())
        window.is_live = True
        window.update_stream_controls(has_cookies=True)
        self.assertTrue(window.campaigns_button.isEnabled())

    def test_main_dialog_factory_keeps_selected_android_context(self):
        window = base.ModeTests.window(self)
        window.device_type_combo.setCurrentIndex(1)
        window.device_id, window.install_id = '333', '444'
        with patch.object(window, 'get_cookie_file_status', return_value=(True, 'Ready')), \
             patch.object(window, 'ensure_device_identifiers', return_value=True), \
             patch.object(gui, 'CampaignsDialog') as dialog, patch.object(gui, 'Stream') as stream:
            window.open_campaigns()
            self.assertEqual(dialog.call_args.kwargs['kind'], 'mobile')
            self.assertEqual(dialog.call_args.kwargs['viewed_cache_path'],
                             str(Path(self.path).with_name('campaign_views.json')))
            factory = dialog.call_args.args[0]
            # The modal normally prevents edits, but even a later state change
            # must not change the identity of its asynchronous requests.
            window.device_type = 'pc'
            window.device_id, window.install_id = '111', '222'
            factory()
            options = stream.call_args.kwargs
            self.assertEqual(options['device_type'], 'mobile')
            self.assertEqual(options['device_profile']['device_id'], '333')
            self.assertEqual(options['device_profile']['install_id'], '444')
            self.assertEqual(options['cookies_path'], self.cookies)


if __name__ == '__main__':
    unittest.main()
