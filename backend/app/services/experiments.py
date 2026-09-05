from __future__ import annotations
import itertools, numpy as np
from app.services.backtest import run_backtest, run_adaptive_meta
from app.services.features import build_feature_panel

def parameter_sweep(base=None,grid=None,panel=None):
    base=base or {}
    grid=grid or {"long_count":[10,20,30],"short_count":[10,20,30],"rebalance_days":[5,10,21]}
    panel=build_feature_panel() if panel is None else panel
    keys=list(grid);rows=[]
    for vals in itertools.product(*(grid[k] for k in keys)):
        p=base|dict(zip(keys,vals));r=run_backtest(p,panel=panel)
        rows.append({"params":p,**r["metrics"]})
    rows.sort(key=lambda x:x["sharpe"],reverse=True)
    return {"count":len(rows),"best":rows[0] if rows else None,"results":rows}

def robustness(base=None,panel=None,adaptive=False):
    base=base or {}
    panel=build_feature_panel() if panel is None else panel
    runner=(lambda p:run_adaptive_meta(p,panel=panel)) if adaptive else (lambda p:run_backtest(p,panel=panel))
    c=float(base.get("commission_bps",6));s=float(base.get("slippage_bps",5))
    scenarios=[
        ("base",{}),("costs_x2",{"commission_bps":c*2,"slippage_bps":s*2}),("costs_x3",{"commission_bps":c*3,"slippage_bps":s*3}),
        ("weekly",{"rebalance_days":5}),("biweekly",{"rebalance_days":10}),("monthly",{"rebalance_days":21}),
        ("tb10",{"long_count":10,"short_count":10}),("tb20",{"long_count":20,"short_count":20}),("tb30",{"long_count":30,"short_count":30}),
        ("gross_1",{"gross_exposure":1.0}),("gross_15",{"gross_exposure":1.5}),
    ]
    rows=[]
    for name,override in scenarios:
        r=runner(base|override);rows.append({"scenario":name,**r["metrics"]})
    sharpes=[x["sharpe"] for x in rows];positive=sum(x>0 for x in sharpes)/len(sharpes)
    stressed=[x for x in rows if x["scenario"] in ("costs_x2","costs_x3")]
    cost_stress_pass=all(x["sharpe"]>0 for x in stressed)
    return {"scenarios":rows,"summary":{"positive_sharpe_ratio":positive,"median_sharpe":float(np.median(sharpes)),
            "min_sharpe":float(np.min(sharpes)),"cost_stress_pass":cost_stress_pass,"passed":positive>=.7 and cost_stress_pass}}
