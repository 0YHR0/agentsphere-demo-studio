"""Real cloud reward smoke; optional dispatch through an installed Miles framework."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from studio.scenarios.miles_rl.reward import CUSTOM_RM_PATH,reward
from studio.scenarios.miles_rl.task import PROMPT,TASK_ID,builtin_candidates


async def run(options):
    source=options.source.read_text(encoding='utf-8') if options.source else builtin_candidates(2)[1]['code']
    values=dict(prompt=PROMPT,response=source,metadata={'agentsphere_task_id':TASK_ID})
    if options.with_miles:
        # Imports intentionally deferred: the local demo doesn't require GPU packages.
        from miles.utils.types import Sample
        from miles.utils.args.custom_view import ImmutableNamespace
        from miles.utils.args.custom_function import CustomFunctionConfig
        from miles.rollout.rm_hub import async_rm
        sample=Sample(**values)
        args=ImmutableNamespace(custom_rm_path=CustomFunctionConfig(path=CUSTOM_RM_PATH),rm_type='')
        value=await async_rm(args,sample)
    else:
        sample=SimpleNamespace(**values,reward=None)
        value=await reward(None,sample)
    assert sample.reward is None,'Miles is responsible for assigning sample.reward'
    print(json.dumps(dict(reward=value,evidence=sample.metadata['agentsphere_reward_evidence'],
        dispatch='Miles async_rm' if options.with_miles else 'direct hook contract',
        training_performed=False),ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-miles',action='store_true',help='Use real Miles imports; requires the documented Miles environment')
    parser.add_argument('--source',type=Path,help='Candidate source file; executed only in AgentSphere')
    asyncio.run(run(parser.parse_args()))
