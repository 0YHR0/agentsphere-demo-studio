"""Export the actual run ledger without converting errors into successes."""
import json


def export_report(engine):
    snapshot = engine.snapshot()
    jobs = snapshot['jobs']
    statuses = {j['status'] for j in jobs}
    overall = ('FAIL' if 'failed' in statuses else 'RUNNING' if 'running' in statuses else
               'INCOMPLETE' if statuses & {'interrupted','cancelled'} else 'NOT_RUN' if not jobs else
               'SKIPPED' if statuses == {'skipped'} else
               'PREPARED' if all(j.get('mode') == 'prepare' for j in jobs) else 'PASS')
    return engine.safe(dict(schema_version=1, overall=overall, sdk=snapshot['sdk'],
        session_id=snapshot['session_id'],
        summary={name: sum(j['status'] == name for j in jobs)
                 for name in ('passed', 'failed', 'skipped', 'running', 'interrupted', 'cancelled')},
        jobs=jobs, resources={k: snapshot[k] for k in ('templates', 'sandboxes')}))


def markdown_report(report):
    lines = ['# AgentSphere 本次演示记录', '', '**结论：'+report['overall']+'**', '',
             '范围为本会话保留的执行记录，不代表全部能力已验收。准备成功不代表演示动作已经执行。', '',
             '| 操作 | 模式 | 结果 | 开始时间 |', '| --- | --- | --- | --- |']
    for job in report['jobs']:
        lines.append('| ' + ' | '.join(str(job.get(k, '')).replace('|', '\\|')
                                     for k in ('case', 'mode', 'status', 'started_at')) + ' |')
    lines += ['', '## 完整脱敏记录', '', '```json', json.dumps(report, ensure_ascii=False, indent=2), '```']
    return '\n'.join(lines) + '\n'
