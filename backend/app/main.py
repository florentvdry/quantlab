from __future__ import annotations
import json
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from redis import Redis

from app.db.session import Base,engine,get_db
from app.models.entities import BacktestRun,PaperPosition,ExecutionLog,RebalanceRun,BrokerOrder,StrategyVersion,ModelVersion,ExperimentRun,JobRun,TradeFill,SystemState
from app.core.config import settings
from app.services.backtest import run_backtest
from app.services.broker import PaperBrokerService
from app.services.features import build_feature_panel,panel_metadata
from app.services.execution import ExecutionService
from app.services.jobs import enqueue
from app.services.monitoring import snapshot_paper,paper_history,compare_paper_backtest,promotion_gate

app=FastAPI(title="Quant Lab V1",version="1.1.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)

@app.exception_handler(RuntimeError)
async def runtime_error_handler(_:Request,exc:RuntimeError):
    return JSONResponse(status_code=503,content={"detail":{"code":"RUNTIME_DEPENDENCY_ERROR","message":str(exc)}})

class BacktestRequest(BaseModel):
    long_count:int=Field(20,ge=1,le=50);short_count:int=Field(20,ge=1,le=50);rebalance_days:int=Field(5,ge=1,le=21)
    commission_bps:float=Field(6,ge=0,le=100);slippage_bps:float=Field(5,ge=0,le=100);gross_exposure:float=Field(2,ge=.2,le=2)
    initial_capital:float=Field(100000,ge=100,le=100000000);adaptive_lookback_days:int=Field(252,ge=126,le=756)
class StrategyCreate(BaseModel):
    name:str="META US";config:dict={}
class ExperimentRequest(BaseModel):
    base:BacktestRequest=BacktestRequest();grid:dict={"long_count":[10,20,30],"short_count":[10,20,30],"rebalance_days":[5,10,21]}

@app.get("/health")
def health():
    return {"status":"ok","version":"1.1.0"}

@app.get("/ready")
def ready(db:Session=Depends(get_db)):
    checks={}
    try: db.execute(text("SELECT 1"));checks["postgres"]=True
    except Exception as e: checks["postgres"]=str(e)
    try: checks["redis"]=bool(Redis.from_url(settings.redis_url).ping())
    except Exception as e: checks["redis"]=str(e)
    return JSONResponse(status_code=200 if all(v is True for v in checks.values()) else 503,content={"ready":all(v is True for v in checks.values()),"checks":checks})

@app.get("/api/system/status")
def system_status():
    return {"data_mode":settings.data_mode,"alpaca_configured":bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            "paper_orders_enabled":settings.allow_alpaca_paper_orders,"paper_auto_enabled":settings.paper_auto_enabled,
            "trading_env":settings.trading_env,"live_trading_supported":False}

@app.get("/api/setup")
def setup(db:Session=Depends(get_db)):
    from app.services.dataset_state import states
    s=states(db);alpaca=bool(settings.alpaca_api_key and settings.alpaca_secret_key)
    steps=[
        {"name":"Market Data","ok":settings.data_mode=="synthetic" or alpaca,"detail":settings.data_mode},
        {"name":"Historical Dataset","ok":"market_data" in s or settings.data_mode=="synthetic","detail":s.get("market_data")},
        {"name":"Feature Store","ok":"features" in s,"detail":s.get("features")},
        {"name":"Data Quality","ok":s.get("data_quality",{}).get("status")=="PASS","detail":s.get("data_quality")},
        {"name":"Strategy","ok":db.query(StrategyVersion).count()>0,"detail":db.query(StrategyVersion).count()},
        {"name":"Paper Trading","ok":bool(db.query(StrategyVersion).filter(StrategyVersion.status=="PAPER").first()),"detail":"locked unless validated"},
    ]
    return {"steps":steps,"research_unlocked":all(x["ok"] for x in steps[:4]),"paper_locked":not steps[-1]["ok"] or not settings.allow_alpaca_paper_orders}

@app.get("/api/dashboard")
def dashboard(db:Session=Depends(get_db)):
    broker=PaperBrokerService(db).sync_account();last=db.query(BacktestRun).order_by(BacktestRun.id.desc()).first()
    return {"broker":broker,"last_backtest":None if not last else _bt_summary(last),"paper_positions":db.query(PaperPosition).count(),"mode":"PAPER"}

def _bt_summary(r):
    dataset={}
    try: dataset=json.loads(r.payload_json).get("dataset",{})
    except Exception: pass
    return {"id":r.id,"strategy":r.strategy_name,"created_at":r.created_at,"cagr":r.cagr,"sharpe":r.sharpe,
            "max_drawdown":r.max_drawdown,"volatility":r.volatility,"turnover":r.turnover,"dataset":dataset}

@app.get("/api/backtests")
def list_backtests(db:Session=Depends(get_db)):
    return [_bt_summary(r) for r in db.query(BacktestRun).order_by(BacktestRun.id.desc()).limit(50).all()]

@app.get("/api/backtests/{run_id}")
def get_backtest(run_id:int,db:Session=Depends(get_db)):
    r=db.get(BacktestRun,run_id)
    if not r: raise HTTPException(404,"Backtest not found")
    return {"id":r.id,**json.loads(r.payload_json)}

@app.post("/api/backtests")
def create_backtest(req:BacktestRequest,db:Session=Depends(get_db)):
    result=run_backtest(req.model_dump());m=result["metrics"]
    row=BacktestRun(strategy_name=result["strategy"],cagr=m["cagr"],sharpe=m["sharpe"],max_drawdown=m["max_drawdown"],volatility=m["volatility"],
                    turnover=m["avg_turnover_per_rebalance"],payload_json=json.dumps(result,default=str))
    db.add(row);db.commit();db.refresh(row);return {"id":row.id,**result}

@app.get("/api/factors/latest")
def factors_latest():
    df=build_feature_panel();snap=df[df.date==df.date.max()].sort_values("meta_score",ascending=False)
    cols=["symbol","sector","meta_score","momentum_12_1_rank","fundamental_raw_rank","earnings_raw_rank","news_raw_rank","low_vol_rank","liquidity_rank"]
    return snap[cols].head(100).round(4).to_dict("records")

@app.get("/api/factors/{symbol}/explain")
def factor_explain(symbol:str):
    from app.services.explainability import explain_symbol
    try:return explain_symbol(symbol)
    except ValueError as e:raise HTTPException(404,str(e))

@app.get("/api/research/factors")
def factors_summary():
    from app.services.research import factor_summary
    return factor_summary()

@app.get("/api/research/factors/{feature}")
def research_factor(feature:str):
    from app.services.research import factor_report
    try:return factor_report(feature)
    except ValueError as e:raise HTTPException(400,str(e))

@app.get("/api/research/correlations")
def research_correlations():
    from app.services.research import correlations
    return correlations()

@app.get("/api/data/quality")
def data_quality():
    from app.services.data_quality import report
    return report()

@app.get("/api/validation/latest")
def validation_latest(db:Session=Depends(get_db)):
    r=db.query(JobRun).filter(JobRun.kind=="VALIDATION",JobRun.status=="COMPLETED").order_by(JobRun.id.desc()).first()
    if not r:return {"status":"NOT_RUN","passed":False}
    return {"status":"COMPLETED",**json.loads(r.result_json or "{}")}

@app.get("/api/meta-v5/signals")
def meta_v5_signals(db:Session=Depends(get_db)):
    row=db.query(SystemState).filter(SystemState.key=="meta_v5.latest_signals").first()
    if not row:return {"status":"NOT_RUN","signals":[],"accepted_signals":[]}
    return json.loads(row.value_json or "{}")

@app.get("/api/system/datasets")
def datasets(db:Session=Depends(get_db)):
    from app.services.dataset_state import states
    return states(db)

@app.get("/api/dataset/current")
def dataset_current():
    return panel_metadata()

@app.get("/api/models")
def models(db:Session=Depends(get_db)):
    rows=db.query(ModelVersion).order_by(ModelVersion.id.desc()).all()
    return [{"id":r.id,"name":r.name,"version":r.version,"type":r.model_type,"status":r.status,"metrics":json.loads(r.metrics_json),"created_at":r.created_at} for r in rows]

@app.get("/api/experiments")
def experiments(db:Session=Depends(get_db)):
    rows=db.query(ExperimentRun).order_by(ExperimentRun.id.desc()).limit(50).all()
    return [{"id":r.id,"name":r.name,"kind":r.kind,"status":r.status,"created_at":r.created_at} for r in rows]

@app.get("/api/strategies")
def strategies(db:Session=Depends(get_db)):
    rows=db.query(StrategyVersion).order_by(StrategyVersion.id.desc()).all()
    return [{"id":r.id,"name":r.name,"version":r.version,"status":r.status,"config":json.loads(r.config_json),"created_at":r.created_at} for r in rows]

@app.post("/api/strategies")
def create_strategy(req:StrategyCreate,db:Session=Depends(get_db)):
    last=db.query(StrategyVersion).filter(StrategyVersion.name==req.name).order_by(StrategyVersion.version.desc()).first()
    row=StrategyVersion(name=req.name,version=(last.version+1 if last else 1),config_json=json.dumps(req.config));db.add(row);db.commit();db.refresh(row)
    return {"id":row.id,"name":row.name,"version":row.version,"status":row.status}

@app.get("/api/strategies/{strategy_id}/promotion-gate")
def strategy_gate(strategy_id:int,db:Session=Depends(get_db)):
    g=promotion_gate(db,strategy_id)
    if not g:raise HTTPException(404,"Strategy not found")
    return g

@app.post("/api/strategies/{strategy_id}/promote")
def promote(strategy_id:int,db:Session=Depends(get_db)):
    row=db.get(StrategyVersion,strategy_id)
    if not row:raise HTTPException(404,"Strategy not found")
    g=promotion_gate(db,strategy_id)
    if not g["passed"]:raise HTTPException(400,{"message":"Promotion blocked","gate":g})
    db.query(StrategyVersion).filter(StrategyVersion.status=="PAPER").update({StrategyVersion.status:"ARCHIVED"})
    row.status="PAPER";db.commit();return {"id":row.id,"status":row.status,"gate":g}

@app.post("/api/jobs/backtest")
def job_backtest(req:BacktestRequest):return enqueue("BACKTEST",req.model_dump())
@app.post("/api/jobs/meta-v5")
def job_meta_v5(req:BacktestRequest):return enqueue("META_V5",req.model_dump())
@app.post("/api/jobs/meta-v5-signals")
def job_meta_v5_signals():return enqueue("META_V5_SIGNALS",{})
@app.post("/api/jobs/v4-backtest")
def job_v4_backtest():return enqueue("V4_BACKTEST",{})
@app.post("/api/jobs/adaptive-backtest")
def job_adaptive_backtest(req:BacktestRequest):return enqueue("ADAPTIVE_BACKTEST",req.model_dump())
@app.post("/api/jobs/baseline")
def job_baseline(req:BacktestRequest):return enqueue("BASELINE",req.model_dump())
@app.post("/api/jobs/sweep")
def job_sweep(req:ExperimentRequest):return enqueue("SWEEP",{"base":req.base.model_dump(),"grid":req.grid})
@app.post("/api/jobs/robustness")
def job_robustness(req:BacktestRequest):return enqueue("ROBUSTNESS",req.model_dump())
@app.post("/api/jobs/model-backtest/{model}")
def job_model_backtest(model:str,req:BacktestRequest):
    if model not in ("ridge","hgb"):raise HTTPException(400,"model must be ridge or hgb")
    return enqueue(("RIDGE_BACKTEST" if model=="ridge" else "HGB_BACKTEST"),req.model_dump())
@app.post("/api/jobs/train/{model}")
def job_train(model:str):
    if model not in ("ridge","hgb"):raise HTTPException(400,"model must be ridge or hgb")
    return enqueue("TRAIN_"+model.upper(),{})
@app.post("/api/jobs/factor-summary")
def job_factor_summary():return enqueue("FACTOR_SUMMARY",{})
@app.post("/api/jobs/validation")
def job_validation(req:BacktestRequest):return enqueue("VALIDATION",req.model_dump())
@app.post("/api/jobs/data-refresh")
def job_data_refresh():return enqueue("DATA_REFRESH",{})
@app.post("/api/jobs/sec-refresh")
def job_sec_refresh():return enqueue("SEC_REFRESH",{})
@app.post("/api/jobs/daily-pipeline")
def job_daily_pipeline(force_market:bool=False,refresh_sec:bool=False):return enqueue("DAILY_PIPELINE",{"force_market":force_market,"refresh_sec":refresh_sec})
@app.post("/api/jobs/paper-snapshot")
def job_paper_snapshot():return enqueue("PAPER_SNAPSHOT",{})

@app.get("/api/jobs")
def jobs(db:Session=Depends(get_db)):
    rows=db.query(JobRun).order_by(JobRun.id.desc()).limit(100).all();out=[]
    for r in rows:
        result={}
        try:result=json.loads(r.result_json or "{}")
        except Exception:pass
        out.append({"id":r.id,"job_key":r.job_key,"kind":r.kind,"status":r.status,"progress":r.progress,"message":result.get("message"),
                    "error":r.error,"created_at":r.created_at,"updated_at":r.updated_at})
    return out

@app.get("/api/jobs/{job_key}")
def job(job_key:str,db:Session=Depends(get_db)):
    r=db.query(JobRun).filter(JobRun.job_key==job_key).first()
    if not r:raise HTTPException(404,"Job not found")
    return {"id":r.id,"job_key":r.job_key,"kind":r.kind,"status":r.status,"progress":r.progress,"error":r.error,
            "result":json.loads(r.result_json or "{}"),"created_at":r.created_at,"updated_at":r.updated_at}

@app.get("/api/paper/account")
def paper_account(db:Session=Depends(get_db)):return PaperBrokerService(db).sync_account()
@app.get("/api/paper/positions")
def paper_positions(db:Session=Depends(get_db)):return PaperBrokerService(db).sync_positions()
@app.get("/api/paper/clock")
def paper_clock(db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).clock()
@app.get("/api/paper/calendar")
def paper_calendar(start:str,end:str,db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).calendar(start,end)
@app.get("/api/paper/rebalance/preview")
def paper_preview(n:int=20,db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).preview(n)
@app.post("/api/paper/rebalance/execute")
def paper_execute(n:int=20,db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).execute(n)
@app.post("/api/paper/reconcile")
def paper_reconcile(db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).reconcile()
@app.post("/api/paper/kill/cancel-orders")
def cancel_orders(db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).cancel_all()
@app.post("/api/paper/kill/flatten")
def flatten(confirm:str,db:Session=Depends(get_db)):return ExecutionService(db,PaperBrokerService(db)).flatten(confirm)
@app.post("/api/paper/snapshot")
def create_snapshot(db:Session=Depends(get_db)):return snapshot_paper(db)
@app.get("/api/paper/performance")
def paper_performance(db:Session=Depends(get_db)):return {"history":paper_history(db),"comparison":compare_paper_backtest(db)}
@app.get("/api/paper/orders")
def orders(db:Session=Depends(get_db)):
    rows=db.query(BrokerOrder).order_by(BrokerOrder.id.desc()).limit(250).all()
    return [{"client_order_id":r.client_order_id,"symbol":r.symbol,"side":r.side,"notional":r.notional,"status":r.status,"created_at":r.created_at} for r in rows]
@app.get("/api/paper/fills")
def fills(db:Session=Depends(get_db)):
    rows=db.query(TradeFill).order_by(TradeFill.id.desc()).limit(500).all()
    return [{"id":r.id,"symbol":r.symbol,"side":r.side,"qty":r.qty,"price":r.price,"notional":r.notional,"event":r.event,"created_at":r.created_at} for r in rows]
@app.get("/api/paper/rebalances")
def rebalances(db:Session=Depends(get_db)):
    rows=db.query(RebalanceRun).order_by(RebalanceRun.id.desc()).limit(100).all()
    return [{"key":r.rebalance_key,"strategy":r.strategy_name,"status":r.status,"targets":r.target_count,"orders":r.order_count,"created_at":r.created_at} for r in rows]
