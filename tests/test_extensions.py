import importlib.util
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import test_engine
from studio.config import Config, redact
from studio.core.instrumentation import recorded
from studio.core.registry import DemoPackage, Field, Registry, get_registry
from studio.core.reporting import markdown_report
from studio.scenarios.vpc.workflow import execute, private_url
from studio.scenarios.vpc.ws_probe import probe


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        test_engine.EngineTests.setUp(self)

    def test_new_package_runs_without_engine_or_frontend_switches(self):
        def prepare(engine, driver, case): engine.state['extension_marker'] = 'ready'
        def execute(engine, driver, case): return {'marker': engine.state['extension_marker']}
        package = DemoPackage(id='customer', title='客户扩展', kind='scenario',
            description='No Engine changes', cases=(('customer_check','检查','客户','描述','customer','ready'),),
            prepare=prepare, execute=execute, plan=lambda e,c:{'steps':['ready']}, source=lambda c:'real_extension_source')
        self.engine.registry = Registry([package])
        self.engine.start('customer_check')
        end = time.monotonic()+3
        while self.engine.job and time.monotonic()<end: time.sleep(.01)
        job = self.engine.state['jobs'][-1]
        self.assertEqual('passed',job['status'])
        self.assertEqual({'marker':'ready'},job['result'])
        self.assertEqual('customer',job['package'])

    def test_registry_rejects_duplicates_reserved_fields_and_secret_defaults(self):
        package = get_registry().packages['vpc']
        with self.assertRaises(ValueError): Registry([package,package])
        for field in [Field('api_key','wrong'),Field('bad_key','wrong','hardcoded',kind='secret')]:
            with self.assertRaises(ValueError): Registry([replace(package,fields=(field,))])

    def test_new_secret_field_is_private_and_blank_preserves_value(self):
        package = replace(get_registry().packages['vpc'],fields=(Field('customer_credential','Key',kind='secret'),))
        with patch('studio.core.registry.get_registry',return_value=Registry([package])):
            config = Config(self.config.directory/'extension')
            config.save({'customer_credential':'test-private-value'})
            config.save({'customer_credential':''})
            self.assertNotIn('customer_credential',config.public())
            self.assertTrue(config.public()['customer_credential_configured'])
            self.assertEqual('[REDACTED]',redact('test-private-value',config.secrets()))
        removed = Config(config.directory)
        self.assertNotIn('test-private-value',json.dumps(removed.public()))
        self.assertEqual('[REDACTED]',redact('test-private-value',removed.secrets()))

    def test_error_is_not_accepted_as_paused(self):
        resource=self.engine.running(self.driver)
        self.driver.sandboxes[resource['sandbox_id']].update(state='paused',detailedState='Error',errorMessage='snapshot failed')
        with self.assertRaisesRegex(RuntimeError,'snapshot failed'):
            self.engine.wait_state(self.driver,resource,'paused')

    def test_pausing_is_polled_until_detailed_paused(self):
        resource=self.engine.running(self.driver)
        responses=iter([{'state':'paused','detailedState':'Pausing'}, {'state':'paused','detailedState':'Paused'}])
        self.driver.sandbox_detail=lambda _:next(responses)
        with patch.object(self.engine.stop,'wait',return_value=False):
            value=self.engine.wait_state(self.driver,resource,'paused')
        self.assertEqual('Paused',value['detailedState'])

    def test_other_account_is_rejected_before_resource_operation(self):
        resource=self.engine.running(self.driver)
        self.config.data['api_key']='other-account-fixture'
        with self.assertRaisesRegex(RuntimeError,'其他账号'):
            self.engine.running(self.driver)
        self.assertFalse(resource.get('deleted'))

    def test_report_keeps_failure_and_preparation_mode(self):
        self.engine.state['jobs']=[{'case':'snapshot','mode':'run','status':'failed','error':'observed 504'},
                                  {'case':'vpc_prepare','mode':'prepare','status':'passed'}]
        report=self.engine.export_report()
        self.assertEqual(1,report['summary']['failed'])
        self.assertEqual('FAIL',report['overall'])
        self.assertIn('observed 504',markdown_report(report))
        self.assertIn('prepare',markdown_report(report))

    def test_prepare_only_report_does_not_claim_demonstration_passed(self):
        self.engine.state['jobs']=[{'case':'command','mode':'prepare','status':'passed'}]
        self.assertEqual('PREPARED',self.engine.export_report()['overall'])

    def test_instrumentation_handles_real_object_results_and_omits_payload(self):
        class Driver:
            @recorded
            def background(self): return type('Handle',(),{'pid':123})()
            @recorded
            def write(self,sid,path,value): return None
        d=Driver();events=[];d.recorder=events.append
        self.assertEqual(123,d.background().pid)
        d.write('sid','/tmp/file','private file body')
        self.assertEqual({'pid':123},events[0]['result'])
        self.assertNotIn('private file body',json.dumps(events))

    def test_telemetry_failure_does_not_hide_created_resource(self):
        class Driver:
            @recorded
            def create_sandbox(self):return 'already-created-id'
        d=Driver()
        def broken(event):raise OSError('disk full')
        d.recorder=broken
        self.assertEqual('already-created-id',d.create_sandbox())
        self.assertIn('disk full',d.recording_error)

    def test_command_failure_keeps_stderr_and_exit_code(self):
        class Failure(Exception):
            stdout='partial output';stderr='business error';exit_code=7
        class Driver:
            @recorded
            def command(self):raise Failure('exit 7')
        d=Driver();events=[];d.recorder=events.append
        with self.assertRaises(Failure):d.command()
        self.assertEqual(7,events[0]['error_details']['exit_code'])
        self.assertEqual('business error',events[0]['error_details']['stderr'])

    def test_connect_does_not_reset_ttl_to_sdk_default(self):
        from studio.sdk import SDK
        d=SDK.__new__(SDK);d.c={'sandbox_timeout':86400};d.sandbox_options={};d._sandboxes={}
        values=[]
        class Handle:
            def connect(self,**kw):values.append(kw['timeout']);return self
        class Sandbox:
            @staticmethod
            def connect(sid,**kw):values.append(kw['timeout']);return Handle()
        d.Sandbox=Sandbox
        d.connect('same-sandbox');d.connect('same-sandbox')
        self.assertEqual([86400,86400],values)


