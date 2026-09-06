from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.core.config import settings
from app.services.features import build_feature_panel, panel_metadata
from app.services.research_cache import load as load_research_cache, make_key as make_research_cache_key, save as save_research_cache
from app.services.meta_v5 import BASE_NAMES, MODEL_FEATURES, REGIMES, DoubleEnsembleLGBM

# V6 does not replace V5. It is an experimental candidate whose labels match the
# actual 10-session holding period and next-open execution used by the portfolio.
V6_PORTFOLIO = {
    "long_count": 15,
    "short_count": 0,
    "rebalance_days": 10,
    "warmup_days": 0,
    "commission_bps": 6.0,
    "slippage_bps": 5.0,
    "gross_exposure": 1.0,
    "long_gross": 1.0,
    "short_gross": 0.0,
    "initial_capital": 100000.0,
    "rank_buffer": 5,
    "rebalance_threshold_pct": 0.20,
    "min_trade_notional": 250.0,
    "min_long_count": 3,
    "normalize_position_scale": False,
}

V6_CACHE_VERSION = "v6-aligned-solid-v4-2"

V6_CONFIG = {
    "holding_days": 10,
    # A target for signal T uses open(T+1) -> open(T+11), so keep 12 sessions
    # between the most recent training label and the score date.
    "embargo_days": 12,
    "min_train_days": 126,
    "validation_days": 126,
    "model_refresh_days": 20,
    "ewma_span": 5,
    "lgbm_members": 3,
    "lgbm_member_timeout_seconds": 45,
    "lgbm_threads": 4,
    "meta_threshold_grid": [0.50, 0.55, 0.60, 0.65, 0.70, 0.75],
    "long_count_grid": [8, 10, 12, 15],
    # 6 bps commission + 5 bps slippage on entry and exit.
    "round_trip_cost_bps": 22.0,
    "min_cross_section_names": 20,
}


