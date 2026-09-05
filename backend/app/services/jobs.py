from __future__ import annotations
import json, traceback, uuid
from datetime import datetime
from redis import Redis
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import JobRun, ExperimentRun, ModelVersion, BacktestRun, SystemState
from app.services.backtest import run_backtest, run_momentum_baseline, run_adaptive_meta, run_meta_v4
from app.services.experiments import parameter_sweep, robustness
from app.services.research import train_walk_forward, factor_summary, run_model_oos_backtest
from app.services.meta_v5 import run_meta_v5, latest_meta_v5_signals

QUEUE="quantlab:jobs"

def redis_client(): return Redis.from_url(settings.redis_url,decode_responses=True)

def enqueue(kind:str,payload:dict|None=None):
    db=SessionLocal(); key=str(uuid.uuid4())
    try:
        row=JobRun(job_key=key,kind=kind,status="QUEUED",progress=0,payload_json=json.dumps(payload or {}))
        db.add(row); db.commit(); db.refresh(row)
        redis_client().rpush(QUEUE,key)
        return {"id":row.id,"job_key":key,"kind":kind,"status":"QUEUED"}
    finally: db.close()

def update(db,row,**kw):
    for k,v in kw.items(): setattr(row,k,v)
    row.updated_at=datetime.utcnow(); db.commit()

def _persist_backtest(db,result):
    m=result["metrics"]
    row=BacktestRun(strategy_name=result["strategy"],cagr=m["cagr"],sharpe=m["sharpe"],max_drawdown=m["max_drawdown"],
                    volatility=m["volatility"],turnover=m["avg_turnover_per_rebalance"],payload_json=json.dumps(result,default=str))
    db.add(row); db.commit(); db.refresh(row)
    return row.id

