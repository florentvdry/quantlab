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
EXCLUDE_NAME=(" ETF"," ETN"," FUND"," WARRANT"," RIGHTS"," UNIT")
ETF_SPONSOR_NAME=(
    "PROSHARES","DIREXION","ISHARES","SPDR ","VANGUARD ","GLOBAL X ",
    "WISDOMTREE","VANECK ","ARK ETF","ULTRAPRO","ULTRASHORT",
    "DAILY BULL","DAILY BEAR","2X SHARES","3X SHARES",
)

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
        if a.get("exchange") not in EXCHANGES or not a.get("tradable"):
            continue
        if any(x in name for x in EXCLUDE_NAME):
            continue
        if any(x in name for x in ETF_SPONSOR_NAME):
            continue
        if not a.get("fractionable"):
            continue
        out.append(sym)
    return sorted(set(out))

def _snapshot_rank(candidates):
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
            if price>=float(settings.real_universe_min_price) and volume>0:
                ranked.append((sym,price*volume,price,volume))
    ranked.sort(key=lambda x:x[1],reverse=True)
    return ranked


def _quality_history(symbols):
    if not symbols:
        return pd.DataFrame()
    start=(date.today()-timedelta(days=365*4+90)).isoformat()
    end=date.today().isoformat()
    rows=[]
    for chunk0 in range(0,len(symbols),20):
        chunk=symbols[chunk0:chunk0+20]
        token=None
        seen=set()
        try:
            while True:
                params={
                    "symbols":",".join(chunk),"timeframe":"1Day","start":start,"end":end,
                    "adjustment":"all","feed":settings.alpaca_feed,"limit":10000,"sort":"asc",
                }
                if token:params["page_token"]=token
                payload=request_json(
                    "GET",settings.alpaca_data_base_url+"/v2/stocks/bars",
                    service="Alpaca universe quality bars",params=params,headers=headers(),
                    timeout=45,retries=2,
                )
                for sym,bars in payload.get("bars",{}).items():
                    for b in bars:
                        rows.append((pd.Timestamp(b["t"]).tz_convert(None).normalize(),sym,float(b["c"]),float(b["v"])))
                nxt=payload.get("next_page_token")
                if not nxt or nxt in seen:break
                seen.add(nxt);token=nxt
        except Exception:
            continue
    if not rows:return pd.DataFrame()
    df=pd.DataFrame(rows,columns=["date","symbol","close","volume"]).drop_duplicates(["date","symbol"])
    df["dollar_volume"]=df["close"]*df["volume"]
    df=df.sort_values(["symbol","date"])
    df["ret_1d"]=df.groupby("symbol")["close"].pct_change(fill_method=None)
    stats=[]
    for sym,g in df.groupby("symbol"):
        recent=g.tail(60)
        vol=float(recent["ret_1d"].std(ddof=1)*np.sqrt(252)) if len(recent)>20 else np.nan
        stats.append({
            "symbol":sym,
            "history_sessions":int(len(g)),
            "last_price":float(g["close"].iloc[-1]),
            "median_dollar_volume_60":float(recent["dollar_volume"].median()) if len(recent) else 0.0,
            "volatility_60":vol,
        })
    return pd.DataFrame(stats)


def _sec_operating_quality(symbols):
    from app.services.sec_fundamentals import fundamental_events

    rows=[]
    core=("revenue","net_income","assets","equity","operating_cf")
    for symbol in symbols:
        try:
            ev=fundamental_events(symbol)
        except Exception:
            continue
        if ev.empty:
            continue
        latest={}
        for metric,g in ev.groupby("metric"):
            g=g.sort_values(["available_at","period_end"])
            latest[metric]=float(g.iloc[-1]["value"])
        coverage=sum(int(metric in latest and np.isfinite(latest[metric])) for metric in core)
        assets=float(latest.get("assets",np.nan))
        equity=float(latest.get("equity",np.nan))
        revenue=float(latest.get("revenue",np.nan))
        net_income=float(latest.get("net_income",np.nan))
        operating_cf=float(latest.get("operating_cf",np.nan))

        balance_ok=np.isfinite(assets) and assets>0 and np.isfinite(equity) and equity>0
        activity_ok=(np.isfinite(revenue) and revenue>0) or np.isfinite(net_income)
        earning_power=(np.isfinite(net_income) and net_income>0) or (np.isfinite(operating_cf) and operating_cf>0)
        eligible=(
            coverage>=int(settings.real_universe_min_sec_core_metrics)
            and balance_ok and activity_ok and earning_power
        )
        rows.append({
            "symbol":symbol,
            "sec_core_metrics":coverage,
            "sec_balance_ok":bool(balance_ok),
            "sec_activity_ok":bool(activity_ok),
            "sec_earning_power":bool(earning_power),
            "sec_operating_company":bool(eligible),
        })
    return pd.DataFrame(rows)


