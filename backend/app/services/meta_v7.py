from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from app.services.features import build_feature_panel, panel_metadata
from app.services.meta_v6 import (
    V6_CONFIG,
    _size_from_probability,
    build_meta_v6_oos,
)

V7_CONFIG = {
    "corr_lookback_days": 63,
    "corr_cap": 0.82,
    "max_names": 12,
    "min_names": 5,
    "market_vol_lookback_days": 20,
    "market_vol_reference_min_days": 60,
    "market_risk_floor": 0.45,
    "single_name_weight_cap": 0.10,
}

V7_PORTFOLIO = {
    "long_count": 12,
    "short_count": 0,
    "rebalance_days": 10,
    "warmup_days": 0,
    "commission_bps": 6.0,
    "slippage_bps": 5.0,
    "gross_exposure": 1.0,
    "long_gross": 1.0,
    "short_gross": 0.0,
    "initial_capital": 100000.0,
    "rank_buffer": 3,
    "rebalance_threshold_pct": 0.15,
    "min_trade_notional": 250.0,
    "min_long_count": 3,
    "normalize_position_scale": False,
    "max_abs_weight": 0.10,
}


def _daily_return_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame[["date", "symbol", "close"]].drop_duplicates(["date", "symbol"]).copy()
    x = x.sort_values(["symbol", "date"])
    x["ret_1d"] = x.groupby("symbol")["close"].pct_change(fill_method=None)
    return x.pivot(index="date", columns="symbol", values="ret_1d").sort_index()


def _market_risk_scale(frame: pd.DataFrame) -> pd.Series:
    returns = _daily_return_matrix(frame)
    market_ret = returns.mean(axis=1, skipna=True)
    lookback = int(V7_CONFIG["market_vol_lookback_days"])
    market_vol = market_ret.rolling(lookback, min_periods=lookback).std() * np.sqrt(252)
    ref = market_vol.expanding(
        min_periods=int(V7_CONFIG["market_vol_reference_min_days"])
    ).median().shift(1)
    scale = (ref / market_vol.replace(0, np.nan)).clip(
        lower=float(V7_CONFIG["market_risk_floor"]),
        upper=1.0,
    )
    return scale.fillna(1.0)


def _diversified_symbols(
    candidates: list[str],
    corr: pd.DataFrame,
    max_names: int,
    corr_cap: float,
    min_names: int,
) -> tuple[list[str], dict[str, float]]:
    selected: list[str] = []
    rejected: list[tuple[str, float]] = []
    max_corr_seen: dict[str, float] = {}

    for symbol in candidates:
        if len(selected) >= max_names:
            break
        if not selected:
            selected.append(symbol)
            max_corr_seen[symbol] = 0.0
            continue

        values = []
        if symbol in corr.index:
            for other in selected:
                if other in corr.columns:
                    value = corr.at[symbol, other]
                    if np.isfinite(value):
                        values.append(float(value))
        max_corr = max(values) if values else 0.0
        max_corr_seen[symbol] = max_corr
        if max_corr <= corr_cap:
            selected.append(symbol)
        else:
            rejected.append((symbol, max_corr))

    # Never let diversification rules turn a valid signal set into an unusably
    # tiny portfolio. Backfill the least-correlated rejected candidates first.
    if len(selected) < min_names:
        for symbol, max_corr in sorted(rejected, key=lambda item: item[1]):
            if symbol not in selected:
                selected.append(symbol)
                max_corr_seen[symbol] = max_corr
            if len(selected) >= min_names:
                break

    return selected[:max_names], max_corr_seen


def _refresh_thresholds(research: dict) -> dict[int, float]:
    out = {}
    for row in research.get("refreshes", []):
        rid = int(row.get("refresh") or 0)
        threshold = (row.get("meta") or {}).get("selected_threshold")
        if rid and threshold is not None:
            out[rid] = float(threshold)
    return out


