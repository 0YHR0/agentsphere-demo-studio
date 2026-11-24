"""CLI uses the same registry, preparation, driver and resource ledger as the UI."""
import argparse
import json
import time
from pathlib import Path

from .core.registry import get_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='.local/cli')
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('list')
    describe = subs.add_parser('describe'); describe.add_argument('case')
    run = subs.add_parser('run'); run.add_argument('case'); run.add_argument('--prepare', action='store_true')
    report = subs.add_parser('report'); report.add_argument('--format', choices=('json','markdown'), default='json')
    args = parser.parse_args()
    registry = get_registry()
    if args.command == 'list':
        print(json.dumps(list(registry.actions.values()), ensure_ascii=False, indent=2)); return
    if args.command == 'describe':
        if args.case not in registry.actions: parser.error('Unknown case: ' + args.case)
        print(registry.package_for(args.case).source(args.case)); return
    from .config import Config
    from .engine import Engine
    engine = Engine(Config(Path(args.data_dir)))
    if args.command == 'report':
        value = engine.export_report()
        if args.format == 'markdown':
            from .core.reporting import markdown_report
            print(markdown_report(value))
        else: print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    engine.start(args.case, 'prepare' if args.prepare else 'run')
    try:
        while engine.job: time.sleep(.2)
    except KeyboardInterrupt:
        engine.stop.set()
        raise SystemExit('停止等待；已提交的云端操作与资源保留')
    job = engine.state['jobs'][-1]
    print(json.dumps(engine.safe(job), ensure_ascii=False, indent=2))
    raise SystemExit(0 if job['status'] in ('passed','skipped') else 1)


if __name__ == '__main__':
    main()
