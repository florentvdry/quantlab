from __future__ import annotations
from app.services.features import build_feature_panel

FACTOR_LABELS={
 "momentum_12_1_rank":"Momentum 12-1","ret_60d_rank":"Momentum 60D","ret_20d_rank":"Momentum 20D",
 "trend_200_rank":"Trend 200D","fundamental_raw_rank":"Fundamentals","earnings_raw_rank":"Earnings",
 "news_raw_rank":"News","low_vol_rank":"Low volatility","liquidity_rank":"Liquidity"
}

def explain_symbol(symbol:str):
    df=build_feature_panel()
    latest=df.date.max()
    snap=df[df.date==latest].sort_values("meta_score",ascending=False).reset_index(drop=True)
    hit=snap[snap.symbol.str.upper()==symbol.upper()]
    if hit.empty: raise ValueError("Symbol not in latest universe")
    r=hit.iloc[0]; rank=int(hit.index[0])+1
    factors=[]
    for key,label in FACTOR_LABELS.items():
        if key in r:
            val=float(r[key]) if r[key]==r[key] else None
            factors.append({"key":key,"label":label,"rank":val})
    positive=sorted([x for x in factors if x["rank"] is not None],key=lambda x:x["rank"],reverse=True)[:3]
    negative=sorted([x for x in factors if x["rank"] is not None],key=lambda x:x["rank"])[:3]
    return {"symbol":symbol.upper(),"date":str(latest.date()),"rank":rank,"universe_size":int(len(snap)),"meta_score":round(float(r.meta_score),4),
            "factors":factors,"positive_contributors":positive,"negative_contributors":negative}
