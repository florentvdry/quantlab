from __future__ import annotations
import json,os,re
from datetime import date,timedelta
import httpx,pandas as pd,numpy as np
from app.core.config import settings

CACHE="/data";os.makedirs(CACHE,exist_ok=True)
DEFAULT_UNIVERSE="AAPL MSFT NVDA AMZN META GOOGL GOOG AVGO TSLA BRK.B JPM LLY V WMT XOM MA UNH ORCL COST HD PG JNJ ABBV BAC NFLX CRM KO CVX MRK AMD PEP TMO CSCO ACN MCD IBM GE ABT CAT QCOM INTU AMAT TXN ISRG NOW BKNG SPGI GS RTX HON AMGN LOW PFE DIS NKE SBUX UPS BA DE".split()
EXCHANGES={"NASDAQ","NYSE","ARCA","AMEX"}
EXCLUDE_NAME=(" ETF"," ETN"," FUND"," WARRANT"," RIGHTS"," UNIT"," DEPOSITARY")

def headers():return {"APCA-API-KEY-ID":settings.alpaca_api_key,"APCA-API-SECRET-KEY":settings.alpaca_secret_key}
def require_keys():
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:raise RuntimeError("Configure ALPACA_API_KEY and ALPACA_SECRET_KEY in .env for DATA_MODE=alpaca")

def get_assets():
    require_keys();r=httpx.get(settings.alpaca_paper_base_url+"/v2/assets",params={"status":"active","asset_class":"us_equity"},headers=headers(),timeout=30);r.raise_for_status();return r.json()

def _asset_candidates():
    out=[]
    for a in get_assets():
        sym=str(a.get("symbol","")).upper();name=" "+str(a.get("name","")).upper()
        if not sym or len(sym)>10 or not re.match(r"^[A-Z0-9.\-]+$",sym):continue
        if a.get("exchange") not in EXCHANGES or not a.get("tradable") or not a.get("shortable"):continue
        if any(x in name for x in EXCLUDE_NAME):continue
        # fractionable is a useful first-pass liquidity filter; curated seeds remain fallback.
        if not a.get("fractionable"):continue
        out.append(sym)
    return sorted(set(out))

def _rank_universe(candidates):
    ranked=[]
    for start in range(0,len(candidates),150):
        chunk=candidates[start:start+150]
        try:
            r=httpx.get(settings.alpaca_data_base_url+"/v2/stocks/snapshots",params={"symbols":",".join(chunk),"feed":settings.alpaca_feed},headers=headers(),timeout=30)
            r.raise_for_status();payload=r.json()
        except Exception:
            continue
        snapshots=payload.get("snapshots",payload)
        for sym,snap in snapshots.items():
            bar=(snap or {}).get("dailyBar") or (snap or {}).get("prevDailyBar") or {}
            price=float(bar.get("c") or 0);volume=float(bar.get("v") or 0);dv=price*volume
            if price>=5 and volume>0:ranked.append((sym,dv,price,volume))
    ranked.sort(key=lambda x:x[1],reverse=True)
    return ranked

def universe(force=False):
    path=f"{CACHE}/universe.json"
    if os.path.exists(path) and not force and pd.Timestamp.now().timestamp()-os.path.getmtime(path)<24*3600:
        try:
            d=json.load(open(path,encoding="utf-8"));syms=d.get("symbols",[])
            if syms:return syms[:settings.real_universe_size]
        except Exception:pass
    try:
        candidates=_asset_candidates();ranked=_rank_universe(candidates);syms=[x[0] for x in ranked[:settings.real_universe_size]]
    except Exception:syms=[]
    if len(syms)<min(20,settings.real_universe_size):
        assets={x["symbol"]:x for x in get_assets()};syms=[s for s in DEFAULT_UNIVERSE if s in assets and assets[s].get("tradable")][:settings.real_universe_size]
    with open(path,"w",encoding="utf-8") as f:json.dump({"date":date.today().isoformat(),"symbols":syms},f)
    return syms

def fetch_bars(force=False):
    require_keys();path=f"{CACHE}/alpaca_bars.parquet"
    if os.path.exists(path) and not force and pd.Timestamp.now().timestamp()-os.path.getmtime(path)<12*3600:return pd.read_parquet(path)
    syms=universe(force=force);start=(date.today()-timedelta(days=365*settings.real_history_years+30)).isoformat();end=date.today().isoformat();rows=[]
    for chunk0 in range(0,len(syms),20):
        chunk=syms[chunk0:chunk0+20];token=None
        while True:
            p={"symbols":",".join(chunk),"timeframe":"1Day","start":start,"end":end,"adjustment":"all","feed":settings.alpaca_feed,"limit":10000,"sort":"asc"}
            if token:p["page_token"]=token
            r=httpx.get(settings.alpaca_data_base_url+"/v2/stocks/bars",params=p,headers=headers(),timeout=60);r.raise_for_status();j=r.json()
            for sym,bars in j.get("bars",{}).items():
                for b in bars:rows.append((pd.Timestamp(b["t"]).tz_convert(None).normalize(),sym,b["o"],b["h"],b["l"],b["c"],b["v"],b.get("vw",b["c"])))
            token=j.get("next_page_token")
            if not token:break
    df=pd.DataFrame(rows,columns=["date","symbol","open","high","low","close","volume","vwap"]).drop_duplicates(["date","symbol"]).sort_values(["symbol","date"])
    if df.empty:raise RuntimeError("Alpaca returned no daily bars for the selected universe")
    df.to_parquet(path,index=False);return df

def fetch_news(days=30):
    require_keys();start=(date.today()-timedelta(days=days)).isoformat();syms=universe();out=[]
    for chunk0 in range(0,len(syms),40):
        token=None;chunk=syms[chunk0:chunk0+40]
        while True:
            p={"symbols":",".join(chunk),"start":start,"limit":50,"sort":"desc"}
            if token:p["page_token"]=token
            r=httpx.get(settings.alpaca_data_base_url+"/v1beta1/news",params=p,headers=headers(),timeout=30)
            if r.status_code>=400:break
            j=r.json();out.extend(j.get("news",[]));token=j.get("next_page_token")
            if not token or len(out)>2000:break
    return out

def news_scores():
    pos={"beat","beats","growth","record","upgrade","raises","strong","profit","surge","wins","approval","buyback","outperform"};neg={"miss","misses","cuts","downgrade","lawsuit","probe","weak","loss","decline","layoffs","recall","fraud","underperform"};scores={}
    for n in fetch_news(30):
        text=(n.get("headline","")+" "+n.get("summary","")).lower();words=set(text.replace(","," ").replace("."," ").split());score=(len(words&pos)-len(words&neg))/max(1,len(words&pos)+len(words&neg))
        age=max(0,(pd.Timestamp.now(tz="UTC")-pd.Timestamp(n["created_at"])).days);decay=np.exp(-age/7)
        for s in n.get("symbols",[]):scores.setdefault(s,[]).append(score*decay)
    return {s:float(np.mean(v)) for s,v in scores.items() if v}
