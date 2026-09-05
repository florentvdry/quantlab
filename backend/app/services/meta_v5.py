from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.services.features import FEATURES, build_feature_panel, panel_metadata

# Historical news is intentionally excluded until QuantLab has a point-in-time
# news archive. Everything below must be available at the signal close.
MODEL_FEATURES = [f for f in FEATURES if f != "news_raw_rank"]
BASE_NAMES = ("ridge", "hgb", "lgbm", "momentum")
REGIMES = ("TREND_UP", "NEUTRAL", "HIGH_VOL", "RISK_OFF")

V5_PORTFOLIO = {
    "long_count": 15,
    "short_count": 0,
    "rebalance_days": 10,
    "commission_bps": 6.0,
    "slippage_bps": 5.0,
    "gross_exposure": 1.0,
    "long_gross": 1.0,
    "short_gross": 0.0,
    "initial_capital": 100000.0,
    "rank_buffer": 5,
    "rebalance_threshold_pct": 0.20,
    "min_trade_notional": 250.0,
    "min_long_count": 5,
    "normalize_position_scale": False,
}

V5_CONFIG = {
    "min_train_days": 504,
    "validation_days": 126,
    "test_days": 126,
    "embargo_days": 20,
    "ewma_span": 5,
    "meta_threshold_grid": [0.50, 0.55, 0.60, 0.65],
    "lgbm_members": 3,
}


class DoubleEnsembleLGBM:
    """Small, independent DoubleEnsemble-style learner.

    It borrows the public research idea (not source code): sequential learners
    focus more on hard training examples and may use a shrinking feature set.
    All reweighting/selection happens inside the training window.
    """

    def __init__(self, members: int = 3, seed: int = 42):
        self.members = members
        self.seed = seed
        self.models: list[LGBMRegressor] = []
        self.feature_sets: list[list[str]] = []

    def fit(self, x: pd.DataFrame, y: pd.Series):
        features = list(x.columns)
        weights = np.ones(len(x), dtype=float)
        train_pred = np.zeros(len(x), dtype=float)

        for k in range(self.members):
            model = LGBMRegressor(
                objective="regression",
                n_estimators=140,
                learning_rate=0.035,
                num_leaves=15,
                max_depth=4,
                min_child_samples=80,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_alpha=0.15,
                reg_lambda=2.0,
                random_state=self.seed + k,
                n_jobs=-1,
                verbosity=-1,
            )
            model.fit(x[features], y, sample_weight=weights)
            self.models.append(model)
            self.feature_sets.append(list(features))

            pred = model.predict(x[features])
            train_pred = (train_pred * k + pred) / (k + 1)
            residual = np.abs(y.to_numpy(dtype=float) - train_pred)
            # Hard examples get at most 3x the weight of easy examples.
            pct = pd.Series(residual).rank(pct=True).to_numpy()
            weights = 0.5 + 1.0 * pct

            if k + 1 < self.members and len(features) > 6:
                imp = pd.Series(model.feature_importances_, index=features)
                keep = max(6, int(math.ceil(len(features) * 0.8)))
                features = list(imp.sort_values(ascending=False).head(keep).index)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        if not self.models:
            raise RuntimeError("DoubleEnsembleLGBM is not fitted")
        preds = [m.predict(x[fs]) for m, fs in zip(self.models, self.feature_sets)]
        return np.mean(np.vstack(preds), axis=0)

    def diagnostics(self) -> dict:
        return {
            "members": len(self.models),
            "feature_sets": self.feature_sets,
        }


def _regime_frame(panel: pd.DataFrame) -> pd.DataFrame:
    daily = panel.groupby("date", as_index=False).agg(
        market_ret_20=("ret_20d", "mean"),
        market_vol_20=("vol_20d", "median"),
    ).sort_values("date")
    daily["vol_reference"] = daily["market_vol_20"].expanding(min_periods=60).median().shift(1)

    def classify(row):
        ret = row.market_ret_20
        vol = row.market_vol_20
        ref = row.vol_reference
        high_vol = np.isfinite(ref) and np.isfinite(vol) and vol > ref * 1.25
        if np.isfinite(ret) and ret < -0.03:
            return "RISK_OFF"
        if high_vol:
            return "HIGH_VOL"
        if np.isfinite(ret) and ret > 0.03:
            return "TREND_UP"
        return "NEUTRAL"

    daily["v5_regime"] = daily.apply(classify, axis=1)
    return panel.merge(daily[["date", "v5_regime"]], on="date", how="left")


