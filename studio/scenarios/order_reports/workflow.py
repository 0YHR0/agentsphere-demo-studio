import hashlib
import json
import math
import random
import statistics
import uuid
from pathlib import Path

from . import policy
from .csv_data import PROFILES,spec
from .environment import install,measure,source_hashes

SCOPE='order_reports'
RULE='rows <= 2000: memory; category aggregation: stream; customer reconciliation: sqlite'
NAMES={'memory':'整表读入','stream':'逐行流式','chunk':'分块汇总','sqlite':'SQLite查询'}


def settings(config):return dict(rounds=int(config['orders_rounds']),seed=int(config['orders_seed']),learning_rate=float(config['orders_learning_rate']))


def validate(config,case,saving=False):
    if case=='orders_cleanup':return
    s=settings(config)
    if not 2<=s['rounds']<=24 or not 0<=s['seed']<=100000 or not math.isfinite(s['learning_rate']) or not .01<=s['learning_rate']<=10:
        raise ValueError('轮数2–24、种子0–100000、学习率0.01–10')
    user=config['orders_user']
    if not user or len(user)>64 or any(c in user for c in ('\n','\r','\0')):raise ValueError('请填写镜像中现有的单行运行用户')
    ref=config['orders_template_ref']
    if ref:
        try:
            parts=ref.split(':')
            if len(parts)!=2:raise ValueError()
            for part in parts:uuid.UUID(part)
        except ValueError:raise ValueError('订单场景需要固定Template ID:Build ID') from None
    elif not saving:raise ValueError('请先在订单场景填写包含Python和SQLite的Ready Template ID:Build ID')
    if config['sandbox_timeout']<600:raise ValueError('订单场景沙箱timeout请至少设置600秒')


def prepare(engine,driver,case):
    config=engine.config.data;validate(config,case);run=engine.scenario_run(SCOPE)
    if case=='orders_cleanup':return run
    resource=next((r for r in engine.state['sandboxes'] if r['sandbox_id']==run.get('sandbox_id')),None)
    if run.get('deleted'):resource=None
    if not resource:
        if case!='orders_prepare':raise RuntimeError('请先准备订单报表环境')
        ref=engine.resolve_template(driver,config['orders_template_ref']);sid=driver.create_sandbox(ref)
        run=engine.bind_scenario(SCOPE,dict(sandbox_id=sid,template_ref=ref,user=config['orders_user'],settings=settings(config),
            weights=policy.initial_weights(),history=[],directory='/tmp/orders-'+uuid.uuid4().hex,
            reward_version='orders-cost-v1',source_hashes=source_hashes(),rule=RULE,synthetic_data=True))
        tid,bid=ref.split(':');resource=dict(sandbox_id=sid,template_id=tid,build_id=bid,template_ref=ref,owned=True,state='creating')
        engine.ledger.record('sandbox',resource,SCOPE,run['run_id']);engine.save()
    engine.own('sandbox',resource)
    if resource.get('deleted') or driver.sandbox_detail(run['sandbox_id']) is None:
        raise RuntimeError('本轮订单沙箱已不存在；请先清理，不会换实例伪装原记录')
    if config['orders_template_ref']!=run['template_ref'] or config['orders_user']!=run['user'] or settings(config)!=run['settings']:
        raise RuntimeError('配置已变更，请清理后开始新一轮')
    if run['source_hashes']!=source_hashes():raise RuntimeError('报表工具已变化，需清理后开始新实验')
    engine.wait_state(driver,resource,'running')
    if case!='orders_prepare' and not run.get('installed'):raise RuntimeError('请执行订单环境检查，不能仅准备状态')
    if case in ('orders_train','orders_evaluate','orders_checkpoint') and not run.get('calibration'):raise RuntimeError('请先执行训练前基线')
    if case in ('orders_evaluate','orders_checkpoint') and len(run['history'])<run['settings']['rounds']:raise RuntimeError('请先完成训练，可接续已完成批次')
    if case=='orders_checkpoint' and not run.get('comparison'):raise RuntimeError('请先执行留出文件评估')
    return run


def rule_action(dataset):
    if dataset['rows']<=2000:return 0
    return 1 if dataset['group']=='category' else 3


def greedy(weights,task):return max(range(4),key=lambda a:policy.probabilities(weights,task)[a])


def job(task,seed,split,action,identifier,**extra):return dict(id=identifier,task=task,action=action,dataset=spec(task,seed,split),**extra)


def collect(engine,driver,run,jobs,progress=None):
    rows=[]
    for offset in range(0,len(jobs),6):
        if engine.stop.is_set():raise RuntimeError('已停止，完成的训练参数保留')
        rows.extend(measure(driver,run,jobs[offset:offset+6]))
        if progress:progress(rows)
        engine.log(f'订单报表：实测完成 {len(rows)}/{len(jobs)} 次执行')
    return rows


