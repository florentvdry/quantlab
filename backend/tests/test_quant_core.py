import numpy as np
import pandas as pd

def synthetic_raw(symbols=("A","B"),days=320):
    dates=pd.bdate_range("2024-01-01",periods=days)
    rows=[]
    for si,s in enumerate(symbols):
        for i,d in enumerate(dates):
            px=100+si*10+i*.1
            rows.append({"date":d,"symbol":s,"sector":"Test","open":px,"high":px+1,"low":px-1,"close":px,
                         "volume":1_000_000,"fundamental_raw":1+si,"earnings_raw":.1*si,"news_raw":0})
    return pd.DataFrame(rows)

def test_future_target_never_crosses_symbol(monkeypatch):
    from app.services import features
    monkeypatch.setattr(features,"synthetic_panel",lambda:synthetic_raw())
    monkeypatch.setattr(features.settings,"data_mode","synthetic")
    features.clear_feature_cache(remove_disk=True)
    df=features.build_feature_panel(force=True).sort_values(["symbol","date"])
    for _,g in df.groupby("symbol"):
        tail=g.tail(20)
        assert tail["future_20d"].isna().all()

def test_backtest_executes_after_signal_date():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2023-01-02",periods=320)
    rows=[]
    for si,s in enumerate(["A","B","C","D"]):
        score=1-si/4
        for i,d in enumerate(dates):
            px=100+i*(1 if s in ("A","B") else -.2)
            rows.append({"date":d,"symbol":s,"sector":"Test","open":max(10,px),"close":max(10,px),
                         "meta_score":score,"momentum_12_1_rank":score,"future_relative_20d":0})
    panel=pd.DataFrame(rows)
    r=run_backtest({"long_count":1,"short_count":1,"rebalance_days":5,"gross_exposure":1},panel=panel)
    assert r["execution_timing"]=="signal_close_T__entry_open_T1"
    assert r["sample_trades"]
    for t in r["sample_trades"]:
        assert pd.Timestamp(t["entry_date"])>pd.Timestamp(t["signal_date"])

def test_transaction_costs_reduce_return():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2023-01-02",periods=320)
    rows=[]
    for si,s in enumerate(["A","B","C","D"]):
        score=1-si/4
        for i,d in enumerate(dates):
            px=100+i*.05
            rows.append({"date":d,"symbol":s,"sector":"Test","open":px,"close":px,"meta_score":score,
                         "momentum_12_1_rank":score,"future_relative_20d":0})
    panel=pd.DataFrame(rows)
    zero=run_backtest({"long_count":1,"short_count":1,"commission_bps":0,"slippage_bps":0},panel=panel)
    costly=run_backtest({"long_count":1,"short_count":1,"commission_bps":20,"slippage_bps":20},panel=panel)
    assert costly["metrics"]["total_return"]<=zero["metrics"]["total_return"]


def test_backtest_exposes_auditable_prices_and_orders():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2023-01-02",periods=340)
    rows=[]
    for si,s in enumerate(["A","B","C","D"]):
        score=1-si/4
        for i,d in enumerate(dates):
            px=100+si*5+i*(.08 if s in ("A","B") else -.02)
            rows.append({"date":d,"symbol":s,"sector":"Test","open":max(10,px),"close":max(10,px),
                         "meta_score":score,"momentum_12_1_rank":score,"future_relative_20d":0})
    panel=pd.DataFrame(rows)
    r=run_backtest({"long_count":1,"short_count":1,"initial_capital":10000},panel=panel)
    assert r["order_ledger"]
    assert r["position_ledger"]
    first=r["position_ledger"][0]
    assert first["entry_price"]>0
    assert first["exit_price"]>0
    assert first["qty"]>0
    assert "net_pnl_usd" in first
    assert {o["action"] for o in r["order_ledger"]} & {"BUY","SHORT","SELL","COVER"}


def test_walk_forward_uses_target_embargo():
    from app.services.research import _walk_forward_scored
    from app.services.features import FEATURES
    dates=pd.bdate_range("2021-01-04",periods=760)
    rows=[]
    for si,s in enumerate(["A","B","C","D","E","F"]):
        for i,d in enumerate(dates):
            row={"date":d,"symbol":s,"sector":"Test","open":100+i*.01,"close":100+i*.01,
                 "future_relative_20d":((si-2.5)/1000)+((i%17)-8)/10000}
            for fi,f in enumerate(FEATURES):
                row[f]=((si+fi+i)%100)/100
            rows.append(row)
    panel=pd.DataFrame(rows)
    _,summary=_walk_forward_scored("ridge",panel,min_train_days=300,test_days=100,embargo_days=20)
    all_dates=list(sorted(panel.date.unique()))
    pos={d:i for i,d in enumerate(all_dates)}
    assert summary["folds"]
    for fold in summary["folds"]:
        train_to=pd.Timestamp(fold["train_to"])
        test_from=pd.Timestamp(fold["test_from"])
        assert pos[test_from]-pos[train_to]>=20


