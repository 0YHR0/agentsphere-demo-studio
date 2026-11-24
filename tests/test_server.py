import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from studio.config import Config
from studio.engine import Engine
from studio.server import handler_for


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.tmp.name))
        self.engine = Engine(self.config)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.engine, 'test-csrf'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        opts = {'Content-Type': 'application/json', 'X-Studio-CSRF': 'test-csrf', **(headers or {})}
        req = urllib.request.Request(self.url + path,
            data=json.dumps(body).encode() if body is not None else None, headers=opts)
        try:
            r = self.opener.open(req)
        except urllib.error.HTTPError as exc:
            r = exc
        return r.code, json.loads(r.read())

    def test_no_credentials_in_state(self):
        status, data = self.call('/api/config', {'api_key': 'private-fixture'})
        self.assertEqual(200, status)
        self.assertNotIn('private-fixture', json.dumps(data))
        status, data = self.call('/api/state')
        self.assertNotIn('private-fixture', json.dumps(data))
        self.assertIs(True, data['config']['api_key_configured'])

    def test_cross_origin_and_missing_csrf_rejected(self):
        status, _ = self.call('/api/config', {}, {'Origin': 'https://example.com'})
        self.assertEqual(403, status)
        status, _ = self.call('/api/config', {}, {'X-Studio-CSRF': ''})
        self.assertEqual(403, status)

    def test_no_private_file_serving(self):
        for path in ('/.local/config.json', '/.env', '/studio/config.py', '/../../.env'):
            status, _ = self.call(path)
            self.assertEqual(404, status)

    def test_scene_save_preserves_secret_and_never_runs_cloud_action(self):
        self.config.save({'api_key': 'cloud-fixture', 'model_api_key': 'model-fixture'})
        status, data = self.call('/api/scenario-config', {
            'case': 'openclaw_task', 'values': {'model_api_key': '',
                'model_base_url': 'https://model.example.com/v1', 'model_id': 'demo-model',
                'openclaw_cli': 'openclaw', 'openclaw_user': 'sandbox'}})
        self.assertEqual(200, status)
        self.assertTrue(data['model_api_key_configured'])
        self.assertNotIn('model-fixture', json.dumps(data))
        self.assertEqual('model-fixture', self.config.data['model_api_key'])
        self.assertEqual('cloud-fixture', self.config.data['api_key'])
        self.assertEqual([], self.engine.state['jobs'])

    def test_scene_fields_are_scoped_and_build_target_requires_pair(self):
        for case, values in [('build_logs', {'model_api_key': 'wrong-scope'}),
                             ('openclaw_probe', {'api_key': 'wrong-scope'}),
                             ('build_logs', {'build_log_template_id': '00000000-0000-4000-8000-000000000001'})]:
            status, _ = self.call('/api/scenario-config', {'case': case, 'values': values})
            self.assertEqual(400, status)
        values = {'build_log_template_id': '00000000-0000-4000-8000-000000000001',
                  'build_log_build_id': '00000000-0000-4000-8000-000000000002'}
        status, _ = self.call('/api/scenario-config', {'case': 'build_logs', 'values': values})
        self.assertEqual(200, status)
        status, _ = self.call('/api/scenario-config', {'case': 'build_logs', 'values': {
            'build_log_template_id': '', 'build_log_build_id': ''}})
        self.assertEqual(200, status)
        self.assertEqual('', self.config.data['build_log_template_id'])

    def test_catalog_and_plan_need_no_cloud_access(self):
        status, data = self.call('/api/catalog')
        self.assertEqual(200, status)
        from studio.core.registry import get_registry
        self.assertEqual(len(get_registry().actions), len(data))
        self.assertTrue({'openclaw', 'vpc', 'miles_rl'} <= {r['package'] for r in data if r['kind']=='scenario'})
        status, data = self.call('/api/case/persisted')
        self.assertEqual(200, status)
        self.assertIn('暂停', ' '.join(data['plan']['steps']))
        self.assertIn('driver.read', data['code'])
        self.assertEqual([], self.engine.state['jobs'])

    def test_every_registered_case_has_real_source_and_plan(self):
        from studio.core.registry import get_registry
        for case in get_registry().actions:
            status, result = self.call('/api/case/'+case)
            self.assertEqual(200, status, case)
            self.assertTrue(result['code'], case)
            self.assertTrue(result['plan']['steps'], case)
        self.assertEqual([], self.engine.state['jobs'])

    def test_package_metadata_and_vpc_settings_are_generic(self):
        status, packages = self.call('/api/packages')
        self.assertEqual(200,status)
        self.assertTrue({'basic','health','openclaw','vpc','miles_rl'} <= {p['id'] for p in packages})
        status, scenarios = self.call('/api/scenarios')
        self.assertTrue({'openclaw','vpc','miles_rl'} <= {p['id'] for p in scenarios})
        status, _ = self.call('/api/scenario-config',{'case':'vpc_prepare','values':{'vpc_http_url':'http://192.168.1.10/health'}})
        self.assertEqual(200,status)
        status, _ = self.call('/api/scenario-config',{'case':'vpc_prepare','values':{'api_key':'wrong-scope'}})
        self.assertEqual(400,status)
        self.assertEqual([],self.engine.state['jobs'])

    def test_optional_visualizer_is_registered_and_script_is_safely_served(self):
        status, scenarios=self.call('/api/scenarios')
        self.assertEqual(200,status)
        self.assertNotIn('cpu_rl',{s['id'] for s in scenarios})
        self.assertEqual('order_router',next(s for s in scenarios if s['id']=='order_reports')['visualizer'])
        response=self.opener.open(self.url+'/order-reports.js')
        self.assertEqual(200,response.status)
        self.assertIn('script-src',response.headers.get('Content-Security-Policy',''))
        self.assertNotIn("'unsafe-inline'",response.headers.get('Content-Security-Policy',''))
        self.assertEqual(200,self.opener.open(self.url+'/order-reports.css').status)
        self.assertEqual(404,self.call('/cpu-rl.js')[0])
        self.assertEqual(404,self.call('/api/case/cpu_prepare')[0])
        self.assertEqual([],self.engine.state['jobs'])

    def test_report_preserves_failure_and_redacts_credentials(self):
        self.config.save({'api_key':'private-report-fixture'})
        self.engine.state['jobs']=[{'case':'pause','mode':'run','status':'failed','error':'504 private-report-fixture'}]
        status, report = self.call('/api/report')
        self.assertEqual(200,status)
        self.assertEqual(1,report['summary']['failed'])
        self.assertNotIn('private-report-fixture',json.dumps(report))
        response=self.opener.open(self.url+'/api/report.md')
        text=response.read().decode('utf-8')
        self.assertIn('failed',text)
        self.assertIn('504',text)
        self.assertNotIn('private-report-fixture',text)


if __name__ == '__main__':
    unittest.main()