def apply_v7_risk_overlay(
    scored: pd.DataFrame,
    research: dict,
    *,
    corr_cap: float | None = None,
    max_names: int | None = None,
) -> tuple[pd.DataFrame, dict]:
    out = scored.copy().sort_values(["date", "symbol"])
    all_dates = np.array(sorted(out["date"].unique()))
    decision_dates = set(all_dates[:: int(V7_PORTFOLIO["rebalance_days"])])
    if len(all_dates):
        decision_dates.add(all_dates[-1])

    corr_cap = float(V7_CONFIG["corr_cap"] if corr_cap is None else corr_cap)
    max_names = int(V7_CONFIG["max_names"] if max_names is None else max_names)
    min_names = int(V7_CONFIG["min_names"])

    out["v7_trade_score"] = np.nan
    out["v7_position_scale"] = 0.0
    out["v7_probability_scale"] = 0.0
    out["v7_vol_scale"] = 0.0
    out["v7_market_risk_scale"] = 0.0
    out["v7_max_corr"] = np.nan
    out["v7_threshold"] = np.nan

    returns = _daily_return_matrix(out)
    market_scale = _market_risk_scale(out)
    thresholds = _refresh_thresholds(research)
    selected_counts = []
    gross_scale_estimates = []

    for signal_date in sorted(decision_dates):
        mask = out["date"].eq(signal_date)
        day = out.loc[mask].copy()
        if day["v6_meta_probability"].notna().sum() == 0:
            continue

        refresh_values = day["v6_refresh_id"].dropna()
        if refresh_values.empty:
            continue
        refresh_id = int(refresh_values.iloc[0])
        threshold = float(thresholds.get(refresh_id, 0.60))

        candidates = day[
            day["v6_meta_probability"].notna()
            & (day["v6_meta_probability"] >= threshold)
            & day["v6_smooth_score"].notna()
        ].sort_values("v6_smooth_score", ascending=False)
        if candidates.empty:
            continue

        history = returns.loc[returns.index <= signal_date].tail(
            int(V7_CONFIG["corr_lookback_days"])
        )
        symbols = [s for s in candidates["symbol"].tolist() if s in history.columns]
        corr = history[symbols].corr(min_periods=max(20, int(len(history) * 0.5))) if symbols else pd.DataFrame()

        selected, corr_diag = _diversified_symbols(
            candidates["symbol"].tolist(),
            corr,
            max_names=max_names,
            corr_cap=corr_cap,
            min_names=min(min_names, len(candidates)),
        )
        if not selected:
            continue

        chosen = candidates[candidates["symbol"].isin(selected)].copy()
        probability_scale = _size_from_probability(
            chosen["v6_meta_probability"].to_numpy(dtype=float),
            threshold,
        )

        median_vol = float(chosen["vol_20d"].replace([np.inf, -np.inf], np.nan).median())
        if not np.isfinite(median_vol) or median_vol <= 0:
            vol_scale = np.ones(len(chosen), dtype=float)
        else:
            vols = chosen["vol_20d"].to_numpy(dtype=float)
            ratio = np.divide(
                median_vol,
                vols,
                out=np.ones_like(vols, dtype=float),
                where=np.isfinite(vols) & (vols > 0),
            )
            # Square-root inverse-vol is deliberately gentler than full risk parity:
            # it cuts extreme names without erasing the alpha ranking.
            vol_scale = np.sqrt(np.clip(ratio, 0.1225, 1.0))
            vol_scale = np.clip(vol_scale, 0.35, 1.0)

        mscale = float(market_scale.get(signal_date, 1.0))
        final_scale = np.clip(probability_scale * vol_scale * mscale, 0.0, 1.0)

        idx = chosen.index
        out.loc[idx, "v7_trade_score"] = chosen["v6_smooth_score"].to_numpy(dtype=float)
        out.loc[idx, "v7_probability_scale"] = probability_scale
        out.loc[idx, "v7_vol_scale"] = vol_scale
        out.loc[idx, "v7_market_risk_scale"] = mscale
        out.loc[idx, "v7_position_scale"] = final_scale
        out.loc[idx, "v7_threshold"] = threshold
        out.loc[idx, "v7_max_corr"] = [
            float(corr_diag.get(symbol, 0.0)) for symbol in chosen["symbol"]
        ]

        selected_counts.append(len(chosen))
        gross_scale_estimates.append(float(np.mean(final_scale)))

    overlay = {
        "corr_lookback_days": int(V7_CONFIG["corr_lookback_days"]),
        "corr_cap": corr_cap,
        "max_names": max_names,
        "min_names": min_names,
        "market_vol_lookback_days": int(V7_CONFIG["market_vol_lookback_days"]),
        "market_risk_floor": float(V7_CONFIG["market_risk_floor"]),
        "single_name_weight_cap": float(V7_CONFIG["single_name_weight_cap"]),
        "mean_selected_names": round(float(np.mean(selected_counts)), 3) if selected_counts else None,
        "mean_position_scale": round(float(np.mean(gross_scale_estimates)), 4) if gross_scale_estimates else None,
        "decision_dates_with_positions": int(len(selected_counts)),
        "method": "PAST_ONLY_CORRELATION_DIVERSIFICATION_PLUS_VOLATILITY_SCALING",
    }
    return out, overlay


