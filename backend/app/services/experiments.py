from __future__ import annotations
import itertools, numpy as np
from app.services.backtest import run_backtest
from app.services.features import build_feature_panel

def parameter_sweep(base=None,grid=None):
    base=base or {}
    grid=grid or {"long_count":[10,20,30],"short_count":[10,20,30],"rebalance_days":[5,10,21]}
    panel=build_feature_panel()
    keys=list(grid); rows=[]
    for vals in itertools.product(*(grid[k] for k in keys)):
        p=base|dict(zip(keys,vals)); r=run_backtest(p,panel=panel)
        rows.append({"params":p,**r["metrics"]})
    rows.sort(key=lambda x:x["sharpe"],reverse=True)
    return {"count":len(rows),"best":rows[0] if rows else None,"results":rows}

def robustness(base=None):
    base=base or {}
    panel=build_feature_panel()
    scenarios=[
        ("base",{}),("costs_x2",{"commission_bps":12,"slippage_bps":10}),("costs_x3",{"commission_bps":18,"slippage_bps":15}),
        ("weekly",{"rebalance_days":5}),("biweekly",{"rebalance_days":10}),("monthly",{"rebalance_days":21}),
        ("tb10",{"long_count":10,"short_count":10}),("tb20",{"long_count":20,"short_count":20}),("tb30",{"long_count":30,"short_count":30}),
        ("gross_1",{"gross_exposure":1.0}),("gross_15",{"gross_exposure":1.5}),
    ]
    rows=[]
    for name,override in scenarios:
        r=run_backtest(base|override,panel=panel)
        rows.append({"scenario":name,**r["metrics"]})
    sharpes=[x["sharpe"] for x in rows]
    positive=sum(x>0 for x in sharpes)/len(sharpes)
    return {"scenarios":rows,"summary":{"positive_sharpe_ratio":positive,"median_sharpe":float(np.median(sharpes)),
            "min_sharpe":float(np.min(sharpes)),"passed":positive>=.7}}