class VpcTests(unittest.TestCase):
    def setUp(self):
        test_engine.EngineTests.setUp(self)
        ref=self.config.data['ready_template_id']+':00000000-0000-4000-8000-000000000003'
        self.config.save({'vpc_template_ref':ref,'vpc_http_url':'http://192.168.1.10:8080/health',
                          'vpc_ws_url':'ws://192.168.1.10:8080/ws'})
        self.driver.build_detail=lambda _:dict(networkConfiguration=dict(networkMode='private',
            targetProjectId='project',targetVpcId='vpc',targetSubnetId='subnet'))
        self.driver.command=lambda sid,command,**opts:dict(exit_code=0,stdout='{"ok":true}\n'+json.dumps(dict(http_code=200,time_total=.004,remote_ip='192.168.1.10')),stderr='')

    def test_direct_http_prepares_dedicated_instance_and_cleans_only_that(self):
        basic=self.engine.running(self.driver)
        output=execute(self.engine,self.driver,'vpc_http')
        sid=output['sandbox_id']
        self.assertNotEqual(basic['sandbox_id'],sid)
        self.assertEqual(200,output['http_status'])
        self.assertEqual('vpc',self.engine.state['sandboxes'][-1]['scope'])
        execute(self.engine,self.driver,'vpc_cleanup')
        self.assertIn(basic['sandbox_id'],self.driver.sandboxes)
        self.assertNotIn(sid,self.driver.sandboxes)

    def test_public_build_is_rejected_without_creating_resources(self):
        self.driver.build_detail=lambda _:dict(networkConfiguration=dict(networkMode='public'))
        with self.assertRaisesRegex(RuntimeError,'private'):
            execute(self.engine,self.driver,'vpc_prepare')
        self.assertEqual([],self.driver.created_references)

    def test_expired_vpc_instance_never_silently_replaced(self):
        output=execute(self.engine,self.driver,'vpc_prepare')
        self.driver.sandboxes.pop(output['sandbox_id'])
        with self.assertRaisesRegex(RuntimeError,'原 VPC 沙箱已不存在'):
            execute(self.engine,self.driver,'vpc_http')
        self.assertEqual(1,len(self.driver.created_references))

    def test_cleanup_without_resources_is_skipped(self):
        self.assertTrue(execute(self.engine,self.driver,'vpc_cleanup')['skipped'])
        self.assertEqual([],self.driver.created_references)

    def test_target_rejects_public_localhost_and_credentials(self):
        for value in ['http://8.8.8.8','http://127.0.0.1','http://localhost','http://u:p@192.168.1.1','file:///tmp/x']:
            with self.assertRaises(ValueError):private_url(value,('http','https'))

    def test_websocket_probe_checks_real_handshake_idle_and_echo(self):
        path=Path(__file__).resolve().parent.parent/'examples/vpc_echo_server.py'
        spec=importlib.util.spec_from_file_location('vpc_echo_fixture',path)
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        server=ThreadingHTTPServer(('127.0.0.1',0),fixture.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            result=probe(f'ws://127.0.0.1:{server.server_port}/ws',.08,.02)
            self.assertEqual('passed',result['status'],result)
            self.assertEqual(101,result['handshake_status'])
            self.assertEqual(1,result['open_count'])
            self.assertEqual(0,result['reconnects'])
            self.assertGreaterEqual(len(result['echoes']),3)
        finally:
            server.shutdown();server.server_close();thread.join()
