from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from app.services.features import build_feature_panel, panel_metadata
from app.services.meta_v6 import build_meta_v6_oos
from app.services.meta_v7 import V7_CONFIG, V7_PORTFOLIO, apply_v7_risk_overlay

V71_CONFIG={
    "confidence_ceiling":0.75,
    "max_target_gross":0.95,
    "regime_floors":{
        "TREND_UP":0.55,
        "NEUTRAL":0.45,
        "HIGH_VOL":0.30,
        "RISK_OFF":0.25,
    },
    "market_weight":0.50,
    "confidence_weight":0.50,
}

V71_PORTFOLIO={
    **V7_PORTFOLIO,
    "long_count":12,
    "max_abs_weight":0.10,
    "normalize_position_scale":False,
}


def _target_gross(day:pd.DataFrame,floor_shift:float=0.0)->tuple[float,dict]:
    regime_values=day["v6_regime"].dropna() if "v6_regime" in day else pd.Series(dtype=object)
    regime=str(regime_values.mode().iloc[0]) if len(regime_values) else "NEUTRAL"
    base_floor=float(V71_CONFIG["regime_floors"].get(regime,V71_CONFIG["regime_floors"]["NEUTRAL"]))
    floor=float(np.clip(base_floor+floor_shift,0.10,0.80))

    threshold_values=pd.to_numeric(day.get("v7_threshold"),errors="coerce").dropna()
    threshold=float(threshold_values.median()) if len(threshold_values) else 0.60
    probabilities=pd.to_numeric(day.get("v6_meta_probability"),errors="coerce").dropna()
    avg_prob=float(probabilities.mean()) if len(probabilities) else threshold

    ceiling=max(float(V71_CONFIG["confidence_ceiling"]),threshold+.10)
    confidence=float(np.clip((avg_prob-threshold)/(ceiling-threshold),0.0,1.0))

    market_values=pd.to_numeric(day.get("v7_market_risk_scale"),errors="coerce").dropna()
    market_scale=float(market_values.median()) if len(market_values) else 1.0

    quality=(
        float(V71_CONFIG["market_weight"])*market_scale
        +float(V71_CONFIG["confidence_weight"])*confidence
    )
    max_gross=float(V71_CONFIG["max_target_gross"])
    target=float(np.clip(floor+(max_gross-floor)*quality,floor,max_gross))
    return target,{
        "regime":regime,
        "floor":round(floor,4),
        "threshold":round(threshold,4),
        "avg_meta_probability":round(avg_prob,4),
        "confidence_quality":round(confidence,4),
        "market_scale":round(market_scale,4),
        "target_gross":round(target,4),
    }


def apply_v71_balanced_exposure(
    v7_scored:pd.DataFrame,
    *,
    floor_shift:float=0.0,
)->tuple[pd.DataFrame,dict]:
    out=v7_scored.copy().sort_values(["date","symbol"])
    out["v71_trade_score"]=np.nan
    out["v71_position_scale"]=0.0
    out["v71_target_gross"]=0.0

    diagnostics=[]
    for signal_date,day in out.groupby("date",sort=True):
        selected=day[day["v7_trade_score"].notna()].copy()
        if selected.empty:
            continue

        target,diag=_target_gross(selected,floor_shift=floor_shift)

        raw=(
            pd.to_numeric(selected["v7_probability_scale"],errors="coerce").fillna(0.0).to_numpy(dtype=float)
            *pd.to_numeric(selected["v7_vol_scale"],errors="coerce").fillna(1.0).to_numpy(dtype=float)
        )
        if not np.isfinite(raw).any() or float(np.nanmean(raw))<=1e-9:
            raw=np.ones(len(selected),dtype=float)

        raw=np.clip(np.nan_to_num(raw,nan=0.0,posinf=1.0,neginf=0.0),0.02,1.0)
        scale=raw/max(float(raw.mean()),1e-9)*target
        scale=np.clip(scale,0.02,1.0)

        # One second normalization pass gets the mean exposure close to target
        # after clipping while never increasing any position above scale=1.
        mean_scale=float(scale.mean())
        if mean_scale>1e-9 and mean_scale<target:
            scale=np.clip(scale*(target/mean_scale),0.02,1.0)

        idx=selected.index
        out.loc[idx,"v71_trade_score"]=selected["v7_trade_score"].to_numpy(dtype=float)
        out.loc[idx,"v71_position_scale"]=scale
        out.loc[idx,"v71_target_gross"]=target

        diagnostics.append({
            "date":str(pd.Timestamp(signal_date).date()),
            **diag,
            "selected_names":int(len(selected)),
            "realized_mean_scale":round(float(scale.mean()),4),
        })

    summary={
        "method":"CONFIDENCE_NORMALIZED_DYNAMIC_GROSS_EXPOSURE",
        "regime_floors":dict(V71_CONFIG["regime_floors"]),
        "floor_shift":round(float(floor_shift),4),
        "max_target_gross":float(V71_CONFIG["max_target_gross"]),
        "mean_target_gross":round(float(np.mean([x["target_gross"] for x in diagnostics])),4) if diagnostics else None,
        "mean_realized_scale":round(float(np.mean([x["realized_mean_scale"] for x in diagnostics])),4) if diagnostics else None,
        "decision_dates":len(diagnostics),
        "latest":diagnostics[-1] if diagnostics else None,
    }
    return out,summary