def compare(rows):
    result={}
    for name in ('initial','rule','trained'):
        subset=[r for r in rows if r.get('route')==name]
        if subset:
            result[name]=dict(count=len(subset),correct=sum(r['correct'] for r in subset),
                mean_reward=statistics.mean(r['reward'] for r in subset),mean_wall_s=statistics.mean(r['wall_s'] for r in subset),
                mean_peak_rss_mib=statistics.mean(r['peak_rss_mib'] for r in subset))
    if 'trained' in result and 'rule' in result:
        delta=result['trained']['mean_reward']-result['rule']['mean_reward']
        result['reward_delta_vs_rule']=delta;result['outcome']='better' if delta>.01 else 'worse' if delta<-.01 else 'similar'
    return result


def summary(run):
    from .evidence import view
    comparison=run.get('comparison',{})
    shown=comparison or compare(run.get('calibration') or [])
    metrics=[{'label':'真实参数更新','value':len(run['history'])},{'label':'训练采样执行','value':len(run['history'])*6},
        {'label':'留出评估','value':'完成' if comparison else '尚未执行'}]
    table=[]
    for name,label in [('initial','未训练策略'),('rule','固定规则'),('trained','RL策略')]:
        if name in shown:
            r=shown[name];table.append(dict(route=label,correct=f'{r["correct"]}/{r["count"]}',reward=f'{r["mean_reward"]:.4f}',
                time=f'{r["mean_wall_s"]*1000:.1f} ms',memory=f'{r["mean_peak_rss_mib"]:.1f} MiB'))
    presentation={'metrics':metrics,'table':{'columns':[{'key':k,'label':v} for k,v in [('route','策略'),('correct','报表正确'),('reward','平均reward'),('time','进程平均耗时'),('memory','平均进程峰值RSS')]],'rows':table},
        'series':{'label':'训练采样平均reward（不是留出成绩）','points':[{'x':x['step'],'y':x['mean_reward']} for x in run['history']]}}
    return dict(sandbox_id=run['sandbox_id'],scenario=SCOPE,trainer='stdlib_cpu_reinforce',training_performed=bool(run['history']),
        weights=run['weights'],parameter_sha256=policy.fingerprint(run['weights']),optimizer_steps=len(run['history']),
        history=run['history'],comparison=comparison,evaluation=run.get('evaluation'),calibration=run.get('calibration'),
        display=view(run),measurement_split='heldout' if comparison else 'calibration' if run.get('calibration') else None,
        synthetic_data=True,rule=RULE,source_hashes=run['source_hashes'],presentation=presentation,
        note='模拟业务CSV，真实沙箱执行和CPU参数训练；固定工具路由，非LLM/Miles。正确性优先；时间和内存为子进程指标，不含SDK网络和CSV生成。')


def measure_controls(engine,driver,run):
    # No policy update: equal initial logits, greedy tie-break picks memory.
    initial=policy.initial_weights();jobs=[]
    for i,task in enumerate(policy.TASKS):
        dataset=spec(task,101+i,'calibration')
        for route,action in [('initial',greedy(initial,task)),('rule',rule_action(dataset))]:
            jobs.append(job(task,101+i,'calibration',action,task+'-'+route,route=route))
    run['calibration']=collect(engine,driver,run,jobs);engine.save()
    return summary(run)


def train_round(engine,driver,run):
    index=len(run['history']);rng=random.Random(str(run['settings']['seed'])+':orders:'+str(index));jobs=[]
    for i,task in enumerate(policy.TASKS):
        for repeat in range(2):
            action=policy.sample_action(run['weights'],task,rng)
            jobs.append(job(task,200000+index*3+i,'train',action,f'train-{index}-{task}-{repeat}'))
    rng.shuffle(jobs)
    observations=collect(engine,driver,run,jobs)
    if engine.stop.is_set():raise RuntimeError('已停止，本批次未提交参数更新')
    before=policy.fingerprint(run['weights'])
    weights,norm=policy.update(run['weights'],observations,run['settings']['learning_rate'])
    run['weights']=weights;run.pop('comparison',None);run.pop('evaluation',None)
    run['history'].append(dict(step=index+1,mean_reward=statistics.mean(o['reward'] for o in observations),gradient_norm=norm,
        parameters_before_sha256=before,parameters_after_sha256=policy.fingerprint(weights),samples=observations))
    engine.save();engine.log(f'订单策略 第{index+1}轮：reward={run["history"][-1]["mean_reward"]:.4f}，gradient={norm:.5f}')
    if engine.job:engine.job['result']=engine.safe(summary(run));engine.save()


