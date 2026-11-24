"""Versioned demonstration task; expected results are computed only on the host."""
import ast
import hashlib
import re

TASK_ID='sum_even_v1'
PROMPT='''Write a Python 3 program using only the standard library.
Read one JSON object from stdin: {"values": [integers]}.
Print exactly one JSON object: {"result": sum_of_all_even_integers}.
Include negative even integers and zero. An empty list has sum 0.
Return only Python source code, optionally in one ```python fenced block.
Do not explain, read files, use network, or run external commands.'''


def cases(task_id=TASK_ID):
    if task_id!=TASK_ID: raise ValueError('Unknown AgentSphere reward task: '+str(task_id))
    values=[[],[1,3,5],[2,4,6],[-4,-3,2,5],[0,-2,8],[-10,1,8,11]]
    return [dict(id=f'case-{i+1}',input={'values':v},expected={'result':sum(x for x in v if x%2==0)}) for i,v in enumerate(values)]


def extract_code(text):
    if not isinstance(text,str) or not text.strip(): raise ValueError('Candidate response must contain Python source')
    code=text.strip()
    match=re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```\s*',code,re.S)
    if match: code=match.group(1)
    if len(code.encode('utf-8'))>32768: raise ValueError('Candidate exceeds 32 KiB')
    return code+'\n'


def candidate(source,index,origin):
    code=extract_code(source)
    try: ast.parse(code);invalid=None
    except SyntaxError as e: invalid=f'SyntaxError at line {e.lineno}'
    return dict(id=f'candidate-{index+1}',code=code,sha256=hashlib.sha256(code.encode()).hexdigest(),
                origin=origin,invalid_syntax=invalid)


def builtin_candidates(count):
    codes=[
        'import json,sys\nv=json.load(sys.stdin)["values"]\nprint(json.dumps({"result":sum(v)}))',
        'import json,sys\nv=json.load(sys.stdin)["values"]\nprint(json.dumps({"result":sum(x for x in v if x%2==0)}))',
        'import json,sys\nv=json.load(sys.stdin)["values"]\nprint(json.dumps({"result":sum(x for x in v if x>0 and x%2==0)}))',
        'raise RuntimeError("intentional negative control")',
    ]
    return [candidate(code,i,'builtin_control_not_model') for i,code in enumerate(codes[:count])]