def build_meta_v7_oos(
    panel: pd.DataFrame | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> tuple[pd.DataFrame, dict]:
    source = build_feature_panel() if panel is None else panel
    if progress:
        progress(8, "META V7 — génération des signaux V6 de contrôle")
    scored, v6_research = build_meta_v6_oos(panel=source, progress=progress)
    if progress:
        progress(76, "META V7 — diversification corrélation + volatility scaling")
    overlaid, overlay = apply_v7_risk_overlay(scored, v6_research)

    research = {
        "name": "META Ensemble v7 Diversified Risk",
        "dataset": panel_metadata(source),
        "parent_model": "META Ensemble v6 Risk-Aware",
        "simulation": {
            **v6_research.get("simulation", {}),
            "method": "CONTINUOUS_OOS_V6_PLUS_PAST_ONLY_RISK_OVERLAY",
        },
        "target": v6_research.get("target", {}),
        "risk_overlay": overlay,
        "v6_oos_mean_rank_ic": v6_research.get("oos_mean_rank_ic"),
        "v6_positive_oos_ic_ratio": v6_research.get("positive_oos_ic_ratio"),
        "design_status": "EXPLORATORY_AFTER_V6_DIAGNOSTIC",
        "audit": (
            "V7 does not retrain alpha after seeing V6 results. It reuses V6 OOS predictions and "
            "adds only past-data risk controls: trailing correlation diversification, square-root "
            "inverse-vol sizing, market-vol exposure scaling and a single-name cap."
        ),
    }
    return overlaid, research


def run_meta_v7(
    panel: pd.DataFrame | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> dict:
    from app.services.backtest import run_backtest

    scored, research = build_meta_v7_oos(panel=panel, progress=progress)
    if progress:
        progress(82, "META V7 — backtest du risk overlay")
    result = run_backtest(
        V7_PORTFOLIO,
        score_column="v7_trade_score",
        strategy_name="META Ensemble v7 Diversified Risk",
        panel=scored,
        position_scale_column="v7_position_scale",
    )
    result["meta_v7"] = research
    result["research_status"] = "EXPERIMENTAL_POST_DIAGNOSTIC_RISK_OVERLAY"
    result["audit_note"] += (
        " V7 is a post-diagnostic research challenger. It keeps V6 alpha unchanged and applies "
        "only controls computable at signal close from historical data. Historical performance "
        "must therefore be treated as exploratory until future shadow validation."
    )
    return result


def meta_v7_validation_bundle(panel: pd.DataFrame | None = None, progress=None) -> dict:
    from app.services.backtest import run_backtest

    source = build_feature_panel() if panel is None else panel
    if progress:
        progress(8, "META V7 — construction V6 OOS")
    v6_scored, v6_research = build_meta_v6_oos(panel=source, progress=progress)

    overlays = [
        ("base", float(V7_CONFIG["corr_cap"]), int(V7_CONFIG["max_names"])),
        ("corr_075", 0.75, int(V7_CONFIG["max_names"])),
        ("corr_090", 0.90, int(V7_CONFIG["max_names"])),
        ("max_10", float(V7_CONFIG["corr_cap"]), 10),
        ("max_15", float(V7_CONFIG["corr_cap"]), 15),
    ]

    rows = []
    base_result = None
    base_research = None
    for i, (name, cap, names) in enumerate(overlays):
        if progress:
            progress(76 + int(15 * i / len(overlays)), f"META V7 risk stress: {name}")
        scored, overlay = apply_v7_risk_overlay(
            v6_scored,
            v6_research,
            corr_cap=cap,
            max_names=names,
        )
        result = run_backtest(
            V7_PORTFOLIO | {"long_count": names},
            score_column="v7_trade_score",
            strategy_name=f"META V7 {name}",
            panel=scored,
            position_scale_column="v7_position_scale",
        )
        rows.append({"scenario": name, **result["metrics"], "risk_overlay": overlay})
        if name == "base":
            base_result = result
            base_research = {
                "name": "META Ensemble v7 Diversified Risk",
                "dataset": panel_metadata(source),
                "parent_model": "META Ensemble v6 Risk-Aware",
                "simulation": {
                    **v6_research.get("simulation", {}),
                    "method": "CONTINUOUS_OOS_V6_PLUS_PAST_ONLY_RISK_OVERLAY",
                },
                "target": v6_research.get("target", {}),
                "risk_overlay": overlay,
                "design_status": "EXPLORATORY_AFTER_V6_DIAGNOSTIC",
            }

    if base_result is None:
        raise RuntimeError("META V7 base scenario missing")

    # Cost stress reuses the exact same selected historical positions.
    base_scored, _ = apply_v7_risk_overlay(v6_scored, v6_research)
    for name, mult in (("cost_x2", 2.0), ("cost_x3", 3.0)):
        result = run_backtest(
            V7_PORTFOLIO | {
                "commission_bps": 6.0 * mult,
                "slippage_bps": 5.0 * mult,
            },
            score_column="v7_trade_score",
            strategy_name=f"META V7 {name}",
            panel=base_scored,
            position_scale_column="v7_position_scale",
        )
        rows.append({"scenario": name, **result["metrics"]})

    sharpes = np.asarray([row["sharpe"] for row in rows], dtype=float)
    robustness = {
        "positive_sharpe_ratio": round(float((sharpes > 0).mean()), 4),
        "median_sharpe": round(float(np.median(sharpes)), 3),
        "min_sharpe": round(float(np.min(sharpes)), 3),
        "cost_stress_pass": all(
            row["sharpe"] > 0
            for row in rows
            if row["scenario"] in ("cost_x2", "cost_x3")
        ),
        "scenario_count": len(rows),
    }

    base_result["meta_v7"] = base_research
    base_result["research_status"] = "EXPERIMENTAL_POST_DIAGNOSTIC_RISK_OVERLAY"
    return {
        "backtest": base_result,
        "research": base_research,
        "robustness": robustness,
        "scenarios": rows,
    }
