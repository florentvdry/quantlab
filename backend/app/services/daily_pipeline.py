from __future__ import annotations
from datetime import datetime, timezone
from app.core.config import settings
from app.services.features import build_feature_panel, panel_metadata, clear_feature_cache
from app.services.data_quality import report
from app.services.dataset_state import set_state, fingerprint

def run_daily_pipeline(db,force_market=False,refresh_sec=False,progress=None):
    progress=progress or (lambda *_:None)
    result={"started_at":datetime.now(timezone.utc).isoformat(),"mode":settings.data_mode,"steps":[]}
    if settings.data_mode.lower()=="alpaca":
        from app.services.real_data import fetch_bars
        progress(15,"Téléchargement des données de marché")
        bars=fetch_bars(force=force_market)
        market={"version":fingerprint({"rows":len(bars),"symbols":int(bars.symbol.nunique()),"max":str(bars.date.max())}),
                "rows":len(bars),"symbols":int(bars.symbol.nunique()),"latest":str(bars.date.max())}
        result["steps"].append({"name":"market_data",**market});set_state(db,"market_data",market)
        if refresh_sec:
            from app.services.real_data import universe
            from app.services.sec_fundamentals import fundamental_events,diagnostics as sec_diagnostics
            syms=universe();covered=events=0;failed=[]
            for i,s in enumerate(syms):
                try:
                    x=fundamental_events(s,force=True);covered+=int(len(x)>0);events+=len(x)
                except Exception as exc:
                    failed.append({"symbol":s,"error":str(exc)})
                if i%3==0:progress(20+int(30*(i+1)/max(1,len(syms))),f"SEC {i+1}/{len(syms)}")
            diag=sec_diagnostics()
            sec={"version":fingerprint({"covered":covered,"events":events}),"symbols":len(syms),"covered":covered,"events":events,
                 "not_found":diag.get("not_found_count",0),"errors":len(failed)+diag.get("error_count",0),"failed":failed[:20],"policy":"best_effort"}
            result["steps"].append({"name":"sec",**sec});set_state(db,"fundamentals",sec)
    progress(55,"Construction du Feature Store")
    clear_feature_cache();panel=build_feature_panel(force=True);meta=panel_metadata(panel);latest=panel.date.max();snap=panel[panel.date==latest]
    state={"version":meta["fingerprint"],"schema":meta["schema"],"rows":len(panel),"latest":str(latest),"symbols":int(snap.symbol.nunique()),"mode":meta["mode"]}
    if settings.data_mode.lower()=="alpaca":
        from app.services.sec_fundamentals import diagnostics as sec_diagnostics
        result["sec_diagnostics"]=sec_diagnostics()
    set_state(db,"features",state);result["steps"].append({"name":"features",**state})
    progress(80,"Contrôle qualité des données")
    dq=report();set_state(db,"data_quality",dq);result["quality"]=dq
    progress(92,"Génération du ranking courant")
    result["ranking"]=[{"symbol":r.symbol,"score":round(float(r.meta_score),4)} for r in snap.sort_values("meta_score",ascending=False).head(20).itertuples()]
    result["completed_at"]=datetime.now(timezone.utc).isoformat()
    return result
