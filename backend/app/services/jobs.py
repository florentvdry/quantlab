from __future__ import annotations
import json, traceback, uuid
from datetime import datetime
from redis import Redis
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import JobRun, ExperimentRun, ModelVersion
from app.services.backtest import run_backtest
from app.services.experiments import parameter_sweep, robustness
from app.services.research import train_walk_forward

QUEUE='quantlab:jobs'

def redis_client(): return Redis.from_url(settings.redis_url, decode_responses=True)

def enqueue(kind:str, payload:dict|None=None):
    db=SessionLocal(); key=str(uuid.uuid4())
    try:
        row=JobRun(job_key=key,kind=kind,status='QUEUED',progress=0,payload_json=json.dumps(payload or {}))
        db.add(row);db.commit();db.refresh(row)
        redis_client().rpush(QUEUE,key)
        return {'id':row.id,'job_key':key,'kind':kind,'status':'QUEUED'}
    finally: db.close()

def update(db,row,**kw):
    for k,v in kw.items(): setattr(row,k,v)
    row.updated_at=datetime.utcnow();db.commit()

def execute_job(key:str):
    db=SessionLocal(); row=db.query(JobRun).filter(JobRun.job_key==key).first()
    if not row: db.close(); return
    try:
        update(db,row,status='RUNNING',progress=5,started_at=datetime.utcnow())
        p=json.loads(row.payload_json or '{}')
        if row.kind=='BACKTEST':
            update(db,row,progress=20); result=run_backtest(p); update(db,row,progress=90)
        elif row.kind=='SWEEP':
            update(db,row,progress=10); result=parameter_sweep(p.get('base',{}),p.get('grid',{}));
            exp=ExperimentRun(name='Parameter Sweep',kind='SWEEP',status='COMPLETED',payload_json=json.dumps(result,default=str));db.add(exp);db.commit(); result={'experiment_id':exp.id,**result}
        elif row.kind=='ROBUSTNESS':
            update(db,row,progress=10); result=robustness(p)
            exp=ExperimentRun(name='Robustness Suite',kind='ROBUSTNESS',status='COMPLETED',payload_json=json.dumps(result,default=str));db.add(exp);db.commit(); result={'experiment_id':exp.id,**result}
        elif row.kind in ('TRAIN_RIDGE','TRAIN_HGB'):
            model='ridge' if row.kind=='TRAIN_RIDGE' else 'hgb'; update(db,row,progress=15); result=train_walk_forward(model)
            last=db.query(ModelVersion).filter(ModelVersion.name==model.upper()).order_by(ModelVersion.version.desc()).first()
            mv=ModelVersion(name=model.upper(),version=(last.version+1 if last else 1),model_type=model,metrics_json=json.dumps(result,default=str));db.add(mv);db.commit();result={'model_version_id':mv.id,**result}
        elif row.kind=='DATA_REFRESH':
            from app.services.real_data import fetch_bars
            df=fetch_bars(force=True); result={'rows':len(df),'symbols':int(df.symbol.nunique()),'from':str(df.date.min()),'to':str(df.date.max())}
        elif row.kind=='DAILY_PIPELINE':
            from app.services.daily_pipeline import run_daily_pipeline
            update(db,row,progress=15); result=run_daily_pipeline(db,force_market=bool(p.get('force_market')),refresh_sec=bool(p.get('refresh_sec'))); update(db,row,progress=90)
        elif row.kind=='PAPER_SNAPSHOT':
            from app.services.monitoring import snapshot_paper
            result=snapshot_paper(db)
        elif row.kind=='SEC_REFRESH':
            from app.services.real_data import universe
            from app.services.sec_fundamentals import fundamental_events
            syms=universe(); covered=events=0
            for i,s in enumerate(syms):
                d=fundamental_events(s,force=True);events+=len(d);covered+=int(len(d)>0)
                if i%5==0:update(db,row,progress=min(90,10+int(80*(i+1)/max(1,len(syms)))))
            result={'symbols':len(syms),'covered':covered,'events':events}
        else: raise ValueError(f'Unknown job kind {row.kind}')
        update(db,row,status='COMPLETED',progress=100,result_json=json.dumps(result,default=str),completed_at=datetime.utcnow())
    except Exception as e:
        update(db,row,status='FAILED',error=str(e),result_json=json.dumps({'traceback':traceback.format_exc()}),completed_at=datetime.utcnow())
    finally: db.close()

def worker_loop():
    r=redis_client(); print('QuantLab worker ready',flush=True)
    while True:
        item=r.blpop(QUEUE,timeout=5)
        if item: execute_job(item[1])