def test_meta_v4_is_long_only_low_turnover_and_benchmarked():
    from app.services.backtest import run_meta_v4,run_backtest,V4_FEATURE_WEIGHTS
    from app.services.features import FEATURES
    dates=pd.bdate_range("2023-01-02",periods=380)
    symbols=[f"S{i:02d}" for i in range(20)]
    rows=[]
    for si,s in enumerate(symbols):
        for i,d in enumerate(dates):
            px=80+si*2+i*(.04+.002*si)
            row={"date":d,"symbol":s,"sector":"Test","open":px,"close":px,
                 "meta_score":1-si/20,"future_relative_20d":0}
            for fi,f in enumerate(FEATURES):
                row[f]=max(.001,min(.999,1-(si/25)+(fi*.001)))
            rows.append(row)
    panel=pd.DataFrame(rows)
    v4=run_meta_v4(panel=panel)
    assert v4["strategy"]=="META Long-Only Low-Turnover v4"
    assert v4["params"]["short_count"]==0
    assert v4["params"]["rebalance_days"]==10
    assert v4["params"]["rank_buffer"]==5
    assert not any(o["action"] in ("SHORT","COVER") for o in v4["order_ledger"])
    assert not any(x["side"]=="SHORT" for x in v4["position_ledger"])
    assert "benchmark_cagr" in v4["metrics"]
    assert v4["dataset"]["backtest_from"]<v4["dataset"]["backtest_to"]
    assert set(v4["score_weights"])==set(V4_FEATURE_WEIGHTS)

def test_no_trade_band_reduces_resize_churn():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2023-01-02",periods=360)
    rows=[]
    for si,s in enumerate(["A","B","C","D"]):
        for i,d in enumerate(dates):
            px=100+si*3+i*(.02+.001*si)
            rows.append({"date":d,"symbol":s,"sector":"Test","open":px,"close":px,
                         "meta_score":1-si/4,"momentum_12_1_rank":1-si/4,"future_relative_20d":0})
    panel=pd.DataFrame(rows)
    noisy=run_backtest({"long_count":2,"short_count":0,"gross_exposure":1,"rebalance_days":5},panel=panel)
    buffered=run_backtest({"long_count":2,"short_count":0,"gross_exposure":1,"rebalance_days":5,
                           "rank_buffer":1,"rebalance_threshold_pct":.20,"min_trade_notional":100},panel=panel)
    assert len(buffered["order_ledger"])<=len(noisy["order_ledger"])
    assert buffered["metrics"]["estimated_costs_usd"]<=noisy["metrics"]["estimated_costs_usd"]


def test_meta_v5_ewma_is_one_sided():
    from app.services.meta_v5 import _blend
    dates=pd.bdate_range("2026-01-05",periods=6)
    base=[]
    for i,d in enumerate(dates):
        base.append({"date":d,"symbol":"A","v5_regime":"NEUTRAL",
                     "rank_ridge":.2+i*.1,"rank_hgb":.3+i*.05,"rank_lgbm":.4+i*.04,"rank_momentum":.5+i*.03})
    df=pd.DataFrame(base)
    router={"GLOBAL":{"ridge":.25,"hgb":.25,"lgbm":.25,"momentum":.25},
            "NEUTRAL":{"ridge":.25,"hgb":.25,"lgbm":.25,"momentum":.25}}
    for r in ("TREND_UP","HIGH_VOL","RISK_OFF"):router[r]=router["GLOBAL"]
    a=_blend(df,router)
    changed=df.copy()
    changed.loc[changed.index[-1],["rank_ridge","rank_hgb","rank_lgbm","rank_momentum"]]=.999
    b=_blend(changed,router)
    assert np.allclose(a["v5_smooth_score"].iloc[:-1],b["v5_smooth_score"].iloc[:-1])

