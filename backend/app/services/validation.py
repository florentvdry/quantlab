from __future__ import annotations

from app.services.backtest import run_momentum_baseline, run_meta_v4
from app.services.data_quality import report as data_quality_report
from app.services.features import build_feature_panel, panel_metadata
from app.services.meta_v5 import meta_v5_validation_bundle

PAPER_THRESHOLDS = {
    "sharpe": 0.75,
    "cagr": 0.05,
    "rank_ic": 0.02,
    "positive_oos_ic_ratio": 0.55,
    "max_drawdown": -0.25,
    "excess_cagr_vs_equal_weight": 0.0,
    "avg_turnover": 0.35,
    "robust_median_sharpe": 0.50,
    "robust_min_sharpe": 0.0,
    "min_acceptance_rate": 0.10,
    "max_acceptance_rate": 0.80,
}


def validation_report(params=None, progress=None, panel=None, bundle=None):
    panel = build_feature_panel() if panel is None else panel
    dq = data_quality_report()
    bundle = meta_v5_validation_bundle(panel=panel, progress=progress) if bundle is None else bundle
    candidate = bundle["backtest"]
    research = bundle["research"]
    robust = bundle["robustness"]

    # Benchmarks stay independent of the V5 meta layer.
    baseline = run_momentum_baseline(params, panel=panel)
    v4 = run_meta_v4(panel=panel)

    m = candidate["metrics"]
    folds = research.get("folds", [])
    fold_ics = [f.get("rank_ic") for f in folds if f.get("rank_ic") is not None]
    positive_fold_ratio = (
        sum(1 for x in fold_ics if x > 0) / len(fold_ics) if fold_ics else 0.0
    )
    acceptance = float(research.get("overall_acceptance_rate") or 0.0)

    checks = [
        {"name": "data_quality", "ok": dq.get("status") == "PASS", "detail": dq.get("status")},
        {
            "name": "dataset_provenance",
            "ok": bool(candidate.get("dataset", {}).get("fingerprint")),
            "detail": candidate.get("dataset"),
        },
        {
            "name": "execution_timing",
            "ok": candidate.get("execution_timing") == "signal_close_T__entry_open_T1",
            "detail": candidate.get("execution_timing"),
        },
        {
            "name": "strict_nested_oos",
            "ok": candidate.get("research_status") == "STRICT_OOS_NESTED_WALK_FORWARD",
            "detail": candidate.get("research_status"),
        },
        {
            "name": "historical_news_no_leakage",
            "ok": candidate.get("dataset", {}).get("historical_news") == "neutral_no_point_in_time_history",
            "detail": candidate.get("dataset", {}).get("historical_news"),
        },
        {
            "name": "sharpe_at_least_0_75",
            "ok": m.get("sharpe", -99) >= PAPER_THRESHOLDS["sharpe"],
            "detail": m.get("sharpe"),
        },
        {
            "name": "cagr_at_least_5pct",
            "ok": m.get("cagr", -99) >= PAPER_THRESHOLDS["cagr"],
            "detail": m.get("cagr"),
        },
        {
            "name": "oos_rank_ic_at_least_0_02",
            "ok": (research.get("oos_mean_rank_ic") or -99) >= PAPER_THRESHOLDS["rank_ic"],
            "detail": research.get("oos_mean_rank_ic"),
        },
        {
            "name": "positive_oos_ic_days",
            "ok": (research.get("positive_oos_ic_ratio") or 0) >= PAPER_THRESHOLDS["positive_oos_ic_ratio"],
            "detail": research.get("positive_oos_ic_ratio"),
        },
        {
            "name": "positive_oos_folds",
            "ok": positive_fold_ratio >= 0.60,
            "detail": {"ratio": round(positive_fold_ratio, 4), "fold_ics": fold_ics},
        },
        {
            "name": "max_drawdown_better_than_minus_25pct",
            "ok": m.get("max_drawdown", -99) >= PAPER_THRESHOLDS["max_drawdown"],
            "detail": m.get("max_drawdown"),
        },
        {
            "name": "beats_equal_weight_cagr",
            "ok": (m.get("excess_cagr_vs_equal_weight") or -99) > PAPER_THRESHOLDS["excess_cagr_vs_equal_weight"],
            "detail": {
                "candidate": m.get("cagr"),
                "equal_weight": m.get("benchmark_cagr"),
                "excess": m.get("excess_cagr_vs_equal_weight"),
            },
        },
        {
            "name": "turnover_under_35pct",
            "ok": (m.get("avg_turnover_per_rebalance") or 99) <= PAPER_THRESHOLDS["avg_turnover"],
            "detail": m.get("avg_turnover_per_rebalance"),
        },
        {
            "name": "meta_filter_not_degenerate",
            "ok": PAPER_THRESHOLDS["min_acceptance_rate"] <= acceptance <= PAPER_THRESHOLDS["max_acceptance_rate"],
            "detail": acceptance,
        },
        {
            "name": "robustness_median_sharpe",
            "ok": robust.get("median_sharpe", -99) >= PAPER_THRESHOLDS["robust_median_sharpe"],
            "detail": robust,
        },
        {
            "name": "robustness_worst_case_positive",
            "ok": robust.get("min_sharpe", -99) >= PAPER_THRESHOLDS["robust_min_sharpe"],
            "detail": robust.get("min_sharpe"),
        },
        {
            "name": "cost_stress_x2_x3",
            "ok": bool(robust.get("cost_stress_pass")),
            "detail": "META V5 must remain Sharpe > 0 under x2/x3 costs",
        },
    ]

    core = checks[:5]
    quality = checks[5:]
    passed = all(c["ok"] for c in checks)
    quality_passes = sum(1 for c in quality if c["ok"])
    if passed:
        tier = "PAPER_READY"
    elif all(c["ok"] for c in core) and quality_passes >= 8:
        tier = "CANDIDATE"
    else:
        tier = "RESEARCH_ONLY"

    return {
        "passed": passed,
        "paper_eligible": passed,
        "tier": tier,
        "candidate_strategy": "META Ensemble v5 OOS",
        "thresholds": PAPER_THRESHOLDS,
        "dataset": panel_metadata(panel),
        "checks": checks,
        "meta_v5_backtest": m,
        "meta_v5_research": research,
        "meta_v5_robustness": robust,
        "meta_v5_scenarios": bundle["scenarios"],
        "baseline_backtest": baseline["metrics"],
        "v4_backtest": v4["metrics"],
    }