def _new_base_models():
    return {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "hgb": HistGradientBoostingRegressor(
            max_iter=140, max_depth=4, learning_rate=0.05,
            l2_regularization=1.5, min_samples_leaf=50, random_state=42
        ),
        "lgbm": DoubleEnsembleLGBM(members=V5_CONFIG["lgbm_members"]),
    }


def _fit_base(train: pd.DataFrame):
    x = train[MODEL_FEATURES].fillna(0.5)
    y = train["future_relative_20d"].astype(float)
    models = _new_base_models()
    for model in models.values():
        model.fit(x, y)
    return models


def _predict_base(models, frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    x = out[MODEL_FEATURES].fillna(0.5)
    out["pred_ridge"] = models["ridge"].predict(x)
    out["pred_hgb"] = models["hgb"].predict(x)
    out["pred_lgbm"] = models["lgbm"].predict(x)
    out["pred_momentum"] = out["momentum_12_1_rank"].fillna(0.5) - 0.5
    for name in BASE_NAMES:
        col = f"pred_{name}"
        out[f"rank_{name}"] = out.groupby("date")[col].transform(
            lambda s: s.rank(pct=True).clip(0.001, 0.999)
        )
    return out


def _daily_ic(frame: pd.DataFrame, col: str) -> pd.Series:
    x = frame.dropna(subset=[col, "future_relative_20d"])
    if x.empty:
        return pd.Series(dtype=float)
    return x.groupby("date").apply(
        lambda g: g[col].corr(g["future_relative_20d"], method="spearman"),
        include_groups=False,
    ).dropna()


def _model_weights(frame: pd.DataFrame) -> tuple[dict, dict]:
    quality = {}
    diagnostics = {}
    for name in BASE_NAMES:
        daily = _daily_ic(frame, f"rank_{name}")
        mean_ic = float(daily.mean()) if len(daily) else 0.0
        hit = float((daily > 0).mean()) if len(daily) else 0.0
        ic_ir = float(mean_ic / (daily.std() + 1e-12)) if len(daily) > 1 else 0.0
        # Positive IC is necessary; hit-rate gives a mild stability preference.
        q = max(mean_ic, 0.0) * max(hit, 0.35)
        quality[name] = q
        diagnostics[name] = {
            "mean_ic": round(mean_ic, 5),
            "ic_ir": round(ic_ir, 4),
            "positive_ic_ratio": round(hit, 4),
        }
    total = sum(quality.values())
    if total <= 1e-12:
        weights = {name: 1.0 / len(BASE_NAMES) for name in BASE_NAMES}
    else:
        weights = {name: float(quality[name] / total) for name in BASE_NAMES}
    return weights, diagnostics


def _router_weights(validation: pd.DataFrame) -> tuple[dict, dict]:
    global_w, global_diag = _model_weights(validation)
    router = {"GLOBAL": global_w}
    diagnostics = {"GLOBAL": global_diag}
    for regime in REGIMES:
        part = validation[validation["v5_regime"] == regime]
        if part["date"].nunique() >= 20:
            w, d = _model_weights(part)
            router[regime] = w
            diagnostics[regime] = d
        else:
            router[regime] = global_w
            diagnostics[regime] = {"fallback": "GLOBAL", "dates": int(part["date"].nunique())}
    return router, diagnostics


def _blend(frame: pd.DataFrame, router: dict) -> pd.DataFrame:
    out = frame.copy()
    out["v5_raw_score"] = 0.0
    for regime in REGIMES:
        mask = out["v5_regime"].eq(regime)
        if not mask.any():
            continue
        weights = router.get(regime, router["GLOBAL"])
        score = sum(out.loc[mask, f"rank_{name}"] * float(weights[name]) for name in BASE_NAMES)
        out.loc[mask, "v5_raw_score"] = score
    # One-sided EWMA uses only current and previous predictions for each symbol.
    out = out.sort_values(["symbol", "date"])
    out["v5_smooth_score"] = out.groupby("symbol")["v5_raw_score"].transform(
        lambda s: s.ewm(span=int(V5_CONFIG["ewma_span"]), adjust=False).mean()
    )
    return out.sort_values(["date", "symbol"])


def _meta_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = frame.copy()
    for regime in REGIMES:
        out[f"regime_{regime.lower()}"] = out["v5_regime"].eq(regime).astype(float)
    cols = (
        [f"rank_{n}" for n in BASE_NAMES]
        + ["v5_raw_score", "v5_smooth_score"]
        + MODEL_FEATURES
        + [f"regime_{r.lower()}" for r in REGIMES]
    )
    return out[cols].fillna(0.5), cols


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-5, 1 - 1e-5)
    return np.log(p / (1 - p)).reshape(-1, 1)


