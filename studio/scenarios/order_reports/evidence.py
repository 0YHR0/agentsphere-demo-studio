"""Read-only views of recorded observations. No SDK calls or new measurements."""
import math
from . import policy


def training_trace(run):
    weights=policy.initial_weights();trace=[]
    for row in run.get('history',[]):
        if policy.fingerprint(weights)!=row['parameters_before_sha256']:
            raise ValueError('Training history before-hash mismatch')
        before=[policy.probabilities(weights,task) for task in policy.TASKS]
        weights,norm=policy.update(weights,row['samples'],run['settings']['learning_rate'])
        if (policy.fingerprint(weights)!=row['parameters_after_sha256'] or
            not math.isclose(norm,row['gradient_norm'],rel_tol=1e-10,abs_tol=1e-12)):
            raise ValueError('Training history update mismatch')
        after=[policy.probabilities(weights,task) for task in policy.TASKS]
        trace.append(dict(step=row['step'],mean_reward=row['mean_reward'],before=before,after=after,
            delta_pp=[[100*(b-a) for a,b in zip(old,new)] for old,new in zip(before,after)]))
    if trace and policy.fingerprint(weights)!=policy.fingerprint(run['weights']):
        raise ValueError('Training history final-hash mismatch')
    return trace


def view(run):
    from .workflow import compare
    controls=compare(run.get('calibration') or [])
    try:
        return dict(control_calibration=controls,trace=training_trace(run),trace_verified=True)
    except (ValueError,KeyError,TypeError) as exc:
        # Old or damaged evidence must not turn into invented probability changes.
        return dict(control_calibration=controls,trace=[],trace_verified=False,trace_error=str(exc))
