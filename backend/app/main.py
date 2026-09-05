from __future__ import annotations
import json
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.session import Base, engine, get_db
from app.models.entities import BacktestRun, PaperPosition, ExecutionLog, RebalanceRun, BrokerOrder, StrategyVersion, ModelVersion, ExperimentRun, JobRun, PortfolioSnapshot, TradeFill
from app.services.backtest import run_backtest
from app.services.broker import PaperBrokerService
from app.services.features import build_feature_panel
from app.core.config import settings
from app.services.research import factor_report, correlations, train_walk_forward
from app.services.execution import ExecutionService
from app.services.experiments import parameter_sweep, robustness
from app.services.jobs import enqueue
from app.services.monitoring import snapshot_paper, paper_history, compare_paper_backtest, promotion_gate

app = FastAPI(title="Quant Lab V1", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

class RebalanceRequest(BaseModel):
    n: int = Field(20, ge=1, le=50)
    execute: bool = False

class BacktestRequest(BaseModel):
    long_count: int = Field(20, ge=1, le=50)
    short_count: int = Field(20, ge=1, le=50)
    rebalance_days: int = Field(5, ge=1, le=21)
    commission_bps: float = Field(6.0, ge=0, le=100)
    slippage_bps: float = Field(5.0, ge=0, le=100)
    gross_exposure: float = Field(2.0, ge=0.2, le=2.0)

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/api/dashboard")
def dashboard(db: Session=Depends(get_db)):
    broker=PaperBrokerService(db).sync_account()
    last=db.query(BacktestRun).order_by(BacktestRun.id.desc()).first()
    positions=db.query(PaperPosition).all()
    return {"broker":broker,"last_backtest":None if not last else {"id":last.id,"strategy":last.strategy_name,"cagr":last.cagr,"sharpe":last.sharpe,"max_drawdown":last.max_drawdown},"paper_positions":len(positions),"mode":"PAPER"}

@app.post("/api/backtests")
def create_backtest(req: BacktestRequest, db: Session=Depends(get_db)):
    result=run_backtest(req.model_dump())
    m=result["metrics"]
    row=BacktestRun(strategy_name=result["strategy"], cagr=m["cagr"], sharpe=m["sharpe"], max_drawdown=m["max_drawdown"], volatility=m["volatility"], turnover=m["avg_turnover_per_rebalance"], payload_json=json.dumps(result))
    db.add(row); db.commit(); db.refresh(row)
    return {"id":row.id, **result}

@app.get("/api/backtests")
def list_backtests(db: Session=Depends(get_db)):
    rows=db.query(BacktestRun).order_by(BacktestRun.id.desc()).limit(20).all()
    return [{"id":r.id,"strategy":r.strategy_name,"created_at":r.created_at,"cagr":r.cagr,"sharpe":r.sharpe,"max_drawdown":r.max_drawdown,"volatility":r.volatility,"turnover":r.turnover} for r in rows]

@app.get("/api/backtests/{run_id}")
def get_backtest(run_id:int, db:Session=Depends(get_db)):
    r=db.get(BacktestRun, run_id)
    if not r: raise HTTPException(404,"Backtest not found")
    return {"id":r.id, **json.loads(r.payload_json)}

@app.get("/api/factors/latest")
def factors_latest():
    df=build_feature_panel(); snap=df[df.date==df.date.max()].sort_values("meta_score",ascending=False)
    cols=["symbol","sector","meta_score","momentum_12_1_rank","fundamental_raw_rank","earnings_raw_rank","news_raw_rank","low_vol_rank"]
    return snap[cols].head(100).round(4).to_dict("records")

@app.get("/api/paper/account")
def paper_account(db:Session=Depends(get_db)): return PaperBrokerService(db).sync_account()

@app.get("/api/paper/positions")
def paper_positions(db:Session=Depends(get_db)):
    rows=db.query(PaperPosition).order_by(PaperPosition.weight.desc()).all()
    return [{"symbol":r.symbol,"side":r.side,"notional":r.notional,"weight":r.weight,"score":r.score} for r in rows]

@app.post("/api/paper/rebalance")
def paper_rebalance(req:RebalanceRequest=RebalanceRequest(), db:Session=Depends(get_db)):
    try: return PaperBrokerService(db).rebalance(req.n, req.execute)
    except RuntimeError as e: raise HTTPException(400,str(e))

@app.post("/api/data/refresh")
def refresh_data():
    if settings.data_mode.lower() != "alpaca": return {"status":"noop","mode":settings.data_mode}
    from app.services.real_data import fetch_bars
    df=fetch_bars(force=True)
    return {"status":"ok","rows":len(df),"symbols":int(df.symbol.nunique()),"from":str(df.date.min().date()),"to":str(df.date.max().date())}

@app.get("/api/system/status")
def system_status():
    return {"data_mode":settings.data_mode,"alpaca_configured":bool(settings.alpaca_api_key and settings.alpaca_secret_key),"paper_orders_enabled":settings.allow_alpaca_paper_orders,"paper_auto_enabled":settings.paper_auto_enabled}

@app.get("/api/paper/logs")
def paper_logs(db:Session=Depends(get_db)):
    rows=db.query(ExecutionLog).order_by(ExecutionLog.id.desc()).limit(100).all()
    return [{"created_at":r.created_at,"level":r.level,"message":r.message} for r in rows]

@app.get("/api/research/factors/{feature}")
def research_factor(feature:str):
    try:return factor_report(feature)
    except ValueError as e:raise HTTPException(400,str(e))

@app.get("/api/research/correlations")
def research_correlations(): return correlations()

@app.post("/api/models/train/{model}")
def train_model(model:str):
    if model not in ("ridge","hgb"): raise HTTPException(400,"model must be ridge or hgb")
    return train_walk_forward(model)

@app.get("/api/data/quality")
def data_quality():
    from app.services.data_quality import report
    return report()

@app.post("/api/data/sec/refresh")
def refresh_sec():
    if settings.data_mode.lower() != "alpaca": return {"status":"noop","mode":settings.data_mode}
    from app.services.real_data import universe
    from app.services.sec_fundamentals import fundamental_events
    syms=universe(); rows=0; covered=0
    for s in syms:
        df=fundamental_events(s,force=True); rows+=len(df); covered+=int(len(df)>0)
    return {"status":"ok","symbols":len(syms),"covered":covered,"events":rows}


@app.get("/api/paper/clock")
def paper_clock(db:Session=Depends(get_db)):
    return ExecutionService(db,PaperBrokerService(db)).clock()

@app.get("/api/paper/calendar")
def paper_calendar(start:str,end:str,db:Session=Depends(get_db)):
    return ExecutionService(db,PaperBrokerService(db)).calendar(start,end)

@app.get("/api/paper/rebalance/preview")
def rebalance_preview(n:int=20,db:Session=Depends(get_db)):
    return ExecutionService(db,PaperBrokerService(db)).preview(n)

@app.post("/api/paper/rebalance/execute")
def rebalance_execute(n:int=20,db:Session=Depends(get_db)):
    try: return ExecutionService(db,PaperBrokerService(db)).execute(n)
    except RuntimeError as e: raise HTTPException(400,str(e))

@app.post("/api/paper/reconcile")
def paper_reconcile(db:Session=Depends(get_db)):
    return ExecutionService(db,PaperBrokerService(db)).reconcile()

@app.get("/api/paper/orders")
def tracked_orders(db:Session=Depends(get_db)):
    rows=db.query(BrokerOrder).order_by(BrokerOrder.id.desc()).limit(250).all()
    return [{"client_order_id":r.client_order_id,"broker_order_id":r.broker_order_id,"rebalance_key":r.rebalance_key,"symbol":r.symbol,"side":r.side,"notional":r.notional,"status":r.status,"created_at":r.created_at,"updated_at":r.updated_at} for r in rows]

@app.get("/api/paper/rebalances")
def rebalances(db:Session=Depends(get_db)):
    rows=db.query(RebalanceRun).order_by(RebalanceRun.id.desc()).limit(100).all()
    return [{"key":r.rebalance_key,"strategy":r.strategy_name,"status":r.status,"targets":r.target_count,"orders":r.order_count,"created_at":r.created_at,"completed_at":r.completed_at} for r in rows]


class StrategyCreate(BaseModel):
    name: str = "META US"
    config: dict = {}

class ExperimentRequest(BaseModel):
    base: BacktestRequest = BacktestRequest()
    grid: dict = {"long_count":[10,20,30],"short_count":[10,20,30],"rebalance_days":[5,10,21]}

@app.get("/api/strategies")
def strategies(db:Session=Depends(get_db)):
    rows=db.query(StrategyVersion).order_by(StrategyVersion.id.desc()).all()
    return [{"id":r.id,"name":r.name,"version":r.version,"status":r.status,"config":json.loads(r.config_json),"created_at":r.created_at} for r in rows]

@app.post("/api/strategies")
def create_strategy(req:StrategyCreate,db:Session=Depends(get_db)):
    last=db.query(StrategyVersion).filter(StrategyVersion.name==req.name).order_by(StrategyVersion.version.desc()).first()
    row=StrategyVersion(name=req.name,version=(last.version+1 if last else 1),config_json=json.dumps(req.config))
    db.add(row);db.commit();db.refresh(row);return {"id":row.id,"name":row.name,"version":row.version,"status":row.status}

@app.get("/api/strategies/{strategy_id}/promotion-gate")
def strategy_promotion_gate(strategy_id:int,db:Session=Depends(get_db)):
    gate=promotion_gate(db,strategy_id)
    if not gate: raise HTTPException(404,"Strategy not found")
    return gate

@app.post("/api/strategies/{strategy_id}/promote")
def promote_strategy(strategy_id:int,db:Session=Depends(get_db)):
    row=db.get(StrategyVersion,strategy_id)
    if not row: raise HTTPException(404,"Strategy not found")
    gate=promotion_gate(db,strategy_id)
    if not gate["passed"]: raise HTTPException(400,{"message":"Promotion blocked","gate":gate})
    db.query(StrategyVersion).filter(StrategyVersion.status=="PAPER").update({StrategyVersion.status:"ARCHIVED"})
    row.status="PAPER";db.commit();return {"id":row.id,"status":row.status,"gate":gate}

@app.get("/api/models")
def models(db:Session=Depends(get_db)):
    rows=db.query(ModelVersion).order_by(ModelVersion.id.desc()).all()
    return [{"id":r.id,"name":r.name,"version":r.version,"type":r.model_type,"status":r.status,"metrics":json.loads(r.metrics_json),"created_at":r.created_at} for r in rows]

@app.post("/api/models/train-and-register/{model}")
def train_register(model:str,db:Session=Depends(get_db)):
    if model not in ("ridge","hgb"): raise HTTPException(400,"model must be ridge or hgb")
    result=train_walk_forward(model)
    last=db.query(ModelVersion).filter(ModelVersion.name==model.upper()).order_by(ModelVersion.version.desc()).first()
    row=ModelVersion(name=model.upper(),version=(last.version+1 if last else 1),model_type=model,metrics_json=json.dumps(result,default=str))
    db.add(row);db.commit();db.refresh(row);return {"id":row.id,"version":row.version,"result":result}

@app.post("/api/experiments/sweep")
def experiment_sweep(req:ExperimentRequest,db:Session=Depends(get_db)):
    result=parameter_sweep(req.base.model_dump(),req.grid)
    row=ExperimentRun(name="Parameter Sweep",kind="SWEEP",payload_json=json.dumps(result,default=str));db.add(row);db.commit();db.refresh(row)
    return {"id":row.id,**result}

@app.post("/api/experiments/robustness")
def experiment_robustness(req:BacktestRequest,db:Session=Depends(get_db)):
    result=robustness(req.model_dump())
    row=ExperimentRun(name="Robustness Suite",kind="ROBUSTNESS",payload_json=json.dumps(result,default=str));db.add(row);db.commit();db.refresh(row)
    return {"id":row.id,**result}

@app.get("/api/experiments")
def experiments(db:Session=Depends(get_db)):
    rows=db.query(ExperimentRun).order_by(ExperimentRun.id.desc()).limit(50).all()
    return [{"id":r.id,"name":r.name,"kind":r.kind,"status":r.status,"created_at":r.created_at} for r in rows]


@app.post("/api/jobs/backtest")
def job_backtest(req:BacktestRequest): return enqueue("BACKTEST",req.model_dump())

@app.post("/api/jobs/sweep")
def job_sweep(req:ExperimentRequest): return enqueue("SWEEP",{"base":req.base.model_dump(),"grid":req.grid})

@app.post("/api/jobs/robustness")
def job_robustness(req:BacktestRequest): return enqueue("ROBUSTNESS",req.model_dump())

@app.post("/api/jobs/train/{model}")
def job_train(model:str):
    if model not in ("ridge","hgb"): raise HTTPException(400,"model must be ridge or hgb")
    return enqueue("TRAIN_"+model.upper(),{})

@app.post("/api/jobs/data-refresh")
def job_data_refresh():
    if settings.data_mode.lower() != "alpaca": raise HTTPException(400,"DATA_MODE must be alpaca")
    return enqueue("DATA_REFRESH",{})

@app.post("/api/jobs/sec-refresh")
def job_sec_refresh():
    if settings.data_mode.lower() != "alpaca": raise HTTPException(400,"DATA_MODE must be alpaca")
    return enqueue("SEC_REFRESH",{})

@app.get("/api/jobs")
def jobs(db:Session=Depends(get_db)):
    rows=db.query(JobRun).order_by(JobRun.id.desc()).limit(100).all()
    return [{"id":r.id,"job_key":r.job_key,"kind":r.kind,"status":r.status,"progress":r.progress,"error":r.error,"created_at":r.created_at,"updated_at":r.updated_at} for r in rows]

@app.get("/api/jobs/{job_key}")
def job(job_key:str,db:Session=Depends(get_db)):
    r=db.query(JobRun).filter(JobRun.job_key==job_key).first()
    if not r: raise HTTPException(404,"Job not found")
    return {"id":r.id,"job_key":r.job_key,"kind":r.kind,"status":r.status,"progress":r.progress,"error":r.error,"result":json.loads(r.result_json or "{}"),"created_at":r.created_at,"updated_at":r.updated_at}


@app.post("/api/paper/snapshot")
def create_paper_snapshot(db:Session=Depends(get_db)):
    return snapshot_paper(db)

@app.get("/api/paper/performance")
def paper_performance(db:Session=Depends(get_db)):
    return {"history":paper_history(db),"comparison":compare_paper_backtest(db)}

@app.get("/api/compare/paper-vs-backtest")
def paper_vs_backtest(db:Session=Depends(get_db)):
    return compare_paper_backtest(db)

@app.post("/api/jobs/paper-snapshot")
def job_paper_snapshot(): return enqueue("PAPER_SNAPSHOT",{})


@app.post("/api/jobs/daily-pipeline")
def job_daily_pipeline(force_market:bool=False,refresh_sec:bool=False):
    return enqueue("DAILY_PIPELINE",{"force_market":force_market,"refresh_sec":refresh_sec})

@app.get("/api/system/datasets")
def dataset_versions(db:Session=Depends(get_db)):
    from app.services.dataset_state import states
    return states(db)


@app.get("/api/paper/fills")
def paper_fills(db:Session=Depends(get_db)):
    rows=db.query(TradeFill).order_by(TradeFill.id.desc()).limit(500).all()
    return [{"id":r.id,"symbol":r.symbol,"side":r.side,"qty":r.qty,"price":r.price,"notional":r.notional,"event":r.event,"client_order_id":r.client_order_id,"created_at":r.created_at} for r in rows]
