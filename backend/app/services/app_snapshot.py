from __future__ import annotations

import json
from redis import Redis

from app.core.config import settings
from app.models.entities import (
    BacktestRun,BrokerOrder,JobRun,ModelVersion,PaperPosition,StrategyVersion,
    SystemState,TradeFill,
)
from app.services.broker import PaperBrokerService
from app.services.dataset_state import get_state,states
from app.services.features import feature_store_status
from app.services.monitoring import compare_paper_backtest,paper_history


def _loads(value,default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _backtest_summary(row):
    payload=_loads(row.payload_json,{})
    metrics=payload.get("metrics",{})
    return {
        "id":row.id,
        "strategy":row.strategy_name,
        "created_at":row.created_at,
        "cagr":row.cagr,
        "sharpe":row.sharpe,
        "max_drawdown":row.max_drawdown,
        "volatility":row.volatility,
        "turnover":row.turnover,
        "dataset":payload.get("dataset",{}),
        "metrics":{
            "total_return":metrics.get("total_return"),
            "cagr":metrics.get("cagr",row.cagr),
            "sharpe":metrics.get("sharpe",row.sharpe),
            "sortino":metrics.get("sortino"),
            "calmar":metrics.get("calmar"),
            "max_drawdown":metrics.get("max_drawdown",row.max_drawdown),
            "benchmark_cagr":metrics.get("benchmark_cagr"),
            "excess_cagr_vs_equal_weight":metrics.get("excess_cagr_vs_equal_weight"),
            "mean_rank_ic_20d":metrics.get("mean_rank_ic_20d"),
            "win_rate":metrics.get("win_rate"),
            "profit_factor":metrics.get("profit_factor"),
            "ending_capital_usd":metrics.get("ending_capital_usd"),
            "net_pnl_usd":metrics.get("net_pnl_usd"),
            "estimated_costs_usd":metrics.get("estimated_costs_usd"),
        },
    }


def _job(row):
    result=_loads(row.result_json,{})
    return {
        "id":row.id,"job_key":row.job_key,"kind":row.kind,"status":row.status,
        "progress":row.progress,"message":result.get("message"),"error":row.error,
        "created_at":row.created_at,"updated_at":row.updated_at,
        "started_at":row.started_at,"completed_at":row.completed_at,
    }


def _runtime():
    try:
        redis=Redis.from_url(settings.redis_url,decode_responses=True)
        return {
            "redis":bool(redis.ping()),
            "worker_online":bool(redis.get("quantlab:worker:heartbeat")),
            "queue_depth":int(redis.llen("quantlab:jobs")),
        }
    except Exception as exc:
        return {"redis":False,"worker_online":False,"queue_depth":None,"error":str(exc)}


def build_app_snapshot(db):
    runtime=_runtime()
    fs=feature_store_status()
    all_states=states(db)
    quality=get_state(db,"data_quality",{"status":"NOT_READY","checks":[]})
    validation=get_state(db,"validation.latest",{"status":"NOT_RUN","tier":"NOT_RUN","passed":False,"checks":[]})
    signals=get_state(db,"meta_v5.latest_signals",{"status":"NOT_RUN","signals":[],"accepted_signals":[]})
    factors=get_state(db,"research.factor_summary",{"status":"NOT_RUN","factors":[]})
    ranking=get_state(db,"ranking.latest",{"rows":[]})

    account=PaperBrokerService(db).cached_account()
    backtests=db.query(BacktestRun).order_by(BacktestRun.id.desc()).limit(30).all()
    jobs=db.query(JobRun).order_by(JobRun.id.desc()).limit(60).all()
    models=db.query(ModelVersion).order_by(ModelVersion.id.desc()).limit(30).all()
    strategies=db.query(StrategyVersion).order_by(StrategyVersion.id.desc()).limit(30).all()
    positions=db.query(PaperPosition).order_by(PaperPosition.symbol).all()
    orders=db.query(BrokerOrder).order_by(BrokerOrder.id.desc()).limit(100).all()
    fills=db.query(TradeFill).order_by(TradeFill.id.desc()).limit(100).all()

    readiness=[
        {"name":"Market data","ok":settings.data_mode.lower()=="synthetic" or bool(settings.alpaca_api_key and settings.alpaca_secret_key)},
        {"name":"Feature Store","ok":bool(fs.get("ready"))},
        {"name":"Data quality","ok":quality.get("status")=="PASS"},
        {"name":"Worker","ok":bool(runtime.get("worker_online"))},
        {"name":"Autopilot","ok":bool(settings.auto_bootstrap_enabled)},
    ]

    datasets={}
    for key in ("market_data","features","fundamentals","data_quality","ranking.latest"):
        if key in all_states:
            datasets[key]=all_states[key]

    return {
        "version":"1.3.0",
        "mode":"PAPER",
        "system":{
            "data_mode":settings.data_mode,
            "trading_env":settings.trading_env,
            "alpaca_configured":bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            "paper_orders_enabled":settings.allow_alpaca_paper_orders,
            "paper_auto_enabled":settings.paper_auto_enabled,
            "auto_bootstrap_enabled":settings.auto_bootstrap_enabled,
            "live_trading_supported":False,
            **runtime,
        },
        "readiness":{"ready":all(x["ok"] for x in readiness[:4]),"steps":readiness,"feature_store":fs},
        "account":account,
        "quality":quality,
        "validation":validation,
        "signals":signals,
        "factor_research":factors,
        "ranking":ranking.get("rows",[]),
        "datasets":datasets,
        "backtests":[_backtest_summary(x) for x in backtests],
        "jobs":[_job(x) for x in jobs],
        "models":[{
            "id":x.id,"name":x.name,"version":x.version,"type":x.model_type,"status":x.status,
            "metrics":_loads(x.metrics_json,{}),"created_at":x.created_at,
        } for x in models],
        "strategies":[{
            "id":x.id,"name":x.name,"version":x.version,"status":x.status,
            "config":_loads(x.config_json,{}),"created_at":x.created_at,
        } for x in strategies],
        "paper":{
            "positions":[{"symbol":x.symbol,"side":x.side,"notional":x.notional,"weight":x.weight,"score":x.score,"updated_at":x.updated_at} for x in positions],
            "orders":[{"client_order_id":x.client_order_id,"symbol":x.symbol,"side":x.side,"notional":x.notional,"status":x.status,"created_at":x.created_at} for x in orders],
            "fills":[{"id":x.id,"symbol":x.symbol,"side":x.side,"qty":x.qty,"price":x.price,"notional":x.notional,"event":x.event,"created_at":x.created_at} for x in fills],
            "performance":{"history":paper_history(db,250),"comparison":compare_paper_backtest(db)},
        },
    }
