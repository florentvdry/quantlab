from __future__ import annotations
import math
import numpy as np
import pandas as pd
from app.services.features import build_feature_panel, panel_metadata, FEATURES

DEFAULTS={
    "long_count":20,"short_count":20,"rebalance_days":5,"warmup_days":0,
    "commission_bps":6.0,"slippage_bps":5.0,"gross_exposure":2.0,
    "initial_capital":100000.0,"adaptive_lookback_days":252,
    "long_gross":None,"short_gross":None,"rank_buffer":0,
    "rebalance_threshold_pct":0.0,"min_trade_notional":0.0,
    "max_abs_weight":None
}
BASELINE_DEFAULTS=DEFAULTS|{"long_count":20,"short_count":20}
V4_DEFAULTS={
    "long_count":15,"short_count":0,"rebalance_days":10,
    "commission_bps":6.0,"slippage_bps":5.0,"gross_exposure":1.0,
    "initial_capital":100000.0,"long_gross":1.0,"short_gross":0.0,
    "rank_buffer":5,"rebalance_threshold_pct":0.20,"min_trade_notional":250.0
}
V4_FEATURE_WEIGHTS={
    "momentum_12_1_rank":0.30,
    "ret_60d_rank":0.15,
    "ret_20d_rank":0.05,
    "trend_50_rank":0.10,
    "trend_200_rank":0.15,
    "fundamental_raw_rank":0.20,
    "liquidity_rank":0.05,
}

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

def _select_with_buffer(ranked_symbols,prev_symbols,count,buffer,side):
    if count<=0:return []
    ranked=list(ranked_symbols);rank={s:i for i,s in enumerate(ranked)};n=len(ranked)
    prev=[s for s in prev_symbols if s in rank]
    if side=="LONG":
        retained=sorted([s for s in prev if rank[s]<count+buffer],key=lambda s:rank[s])
        candidates=ranked
    else:
        retained=sorted([s for s in prev if rank[s]>=n-count-buffer],key=lambda s:rank[s],reverse=True)
        candidates=list(reversed(ranked))
    out=[]
    for s in retained+candidates:
        if s not in out:out.append(s)
        if len(out)>=count:break
    return out

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

