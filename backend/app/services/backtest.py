from __future__ import annotations
import math
import numpy as np
import pandas as pd
from app.services.features import build_feature_panel

DEFAULTS = {
    "long_count": 20,
    "short_count": 20,
    "rebalance_days": 5,
    "commission_bps": 6.0,
    "slippage_bps": 5.0,
    "gross_exposure": 2.0,
}

def run_backtest(params: dict | None = None) -> dict:
    p = DEFAULTS | (params or {})
    df = build_feature_panel().copy()
    dates = sorted(df.date.unique())
    warm = 260
    dates = dates[warm::int(p["rebalance_days"])]
    equity = 1.0
    curve = []
    turnovers = []
    prev_weights = {}
    trade_rows = []

    for idx, d in enumerate(dates[:-1]):
        next_d = dates[idx+1]
        snap = df[df.date == d].sort_values("meta_score", ascending=False)
        longs = snap.head(int(p["long_count"]))
        shorts = snap.tail(int(p["short_count"]))
        leg = p["gross_exposure"] / 2
        weights = {r.symbol: leg/len(longs) for r in longs.itertuples()}
        weights.update({r.symbol: -leg/len(shorts) for r in shorts.itertuples()})
        all_syms = set(prev_weights) | set(weights)
        turnover = sum(abs(weights.get(s,0)-prev_weights.get(s,0)) for s in all_syms)
        cost = turnover * ((p["commission_bps"] + p["slippage_bps"])/10000)

        p0 = df[df.date == d].set_index("symbol").close
        p1 = df[df.date == next_d].set_index("symbol").close
        gross_ret = 0.0
        for s,w in weights.items():
            if s in p0.index and s in p1.index:
                r = float(p1[s]/p0[s]-1)
                gross_ret += w*r
                trade_rows.append({"date": str(pd.Timestamp(d).date()), "symbol": s, "side": "LONG" if w>0 else "SHORT", "weight": round(w,4), "return": round((w*r),6)})
        net_ret = gross_ret - cost
        equity *= (1 + net_ret)
        curve.append({"date": str(pd.Timestamp(next_d).date()), "equity": round(equity,6), "return": net_ret})
        turnovers.append(turnover)
        prev_weights = weights

    returns = pd.Series([x["return"] for x in curve], dtype=float)
    if len(returns) < 2:
        raise ValueError("Not enough data")
    periods_per_year = 252 / p["rebalance_days"]
    years = len(returns)/periods_per_year
    cagr = equity**(1/max(years,1e-9))-1
    vol = returns.std(ddof=1)*math.sqrt(periods_per_year)
    sharpe = (returns.mean()*periods_per_year)/(vol+1e-12)
    eq = pd.Series([x["equity"] for x in curve])
    dd = eq/eq.cummax()-1
    max_dd = float(dd.min())
    rank_sample = df[df.date == df.date.max()].sort_values("meta_score", ascending=False)
    ranking = [{"rank": i+1, "symbol": r.symbol, "sector": r.sector, "score": round(float(r.meta_score),4)} for i,r in enumerate(rank_sample.head(30).itertuples())]
    bottom = [{"rank": len(rank_sample)-29+i, "symbol": r.symbol, "sector": r.sector, "score": round(float(r.meta_score),4)} for i,r in enumerate(rank_sample.tail(30).itertuples())]
    try:
        ic = df.groupby("date").apply(lambda x: x["meta_score"].corr(x["future_relative_20d"], method="spearman"), include_groups=False).mean()
    except Exception:
        ic = float("nan")

    return {
        "strategy": "META US v1",
        "params": p,
        "metrics": {
            "total_return": round(equity-1,4),
            "cagr": round(float(cagr),4),
            "sharpe": round(float(sharpe),3),
            "volatility": round(float(vol),4),
            "max_drawdown": round(max_dd,4),
            "avg_turnover_per_rebalance": round(float(np.mean(turnovers)),4),
            "mean_rank_ic_20d": None if np.isnan(ic) else round(float(ic),4),
            "rebalance_count": len(curve),
        },
        "equity_curve": curve,
        "ranking_top": ranking,
        "ranking_bottom": bottom,
        "sample_trades": trade_rows[-100:],
    }
