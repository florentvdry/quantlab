from __future__ import annotations
import json, os, time
from pathlib import Path
import httpx, numpy as np, pandas as pd

_LAST_DIAGNOSTICS={'not_found':set(),'errors':{}}
from app.core.config import settings

CACHE=Path(os.getenv('QUANTLAB_DATA_DIR','/data'))/'sec'; CACHE.mkdir(parents=True,exist_ok=True)
BASE='https://data.sec.gov'
TICKERS_URL='https://www.sec.gov/files/company_tickers.json'

CONCEPTS={
 'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],
 'net_income':['NetIncomeLoss'],
 'gross_profit':['GrossProfit'],
 'operating_income':['OperatingIncomeLoss'],
 'assets':['Assets'],
 'equity':['StockholdersEquity','StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
 'cash':['CashAndCashEquivalentsAtCarryingValue','CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'],
 'debt':['LongTermDebtAndFinanceLeaseObligationsCurrent','LongTermDebtCurrent','LongTermDebtNoncurrent'],
 'operating_cf':['NetCashProvidedByUsedInOperatingActivities'],
 'capex':['PaymentsToAcquirePropertyPlantAndEquipment'],
 'shares':['CommonStocksIncludingAdditionalPaidInCapitalMember','CommonStockSharesOutstanding'],
 'eps':['EarningsPerShareDiluted','EarningsPerShareBasic'],
}

def _headers():
    return {'User-Agent':settings.sec_user_agent,'Accept-Encoding':'gzip, deflate','Host':'data.sec.gov'}

def _get_json(url:str, host_data=True):
    h=_headers() if host_data else {'User-Agent':settings.sec_user_agent,'Accept-Encoding':'gzip, deflate'}
    with httpx.Client(timeout=45,headers=h,follow_redirects=True) as c:
        r=c.get(url); r.raise_for_status(); return r.json()

def ticker_map(force=False):
    p=CACHE/'ticker_map.json'
    if p.exists() and not force and time.time()-p.stat().st_mtime<7*86400:
        try:return json.loads(p.read_text())
        except Exception:pass
    try:
        raw=_get_json(TICKERS_URL,host_data=False)
        out={v['ticker'].upper():{'cik':str(v['cik_str']).zfill(10),'title':v['title']} for v in raw.values()}
        tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(out));os.replace(tmp,p)
        return out
    except Exception as exc:
        _LAST_DIAGNOSTICS['errors']['ticker_map']=str(exc)
        if p.exists():
            try:return json.loads(p.read_text())
            except Exception:pass
        return {}

def companyfacts(symbol:str, force=False):
    mp=ticker_map(); item=mp.get(symbol.upper().replace('.','-')) or mp.get(symbol.upper())
    if not item:
        _LAST_DIAGNOSTICS['not_found'].add(symbol.upper())
        return None
    p=CACHE/f"{item['cik']}.json";missing=CACHE/f"{item['cik']}.missing"
    if missing.exists() and not force and time.time()-missing.stat().st_mtime<86400:
        _LAST_DIAGNOSTICS['not_found'].add(symbol.upper())
        return None
    if p.exists() and not force and time.time()-p.stat().st_mtime<7*86400:return json.loads(p.read_text())
    try:
        j=_get_json(f"{BASE}/api/xbrl/companyfacts/CIK{item['cik']}.json")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code==404:
            missing.write_text(json.dumps({"symbol":symbol.upper(),"cik":item['cik'],"checked_at":pd.Timestamp.utcnow().isoformat()}))
            _LAST_DIAGNOSTICS['not_found'].add(symbol.upper())
            return None
        _LAST_DIAGNOSTICS['errors'][symbol.upper()]=f"HTTP {exc.response.status_code}"
        raise
    if missing.exists():
        try:missing.unlink()
        except OSError:pass
    p.write_text(json.dumps(j)); time.sleep(.11); return j

def _units_for(fact):
    units=fact.get('units',{})
    for u in ('USD','USD/shares','shares','pure'):
        if u in units:return units[u]
    return next(iter(units.values()),[])

def _concept_rows(usgaap, names, metric):
    for name in names:
        if name not in usgaap:continue
        rows=[]
        for x in _units_for(usgaap[name]):
            if x.get('form') not in ('10-Q','10-K','10-Q/A','10-K/A'):continue
            if not x.get('filed') or x.get('val') is None:continue
            rows.append({'metric':metric,'value':float(x['val']),'period_end':x.get('end'),'available_at':x['filed'],'fy':x.get('fy'),'fp':x.get('fp'),'form':x.get('form'),'accn':x.get('accn')})
        if rows:return rows
    return []

