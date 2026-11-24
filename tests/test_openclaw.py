import unittest

import test_engine
from studio.openclaw import digest, execute, prepare


class BusinessWorkflowTests(unittest.TestCase):
    def setUp(self):
        test_engine.EngineTests.setUp(self)
        self.driver.command = lambda sid, cmd, **kw: {
            'sandbox_id': sid, 'exit_code': 0,
            'stdout': 'HTTP=200 IP=1.2.3.4\n' if 'baidu' in cmd else 'OpenClaw test CLI'}

    def setup_business(self):
        execute(self.engine, self.driver, 'openclaw_probe')
        execute(self.engine, self.driver, 'openclaw_network')
        execute(self.engine, self.driver, 'openclaw_input')
        run = self.engine.state['openclaw_run']
        def task(driver, sid, directory, task_path):
            self.assertEqual(run['input_path'], task_path)
            path = directory + '/workspace/delivery-summary.md'
            self.driver.write(sid, path, 'real test artifact')
            return dict(sandbox_id=sid, artifact_path=path, artifact='real test artifact')
        self.engine.openclaw_task = task
        execute(self.engine, self.driver, 'openclaw_task')
        return run

    def test_business_does_not_reuse_or_delete_basic_sandbox(self):
        basic = self.engine.running(self.driver)
        run = self.setup_business()
        self.assertNotEqual(basic['sandbox_id'], run['sandbox_id'])
        self.assertEqual(basic['sandbox_id'], self.engine.state['active_sandbox'])
        execute(self.engine, self.driver, 'openclaw_cleanup')
        self.assertIn(basic['sandbox_id'], self.driver.sandboxes)
        self.assertNotIn(run['sandbox_id'], self.driver.sandboxes)

    def test_restore_checks_existing_artifact_without_rewriting(self):
        run = self.setup_business()
        before = dict(self.driver.files)
        execute(self.engine, self.driver, 'openclaw_pause')
        result = execute(self.engine, self.driver, 'openclaw_restore')
        self.assertEqual(run['sandbox_id'], result['same_sandbox_id'])
        self.assertEqual(before, self.driver.files)
        self.assertTrue(result['artifact_preserved'])
        with self.assertRaisesRegex(RuntimeError, '暂停等待'):
            prepare(self.engine, self.driver, 'openclaw_restore')

    def test_missing_business_input_does_not_get_synthesized(self):
        execute(self.engine, self.driver, 'openclaw_probe')
        execute(self.engine, self.driver, 'openclaw_network')
        with self.assertRaisesRegex(RuntimeError, '先上传'):
            execute(self.engine, self.driver, 'openclaw_task')
        self.assertFalse(self.driver.files)

    def test_corrupt_business_artifact_fails_restore(self):
        run = self.setup_business()
        execute(self.engine, self.driver, 'openclaw_pause')
        self.driver.write(run['sandbox_id'], run['artifact_path'], 'corrupted')
        with self.assertRaisesRegex(RuntimeError, 'SHA256'):
            execute(self.engine, self.driver, 'openclaw_restore')

    def test_expired_business_sandbox_never_replaced_on_restore(self):
        run = self.setup_business()
        execute(self.engine, self.driver, 'openclaw_pause')
        self.driver.sandboxes.pop(run['sandbox_id'])
        count = len(self.driver.created_references)
        with self.assertRaisesRegex(RuntimeError, '原业务沙箱已不存在'):
            execute(self.engine, self.driver, 'openclaw_restore')
        self.assertEqual(count, len(self.driver.created_references))
