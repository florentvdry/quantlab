from __future__ import annotations
from datetime import datetime, timezone
from app.core.config import settings
from app.services.features import build_feature_panel
from app.services.data_quality import report
from app.services.dataset_state import set_state, fingerprint


def run_daily_pipeline(db, force_market=False, refresh_sec=False):
    result={'started_at':datetime.now(timezone.utc).isoformat(),'mode':settings.data_mode,'steps':[]}
    if settings.data_mode.lower()=='alpaca':
        from app.services.real_data import fetch_bars
        bars=fetch_bars(force=force_market)
        result['steps'].append({'name':'market_data','rows':len(bars),'symbols':int(bars.symbol.nunique())})
        set_state(db,'market_data',{'version':fingerprint({'rows':len(bars),'symbols':int(bars.symbol.nunique()),'max':str(bars.date.max())}),'rows':len(bars),'symbols':int(bars.symbol.nunique()),'latest':str(bars.date.max())})
        if refresh_sec:
            from app.services.real_data import universe
            from app.services.sec_fundamentals import fundamental_events
            syms=universe(); covered=events=0
            for s in syms:
                x=fundamental_events(s,force=True); covered+=int(len(x)>0); events+=len(x)
            result['steps'].append({'name':'sec','symbols':len(syms),'covered':covered,'events':events})
            set_state(db,'fundamentals',{'version':fingerprint({'covered':covered,'events':events}),'symbols':len(syms),'covered':covered,'events':events})
    panel=build_feature_panel()
    latest=panel.date.max(); snap=panel[panel.date==latest]
    set_state(db,'features',{'version':fingerprint({'rows':len(panel),'latest':str(latest),'symbols':int(snap.symbol.nunique())}),'rows':len(panel),'latest':str(latest),'symbols':int(snap.symbol.nunique())})
    result['steps'].append({'name':'features','rows':len(panel),'latest':str(latest),'symbols':int(snap.symbol.nunique())})
    dq=report(); set_state(db,'data_quality',dq); result['quality']=dq
    result['completed_at']=datetime.now(timezone.utc).isoformat(); return result
