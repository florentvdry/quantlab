from __future__ import annotations
from app.services.features import build_feature_panel,panel_metadata
from app.services.backtest import run_backtest,run_momentum_baseline
from app.services.research import train_walk_forward
from app.services.data_quality import report as data_quality_report
from app.services.experiments import robustness

def validation_report(params=None):
    panel=build_feature_panel();dq=data_quality_report();meta=run_backtest(params,panel=panel);baseline=run_momentum_baseline(params,panel=panel)
    ridge=train_walk_forward("ridge",panel=panel);rob=robustness(params,panel=panel)
    checks=[
        {"name":"data_quality","ok":dq.get("status")=="PASS","detail":dq.get("status")},
        {"name":"dataset_provenance","ok":bool(meta.get("dataset",{}).get("fingerprint")),"detail":meta.get("dataset")},
        {"name":"execution_timing","ok":meta.get("execution_timing")=="signal_close_T__entry_open_T1","detail":meta.get("execution_timing")},
        {"name":"positive_sharpe","ok":meta["metrics"].get("sharpe",0)>0,"detail":meta["metrics"].get("sharpe")},
        {"name":"rank_ic","ok":(meta["metrics"].get("mean_rank_ic_20d") or 0)>0,"detail":meta["metrics"].get("mean_rank_ic_20d")},
        {"name":"walk_forward_oos","ok":ridge.get("oos_mean_rank_ic",0)>0,"detail":{"ic":ridge.get("oos_mean_rank_ic"),"ir":ridge.get("oos_ic_ir")}},
        {"name":"max_drawdown","ok":meta["metrics"]["max_drawdown"]>-0.5,"detail":meta["metrics"]["max_drawdown"]},
        {"name":"baseline_comparison","ok":meta["metrics"]["sharpe"]>=baseline["metrics"]["sharpe"],"detail":{"meta":meta["metrics"]["sharpe"],"baseline":baseline["metrics"]["sharpe"]}},
        {"name":"robustness","ok":bool(rob["summary"].get("passed")),"detail":rob["summary"]},
        {"name":"cost_stress","ok":bool(rob["summary"].get("cost_stress_pass")),"detail":{"x2_x3":"Sharpe must remain > 0"}},
    ]
    return {"passed":all(c["ok"] for c in checks),"paper_eligible":all(c["ok"] for c in checks),"dataset":panel_metadata(panel),"checks":checks,
            "meta_backtest":meta["metrics"],"baseline_backtest":baseline["metrics"],"robustness":rob,
            "ridge_walk_forward":{"oos_mean_rank_ic":ridge["oos_mean_rank_ic"],"oos_ic_ir":ridge["oos_ic_ir"],"positive_oos_ic_ratio":ridge["positive_oos_ic_ratio"],"folds":ridge["folds"]}}