def run_backtest(params:dict|None=None,score_column="meta_score",strategy_name="META US v2",panel=None,adaptive=False,position_scale_column=None)->dict:
    p=DEFAULTS|(params or {})
    df=(build_feature_panel() if panel is None else panel).copy().sort_values(["date","symbol"])
    all_dates=np.array(sorted(df.date.unique()))
    warmup=max(0,int(p.get("warmup_days",0)))
    if len(all_dates)<max(30,warmup+20): raise ValueError("Not enough history for backtest")
    signal_dates=list(all_dates[warmup::int(p["rebalance_days"])])
    equity=1.0;curve=[];turnovers=[];prev_weights={};prev_qty={}
    benchmark_equity=1.0;benchmark_curve=[]
    positions=[];orders=[];rebalances=[];gross_pnl=[];costs=[]
    initial_capital=float(p.get("initial_capital",100000))
    by_date={d:x.set_index("symbol") for d,x in df.groupby("date")}
    date_pos={d:i for i,d in enumerate(all_dates)}
    ic_frame=_daily_ic_frame(df) if adaptive else None
    adaptive_eval_ic=[]
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
            try:
                eval_ic=snap["_score"].corr(snap["future_relative_20d"],method="spearman")
                if np.isfinite(eval_ic):adaptive_eval_ic.append(float(eval_ic))
            except Exception:pass
        else:
            active_score=score_column
        snap=snap.dropna(subset=[active_score]).sort_values(active_score,ascending=False)
        long_n=int(p["long_count"]);short_n=int(p["short_count"])
        min_long=long_n if p.get("min_long_count") is None else int(p.get("min_long_count") or 0)
        min_short=short_n if p.get("min_short_count") is None else int(p.get("min_short_count") or 0)
        if len(snap)<min_long+min_short:continue
        long_n=min(long_n,len(snap))
        short_n=min(short_n,max(0,len(snap)-long_n))
        prev_long=[s for s,w in prev_weights.items() if w>0]
        prev_short=[s for s,w in prev_weights.items() if w<0]
        buffer=int(p.get("rank_buffer") or 0)
        long_syms=_select_with_buffer(snap.index,prev_long,long_n,buffer,"LONG")
        short_syms=_select_with_buffer(snap.index,prev_short,short_n,buffer,"SHORT")
        longs=snap.loc[long_syms] if long_syms else snap.iloc[0:0]
        shorts=snap.loc[short_syms] if short_syms else snap.iloc[0:0]
        if long_n and longs.empty:continue
        if short_n and shorts.empty:continue

        if p.get("long_gross") is None and p.get("short_gross") is None:
            if long_n and short_n:
                long_gross=short_gross=float(p["gross_exposure"])/2
            elif long_n:
                long_gross=float(p["gross_exposure"]);short_gross=0.0
            else:
                long_gross=0.0;short_gross=float(p["gross_exposure"])
        else:
            long_gross=float(p.get("long_gross") or 0.0)
            short_gross=float(p.get("short_gross") or 0.0)
        weights={}
        if len(longs):
            if position_scale_column and position_scale_column in longs.columns:
                scales=longs[position_scale_column].clip(lower=0,upper=1).fillna(0.0)
                if bool(p.get("normalize_position_scale",True)) and float(scales.sum())>1e-12:
                    weights.update({s:long_gross*float(scales.loc[s]/scales.sum()) for s in longs.index})
                else:
                    weights.update({s:long_gross*float(scales.loc[s])/len(longs) for s in longs.index})
            else:
                weights.update({s:long_gross/len(longs) for s in longs.index})
        if len(shorts):
            if position_scale_column and position_scale_column in shorts.columns:
                scales=shorts[position_scale_column].clip(lower=0,upper=1).fillna(0.0)
                if bool(p.get("normalize_position_scale",True)) and float(scales.sum())>1e-12:
                    weights.update({s:-short_gross*float(scales.loc[s]/scales.sum()) for s in shorts.index})
                else:
                    weights.update({s:-short_gross*float(scales.loc[s])/len(shorts) for s in shorts.index})
            else:
                weights.update({s:-short_gross/len(shorts) for s in shorts.index})
        max_abs_weight=p.get("max_abs_weight")
        if max_abs_weight is not None:
            cap=max(0.0,float(max_abs_weight))
            weights={s:float(np.clip(w,-cap,cap)) for s,w in weights.items()}
        weights={s:w for s,w in weights.items() if abs(w)>1e-12}

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

        # Hysteresis / no-trade zone: keep an existing position when the requested
        # resize is economically insignificant. Exits and side flips are never skipped.
        resize_band=float(p.get("rebalance_threshold_pct") or 0.0)
        min_trade=float(p.get("min_trade_notional") or 0.0)
        for s in list(target_qty):
            if s not in prev_qty or s not in entry.index:continue
            prev=float(prev_qty[s]);target=float(target_qty[s])
            if prev==0 or target==0 or np.sign(prev)!=np.sign(target):continue
            price=float(entry.loc[s,"open"])
            delta_notional=abs((target-prev)*price)
            target_notional=abs(target*price)
            if delta_notional<max(min_trade,resize_band*target_notional):
                target_qty[s]=prev

        period_trade_notional_usd=0.0
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
            period_trade_notional_usd+=sum(float(x["notional_usd"]) for x in generated)
            entry_cost_by_symbol[s]=sum(x["estimated_cost_usd"] for x in generated)

        period_cost_usd=float(sum(entry_cost_by_symbol.values()))
        turnover=period_trade_notional_usd/max(equity_before_usd,1e-12)

        common=entry.index.intersection(exit_.index)
        if len(common):
            bench_ret=(exit_.loc[common,"open"]/entry.loc[common,"open"]-1).replace([np.inf,-np.inf],np.nan).dropna().mean()
            if np.isfinite(bench_ret):
                benchmark_equity*=1+float(bench_ret)
                benchmark_curve.append({"date":str(pd.Timestamp(exit_d).date()),"equity":benchmark_equity,"return":float(bench_ret)})
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
                "position_return":round(float(asset_ret if w>0 else -asset_ret),6),
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
        actual_weights={}
        for s,qty in target_qty.items():
            if s in entry.index:
                actual_weights[s]=float(qty)*float(entry.loc[s,"open"])/max(equity_before_usd,1e-12)
        prev_weights=actual_weights;prev_qty=target_qty

    metrics=_metrics(curve,equity,turnovers,252/int(p["rebalance_days"]),positions)
    metrics["gross_return_sum"]=round(float(np.sum(gross_pnl)),4)
    metrics["costs_sum"]=round(float(np.sum(costs)),4)
    metrics["initial_capital_usd"]=round(initial_capital,2)
    metrics["ending_capital_usd"]=round(initial_capital*equity,2)
    metrics["gross_pnl_usd"]=round(float(sum(x["gross_pnl_usd"] for x in positions)),2)
    metrics["estimated_costs_usd"]=round(float(sum(x["estimated_cost_usd"] for x in orders)),2)
    metrics["net_pnl_usd"]=round(metrics["ending_capital_usd"]-initial_capital,2)
    long_costs=sum(float(x["estimated_cost_usd"]) for x in orders if x["action"] in ("BUY","SELL"))
    short_costs=sum(float(x["estimated_cost_usd"]) for x in orders if x["action"] in ("SHORT","COVER"))
    long_gross_pnl=sum(float(x["gross_pnl_usd"]) for x in positions if x["side"]=="LONG")
    short_gross_pnl=sum(float(x["gross_pnl_usd"]) for x in positions if x["side"]=="SHORT")
    metrics["long_costs_usd"]=round(long_costs,2);metrics["short_costs_usd"]=round(short_costs,2)
    metrics["long_pnl_usd"]=round(long_gross_pnl-long_costs,2)
    metrics["short_pnl_usd"]=round(short_gross_pnl-short_costs,2)
    if len(benchmark_curve)>1:
        bm=_metrics(benchmark_curve,benchmark_equity,[0.0]*len(benchmark_curve),252/int(p["rebalance_days"]))
        metrics["benchmark_cagr"]=bm["cagr"];metrics["benchmark_sharpe"]=bm["sharpe"];metrics["benchmark_max_drawdown"]=bm["max_drawdown"]
        metrics["excess_cagr_vs_equal_weight"]=round(metrics["cagr"]-bm["cagr"],4)
    try:
        ic=df.groupby("date").apply(
            lambda x:x[score_column].corr(x["future_relative_20d"],method="spearman"),
            include_groups=False
        ).mean()
    except Exception:ic=np.nan
    if adaptive and adaptive_eval_ic:
        metrics["mean_rank_ic_20d"]=round(float(np.mean(adaptive_eval_ic)),4)
    else:
        metrics["mean_rank_ic_20d"]=None if not np.isfinite(ic) else round(float(ic),4)
    rank_source=df.dropna(subset=[score_column]) if score_column in df.columns else df
    rank_date=rank_source.date.max()
    rank_sample=rank_source[rank_source.date==rank_date].sort_values(score_column,ascending=False)
    dataset=panel_metadata(df)
    if rebalances:
        dataset["backtest_from"]=rebalances[0]["entry_date"]
        dataset["backtest_to"]=rebalances[-1]["exit_date"]
    return {
        "strategy":strategy_name,"score_column":"adaptive_train_only" if adaptive else score_column,
        "params":p,"dataset":dataset,
        "position_scale_column":position_scale_column,
        "execution_timing":"signal_close_T__entry_open_T1",
        "audit_note":"Prices are next-open rebalance marks. Orders show simulated BUY/SELL/SHORT/COVER activity; position_ledger attributes P&L between consecutive rebalance opens.",
        "metrics":metrics,"equity_curve":curve,
        "benchmark":{"name":"Equal-weight current universe (no costs)","equity_curve":benchmark_curve},
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

def run_meta_v4(panel=None):
    panel=build_feature_panel() if panel is None else panel.copy()
    panel["meta_v4_score"]=sum(panel[f].fillna(.5)*w for f,w in V4_FEATURE_WEIGHTS.items())
    result=run_backtest(V4_DEFAULTS,score_column="meta_v4_score",strategy_name="META Long-Only Low-Turnover v4",panel=panel)
    result["research_status"]="EXPLORATORY_AFTER_DIAGNOSTIC"
    result["score_weights"]=V4_FEATURE_WEIGHTS
    result["audit_note"]+=" V4 is long-only, uses rank hysteresis and a no-trade resize band. Earnings/low-vol are excluded; historical news is excluded until point-in-time news history exists."
    return result
