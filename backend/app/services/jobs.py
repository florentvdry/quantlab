from __future__ import annotations
import json, traceback, uuid, threading, time
from datetime import datetime
from redis import Redis
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import JobRun, ExperimentRun, ModelVersion, BacktestRun, SystemState
from app.services.backtest import run_backtest, run_momentum_baseline, run_adaptive_meta, run_meta_v4
from app.services.experiments import parameter_sweep, robustness
from app.services.research import train_walk_forward, factor_summary, run_model_oos_backtest
from app.services.meta_v5 import run_meta_v5, latest_meta_v5_signals, meta_v5_validation_bundle
from app.services.meta_v6 import run_meta_v6, meta_v6_validation_bundle
from app.services.meta_v7 import run_meta_v7, meta_v7_validation_bundle
from app.services.meta_v71 import run_meta_v71, meta_v71_validation_bundle
from app.services.json_utils import safe_dumps

QUEUE="quantlab:jobs"
WORKER_HEARTBEAT="quantlab:worker:heartbeat"
DEDUP_KINDS={"AUTO_BOOTSTRAP","META_V5","META_V6","META_V7","META_V71","META_V5_SIGNALS","VALIDATION","DAILY_PIPELINE","DATA_REFRESH","SEC_REFRESH"}

RESEARCH_JOB_KINDS={
    "BACKTEST","META_V5","META_V6","META_V7","META_V71","V4_BACKTEST","ADAPTIVE_BACKTEST","BASELINE",
    "SWEEP","ROBUSTNESS","RIDGE_BACKTEST","HGB_BACKTEST",
    "TRAIN_RIDGE","TRAIN_HGB","FACTOR_SUMMARY","VALIDATION","META_V5_SIGNALS",
}

def _ensure_research_data(db,row):
    if row.kind not in RESEARCH_JOB_KINDS:
        return
    from app.services.features import feature_store_status
    status=feature_store_status()
    if status.get("ready"):
        return
    from app.services.daily_pipeline import run_daily_pipeline
    def bootstrap_progress(value,message):
        mapped=min(30,max(6,6+int(float(value)*0.24)))
        update(db,row,progress=mapped,result_json=safe_dumps({
            "message":"Préparation des données — "+str(message),
            "feature_store":status,
        },default=str))
    update(db,row,progress=6,result_json=safe_dumps({
        "message":"Feature Store absent/obsolète — reconstruction automatique",
        "feature_store":status,
    },default=str))
    run_daily_pipeline(db,force_market=False,refresh_sec=False,progress=bootstrap_progress)

def redis_client(): return Redis.from_url(settings.redis_url,decode_responses=True)

def enqueue(kind:str,payload:dict|None=None):
    db=SessionLocal(); key=str(uuid.uuid4())
    try:
        if kind in DEDUP_KINDS:
            active=db.query(JobRun).filter(JobRun.kind==kind,JobRun.status.in_(["QUEUED","RUNNING"])).order_by(JobRun.id.desc()).first()
            if active:
                return {"id":active.id,"job_key":active.job_key,"kind":kind,"status":active.status,"deduplicated":True}
        row=JobRun(job_key=key,kind=kind,status="QUEUED",progress=0,payload_json=safe_dumps(payload or {}))
        db.add(row); db.commit(); db.refresh(row)
        redis_client().rpush(QUEUE,key)
        return {"id":row.id,"job_key":key,"kind":kind,"status":"QUEUED","deduplicated":False}
    finally: db.close()

def update(db,row,**kw):
    for k,v in kw.items(): setattr(row,k,v)
    row.updated_at=datetime.utcnow(); db.commit()

def _save_state(db,key,value):
    row=db.query(SystemState).filter(SystemState.key==key).first()
    if not row:
        row=SystemState(key=key,value_json="{}");db.add(row)
    row.value_json=safe_dumps(value,default=str);row.updated_at=datetime.utcnow();db.commit()
    return row

def _persist_meta_model(db,result,name,key):
    last=db.query(ModelVersion).filter(ModelVersion.name==name).order_by(ModelVersion.version.desc()).first()
    mv=ModelVersion(
        name=name,version=(last.version+1 if last else 1),model_type="meta_ensemble",
        metrics_json=safe_dumps(result.get(key,{}),default=str),
        config_json=safe_dumps({"portfolio":result.get("params",{}),"architecture":result.get(key,{}).get("architecture",{})},default=str)
    )
    db.add(mv);db.commit();db.refresh(mv)
    return mv.id

