from __future__ import annotations
import json
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.entities import RebalanceRun, BrokerOrder, ExecutionLog

class ExecutionService:
    def __init__(self, db: Session, broker):
        self.db=db; self.broker=broker

    def _headers(self): return self.broker._headers()

    def clock(self):
        if not self.broker.alpaca_enabled():
            return {"configured":False,"is_open":False,"message":"Alpaca credentials missing"}
        # v2 clock is stable for Trading API; retain fallback for compatibility
        r=httpx.get(settings.alpaca_paper_base_url+'/v2/clock',headers=self._headers(),timeout=10)
        r.raise_for_status(); d=r.json()
        return {"configured":True,"is_open":bool(d.get('is_open')),"timestamp":d.get('timestamp'),"next_open":d.get('next_open'),"next_close":d.get('next_close')}

    def calendar(self, start:str, end:str):
        if not self.broker.alpaca_enabled(): return []
        r=httpx.get(settings.alpaca_paper_base_url+'/v2/calendar',headers=self._headers(),params={'start':start,'end':end},timeout=10)
        r.raise_for_status(); return r.json()

    def risk_checks(self, targets, require_open=False):
        checks=[]
        checks.append({"name":"paper_environment","ok":settings.trading_env.upper()=="PAPER","detail":settings.trading_env})
        checks.append({"name":"real_market_data","ok":settings.data_mode.lower()=="alpaca","detail":settings.data_mode})
        checks.append({"name":"alpaca_credentials","ok":self.broker.alpaca_enabled(),"detail":"configured" if self.broker.alpaca_enabled() else "missing"})
        checks.append({"name":"orders_enabled","ok":settings.allow_alpaca_paper_orders,"detail":str(settings.allow_alpaca_paper_orders)})
        gross=sum(abs(float(t['weight'])) for t in targets); net=sum(float(t['weight']) for t in targets)
        checks.append({"name":"gross_exposure","ok":gross <= 2.0001,"detail":round(gross,4)})
        checks.append({"name":"net_exposure","ok":abs(net) <= .10,"detail":round(net,4)})
        checks.append({"name":"position_count","ok":0 < len(targets) <= 200,"detail":len(targets)})
        if require_open and self.broker.alpaca_enabled():
            c=self.clock(); checks.append({"name":"market_open","ok":bool(c.get('is_open')),"detail":c})
        return {"passed":all(x['ok'] for x in checks),"checks":checks}

    def preview(self,n=20):
        targets=self.broker.target_portfolio(n)
        account=self.broker.sync_account()
        equity=float(account['equity'])
        current={}
        if self.broker.alpaca_enabled():
            for p in self.broker._alpaca_positions(): current[p['symbol']]=float(p.get('market_value') or 0)
        proposed=[]; wanted={t['symbol']:float(t['weight'])*equity for t in targets}
        for sym,val in current.items():
            if sym not in wanted: proposed.append({'symbol':sym,'action':'CLOSE','current_notional':round(val,2),'target_notional':0,'delta':round(-val,2)})
        for t in targets:
            sym=t['symbol']; target=wanted[sym]; cur=current.get(sym,0.0); delta=target-cur
            if abs(delta)>=max(25,equity*.001): proposed.append({'symbol':sym,'action':'BUY' if delta>0 else 'SELL','current_notional':round(cur,2),'target_notional':round(target,2),'delta':round(delta,2),'score':round(float(t['score']),6)})
        return {'targets':targets,'proposed_orders':proposed,'account':account,'risk':self.risk_checks(targets,False)}

    def execute(self,n=20):
        preview=self.preview(n); risk=self.risk_checks(preview['targets'],True)
        if not risk['passed']: raise RuntimeError('Risk gate blocked execution: '+', '.join(x['name'] for x in risk['checks'] if not x['ok']))
        day=datetime.now(timezone.utc).strftime('%Y%m%d'); key=f'meta-us-v1-{day}-tb{n}'
        existing=self.db.query(RebalanceRun).filter_by(rebalance_key=key).first()
        if existing and existing.status in ('SUBMITTED','COMPLETED'): raise RuntimeError(f'Rebalance {key} already executed.')
        run=existing or RebalanceRun(rebalance_key=key,strategy_name='META US v1')
        run.status='RUNNING'; run.target_count=len(preview['targets']); run.payload_json=json.dumps(preview,default=str); self.db.add(run); self.db.commit()
        submitted=[]
        for idx,o in enumerate(preview['proposed_orders']):
            cid=f'ql-{day}-{n}-{idx:03d}-{o["symbol"]}'[:128]
            known=self.db.query(BrokerOrder).filter_by(client_order_id=cid).first()
            if known:
                submitted.append({'client_order_id':cid,'symbol':o['symbol'],'status':'already_known'}); continue
            if o['action']=='CLOSE':
                rr=httpx.delete(settings.alpaca_paper_base_url+f'/v2/positions/{o["symbol"]}',headers=self._headers(),timeout=15)
                payload=rr.json() if rr.content else {}; status='submitted' if rr.is_success else 'rejected'
                bo=BrokerOrder(rebalance_key=key,client_order_id=cid,broker_order_id=str(payload.get('id','')) or None,symbol=o['symbol'],side='close',notional=abs(o['delta']),status=status,payload_json=json.dumps(payload))
            else:
                payload={'symbol':o['symbol'],'notional':round(abs(o['delta']),2),'side':'buy' if o['delta']>0 else 'sell','type':'market','time_in_force':'day','client_order_id':cid}
                rr=httpx.post(settings.alpaca_paper_base_url+'/v2/orders',headers=self._headers(),json=payload,timeout=15)
                body=rr.json() if rr.content else {}; status=str(body.get('status','submitted' if rr.is_success else 'rejected'))
                bo=BrokerOrder(rebalance_key=key,client_order_id=cid,broker_order_id=body.get('id'),symbol=o['symbol'],side=payload['side'],notional=payload['notional'],status=status,payload_json=json.dumps(body))
            self.db.add(bo); submitted.append({'client_order_id':cid,'symbol':o['symbol'],'status':bo.status})
        run.status='SUBMITTED'; run.order_count=len(submitted); run.completed_at=datetime.utcnow(); self.db.add(ExecutionLog(message=f'{key}: {len(submitted)} paper actions submitted')); self.db.commit()
        return {'rebalance_key':key,'status':run.status,'orders':submitted,'risk':risk}

    def reconcile(self):
        if not self.broker.alpaca_enabled(): return {'updated':0}
        rows=self.db.query(BrokerOrder).filter(BrokerOrder.status.notin_(['filled','canceled','rejected','expired'])).all(); updated=0
        for row in rows:
            if not row.broker_order_id: continue
            r=httpx.get(settings.alpaca_paper_base_url+f'/v2/orders/{row.broker_order_id}',headers=self._headers(),timeout=10)
            if r.is_success:
                d=r.json(); row.status=d.get('status',row.status); row.payload_json=json.dumps(d); row.updated_at=datetime.utcnow(); updated+=1
        self.db.commit(); return {'updated':updated,'open_tracked':len(rows)}
