import asyncio
import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_engine
from studio.scenarios.miles_rl.task import TASK_ID,PROMPT,builtin_candidates
from studio.scenarios.miles_rl.evaluator import evaluate_candidate,grade_case
from studio.scenarios.miles_rl.reward import reward,reward_context,environment_evaluator
from studio.scenarios.miles_rl.workflow import execute,generate_candidates


class LocalTrustedFixtureSDK(test_engine.FakeSDK):
    """Only test-owned built-in fixtures run locally; never used by production."""
    def command(self,sid,command,**kwargs):
        words=shlex.split(command)
        if len(words)>2 and words[0]=='python3' and words[1].endswith('/runner.py'):
            code=self.files[(sid,words[2])]
            payload=base64.b64decode(words[3])
            # Fixtures below are source strings authored in this test suite.
            with tempfile.TemporaryDirectory() as directory:
                source=Path(directory)/'candidate.py';source.write_text(code,encoding='utf-8')
                child=subprocess.run([sys.executable,'-I',str(source)],input=payload,capture_output=True,timeout=3)
            value=dict(returncode=child.returncode,timed_out=False,
                stdout=child.stdout.decode('utf-8'),stderr=child.stderr.decode('utf-8'),elapsed_s=.001)
            return dict(exit_code=0,stdout=json.dumps(value),stderr='')
        return dict(exit_code=0,stdout='Python test fixture\nuid=2001(sandbox)',stderr='')


