from __future__ import annotations
from itertools import product
from app.services.backtest import run_backtest


def parameter_sweep(base: dict, grid: dict) -> dict:
    keys=list(grid)
    combos=list(product(*[grid[k] for k in keys]))
    runs=[]
    for vals in combos:
        cfg=dict(base); cfg.update(dict(zip(keys,vals)))
        result=run_backtest(cfg)
        m=result['metrics']
        runs.append({'params':{k:cfg[k] for k in keys},'metrics':m})
    runs.sort(key=lambda x:(x['metrics'].get('sharpe') or -999),reverse=True)
    return {'count':len(runs),'best':runs[0] if runs else None,'runs':runs}


def robustness(base: dict) -> dict:
    scenarios=[
      ('base',{}),('cost_x2',{'commission_bps':base.get('commission_bps',6)*2,'slippage_bps':base.get('slippage_bps',5)*2}),
      ('cost_x3',{'commission_bps':base.get('commission_bps',6)*3,'slippage_bps':base.get('slippage_bps',5)*3}),
      ('weekly',{'rebalance_days':5}),('biweekly',{'rebalance_days':10}),('monthly',{'rebalance_days':21}),
      ('tb10',{'long_count':10,'short_count':10}),('tb20',{'long_count':20,'short_count':20}),('tb30',{'long_count':30,'short_count':30}),
    ]
    out=[]
    for name,overrides in scenarios:
        cfg=dict(base);cfg.update(overrides)
        r=run_backtest(cfg);out.append({'scenario':name,'params':overrides,'metrics':r['metrics']})
    sharpes=[x['metrics'].get('sharpe',0) or 0 for x in out]
    positive=sum(s>0 for s in sharpes)
    return {'scenarios':out,'summary':{'positive_sharpe_ratio':positive/len(out),'min_sharpe':min(sharpes),'median_sharpe':sorted(sharpes)[len(sharpes)//2],'passed':positive/len(out)>=0.7}}
