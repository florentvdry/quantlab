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
    df=features.build_feature_panel().sort_values(["symbol","date"])
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
