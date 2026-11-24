import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_engine
from studio.sdk_features import SDKFeatures
from studio.capabilities.obs import workflow


class OBSTests(unittest.TestCase):
    def setUp(self):
        test_engine.EngineTests.setUp(self)
        self.ref=self.config.data['ready_template_id']+':00000000-0000-4000-8000-000000000003'
        self.config.save(dict(obs_template_ref=self.ref,obs_bucket='example-test',obs_prefix='studio-tests'))

    def test_storage_metadata_has_no_aksk_and_keeps_fixed_build(self):
        d=SDKFeatures();d.c={'sandbox_timeout':600};d.sandbox_options={'api_key':'test-local-key'};d._sandboxes={}
        d.Sandbox=SimpleNamespace(create=Mock(return_value=SimpleNamespace(sandbox_id='new-sandbox')))
        sid=d.create_obs_sandbox(self.ref,'example-test','studio-tests/run-owned','/mnt/obs',True)
        self.assertEqual('new-sandbox',sid)
        opts=d.Sandbox.create.call_args.kwargs;self.assertEqual(self.ref,opts['template'])
        meta=json.loads(opts['metadata']['agentsandbox.storage.obs'])
        self.assertEqual({'obsMounts':[{'bucket':'example-test','bucketPath':'studio-tests/run-owned','mountDir':'/mnt/obs','readOnly':True}]},meta)
        self.assertNotIn('test-local-key',json.dumps(meta))

    def test_prefix_cannot_escape_owned_run(self):
        for prefix in ('/','../other','a/../b','a//b','a/','a;rm','a\\b'):
            self.config.data['obs_prefix']=prefix
            with self.assertRaises(ValueError):workflow.validate(self.config,'obs_write')

    def test_public_build_and_missing_agency_rejected_before_creation(self):
        self.driver.create_obs_sandbox=Mock()
        for details in ({'networkConfiguration':{'networkMode':'public'}},
                        {'networkConfiguration':{'networkMode':'private','targetProjectId':'p','targetVpcId':'v','targetSubnetId':'s'}}):
            self.driver.build_detail=Mock(return_value=details)
            with self.assertRaises(RuntimeError):workflow.prepare(self.engine,self.driver,'obs_write')
        self.driver.create_obs_sandbox.assert_not_called()

    def test_plain_directory_is_not_a_mount_pass(self):
        d=SDKFeatures();d.command=Mock(return_value={'stdout':'[]'})
        with self.assertRaisesRegex(RuntimeError,'普通目录'):d.obs_mount_info('sid','/mnt/obs')
        d.command.return_value={'stdout':json.dumps([{'filesystem':'ext4'}])}
        with self.assertRaises(RuntimeError):d.obs_mount_info('sid','/mnt/obs')

    def test_creation_is_journaled_even_if_mount_check_fails(self):
        self.driver.create_obs_sandbox=Mock(return_value='obs-created')
        self.driver.sandboxes['obs-created']={'state':'running'}
        self.driver.obs_mount_info=Mock(side_effect=RuntimeError('mount failed'))
        run=dict(template_ref=self.ref,bucket='example-test',bucket_path='studio-tests/run-abc',run_id='abc',sandbox_ids=[])
        self.engine.state['obs_run']=run
        with self.assertRaisesRegex(RuntimeError,'mount failed'):workflow.create(self.engine,self.driver,run)
        r=workflow.resource(self.engine,'obs-created');self.assertEqual('obs',r['scope'])
        self.assertEqual(['obs-created'],run['sandbox_ids'])

    def test_readonly_rejects_a_successful_write(self):
        d=SDKFeatures();d.connect=Mock(return_value=SimpleNamespace(files=SimpleNamespace(read=Mock(return_value='expected'),exists=Mock(return_value=False))))
        d.command=Mock(return_value={'stdout':'{"denied":false}'})
        with self.assertRaisesRegex(RuntimeError,'未拒绝'):d.obs_readonly_check('sid','/mnt/obs','expected')

    def test_persistence_deletes_original_and_does_not_rewrite_missing_file(self):
        run=dict(run_id='abc',test_dir='run-abc',template_ref=self.ref,bucket='example-test',bucket_path='studio-tests',writer_id='writer',seeded=True,expected='expected',sandbox_ids=['writer'])
        self.engine.state['obs_run']=run
        old=dict(sandbox_id='writer',owned=True,read_only=False)
        self.engine.ledger.record('sandbox',old,'obs','abc');self.driver.sandboxes['writer']={'state':'running'}
        self.driver.create_obs_sandbox=Mock(return_value='reader');self.driver.sandboxes['reader']={'state':'running'}
        self.driver.obs_mount_info=Mock(return_value={'mount':{'filesystem':'fuse.obsfs'}})
        self.driver.read=Mock(side_effect=FileNotFoundError('missing'));self.driver.write=Mock()
        with patch.object(workflow,'time',SimpleNamespace(monotonic=Mock(side_effect=[0,31]))):
            with self.assertRaises(FileNotFoundError):workflow.execute(self.engine,self.driver,'obs_persist')
        self.assertTrue(old['deleted']);self.assertEqual('reader',run['reader_id'])
        self.driver.write.assert_not_called()

    def test_cleanup_only_own_named_files_and_sandboxes(self):
        self.engine.running(self.driver);other=self.engine.resource('sandbox')['sandbox_id']
        r=dict(sandbox_id='obs-owned',owned=True,read_only=False)
        self.driver.sandboxes['obs-owned']={'state':'running'}
        self.engine.ledger.record('sandbox',r,'obs','abc')
        run=dict(run_id='abc',test_dir='run-abc',sandbox_ids=['obs-owned']);self.engine.state['obs_run']=run
        fs=SimpleNamespace(exists=Mock(side_effect=[True,False,False,False,True]),remove=Mock(),list=Mock(return_value=[]))
        self.driver.connect=Mock(return_value=SimpleNamespace(files=fs));self.driver.command=Mock()
        self.driver.obs_mount_info=Mock()
        result=workflow.cleanup(self.engine,self.driver,run)
        self.assertTrue(result['test_objects_removed']);self.assertIn(other,self.driver.sandboxes)
        self.assertTrue(result['test_directory_removed'])
        fs.remove.assert_called_once_with(workflow.MOUNT+'/run-abc/evidence.txt',user='root',request_timeout=30)
        self.assertEqual([],self.engine.state['templates'])

    def test_mounting_bucket_root_is_supported(self):
        self.config.data['obs_prefix']='';workflow.validate(self.config,'obs_write')

    def test_unknown_or_foreign_sandbox_cannot_be_cleaned(self):
        self.engine.running(self.driver);other=self.engine.resource('sandbox')['sandbox_id']
        with self.assertRaises(RuntimeError):workflow.cleanup(self.engine,self.driver,dict(sandbox_ids=[other]))
        self.assertIn(other,self.driver.sandboxes)
