from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from app.services.features import build_feature_panel, FEATURES, panel_metadata

def factor_report(feature:str,panel=None):
    if feature not in FEATURES: raise ValueError("Unknown feature")
    df=(build_feature_panel() if panel is None else panel).dropna(subset=[feature,"future_relative_20d"]).copy()
    daily=df.groupby("date").apply(lambda x:x[feature].corr(x.future_relative_20d,method="spearman"),include_groups=False).dropna()
    df["q"]=df.groupby("date")[feature].transform(lambda s:pd.qcut(s.rank(method="first"),5,labels=False,duplicates="drop"))
    spreads=[]
    for _,x in df.groupby("date"):
        if x.q.nunique()>=5: spreads.append(x[x.q==4].future_relative_20d.mean()-x[x.q==0].future_relative_20d.mean())
    monthly=daily.groupby(pd.to_datetime(daily.index).to_period("M")).mean()
    return {"feature":feature,"mean_rank_ic":float(daily.mean()),"ic_std":float(daily.std()),"ic_ir":float(daily.mean()/(daily.std()+1e-12)),
            "positive_ic_ratio":float((daily>0).mean()),"top_bottom_future_20d":float(np.nanmean(spreads)),
            "observations":int(len(df)),"dates":int(df.date.nunique()),
            "monthly_ic":[{"month":str(k),"ic":round(float(v),4)} for k,v in monthly.tail(36).items()],
            "recent_ic":[{"date":str(pd.Timestamp(d).date()),"ic":round(float(v),4)} for d,v in daily.tail(60).items()]}

def factor_summary(panel=None):
    df=build_feature_panel() if panel is None else panel
    rows=[]
    for f in FEATURES:
        try:
            r=factor_report(f,df); rows.append({k:r[k] for k in ["feature","mean_rank_ic","ic_ir","positive_ic_ratio","top_bottom_future_20d"]})
        except Exception:
            rows.append({"feature":f,"mean_rank_ic":None,"ic_ir":None,"positive_ic_ratio":None,"top_bottom_future_20d":None})
    return {"dataset":panel_metadata(df),"factors":rows}

def correlations(panel=None):
    df=build_feature_panel() if panel is None else panel
    latest=df[df.date==df.date.max()]
    c=latest[FEATURES].corr().round(3)
    return {"features":FEATURES,"matrix":c.values.tolist()}

def _make_model(model):
    if model=="ridge": return Ridge(alpha=10)
    if model=="hgb": return HistGradientBoostingRegressor(max_iter=150,max_depth=4,learning_rate=.05,l2_regularization=1)
    raise ValueError("model must be ridge or hgb")

def train_walk_forward(model="ridge", panel=None, min_train_days=504, test_days=126):
    df=(build_feature_panel() if panel is None else panel).dropna(subset=FEATURES+["future_relative_20d"]).copy()
    dates=np.array(sorted(df.date.unique()))
    if len(dates)<min_train_days+test_days:
        min_train_days=max(252,int(len(dates)*.55)); test_days=max(63,int(len(dates)*.15))
    folds=[]; all_pred=[]; start=min_train_days
    while start<len(dates):
        stop=min(start+test_days,len(dates)); train_dates=dates[:start]; test_dates=dates[start:stop]
        if len(test_dates)<20: break
        tr=df[df.date.isin(train_dates)]; te=df[df.date.isin(test_dates)].copy()
        m=_make_model(model); m.fit(tr[FEATURES].fillna(.5),tr.future_relative_20d)
        te["pred"]=m.predict(te[FEATURES].fillna(.5))
        daily=te.groupby("date").apply(lambda x:x.pred.corr(x.future_relative_20d,method="spearman"),include_groups=False).dropna()
        folds.append({"train_from":str(pd.Timestamp(train_dates[0]).date()),"train_to":str(pd.Timestamp(train_dates[-1]).date()),
                      "test_from":str(pd.Timestamp(test_dates[0]).date()),"test_to":str(pd.Timestamp(test_dates[-1]).date()),
                      "mean_rank_ic":float(daily.mean()),"ic_ir":float(daily.mean()/(daily.std()+1e-12)),"days":int(len(test_dates))})
        all_pred.append(te[["date","symbol","future_relative_20d","pred"]]); start=stop
    if not folds: raise ValueError("Not enough history for walk-forward")
    oos=pd.concat(all_pred,ignore_index=True)
    daily=oos.groupby("date").apply(lambda x:x.pred.corr(x.future_relative_20d,method="spearman"),include_groups=False).dropna()
    final=_make_model(model); final.fit(df[FEATURES].fillna(.5),df.future_relative_20d)
    latest=df[df.date==df.date.max()].copy(); latest["prediction"]=final.predict(latest[FEATURES].fillna(.5)); latest=latest.sort_values("prediction",ascending=False)
    imp=[]
    if model=="ridge": imp=[{"feature":f,"importance":float(v)} for f,v in sorted(zip(FEATURES,final.coef_),key=lambda z:abs(z[1]),reverse=True)]
    return {"model":model,"dataset":panel_metadata(df),"folds":folds,"oos_mean_rank_ic":float(daily.mean()),
            "oos_ic_ir":float(daily.mean()/(daily.std()+1e-12)),"positive_oos_ic_ratio":float((daily>0).mean()),
            "feature_importance":imp,"latest_top":[{"symbol":r.symbol,"prediction":round(float(r.prediction),6)} for r in latest.head(20).itertuples()]}
