from __future__ import annotations
from datetime import datetime, timezone
from app.core.config import settings
from app.services.features import build_feature_panel, panel_metadata
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
            from app.services.sec_fundamentals import fundamental_events
            syms=universe();covered=events=0
            for i,s in enumerate(syms):
                x=fundamental_events(s,force=True);covered+=int(len(x)>0);events+=len(x)
                if i%3==0:progress(20+int(30*(i+1)/max(1,len(syms))),f"SEC {i+1}/{len(syms)}")
            sec={"version":fingerprint({"covered":covered,"events":events}),"symbols":len(syms),"covered":covered,"events":events}
            result["steps"].append({"name":"sec",**sec});set_state(db,"fundamentals",sec)
    progress(55,"Construction du Feature Store")
    panel=build_feature_panel();meta=panel_metadata(panel);latest=panel.date.max();snap=panel[panel.date==latest]
    state={"version":meta["fingerprint"],"schema":meta["schema"],"rows":len(panel),"latest":str(latest),"symbols":int(snap.symbol.nunique()),"mode":meta["mode"]}
    set_state(db,"features",state);result["steps"].append({"name":"features",**state})
    progress(80,"Contrôle qualité des données")
    dq=report();set_state(db,"data_quality",dq);result["quality"]=dq
    progress(92,"Génération du ranking courant")
    result["ranking"]=[{"symbol":r.symbol,"score":round(float(r.meta_score),4)} for r in snap.sort_values("meta_score",ascending=False).head(20).itertuples()]
    result["completed_at"]=datetime.now(timezone.utc).isoformat()
    return result
