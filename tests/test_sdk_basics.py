import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import httpx
import test_engine
from studio.sdk import SDK
from studio.sdk_features import SDKFeatures
from studio.capabilities.sdk_basics import workflow


class SDKBasicsTests(unittest.TestCase):
    def setUp(self):test_engine.EngineTests.setUp(self)

    def adapter(self,sandbox):
        driver=SDKFeatures();driver.c={'command_user':'sandbox','command_cwd':'/tmp'}
        driver.connect=Mock(return_value=sandbox)
        return driver

    def test_official_patch_serializes_build_extensions_and_journals_before_submit(self):
        self.config.data['api_key']='e2b_'+'0'*40
        driver=SDK(self.config.data);seen=[];created=[]
        tid='00000000-0000-4000-8000-000000000005';bid='00000000-0000-4000-8000-000000000006'
        def transport(request):
            body=json.loads(request.content);seen.append((request.url.path,body))
            if request.url.path=='/v3/templates':
                return httpx.Response(202,json=dict(templateID=tid,buildID=bid,public=False,names=['fixture'],tags=[],aliases=[]))
            self.assertEqual(1,len(created))
            return httpx.Response(202)
        driver.client.set_httpx_client(httpx.Client(base_url='https://api.example.invalid',transport=httpx.MockTransport(transport)))
        extensions={'env_vars':{'DEMO':'yes'},'network_configuration':{'networkMode':'public'},
            'first_invoke_cmd':['/bin/sh','-c','echo yes'],'storage_config':{'obsMounts':[]},'observability':{'logs':{'enableStdLogs':False}}}
        with patch('e2b.template_sync.main.get_api_client',return_value=driver.client):
            result=driver.build_template_async(created.append,extensions)
        self.assertEqual(tid,result['template_id']);self.assertEqual(self.config.data['gateway_id'],seen[0][1]['gatewayID'])
        for source,target in [('env_vars','envVars'),('network_configuration','networkConfiguration'),('first_invoke_cmd','firstInvokeCmd'),('storage_config','storageConfig'),('observability','observability')]:
            self.assertEqual(extensions[source],seen[1][1][target])

    def test_build_creation_survives_later_submit_failure(self):
        resource=dict(template_id='new-owned',build_id='new-build',owned=True)
        def build(callback,options):callback(resource);raise RuntimeError('submit failed')
        self.driver.build_template_async=build
        with self.assertRaisesRegex(RuntimeError,'submit failed'):workflow.execute(self.engine,self.driver,'template_sdk_build')
        self.assertEqual('new-owned',self.engine.state['sdk_basics_template'])
        self.engine.own('template',resource)

    def test_build_delete_rejects_referenced_or_unowned_template(self):
        resource=dict(template_id='own-test',build_id='own-build',owned=True)
        self.engine.ledger.record('template',resource,'sdk_basics');self.engine.state['sdk_basics_template']='own-test'
        self.driver.list_sandboxes=Mock(return_value={'sandboxes':[{'template_id':'own-test'}]})
        self.driver.delete_build=Mock()
        with self.assertRaisesRegex(RuntimeError,'仍有沙箱'):workflow.execute(self.engine,self.driver,'build_delete')
        self.driver.delete_build.assert_not_called()
        resource['owned']=False;self.driver.list_sandboxes.return_value={'sandboxes':[]}
        with self.assertRaisesRegex(RuntimeError,'自有资源'):workflow.execute(self.engine,self.driver,'build_delete')

    def test_cleanup_preserves_other_scene_and_external_template(self):
        basic=self.engine.running(self.driver)
        sid=self.driver.create_sandbox('own-test')
        extra=dict(sandbox_id=sid,template_id='own-test',owned=True)
        self.engine.ledger.record('sandbox',extra,'sdk_basics')
        self.driver.list_sandboxes=Mock(return_value={'sandboxes':[]})
        result=workflow.execute(self.engine,self.driver,'sdk_basics_cleanup')
        self.assertTrue(result['other_resources_preserved']);self.assertIn(basic['sandbox_id'],self.driver.sandboxes)
        self.assertNotIn(sid,self.driver.sandboxes)

    def test_build_options_reject_unknown_credentials_and_wrong_types(self):
        for data in ({'api_key':'wrong'},{'api_headers':{'Authorization':'wrong'}},{'env_vars':{'X':7}},{'first_invoke_cmd':'echo hello'},{'skip_cache':'true'}):
            with self.assertRaises(ValueError):workflow.build_options(json.dumps(data))
        value='{"env_vars":{"PRIVATE_VALUE":"example-only"}}'
        self.config.save({'extra_build_options_json':value})
        self.assertNotIn(value,json.dumps(self.config.public()))
        self.assertTrue(self.config.public()['extra_build_options_json_configured'])

    def test_command_env_uses_explicit_cwd(self):
        run=Mock(return_value=SimpleNamespace(stdout='created-by-studio',exit_code=0))
        adapter=self.adapter(SimpleNamespace(commands=SimpleNamespace(run=run)))
        adapter.sdk_envs('test-id')
        self.assertEqual('/tmp',run.call_args.kwargs['cwd']);self.assertEqual('sandbox',run.call_args.kwargs['user'])

    def test_missing_metrics_never_report_success(self):
        response=httpx.Response(200,json={'cpu_count':2},request=httpx.Request('GET','https://gateway.example.invalid/metrics'))
        adapter=self.adapter(SimpleNamespace(_envd_api=SimpleNamespace(get=lambda p:response)))
        with self.assertRaisesRegex(RuntimeError,'字段不完整'):adapter.sdk_metrics('test-id')

    def test_capabilities_point_to_their_own_resource_context(self):
        actions=self.engine.registry.actions
        self.assertEqual('sdk_basics_sandbox',actions['pty_session']['resource_state_key'])
        self.assertEqual('sdk_basics_sandbox',actions['sandbox_metrics']['resource_state_key'])
        self.assertEqual('',actions['template_sdk_build']['resource_state_key'])
        self.assertIsNone(actions['command']['resource_state_key'])

    def test_signed_url_reports_real_status_and_omits_signature(self):
        payload=b'AgentSphere signed-url test\x00\xff'
        upload=httpx.Response(201,request=httpx.Request('POST','https://gateway.example.invalid/files'))
        download=httpx.Response(200,content=payload,request=httpx.Request('GET','https://gateway.example.invalid/files'))
        sb=SimpleNamespace(files=SimpleNamespace(make_dir=Mock()),upload_url=Mock(return_value='https://gateway.example.invalid/files?signature=private-value'),
            download_url=Mock(return_value='https://gateway.example.invalid/files?signature=private-value'),
            _envd_api=SimpleNamespace(post=Mock(return_value=upload),get=Mock(return_value=download)))
        result=self.adapter(sb).file_urls('test-id','/tmp/owned')
        self.assertEqual(201,result['upload_http']);self.assertNotIn('private-value',json.dumps(result))

    def test_killed_process_requires_confirmed_kill_and_absence(self):
        from e2b.sandbox.commands.command_handle import CommandExitException
        handle=Mock(pid=123);attached=Mock(pid=123)
        attached.wait.side_effect=CommandExitException(stderr='',stdout='',exit_code=-1,error=None)
        commands=SimpleNamespace(run=Mock(return_value=handle),connect=Mock(return_value=attached),
            list=Mock(side_effect=[[SimpleNamespace(pid=123)],[]]),kill=Mock(return_value=True))
        result=self.adapter(SimpleNamespace(commands=commands)).process_background('test-id')
        self.assertTrue(result['absent_after']);self.assertEqual(-1,result['exit_code'])
        commands.list=Mock(return_value=[SimpleNamespace(pid=123)]);commands.kill=Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError,'kill未确认'):self.adapter(SimpleNamespace(commands=commands)).process_background('test-id')
