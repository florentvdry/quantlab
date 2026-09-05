from __future__ import annotations
import json, os
from datetime import date, timedelta
from functools import lru_cache
import httpx, pandas as pd, numpy as np
from app.core.config import settings
CACHE='/data'; os.makedirs(CACHE,exist_ok=True)
DEFAULT_UNIVERSE='AAPL MSFT NVDA AMZN META GOOGL GOOG AVGO TSLA BRK.B JPM LLY V WMT XOM MA UNH ORCL COST HD PG JNJ ABBV BAC NFLX CRM KO CVX MRK AMD PEP TMO CSCO ACN MCD IBM GE ABT CAT QCOM INTU AMAT TXN ISRG NOW BKNG SPGI GS RTX HON AMGN LOW PFE DIS NKE SBUX UPS BA DE'.split()

def headers(): return {'APCA-API-KEY-ID':settings.alpaca_api_key,'APCA-API-SECRET-KEY':settings.alpaca_secret_key}
def require_keys():
    if not settings.alpaca_api_key or not settings.alpaca_secret_key: raise RuntimeError('Configure ALPACA_API_KEY and ALPACA_SECRET_KEY in .env for DATA_MODE=alpaca')

def get_assets():
    require_keys(); r=httpx.get(settings.alpaca_paper_base_url+'/v2/assets',params={'status':'active','asset_class':'us_equity'},headers=headers(),timeout=30); r.raise_for_status(); return r.json()

def universe():
    assets={x['symbol']:x for x in get_assets()}
    syms=[]
    for s in DEFAULT_UNIVERSE:
        a=assets.get(s)
        if a and a.get('tradable') and a.get('exchange') in ('NASDAQ','NYSE','ARCA','AMEX'): syms.append(s)
    return syms[:settings.real_universe_size]

def fetch_bars(force=False):
    require_keys(); path=f'{CACHE}/alpaca_bars.parquet'
    if os.path.exists(path) and not force and (pd.Timestamp.now().timestamp()-os.path.getmtime(path)<12*3600): return pd.read_parquet(path)
    syms=universe(); start=(date.today()-timedelta(days=365*settings.real_history_years+30)).isoformat(); end=date.today().isoformat(); rows=[]
    for chunk0 in range(0,len(syms),20):
        chunk=syms[chunk0:chunk0+20]; token=None
        while True:
            p={'symbols':','.join(chunk),'timeframe':'1Day','start':start,'end':end,'adjustment':'all','feed':settings.alpaca_feed,'limit':10000,'sort':'asc'}
            if token:p['page_token']=token
            r=httpx.get(settings.alpaca_data_base_url+'/v2/stocks/bars',params=p,headers=headers(),timeout=60); r.raise_for_status(); j=r.json()
            for sym,bars in j.get('bars',{}).items():
                for b in bars: rows.append((pd.Timestamp(b['t']).tz_convert(None).normalize(),sym,b['o'],b['h'],b['l'],b['c'],b['v'],b.get('vw',b['c'])))
            token=j.get('next_page_token')
            if not token:break
    df=pd.DataFrame(rows,columns=['date','symbol','open','high','low','close','volume','vwap']).drop_duplicates(['date','symbol']).sort_values(['symbol','date'])
    df.to_parquet(path,index=False); return df

def fetch_news(days=30):
    require_keys(); start=(date.today()-timedelta(days=days)).isoformat(); syms=universe(); out=[]
    for chunk0 in range(0,len(syms),40):
        token=None; chunk=syms[chunk0:chunk0+40]
        while True:
            p={'symbols':','.join(chunk),'start':start,'limit':50,'sort':'desc'}
            if token:p['page_token']=token
            r=httpx.get(settings.alpaca_data_base_url+'/v1beta1/news',params=p,headers=headers(),timeout=30)
            if r.status_code>=400: break
            j=r.json(); out.extend(j.get('news',[])); token=j.get('next_page_token')
            if not token or len(out)>1000:break
    return out

def news_scores():
    pos={'beat','beats','growth','record','upgrade','raises','strong','profit','surge','wins','approval','buyback','outperform'}; neg={'miss','misses','cuts','downgrade','lawsuit','probe','weak','loss','decline','layoffs','recall','fraud','underperform'}
    scores={}
    for n in fetch_news(30):
        text=(n.get('headline','')+' '+n.get('summary','')).lower(); words=set(text.replace(',',' ').replace('.',' ').split()); score=(len(words&pos)-len(words&neg))/max(1,len(words&pos)+len(words&neg))
        age=max(0,(pd.Timestamp.now(tz='UTC')-pd.Timestamp(n['created_at'])).days); decay=np.exp(-age/7)
        for s in n.get('symbols',[]): scores.setdefault(s,[]).append(score*decay)
    return {s:float(np.mean(v)) for s,v in scores.items() if v}