def _add_execution_aligned_targets(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy().sort_values(["symbol", "date"])
    hold = int(V6_CONFIG["holding_days"])
    g = out.groupby("symbol", group_keys=False)
    entry_open = g["open"].shift(-1)
    exit_open = g["open"].shift(-(hold + 1))
    out["v6_future_open_return"] = exit_open / entry_open - 1.0
    out["v6_future_relative_return"] = (
        out["v6_future_open_return"]
        - out.groupby("date")["v6_future_open_return"].transform("mean")
    )
    return out.sort_values(["date", "symbol"])


def _context_frame(panel: pd.DataFrame) -> pd.DataFrame:
    daily = panel.groupby("date", as_index=False).agg(
        market_ret_20=("ret_20d", "mean"),
        market_vol_20=("vol_20d", "median"),
        market_dispersion_20=("ret_20d", "std"),
        market_breadth_20=("ret_20d", lambda s: float((s > 0).mean())),
        market_trend_breadth=("trend_200", lambda s: float((s > 0).mean())),
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

    daily["v6_regime"] = daily.apply(classify, axis=1)
    cols = [
        "date", "v6_regime", "market_ret_20", "market_vol_20",
        "market_dispersion_20", "market_breadth_20", "market_trend_breadth",
    ]
    return panel.merge(daily[cols], on="date", how="left")


def _new_base_models():
    return {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "hgb": HistGradientBoostingRegressor(
            max_iter=140,
            max_depth=4,
            learning_rate=0.05,
            l2_regularization=1.5,
            min_samples_leaf=50,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.10,
            n_iter_no_change=12,
        ),
        "lgbm": DoubleEnsembleLGBM(
            members=int(V6_CONFIG["lgbm_members"]),
            member_timeout_seconds=int(V6_CONFIG["lgbm_member_timeout_seconds"]),
            threads=int(V6_CONFIG["lgbm_threads"]),
        ),
    }


def _fit_base(train: pd.DataFrame):
    x = train[MODEL_FEATURES].fillna(0.5)
    y = train["v6_future_relative_return"].astype(float)
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
        out[f"rank_{name}"] = out.groupby("date")[f"pred_{name}"].transform(
            lambda s: s.rank(pct=True).clip(0.001, 0.999)
        )
    return out


def _daily_ic(frame: pd.DataFrame, col: str) -> pd.Series:
    x = frame.dropna(subset=[col, "v6_future_relative_return"])
    if x.empty:
        return pd.Series(dtype=float)
    return x.groupby("date").apply(
        lambda g: g[col].corr(g["v6_future_relative_return"], method="spearman"),
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
        part = validation[validation["v6_regime"] == regime]
        if part["date"].nunique() >= 20:
            w, diag = _model_weights(part)
            router[regime] = w
            diagnostics[regime] = diag
        else:
            router[regime] = global_w
            diagnostics[regime] = {"fallback": "GLOBAL", "dates": int(part["date"].nunique())}
    return router, diagnostics


def _blend_raw(frame: pd.DataFrame, router: dict) -> pd.DataFrame:
    out = frame.copy()
    out["v6_raw_score"] = 0.0
    for regime in REGIMES:
        mask = out["v6_regime"].eq(regime)
        if not mask.any():
            continue
        weights = router.get(regime, router["GLOBAL"])
        out.loc[mask, "v6_raw_score"] = sum(
            out.loc[mask, f"rank_{name}"] * float(weights[name]) for name in BASE_NAMES
        )
    return out


def _smooth_validation(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values(["symbol", "date"]).copy()
    out["v6_smooth_score"] = out.groupby("symbol")["v6_raw_score"].transform(
        lambda s: s.ewm(span=int(V6_CONFIG["ewma_span"]), adjust=False).mean()
    )
    return out.sort_values(["date", "symbol"])


CONTEXT_FEATURES = [
    "market_ret_20",
    "market_vol_20",
    "market_dispersion_20",
    "market_breadth_20",
    "market_trend_breadth",
]


def _meta_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = frame.copy()
    for regime in REGIMES:
        out[f"regime_{regime.lower()}"] = out["v6_regime"].eq(regime).astype(float)
    cols = (
        [f"rank_{name}" for name in BASE_NAMES]
        + ["v6_raw_score", "v6_smooth_score"]
        + MODEL_FEATURES
        + CONTEXT_FEATURES
        + [f"regime_{regime.lower()}" for regime in REGIMES]
    )
    return out[cols].replace([np.inf, -np.inf], np.nan).fillna(0.5), cols


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-5, 1 - 1e-5)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _size_from_probability(prob, threshold):
    prob = np.asarray(prob, dtype=float)
    accepted = prob >= threshold
    denom = max(0.90 - float(threshold), 0.10)
    confidence = np.clip((prob - threshold) / denom, 0.0, 1.0)
    # V5 gave every accepted name a 25% floor. V6 deliberately makes marginal
    # signals smaller; strong calibrated signals can still reach full size.
    return np.where(accepted, 0.10 + 0.90 * np.power(confidence, 1.25), 0.0)


class _ConstantProbabilityClassifier:
    def __init__(self, probability: float):
        self.probability=float(np.clip(probability,1e-4,1-1e-4))
    def predict_proba(self, x):
        p=np.full(len(x),self.probability,dtype=float)
        return np.column_stack([1.0-p,p])


@dataclass
class MetaLayerV6:
    classifier: object
    calibrator: object | None
    columns: list[str]
    threshold: float
    selected_long_count: int
    diagnostics: dict

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        x, _ = _meta_matrix(frame)
        raw = self.classifier.predict_proba(x[self.columns])[:, 1]
        if self.calibrator is None:
            return raw
        return self.calibrator.predict_proba(_logit(raw))[:, 1]


def _portfolio_threshold_search(cal: pd.DataFrame, probabilities: np.ndarray):
    work = cal.copy()
    work["_prob"] = probabilities
    dates = np.array(sorted(work["date"].unique()))
    # Non-overlapping validation observations approximate the real 10-session
    # portfolio holding period and avoid rewarding overlapping labels.
    eval_dates = dates[:: int(V6_CONFIG["holding_days"])]
    cost = float(V6_CONFIG["round_trip_cost_bps"]) / 10000.0
    rows = []
    best = None

    for threshold in V6_CONFIG["meta_threshold_grid"]:
        for long_count in V6_CONFIG["long_count_grid"]:
            period_returns = []
            accepted_names = 0
            candidate_names = 0
            for d in eval_dates:
                day = work[work["date"] == d].sort_values("v6_smooth_score", ascending=False)
                candidate_names += len(day)
                accepted = day[day["_prob"] >= threshold].head(int(long_count)).copy()
                if len(accepted) < 3:
                    continue
                scales = _size_from_probability(accepted["_prob"].to_numpy(), float(threshold))
                net_asset = accepted["v6_future_open_return"].to_numpy(dtype=float) - cost
                period_returns.append(float(np.mean(scales * net_asset)))
                accepted_names += len(accepted)

            arr = np.asarray(period_returns, dtype=float)
            if len(arr) < 4 or not np.isfinite(arr).all():
                score = -np.inf
                mean_ret = np.nan
                vol = np.nan
                worst = np.nan
            else:
                mean_ret = float(arr.mean())
                vol = float(arr.std(ddof=1))
                worst = float(arr.min())
                # Optimize risk-adjusted period return; a mild downside term
                # discourages settings that win only through a few huge bets.
                score = mean_ret / (vol + 1e-12) - 0.15 * abs(min(worst, 0.0))

            acceptance_rate = (
                float(accepted_names / candidate_names) if candidate_names else 0.0
            )
            row = {
                "threshold": float(threshold),
                "long_count": int(long_count),
                "periods": int(len(arr)),
                "acceptance_rate": round(acceptance_rate, 4),
                "mean_net_period_return": None if not np.isfinite(mean_ret) else round(mean_ret, 6),
                "period_volatility": None if not np.isfinite(vol) else round(vol, 6),
                "worst_period_return": None if not np.isfinite(worst) else round(worst, 6),
                "objective": None if not np.isfinite(score) else round(float(score), 6),
            }
            rows.append(row)

            if np.isfinite(score) and (best is None or score > best[0]):
                best = (score, float(threshold), int(long_count))

    if best is None:
        thresholds=list(V6_CONFIG["meta_threshold_grid"])
        counts=list(V6_CONFIG["long_count_grid"])
        return float(thresholds[len(thresholds)//2]), int(counts[len(counts)//2]), rows
    return best[1], best[2], rows


def _fit_meta_layer(validation: pd.DataFrame) -> MetaLayerV6:
    dates = np.array(sorted(validation["date"].unique()))
    split = max(30, int(len(dates) * 0.55))
    inner_embargo = int(V6_CONFIG["embargo_days"])
    cal_start = min(len(dates), split + inner_embargo)
    fit_dates = dates[:split]
    cal_dates = dates[cal_start:]
    if len(cal_dates) < 10:
        cal_start = split
        cal_dates = dates[cal_start:]

    fit = validation[validation["date"].isin(fit_dates)].copy()
    cal = validation[validation["date"].isin(cal_dates)].copy()
    if cal.empty:
        cal = fit.copy()

    x_fit, cols = _meta_matrix(fit)
    cost = float(V6_CONFIG["round_trip_cost_bps"]) / 10000.0
    # Crucial V6 difference: the filter asks "would this long make money after
    # expected round-trip costs?", not merely "would it beat the cross-section?".
    y_fit = (fit["v6_future_open_return"] > cost).astype(int)
    if y_fit.nunique()<2:
        clf=_ConstantProbabilityClassifier(float(y_fit.mean()))
    else:
        clf = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.30, class_weight="balanced", max_iter=1000, random_state=42),
        )
        clf.fit(x_fit[cols], y_fit)

    x_cal, _ = _meta_matrix(cal)
    y_cal = (cal["v6_future_open_return"] > cost).astype(int).to_numpy()
    raw_cal = clf.predict_proba(x_cal[cols])[:, 1]

    calibrator = None
    calibrated = raw_cal
    if len(np.unique(y_cal)) == 2 and len(y_cal) >= 100:
        calibrator = LogisticRegression(C=1.0, max_iter=500, random_state=42)
        calibrator.fit(_logit(raw_cal), y_cal)
        calibrated = calibrator.predict_proba(_logit(raw_cal))[:, 1]

    threshold, long_count, search = _portfolio_threshold_search(cal, calibrated)

    return MetaLayerV6(
        classifier=clf,
        calibrator=calibrator,
        columns=cols,
        threshold=threshold,
        selected_long_count=long_count,
        diagnostics={
            "fit_dates": int(len(fit_dates)),
            "calibration_dates": int(len(cal_dates)),
            "calibration_embargo_days": int(max(0, cal_start - split)),
            "calibrated": calibrator is not None,
            "selected_threshold": threshold,
            "selected_long_count": long_count,
            "threshold_portfolio_search": search,
            "label": f"next_open_to_plus_{V6_CONFIG['holding_days']}_open_net_positive",
            "round_trip_cost_bps": float(V6_CONFIG["round_trip_cost_bps"]),
        },
    )


def _apply_meta(frame: pd.DataFrame, meta: MetaLayerV6) -> pd.DataFrame:
    out = frame.copy()
    prob = meta.predict(out)
    out["v6_meta_probability"] = prob
    out["v6_threshold"] = float(meta.threshold)
    out["v6_position_scale"] = _size_from_probability(prob, meta.threshold)

    accepted = out["v6_meta_probability"] >= float(meta.threshold)
    accepted_rank = (
        out["v6_smooth_score"].where(accepted)
        .groupby(out["date"])
        .rank(method="first", ascending=False)
    )
    accepted &= accepted_rank <= int(meta.selected_long_count)
    out["v6_selected_rank"] = accepted_rank
    out["v6_position_scale"] = np.where(accepted, out["v6_position_scale"], 0.0)
    out["v6_trade_score"] = np.where(accepted, out["v6_smooth_score"], np.nan)
    return out


def build_meta_v6_oos(
    panel: pd.DataFrame | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> tuple[pd.DataFrame, dict]:
    source = build_feature_panel() if panel is None else panel.copy()
    source = _add_execution_aligned_targets(source)
    source = _context_frame(source).sort_values(["date", "symbol"])
    dataset_meta=panel_metadata(source)
    cache_key=make_research_cache_key(
        "meta_v6_oos",
        dataset_meta["fingerprint"],
        V6_CACHE_VERSION,
        V6_CONFIG,
        {"model_features":MODEL_FEATURES},
    )
    if settings.data_mode.lower()=="alpaca":
        cached=load_research_cache("meta_v6_oos",cache_key)
        if cached is not None:
            cached_scored,cached_research,cached_meta=cached
            cached_research=dict(cached_research)
            cached_research["cache"]={
                "hit":True,
                "version":V6_CACHE_VERSION,
                "key":cache_key,
                "stored_at":cached_meta.get("stored_at"),
            }
            if progress:
                progress(74,"META V6 — cache OOS réutilisé; aucun réentraînement historique")
            return cached_scored,cached_research

    eligible_mask=source["solid_eligible"].fillna(False).astype(bool) if "solid_eligible" in source.columns else pd.Series(True,index=source.index)
    eligible_source=source[eligible_mask].copy()
    min_cross_section=(
        int(V6_CONFIG["min_cross_section_names"])
        if settings.data_mode.lower()=="alpaca"
        else 1
    )
    eligible_counts=eligible_source.groupby("date")["symbol"].nunique()
    valid_cross_section_dates=set(
        eligible_counts[eligible_counts>=min_cross_section].index
    )
    labelled = eligible_source[eligible_source["date"].isin(valid_cross_section_dates)].dropna(
        subset=MODEL_FEATURES + ["v6_future_relative_return", "v6_future_open_return"]
    ).copy()
    all_dates = np.array(sorted(source["date"].unique()))

    min_train = int(V6_CONFIG["min_train_days"])
    validation_days = int(V6_CONFIG["validation_days"])
    embargo = int(V6_CONFIG["embargo_days"])
    refresh_days = max(1, int(V6_CONFIG["model_refresh_days"]))
    first_score_idx = min_train + validation_days + 2 * embargo

    if len(all_dates) <= first_score_idx + int(V6_CONFIG["holding_days"]) + 1:
        raise ValueError(
            f"Not enough history for META V6: need > {first_score_idx + V6_CONFIG['holding_days'] + 1} sessions, got {len(all_dates)}"
        )

    by_date = {d: frame.copy() for d, frame in source.groupby("date")}
    predictions = []
    refreshes = []
    ewma_state: dict[str, float] = {}
    alpha = 2.0 / (float(V6_CONFIG["ewma_span"]) + 1.0)

    live_models = None
    router = None
    meta = None
    refresh_id = 0
    refresh_total = max(1, math.ceil((len(all_dates) - first_score_idx) / refresh_days))

    for date_i in range(first_score_idx, len(all_dates)):
        signal_date = all_dates[date_i]
        must_refresh = live_models is None or (date_i - first_score_idx) % refresh_days == 0

        if must_refresh:
            safe_stop = date_i - embargo
            val_start = safe_stop - validation_days
            base_stop = val_start - embargo
            if base_stop < min_train:
                continue

            base_dates = all_dates[:base_stop]
            val_dates = all_dates[val_start:safe_stop]
            safe_train_dates = all_dates[:safe_stop]

            base_train = labelled[labelled["date"].isin(base_dates)]
            validation = labelled[labelled["date"].isin(val_dates)]
            safe_train = labelled[labelled["date"].isin(safe_train_dates)]
            if (
                base_train["date"].nunique() < min_train
                or validation["date"].nunique() < max(20, validation_days // 2)
                or safe_train.empty
            ):
                continue

            refresh_id += 1
            if progress:
                pct = 10 + int(65 * (refresh_id - 1) / refresh_total)
                progress(
                    min(74, pct),
                    f"META V6 {pd.Timestamp(signal_date).date()} — aligned-target refresh {refresh_id}/{refresh_total}",
                )

            validation_models = _fit_base(base_train)
            val_pred = _predict_base(validation_models, validation)
            router, router_diag = _router_weights(val_pred)
            val_pred = _smooth_validation(_blend_raw(val_pred, router))
            meta = _fit_meta_layer(val_pred)

            live_models = _fit_base(safe_train)

            if refreshes:
                refreshes[-1]["test_to"] = str(pd.Timestamp(all_dates[date_i - 1]).date())
            refreshes.append({
                "refresh": refresh_id,
                "base_train_from": str(pd.Timestamp(base_dates[0]).date()),
                "base_train_to": str(pd.Timestamp(base_dates[-1]).date()),
                "validation_from": str(pd.Timestamp(val_dates[0]).date()),
                "validation_to": str(pd.Timestamp(val_dates[-1]).date()),
                "safe_train_to": str(pd.Timestamp(safe_train_dates[-1]).date()),
                "test_from": str(pd.Timestamp(signal_date).date()),
                "test_to": None,
                "embargo_days": embargo,
                "meta": meta.diagnostics,
                "router_weights": router,
                "router_diagnostics": router_diag,
                "lgbm": live_models["lgbm"].diagnostics(),
            })

        if live_models is None or router is None or meta is None:
            continue

        current = by_date[signal_date].dropna(subset=MODEL_FEATURES).copy()
        if "solid_eligible" in current.columns:
            current=current[current["solid_eligible"].fillna(False).astype(bool)].copy()
        if len(current)<min_cross_section:
            continue

        current_pred = _blend_raw(_predict_base(live_models, current), router)
        smooth_values = []
        for row in current_pred.itertuples():
            raw = float(row.v6_raw_score)
            previous = ewma_state.get(row.symbol)
            smooth = raw if previous is None else alpha * raw + (1.0 - alpha) * previous
            ewma_state[row.symbol] = smooth
            smooth_values.append(smooth)
        current_pred["v6_smooth_score"] = smooth_values
        current_pred = _apply_meta(current_pred, meta)
        current_pred["v6_refresh_id"] = refresh_id

        predictions.append(current_pred[[
            "date", "symbol", "v6_regime",
            "market_ret_20", "market_vol_20", "market_dispersion_20",
            "market_breadth_20", "market_trend_breadth",
            "v6_raw_score", "v6_smooth_score", "v6_meta_probability",
            "v6_position_scale", "v6_trade_score", "v6_selected_rank", "v6_refresh_id",
        ]])

    if not predictions:
        raise ValueError("META V6 produced no historical live-like predictions")

    refreshes[-1]["test_to"] = str(pd.Timestamp(all_dates[-1]).date())
    oos = pd.concat(predictions, ignore_index=True)
    scored = source.merge(oos, on=["date", "symbol"], how="left", suffixes=("", "_oos"))

    for refresh in refreshes:
        part = scored[scored["v6_refresh_id"] == refresh["refresh"]]
        daily_part = _daily_ic(part, "v6_smooth_score")
        selected = part["v6_trade_score"].notna()
        refresh["rank_ic"] = round(float(daily_part.mean()), 5) if len(daily_part) else None
        refresh["positive_ic_ratio"] = round(float((daily_part > 0).mean()), 4) if len(daily_part) else None
        refresh["acceptance_rate"] = round(float(selected.mean()), 4) if len(part) else None

    daily = _daily_ic(scored, "v6_smooth_score")
    selected = oos["v6_trade_score"].notna()
    scored_dates = np.array(sorted(oos["date"].unique()))
    expected_post_startup_dates=all_dates[first_score_idx:] if first_score_idx<len(all_dates) else np.array([])
    post_startup_coverage=(
        float(len(scored_dates)/len(expected_post_startup_dates))
        if len(expected_post_startup_dates)
        else 0.0
    )

    summary = {
        "name": "META Ensemble v6 Risk-Aware",
        "dataset": panel_metadata(source),
        "target": {
            "alpha": f"cross-sectional next-open to +{V6_CONFIG['holding_days']}-session open relative return",
            "meta_label": "absolute execution-aligned return > estimated round-trip cost",
            "round_trip_cost_bps": float(V6_CONFIG["round_trip_cost_bps"]),
        },
        "simulation": {
            "method": "CONTINUOUS_EXPANDING_WALK_FORWARD_EXECUTION_ALIGNED",
            "fixed_holdout": False,
            "feature_valid_from": str(pd.Timestamp(all_dates[0]).date()),
            "first_live_like_score": str(pd.Timestamp(scored_dates[0]).date()),
            "last_live_like_score": str(pd.Timestamp(scored_dates[-1]).date()),
            "feature_valid_sessions": int(len(all_dates)),
            "live_like_sessions": int(len(scored_dates)),
            "coverage_ratio": round(float(len(scored_dates) / len(all_dates)), 4),
            "coverage_ratio_including_startup": round(float(len(scored_dates) / len(all_dates)), 4),
            "post_startup_coverage_ratio": round(post_startup_coverage, 4),
            "expected_post_startup_sessions": int(len(expected_post_startup_dates)),
            "initial_startup_sessions": int(first_score_idx),
            "min_train_days": min_train,
            "validation_days": validation_days,
            "target_embargo_days": embargo,
            "model_refresh_days": refresh_days,
            "rebalance_days": int(V6_PORTFOLIO["rebalance_days"]),
        },
        "architecture": {
            "base_models": ["Ridge", "HistGradientBoosting", "DoubleEnsemble-style LightGBM x3", "Momentum"],
            "ensemble": "past validation RankIC weighted + regime router",
            "market_context": CONTEXT_FEATURES + list(REGIMES),
            "smoothing": f"stateful one-sided EWMA span={V6_CONFIG['ewma_span']}",
            "meta_labeler": "absolute net-positive trade filter + Platt calibration",
            "portfolio_search": "validation-only threshold + max position count",
            "position_sizing": "calibrated probability, 10%-100% scale, no forced full exposure",
            "min_cross_section_names": int(V6_CONFIG["min_cross_section_names"]),
            "historical_news": "excluded",
        },
        "oos_mean_rank_ic": round(float(daily.mean()), 5) if len(daily) else None,
        "oos_ic_ir": round(float(daily.mean() / (daily.std() + 1e-12)), 4) if len(daily) > 1 else None,
        "positive_oos_ic_ratio": round(float((daily > 0).mean()), 4) if len(daily) else None,
        "overall_acceptance_rate": round(float(selected.mean()), 4),
        "refreshes": refreshes,
        "folds": refreshes,
        "cache":{"hit":False,"version":V6_CACHE_VERSION,"key":cache_key},
    }
    if settings.data_mode.lower()=="alpaca":
        save_research_cache("meta_v6_oos",cache_key,scored,summary,dataset_meta["fingerprint"])
    return scored, summary


def run_meta_v6(
    panel: pd.DataFrame | None = None,
    params: dict | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> dict:
    from app.services.backtest import run_backtest

    scored, research = build_meta_v6_oos(panel=panel, progress=progress)
    portfolio = V6_PORTFOLIO | (params or {})
    if progress:
        progress(80, "META V6 — execution-aligned portfolio backtest")
    result = run_backtest(
        portfolio,
        score_column="v6_trade_score",
        strategy_name="META Ensemble v6 Risk-Aware",
        panel=scored,
        position_scale_column="v6_position_scale",
    )
    result["meta_v6"] = research
    result["research_status"] = "EXPERIMENTAL_CONTINUOUS_OOS_EXECUTION_ALIGNED"
    result["audit_note"] += (
        " META V6 is an experimental challenger to V5. Alpha labels match the 10-session "
        "next-open holding period; the meta-label predicts absolute profitability after "
        "round-trip costs; threshold and position count are selected only on past validation data."
    )
    return result


def meta_v6_validation_bundle(panel: pd.DataFrame | None = None, progress=None) -> dict:
    from app.services.backtest import run_backtest

    scored, research = build_meta_v6_oos(panel=panel, progress=progress)
    base = run_backtest(
        V6_PORTFOLIO,
        score_column="v6_trade_score",
        strategy_name="META Ensemble v6 Risk-Aware",
        panel=scored,
        position_scale_column="v6_position_scale",
    )
    base["meta_v6"] = research
    base["research_status"] = "EXPERIMENTAL_CONTINUOUS_OOS_EXECUTION_ALIGNED"

    scenarios = [
        ("base", {}),
        ("long_cap_10", {"long_count": 10}),
        ("rank_buffer_0", {"rank_buffer": 0}),
        ("resize_band_0", {"rebalance_threshold_pct": 0.0}),
        ("cost_x2", {"commission_bps": 12.0, "slippage_bps": 10.0}),
        ("cost_x3", {"commission_bps": 18.0, "slippage_bps": 15.0}),
    ]
    rows = []
    for i, (name, override) in enumerate(scenarios):
        if progress:
            progress(80 + int(15 * i / len(scenarios)), f"META V6 robustness: {name}")
        result = run_backtest(
            V6_PORTFOLIO | override,
            score_column="v6_trade_score",
            strategy_name=f"META V6 {name}",
            panel=scored,
            position_scale_column="v6_position_scale",
        )
        rows.append({"scenario": name, **result["metrics"]})

    sharpes = np.array([row["sharpe"] for row in rows], dtype=float)
    robustness = {
        "positive_sharpe_ratio": round(float((sharpes > 0).mean()), 4),
        "median_sharpe": round(float(np.median(sharpes)), 3),
        "min_sharpe": round(float(np.min(sharpes)), 3),
        "cost_stress_pass": all(
            row["sharpe"] > 0 for row in rows if row["scenario"] in ("cost_x2", "cost_x3")
        ),
        "turnover_base": next(
            (row["avg_turnover_per_rebalance"] for row in rows if row["scenario"] == "base"),
            None,
        ),
    }
    return {
        "backtest": base,
        "research": research,
        "robustness": robustness,
        "scenarios": rows,
    }
