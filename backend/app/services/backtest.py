from __future__ import annotations
import math
import numpy as np
import pandas as pd
from app.services.features import build_feature_panel, panel_metadata, FEATURES

DEFAULTS={
    "long_count":20,"short_count":20,"rebalance_days":5,
    "commission_bps":6.0,"slippage_bps":5.0,"gross_exposure":2.0,
    "initial_capital":100000.0,"adaptive_lookback_days":252
}
BASELINE_DEFAULTS=DEFAULTS|{"long_count":20,"short_count":20}

def _metrics(curve,equity,turnovers,periods_per_year,positions=None):
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
    out={"total_return":round(equity-1,4),"cagr":round(float(cagr),4),"sharpe":round(float(sharpe),3),
         "sortino":None if not np.isfinite(sortino) else round(float(sortino),3),
         "calmar":None if not np.isfinite(calmar) else round(float(calmar),3),
         "volatility":round(float(vol),4),"max_drawdown":round(max_dd,4),
         "avg_turnover_per_rebalance":round(float(np.mean(turnovers)),4),"rebalance_count":len(curve)}
    if positions:
        pnl=np.array([float(x["net_pnl_usd"]) for x in positions],dtype=float)
        wins=pnl[pnl>0];losses=pnl[pnl<0]
        out["position_periods"]=len(positions)
        out["win_rate"]=round(float((pnl>0).mean()),4)
        out["profit_factor"]=None if not len(losses) else round(float(wins.sum()/abs(losses.sum())),3)
        out["avg_position_period_return"]=round(float(np.mean([x["asset_return"]*(1 if x["side"]=="LONG" else -1) for x in positions])),5)
        out["best_position_pnl_usd"]=round(float(pnl.max()),2)
        out["worst_position_pnl_usd"]=round(float(pnl.min()),2)
        out["long_pnl_usd"]=round(float(sum(x["net_pnl_usd"] for x in positions if x["side"]=="LONG")),2)
        out["short_pnl_usd"]=round(float(sum(x["net_pnl_usd"] for x in positions if x["side"]=="SHORT")),2)
    return out

def _daily_ic_frame(df):
    rows={}
    for f in FEATURES:
        try:
            rows[f]=df.groupby("date").apply(
                lambda x:x[f].corr(x["future_relative_20d"],method="spearman"),
                include_groups=False
            )
        except Exception:
            rows[f]=pd.Series(dtype=float)
    return pd.DataFrame(rows).sort_index()

def _cap_weights(raw,cap=.35):
    raw=raw.clip(lower=0).fillna(0.0)
    if float(raw.sum())<=1e-12:
        fallback=pd.Series({
            "momentum_12_1_rank":.35,"trend_200_rank":.20,
            "fundamental_raw_rank":.20,"news_raw_rank":.15,"liquidity_rank":.10
        })
        return fallback.reindex(FEATURES).fillna(0.0)
    w=raw/raw.sum()
    for _ in range(8):
        over=w>cap+1e-12
        if not over.any(): break
        excess=float((w[over]-cap).sum());w[over]=cap
        under=~over
        if excess<=0 or float(w[under].sum())<=1e-12: break
        w[under]+=excess*(w[under]/w[under].sum())
    return w/w.sum()

def _adaptive_weights(ic_frame,all_dates,signal_d,lookback=252,embargo=20):
    pos={d:i for i,d in enumerate(all_dates)}
    cutoff_i=pos.get(signal_d,0)-embargo
    if cutoff_i<=40:
        return _cap_weights(pd.Series(dtype=float)),{}
    eligible=all_dates[max(0,cutoff_i-int(lookback)):cutoff_i]
    hist=ic_frame.reindex(eligible).dropna(how="all")
    mean=hist.mean()
    std=hist.std().replace(0,np.nan)
    positive=(hist>0).mean()
    # Only reward factors whose historical IC is positive. Reliability shrinkage
    # prevents one noisy factor from dominating a single rebalance.
    reliability=((positive-.5).clip(lower=0)*2).fillna(0)
    raw=mean.clip(lower=0).fillna(0)*(.5+.5*reliability)
    weights=_cap_weights(raw)
    diagnostics={
        f:{"weight":round(float(weights.get(f,0)),4),
           "mean_ic":None if not np.isfinite(mean.get(f,np.nan)) else round(float(mean[f]),4),
           "positive_ic":None if not np.isfinite(positive.get(f,np.nan)) else round(float(positive[f]),3)}
        for f in FEATURES
    }
    return weights,diagnostics

