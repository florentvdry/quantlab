from __future__ import annotations
import numpy as np, pandas as pd
from app.core.config import settings
from app.services.data import synthetic_panel

def _rank(s): return s.rank(pct=True).clip(.001,.999)
def _technical(df):
    df=df.copy().sort_values(['symbol','date']); g=df.groupby('symbol',group_keys=False)
    for n in [5,20,60,120,252]: df[f'ret_{n}d']=g.close.pct_change(n)
    df['momentum_12_1']=df['ret_252d']-df['ret_20d']; daily=g.close.pct_change()
    df['vol_20d']=daily.rolling(20).std().reset_index(level=0,drop=True)*np.sqrt(252); df['vol_60d']=daily.rolling(60).std().reset_index(level=0,drop=True)*np.sqrt(252)
    df['sma_50']=g.close.rolling(50).mean().reset_index(level=0,drop=True); df['sma_200']=g.close.rolling(200).mean().reset_index(level=0,drop=True)
    df['trend_50']=df.close/df.sma_50-1; df['trend_200']=df.close/df.sma_200-1; df['dollar_volume']=df.close*df.volume
    return df

def build_feature_panel():
    if settings.data_mode.lower()=='alpaca':
        from app.services.real_data import fetch_bars,news_scores
        df=fetch_bars(); df['sector']='US Equity'; ns=news_scores(); df['news_raw']=df.symbol.map(ns).fillna(0.)
        from app.services.sec_fundamentals import point_in_time_panel
        pit=point_in_time_panel(sorted(df.symbol.unique()), sorted(df.date.unique()))
        if not pit.empty:
            df=df.merge(pit[['date','symbol','fundamental_raw','earnings_raw']],on=['date','symbol'],how='left')
        else:
            df['fundamental_raw']=np.nan; df['earnings_raw']=np.nan
        # Missing filings are neutral, never backfilled from future/current values.
        df['fundamental_raw']=df['fundamental_raw'].fillna(df.groupby('date')['fundamental_raw'].transform('median')).fillna(0.)
        df['earnings_raw']=df['earnings_raw'].fillna(0.)
    else: df=synthetic_panel().copy()
    df=_technical(df); g=df.groupby('symbol',group_keys=False)
    cols=['momentum_12_1','ret_60d','ret_20d','trend_50','trend_200','fundamental_raw','earnings_raw','news_raw']
    for c in cols: df[c+'_rank']=df.groupby('date')[c].transform(_rank)
    df['low_vol_rank']=1-df.groupby('date').vol_20d.transform(_rank); df['liquidity_rank']=df.groupby('date').dollar_volume.transform(_rank)
    df['meta_score']=.25*df.momentum_12_1_rank+.10*df.ret_60d_rank+.10*df.trend_200_rank+.20*df.fundamental_raw_rank+.15*df.earnings_raw_rank+.05*df.news_raw_rank+.10*df.low_vol_rank+.05*df.liquidity_rank
    df['future_20d']=g.close.pct_change(20).shift(-20); df['future_relative_20d']=df.future_20d-df.groupby('date').future_20d.transform('mean')
    return df.dropna(subset=['meta_score']).copy()
