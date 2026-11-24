"""Miles custom_rm entry point. Async signature verified against the pinned source."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import os
from threading import BoundedSemaphore,Lock

from .evaluator import evaluate_candidate
from .task import TASK_ID

UPSTREAM_COMMIT='2f627e0887f26a5a39a749e2d71b5b3c7c9db003'
CUSTOM_RM_PATH='studio.scenarios.miles_rl.reward.reward'
_context=ContextVar('agentsphere_miles_evaluator',default=None)
_locks={};_guard=Lock()


@contextmanager
def reward_context(evaluator):
    """Studio injects its real SDK/ledger; external Miles uses environment config."""
    token=_context.set(evaluator)
    try:yield
    finally:_context.reset(token)


def environment_evaluator(source,task_id):
    from ...sdk import SDK
    from ...config import DEFAULTS
    count=int(os.environ.get('AGENTSPHERE_RL_CONCURRENCY','2'))
    if not 1<=count<=8:raise ValueError('AGENTSPHERE_RL_CONCURRENCY must be 1..8 per worker process')
    timeout=int(os.environ.get('AGENTSPHERE_RL_CASE_TIMEOUT','3'))
    if not 1<=timeout<=10:raise ValueError('AGENTSPHERE_RL_CASE_TIMEOUT must be 1..10 seconds')
    with _guard:semaphore=_locks.setdefault(count,BoundedSemaphore(count))
    config={**DEFAULTS,'api_key':os.environ['E2B_API_KEY'],
        'api_url':os.environ['E2B_API_URL'],'gateway_url':os.environ['E2B_SANDBOX_URL'],
        'sandbox_timeout':600}
    reference=os.environ['AGENTSPHERE_RL_TEMPLATE_REF']
    if len(reference.split(':'))!=2:raise ValueError('Use fixed templateID:buildID')
    with semaphore:
        return evaluate_candidate(SDK(config),reference,source,task_id=task_id,
            user=os.environ.get('AGENTSPHERE_RL_USER','sandbox'),
            case_timeout=timeout,cleanup=True)


async def reward(args,sample,**kwargs):
    """Return float; never set sample.reward (Miles assigns the returned value)."""
    metadata=sample.metadata if isinstance(sample.metadata,dict) else {}
    task_id=metadata.get('agentsphere_task_id')
    if task_id!=TASK_ID:raise ValueError('Sample.metadata.agentsphere_task_id must be '+TASK_ID)
    evaluator=_context.get() or environment_evaluator
    result=await asyncio.to_thread(evaluator,sample.response,task_id)
    sample.metadata={**metadata,'agentsphere_reward_evidence':{
        k:result.get(k) for k in ('task_id','sandbox_id','reward','passed','total','candidate_sha256','elapsed_s','candidate_error')}}
    return float(result['reward'])
