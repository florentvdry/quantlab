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

def test_meta_v5_nested_walk_forward_has_outer_embargo(monkeypatch):
    from app.services import meta_v5
    from app.services.features import FEATURES
    dates=pd.bdate_range("2023-01-02",periods=430)
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
    monkeypatch.setitem(meta_v5.V5_CONFIG,"min_train_days",320)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"validation_days",60)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"test_days",50)
    monkeypatch.setitem(meta_v5.V5_CONFIG,"lgbm_members",1)
    scored,summary=meta_v5.build_meta_v5_oos(panel=panel)
    assert summary["folds"]
    pos={d:i for i,d in enumerate(sorted(panel.date.unique()))}
    for fold in summary["folds"]:
        vto=pd.Timestamp(fold["validation_to"])
        tfrom=pd.Timestamp(fold["test_from"])
        assert pos[tfrom]-pos[vto]>=20
        assert fold["meta"]["calibration_embargo_days"]>=0
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