def test_meta_v5_continuous_walk_forward_has_no_fixed_holdout(monkeypatch):
    from app.services import meta_v5
    from app.services.features import FEATURES
    dates=pd.bdate_range("2023-01-02",periods=320)
    symbols=[f"S{i:02d}" for i in range(18)]
    rows=[]
    for i,d in enumerate(dates):
        for si,s in enumerate(symbols):
            quality=(len(symbols)-si)/len(symbols)
            row={"date":d,"symbol":s,"sector":"Test","open":100+si+i*.03,"close":100+si+i*.03,
                 "ret_20d":(quality-.5)*.05,"vol_20d":.18+(si%3)*.01,
                 "future_relative_20d":(quality-.5)*.02+((i%7)-3)*.0002}
            for fi,name in enumerate(FEATURES):
                row[name]=max(.001,min(.999,quality+(fi%3-1)*.01))
            rows.append(row)
    panel=pd.DataFrame(rows)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"min_train_days",90)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"validation_days",40)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"model_refresh_days",40)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"lgbm_members",1)
    scored,summary=meta_v5.build_meta_v5_oos(panel=panel)
    assert summary["simulation"]["method"]=="CONTINUOUS_EXPANDING_WALK_FORWARD"
    assert summary["simulation"]["fixed_holdout"] is False
    assert summary["folds"]
    pos={d:i for i,d in enumerate(sorted(panel.date.unique()))}
    for fold in summary["folds"]:
        vto=pd.Timestamp(fold["validation_to"])
        tfrom=pd.Timestamp(fold["test_from"])
        assert pos[tfrom]-pos[vto]>=20
        assert fold["meta"]["calibration_embargo_days"]>=0
    first_scored=scored.loc[scored["v5_meta_probability"].notna(),"date"].min()
    assert first_scored<dates[int(len(dates)*.70)]
    assert scored["v5_meta_probability"].notna().any()

def test_probability_sizing_can_leave_cash():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2023-01-02",periods=330)
    rows=[]
    for si,s in enumerate(["A","B","C","D"]):
        for i,d in enumerate(dates):
            rows.append({"date":d,"symbol":s,"sector":"Test","open":100+si+i*.01,"close":100+si+i*.01,
                         "score":1-si/4,"scale":.5,"future_relative_20d":0})
    panel=pd.DataFrame(rows)
    r=run_backtest({"long_count":2,"short_count":0,"gross_exposure":1,"long_gross":1,
                    "min_long_count":1,"normalize_position_scale":False},
                   score_column="score",strategy_name="sized",panel=panel,position_scale_column="scale")
    first=r["position_ledger"][0]
    assert first["weight"]<=.25+1e-6


def test_sec_companyfacts_404_is_non_fatal_and_cached(monkeypatch,tmp_path):
    import httpx
    from app.services import sec_fundamentals as sec
    monkeypatch.setattr(sec,"CACHE",tmp_path)
    monkeypatch.setattr(sec,"ticker_map",lambda force=False:{"MISS":{"cik":"0001067839","title":"Missing XBRL"}})
    calls={"n":0}
    def missing(url,host_data=True):
        calls["n"]+=1
        req=httpx.Request("GET",url)
        resp=httpx.Response(404,request=req)
        raise httpx.HTTPStatusError("not found",request=req,response=resp)
    monkeypatch.setattr(sec,"_get_json",missing)
    sec._LAST_DIAGNOSTICS["not_found"].clear();sec._LAST_DIAGNOSTICS["errors"].clear()
    assert sec.companyfacts("MISS") is None
    assert calls["n"]==1
    assert sec.companyfacts("MISS") is None
    assert calls["n"]==1
    assert "MISS" in sec.diagnostics()["not_found"]

def test_feature_store_status_reports_missing_without_raising(monkeypatch,tmp_path):
    from app.services import features
    monkeypatch.setattr(features,"STORE_PATH",str(tmp_path/"feature_store.parquet"))
    monkeypatch.setattr(features,"META_PATH",str(tmp_path/"feature_store.json"))
    status=features.feature_store_status()
    assert status["ready"] is False
    assert status["reason"]=="missing"


def test_json_safe_normalizes_non_finite_quant_values():
    import json
    from app.services.json_utils import StrictJSONResponse,json_safe,safe_dumps

    payload={
        "nan":np.nan,
        "pos_inf":np.inf,
        "neg_inf":-np.inf,
        "nested":[1.0,{"metric":np.float64(np.nan),"ok":np.float64(.25)}],
    }
    safe=json_safe(payload)
    assert safe["nan"] is None
    assert safe["pos_inf"] is None
    assert safe["neg_inf"] is None
    assert safe["nested"][1]["metric"] is None
    assert safe["nested"][1]["ok"]==.25
    json.dumps(safe,allow_nan=False)
    assert '"nan": null' in safe_dumps(payload)
    rendered=StrictJSONResponse(payload).body.decode()
    assert '"nan":null' in rendered
    assert "NaN" not in rendered
    assert "Infinity" not in rendered


