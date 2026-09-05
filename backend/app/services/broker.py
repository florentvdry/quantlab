from __future__ import annotations
from datetime import datetime
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.entities import BrokerConnection,PaperPosition,ExecutionLog
from app.services.features import build_feature_panel
class PaperBrokerService:
 def __init__(self,db:Session): self.db=db
 def _headers(self): return {'APCA-API-KEY-ID':settings.alpaca_api_key,'APCA-API-SECRET-KEY':settings.alpaca_secret_key}
 def _conn(self):
  c=self.db.query(BrokerConnection).first()
  if not c: c=BrokerConnection(provider='alpaca' if self.alpaca_enabled() else 'simulated'); self.db.add(c); self.db.commit(); self.db.refresh(c)
  return c
 def alpaca_enabled(self): return bool(settings.alpaca_api_key and settings.alpaca_secret_key)
 def sync_account(self):
  c=self._conn()
  if self.alpaca_enabled():
   r=httpx.get(settings.alpaca_paper_base_url+'/v2/account',headers=self._headers(),timeout=10); r.raise_for_status(); d=r.json(); c.provider='alpaca'; c.equity=float(d['equity']); c.cash=float(d['cash']); c.buying_power=float(d['buying_power']); c.connected=True;c.updated_at=datetime.utcnow();self.db.commit()
  return {'provider':c.provider,'environment':'PAPER','connected':c.connected,'equity':c.equity,'cash':c.cash,'buying_power':c.buying_power,'alpaca_credentials_configured':self.alpaca_enabled(),'data_mode':settings.data_mode,'orders_enabled':settings.allow_alpaca_paper_orders}
 def target_portfolio(self,n=20):
  df=build_feature_panel();snap=df[df.date==df.date.max()].sort_values('meta_score',ascending=False);longs=snap.head(n);shorts=snap.tail(n);w=1/n
  return [{'symbol':r.symbol,'side':'LONG','weight':w,'score':float(r.meta_score)} for r in longs.itertuples()]+[{'symbol':r.symbol,'side':'SHORT','weight':-w,'score':float(r.meta_score)} for r in shorts.itertuples()]
 def _alpaca_positions(self):
  r=httpx.get(settings.alpaca_paper_base_url+'/v2/positions',headers=self._headers(),timeout=15);r.raise_for_status();return r.json()
 def rebalance(self,n=20,execute=False):
  targets=self.target_portfolio(n); c=self._conn()
  if execute:
   if settings.data_mode.lower()!='alpaca': raise RuntimeError('Real Alpaca orders require DATA_MODE=alpaca.')
   if not self.alpaca_enabled(): raise RuntimeError('Alpaca Paper credentials missing.')
   if not settings.allow_alpaca_paper_orders: raise RuntimeError('Set ALLOW_ALPACA_PAPER_ORDERS=true to enable PAPER orders.')
   current={p['symbol']:float(p['market_value']) for p in self._alpaca_positions()}; equity=self.sync_account()['equity']; orders=[]
   target={t['symbol']:t['weight']*equity for t in targets}
   # close symbols no longer wanted first
   for sym,val in current.items():
    if sym not in target:
     rr=httpx.delete(settings.alpaca_paper_base_url+f'/v2/positions/{sym}',headers=self._headers(),timeout=15); orders.append({'symbol':sym,'action':'close','status':rr.status_code})
   for sym,tval in target.items():
    delta=tval-current.get(sym,0.0)
    if abs(delta)<max(25,equity*.001): continue
    payload={'symbol':sym,'notional':round(abs(delta),2),'side':'buy' if delta>0 else 'sell','type':'market','time_in_force':'day','client_order_id':f'ql-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}-{sym}'[:48]}
    rr=httpx.post(settings.alpaca_paper_base_url+'/v2/orders',headers=self._headers(),json=payload,timeout=15); orders.append({'symbol':sym,'status':rr.status_code,'response':rr.json() if rr.content else {}})
   self.db.add(ExecutionLog(message=f'Alpaca PAPER rebalance submitted: {len(orders)} actions'));self.db.commit();return {'status':'submitted','orders':len(orders),'details':orders,'mode':'ALPACA_PAPER'}
  self.db.query(PaperPosition).delete()
  for t in targets:self.db.add(PaperPosition(symbol=t['symbol'],side=t['side'],notional=abs(t['weight'])*c.equity,weight=t['weight'],score=t['score']))
  self.db.add(ExecutionLog(message=f'Preview/simulated paper rebalance: {len(targets)} target positions'));self.db.commit();return {'status':'preview','orders':len(targets),'mode':'PREVIEW'}
 def rebalance_simulated(self,n=20): return self.rebalance(n,False)
