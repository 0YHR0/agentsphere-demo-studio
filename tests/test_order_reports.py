import base64
import hashlib
import io
import json
import math
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

import test_engine
from studio.scenarios.order_reports import csv_data,environment,policy,strategies,workflow,evidence


class OrderFixtureSDK(test_engine.FakeSDK):
    """Deterministic metrics only for workflow QA; never a production fallback."""
    def command(self,sid,command,**options):
        args=shlex.split(command)
        if len(args)>2 and args[1].endswith('/guest.py'):
            jobs=json.loads(base64.b64decode(args[2]));rows=[]
            for job in jobs:
                spec=job['dataset'];report=environment.reference(spec['profile'],spec['seed'])
                cost={'memory':.4,'stream':.2,'chunk':.3,'sqlite':.5}[job['action']]
                rows.append(dict(id=job['id'],dataset_sha256=environment.dataset_digest(spec['profile'],spec['seed']),
                    returncode=0,timed_out=False,stdout=json.dumps(report),stderr='',wall_s=cost,cpu_s=cost*.9,peak_rss_mib=20))
            return dict(stdout=json.dumps(dict(source_hashes=environment.source_hashes(),results=rows)),exit_code=0)
        return dict(stdout='Python test fixture; sqlite3; uid=1000',exit_code=0)