def _split_order(symbol,prev_qty,target_qty,price,date,rebalance_id,cost_rate):
    orders=[]
    def add(action,qty):
        if qty<=1e-9:return
        notional=qty*price
        orders.append({
            "rebalance_id":rebalance_id,"date":date,"symbol":symbol,"action":action,
            "qty":round(float(qty),6),"price":round(float(price),4),
            "notional_usd":round(float(notional),2),
            "estimated_cost_usd":round(float(notional*cost_rate),2),
            "reason":"REBALANCE"
        })
    if prev_qty<0<target_qty:
        add("COVER",abs(prev_qty));add("BUY",target_qty)
    elif prev_qty>0>target_qty:
        add("SELL",prev_qty);add("SHORT",abs(target_qty))
    elif target_qty>prev_qty:
        add("COVER" if prev_qty<0 else "BUY",target_qty-prev_qty)
    elif target_qty<prev_qty:
        add("SELL" if prev_qty>0 else "SHORT",prev_qty-target_qty)
    return orders

def run_backtest(params:dict|None=None,score_column="meta_score",strategy_name="META US v2",panel=None,adaptive=False)->dict:
    p=DEFAULTS|(params or {})
    df=(build_feature_panel() if panel is None else panel).copy().sort_values(["date","symbol"])
    all_dates=np.array(sorted(df.date.unique()))
    if len(all_dates)<280: raise ValueError("Not enough history for warm-up and out-of-sample backtest")
    signal_dates=list(all_dates[260::int(p["rebalance_days"])])
    equity=1.0;curve=[];turnovers=[];prev_weights={};prev_qty={}
    positions=[];orders=[];rebalances=[];gross_pnl=[];costs=[]
    initial_capital=float(p.get("initial_capital",100000))
    by_date={d:x.set_index("symbol") for d,x in df.groupby("date")}
    date_pos={d:i for i,d in enumerate(all_dates)}
    ic_frame=_daily_ic_frame(df) if adaptive else None
    total_cost_rate=(float(p["commission_bps"])+float(p["slippage_bps"]))/10000

    for idx,signal_d in enumerate(signal_dates[:-1]):
        next_signal=signal_dates[idx+1]
        ep=date_pos[signal_d]+1;xp=date_pos[next_signal]+1
        if ep>=len(all_dates) or xp>=len(all_dates): break
        entry_d,exit_d=all_dates[ep],all_dates[xp]
        snap=by_date[signal_d].copy()

        adaptive_diag={}
        if adaptive:
            aw,adaptive_diag=_adaptive_weights(
                ic_frame,all_dates,signal_d,
                lookback=int(p.get("adaptive_lookback_days",252)),embargo=20
            )
            snap["_score"]=sum(snap[f].fillna(.5)*float(aw.get(f,0)) for f in FEATURES)
            active_score="_score"
        else:
            active_score=score_column
        snap=snap.sort_values(active_score,ascending=False)
        longs=snap.head(int(p["long_count"]));shorts=snap.tail(int(p["short_count"]))
        if longs.empty or shorts.empty: continue
        leg=float(p["gross_exposure"])/2
        weights={s:leg/len(longs) for s in longs.index}
        weights.update({s:-leg/len(shorts) for s in shorts.index})
        turnover=sum(abs(weights.get(s,0)-prev_weights.get(s,0)) for s in set(prev_weights)|set(weights))

        entry=by_date.get(entry_d);exit_=by_date.get(exit_d)
        if entry is None or exit_ is None: continue
        equity_before_usd=initial_capital*equity
        rebalance_id=idx+1
        rank_map={s:i+1 for i,s in enumerate(snap.index)}
        target_qty={}
        entry_cost_by_symbol={}

        for s,w in weights.items():
            if s not in entry.index:continue
            price=float(entry.loc[s,"open"])
            if price<=0:continue
            target_qty[s]=(w*equity_before_usd)/price

        for s in set(prev_qty)|set(target_qty):
            price=None
            if s in entry.index:price=float(entry.loc[s,"open"])
            elif s in exit_.index:price=float(exit_.loc[s,"open"])
            if not price or price<=0:continue
            generated=_split_order(
                s,float(prev_qty.get(s,0)),float(target_qty.get(s,0)),price,
                str(pd.Timestamp(entry_d).date()),rebalance_id,total_cost_rate
            )
            orders.extend(generated)
            entry_cost_by_symbol[s]=sum(x["estimated_cost_usd"] for x in generated)

        period_cost_usd=float(sum(entry_cost_by_symbol.values()))
        gross_pnl_usd=0.0
        for s,w in weights.items():
            if s not in entry.index or s not in exit_.index or s not in target_qty:continue
            p0=float(entry.loc[s,"open"]);p1=float(exit_.loc[s,"open"])
            if p0<=0:continue
            qty=float(target_qty[s]);asset_ret=p1/p0-1
            symbol_gross=qty*(p1-p0)
            symbol_cost=float(entry_cost_by_symbol.get(s,0))
            symbol_net=symbol_gross-symbol_cost
            gross_pnl_usd+=symbol_gross
            positions.append({
                "rebalance_id":rebalance_id,
                "signal_date":str(pd.Timestamp(signal_d).date()),
                "entry_date":str(pd.Timestamp(entry_d).date()),
                "exit_date":str(pd.Timestamp(exit_d).date()),
                "holding_trading_days":int(xp-ep),
                "symbol":s,"side":"LONG" if w>0 else "SHORT",
                "rank":int(rank_map.get(s,0)),
                "signal_score":round(float(snap.loc[s,active_score]),6),
                "weight":round(float(w),5),
                "entry_price":round(p0,4),"exit_price":round(p1,4),
                "qty":round(abs(qty),6),
                "entry_notional_usd":round(abs(qty*p0),2),
                "asset_return":round(float(asset_ret),6),
                "gross_pnl_usd":round(float(symbol_gross),2),
                "estimated_cost_usd":round(symbol_cost,2),
                "net_pnl_usd":round(float(symbol_net),2)
            })

        gross_ret=gross_pnl_usd/max(equity_before_usd,1e-12)
        cost_ret=period_cost_usd/max(equity_before_usd,1e-12)
        net_ret=gross_ret-cost_ret
        equity_after_usd=equity_before_usd*(1+net_ret)
        equity*=1+net_ret
        curve.append({
            "date":str(pd.Timestamp(exit_d).date()),"equity":round(equity,6),
            "equity_usd":round(equity_after_usd,2),"return":net_ret,
            "gross_return":gross_ret,"cost":cost_ret
        })
        rebalances.append({
            "rebalance_id":rebalance_id,
            "signal_date":str(pd.Timestamp(signal_d).date()),
            "entry_date":str(pd.Timestamp(entry_d).date()),
            "exit_date":str(pd.Timestamp(exit_d).date()),
            "long_count":len(longs),"short_count":len(shorts),
            "turnover":round(float(turnover),4),
            "equity_before_usd":round(equity_before_usd,2),
            "gross_pnl_usd":round(gross_pnl_usd,2),
            "cost_usd":round(period_cost_usd,2),
            "net_pnl_usd":round(gross_pnl_usd-period_cost_usd,2),
            "equity_after_usd":round(equity_after_usd,2),
            "adaptive_factors":adaptive_diag if adaptive else None
        })
        turnovers.append(turnover);gross_pnl.append(gross_ret);costs.append(cost_ret)
        prev_weights=weights;prev_qty=target_qty

    metrics=_metrics(curve,equity,turnovers,252/int(p["rebalance_days"]),positions)
    metrics["gross_return_sum"]=round(float(np.sum(gross_pnl)),4)
    metrics["costs_sum"]=round(float(np.sum(costs)),4)
    metrics["initial_capital_usd"]=round(initial_capital,2)
    metrics["ending_capital_usd"]=round(initial_capital*equity,2)
    metrics["gross_pnl_usd"]=round(float(sum(x["gross_pnl_usd"] for x in positions)),2)
    metrics["estimated_costs_usd"]=round(float(sum(x["estimated_cost_usd"] for x in orders)),2)
    metrics["net_pnl_usd"]=round(metrics["ending_capital_usd"]-initial_capital,2)
    try:
        ic=df.groupby("date").apply(
            lambda x:x[score_column].corr(x["future_relative_20d"],method="spearman"),
            include_groups=False
        ).mean()
    except Exception:ic=np.nan
    metrics["mean_rank_ic_20d"]=None if not np.isfinite(ic) else round(float(ic),4)
    rank_sample=df[df.date==df.date.max()].sort_values(score_column,ascending=False)
    return {
        "strategy":strategy_name,"score_column":"adaptive_train_only" if adaptive else score_column,
        "params":p,"dataset":panel_metadata(df),
        "execution_timing":"signal_close_T__entry_open_T1",
        "audit_note":"Prices are next-open rebalance marks. Orders show simulated BUY/SELL/SHORT/COVER activity; position_ledger attributes P&L between consecutive rebalance opens.",
        "metrics":metrics,"equity_curve":curve,
        "ranking_top":[{"rank":i+1,"symbol":r.symbol,"sector":r.sector,"score":round(float(getattr(r,score_column)),4)} for i,r in enumerate(rank_sample.head(30).itertuples())],
        "ranking_bottom":[{"rank":len(rank_sample)-29+i,"symbol":r.symbol,"sector":r.sector,"score":round(float(getattr(r,score_column)),4)} for i,r in enumerate(rank_sample.tail(30).itertuples())],
        "rebalance_ledger":rebalances,
        "order_ledger":orders,
        "position_ledger":positions,
        "sample_trades":positions[-100:]
    }

def run_momentum_baseline(params=None,panel=None):
    return run_backtest(params,score_column="momentum_12_1_rank",strategy_name="Momentum 12-1 baseline",panel=panel)

def run_adaptive_meta(params=None,panel=None):
    return run_backtest(params,score_column="meta_score",strategy_name="Adaptive META US v3",panel=panel,adaptive=True)