def _persist_meta_v5_model(db,result):
    return _persist_meta_model(db,result,"META_V5","meta_v5")

def _persist_meta_v6_model(db,result):
    return _persist_meta_model(db,result,"META_V6","meta_v6")

def _persist_meta_v7_model(db,result):
    return _persist_meta_model(db,result,"META_V7","meta_v7")

def _persist_meta_v71_model(db,result):
    return _persist_meta_model(db,result,"META_V71","meta_v71")

def _persist_backtest(db,result):
    m=result["metrics"]
    row=BacktestRun(strategy_name=result["strategy"],cagr=m["cagr"],sharpe=m["sharpe"],max_drawdown=m["max_drawdown"],
                    volatility=m["volatility"],turnover=m["avg_turnover_per_rebalance"],payload_json=safe_dumps(result,default=str))
    db.add(row); db.commit(); db.refresh(row)
    return row.id

def execute_job(key:str):
    db=SessionLocal(); row=db.query(JobRun).filter(JobRun.job_key==key).first()
    if not row: db.close(); return
    try:
        update(db,row,status="RUNNING",progress=5,started_at=datetime.utcnow(),result_json=safe_dumps({"message":"Initialisation"}))
        p=json.loads(row.payload_json or "{}")
        _ensure_research_data(db,row)
        if row.kind=="AUTO_BOOTSTRAP":
            from app.services.daily_pipeline import run_daily_pipeline
            from app.services.features import build_feature_panel
            from app.services.validation import validation_report
            update(db,row,progress=6,result_json=safe_dumps({"message":"Autopilot — préparation des données"}))
            def pipeline_progress(value,message):
                mapped=6+int(min(100,max(0,float(value)))*0.24)
                update(db,row,progress=min(30,mapped),result_json=safe_dumps({"message":"Autopilot / Data — "+str(message)}))
            pipeline=run_daily_pipeline(
                db,
                force_market=bool(p.get("force_market",False)),
                refresh_sec=bool(p.get("refresh_sec",False)),
                progress=pipeline_progress,
            )
            panel=build_feature_panel()
            update(db,row,progress=32,result_json=safe_dumps({"message":"Autopilot — Factor Research"}))
            factors=factor_summary(panel);_save_state(db,"research.factor_summary",factors)

            def v5_progress(value,message):
                mapped=36+int(min(100,max(0,float(value)))*0.38)
                update(db,row,progress=min(76,mapped),result_json=safe_dumps({"message":"Autopilot / META V5 — "+str(message)}))
            bundle=meta_v5_validation_bundle(panel=panel,progress=v5_progress)
            candidate=bundle["backtest"]
            candidate["backtest_id"]=_persist_backtest(db,candidate)
            candidate["model_version_id"]=_persist_meta_v5_model(db,candidate)
            update(db,row,progress=78,result_json=safe_dumps({"message":"Autopilot — Validation Gate"}))
            validation=validation_report(p, panel=panel, bundle=bundle)
            _save_state(db,"validation.latest",{"status":"COMPLETED",**validation})

            update(db,row,progress=90,result_json=safe_dumps({"message":"Autopilot — Current signals from continuous walk-forward"}))
            signals=bundle["signals"]
            _save_state(db,"meta_v5.latest_signals",signals)
            result={
                "mode":"AUTO",
                "pipeline":pipeline,
                "factor_research":factors,
                "backtest_id":candidate["backtest_id"],
                "model_version_id":candidate["model_version_id"],
                "validation":{"tier":validation.get("tier"),"passed":validation.get("passed"),"paper_eligible":validation.get("paper_eligible")},
                "signals":{"market_date":signals.get("market_date"),"accepted_count":signals.get("accepted_count"),"paper_execution":signals.get("paper_execution")},
            }
        elif row.kind=="BACKTEST":
            update(db,row,progress=20,result_json=safe_dumps({"message":"Construction des features et du portefeuille"}))
            result=run_backtest(p); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=safe_dumps({"message":"Calcul des métriques"}))
        elif row.kind=="META_V5_SIGNALS":
            def progress_sig(value,message):
                update(db,row,progress=value,result_json=safe_dumps({"message":message}))
            result=latest_meta_v5_signals(progress=progress_sig)
            state=db.query(SystemState).filter(SystemState.key=="meta_v5.latest_signals").first()
            if not state:
                state=SystemState(key="meta_v5.latest_signals",value_json="{}");db.add(state)
            state.value_json=safe_dumps(result,default=str);state.updated_at=datetime.utcnow();db.commit()
            update(db,row,progress=95,result_json=safe_dumps({"message":"META V5 signals saved"}))
        elif row.kind=="META_V5":
            def progress_v5(value,message):
                update(db,row,progress=value,result_json=safe_dumps({"message":message}))
            update(db,row,progress=10,result_json=safe_dumps({"message":"META V5 — continuous walk-forward initialisation"}))
            result=run_meta_v5(params=p,progress=progress_v5)
            result["backtest_id"]=_persist_backtest(db,result)
            result["model_version_id"]=_persist_meta_v5_model(db,result)
            update(db,row,progress=95,result_json=safe_dumps({"message":"META V5 — persistance du modèle et du backtest"}))
        elif row.kind=="META_V6":
            def progress_v6(value,message):
                update(db,row,progress=value,result_json=safe_dumps({"message":message}))
            update(db,row,progress=10,result_json=safe_dumps({"message":"META V6 — target aligné 10j + filtre absolu net"}))
            bundle=meta_v6_validation_bundle(progress=progress_v6)
            result=bundle["backtest"]
            result["meta_v6_validation"]={"robustness":bundle["robustness"],"scenarios":bundle["scenarios"]}
            result["backtest_id"]=_persist_backtest(db,result)
            result["model_version_id"]=_persist_meta_v6_model(db,result)
            update(db,row,progress=95,result_json=safe_dumps({"message":"META V6 — challenger persisté; compare au V5 dans Backtests"}))
        elif row.kind=="META_V7":
            def progress_v7(value,message):
                update(db,row,progress=value,result_json=safe_dumps({"message":message}))
            update(db,row,progress=10,result_json=safe_dumps({"message":"META V7 — diversification corrélation + volatility scaling"}))
            bundle=meta_v7_validation_bundle(progress=progress_v7)
            result=bundle["backtest"]
            result["meta_v7_validation"]={"robustness":bundle["robustness"],"scenarios":bundle["scenarios"]}
            result["backtest_id"]=_persist_backtest(db,result)
            result["model_version_id"]=_persist_meta_v7_model(db,result)
            update(db,row,progress=95,result_json=safe_dumps({"message":"META V7 — risk challenger persisté; compare au V6 dans Backtests"}))
        elif row.kind=="META_V71":
            def progress_v71(value,message):
                update(db,row,progress=value,result_json=safe_dumps({"message":message}))
            update(db,row,progress=10,result_json=safe_dumps({"message":"META V7.1 — balanced exposure sur alpha/risk V7"}))
            bundle=meta_v71_validation_bundle(progress=progress_v71)
            result=bundle["backtest"]
            result["meta_v71_validation"]={"robustness":bundle["robustness"],"scenarios":bundle["scenarios"]}
            result["backtest_id"]=_persist_backtest(db,result)
            result["model_version_id"]=_persist_meta_v71_model(db,result)
            update(db,row,progress=95,result_json=safe_dumps({"message":"META V7.1 — balanced exposure persisté; compare au V7"}))
        elif row.kind=="V4_BACKTEST":
            update(db,row,progress=20,result_json=safe_dumps({"message":"META V4 — long-only, low-turnover, no historical news leakage"}))
            result=run_meta_v4(); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=safe_dumps({"message":"Benchmark equal-weight et audit des coûts"}))
        elif row.kind=="ADAPTIVE_BACKTEST":
            update(db,row,progress=20,result_json=safe_dumps({"message":"Adaptive META V3 — poids train-only"}))
            result=run_adaptive_meta(p); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=safe_dumps({"message":"Audit ledger et métriques"}))
        elif row.kind=="BASELINE":
            update(db,row,progress=20,result_json=safe_dumps({"message":"Baseline momentum 12-1"}))
            result=run_momentum_baseline(p); result["backtest_id"]=_persist_backtest(db,result)
        elif row.kind=="SWEEP":
            update(db,row,progress=10,result_json=safe_dumps({"message":"Parameter sweep"}))
            result=parameter_sweep(p.get("base",{}),p.get("grid",{}))
            exp=ExperimentRun(name="Parameter Sweep",kind="SWEEP",status="COMPLETED",payload_json=safe_dumps(result,default=str));db.add(exp);db.commit()
            result={"experiment_id":exp.id,**result}
        elif row.kind=="ROBUSTNESS":
            update(db,row,progress=10,result_json=safe_dumps({"message":"Robustness suite"}))
            result=robustness(p)
            exp=ExperimentRun(name="Robustness Suite",kind="ROBUSTNESS",status="COMPLETED",payload_json=safe_dumps(result,default=str));db.add(exp);db.commit()
            result={"experiment_id":exp.id,**result}
        elif row.kind in ("RIDGE_BACKTEST","HGB_BACKTEST"):
            model="ridge" if row.kind=="RIDGE_BACKTEST" else "hgb"
            update(db,row,progress=20,result_json=safe_dumps({"message":"Backtest OOS "+model.upper()+" avec embargo 20 jours"}))
            result=run_model_oos_backtest(model,p); result["backtest_id"]=_persist_backtest(db,result)
            update(db,row,progress=90,result_json=safe_dumps({"message":"Audit ledger et métriques OOS"}))
        elif row.kind in ("TRAIN_RIDGE","TRAIN_HGB"):
            model="ridge" if row.kind=="TRAIN_RIDGE" else "hgb"
            update(db,row,progress=15,result_json=safe_dumps({"message":"Walk-forward "+model.upper()}))
            result=train_walk_forward(model)
            last=db.query(ModelVersion).filter(ModelVersion.name==model.upper()).order_by(ModelVersion.version.desc()).first()
            mv=ModelVersion(name=model.upper(),version=(last.version+1 if last else 1),model_type=model,metrics_json=safe_dumps(result,default=str))
            db.add(mv);db.commit();result={"model_version_id":mv.id,**result}
        elif row.kind=="FACTOR_SUMMARY":
            update(db,row,progress=20,result_json=safe_dumps({"message":"Calcul des IC cross-sectionnels"})); result=factor_summary();_save_state(db,"research.factor_summary",result)
        elif row.kind=="VALIDATION":
            from app.services.validation import validation_report
            update(db,row,progress=15,result_json=safe_dumps({"message":"META V5 validation gate"})); result=validation_report(p);_save_state(db,"validation.latest",{"status":"COMPLETED",**result})
        elif row.kind=="DATA_REFRESH":
            from app.services.real_data import fetch_bars
            update(db,row,progress=20,result_json=safe_dumps({"message":"Téléchargement des barres Alpaca"}))
            df=fetch_bars(force=True); result={"rows":len(df),"symbols":int(df.symbol.nunique()),"from":str(df.date.min()),"to":str(df.date.max())}
        elif row.kind=="DAILY_PIPELINE":
            from app.services.daily_pipeline import run_daily_pipeline
            def progress(value,message):
                update(db,row,progress=value,result_json=safe_dumps({"message":message}))
            result=run_daily_pipeline(db,force_market=bool(p.get("force_market")),refresh_sec=bool(p.get("refresh_sec")),progress=progress)
        elif row.kind=="PAPER_SNAPSHOT":
            from app.services.monitoring import snapshot_paper
            result=snapshot_paper(db)
        elif row.kind=="SEC_REFRESH":
            from app.services.real_data import universe
            from app.services.sec_fundamentals import fundamental_events,diagnostics as sec_diagnostics
            syms=universe();covered=events=0;failed=[]
            for i,s in enumerate(syms):
                try:
                    d=fundamental_events(s,force=True);events+=len(d);covered+=int(len(d)>0)
                except Exception as exc:
                    failed.append({"symbol":s,"error":str(exc)})
                if i%3==0:update(db,row,progress=min(90,10+int(80*(i+1)/max(1,len(syms)))),result_json=safe_dumps({"message":f"SEC {i+1}/{len(syms)}"}))
            diag=sec_diagnostics()
            result={"symbols":len(syms),"covered":covered,"events":events,"not_found":diag.get("not_found_count",0),"errors":len(failed)+diag.get("error_count",0),"failed":failed[:20],"policy":"best_effort"}
        else: raise ValueError(f"Unknown job kind {row.kind}")
        update(db,row,status="COMPLETED",progress=100,result_json=safe_dumps(result,default=str),completed_at=datetime.utcnow())
    except Exception as e:
        update(db,row,status="FAILED",error=str(e),result_json=safe_dumps({"message":"Échec","traceback":traceback.format_exc()}),completed_at=datetime.utcnow())
    finally: db.close()

def _heartbeat_loop():
    while True:
        try:
            redis_client().setex(WORKER_HEARTBEAT,20,datetime.utcnow().isoformat())
        except Exception:
            pass
        time.sleep(5)

def worker_loop():
    r=redis_client()
    threading.Thread(target=_heartbeat_loop,daemon=True,name="quantlab-heartbeat").start()
    print("QuantLab worker ready",flush=True)
    while True:
        item=r.blpop(QUEUE,timeout=5)
        if item:
            execute_job(item[1])