def test_backtest_starts_at_first_available_signal_instead_of_hidden_260_day_skip():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2025-01-02",periods=90)
    rows=[]
    for si,s in enumerate(["A","B","C","D"]):
        for i,d in enumerate(dates):
            rows.append({"date":d,"symbol":s,"sector":"Test","open":100+si+i*.02,"close":100+si+i*.02,
                         "meta_score":1-si/4,"momentum_12_1_rank":1-si/4,"future_relative_20d":0})
    panel=pd.DataFrame(rows)
    result=run_backtest({"long_count":1,"short_count":1,"rebalance_days":10},panel=panel)
    assert result["position_ledger"]
    assert pd.Timestamp(result["position_ledger"][0]["signal_date"])==dates[0]
    assert pd.Timestamp(result["position_ledger"][0]["entry_date"])==dates[1]


def test_backtest_request_accepts_long_only_v5():
    from app.main import BacktestRequest
    req=BacktestRequest(long_count=15,short_count=0,rebalance_days=10,gross_exposure=1)
    assert req.short_count==0

def test_alpaca_history_defaults_to_2016(monkeypatch):
    from app.services import real_data
    monkeypatch.setattr(real_data.settings,"real_history_start","2016-01-01")
    assert real_data._requested_history_start()=="2016-01-01"


def test_meta_v6_target_matches_next_open_holding_period(monkeypatch):
    from app.services import meta_v6
    monkeypatch.setitem(meta_v6.V6_CONFIG,"holding_days",10)
    dates=pd.bdate_range("2026-01-02",periods=20)
    panel=pd.DataFrame({
        "date":dates,
        "symbol":["A"]*len(dates),
        "open":np.arange(100,120,dtype=float),
    })
    out=meta_v6._add_execution_aligned_targets(panel)
    first=out.iloc[0]
    expected=111.0/101.0-1.0
    assert abs(first["v6_future_open_return"]-expected)<1e-12


def test_meta_v6_continuous_builder_uses_execution_aligned_labels(monkeypatch):
    from app.services import meta_v6
    from app.services.features import FEATURES

    dates=pd.bdate_range("2024-01-02",periods=280)
    symbols=[f"V{i:02d}" for i in range(16)]
    rows=[]
    for si,symbol in enumerate(symbols):
        quality=(len(symbols)-si)/len(symbols)
        price=100.0+si
        prices=[]
        for i,_ in enumerate(dates):
            daily_ret=(quality-.5)*.0015+np.sin((i+si)/8.0)*.004
            price*=1+daily_ret
            prices.append(price)
        for i,d in enumerate(dates):
            row={
                "date":d,"symbol":symbol,"sector":"Test",
                "open":prices[i],"close":prices[i]*(1+0.0002*np.cos(i)),
                "ret_20d":(quality-.5)*.06+np.sin((i+si)/10.0)*.02,
                "vol_20d":.15+(si%4)*.02,
                "trend_200":(quality-.5)*.08,
                "future_relative_20d":0.0,
            }
            for fi,name in enumerate(FEATURES):
                row[name]=max(.001,min(.999,quality+(fi%3-1)*.015))
            rows.append(row)

    panel=pd.DataFrame(rows)
    monkeypatch.setitem(meta_v6.V6_CONFIG,"min_train_days",80)
    monkeypatch.setitem(meta_v6.V6_CONFIG,"validation_days",40)
    monkeypatch.setitem(meta_v6.V6_CONFIG,"model_refresh_days",50)
    monkeypatch.setitem(meta_v6.V6_CONFIG,"lgbm_members",1)
    monkeypatch.setitem(meta_v6.V6_CONFIG,"meta_threshold_grid",[0.50,0.60])
    monkeypatch.setitem(meta_v6.V6_CONFIG,"long_count_grid",[5,8])

    scored,summary=meta_v6.build_meta_v6_oos(panel=panel)
    assert summary["simulation"]["method"]=="CONTINUOUS_EXPANDING_WALK_FORWARD_EXECUTION_ALIGNED"
    assert "next-open" in summary["target"]["alpha"]
    assert summary["target"]["round_trip_cost_bps"]==22.0
    assert scored["v6_meta_probability"].notna().any()
    assert scored["v6_trade_score"].notna().any()
    refresh=summary["refreshes"][0]
    assert refresh["meta"]["selected_long_count"] in (5,8)
    assert refresh["meta"]["selected_threshold"] in (0.50,0.60)