def _quality_rank_universe(candidates):
    snapshot=_snapshot_rank(candidates)
    if not snapshot:return []
    prefilter=int(settings.real_universe_prefilter_size)
    top=snapshot[:max(prefilter,int(settings.real_universe_size))]
    symbols=[x[0] for x in top]
    current_liq={x[0]:x[1] for x in top}
    stats=_quality_history(symbols)
    if stats.empty:
        return [x[0] for x in top[:settings.real_universe_size]]

    stats["current_dollar_volume"]=stats["symbol"].map(current_liq).fillna(0.0)
    qualified=stats[
        (stats["history_sessions"]>=int(settings.real_universe_min_history_sessions))
        &(stats["last_price"]>=float(settings.real_universe_min_price))
        &(stats["median_dollar_volume_60"]>=float(settings.real_universe_min_median_dollar_volume))
        &(stats["volatility_60"].fillna(99)<=float(settings.real_universe_max_volatility))
    ].copy()

    if qualified.empty:
        return []

    sec=_sec_operating_quality(qualified["symbol"].tolist())
    if sec.empty:
        return []
    qualified=qualified.merge(sec,on="symbol",how="left")
    qualified=qualified[qualified["sec_operating_company"].fillna(False)].copy()
    if qualified.empty:
        return []

    qualified["liq_rank"]=qualified["median_dollar_volume_60"].rank(pct=True)
    qualified["current_liq_rank"]=qualified["current_dollar_volume"].rank(pct=True)
    qualified["history_rank"]=qualified["history_sessions"].rank(pct=True)
    qualified["stability_rank"]=1-qualified["volatility_60"].rank(pct=True)
    qualified["quality_score"]=(
        .50*qualified["liq_rank"]
        +.20*qualified["current_liq_rank"]
        +.15*qualified["history_rank"]
        +.15*qualified["stability_rank"]
    )
    qualified=qualified.sort_values(["quality_score","median_dollar_volume_60"],ascending=False)

    selected=qualified.head(int(settings.real_universe_size))["symbol"].tolist()

    diagnostics={
        "generated_at":pd.Timestamp.utcnow().isoformat(),
        "candidate_count":len(candidates),
        "prefilter_count":len(symbols),
        "qualified_count":int(len(qualified)),
        "selected_count":len(selected),
        "filters":{
            "min_price":float(settings.real_universe_min_price),
            "min_history_sessions":int(settings.real_universe_min_history_sessions),
            "min_median_dollar_volume_60":float(settings.real_universe_min_median_dollar_volume),
            "max_volatility_60":float(settings.real_universe_max_volatility),
            "min_sec_core_metrics":int(settings.real_universe_min_sec_core_metrics),
            "requires_positive_equity":True,
            "requires_positive_net_income_or_operating_cf":True,
        },
        "top":[
            {
                "symbol":row.symbol,
                "score":round(float(row.quality_score),4),
                "median_dollar_volume_60":round(float(row.median_dollar_volume_60),2),
                "history_sessions":int(row.history_sessions),
                "volatility_60":round(float(row.volatility_60),4),
                "sec_core_metrics":int(row.sec_core_metrics),
            }
            for row in qualified.head(min(50,len(qualified))).itertuples()
        ],
    }
    tmp=os.path.join(DATA_DIR,"universe_quality.json.tmp")
    final=os.path.join(DATA_DIR,"universe_quality.json")
    with open(tmp,"w",encoding="utf-8") as fh:json.dump(diagnostics,fh,indent=2)
    os.replace(tmp,final)
    return selected

def universe_quality_metadata():
    path=os.path.join(DATA_DIR,"universe_quality.json")
    if not os.path.exists(path):return {}
    try:
        with open(path,encoding="utf-8") as fh:return json.load(fh)
    except Exception:return {}

def universe(force=False):
    path=os.path.join(DATA_DIR,"universe.json")
    if os.path.exists(path) and not force and pd.Timestamp.now().timestamp()-os.path.getmtime(path)<24*3600:
        try:
            with open(path,encoding="utf-8") as fh:
                cached=json.load(fh)
            syms=cached.get("symbols",[])
            if (
                syms
                and cached.get("mode")=="quality_operating_v3"
                and int(cached.get("requested_size",0))==int(settings.real_universe_size)
            ):
                return syms[:settings.real_universe_size]
        except (OSError,ValueError,TypeError):
            pass

    syms=[]
    try:
        syms=_quality_rank_universe(_asset_candidates())
    except Exception:
        syms=[]

    # Fallback must not depend on the same failing /assets request.
    if len(syms)<min(20,settings.real_universe_size):
        syms=DEFAULT_UNIVERSE[:settings.real_universe_size]

    tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as fh:
        json.dump({"date":date.today().isoformat(),"mode":"quality_operating_v3","requested_size":int(settings.real_universe_size),"symbols":syms},fh)
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