@dataclass
class MetaLayer:
    classifier: object
    calibrator: object | None
    columns: list[str]
    threshold: float
    diagnostics: dict

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        x, _ = _meta_matrix(frame)
        raw = self.classifier.predict_proba(x[self.columns])[:, 1]
        if self.calibrator is None:
            return raw
        return self.calibrator.predict_proba(_logit(raw))[:, 1]


def _fit_meta_layer(validation: pd.DataFrame) -> MetaLayer:
    dates = np.array(sorted(validation["date"].unique()))
    split = max(20, int(len(dates) * 0.70))
    fit_dates = dates[:split]
    cal_dates = dates[split:]
    fit = validation[validation["date"].isin(fit_dates)].copy()
    cal = validation[validation["date"].isin(cal_dates)].copy()
    if cal.empty:
        cal = fit.copy()

    x_fit, cols = _meta_matrix(fit)
    y_fit = (fit["future_relative_20d"] > 0).astype(int)
    clf = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.35, class_weight="balanced", max_iter=1000, random_state=42),
    )
    clf.fit(x_fit[cols], y_fit)

    x_cal, _ = _meta_matrix(cal)
    y_cal = (cal["future_relative_20d"] > 0).astype(int).to_numpy()
    raw_cal = clf.predict_proba(x_cal[cols])[:, 1]

    calibrator = None
    calibrated = raw_cal
    if len(np.unique(y_cal)) == 2 and len(y_cal) >= 100:
        calibrator = LogisticRegression(C=1.0, max_iter=500, random_state=42)
        calibrator.fit(_logit(raw_cal), y_cal)
        calibrated = calibrator.predict_proba(_logit(raw_cal))[:, 1]

    best_threshold = 0.55
    best_score = -np.inf
    threshold_rows = []
    target = cal["future_relative_20d"].to_numpy(dtype=float)
    for threshold in V5_CONFIG["meta_threshold_grid"]:
        accepted = calibrated >= threshold
        rate = float(accepted.mean()) if len(accepted) else 0.0
        mean_rel = float(np.nanmean(target[accepted])) if accepted.any() else np.nan
        n = int(accepted.sum())
        score = mean_rel * math.sqrt(max(n, 1)) if np.isfinite(mean_rel) and rate >= 0.15 else -np.inf
        threshold_rows.append({
            "threshold": threshold, "acceptance_rate": round(rate, 4),
            "mean_future_relative_20d": None if not np.isfinite(mean_rel) else round(mean_rel, 6),
            "accepted": n,
        })
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)

    return MetaLayer(
        classifier=clf,
        calibrator=calibrator,
        columns=cols,
        threshold=best_threshold,
        diagnostics={
            "fit_dates": int(len(fit_dates)),
            "calibration_dates": int(len(cal_dates)),
            "calibrated": calibrator is not None,
            "selected_threshold": best_threshold,
            "threshold_search": threshold_rows,
        },
    )


def _apply_meta(frame: pd.DataFrame, meta: MetaLayer) -> pd.DataFrame:
    out = frame.copy()
    prob = meta.predict(out)
    out["v5_meta_probability"] = prob
    threshold = float(meta.threshold)
    accepted = prob >= threshold
    denom = max(0.90 - threshold, 0.10)
    confidence = np.clip((prob - threshold) / denom, 0.0, 1.0)
    # Accepted positions keep a 25% floor; confidence controls both relative
    # position size and, because the backtest does not renormalize V5 sizes,
    # total gross exposure.
    out["v5_position_scale"] = np.where(accepted, 0.25 + 0.75 * confidence, 0.0)
    out["v5_trade_score"] = np.where(accepted, out["v5_smooth_score"], np.nan)
    return out


