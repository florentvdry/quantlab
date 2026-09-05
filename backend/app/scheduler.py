from __future__ import annotations
import json,time
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import settings
from app.db.session import Base,engine,SessionLocal
from app.models.entities import SystemState,JobRun
from app.services.broker import PaperBrokerService
from app.services.execution import ExecutionService
from app.services.jobs import enqueue

TZ=ZoneInfo("America/New_York")

def _done(db,key,value):
    row=db.query(SystemState).filter(SystemState.key==key).first()
    if not row:return False
    try:return json.loads(row.value_json).get("value")==value
    except Exception:return False

def _mark(db,key,value):
    row=db.query(SystemState).filter(SystemState.key==key).first() or SystemState(key=key)
    row.value_json=json.dumps({"value":value});row.updated_at=datetime.utcnow();db.add(row);db.commit()

def _bootstrap_needed(db):
    if not settings.auto_bootstrap_enabled:
        return False
    from app.services.features import feature_store_status
    if not feature_store_status().get("ready"):
        return True
    validation=db.query(SystemState).filter(SystemState.key=="validation.latest").first()
    signals=db.query(SystemState).filter(SystemState.key=="meta_v5.latest_signals").first()
    return validation is None or signals is None

def _bootstrap_active_or_recent_failure(db):
    latest=db.query(JobRun).filter(JobRun.kind=="AUTO_BOOTSTRAP").order_by(JobRun.id.desc()).first()
    if not latest:return False
    if latest.status in ("QUEUED","RUNNING"):return True
    if latest.status=="FAILED" and latest.created_at and (datetime.utcnow()-latest.created_at).total_seconds()<600:return True
    return False

def loop():
    Base.metadata.create_all(bind=engine);print("QuantLab scheduler ready",flush=True)
    while True:
        now=datetime.now(TZ);day=now.strftime("%Y-%m-%d");db=SessionLocal()
        try:
            daily_due=settings.daily_pipeline_enabled and now.hour==settings.daily_pipeline_hour_et and now.minute>=settings.daily_pipeline_minute_et
            daily_queued=False
            if daily_due and not _done(db,"scheduler.daily_pipeline",day) and not _bootstrap_active_or_recent_failure(db):
                enqueue("AUTO_BOOTSTRAP",{"force_market":True,"refresh_sec":now.weekday()==settings.daily_sec_refresh_weekday})
                enqueue("PAPER_SNAPSHOT",{});_mark(db,"scheduler.daily_pipeline",day);daily_queued=True
                print("Daily autopilot refresh queued",day,flush=True)
            if not daily_queued and _bootstrap_needed(db) and not _bootstrap_active_or_recent_failure(db):
                enqueue("AUTO_BOOTSTRAP",{"force_market":False,"refresh_sec":False})
                print("Autopilot bootstrap queued",flush=True)
            hour_key=now.strftime("%Y-%m-%d-%H")
            if settings.alpaca_api_key and settings.alpaca_secret_key and not _done(db,"scheduler.reconcile",hour_key):
                try:ExecutionService(db,PaperBrokerService(db)).reconcile()
                finally:_mark(db,"scheduler.reconcile",hour_key)
            trade_due=settings.paper_auto_enabled and now.weekday()==settings.paper_auto_weekday and now.hour==settings.paper_auto_hour_et and now.minute>=settings.paper_auto_minute_et
            if trade_due and not _done(db,"scheduler.paper_rebalance",day):
                svc=ExecutionService(db,PaperBrokerService(db));preview=svc.preview(settings.paper_auto_top_n)
                if preview["risk"]["passed"]:
                    svc.execute(settings.paper_auto_top_n);_mark(db,"scheduler.paper_rebalance",day);print("Paper auto submitted",day,flush=True)
                else:print("Paper auto blocked by risk gate",preview["risk"],flush=True)
        except Exception as e:print("Scheduler error",repr(e),flush=True)
        finally:db.close()
        time.sleep(30)
if __name__=="__main__":loop()
