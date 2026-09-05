from __future__ import annotations

import json
import os
import re
from datetime import date,timedelta

import numpy as np
import pandas as pd

from app.core.config import settings
from app.services.external_http import ExternalServiceError,request_json

DATA_DIR=os.getenv("QUANTLAB_DATA_DIR","/data")
os.makedirs(DATA_DIR,exist_ok=True)

DEFAULT_UNIVERSE="AAPL MSFT NVDA AMZN META GOOGL GOOG AVGO TSLA BRK.B JPM LLY V WMT XOM MA UNH ORCL COST HD PG JNJ ABBV BAC NFLX CRM KO CVX MRK AMD PEP TMO CSCO ACN MCD IBM GE ABT CAT QCOM INTU AMAT TXN ISRG NOW BKNG SPGI GS RTX HON AMGN LOW PFE DIS NKE SBUX UPS BA DE".split()
EXCHANGES={"NASDAQ","NYSE","ARCA","AMEX"}
EXCLUDE_NAME=(" ETF"," ETN"," FUND"," WARRANT"," RIGHTS"," UNIT"," DEPOSITARY")

def headers():
    return {"APCA-API-KEY-ID":settings.alpaca_api_key,"APCA-API-SECRET-KEY":settings.alpaca_secret_key}

def require_keys():
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise RuntimeError("Configure ALPACA_API_KEY and ALPACA_SECRET_KEY in .env for DATA_MODE=alpaca")

def get_assets():
    require_keys()
    return request_json(
        "GET",
        settings.alpaca_paper_base_url+"/v2/assets",
        service="Alpaca assets",
        params={"status":"active","asset_class":"us_equity"},
        headers=headers(),
        timeout=20,
        retries=2,
    )

def _asset_candidates():
    out=[]
    for a in get_assets():
        sym=str(a.get("symbol","")).upper()
        name=" "+str(a.get("name","")).upper()
        if not sym or len(sym)>10 or not re.match(r"^[A-Z0-9.\-]+$",sym):
            continue
        if a.get("exchange") not in EXCHANGES or not a.get("tradable") or not a.get("shortable"):
            continue
        if any(x in name for x in EXCLUDE_NAME):
            continue
        if not a.get("fractionable"):
            continue
        out.append(sym)
    return sorted(set(out))

def _rank_universe(candidates):
    ranked=[]
    for start in range(0,len(candidates),150):
        chunk=candidates[start:start+150]
        try:
            payload=request_json(
                "GET",
                settings.alpaca_data_base_url+"/v2/stocks/snapshots",
                service="Alpaca snapshots",
                params={"symbols":",".join(chunk),"feed":settings.alpaca_feed},
                headers=headers(),
                timeout=25,
                retries=2,
            )
        except ExternalServiceError:
            continue
        snapshots=payload.get("snapshots",payload)
        for sym,snap in snapshots.items():
            bar=(snap or {}).get("dailyBar") or (snap or {}).get("prevDailyBar") or {}
            price=float(bar.get("c") or 0)
            volume=float(bar.get("v") or 0)
            if price>=5 and volume>0:
                ranked.append((sym,price*volume,price,volume))
    ranked.sort(key=lambda x:x[1],reverse=True)
    return ranked

def universe(force=False):
    path=os.path.join(DATA_DIR,"universe.json")
    if os.path.exists(path) and not force and pd.Timestamp.now().timestamp()-os.path.getmtime(path)<24*3600:
        try:
            with open(path,encoding="utf-8") as fh:
                syms=json.load(fh).get("symbols",[])
            if syms:
                return syms[:settings.real_universe_size]
        except (OSError,ValueError,TypeError):
            pass

    syms=[]
    try:
        ranked=_rank_universe(_asset_candidates())
        syms=[x[0] for x in ranked[:settings.real_universe_size]]
    except Exception:
        syms=[]

    # Fallback must not depend on the same failing /assets request.
    if len(syms)<min(20,settings.real_universe_size):
        syms=DEFAULT_UNIVERSE[:settings.real_universe_size]

    tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as fh:
        json.dump({"date":date.today().isoformat(),"symbols":syms},fh)
    os.replace(tmp,path)
    return syms

def _bars_meta_path():
    return os.path.join(DATA_DIR,"alpaca_bars.meta.json")

def market_data_metadata():
    path=_bars_meta_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path,encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def _requested_history_start():
    configured=str(getattr(settings,"real_history_start","") or "").strip()
    if configured:
        return configured
    return (date.today()-timedelta(days=365*settings.real_history_years+30)).isoformat()