def test_backtest_single_name_weight_cap_leaves_cash():
    from app.services.backtest import run_backtest
    dates=pd.bdate_range("2026-01-02",periods=40)
    rows=[]
    for si,symbol in enumerate(["A","B","C"]):
        for i,d in enumerate(dates):
            rows.append({
                "date":d,"symbol":symbol,"sector":"Test",
                "open":100+si+i*.1,"close":100+si+i*.1,
                "score":1-si*.1,"scale":1.0,"future_relative_20d":0.0,
            })
    panel=pd.DataFrame(rows)
    result=run_backtest(
        {
            "long_count":2,"short_count":0,"rebalance_days":10,
            "gross_exposure":1.0,"long_gross":1.0,
            "min_long_count":1,"normalize_position_scale":False,
            "max_abs_weight":0.10,
        },
        score_column="score",
        strategy_name="weight-cap",
        panel=panel,
        position_scale_column="scale",
    )
    assert result["position_ledger"]
    assert max(abs(float(x["weight"])) for x in result["position_ledger"])<=0.100001


def test_v7_diversification_rejects_highly_correlated_duplicate():
    from app.services.meta_v7 import _diversified_symbols

    corr=pd.DataFrame(
        [
            [1.0,.95,.10,.20],
            [.95,1.0,.15,.25],
            [.10,.15,1.0,.30],
            [.20,.25,.30,1.0],
        ],
        index=["A","B","C","D"],
        columns=["A","B","C","D"],
    )
    selected,diag=_diversified_symbols(
        ["A","B","C","D"],corr,max_names=3,corr_cap=.82,min_names=2
    )
    assert "A" in selected
    assert "B" not in selected
    assert "C" in selected
    assert diag["B"]>.82


def test_v7_market_risk_scale_is_one_sided():
    from app.services import meta_v7

    dates=pd.bdate_range("2025-01-02",periods=120)
    rows=[]
    for si,symbol in enumerate(["A","B","C","D"]):
        price=100+si
        for i,d in enumerate(dates):
            shock=.001*((i%5)-2)
            price*=1+shock
            rows.append({"date":d,"symbol":symbol,"close":price})
    base=pd.DataFrame(rows)
    a=meta_v7._market_risk_scale(base)

    changed=base.copy()
    future_dates=set(dates[-10:])
    changed.loc[changed.date.isin(future_dates),"close"]*=np.linspace(1.0,1.8,changed.date.isin(future_dates).sum())
    b=meta_v7._market_risk_scale(changed)

    cutoff=dates[-11]
    assert np.allclose(
        a.loc[a.index<=cutoff].to_numpy(),
        b.loc[b.index<=cutoff].to_numpy(),
        equal_nan=True,
    )


def test_backtest_account_curve_tracks_daily_equity_and_realized_balance():
    from app.services.backtest import run_backtest

    dates=pd.bdate_range("2026-01-02",periods=70)
    rows=[]
    for si,symbol in enumerate(["A","B","C","D"]):
        price=100.0+si
        for i,d in enumerate(dates):
            price*=1+(0.0015 if symbol=="A" else 0.0004)
            rows.append({
                "date":d,"symbol":symbol,"sector":"Test",
                "open":price,"close":price,
                "score":1.0-si*.2,
                "future_relative_20d":0.0,
            })
    panel=pd.DataFrame(rows)
    result=run_backtest(
        {
            "long_count":2,"short_count":0,"rebalance_days":10,
            "gross_exposure":1.0,"long_gross":1.0,
            "initial_capital":100000,
        },
        score_column="score",
        strategy_name="account-curve",
        panel=panel,
    )

    curve=result["account_curve"]
    assert len(curve)>len(result["equity_curve"])
    assert {"date","equity_usd","balance_usd","floating_pnl_usd","daily_pnl_usd","daily_return","drawdown","gross_exposure","cash_pct","turnover","trade_count","active_symbols"}<=set(curve[0])
    assert any(abs(float(row["equity_usd"])-float(row["balance_usd"]))>0.01 for row in curve[1:-1])
    assert all(isinstance(row["active_symbols"],list) for row in curve)
    assert all(float(row["gross_exposure"])>=0 for row in curve[:-1])
    assert any(int(row["trade_count"])>0 for row in curve)
    assert curve[-1]["equity_usd"]==curve[-1]["balance_usd"]
    assert curve[-1]["equity_usd"]==result["metrics"]["ending_capital_usd"]


