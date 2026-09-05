from __future__ import annotations
import hashlib,json,os,time
import numpy as np
import pandas as pd
from app.core.config import settings
from app.services.data import synthetic_panel

FEATURE_SCHEMA_VERSION="3"
FEATURES=["momentum_12_1_rank","ret_60d_rank","ret_20d_rank","trend_50_rank","trend_200_rank","fundamental_raw_rank","earnings_raw_rank","news_raw_rank","low_vol_rank","liquidity_rank"]
STORE_DIR=os.getenv("QUANTLAB_DATA_DIR","/data");STORE_PATH=f"{STORE_DIR}/feature_store.parquet";META_PATH=f"{STORE_DIR}/feature_store.json"
_PANEL_CACHE=None;_PANEL_CACHE_AT=0.0
os.makedirs(STORE_DIR,exist_ok=True)

def _rank(s):return s.rank(pct=True).clip(.001,.999)

def _technical(df):
    df=df.copy().sort_values(["symbol","date"]);g=df.groupby("symbol",group_keys=False)
    for n in [5,20,60,120,252]:df[f"ret_{n}d"]=g["close"].pct_change(n,fill_method=None)
    df["momentum_12_1"]=df["ret_252d"]-df["ret_20d"];daily=g["close"].pct_change(fill_method=None)
    df["vol_20d"]=daily.groupby(df["symbol"]).rolling(20).std().reset_index(level=0,drop=True)*np.sqrt(252)
    df["vol_60d"]=daily.groupby(df["symbol"]).rolling(60).std().reset_index(level=0,drop=True)*np.sqrt(252)
    df["sma_50"]=g["close"].rolling(50).mean().reset_index(level=0,drop=True);df["sma_200"]=g["close"].rolling(200).mean().reset_index(level=0,drop=True)
    df["trend_50"]=df["close"]/df["sma_50"]-1;df["trend_200"]=df["close"]/df["sma_200"]-1;df["dollar_volume"]=df["close"]*df["volume"]
    return df

def _source_panel():
    if settings.data_mode.lower()=="alpaca":
        from app.services.real_data import fetch_bars,news_scores
        df=fetch_bars().copy();df["sector"]="US Equity";ns=news_scores();df["news_raw"]=0.0
        # The provider endpoint only gives a recent news window. Never smear today's
        # news score across historical dates: that would leak future information.
        latest_date=df["date"].max()
        mask=df["date"].eq(latest_date)
        df.loc[mask,"news_raw"]=df.loc[mask,"symbol"].map(ns).fillna(0.0)
        from app.services.sec_fundamentals import point_in_time_panel
        pit=point_in_time_panel(sorted(df.symbol.unique()),sorted(df.date.unique()))
        if not pit.empty:df=df.merge(pit[["date","symbol","fundamental_raw","earnings_raw"]],on=["date","symbol"],how="left")
        else:df["fundamental_raw"]=np.nan;df["earnings_raw"]=np.nan
        df["fundamental_raw"]=df["fundamental_raw"].fillna(df.groupby("date")["fundamental_raw"].transform("median")).fillna(0.0);df["earnings_raw"]=df["earnings_raw"].fillna(0.0)
        return df
    return synthetic_panel().copy()

def clear_feature_cache(remove_disk=False):
    global _PANEL_CACHE,_PANEL_CACHE_AT
    _PANEL_CACHE=None;_PANEL_CACHE_AT=0.0
    if remove_disk:
        for path in (STORE_PATH,META_PATH):
            try:os.remove(path)
            except FileNotFoundError:pass

def _store_matches_mode():
    if not os.path.exists(STORE_PATH) or not os.path.exists(META_PATH):return False
    try:
        with open(META_PATH,encoding="utf-8") as f:meta=json.load(f)
        return meta.get("mode")==settings.data_mode.lower() and meta.get("schema")==FEATURE_SCHEMA_VERSION
    except Exception:return False

def _disk_valid():
    return _store_matches_mode() and time.time()-os.path.getmtime(STORE_PATH)<12*3600

def _read_store():
    global _PANEL_CACHE,_PANEL_CACHE_AT
    df=pd.read_parquet(STORE_PATH);_PANEL_CACHE=df;_PANEL_CACHE_AT=time.time();return df.copy()

def _write_store(df):
    df.to_parquet(STORE_PATH,index=False)
    meta=panel_metadata(df);meta["stored_at"]=pd.Timestamp.utcnow().isoformat()
    with open(META_PATH,"w",encoding="utf-8") as f:json.dump(meta,f,indent=2)

def build_feature_panel(force=False):
    global _PANEL_CACHE,_PANEL_CACHE_AT
    if not force and _PANEL_CACHE is not None and time.time()-_PANEL_CACHE_AT<60:return _PANEL_CACHE.copy()

    # Dashboard/API reads must never trigger the expensive Alpaca + SEC rebuild.
    # Use the persisted store even when it is older than 12h; freshness is reported
    # separately by the data-quality/risk gates. Only the Daily Pipeline uses force=True.
    if not force and _store_matches_mode():return _read_store()
    if not force and settings.data_mode.lower()=="alpaca":
        raise RuntimeError("Feature Store not initialized for Alpaca mode. Run the Daily Pipeline first.")

    df=_technical(_source_panel());rank_cols=["momentum_12_1","ret_60d","ret_20d","trend_50","trend_200","fundamental_raw","earnings_raw","news_raw"]
    for c in rank_cols:df[c+"_rank"]=df.groupby("date")[c].transform(_rank)
    df["low_vol_rank"]=1-df.groupby("date")["vol_20d"].transform(_rank);df["liquidity_rank"]=df.groupby("date")["dollar_volume"].transform(_rank)
    df["meta_score"]=(.25*df["momentum_12_1_rank"]+.10*df["ret_60d_rank"]+.10*df["trend_200_rank"]+.20*df["fundamental_raw_rank"]+.15*df["earnings_raw_rank"]+.05*df["news_raw_rank"]+.10*df["low_vol_rank"]+.05*df["liquidity_rank"])
    df["future_20d"]=df.groupby("symbol",group_keys=False)["close"].transform(lambda s:s.shift(-20)/s-1);df["future_relative_20d"]=df["future_20d"]-df.groupby("date")["future_20d"].transform("mean")
    df=df.dropna(subset=["meta_score"]).copy();_PANEL_CACHE=df;_PANEL_CACHE_AT=time.time();_write_store(df);return df.copy()

def panel_metadata(df=None):
    df=build_feature_panel() if df is None else df
    payload={"mode":settings.data_mode.lower(),"feed":settings.alpaca_feed if settings.data_mode.lower()=="alpaca" else "synthetic","schema":FEATURE_SCHEMA_VERSION,
             "rows":int(len(df)),"symbols":int(df.symbol.nunique()),"from":str(pd.Timestamp(df.date.min()).date()),"to":str(pd.Timestamp(df.date.max()).date()),
             "historical_news":"neutral_no_point_in_time_history"}
    raw=json.dumps(payload,sort_keys=True).encode();payload["fingerprint"]=hashlib.sha256(raw).hexdigest()[:16];return payload