def evaluate_routes(engine,driver,run):
    jobs=[]
    for seed_index,seed in enumerate((900001,900107)):
        for task in policy.TASKS:
            dataset=spec(task,seed,'heldout')
            routes=[('initial',greedy(policy.initial_weights(),task)),('rule',rule_action(dataset)),('trained',greedy(run['weights'],task))]
            for repeat in range(2):
                order=routes[seed_index:]+routes[:seed_index]
                if repeat:order=list(reversed(order))
                for route,action in order:jobs.append(job(task,seed,'heldout',action,f'eval-{seed}-{task}-{repeat}-{route}',route=route,repeat=repeat))
    run.pop('comparison',None);run.pop('evaluation',None);run['partial_evaluation']=[];engine.save()
    def partial(rows):run['partial_evaluation']=rows;engine.save()
    rows=collect(engine,driver,run,jobs,partial)
    trained_inputs={s['dataset_sha256'] for row in run['history'] for s in row['samples']}
    if any(r['dataset_sha256'] in trained_inputs for r in rows):raise RuntimeError('Heldout dataset leaked into training')
    run['evaluation']=rows;run['comparison']=compare(rows);run.pop('partial_evaluation',None);engine.save()
    return summary(run)


def execute(engine,driver,case):
    run=prepare(engine,driver,case)
    if case=='orders_cleanup':
        deleted=[]
        for r in engine.state['sandboxes']:
            if r.get('scope')!=SCOPE or r.get('run_id')!=run.get('run_id') or r.get('deleted'):continue
            engine.own('sandbox',r)
            result=driver.delete_sandbox(r['sandbox_id']) if driver.sandbox_detail(r['sandbox_id']) else {'sandbox_id':r['sandbox_id'],'detail_http':404}
            r['deleted']=True;deleted.append(result);engine.save()
        if run:run['deleted']=True;engine.save()
        return dict(deleted=deleted,customer_templates_preserved=True)
    if case=='orders_prepare':
        if not run.get('installed'):
            run['environment']=install(driver,run);run['installed']=True;engine.save()
        return dict(**summary(run),environment=run['environment'],profiles=PROFILES)
    if case=='orders_baseline':
        if run['history']:raise RuntimeError('已有训练更新，不能覆盖初始基线')
        return measure_controls(engine,driver,run)
    if case=='orders_train':
        while len(run['history'])<run['settings']['rounds']:
            if engine.stop.is_set():raise RuntimeError('已停止，可接续下一批次')
            train_round(engine,driver,run)
        return summary(run)
    if case=='orders_evaluate':
        return evaluate_routes(engine,driver,run)
    checkpoint=dict(format='agentsphere-order-router-v1',tasks=list(policy.TASKS),actions=list(policy.ACTIONS),weights=run['weights'],settings=run['settings'],
        optimizer_steps=len(run['history']),source_hashes=run['source_hashes'],parameter_sha256=policy.fingerprint(run['weights']),rule=RULE,reward_version=run['reward_version'])
    directory=engine.config.directory/'artifacts'/run['run_id'];directory.mkdir(parents=True,exist_ok=True);path=directory/'order-router-model.json'
    path.write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');loaded=json.loads(path.read_text(encoding='utf-8'))
    policy.validate_weights(loaded['weights'])
    if policy.fingerprint(loaded['weights'])!=checkpoint['parameter_sha256']:raise RuntimeError('Checkpoint parameters differ')
    if any(greedy(loaded['weights'],t)!=greedy(run['weights'],t) for t in policy.TASKS):raise RuntimeError('Checkpoint policy differs')
    rows=collect(engine,driver,run,[job(t,900107,'heldout',greedy(loaded['weights'],t),'reload-'+t,route='reloaded') for t in policy.TASKS])
    if not all(r['correct'] for r in rows):raise RuntimeError('Restored model produced incorrect report')
    # Real timing/reward naturally varies. Do NOT demand identical wall times.
    run['checkpoint_verified']=True;run['reload_results']=rows;engine.save()
    report=dict(model=checkpoint,comparison=run['comparison'],heldout_results=run['evaluation'],reload_results=rows,synthetic_data=True)
    artifact=json.dumps(report,ensure_ascii=False,indent=2)+'\n';(directory/'order-report-evidence.json').write_text(artifact,encoding='utf-8')
    return dict(**summary(run),artifact=artifact,artifact_path='order-report-evidence.json',sha256=hashlib.sha256(artifact.encode()).hexdigest(),
        model_path=str(path),reload_verified=True,reload_results=rows)
