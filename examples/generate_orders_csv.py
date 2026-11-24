"""Generate the public demo's synthetic CSV locally, without cloud/model calls."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from studio.scenarios.order_reports.csv_data import PROFILES,spec,write_csv


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=PROFILES,default='daily');parser.add_argument('--seed',type=int,default=47)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 0<=args.seed<=1000000:parser.error('seed must be 0..1000000')
    with args.output.open('x',encoding='utf-8',newline='') as stream:write_csv(spec(args.profile,args.seed,'local-example'),stream)
    print('Created synthetic CSV:',args.output)