def execute_job(key:str):
    db=SessionLocal(); row=db.query(JobRun).filter(JobRun.job_key==key).first()
    if not row: db.close(); return
    try:
        update(db,row,status="RUNNING",progress=5,started_at=datetime.utcnow(),result_json=json.dumps({"message":"Initialisation"}))
        p=json.loads(row.payload_json or "{}")
        if row.kind=="BACKTEST":
            update(db,row,progress=20,result_json=json.dumps({"message":"Construction des features et du portefeuille"}))
            result=run_backtest(p); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=json.dumps({"message":"Calcul des métriques"}))
        elif row.kind=="META_V5_SIGNALS":
            def progress_sig(value,message):
                update(db,row,progress=value,result_json=json.dumps({"message":message}))
            result=latest_meta_v5_signals(progress=progress_sig)
            state=db.query(SystemState).filter(SystemState.key=="meta_v5.latest_signals").first()
            if not state:
                state=SystemState(key="meta_v5.latest_signals",value_json="{}");db.add(state)
            state.value_json=json.dumps(result,default=str);state.updated_at=datetime.utcnow();db.commit()
            update(db,row,progress=95,result_json=json.dumps({"message":"META V5 signals saved"}))
        elif row.kind=="META_V5":
            def progress_v5(value,message):
                update(db,row,progress=value,result_json=json.dumps({"message":message}))
            update(db,row,progress=10,result_json=json.dumps({"message":"META V5 — nested walk-forward initialisation"}))
            result=run_meta_v5(params=p,progress=progress_v5)
            result["backtest_id"]=_persist_backtest(db,result)
            last=db.query(ModelVersion).filter(ModelVersion.name=="META_V5").order_by(ModelVersion.version.desc()).first()
            mv=ModelVersion(
                name="META_V5",version=(last.version+1 if last else 1),model_type="meta_ensemble",
                metrics_json=json.dumps(result.get("meta_v5",{}),default=str),
                config_json=json.dumps({"portfolio":result.get("params",{}),"architecture":result.get("meta_v5",{}).get("architecture",{})},default=str)
            )
            db.add(mv);db.commit();db.refresh(mv)
            result["model_version_id"]=mv.id
            update(db,row,progress=95,result_json=json.dumps({"message":"META V5 — persistance du modèle et du backtest"}))
        elif row.kind=="V4_BACKTEST":
            update(db,row,progress=20,result_json=json.dumps({"message":"META V4 — long-only, low-turnover, no historical news leakage"}))
            result=run_meta_v4(); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=json.dumps({"message":"Benchmark equal-weight et audit des coûts"}))
        elif row.kind=="ADAPTIVE_BACKTEST":
            update(db,row,progress=20,result_json=json.dumps({"message":"Adaptive META V3 — poids train-only"}))
            result=run_adaptive_meta(p); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=json.dumps({"message":"Audit ledger et métriques"}))
        elif row.kind=="BASELINE":
            update(db,row,progress=20,result_json=json.dumps({"message":"Baseline momentum 12-1"}))
            result=run_momentum_baseline(p); result["backtest_id"]=_persist_backtest(db,result)
        elif row.kind=="SWEEP":
            update(db,row,progress=10,result_json=json.dumps({"message":"Parameter sweep"}))
            result=parameter_sweep(p.get("base",{}),p.get("grid",{}))
            exp=ExperimentRun(name="Parameter Sweep",kind="SWEEP",status="COMPLETED",payload_json=json.dumps(result,default=str));db.add(exp);db.commit()
            result={"experiment_id":exp.id,**result}
        elif row.kind=="ROBUSTNESS":
            update(db,row,progress=10,result_json=json.dumps({"message":"Robustness suite"}))
            result=robustness(p)
            exp=ExperimentRun(name="Robustness Suite",kind="ROBUSTNESS",status="COMPLETED",payload_json=json.dumps(result,default=str));db.add(exp);db.commit()
            result={"experiment_id":exp.id,**result}
        elif row.kind in ("RIDGE_BACKTEST","HGB_BACKTEST"):
            model="ridge" if row.kind=="RIDGE_BACKTEST" else "hgb"
            update(db,row,progress=20,result_json=json.dumps({"message":"Backtest OOS "+model.upper()+" avec embargo 20 jours"}))
            result=run_model_oos_backtest(model,p); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=json.dumps({"message":"Audit ledger et métriques OOS"}))
        elif row.kind in ("TRAIN_RIDGE","TRAIN_HGB"):
            model="ridge" if row.kind=="TRAIN_RIDGE" else "hgb"
            update(db,row,progress=15,result_json=json.dumps({"message":"Walk-forward "+model.upper()}))
            result=train_walk_forward(model)
            last=db.query(ModelVersion).filter(ModelVersion.name==model.upper()).order_by(ModelVersion.version.desc()).first()
            mv=ModelVersion(name=model.upper(),version=(last.version+1 if last else 1),model_type=model,metrics_json=json.dumps(result,default=str))
            db.add(mv);db.commit();result={"model_version_id":mv.id,**result}
        elif row.kind=="FACTOR_SUMMARY":
            update(db,row,progress=20,result_json=json.dumps({"message":"Calcul des IC cross-sectionnels"})); result=factor_summary()
        elif row.kind=="VALIDATION":
            from app.services.validation import validation_report
            update(db,row,progress=15,result_json=json.dumps({"message":"META V5 validation gate"})); result=validation_report(p)
        elif row.kind=="DATA_REFRESH":
            from app.services.real_data import fetch_bars
            update(db,row,progress=20,result_json=json.dumps({"message":"Téléchargement des barres Alpaca"}))
            df=fetch_bars(force=True); result={"rows":len(df),"symbols":int(df.symbol.nunique()),"from":str(df.date.min()),"to":str(df.date.max())}
        elif row.kind=="DAILY_PIPELINE":
            from app.services.daily_pipeline import run_daily_pipeline
            def progress(value,message):
                update(db,row,progress=value,result_json=json.dumps({"message":message}))
            result=run_daily_pipeline(db,force_market=bool(p.get("force_market")),refresh_sec=bool(p.get("refresh_sec")),progress=progress)
        elif row.kind=="PAPER_SNAPSHOT":
            from app.services.monitoring import snapshot_paper
            result=snapshot_paper(db)
        elif row.kind=="SEC_REFRESH":
            from app.services.real_data import universe
            from app.services.sec_fundamentals import fundamental_events
            syms=universe();covered=events=0
            for i,s in enumerate(syms):
                d=fundamental_events(s,force=True);events+=len(d);covered+=int(len(d)>0)
                if i%3==0:update(db,row,progress=min(90,10+int(80*(i+1)/max(1,len(syms)))),result_json=json.dumps({"message":f"SEC {i+1}/{len(syms)}"}))
            result={"symbols":len(syms),"covered":covered,"events":events}
        else: raise ValueError(f"Unknown job kind {row.kind}")
        update(db,row,status="COMPLETED",progress=100,result_json=json.dumps(result,default=str),completed_at=datetime.utcnow())
    except Exception as e:
        update(db,row,status="FAILED",error=str(e),result_json=json.dumps({"message":"Échec","traceback":traceback.format_exc()}),completed_at=datetime.utcnow())
    finally: db.close()

def worker_loop():
    r=redis_client(); print("QuantLab worker ready",flush=True)
    while True:
        item=r.blpop(QUEUE,timeout=5)
        if item: execute_job(item[1])