def build_meta_v71_oos(
    panel:pd.DataFrame|None=None,
    progress:Callable[[int,str],None]|None=None,
)->tuple[pd.DataFrame,dict]:
    source=build_feature_panel() if panel is None else panel
    if progress:progress(8,"META V7.1 — construction alpha V6 OOS")
    v6_scored,v6_research=build_meta_v6_oos(panel=source,progress=progress)
    if progress:progress(72,"META V7.1 — diversification V7")
    v7_scored,v7_overlay=apply_v7_risk_overlay(v6_scored,v6_research)
    if progress:progress(80,"META V7.1 — balanced exposure")
    scored,exposure=apply_v71_balanced_exposure(v7_scored)

    research={
        "name":"META Ensemble v7.1 Balanced Exposure",
        "dataset":panel_metadata(source),
        "parent_model":"META Ensemble v7 Diversified Risk",
        "simulation":{
            **v6_research.get("simulation",{}),
            "method":"CONTINUOUS_OOS_V6_PLUS_V7_RISK_PLUS_BALANCED_EXPOSURE",
        },
        "target":v6_research.get("target",{}),
        "risk_overlay":v7_overlay,
        "exposure_overlay":exposure,
        "design_status":"EXPLORATORY_AFTER_V7_UNDEREXPOSURE_DIAGNOSTIC",
        "audit":(
            "V7.1 keeps V6 alpha and V7 correlation selection unchanged. It only normalizes "
            "position scales to a dynamic gross-exposure target computed from then-known market "
            "risk, regime and meta confidence. It is post-diagnostic and requires future shadow validation."
        ),
    }
    return scored,research


def run_meta_v71(panel:pd.DataFrame|None=None,progress=None)->dict:
    from app.services.backtest import run_backtest
    scored,research=build_meta_v71_oos(panel=panel,progress=progress)
    result=run_backtest(
        V71_PORTFOLIO,
        score_column="v71_trade_score",
        strategy_name="META Ensemble v7.1 Balanced Exposure",
        panel=scored,
        position_scale_column="v71_position_scale",
    )
    result["meta_v71"]=research
    result["research_status"]="EXPERIMENTAL_POST_DIAGNOSTIC_BALANCED_EXPOSURE"
    result["audit_note"]+=(
        " V7.1 is an exploratory capital-utilization overlay. Alpha, labels and correlation "
        "selection are unchanged from V6/V7; only gross exposure allocation is modified."
    )
    return result


def meta_v71_validation_bundle(panel:pd.DataFrame|None=None,progress=None)->dict:
    from app.services.backtest import run_backtest

    source=build_feature_panel() if panel is None else panel
    if progress:progress(8,"META V7.1 — alpha V6 OOS")
    v6_scored,v6_research=build_meta_v6_oos(panel=source,progress=progress)
    if progress:progress(70,"META V7.1 — risk overlay V7")
    v7_scored,v7_overlay=apply_v7_risk_overlay(v6_scored,v6_research)

    scenarios=[
        ("base",0.00),
        ("floor_minus_10",-0.10),
        ("floor_plus_10",0.10),
    ]
    rows=[]
    base_result=None
    base_research=None
    base_scored=None

    for i,(name,shift) in enumerate(scenarios):
        if progress:progress(78+int(10*i/len(scenarios)),f"META V7.1 exposure stress: {name}")
        scored,exposure=apply_v71_balanced_exposure(v7_scored,floor_shift=shift)
        result=run_backtest(
            V71_PORTFOLIO,
            score_column="v71_trade_score",
            strategy_name=f"META V7.1 {name}",
            panel=scored,
            position_scale_column="v71_position_scale",
        )
        rows.append({"scenario":name,**result["metrics"],"exposure_overlay":exposure})
        if name=="base":
            base_result=result;base_scored=scored
            base_research={
                "name":"META Ensemble v7.1 Balanced Exposure",
                "dataset":panel_metadata(source),
                "parent_model":"META Ensemble v7 Diversified Risk",
                "simulation":{
                    **v6_research.get("simulation",{}),
                    "method":"CONTINUOUS_OOS_V6_PLUS_V7_RISK_PLUS_BALANCED_EXPOSURE",
                },
                "target":v6_research.get("target",{}),
                "risk_overlay":v7_overlay,
                "exposure_overlay":exposure,
                "design_status":"EXPLORATORY_AFTER_V7_UNDEREXPOSURE_DIAGNOSTIC",
            }

    for name,mult in (("cost_x2",2.0),("cost_x3",3.0)):
        result=run_backtest(
            V71_PORTFOLIO|{
                "commission_bps":6.0*mult,
                "slippage_bps":5.0*mult,
            },
            score_column="v71_trade_score",
            strategy_name=f"META V7.1 {name}",
            panel=base_scored,
            position_scale_column="v71_position_scale",
        )
        rows.append({"scenario":name,**result["metrics"]})

    sharpes=np.asarray([float(row["sharpe"]) for row in rows],dtype=float)
    robustness={
        "positive_sharpe_ratio":round(float((sharpes>0).mean()),4),
        "median_sharpe":round(float(np.median(sharpes)),3),
        "min_sharpe":round(float(np.min(sharpes)),3),
        "cost_stress_pass":all(row["sharpe"]>0 for row in rows if row["scenario"] in ("cost_x2","cost_x3")),
        "scenario_count":len(rows),
    }
    base_result["meta_v71"]=base_research
    base_result["research_status"]="EXPERIMENTAL_POST_DIAGNOSTIC_BALANCED_EXPOSURE"
    return {"backtest":base_result,"research":base_research,"robustness":robustness,"scenarios":rows}
