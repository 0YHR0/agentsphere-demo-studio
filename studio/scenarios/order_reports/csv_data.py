"""Synthetic order INPUT generator; no expected reports or rewards in this file."""
import csv

FIELDS=('order_id','customer_id','category','quantity','unit_price_cents','refund_cents','status')
PROFILES={
    'daily':dict(label='日常销售快报',rows=400,customers=40,group='',time_budget_s=.25,memory_budget_mib=32),
    'monthly':dict(label='月度商品分类汇总',rows=60000,customers=2000,group='category',time_budget_s=1.5,memory_budget_mib=48),
    'customer':dict(label='客户退款与净额对账',rows=20000,customers=2000,group='customer_id',time_budget_s=.8,memory_budget_mib=48),
}
VERSION='orders-csv-v1'


def spec(profile,seed,split):
    return dict(profile=profile,seed=seed,split=split,version=VERSION,**PROFILES[profile])


def write_csv(spec,stream):
    writer=csv.writer(stream,lineterminator='\n');writer.writerow(FIELDS)
    seed=spec['seed']
    for i in range(spec['rows']):
        quantity=(i+seed)%5+1;price=(i*37+seed*13)%9901+99
        status='cancelled' if (i+seed)%17==0 else 'paid'
        refund=quantity*price//2 if (i*3+seed)%11==0 and status=='paid' else 0
        writer.writerow((f'O{i:08d}',f'C{(i*17+seed)%spec["customers"]:06d}',f'category_{(i+seed)%8:02d}',quantity,price,refund,status))