def build_meta_v5_oos(
    panel: pd.DataFrame | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> tuple[pd.DataFrame, dict]:
    source = build_feature_panel() if panel is None else panel.copy()
    source = _regime_frame(source)
    labelled = source.dropna(subset=MODEL_FEATURES + ["future_relative_20d"]).copy()
    dates = np.array(sorted(labelled["date"].unique()))

    min_train = int(V5_CONFIG["min_train_days"])
    test_days = int(V5_CONFIG["test_days"])
    validation_days = int(V5_CONFIG["validation_days"])
    embargo = int(V5_CONFIG["embargo_days"])
    if len(dates) < min_train + 40:
        min_train = max(320, int(len(dates) * 0.55))
        validation_days = max(63, int(len(dates) * 0.15))
        test_days = max(63, int(len(dates) * 0.15))

    folds = []
    predictions = []
    start = min_train
    fold_no = 0
    estimated_folds = max(1, math.ceil((len(dates) - start) / max(test_days, 1)))

    while start < len(dates):
        stop = min(start + test_days, len(dates))
        outer_train_stop = start - embargo
        val_start = outer_train_stop - validation_days
        base_train_stop = val_start - embargo
        if base_train_stop < 126 or val_start <= base_train_stop:
            break

        base_dates = dates[:base_train_stop]
        val_dates = dates[val_start:outer_train_stop]
        test_dates = dates[start:stop]
        if len(test_dates) < 20 or len(val_dates) < 40:
            break

        fold_no += 1
        if progress:
            pct = 10 + int(65 * (fold_no - 1) / estimated_folds)
            progress(pct, f"META V5 fold {fold_no}: base models + meta-labeler")

        base_train = labelled[labelled["date"].isin(base_dates)]
        validation = labelled[labelled["date"].isin(val_dates)]
        outer_train = labelled[labelled["date"].isin(dates[:outer_train_stop])]
        test = labelled[labelled["date"].isin(test_dates)]

        # Nested OOS predictions for ensemble weighting + meta-labeler training.
        val_models = _fit_base(base_train)
        val_pred = _predict_base(val_models, validation)
        router, router_diag = _router_weights(val_pred)
        val_pred = _blend(val_pred, router)
        meta = _fit_meta_layer(val_pred)

        # Refit base learners on every label safely available before outer test.
        test_models = _fit_base(outer_train)
        test_pred = _predict_base(test_models, test)
        test_pred = _blend(test_pred, router)
        test_pred = _apply_meta(test_pred, meta)

        daily = _daily_ic(test_pred, "v5_smooth_score")
        accepted = test_pred["v5_trade_score"].notna()
        fold_summary = {
            "fold": fold_no,
            "base_train_from": str(pd.Timestamp(base_dates[0]).date()),
            "base_train_to": str(pd.Timestamp(base_dates[-1]).date()),
            "validation_from": str(pd.Timestamp(val_dates[0]).date()),
            "validation_to": str(pd.Timestamp(val_dates[-1]).date()),
            "test_from": str(pd.Timestamp(test_dates[0]).date()),
            "test_to": str(pd.Timestamp(test_dates[-1]).date()),
            "embargo_days": embargo,
            "rank_ic": round(float(daily.mean()), 5) if len(daily) else None,
            "positive_ic_ratio": round(float((daily > 0).mean()), 4) if len(daily) else None,
            "acceptance_rate": round(float(accepted.mean()), 4),
            "meta": meta.diagnostics,
            "router_weights": router,
            "router_diagnostics": router_diag,
            "lgbm": test_models["lgbm"].diagnostics(),
        }
        folds.append(fold_summary)
        predictions.append(test_pred[[
            "date", "symbol", "v5_regime", "v5_raw_score", "v5_smooth_score",
            "v5_meta_probability", "v5_position_scale", "v5_trade_score",
        ]])
        start = stop

    if not predictions:
        raise ValueError("Not enough history for META V5 nested walk-forward")

    oos = pd.concat(predictions, ignore_index=True)
    scored = source.merge(oos, on=["date", "symbol"], how="left", suffixes=("", "_oos"))
    daily = _daily_ic(scored, "v5_smooth_score")
    accepted = scored["v5_trade_score"].notna()
    summary = {
        "name": "META Ensemble v5",
        "dataset": panel_metadata(source),
        "architecture": {
            "base_models": ["Ridge", "HistGradientBoosting", "DoubleEnsemble-style LightGBM x3", "Momentum"],
            "ensemble": "validation RankIC weighted + regime router",
            "smoothing": f"one-sided EWMA span={V5_CONFIG['ewma_span']}",
            "meta_labeler": "logistic trade/skip + held-out Platt calibration",
            "position_sizing": "calibrated probability, 25%-100% scale, no forced full exposure",
            "historical_news": "excluded",
        },
        "oos_mean_rank_ic": round(float(daily.mean()), 5) if len(daily) else None,
        "oos_ic_ir": round(float(daily.mean() / (daily.std() + 1e-12)), 4) if len(daily) > 1 else None,
        "positive_oos_ic_ratio": round(float((daily > 0).mean()), 4) if len(daily) else None,
        "overall_acceptance_rate": round(float(accepted.mean()), 4),
        "folds": folds,
    }
    return scored, summary


def run_meta_v5(
    panel: pd.DataFrame | None = None,
    params: dict | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> dict:
    from app.services.backtest import run_backtest

    scored, research = build_meta_v5_oos(panel=panel, progress=progress)
    p = V5_PORTFOLIO | (params or {})
    if progress:
        progress(80, "META V5: backtest OOS, EWMA, sizing et coûts")
    result = run_backtest(
        p,
        score_column="v5_trade_score",
        strategy_name="META Ensemble v5 OOS",
        panel=scored,
        position_scale_column="v5_position_scale",
    )
    result["meta_v5"] = research
    result["research_status"] = "STRICT_OOS_NESTED_WALK_FORWARD"
    result["audit_note"] += (
        " META V5 uses nested walk-forward base models, a validation-only regime router, "
        "one-sided EWMA smoothing, an OOS-trained/calibrated trade filter and probability sizing."
    )
    return result


def meta_v5_robustness(panel: pd.DataFrame | None = None, progress=None) -> dict:
    from app.services.backtest import run_backtest

    scored, research = build_meta_v5_oos(panel=panel, progress=progress)
    scenarios = [
        ("base", {}),
        ("long_10", {"long_count": 10, "min_long_count": 4}),
        ("long_20", {"long_count": 20, "min_long_count": 6}),
        ("rebalance_5", {"rebalance_days": 5}),
        ("rebalance_20", {"rebalance_days": 20}),
        ("cost_x2", {"commission_bps": 12.0, "slippage_bps": 10.0}),
        ("cost_x3", {"commission_bps": 18.0, "slippage_bps": 15.0}),
    ]
    rows = []
    for i, (name, override) in enumerate(scenarios):
        if progress:
            progress(78 + int(17 * i / len(scenarios)), f"META V5 robustness: {name}")
        result = run_backtest(
            V5_PORTFOLIO | override,
            score_column="v5_trade_score",
            strategy_name=f"META V5 {name}",
            panel=scored,
            position_scale_column="v5_position_scale",
        )
        rows.append({"scenario": name, **result["metrics"]})

    sharpes = np.array([r["sharpe"] for r in rows], dtype=float)
    summary = {
        "positive_sharpe_ratio": round(float((sharpes > 0).mean()), 4),
        "median_sharpe": round(float(np.median(sharpes)), 3),
        "min_sharpe": round(float(np.min(sharpes)), 3),
        "cost_stress_pass": all(r["sharpe"] > 0 for r in rows if r["scenario"] in ("cost_x2", "cost_x3")),
        "turnover_base": next((r["avg_turnover_per_rebalance"] for r in rows if r["scenario"] == "base"), None),
    }
    return {"research": research, "summary": summary, "scenarios": rows}


def meta_v5_validation_bundle(panel: pd.DataFrame | None = None, progress=None) -> dict:
    """Build OOS predictions once, then stress only portfolio/cost assumptions."""
    from app.services.backtest import run_backtest

    scored, research = build_meta_v5_oos(panel=panel, progress=progress)
    base = run_backtest(
        V5_PORTFOLIO,
        score_column="v5_trade_score",
        strategy_name="META Ensemble v5 OOS",
        panel=scored,
        position_scale_column="v5_position_scale",
    )
    base["meta_v5"] = research
    base["research_status"] = "STRICT_OOS_NESTED_WALK_FORWARD"

    scenarios = [
        ("base", {}),
        ("long_10", {"long_count": 10, "min_long_count": 4}),
        ("long_20", {"long_count": 20, "min_long_count": 6}),
        ("rebalance_5", {"rebalance_days": 5}),
        ("rebalance_20", {"rebalance_days": 20}),
        ("cost_x2", {"commission_bps": 12.0, "slippage_bps": 10.0}),
        ("cost_x3", {"commission_bps": 18.0, "slippage_bps": 15.0}),
    ]
    rows = []
    for i, (name, override) in enumerate(scenarios):
        if progress:
            progress(78 + int(17 * i / len(scenarios)), f"META V5 validation stress: {name}")
        result = run_backtest(
            V5_PORTFOLIO | override,
            score_column="v5_trade_score",
            strategy_name=f"META V5 {name}",
            panel=scored,
            position_scale_column="v5_position_scale",
        )
        rows.append({"scenario": name, **result["metrics"]})

    sharpes = np.array([r["sharpe"] for r in rows], dtype=float)
    robust = {
        "positive_sharpe_ratio": round(float((sharpes > 0).mean()), 4),
        "median_sharpe": round(float(np.median(sharpes)), 3),
        "min_sharpe": round(float(np.min(sharpes)), 3),
        "cost_stress_pass": all(r["sharpe"] > 0 for r in rows if r["scenario"] in ("cost_x2", "cost_x3")),
        "turnover_base": next((r["avg_turnover_per_rebalance"] for r in rows if r["scenario"] == "base"), None),
    }
    return {"backtest": base, "research": research, "robustness": robust, "scenarios": rows}
