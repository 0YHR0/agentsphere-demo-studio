"""Read a tiny order-router model/evidence file. No program/cloud execution."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from studio.scenarios.order_reports import policy


def load(path):
    data=json.loads(path.read_text(encoding='utf-8'));data=data.get('model',data)
    if data.get('format')!='agentsphere-order-router-v1' or data.get('tasks')!=list(policy.TASKS) or data.get('actions')!=list(policy.ACTIONS):
        raise ValueError('Unsupported order-router model')
    policy.validate_weights(data['weights'])
    if policy.fingerprint(data['weights'])!=data.get('parameter_sha256'):raise ValueError('Parameter hash mismatch')
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',type=Path,required=True);parser.add_argument('--profile',choices=policy.TASKS,default='daily')
    args=parser.parse_args();model=load(args.model);p=policy.probabilities(model['weights'],args.profile)
    print(json.dumps(dict(profile=args.profile,probabilities=dict(zip(policy.ACTIONS,p)),selected=policy.ACTIONS[max(range(4),key=p.__getitem__)],optimizer_steps=model['optimizer_steps']),indent=2))
