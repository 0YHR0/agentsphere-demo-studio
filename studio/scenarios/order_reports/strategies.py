"""Four real implementations of the SAME integer-cent order-report contract."""
import csv
import itertools
import json
import sqlite3
import sys

KEYS=('paid_orders','gross_cents','refund_cents','net_cents')


def empty():return dict.fromkeys(KEYS,0)


def accumulate(rows,group):
    totals=empty();groups={}
    for row in rows:
        if row['status']!='paid':continue
        gross=int(row['quantity'])*int(row['unit_price_cents']);refund=int(row['refund_cents'])
        values=(1,gross,refund,gross-refund)
        for key,value in zip(KEYS,values):totals[key]+=value
        if group:
            bucket=groups.setdefault(row[group],empty())
            for key,value in zip(KEYS,values):bucket[key]+=value
    return dict(**totals,groups=groups)


def calculate(path,action,group):
    if group not in ('','category','customer_id'):raise ValueError('Unknown report type')
    with open(path,encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream)
        if action=='memory':return accumulate(list(reader),group)
        if action=='stream':return accumulate(reader,group)
        if action=='chunk':
            result=dict(**empty(),groups={})
            while True:
                batch=list(itertools.islice(reader,1024))
                if not batch:break
                part=accumulate(batch,group)
                for key in KEYS:result[key]+=part[key]
                for name,values in part['groups'].items():
                    bucket=result['groups'].setdefault(name,empty())
                    for key in KEYS:bucket[key]+=values[key]
            return result
        if action=='sqlite':
            with sqlite3.connect(':memory:') as db:
                db.execute('CREATE TABLE orders(customer_id TEXT, category TEXT, quantity INTEGER, price INTEGER, refund INTEGER, status TEXT)')
                db.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?)',((r['customer_id'],r['category'],int(r['quantity']),int(r['unit_price_cents']),int(r['refund_cents']),r['status']) for r in reader))
                expression='COUNT(*),COALESCE(SUM(quantity*price),0),COALESCE(SUM(refund),0),COALESCE(SUM(quantity*price-refund),0)'
                totals=dict(zip(KEYS,db.execute('SELECT '+expression+" FROM orders WHERE status='paid'").fetchone()))
                groups={}
                if group:
                    for row in db.execute('SELECT '+group+','+expression+" FROM orders WHERE status='paid' GROUP BY "+group):groups[row[0]]=dict(zip(KEYS,row[1:]))
                return dict(**totals,groups=groups)
        raise ValueError('Unknown strategy')


if __name__=='__main__':print(json.dumps(calculate(sys.argv[1],sys.argv[2],sys.argv[3]),separators=(',',':')))
