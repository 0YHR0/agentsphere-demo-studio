"""A 12-parameter report-routing contextual bandit; standard-library CPU REINFORCE."""
import hashlib
import json
import math

TASKS=('daily','monthly','customer')
ACTIONS=('memory','stream','chunk','sqlite')


def initial_weights():
    return [[0.0]*len(ACTIONS) for _ in TASKS]


def validate_weights(weights):
    if (not isinstance(weights,list) or len(weights)!=len(TASKS) or
        any(not isinstance(row,list) or len(row)!=len(ACTIONS) or
            any(type(x) not in (int,float) or not math.isfinite(x) for x in row) for row in weights)):
        raise ValueError('Invalid CPU policy weights')


def probabilities(weights,task):
    row=weights[TASKS.index(task)];peak=max(row)
    values=[math.exp(x-peak) for x in row];total=sum(values)
    return [v/total for v in values]


def sample_action(weights,task,rng):
    return rng.choices(range(len(ACTIONS)),weights=probabilities(weights,task),k=1)[0]


def update(weights,samples,learning_rate):
    """Gradient ascent with leave-one-out baseline; only (task,action,reward) inputs.

    Each task has two independent on-policy samples. The other sample's reward
    is a baseline independent of this sample's action. Gradients use PRE-update
    probabilities; update is simultaneous, not sequential within the batch.
    """
    validate_weights(weights)
    gradients=[[0.0]*len(ACTIONS) for _ in TASKS]
    groups={task:[s for s in samples if s['task']==task] for task in TASKS}
    if any(len(group)!=2 for group in groups.values()):raise ValueError('Two samples per task required')
    for task,group in groups.items():
        p=probabilities(weights,task);row=gradients[TASKS.index(task)]
        for index,sample in enumerate(group):
            action=sample['action'];r=sample['reward'];other=group[1-index]['reward']
            if type(action) is not int or not 0<=action<len(ACTIONS) or not 0<=r<=1 or not 0<=other<=1:
                raise ValueError('Invalid policy sample')
            advantage=r-other
            for j in range(len(ACTIONS)):row[j]+=advantage*((1 if j==action else 0)-p[j])/len(samples)
    new=[[value+learning_rate*g for value,g in zip(row,gradient)] for row,gradient in zip(weights,gradients)]
    validate_weights(new)
    return new,math.sqrt(sum(g*g for row in gradients for g in row))


def fingerprint(weights):
    validate_weights(weights)
    return hashlib.sha256(json.dumps(weights,separators=(',',':')).encode()).hexdigest()