class MilesTests(unittest.TestCase):
    def setUp(self):
        test_engine.EngineTests.setUp(self)
        self.driver=LocalTrustedFixtureSDK(self.config.data)
        self.config.save({'miles_candidate_mode':'builtin','miles_user':'sandbox'})

    def test_builtin_rewards_are_measured_and_independent(self):
        values=builtin_candidates(2)
        scores=[evaluate_candidate(self.driver,'template:build',x['code']) for x in values]
        self.assertEqual([.5,1.0],[s['reward'] for s in scores])
        self.assertNotEqual(scores[0]['sandbox_id'],scores[1]['sandbox_id'])
        self.assertEqual([3,6],[s['passed'] for s in scores])

    def test_infrastructure_failure_raises_and_cleans_created_sandbox(self):
        self.driver.command=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Gateway unavailable'))
        with self.assertRaisesRegex(RuntimeError,'no reward issued'):
            evaluate_candidate(self.driver,'template:build',builtin_candidates(2)[1]['code'],cleanup=True)
        self.assertEqual({},self.driver.sandboxes)

    def test_oracle_rejects_bool_timeout_bad_json_and_nonzero(self):
        case={'expected':{'result':0}}
        for stdout,code,timeout in [('true',0,False),('{"result":false}',0,False),('{"result":0}',1,False),('{"result":0}',0,True)]:
            self.assertFalse(grade_case(case,dict(stdout=stdout,returncode=code,timed_out=timeout))[0])

    def test_syntax_error_is_zero_without_creating_sandbox(self):
        score=evaluate_candidate(self.driver,'template:build','def invalid(:\n')
        self.assertEqual(0,score['reward']);self.assertEqual([],self.driver.created_references)

    def test_miles_hook_returns_float_without_mutating_reward(self):
        sample=SimpleNamespace(response=builtin_candidates(2)[1]['code'],metadata={'agentsphere_task_id':TASK_ID},reward=None)
        def evaluator(code,task):return evaluate_candidate(self.driver,'template:build',code,task_id=task,cleanup=True)
        async def run():
            with reward_context(evaluator):return await reward(None,sample)
        self.assertEqual(1.0,asyncio.run(run()));self.assertIsNone(sample.reward)
        self.assertEqual(6,sample.metadata['agentsphere_reward_evidence']['passed'])
        self.assertEqual({},self.driver.sandboxes)

    def test_hook_rejects_other_tasks_before_cloud_call(self):
        sample=SimpleNamespace(response='print(1)',metadata={},reward=None)
        with self.assertRaises(ValueError):asyncio.run(reward(None,sample))

    def test_complete_studio_loop_and_cleanup_preserve_basic(self):
        basic=self.engine.running(self.driver)
        execute(self.engine,self.driver,'miles_prepare')
        rollout=execute(self.engine,self.driver,'miles_rollout')
        self.assertEqual('builtin_control_not_model',rollout['origin'])
        grade=execute(self.engine,self.driver,'miles_evaluate')
        self.assertEqual([-.25,.25],[r['centered_reward'] for r in grade['evaluations']])
        feedback=execute(self.engine,self.driver,'miles_callback')
        self.assertEqual(.5,feedback['returned_reward'])
        self.assertFalse(feedback['training_performed'])
        output=execute(self.engine,self.driver,'miles_export')
        records=[json.loads(line) for line in output['artifact'].splitlines()]
        self.assertEqual([.5,1.0],[r['reward'] for r in records])
        execute(self.engine,self.driver,'miles_cleanup')
        self.assertIn(basic['sandbox_id'],self.driver.sandboxes)
        self.assertEqual(1,len(self.driver.sandboxes))

    def test_prepare_does_not_generate_candidates_or_call_model(self):
        execute(self.engine,self.driver,'miles_prepare')
        with patch('studio.scenarios.miles_rl.workflow.generate_candidates') as generation:
            self.engine.prepare('miles_rollout',self.driver)
            generation.assert_not_called()

    def test_rollout_is_frozen_and_changes_require_new_round(self):
        execute(self.engine,self.driver,'miles_prepare');execute(self.engine,self.driver,'miles_rollout')
        with self.assertRaisesRegex(RuntimeError,'已固定'):execute(self.engine,self.driver,'miles_rollout')
        self.config.save({'miles_user':'root'})
        with self.assertRaisesRegex(RuntimeError,'已改变'):execute(self.engine,self.driver,'miles_evaluate')

    def test_missing_steps_are_not_synthesized(self):
        with self.assertRaisesRegex(RuntimeError,'先执行'):execute(self.engine,self.driver,'miles_evaluate')
        self.assertEqual([],self.driver.created_references)

    def test_live_model_http_generation_contract(self):
        import httpx
        cfg={**self.config.data,'miles_candidate_mode':'model','miles_model_base_url':'https://model.example.invalid/v1',
             'miles_model_api_key':'private-model-fixture','miles_model_id':'test-model'}
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(200,json={'choices':[{'message':{'content':'```python\nprint(1)\n```'}}]})
        real_client=httpx.Client
        with patch('httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)):
            value=generate_candidates(cfg)
        self.assertEqual(2,value['model_calls'])
        self.assertEqual('live_model',value['origin'])
        self.assertEqual('Bearer private-model-fixture',requests[0].headers['authorization'])
        self.assertNotIn('private-model-fixture',json.dumps(value))

    def test_model_payment_error_never_becomes_fallback_candidates(self):
        import httpx
        cfg={**self.config.data,'miles_candidate_mode':'model','miles_model_base_url':'https://model.example.invalid',
             'miles_model_api_key':'private-model-fixture','miles_model_id':'test-model'}
        real_client=httpx.Client
        with patch('httpx.Client',side_effect=lambda **kw:real_client(
                transport=httpx.MockTransport(lambda r:httpx.Response(402,text='account unavailable')),**kw)):
            with self.assertRaisesRegex(RuntimeError,'HTTP 402'):generate_candidates(cfg)

    def test_external_hook_rejects_invalid_resource_limits_before_cloud(self):
        for values in ({'AGENTSPHERE_RL_CONCURRENCY':'0'},{'AGENTSPHERE_RL_CONCURRENCY':'2','AGENTSPHERE_RL_CASE_TIMEOUT':'11'}):
            with patch.dict('os.environ',values),patch('studio.sdk.SDK') as sdk:
                with self.assertRaises(ValueError):environment_evaluator('print(1)',TASK_ID)
                sdk.assert_not_called()

    def test_legacy_model_secret_is_not_returned_after_scene_config_save(self):
        self.config.save({'miles_model_api_key':'private-miles-credential'})
        self.assertNotIn('private-miles-credential',json.dumps(self.config.public()))
        self.config.save({'miles_model_api_key':''})
        self.assertTrue(self.config.public()['miles_model_api_key_configured'])
