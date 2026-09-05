from __future__ import annotations
import json, os, time
from pathlib import Path
import httpx, numpy as np, pandas as pd
from app.core.config import settings

CACHE=Path('/data/sec'); CACHE.mkdir(parents=True,exist_ok=True)
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
    if p.exists() and not force and time.time()-p.stat().st_mtime<7*86400: return json.loads(p.read_text())
    raw=_get_json(TICKERS_URL,host_data=False)
    out={v['ticker'].upper():{'cik':str(v['cik_str']).zfill(10),'title':v['title']} for v in raw.values()}
    p.write_text(json.dumps(out)); return out

def companyfacts(symbol:str, force=False):
    mp=ticker_map(); item=mp.get(symbol.upper().replace('.','-')) or mp.get(symbol.upper())
    if not item:return None
    p=CACHE/f"{item['cik']}.json"
    if p.exists() and not force and time.time()-p.stat().st_mtime<7*86400:return json.loads(p.read_text())
    j=_get_json(f"{BASE}/api/xbrl/companyfacts/CIK{item['cik']}.json")
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
    dates=pd.DatetimeIndex(pd.to_datetime(dates)).sort_values().unique(); parts=[]
    for symbol in symbols:
        ev=fundamental_events(symbol,force)
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
    out['roe']=out.get('net_income',np.nan)/out.get('equity',np.nan).replace(0,np.nan)
    out['roa']=out.get('net_income',np.nan)/out.get('assets',np.nan).replace(0,np.nan)
    out['gross_margin']=out.get('gross_profit',np.nan)/out.get('revenue',np.nan).replace(0,np.nan)
    out['operating_margin']=out.get('operating_income',np.nan)/out.get('revenue',np.nan).replace(0,np.nan)
    out['fcf']=out.get('operating_cf',np.nan)-out.get('capex',0).fillna(0)
    out['fcf_margin']=out.fcf/out.get('revenue',np.nan).replace(0,np.nan)
    out['debt_assets']=out.get('debt',np.nan)/out.get('assets',np.nan).replace(0,np.nan)
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
