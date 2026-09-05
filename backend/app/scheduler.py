from __future__ import annotations
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import settings
from app.db.session import Base,engine,SessionLocal
from app.services.broker import PaperBrokerService
from app.services.execution import ExecutionService
from app.services.jobs import enqueue

def loop():
    Base.metadata.create_all(bind=engine); last_trade=None; last_daily=None
    print('QuantLab scheduler ready',flush=True)
    while True:
        now=datetime.now(ZoneInfo('America/New_York')); key=now.strftime('%Y-%m-%d')
        daily_due=settings.daily_pipeline_enabled and now.hour==settings.daily_pipeline_hour_et and now.minute>=settings.daily_pipeline_minute_et
        if daily_due and last_daily!=key:
            try:
                enqueue('DAILY_PIPELINE',{'force_market':True,'refresh_sec':now.weekday()==settings.daily_sec_refresh_weekday}); last_daily=key
                print('Daily pipeline queued',key,flush=True)
            except Exception as e: print('Daily pipeline queue error',repr(e),flush=True)
        trade_due=(settings.paper_auto_enabled and now.weekday()==settings.paper_auto_weekday and now.hour==settings.paper_auto_hour_et and now.minute>=settings.paper_auto_minute_et)
        if trade_due and last_trade!=key:
            db=SessionLocal()
            try:
                svc=ExecutionService(db,PaperBrokerService(db)); preview=svc.preview(settings.paper_auto_top_n)
                if preview['risk']['passed']:
                    svc.execute(settings.paper_auto_top_n);last_trade=key
                else: print('Paper auto blocked by risk gate',preview['risk'],flush=True)
            except Exception as e: print('Paper auto error',repr(e),flush=True)
            finally: db.close()
        time.sleep(30)
if __name__=='__main__': loop()
