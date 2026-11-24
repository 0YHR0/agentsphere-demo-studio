import asyncio
import hashlib
import json
import math
from pathlib import Path
import shlex
import statistics
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

from .evaluator import evaluate_candidate
from .reward import CUSTOM_RM_PATH,UPSTREAM_COMMIT,reward,reward_context
from .task import PROMPT,TASK_ID,builtin_candidates,candidate


def validate_settings(config,case,mode):
    if case=='miles_cleanup':return
    if config['miles_candidate_mode'] not in ('model','builtin'):
        raise ValueError('请选择实时模型或内置对照模式')
    try:
        count=int(config['miles_candidate_count']);timeout=int(config['miles_case_timeout_s'])
    except ValueError:raise ValueError('候选数量与子进程时限必须为整数') from None
    if not 2<=count<=4 or not 1<=timeout<=10:
        raise ValueError('候选数量2–4，每个测试时限1–10秒')
    if config['sandbox_timeout']<60:raise ValueError('沙箱timeout至少60秒')
    if not config['miles_user'] or len(config['miles_user'])>64 or any(x in config['miles_user'] for x in ('\n','\r','\0')):
        raise ValueError('请填写镜像中已存在的单行运行用户名')
    ref=config['miles_template_ref']
    if ref:
        try:
            parts=ref.split(':')
            if len(parts)!=2:raise ValueError()
            for part in parts:UUID(part)
        except ValueError:raise ValueError('RL模板请填写固定Template ID:Build ID') from None
    elif mode!='save' and (not config['ready_template_id'] or config['template_source']=='build'):
        raise ValueError('请填RL Ready模板引用，或在环境中选择已有Ready模板；本场景不现场构建')
    url=config['miles_model_base_url']
    if url:
        u=urlsplit(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('模型Base URL需为不含凭据或查询参数的HTTPS地址')
    if case=='miles_rollout' and mode=='run' and config['miles_candidate_mode']=='model':
        if any(not config[k] for k in ('miles_model_base_url','miles_model_id','miles_model_api_key')):
            raise ValueError('实时模型模式需先填写模型Base URL、模型ID与模型API Key')


def _resource(engine,sid):
    return next((r for r in engine.state['sandboxes'] if r['sandbox_id']==sid),None)


def _listener(engine,run,role):
    def record(event,sid):
        if event=='created':
            tid,bid=run['template_ref'].split(':')
            engine.ledger.record('sandbox',dict(sandbox_id=sid,template_id=tid,build_id=bid,
                template_ref=run['template_ref'],owned=True,state='running',scene='miles_rl',role=role),
                'miles_rl',run['run_id'])
            run.setdefault('episode_ids',[]).append(sid)
        elif event=='deleted':
            resource=_resource(engine,sid)
            if resource:resource['deleted']=True
        engine.save()
    return record


def prepare(engine,driver,case):
    validate_settings(engine.config.data,case,'prepare')
    run=engine.scenario_run('miles_rl')
    if case=='miles_cleanup':return run
    resource=_resource(engine,run.get('sandbox_id'))
    if resource and resource.get('deleted'):resource=None
    if resource is None:
        if case!='miles_prepare':raise RuntimeError('请先执行“准备 RL 沙箱环境”')
        chosen=engine.config.data['miles_template_ref'] or engine.config.data['ready_template_id']
        reference=engine.resolve_template(driver,chosen)
        sid=driver.create_sandbox(reference)
        run=engine.bind_scenario('miles_rl',dict(sandbox_id=sid,template_ref=reference,
            task_id=TASK_ID,user=engine.config.data['miles_user'],case_timeout=int(engine.config.data['miles_case_timeout_s']),episode_ids=[]))
        tid,bid=reference.split(':')
        resource=dict(sandbox_id=sid,template_id=tid,build_id=bid,template_ref=reference,
                      owned=True,state='creating',scene='miles_rl',role='environment_probe')
        engine.ledger.record('sandbox',resource,'miles_rl',run['run_id']);engine.save()
    engine.own('sandbox',resource)
    if driver.sandbox_detail(resource['sandbox_id']) is None:
        raise RuntimeError('原RL环境已不存在；请清理本轮记录，不会替换原沙箱冒充同一轮')
    config=engine.config.data
    if run['user']!=config['miles_user'] or run['case_timeout']!=int(config['miles_case_timeout_s']):
        raise RuntimeError('执行用户或测试时限已改变；请清理后重新准备RL环境')
    chosen=config['miles_template_ref'] or config['ready_template_id']
    if chosen.split(':')[0]!=run['template_ref'].split(':')[0] or (':' in chosen and chosen!=run['template_ref']):
        raise RuntimeError('RL模板来源已改变，请清理本轮后重新准备')
    engine.wait_state(driver,resource,'running')
    if case!='miles_prepare' and not run.get('environment_verified'):
        raise RuntimeError('请先执行RL环境检查')
    if case in ('miles_evaluate','miles_callback','miles_export') and not run.get('candidates'):
        raise RuntimeError('请先生成候选代码；仅准备状态不会自动调用模型')
    if case in ('miles_callback','miles_export') and not run.get('evaluations'):
        raise RuntimeError('请先执行测试并计算reward')
    return run


def generate_candidates(config):
    count=int(config['miles_candidate_count'])
    if config['miles_candidate_mode']=='builtin':
        return dict(origin='builtin_control_not_model',model_calls=0,candidates=builtin_candidates(count))
    import httpx
    output=[]
    with httpx.Client(timeout=90,trust_env=False,follow_redirects=False) as client:
        for index in range(count):
            response=client.post(config['miles_model_base_url'].rstrip('/')+'/chat/completions',
                headers={'Authorization':'Bearer '+config['miles_model_api_key']},
                json={'model':config['miles_model_id'],'messages':[{'role':'user','content':PROMPT}],
                      'max_tokens':768,'temperature':.8,'stream':False})
            if response.status_code>=400:
                raise RuntimeError('模型生成请求失败，HTTP '+str(response.status_code))
            data=response.json()
            text=data['choices'][0]['message']['content']
            output.append(candidate(text,index,'live_model'))
    return dict(origin='live_model',model_calls=count,model_id=config['miles_model_id'],candidates=output)


def execute(engine,driver,case):
    run=prepare(engine,driver,case);config=engine.config.data
    if case=='miles_cleanup':
        deleted=[];errors=[]
        for resource in engine.state['sandboxes']:
            if resource.get('scope')!='miles_rl' or resource.get('run_id')!=run.get('run_id') or resource.get('deleted'):continue
            try:
                engine.own('sandbox',resource)
                if driver.sandbox_detail(resource['sandbox_id']) is None:result={'sandbox_id':resource['sandbox_id'],'detail_http':404}
                else:result=driver.delete_sandbox(resource['sandbox_id'])
                resource['deleted']=True;deleted.append(result);engine.save()
            except Exception as e:errors.append(str(e))
        if errors:raise RuntimeError('RL部分资源清理失败：'+'; '.join(errors))
        if not deleted:return {'skipped':True,'reason':'本轮没有待清理RL沙箱'}
        run['deleted']=True;engine.save()
        return {'deleted':deleted,'external_templates_preserved':True}
    if case=='miles_prepare':
        result=driver.command(run['sandbox_id'],"python3 -c 'import sys,resource; print(sys.version)' ; id",user=run['user'])
        # A failed Python check must not be hidden by a following successful id.
        driver.command(run['sandbox_id'],"python3 -c 'import json,resource,subprocess'",user=run['user'])
        run['environment_verified']=True;engine.save()
        return dict(sandbox_id=run['sandbox_id'],template_ref=run['template_ref'],user=run['user'],
                    environment=result,task=TASK_ID,training_performed=False)
    if case=='miles_rollout':
        if run.get('candidates'):raise RuntimeError('本轮候选已固定；请清理并准备新一轮，避免历史评分与新候选混淆')
        result=generate_candidates(config)
        run.update(result);engine.save()
        return dict(task=TASK_ID,prompt=PROMPT,**result,presentation={'metrics':[
            {'label':'候选来源','value':'实时模型' if result['origin']=='live_model' else '内置对照（非模型）'},
            {'label':'模型调用','value':result['model_calls']},{'label':'候选数量','value':len(result['candidates'])}]})
    if case=='miles_evaluate':
        run.pop('evaluations',None);run.pop('callback',None);engine.save()
        rows=[]
        for item in run['candidates']:
            if engine.stop.is_set():raise RuntimeError('RL评估已停止，已有候选沙箱保留')
            result=evaluate_candidate(driver,run['template_ref'],item['code'],user=run['user'],
                case_timeout=run['case_timeout'],on_resource=_listener(engine,run,'candidate'),cleanup=False)
            rows.append(dict(candidate_id=item['id'],**result))
            run['partial_evaluations']=rows;engine.save()
        mean=statistics.mean(row['reward'] for row in rows)
        for row in rows:row['centered_reward']=row['reward']-mean
        run['evaluations']=rows;run.pop('partial_evaluations',None);engine.save()
        presentation={'metrics':[{'label':'独立候选','value':len(rows)},
            {'label':'组平均 reward','value':f'{mean:.3f}'},{'label':'模型训练','value':'未执行'}],
            'table':{'columns':[{'key':'candidate_id','label':'候选'},{'key':'passed','label':'通过测试'},
                               {'key':'reward','label':'Reward'},{'key':'centered_reward','label':'组内中心化信号'},
                               {'key':'sandbox_id','label':'独立 Sandbox ID'}],
                     'rows':[dict(candidate_id=row['candidate_id'],passed=f'{row["passed"]}/{row["total"]}',
                                  reward=f'{row["reward"]:.3f}',centered_reward=f'{row["centered_reward"]:+.3f}',
                                  sandbox_id=row['sandbox_id'] or '语法错误，未创建实例') for row in rows]}}
        return dict(task=TASK_ID,origin=run['origin'],evaluations=rows,group_mean_reward=mean,presentation=presentation,
                    note='组内中心化仅用于展示反馈信号，不是完整GRPO损失或梯度更新',training_performed=False)
    if case=='miles_callback':
        item=run['candidates'][0]
        sample=SimpleNamespace(prompt=PROMPT,response=item['code'],metadata={'agentsphere_task_id':TASK_ID},reward=None)
        def evaluator(source,task_id):
            return evaluate_candidate(driver,run['template_ref'],source,task_id=task_id,user=run['user'],
                case_timeout=run['case_timeout'],on_resource=_listener(engine,run,'miles_callback'),cleanup=True)
        async def invoke():
            with reward_context(evaluator):return await reward(None,sample)
        value=asyncio.run(invoke())
        expected=run['evaluations'][0]['reward']
        if not math.isclose(value,expected):raise RuntimeError('Miles回调复测reward与前次测试不一致')
        result=dict(hook=CUSTOM_RM_PATH,miles_revision=UPSTREAM_COMMIT,returned_reward=value,
                    reward_field_unmodified=sample.reward is None,metadata=sample.metadata,
                    external_training_connected=False,training_performed=False,
                    note='实际调用同一异步hook并新建沙箱复测；未向GPU训练集群提交任务')
        result['presentation']={'metrics':[{'label':'Miles hook 返回 reward','value':f'{value:.3f}'},
            {'label':'与前次评分一致','value':'是'},{'label':'GPU参数更新','value':'未执行'}]}
        run['callback']=result;engine.save();return result
    records=[dict(task_id=TASK_ID,candidate_id=row['candidate_id'],origin=run['origin'],
        response=run['candidates'][i]['code'],reward=row['reward'],passed=row['passed'],total=row['total'],
        sandbox_id=row['sandbox_id'],candidate_sha256=row['candidate_sha256'],training_performed=False)
        for i,row in enumerate(run['evaluations'])]
    artifact='\n'.join(json.dumps(row,ensure_ascii=False) for row in records)+'\n'
    directory=engine.config.directory/'artifacts'/run['run_id'];directory.mkdir(parents=True,exist_ok=True)
    target=directory/'miles-rewards.jsonl';target.write_text(engine.safe(artifact),encoding='utf-8')
    return dict(artifact=artifact,artifact_path='miles-rewards.jsonl',sha256=hashlib.sha256(artifact.encode()).hexdigest(),
        local_artifact_path=str(target),reward_hook=CUSTOM_RM_PATH,
        hook_command='--custom-rm-path '+CUSTOM_RM_PATH,
        miles_revision=UPSTREAM_COMMIT,callback_verified=bool(run.get('callback')),training_performed=False,
        note='JSONL为奖励审计记录，不能直接作为Miles训练checkpoint或已完成训练的证明')
