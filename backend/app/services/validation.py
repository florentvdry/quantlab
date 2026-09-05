from __future__ import annotations
from app.services.features import build_feature_panel,panel_metadata
from app.services.backtest import run_backtest,run_momentum_baseline,run_adaptive_meta
from app.services.research import train_walk_forward
from app.services.data_quality import report as data_quality_report
from app.services.experiments import robustness

PAPER_THRESHOLDS={
    "sharpe":0.75,
    "cagr":0.05,
    "rank_ic":0.02,
    "oos_ic":0.03,
    "positive_oos_ic_ratio":0.55,
    "max_drawdown":-0.25,
    "baseline_sharpe_edge":0.15,
    "robust_median_sharpe":0.50,
    "robust_min_sharpe":0.0,
}

def validation_report(params=None):
    panel=build_feature_panel()
    dq=data_quality_report()
    fixed=run_backtest(params,panel=panel)
    adaptive=run_adaptive_meta(params,panel=panel)
    baseline=run_momentum_baseline(params,panel=panel)
    ridge=train_walk_forward("ridge",panel=panel)
    rob=robustness(params,panel=panel,adaptive=True)

    m=adaptive["metrics"];b=baseline["metrics"];r=rob["summary"]
    checks=[
        {"name":"data_quality","ok":dq.get("status")=="PASS","detail":dq.get("status")},
        {"name":"dataset_provenance","ok":bool(adaptive.get("dataset",{}).get("fingerprint")),"detail":adaptive.get("dataset")},
        {"name":"execution_timing","ok":adaptive.get("execution_timing")=="signal_close_T__entry_open_T1","detail":adaptive.get("execution_timing")},
        {"name":"sharpe_at_least_0_75","ok":m.get("sharpe",0)>=PAPER_THRESHOLDS["sharpe"],"detail":m.get("sharpe")},
        {"name":"cagr_at_least_5pct","ok":m.get("cagr",0)>=PAPER_THRESHOLDS["cagr"],"detail":m.get("cagr")},
        {"name":"rank_ic_at_least_0_02","ok":(m.get("mean_rank_ic_20d") or 0)>=PAPER_THRESHOLDS["rank_ic"],"detail":m.get("mean_rank_ic_20d")},
        {"name":"walk_forward_oos_ic_at_least_0_03","ok":ridge.get("oos_mean_rank_ic",0)>=PAPER_THRESHOLDS["oos_ic"],"detail":{"ic":ridge.get("oos_mean_rank_ic"),"ir":ridge.get("oos_ic_ir")}},
        {"name":"walk_forward_positive_days","ok":ridge.get("positive_oos_ic_ratio",0)>=PAPER_THRESHOLDS["positive_oos_ic_ratio"],"detail":ridge.get("positive_oos_ic_ratio")},
        {"name":"max_drawdown_better_than_minus_25pct","ok":m["max_drawdown"]>=PAPER_THRESHOLDS["max_drawdown"],"detail":m["max_drawdown"]},
        {"name":"beats_momentum_by_0_15_sharpe","ok":m["sharpe"]-b["sharpe"]>=PAPER_THRESHOLDS["baseline_sharpe_edge"],"detail":{"adaptive":m["sharpe"],"baseline":b["sharpe"],"edge":round(m["sharpe"]-b["sharpe"],3)}},
        {"name":"robustness_median_sharpe","ok":r.get("median_sharpe",-99)>=PAPER_THRESHOLDS["robust_median_sharpe"],"detail":r},
        {"name":"robustness_worst_case_positive","ok":r.get("min_sharpe",-99)>=PAPER_THRESHOLDS["robust_min_sharpe"],"detail":r.get("min_sharpe")},
        {"name":"cost_stress_x2_x3","ok":bool(r.get("cost_stress_pass")),"detail":"Adaptive META must remain Sharpe > 0 under x2/x3 costs"},
    ]
    core=checks[:3]
    quality=checks[3:]
    passed=all(c["ok"] for c in checks)
    quality_passes=sum(1 for c in quality if c["ok"])
    if passed:
        tier="PAPER_READY"
    elif all(c["ok"] for c in core) and quality_passes>=7:
        tier="CANDIDATE"
    else:
        tier="RESEARCH_ONLY"
    return {
        "passed":passed,"paper_eligible":passed,"tier":tier,
        "candidate_strategy":"Adaptive META US v3",
        "thresholds":PAPER_THRESHOLDS,
        "dataset":panel_metadata(panel),"checks":checks,
        "adaptive_backtest":adaptive["metrics"],
        "fixed_meta_backtest":fixed["metrics"],
        "meta_backtest":adaptive["metrics"],
        "baseline_backtest":baseline["metrics"],
        "robustness":rob,
        "ridge_walk_forward":{
            "oos_mean_rank_ic":ridge["oos_mean_rank_ic"],
            "oos_ic_ir":ridge["oos_ic_ir"],
            "positive_oos_ic_ratio":ridge["positive_oos_ic_ratio"],
            "folds":ridge["folds"]
        }
    }
