from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from app.services.features import build_feature_panel
FEATURES=['momentum_12_1_rank','ret_60d_rank','ret_20d_rank','trend_50_rank','trend_200_rank','fundamental_raw_rank','earnings_raw_rank','news_raw_rank','low_vol_rank','liquidity_rank']

def factor_report(feature:str):
    if feature not in FEATURES: raise ValueError('Unknown feature')
    df=build_feature_panel().dropna(subset=[feature,'future_relative_20d']).copy()
    daily=df.groupby('date').apply(lambda x:x[feature].corr(x.future_relative_20d,method='spearman'),include_groups=False).dropna()
    q=df.groupby('date')[feature].transform(lambda s:pd.qcut(s.rank(method='first'),5,labels=False,duplicates='drop'))
    df['q']=q; spreads=[]
    for d,x in df.groupby('date'):
        if x.q.nunique()>=5: spreads.append(x[x.q==4].future_relative_20d.mean()-x[x.q==0].future_relative_20d.mean())
    return {'feature':feature,'mean_rank_ic':float(daily.mean()),'ic_std':float(daily.std()),'ic_ir':float(daily.mean()/(daily.std()+1e-12)),'positive_ic_ratio':float((daily>0).mean()),'top_bottom_future_20d':float(np.nanmean(spreads)),'observations':int(len(df)),'dates':int(df.date.nunique()),'recent_ic':[{'date':str(pd.Timestamp(d).date()),'ic':round(float(v),4)} for d,v in daily.tail(60).items()]}

def correlations():
    df=build_feature_panel(); latest=df[df.date==df.date.max()]; c=latest[FEATURES].corr().round(3); return {'features':FEATURES,'matrix':c.values.tolist()}

def train_walk_forward(model='ridge'):
    df=build_feature_panel().dropna(subset=FEATURES+['future_relative_20d']).copy(); dates=np.array(sorted(df.date.unique())); cut=int(len(dates)*.7); train_dates=set(dates[:cut]); test_dates=set(dates[cut:])
    tr=df[df.date.isin(train_dates)]; te=df[df.date.isin(test_dates)]; Xtr=tr[FEATURES].fillna(.5);Xte=te[FEATURES].fillna(.5);y=tr.future_relative_20d
    if model=='ridge': m=Ridge(alpha=10).fit(Xtr,y)
    else: m=HistGradientBoostingRegressor(max_iter=150,max_depth=4,learning_rate=.05,l2_regularization=1).fit(Xtr,y)
    pred=m.predict(Xte); te=te.copy();te['pred']=pred
    daily=te.groupby('date').apply(lambda x:x.pred.corr(x.future_relative_20d,method='spearman'),include_groups=False).dropna()
    latest=df[df.date==df.date.max()].copy();latest['prediction']=m.predict(latest[FEATURES].fillna(.5));latest=latest.sort_values('prediction',ascending=False)
    imp=[]
    if model=='ridge': imp=[{'feature':f,'importance':float(v)} for f,v in sorted(zip(FEATURES,m.coef_),key=lambda z:abs(z[1]),reverse=True)]
    return {'model':model,'train_from':str(pd.Timestamp(min(train_dates)).date()),'train_to':str(pd.Timestamp(max(train_dates)).date()),'test_from':str(pd.Timestamp(min(test_dates)).date()),'test_to':str(pd.Timestamp(max(test_dates)).date()),'test_mean_rank_ic':float(daily.mean()),'test_ic_ir':float(daily.mean()/(daily.std()+1e-12)),'feature_importance':imp,'latest_top':[{'symbol':r.symbol,'prediction':round(float(r.prediction),6)} for r in latest.head(20).itertuples()]}
