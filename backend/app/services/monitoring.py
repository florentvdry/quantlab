from __future__ import annotations
import json
from app.models.entities import PortfolioSnapshot,BacktestRun,StrategyVersion,JobRun
from app.services.broker import PaperBrokerService

def snapshot_paper(db):
    broker=PaperBrokerService(db);account=broker.sync_account();positions=broker.sync_positions();equity=float(account.get("equity") or 0)
    long_exp=sum(abs(float(p["notional"])) for p in positions if str(p["side"]).upper()=="LONG")
    short_exp=sum(abs(float(p["notional"])) for p in positions if str(p["side"]).upper()=="SHORT")
    gross=(long_exp+short_exp)/equity if equity else 0;net=(long_exp-short_exp)/equity if equity else 0
    row=PortfolioSnapshot(source="PAPER",equity=equity,cash=float(account.get("cash") or 0),buying_power=float(account.get("buying_power") or 0),
        long_exposure=long_exp,short_exposure=short_exp,gross_exposure=gross,net_exposure=net,position_count=len(positions),
        payload_json=json.dumps({"account":account,"positions":positions},default=str))
    db.add(row);db.commit();db.refresh(row);return serialize_snapshot(row)

def serialize_snapshot(r):
    return {"id":r.id,"source":r.source,"equity":r.equity,"cash":r.cash,"buying_power":r.buying_power,"long_exposure":r.long_exposure,
            "short_exposure":r.short_exposure,"gross_exposure":r.gross_exposure,"net_exposure":r.net_exposure,
            "position_count":r.position_count,"created_at":r.created_at}

def paper_history(db,limit=500):
    rows=db.query(PortfolioSnapshot).filter(PortfolioSnapshot.source=="PAPER").order_by(PortfolioSnapshot.id.desc()).limit(limit).all()
    return [serialize_snapshot(r) for r in reversed(rows)]

def compare_paper_backtest(db):
    snaps=paper_history(db,10000);last_bt=db.query(BacktestRun).order_by(BacktestRun.id.desc()).first()
    paper_return=None
    if len(snaps)>=2 and snaps[0]["equity"]:paper_return=snaps[-1]["equity"]/snaps[0]["equity"]-1
    bt_return=None;bt_cagr=None;bt_sharpe=None;aligned=False
    if last_bt:
        bt_cagr=last_bt.cagr;bt_sharpe=last_bt.sharpe
        try:
            payload=json.loads(last_bt.payload_json);curve=payload.get("equity_curve") or []
            if len(snaps)>=2 and curve:
                start=str(snaps[0]["created_at"].date());end=str(snaps[-1]["created_at"].date())
                sub=[x for x in curve if start<=x["date"]<=end]
                if len(sub)>=2 and float(sub[0]["equity"]):
                    bt_return=float(sub[-1]["equity"])/float(sub[0]["equity"])-1;aligned=True
        except Exception:pass
    return {"paper_return":paper_return,"backtest_return":bt_return,"return_gap":None if paper_return is None or bt_return is None else paper_return-bt_return,
            "backtest_cagr":bt_cagr,"backtest_sharpe":bt_sharpe,"paper_snapshots":len(snaps),"date_aligned":aligned}

def promotion_gate(db,strategy_id:int):
    strategy=db.get(StrategyVersion,strategy_id)
    if not strategy:return None
    v=db.query(JobRun).filter(JobRun.kind=="VALIDATION",JobRun.status=="COMPLETED").order_by(JobRun.id.desc()).first()
    result={}
    if v:
        try:result=json.loads(v.result_json or "{}")
        except Exception:result={}
    checks=[
        {"name":"validation_completed","ok":v is not None,"detail":None if not v else v.job_key},
        {"name":"validation_passed","ok":bool(result.get("passed")),"detail":result.get("passed")},
        {"name":"paper_eligible","ok":bool(result.get("paper_eligible")),"detail":result.get("checks",[])},
    ]
    return {"strategy_id":strategy_id,"passed":all(x["ok"] for x in checks),"checks":checks}