def test_daily_metrics_use_calendar_time_and_cash_days():
    from app.services.backtest import run_backtest

    dates=pd.bdate_range("2022-01-03",periods=520)
    rows=[]
    for si,symbol in enumerate(["A","B","C","D"]):
        price=100.0+si
        for i,d in enumerate(dates):
            price*=1+(0.0007 if symbol=="A" else 0.0002)
            score=np.nan if 100<=i<160 else 1.0-si*.1
            rows.append({
                "date":d,"symbol":symbol,"sector":"Test",
                "open":price,"close":price,
                "score":score,"future_relative_20d":0.0,
            })
    panel=pd.DataFrame(rows)
    result=run_backtest(
        {
            "long_count":2,"short_count":0,"rebalance_days":10,
            "gross_exposure":1.0,"long_gross":1.0,
            "initial_capital":100000,
            "min_long_count":1,
        },
        score_column="score",
        strategy_name="daily-metrics",
        panel=panel,
    )

    metrics=result["metrics"]
    curve=result["account_curve"]
    assert metrics["metric_frequency"]=="DAILY_MARK_TO_MARKET"
    assert metrics["metric_observations"]==len(curve)
    assert metrics["elapsed_years"]>1.8
    # The skipped-signal zone must remain present as zero-return cash days.
    zero_cash=[
        row for row in curve
        if row["gross_exposure"]==0 and row["cash_pct"]==1.0 and abs(row["daily_return"])<1e-12
    ]
    assert len(zero_cash)>20


def test_daily_max_drawdown_catches_intraperiod_loss():
    from app.services.backtest import _metrics

    daily=[
        {"date":"2026-01-02","equity_usd":100000.0,"daily_return":0.0},
        {"date":"2026-01-05","equity_usd":90000.0,"daily_return":-0.10},
        {"date":"2026-01-06","equity_usd":100000.0,"daily_return":1/9},
    ]
    rebalance=[
        {"date":"2026-01-06","equity":1.0,"return":0.0},
        {"date":"2026-01-07","equity":1.0,"return":0.0},
    ]
    m=_metrics(rebalance,1.0,[0.0,0.0],25.2,daily_curve=daily,initial_capital=100000.0)
    assert m["max_drawdown"]==-0.10


def test_quality_universe_filters_recent_illiquid_and_non_operating_names(monkeypatch,tmp_path):
    from app.services import real_data

    monkeypatch.setattr(real_data,"DATA_DIR",str(tmp_path))
    monkeypatch.setattr(real_data.settings,"real_universe_size",2)
    monkeypatch.setattr(real_data.settings,"real_universe_prefilter_size",4)
    monkeypatch.setattr(real_data.settings,"real_universe_min_price",10.0)
    monkeypatch.setattr(real_data.settings,"real_universe_min_history_sessions",1000)
    monkeypatch.setattr(real_data.settings,"real_universe_min_median_dollar_volume",50_000_000.0)
    monkeypatch.setattr(real_data.settings,"real_universe_max_volatility",0.65)
    monkeypatch.setattr(real_data.settings,"real_universe_min_sec_core_metrics",3)

    monkeypatch.setattr(real_data,"_snapshot_rank",lambda candidates:[
        ("AAPL",2_000_000_000.0,200.0,10_000_000.0),
        ("MSFT",1_800_000_000.0,450.0,4_000_000.0),
        ("NEWCO",1_700_000_000.0,50.0,34_000_000.0),
        ("TQQQ",1_600_000_000.0,80.0,20_000_000.0),
    ])
    monkeypatch.setattr(real_data,"_quality_history",lambda symbols:pd.DataFrame([
        {"symbol":"AAPL","history_sessions":1200,"last_price":200.0,"median_dollar_volume_60":1_500_000_000.0,"volatility_60":0.25},
        {"symbol":"MSFT","history_sessions":1200,"last_price":450.0,"median_dollar_volume_60":1_200_000_000.0,"volatility_60":0.22},
        {"symbol":"NEWCO","history_sessions":180,"last_price":50.0,"median_dollar_volume_60":900_000_000.0,"volatility_60":0.55},
        {"symbol":"TQQQ","history_sessions":1200,"last_price":80.0,"median_dollar_volume_60":1_600_000_000.0,"volatility_60":0.60},
    ]))
    monkeypatch.setattr(real_data,"_sec_operating_quality",lambda symbols:pd.DataFrame([
        {"symbol":"AAPL","sec_core_metrics":5,"sec_balance_ok":True,"sec_activity_ok":True,"sec_earning_power":True,"sec_operating_company":True},
        {"symbol":"MSFT","sec_core_metrics":5,"sec_balance_ok":True,"sec_activity_ok":True,"sec_earning_power":True,"sec_operating_company":True},
        {"symbol":"TQQQ","sec_core_metrics":0,"sec_balance_ok":False,"sec_activity_ok":False,"sec_earning_power":False,"sec_operating_company":False},
    ]))

    selected=real_data._quality_rank_universe(["AAPL","MSFT","NEWCO","TQQQ"])
    assert selected==["AAPL","MSFT"]