def fundamental_events(symbol:str, force=False):
    j=companyfacts(symbol,force)
    if not j:return pd.DataFrame(columns=['symbol','metric','value','period_end','available_at'])
    us=j.get('facts',{}).get('us-gaap',{}); rows=[]
    for metric,names in CONCEPTS.items(): rows.extend(_concept_rows(us,names,metric))
    if not rows:return pd.DataFrame(columns=['symbol','metric','value','period_end','available_at'])
    df=pd.DataFrame(rows); df['symbol']=symbol; df['available_at']=pd.to_datetime(df.available_at); df['period_end']=pd.to_datetime(df.period_end)
    # Multiple XBRL frames can represent the same filing. Keep latest period for each metric/availability.
    df=df.sort_values(['metric','available_at','period_end']).drop_duplicates(['metric','available_at'],keep='last')
    return df

def point_in_time_panel(symbols, dates, force=False):
    _LAST_DIAGNOSTICS['not_found'].clear();_LAST_DIAGNOSTICS['errors'].clear()
    dates=pd.DatetimeIndex(pd.to_datetime(dates)).sort_values().unique(); parts=[]
    for symbol in symbols:
        try:
            ev=fundamental_events(symbol,force)
        except Exception as exc:
            _LAST_DIAGNOSTICS['errors'][symbol.upper()]=str(exc)
            ev=pd.DataFrame(columns=['symbol','metric','value','period_end','available_at'])
        base=pd.DataFrame({'date':dates})
        if ev.empty:
            base['symbol']=symbol; parts.append(base); continue
        wide=[]
        for metric,g in ev.groupby('metric'):
            x=g[['available_at','value']].sort_values('available_at').rename(columns={'available_at':'date', 'value':metric})
            z=pd.merge_asof(base,x,on='date',direction='backward',allow_exact_matches=True); wide.append(z.set_index('date')[metric])
        w=pd.concat(wide,axis=1).reset_index(); w['symbol']=symbol; parts.append(w)
    out=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
    if out.empty:return out
    # Conservative PIT ratios using only values filed by that date.
    equity_for_roe=out.get('equity',pd.Series(index=out.index,dtype=float)).where(
        out.get('equity',pd.Series(index=out.index,dtype=float)).gt(0)
    )
    out['roe']=out.get('net_income',np.nan)/equity_for_roe.replace(0,np.nan)
    out['roa']=out.get('net_income',np.nan)/out.get('assets',np.nan).replace(0,np.nan)
    out['gross_margin']=out.get('gross_profit',np.nan)/out.get('revenue',np.nan).replace(0,np.nan)
    out['operating_margin']=out.get('operating_income',np.nan)/out.get('revenue',np.nan).replace(0,np.nan)
    capex=out.get('capex',pd.Series(0.0,index=out.index,dtype=float))
    out['fcf']=out.get('operating_cf',np.nan)-capex.fillna(0)
    out['fcf_margin']=out.fcf/out.get('revenue',np.nan).replace(0,np.nan)
    out['debt_assets']=out.get('debt',np.nan)/out.get('assets',np.nan).replace(0,np.nan)

    core_cols=['revenue','net_income','assets','equity','operating_cf']
    core_frame=pd.concat(
        [out.get(name,pd.Series(index=out.index,dtype=float)).rename(name) for name in core_cols],
        axis=1,
    )
    out['sec_core_metrics']=core_frame.notna().sum(axis=1)
    assets=out.get('assets',pd.Series(index=out.index,dtype=float))
    equity=out.get('equity',pd.Series(index=out.index,dtype=float))
    revenue=out.get('revenue',pd.Series(index=out.index,dtype=float))
    net_income=out.get('net_income',pd.Series(index=out.index,dtype=float))
    operating_cf=out.get('operating_cf',pd.Series(index=out.index,dtype=float))
    out['solid_fundamental_eligible']=(
        (out['sec_core_metrics']>=int(settings.real_universe_min_sec_core_metrics))
        &assets.gt(0)
        &equity.notna()
        &equity.gt(-0.50*assets)
        &(revenue.gt(0)|net_income.notna())
        &(
            revenue.ge(float(settings.real_universe_min_revenue))
            |assets.ge(float(settings.real_universe_min_assets))
        )
    ).fillna(False)

    # Composite deliberately excludes valuation until historical shares/market-cap alignment is complete.
    quality=pd.concat([out.roe,out.roa,out.gross_margin,out.operating_margin,out.fcf_margin,-out.debt_assets],axis=1)
    out['fundamental_raw']=quality.replace([np.inf,-np.inf],np.nan).mean(axis=1,skipna=True)
    out['earnings_raw'] = (
    out.get('eps', pd.Series(index=out.index, dtype=float))
    .groupby(out.symbol)
    .pct_change(fill_method=None)
    .replace([np.inf, -np.inf], np.nan)
)
    return out


def diagnostics():
    return {
        "not_found":sorted(_LAST_DIAGNOSTICS["not_found"]),
        "not_found_count":len(_LAST_DIAGNOSTICS["not_found"]),
        "errors":dict(_LAST_DIAGNOSTICS["errors"]),
        "error_count":len(_LAST_DIAGNOSTICS["errors"]),
        "policy":"best_effort",
    }
