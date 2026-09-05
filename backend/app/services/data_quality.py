from __future__ import annotations
import os, pandas as pd
from app.core.config import settings
from app.services.features import build_feature_panel

def report():
    df=build_feature_panel(); latest=pd.Timestamp(df.date.max()); snap=df[df.date==latest]
    checks=[]
    def add(name,ok,detail,severity='critical'):checks.append({'name':name,'ok':bool(ok),'detail':detail,'severity':severity})
    add('market_data_present',len(df)>0,f'{len(df):,} feature rows')
    add('universe_size',snap.symbol.nunique()>=20,f'{snap.symbol.nunique()} symbols on latest date')
    add('latest_features',len(snap)>0,f'latest={latest.date()}')
    add('finite_scores',snap.meta_score.notna().mean()>.98,f'{snap.meta_score.notna().mean()*100:.1f}% scores available')
    if settings.data_mode.lower()=='alpaca':
        add('alpaca_keys',bool(settings.alpaca_api_key and settings.alpaca_secret_key),'credentials configured')
        add('sec_user_agent',settings.sec_user_agent!='QuantLab local research contact@example.com','set a real contact in SEC_USER_AGENT','warning')
        add('fundamentals_coverage',snap.fundamental_raw.ne(0).mean()>.50,f'{snap.fundamental_raw.ne(0).mean()*100:.1f}% non-neutral PIT fundamentals','warning')
    critical_ok=all(x['ok'] for x in checks if x['severity']=='critical')
    return {'status':'PASS' if critical_ok else 'BLOCK','data_mode':settings.data_mode,'latest_date':str(latest.date()),'checks':checks}
