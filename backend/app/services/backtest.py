from __future__ import annotations
import math
import numpy as np
import pandas as pd
from app.services.features import build_feature_panel, panel_metadata

DEFAULTS={"long_count":20,"short_count":20,"rebalance_days":5,"commission_bps":6.0,"slippage_bps":5.0,"gross_exposure":2.0}
BASELINE_DEFAULTS=DEFAULTS|{"long_count":20,"short_count":20}

def _metrics(curve,equity,turnovers,periods_per_year):
    returns=pd.Series([x["return"] for x in curve],dtype=float)
    if len(returns)<2: raise ValueError("Not enough data")
    years=len(returns)/periods_per_year
    cagr=equity**(1/max(years,1e-9))-1
    vol=returns.std(ddof=1)*math.sqrt(periods_per_year)
    ann=returns.mean()*periods_per_year
    downside=returns[returns<0].std(ddof=1)*math.sqrt(periods_per_year) if (returns<0).sum()>1 else np.nan
    sharpe=ann/(vol+1e-12)
    sortino=ann/(downside+1e-12) if np.isfinite(downside) else np.nan
    eq=pd.Series([x["equity"] for x in curve],dtype=float)
    dd=eq/eq.cummax()-1
    max_dd=float(dd.min())
    calmar=cagr/abs(max_dd) if max_dd<0 else np.nan
    return {"total_return":round(equity-1,4),"cagr":round(float(cagr),4),"sharpe":round(float(sharpe),3),
            "sortino":None if not np.isfinite(sortino) else round(float(sortino),3),
            "calmar":None if not np.isfinite(calmar) else round(float(calmar),3),
            "volatility":round(float(vol),4),"max_drawdown":round(max_dd,4),
            "avg_turnover_per_rebalance":round(float(np.mean(turnovers)),4),"rebalance_count":len(curve)}

def run_backtest(params:dict|None=None, score_column="meta_score", strategy_name="META US v2", panel=None)->dict:
    p=DEFAULTS|(params or {})
    df=(build_feature_panel() if panel is None else panel).copy().sort_values(["date","symbol"])
    all_dates=np.array(sorted(df.date.unique()))
    if len(all_dates)<280: raise ValueError("Not enough history for warm-up and out-of-sample backtest")
    signal_dates=list(all_dates[260::int(p["rebalance_days"])])
    equity=1.0; curve=[]; turnovers=[]; prev_weights={}; trade_rows=[]; gross_pnl=[]; costs=[]
    by_date={d:x.set_index("symbol") for d,x in df.groupby("date")}
    date_pos={d:i for i,d in enumerate(all_dates)}
    # Signal is formed using close T. Entry is next trading day's open.
    for idx,signal_d in enumerate(signal_dates[:-1]):
        next_signal=signal_dates[idx+1]
        ep=date_pos[signal_d]+1
        xp=date_pos[next_signal]+1
        if ep>=len(all_dates) or xp>=len(all_dates): break
        entry_d, exit_d=all_dates[ep], all_dates[xp]
        snap=by_date[signal_d].sort_values(score_column,ascending=False)
        longs=snap.head(int(p["long_count"])); shorts=snap.tail(int(p["short_count"]))
        if longs.empty or shorts.empty: continue
        leg=float(p["gross_exposure"])/2
        weights={s:leg/len(longs) for s in longs.index}
        weights.update({s:-leg/len(shorts) for s in shorts.index})
        turnover=sum(abs(weights.get(s,0)-prev_weights.get(s,0)) for s in set(prev_weights)|set(weights))
        cost=turnover*((float(p["commission_bps"])+float(p["slippage_bps"]))/10000)
        entry=by_date.get(entry_d); exit_=by_date.get(exit_d)
        if entry is None or exit_ is None: continue
        gross_ret=0.0
        for s,w in weights.items():
            if s in entry.index and s in exit_.index:
                p0=float(entry.loc[s,"open"]); p1=float(exit_.loc[s,"open"])
                if p0<=0: continue
                asset_ret=p1/p0-1
                contrib=w*asset_ret
                gross_ret+=contrib
                trade_rows.append({"signal_date":str(pd.Timestamp(signal_d).date()),"entry_date":str(pd.Timestamp(entry_d).date()),
                                   "exit_date":str(pd.Timestamp(exit_d).date()),"symbol":s,"side":"LONG" if w>0 else "SHORT",
                                   "weight":round(w,4),"asset_return":round(asset_ret,6),"contribution":round(contrib,6)})
        net_ret=gross_ret-cost
        equity*=1+net_ret
        curve.append({"date":str(pd.Timestamp(exit_d).date()),"equity":round(equity,6),"return":net_ret,
                      "gross_return":gross_ret,"cost":cost})
        turnovers.append(turnover); gross_pnl.append(gross_ret); costs.append(cost); prev_weights=weights
    metrics=_metrics(curve,equity,turnovers,252/int(p["rebalance_days"]))
    metrics["gross_return_sum"]=round(float(np.sum(gross_pnl)),4)
    metrics["costs_sum"]=round(float(np.sum(costs)),4)
    try:
        ic=df.groupby("date").apply(lambda x:x[score_column].corr(x["future_relative_20d"],method="spearman"),include_groups=False).mean()
    except Exception: ic=np.nan
    metrics["mean_rank_ic_20d"]=None if not np.isfinite(ic) else round(float(ic),4)
    rank_sample=df[df.date==df.date.max()].sort_values(score_column,ascending=False)
    return {"strategy":strategy_name,"score_column":score_column,"params":p,"dataset":panel_metadata(df),"execution_timing":"signal_close_T__entry_open_T1",
            "metrics":metrics,"equity_curve":curve,
            "ranking_top":[{"rank":i+1,"symbol":r.symbol,"sector":r.sector,"score":round(float(getattr(r,score_column)),4)} for i,r in enumerate(rank_sample.head(30).itertuples())],
            "ranking_bottom":[{"rank":len(rank_sample)-29+i,"symbol":r.symbol,"sector":r.sector,"score":round(float(getattr(r,score_column)),4)} for i,r in enumerate(rank_sample.tail(30).itertuples())],
            "sample_trades":trade_rows[-100:]}

def run_momentum_baseline(params=None,panel=None):
    return run_backtest(params,score_column="momentum_12_1_rank",strategy_name="Momentum 12-1 baseline",panel=panel)