def test_asset_candidates_exclude_leveraged_etf_sponsors(monkeypatch):
    from app.services import real_data

    monkeypatch.setattr(real_data,"get_assets",lambda:[
        {"symbol":"TQQQ","name":"ProShares UltraPro QQQ","exchange":"NASDAQ","tradable":True,"fractionable":True},
        {"symbol":"AAPL","name":"Apple Inc. Common Stock","exchange":"NASDAQ","tradable":True,"fractionable":True},
    ])
    assert real_data._asset_candidates()==["AAPL"]


def test_v71_balanced_exposure_uses_confidence_and_regime():
    from app.services.meta_v71 import _target_gross,apply_v71_balanced_exposure

    base=pd.DataFrame([
        {
            "date":pd.Timestamp("2026-01-02"),"symbol":"A","v7_trade_score":0.9,
            "v7_probability_scale":0.20,"v7_vol_scale":0.80,"v7_market_risk_scale":0.50,
            "v7_threshold":0.50,"v6_meta_probability":0.58,"v6_regime":"RISK_OFF",
        },
        {
            "date":pd.Timestamp("2026-01-02"),"symbol":"B","v7_trade_score":0.8,
            "v7_probability_scale":0.30,"v7_vol_scale":1.00,"v7_market_risk_scale":0.50,
            "v7_threshold":0.50,"v6_meta_probability":0.60,"v6_regime":"RISK_OFF",
        },
    ])
    target_risk,_=_target_gross(base)

    trend=base.copy()
    trend["v6_regime"]="TREND_UP"
    trend["v7_market_risk_scale"]=1.0
    trend["v6_meta_probability"]=0.70
    target_trend,_=_target_gross(trend)

    assert 0.25<=target_risk<=0.95
    assert target_trend>target_risk

    scored,summary=apply_v71_balanced_exposure(base)
    selected=scored[scored["v71_trade_score"].notna()]
    assert len(selected)==2
    assert float(selected["v71_position_scale"].mean())>=0.25
    assert float(selected["v71_position_scale"].max())<=1.0
    assert summary["decision_dates"]==1


def test_feature_solid_eligibility_is_point_in_time_and_maturity_gated(monkeypatch):
    from app.services import features

    monkeypatch.setattr(features.settings,"real_universe_min_price",10.0)
    monkeypatch.setattr(features.settings,"real_trade_min_history_sessions",5)
    monkeypatch.setattr(features.settings,"real_trade_min_median_dollar_volume",1.0)
    monkeypatch.setattr(features.settings,"real_trade_max_volatility",2.0)

    dates=pd.bdate_range("2026-01-02",periods=70)
    df=pd.DataFrame({
        "date":dates,
        "symbol":["A"]*len(dates),
        "close":np.linspace(100,110,len(dates)),
        "volume":[1_000_000]*len(dates),
        "solid_fundamental_eligible":[False]*35+[True]*35,
    })
    out=features._technical(df)
    assert not bool(out.iloc[34]["solid_eligible"])
    assert bool(out.iloc[-1]["solid_eligible"])


def test_current_universe_size_gate_does_not_require_current_profit(monkeypatch):
    from app.services import real_data

    class FakeSettings:
        real_universe_min_sec_core_metrics=3
        real_universe_min_revenue=1_000_000_000.0
        real_universe_min_assets=5_000_000_000.0

    # Reuse the real settings object fields through monkeypatch.
    monkeypatch.setattr(real_data.settings,"real_universe_min_sec_core_metrics",3)
    monkeypatch.setattr(real_data.settings,"real_universe_min_revenue",1_000_000_000.0)
    monkeypatch.setattr(real_data.settings,"real_universe_min_assets",5_000_000_000.0)

    def fake_events(symbol):
        values={
            "revenue":2_000_000_000.0,
            "net_income":-250_000_000.0,
            "assets":12_000_000_000.0,
            "equity":4_000_000_000.0,
            "operating_cf":-100_000_000.0,
        }
        return pd.DataFrame([
            {
                "symbol":symbol,
                "metric":metric,
                "value":value,
                "period_end":pd.Timestamp("2025-12-31"),
                "available_at":pd.Timestamp("2026-02-15"),
            }
            for metric,value in values.items()
        ])

    import app.services.sec_fundamentals as sf
    monkeypatch.setattr(sf,"fundamental_events",fake_events)
    row=real_data._sec_operating_quality(["BIGCO"]).iloc[0]
    assert bool(row["sec_operating_company"])
    assert not bool(row["sec_earning_power"])
    assert bool(row["sec_size_ok"])