def fetch_bars(force=False):
    require_keys()
    path=os.path.join(DATA_DIR,"alpaca_bars.parquet")
    syms=universe(force=force)
    start=_requested_history_start()
    end=date.today().isoformat()
    meta=market_data_metadata()
    cache_matches=(
        os.path.exists(path)
        and meta.get("requested_start")==start
        and meta.get("feed")==settings.alpaca_feed
        and meta.get("universe_size")==len(syms)
    )
    if cache_matches and not force and pd.Timestamp.now().timestamp()-os.path.getmtime(path)<12*3600:
        return pd.read_parquet(path)

    rows=[]
    failures=[]

    for chunk0 in range(0,len(syms),20):
        chunk=syms[chunk0:chunk0+20]
        token=None
        seen_tokens=set()
        try:
            while True:
                params={"symbols":",".join(chunk),"timeframe":"1Day","start":start,"end":end,"adjustment":"all","feed":settings.alpaca_feed,"limit":10000,"sort":"asc"}
                if token:
                    params["page_token"]=token
                payload=request_json(
                    "GET",
                    settings.alpaca_data_base_url+"/v2/stocks/bars",
                    service="Alpaca bars",
                    params=params,
                    headers=headers(),
                    timeout=45,
                    retries=2,
                )
                for sym,bars in payload.get("bars",{}).items():
                    for b in bars:
                        rows.append((pd.Timestamp(b["t"]).tz_convert(None).normalize(),sym,b["o"],b["h"],b["l"],b["c"],b["v"],b.get("vw",b["c"])))
                next_token=payload.get("next_page_token")
                if not next_token:
                    break
                if next_token in seen_tokens:
                    raise RuntimeError("Alpaca bars returned a repeated pagination token")
                seen_tokens.add(next_token)
                token=next_token
        except Exception as exc:
            failures.append({"symbols":chunk,"error":str(exc)})

    df=pd.DataFrame(rows,columns=["date","symbol","open","high","low","close","volume","vwap"])
    if df.empty:
        raise RuntimeError(f"Alpaca returned no daily bars. failures={failures[:3]}")
    df=df.drop_duplicates(["date","symbol"]).sort_values(["symbol","date"])
    minimum=min(20,settings.real_universe_size)
    if df.symbol.nunique()<minimum:
        raise RuntimeError(f"Alpaca bars incomplete: only {df.symbol.nunique()} symbols, expected at least {minimum}. failures={failures[:3]}")

    tmp=path+".tmp"
    df.to_parquet(tmp,index=False)
    os.replace(tmp,path)
    meta={
        "requested_start":start,
        "requested_end":end,
        "actual_from":str(pd.Timestamp(df.date.min()).date()),
        "actual_to":str(pd.Timestamp(df.date.max()).date()),
        "feed":settings.alpaca_feed,
        "symbols":int(df.symbol.nunique()),
        "universe_size":len(syms),
        "rows":int(len(df)),
        "updated_at":pd.Timestamp.utcnow().isoformat(),
        "failures":failures[:20],
    }
    meta_path=_bars_meta_path();tmp_meta=meta_path+".tmp"
    with open(tmp_meta,"w",encoding="utf-8") as fh:
        json.dump(meta,fh,indent=2)
    os.replace(tmp_meta,meta_path)
    return df

def fetch_news(days=30):
    require_keys()
    start=(date.today()-timedelta(days=days)).isoformat()
    syms=universe()
    out=[]
    for chunk0 in range(0,len(syms),40):
        token=None
        seen_tokens=set()
        chunk=syms[chunk0:chunk0+40]
        while True:
            params={"symbols":",".join(chunk),"start":start,"limit":50,"sort":"desc"}
            if token:
                params["page_token"]=token
            try:
                payload=request_json(
                    "GET",
                    settings.alpaca_data_base_url+"/v1beta1/news",
                    service="Alpaca news",
                    params=params,
                    headers=headers(),
                    timeout=20,
                    retries=1,
                )
            except ExternalServiceError:
                break
            out.extend(payload.get("news",[]))
            next_token=payload.get("next_page_token")
            if not next_token or len(out)>2000 or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            token=next_token
    return out

def news_scores():
    pos={"beat","beats","growth","record","upgrade","raises","strong","profit","surge","wins","approval","buyback","outperform"}
    neg={"miss","misses","cuts","downgrade","lawsuit","probe","weak","loss","decline","layoffs","recall","fraud","underperform"}
    scores={}
    try:
        news=fetch_news(30)
    except Exception:
        news=[]
    for item in news:
        text=(item.get("headline","")+" "+item.get("summary","")).lower()
        words=set(text.replace(","," ").replace("."," ").split())
        score=(len(words&pos)-len(words&neg))/max(1,len(words&pos)+len(words&neg))
        try:
            age=max(0,(pd.Timestamp.now(tz="UTC")-pd.Timestamp(item["created_at"])).days)
        except Exception:
            age=30
        decay=np.exp(-age/7)
        for symbol in item.get("symbols",[]):
            scores.setdefault(symbol,[]).append(score*decay)
    return {symbol:float(np.mean(values)) for symbol,values in scores.items() if values}
