from __future__ import annotations
import json
from datetime import datetime, timezone
from app.models.entities import PortfolioSnapshot, PaperPosition, BacktestRun, StrategyVersion, SystemState
from app.services.broker import PaperBrokerService
from app.services.data_quality import report as data_quality_report


def snapshot_paper(db):
    broker = PaperBrokerService(db)
    account = broker.sync_account()
    positions = db.query(PaperPosition).all()
    equity = float(account.get('equity') or 0)
    long_exp = sum(max(float(p.notional or 0), 0) for p in positions)
    short_exp = sum(abs(min(float(p.notional or 0), 0)) for p in positions)
    # Simulated positions historically stored positive notional + side.
    if short_exp == 0:
        short_exp = sum(abs(float(p.notional or 0)) for p in positions if str(p.side).upper() == 'SHORT')
        long_exp = sum(abs(float(p.notional or 0)) for p in positions if str(p.side).upper() == 'LONG')
    gross = (long_exp + short_exp) / equity if equity else 0
    net = (long_exp - short_exp) / equity if equity else 0
    row = PortfolioSnapshot(
        source='PAPER', equity=equity, cash=float(account.get('cash') or 0),
        buying_power=float(account.get('buying_power') or 0), long_exposure=long_exp,
        short_exposure=short_exp, gross_exposure=gross, net_exposure=net,
        position_count=len(positions), payload_json=json.dumps(account, default=str)
    )
    db.add(row); db.commit(); db.refresh(row)
    return serialize_snapshot(row)


def serialize_snapshot(r):
    return {'id':r.id,'source':r.source,'equity':r.equity,'cash':r.cash,'buying_power':r.buying_power,
            'long_exposure':r.long_exposure,'short_exposure':r.short_exposure,'gross_exposure':r.gross_exposure,
            'net_exposure':r.net_exposure,'position_count':r.position_count,'created_at':r.created_at}


def paper_history(db, limit=500):
    rows=db.query(PortfolioSnapshot).filter(PortfolioSnapshot.source=='PAPER').order_by(PortfolioSnapshot.id.desc()).limit(limit).all()
    return [serialize_snapshot(r) for r in reversed(rows)]


def compare_paper_backtest(db):
    snaps=paper_history(db, 10000)
    last_bt=db.query(BacktestRun).order_by(BacktestRun.id.desc()).first()
    if len(snaps)<2:
        paper_return=None
    else:
        first,last=snaps[0]['equity'],snaps[-1]['equity']; paper_return=(last/first-1) if first else None
    bt_return=None; bt_cagr=None; bt_sharpe=None
    if last_bt:
        bt_cagr=last_bt.cagr; bt_sharpe=last_bt.sharpe
        try:
            p=json.loads(last_bt.payload_json); curve=p.get('equity_curve') or []
            if len(curve)>=2:
                a=float(curve[0]['equity']); b=float(curve[-1]['equity']); bt_return=b/a-1 if a else None
        except Exception: pass
    return {'paper_return':paper_return,'backtest_return':bt_return,'return_gap':None if paper_return is None or bt_return is None else paper_return-bt_return,
            'backtest_cagr':bt_cagr,'backtest_sharpe':bt_sharpe,'paper_snapshots':len(snaps)}


def promotion_gate(db, strategy_id:int):
    strategy=db.get(StrategyVersion,strategy_id)
    if not strategy: return None
    dq=data_quality_report(); bt=db.query(BacktestRun).order_by(BacktestRun.id.desc()).first()
    checks=[
        {'name':'data_quality','ok':str(dq.get('status','')).upper() in ('PASS','OK'),'detail':dq.get('status')},
        {'name':'backtest_exists','ok':bt is not None,'detail':None if not bt else bt.id},
        {'name':'positive_sharpe','ok':bool(bt and bt.sharpe>0),'detail':None if not bt else bt.sharpe},
        {'name':'drawdown_bounded','ok':bool(bt and bt.max_drawdown>-0.50),'detail':None if not bt else bt.max_drawdown},
    ]
    return {'strategy_id':strategy_id,'passed':all(x['ok'] for x in checks),'checks':checks}