class ReportTests(unittest.TestCase):
    def setUp(self):
        test_engine.EngineTests.setUp(self)
        self.config.save({'orders_template_ref':self.config.data['ready_template_id']+':00000000-0000-4000-8000-000000000003','orders_rounds':'2'})
        self.driver=OrderFixtureSDK(self.config.data)

    def test_update_matches_finite_difference_policy_gradient(self):
        weights=[[.1,-.2,.3,0] for _ in policy.TASKS]
        samples=[dict(task=t,action=a,reward=r) for t in policy.TASKS for a,r in [(1,1),(0,.25)]]
        updated,norm=policy.update(weights,samples,1)
        def objective(w):
            return sum((s['reward']-samples[i//2*2+1-i%2]['reward'])*math.log(policy.probabilities(w,s['task'])[s['action']]) for i,s in enumerate(samples))/6
        eps=1e-5
        for i in range(3):
            for j in range(4):
                plus=[r[:] for r in weights];minus=[r[:] for r in weights]
                plus[i][j]+=eps;minus[i][j]-=eps
                self.assertAlmostEqual(updated[i][j]-weights[i][j],(objective(plus)-objective(minus))/(2*eps),places=7)
        self.assertGreater(norm,0)

    def test_equal_rewards_produce_no_gradient_and_stable_softmax(self):
        weights=policy.initial_weights()
        samples=[dict(task=t,action=a,reward=.5) for t in policy.TASKS for a in (0,1)]
        self.assertEqual((weights,0),policy.update(weights,samples,3))
        self.assertAlmostEqual(1,sum(policy.probabilities([[10000,9999,9998,9997]]*3,'daily')))

    def test_four_implementations_match_independent_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            for profile in policy.TASKS:
                path=Path(directory)/'orders.csv';spec=csv_data.spec(profile,47,'test')
                with path.open('w',encoding='utf-8',newline='') as output:csv_data.write_csv(spec,output)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),environment.dataset_digest(profile,47))
                for action in policy.ACTIONS:
                    self.assertEqual(environment.reference(profile,47),strategies.calculate(path,action,spec['group']),(profile,action))

    def test_refunds_cancelled_and_exact_cents_hand_example(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'tiny.csv'
            path.write_text('order_id,customer_id,category,quantity,unit_price_cents,refund_cents,status\na,C1,A,2,100,50,paid\nb,C1,A,1,999,0,cancelled\nc,C2,B,1,300,300,paid\n',encoding='utf-8')
            expected=dict(paid_orders=2,gross_cents=500,refund_cents=350,net_cents=150,
                groups={'A':dict(paid_orders=1,gross_cents=200,refund_cents=50,net_cents=150),'B':dict(paid_orders=1,gross_cents=300,refund_cents=300,net_cents=0)})
            for action in policy.ACTIONS:self.assertEqual(expected,strategies.calculate(path,action,'category'))

    def test_incorrect_outputs_zero_and_infra_metrics_raise(self):
        dataset=csv_data.spec('daily',101,'test');report=environment.reference('daily',101)
        execution=dict(returncode=0,timed_out=False,stdout=json.dumps(report),wall_s=.1,cpu_s=.08,peak_rss_mib=20)
        self.assertTrue(environment.grade(dataset,execution)['correct'])
        for invalid in ({**report,'gross_cents':float(report['gross_cents'])},{**report,'net_cents':-1}):
            self.assertEqual(0,environment.grade(dataset,{**execution,'stdout':json.dumps(invalid)})['reward'])
        self.assertEqual(0,environment.grade(dataset,{**execution,'returncode':1})['reward'])
        for metrics in ({'wall_s':-1},{'peak_rss_mib':float('nan')},{'cpu_s':None}):
            with self.assertRaisesRegex(RuntimeError,'no reward'):environment.grade(dataset,{**execution,**metrics})

    def test_cost_reward_decreases_with_real_costs(self):
        spec=csv_data.spec('daily',101,'test');row=dict(returncode=0,timed_out=False,stdout=json.dumps(environment.reference('daily',101)),wall_s=.1,cpu_s=.1,peak_rss_mib=20)
        first=environment.grade(spec,row)['reward']
        self.assertLess(environment.grade(spec,{**row,'wall_s':.3})['reward'],first)
        self.assertLess(environment.grade(spec,{**row,'peak_rss_mib':40})['reward'],first)

    def test_complete_loop_heldout_pairing_checkpoint_cleanup(self):
        basic=self.engine.running(self.driver)
        for case in ('orders_prepare','orders_baseline','orders_train','orders_evaluate','orders_checkpoint'):
            result=workflow.execute(self.engine,self.driver,case)
        self.assertTrue(result['reload_verified']);self.assertEqual(2,result['optimizer_steps'])
        self.assertEqual(36,len(result['evaluation']))
        self.assertTrue(all(r['correct'] for r in result['evaluation']))
        self.assertEqual({12},set(result['comparison'][k]['count'] for k in ('initial','rule','trained')))
        train={s['dataset_sha256'] for step in result['history'] for s in step['samples']}
        self.assertTrue(train.isdisjoint({s['dataset_sha256'] for s in result['evaluation']}))
        workflow.execute(self.engine,self.driver,'orders_cleanup')
        self.assertIn(basic['sandbox_id'],self.driver.sandboxes)

    def test_infra_failure_does_not_update_model(self):
        workflow.execute(self.engine,self.driver,'orders_prepare');workflow.execute(self.engine,self.driver,'orders_baseline')
        before=policy.fingerprint(self.engine.scenario_run('order_reports')['weights'])
        with patch.object(workflow,'measure',side_effect=RuntimeError('Gateway unavailable')):
            with self.assertRaises(RuntimeError):workflow.execute(self.engine,self.driver,'orders_train')
        run=self.engine.scenario_run('order_reports')
        self.assertEqual(before,policy.fingerprint(run['weights']));self.assertEqual([],run['history'])

    def test_report_no_victory_is_fabricated(self):
        rows=[]
        for route,reward in [('initial',.5),('rule',.8),('trained',.6)]:
            rows.append(dict(route=route,reward=reward,correct=True,wall_s=.1,peak_rss_mib=20))
        self.assertEqual('worse',workflow.compare(rows)['outcome'])

    def test_prepare_does_not_train_and_settings_are_frozen(self):
        self.engine.prepare('orders_prepare',self.driver)
        self.assertEqual([],self.engine.scenario_run('order_reports')['history'])
        with self.assertRaisesRegex(RuntimeError,'不能仅准备状态'):workflow.execute(self.engine,self.driver,'orders_train')
        workflow.execute(self.engine,self.driver,'orders_prepare');self.config.save({'orders_seed':'8'})
        with self.assertRaisesRegex(RuntimeError,'配置已变更'):workflow.execute(self.engine,self.driver,'orders_baseline')

    def test_baseline_and_probability_trace_are_recorded_and_read_only(self):
        workflow.execute(self.engine,self.driver,'orders_prepare')
        baseline=workflow.execute(self.engine,self.driver,'orders_baseline')
        self.assertEqual('calibration',baseline['measurement_split'])
        self.assertEqual(2,len(baseline['presentation']['table']['rows']))
        self.assertEqual([],baseline['display']['trace'])
        workflow.execute(self.engine,self.driver,'orders_train')
        original=json.dumps(self.engine.state,sort_keys=True)
        view=self.engine.snapshot()['scenario_runs']['order_reports']['display']
        self.assertTrue(view['trace_verified']);self.assertEqual(2,len(view['trace']))
        self.assertEqual([.25]*4,view['trace'][0]['before'][0])
        for row in view['trace']:
            for before,after,delta in zip(row['before'],row['after'],row['delta_pp']):
                self.assertAlmostEqual(1,sum(after))
                for a,b,d in zip(before,after,delta):self.assertAlmostEqual((b-a)*100,d)
        self.assertEqual(original,json.dumps(self.engine.state,sort_keys=True))

    def test_changed_training_evidence_never_fabricates_probability_changes(self):
        for case in ('orders_prepare','orders_baseline','orders_train'):
            workflow.execute(self.engine,self.driver,case)
        run=self.engine.scenario_run('order_reports')
        run['history'][0]['parameters_after_sha256']='invalid'
        view=evidence.view(run)
        self.assertFalse(view['trace_verified']);self.assertEqual([],view['trace'])
        self.assertTrue(view['control_calibration'])
