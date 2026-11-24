import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from studio.config import Config, redact
from studio.engine import Engine


class FakeSDK:
    """A deterministic cloud model used only by tests, never by the application."""
    def __init__(self, config):
        self.config = config
        self.sandboxes, self.templates, self.files = {}, {}, {}
        self.events = []
        self.created_references = []

    def template(self, tid):
        if tid == self.config['ready_template_id'].split(':')[0] or tid in self.templates:
            return {'gatewayID': self.config['gateway_id'], 'builds': [
                {'status': 'ready', 'buildID': 'own-build' if tid in self.templates else '00000000-0000-4000-8000-000000000003'}]}

    def create_template(self):
        resource = {'template_id': 'own-template', 'build_id': 'own-build', 'name': 'test', 'owned': True}
        self.templates['own-template'] = resource
        self.events.append('create_template')
        return resource

    def submit_build(self, resource):
        self.events.append('submit_build')

    def build_logs(self, resource):
        return {**resource, 'status': 'ready', 'log_entries': []}

    def create_sandbox(self, tid):
        self.created_references.append(tid)
        sid = 'own-sandbox-' + str(len(self.sandboxes))
        self.sandboxes[sid] = {'sandboxID': sid, 'state': 'running'}
        self.events.append(('create', sid))
        return sid

    def sandbox_detail(self, sid):
        return self.sandboxes.get(sid)

    def has_handle(self, sid):
        return False

    def pause(self, sid):
        self.sandboxes[sid]['state'] = 'paused'
        self.events.append(('pause', sid))

    def resume(self, sid):
        self.sandboxes[sid]['state'] = 'running'
        self.events.append(('resume', sid))
        return {'stdout': 'resumed-ok'}

    def write(self, sid, path, data, **opts):
        self.files[(sid, path)] = data

    def read(self, sid, path, **opts):
        return self.files[(sid, path)]

    def delete_sandbox(self, sid):
        self.events.append(('delete_sandbox', sid))
        self.sandboxes.pop(sid, None)
        return {'sandbox_id': sid, 'detail_http': 404}

    def delete_template(self, tid):
        self.events.append(('delete_template', tid))
        self.templates.pop(tid, None)
        return {'template_id': tid, 'detail_http': 404}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Config(Path(self.tmp.name))
        self.config.save({'api_key': 'test-key-private',
                          'image': 'example.invalid/openclaw:demo',
                          'gateway_id': '00000000-0000-4000-8000-000000000001',
                          'gateway_url': 'https://gateway.example.com',
                          'ready_template_id': '00000000-0000-4000-8000-000000000002'})
        self.driver = FakeSDK(self.config.data)
        self.engine = Engine(self.config, lambda c: self.driver)

    def test_direct_persistence_preserves_same_id(self):
        self.engine.prepare('persisted', self.driver)
        result = self.engine.execute('persisted', self.driver)
        sid = result['sandbox_id']
        self.assertTrue(result['binary_preserved'])
        self.assertEqual([('create', sid), ('pause', sid), ('resume', sid)], self.driver.events)
        self.assertEqual([], self.engine.state['templates'])

    def test_resume_can_be_selected_first(self):
        self.engine.prepare('resume', self.driver)
        resource = self.engine.resource('sandbox')
        self.assertEqual('paused', resource['state'])
        result = self.engine.execute('resume', self.driver)
        self.assertEqual(resource['sandbox_id'], result['same_sandbox_id'])
        self.assertEqual('running', resource['state'])

    def test_corruption_is_failure(self):
        self.engine.prepare('persisted', self.driver)
        files = self.engine.state['files']
        self.driver.files[(files['sandbox_id'], files['binary_path'])] = b'corrupted'
        with self.assertRaisesRegex(RuntimeError, 'SHA256'):
            self.engine.execute('persisted', self.driver)

    def test_disappeared_during_resume_not_recreated(self):
        self.engine.prepare('resume', self.driver)
        sid = self.engine.resource('sandbox')['sandbox_id']
        self.driver.sandboxes.pop(sid)
        with self.assertRaises(Exception):
            self.engine.execute('resume', self.driver)
        self.assertEqual(1, len(self.engine.state['sandboxes']))

    def test_cleanup_never_deletes_external_template(self):
        self.engine.prepare('command', self.driver)
        self.engine.prepare('template_build', self.driver)
        result = self.engine.cleanup(self.driver)
        self.assertTrue(result['external_templates_preserved'])
        ids = [e[1] for e in self.driver.events if isinstance(e, tuple) and e[0].startswith('delete')]
        self.assertNotIn(self.config.data['ready_template_id'], ids)
        self.assertEqual('delete_sandbox', self.driver.events[-2][0])
        self.assertEqual('delete_template', self.driver.events[-1][0])

    def test_config_and_output_hide_secrets(self):
        public = self.engine.snapshot()
        self.assertTrue(public['config']['api_key_configured'])
        self.assertNotIn('test-key-private', json.dumps(public))
        self.assertEqual('[REDACTED]', self.engine.safe('test-key-private'))
        self.assertEqual('[REDACTED]', redact({'envdAccessToken': 'token'})['envdAccessToken'])

    def test_ownership_guard(self):
        with self.assertRaisesRegex(RuntimeError, '自有资源'):
            self.engine.own('sandbox', {'sandbox_id': 'external', 'owned': True})

    def test_missing_version_after_restart_is_explicit_new_preparation(self):
        resource = self.engine.running(self.driver)
        old = resource['sandbox_id']
        self.driver.sandboxes[old]['envdVersion'] = ''
        new = self.engine.running(self.driver)
        self.assertNotEqual(old, new['sandbox_id'])
        self.assertFalse(resource.get('deleted', False))
        self.assertEqual(2, len(self.engine.state['sandboxes']))

    def test_engine_reuses_official_driver_between_jobs(self):
        count = []
        self.engine.driver_factory = lambda config: (count.append(1) or self.driver)
        for _ in range(2):
            self.engine.start('template_create')
            deadline = time.monotonic() + 3
            while self.engine.job and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual('passed', self.engine.state['jobs'][-1]['status'])
        self.assertEqual(1, len(count))

    def test_manual_build_reference_is_preserved_and_resource_keeps_base_id(self):
        tid = self.config.data['ready_template_id']
        bid = '00000000-0000-4000-8000-000000000003'
        self.config.save({'ready_template_id': tid + ':' + bid})
        resource = self.engine.running(self.driver)
        self.assertEqual([tid + ':' + bid], self.driver.created_references)
        self.assertEqual(tid, resource['template_id'])
        self.assertEqual(bid, resource['build_id'])

    def test_requested_non_ready_build_never_falls_back(self):
        tid = self.config.data['ready_template_id']
        self.config.save({'ready_template_id': tid + ':00000000-0000-4000-8000-000000000099'})
        with self.assertRaisesRegex(RuntimeError, '指定的 Build'):
            self.engine.running(self.driver)
        self.assertEqual([], self.driver.created_references)

    def test_bare_template_resolves_latest_ready_build_not_latest_failed(self):
        tid = self.config.data['ready_template_id']
        self.driver.template = lambda _: {'gatewayID': self.config.data['gateway_id'], 'builds': [
            {'buildID': 'failed-newest', 'status': 'error', 'createdAt': '2026-10-20T03:00:00Z'},
            {'buildID': 'ready-old', 'status': 'ready', 'createdAt': '2026-10-20T01:00:00Z'},
            {'buildID': 'ready-new', 'status': 'Ready', 'createdAt': '2026-10-20T02:00:00Z'}]}
        self.engine.running(self.driver)
        self.assertEqual([tid + ':ready-new'], self.driver.created_references)

    def test_execution_overrides_are_job_scoped_and_do_not_leak(self):
        self.driver.c = dict(self.config.data)
        self.engine.execute = lambda case, driver: {
            k: driver.c[k] for k in ('command_user', 'command_cwd')}
        original = {k: self.config.data[k] for k in ('command_user', 'command_cwd')}
        override = {'command_user': 'sandbox', 'command_cwd': '/tmp'}
        for execution, expected in ((override, override), ({}, original)):
            self.engine.start('command', execution=execution)
            deadline = time.monotonic() + 3
            while self.engine.job and time.monotonic() < deadline:
                time.sleep(.01)
            job = self.engine.state['jobs'][-1]
            self.assertEqual('passed', job['status'])
            self.assertEqual(expected, job['result'])
            self.assertEqual(original, {k: self.driver.c[k] for k in original})
            self.assertEqual(original, {k: self.config.data[k] for k in original})

    def test_invalid_or_unrelated_execution_options_rejected_before_work(self):
        for case, options in [('command', {'command_cwd': 'relative'}),
                              ('command', {'command_user': ''}),
                              ('command', {'api_key': 'bad'}),
                              ('template_create', {'command_user': 'root'})]:
            with self.assertRaises(ValueError):
                self.engine.start(case, execution=options)
        self.assertEqual([], self.driver.events)

    def test_source_mode_build_ignores_previously_saved_ready_template(self):
        self.config.save({'template_source': 'build'})
        self.engine.running(self.driver)
        self.assertEqual(['own-template:own-build'], self.driver.created_references)
        self.assertIn('submit_build', self.driver.events)

    def test_source_mode_existing_requires_id_and_does_not_build_silently(self):
        self.config.save({'template_source': 'existing', 'ready_template_id': ''})
        with self.assertRaisesRegex(RuntimeError, '填写已构建模板'):
            self.engine.running(self.driver)
        self.assertEqual([], self.driver.events)

    def test_source_mode_both_uses_existing_ready_build_for_sandbox(self):
        self.config.save({'template_source': 'both'})
        self.engine.running(self.driver)
        self.assertTrue(self.driver.created_references[0].startswith(self.config.data['ready_template_id'] + ':'))
        self.assertNotIn('submit_build', self.driver.events)

    def test_legacy_source_selection_preserves_previous_priority(self):
        for ready, image, expected in [('template', 'image', 'both'), ('template', '', 'existing'),
                                        ('', 'image', 'build'), ('', '', 'existing')]:
            self.config.path.write_text(json.dumps({'ready_template_id': ready, 'image': image}), encoding='utf-8')
            migrated = Config(self.config.directory)
            self.assertEqual(expected, migrated.data['template_source'])

    def test_config_https_and_uuid_validation(self):
        with self.assertRaises(ValueError):
            self.config.save({'gateway_url': 'http://gateway.example.com'})
        with self.assertRaises(ValueError):
            self.config.save({'ready_template_id': 'not-a-uuid'})


if __name__ == '__main__':
    unittest.main()