def test_point_in_time_solid_gate_uses_size_not_profit(monkeypatch):
    from app.services import sec_fundamentals as sf

    monkeypatch.setattr(sf.settings,"real_universe_min_sec_core_metrics",3)
    monkeypatch.setattr(sf.settings,"real_universe_min_revenue",1_000_000_000.0)
    monkeypatch.setattr(sf.settings,"real_universe_min_assets",5_000_000_000.0)

    dates=pd.DatetimeIndex([pd.Timestamp("2026-03-01")])
    events=pd.DataFrame([
        {"symbol":"BIGCO","metric":"revenue","value":2_000_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BIGCO","metric":"net_income","value":-300_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BIGCO","metric":"assets","value":10_000_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BIGCO","metric":"equity","value":4_000_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BIGCO","metric":"operating_cf","value":-50_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
    ])
    monkeypatch.setattr(sf,"fundamental_events",lambda symbol,force=False:events)
    panel=sf.point_in_time_panel(["BIGCO"],dates)
    assert bool(panel.iloc[0]["solid_fundamental_eligible"])


def test_v7_market_risk_floor_is_explicitly_stressable():
    from app.services import meta_v7

    dates=pd.bdate_range("2025-01-02",periods=140)
    rows=[]
    for si,symbol in enumerate(["A","B","C","D","E"]):
        price=100.0+si
        for i,d in enumerate(dates):
            # Calm history followed by a volatile tail so the lower clip matters.
            shock=(0.001*((i%5)-2)) if i<110 else (0.025*((i%3)-1))
            price*=1+shock
            rows.append({"date":d,"symbol":symbol,"close":price})
    frame=pd.DataFrame(rows)

    low=meta_v7._market_risk_scale(frame,floor=.35)
    high=meta_v7._market_risk_scale(frame,floor=.65)
    assert float(low.min())>=.35-1e-12
    assert float(high.min())>=.65-1e-12
    assert float(high.iloc[-1])>=float(low.iloc[-1])


def test_research_cache_round_trip(monkeypatch,tmp_path):
    from app.services import research_cache

    monkeypatch.setattr(research_cache,"ROOT",tmp_path)
    key=research_cache.make_key(
        "meta_v6_oos","dataset-123","version-1",{"a":1},{"features":["x","y"]}
    )
    frame=pd.DataFrame({
        "date":pd.to_datetime(["2026-01-02","2026-01-05"]),
        "symbol":["A","B"],
        "score":[0.1,0.2],
    })
    research={"simulation":{"coverage_ratio":0.75},"oos_mean_rank_ic":0.03}
    research_cache.save("meta_v6_oos",key,frame,research,"dataset-123")

    loaded=research_cache.load("meta_v6_oos",key)
    assert loaded is not None
    cached_frame,cached_research,meta=loaded
    assert list(cached_frame["symbol"])==["A","B"]
    assert cached_research["simulation"]["coverage_ratio"]==0.75
    assert meta["dataset_fingerprint"]=="dataset-123"
    assert research_cache.load("meta_v6_oos","wrong-key") is None


def test_point_in_time_solid_gate_allows_bounded_negative_equity(monkeypatch):
    from app.services import sec_fundamentals as sf

    monkeypatch.setattr(sf.settings,"real_universe_min_sec_core_metrics",3)
    monkeypatch.setattr(sf.settings,"real_universe_min_revenue",1_000_000_000.0)
    monkeypatch.setattr(sf.settings,"real_universe_min_assets",5_000_000_000.0)

    dates=pd.DatetimeIndex([pd.Timestamp("2026-03-01")])
    events=pd.DataFrame([
        {"symbol":"BUYBACK","metric":"revenue","value":8_000_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BUYBACK","metric":"net_income","value":700_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BUYBACK","metric":"assets","value":20_000_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BUYBACK","metric":"equity","value":-3_000_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
        {"symbol":"BUYBACK","metric":"operating_cf","value":1_200_000_000.0,"period_end":pd.Timestamp("2025-12-31"),"available_at":pd.Timestamp("2026-02-15")},
    ])
    monkeypatch.setattr(sf,"fundamental_events",lambda symbol,force=False:events)
    panel=sf.point_in_time_panel(["BUYBACK"],dates)
    assert bool(panel.iloc[0]["solid_fundamental_eligible"])
    assert pd.isna(panel.iloc[0]["roe"])
