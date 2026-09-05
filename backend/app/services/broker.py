from __future__ import annotations
from datetime import datetime
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.entities import BrokerConnection,PaperPosition,ExecutionLog
from app.services.features import build_feature_panel

class PaperBrokerService:
    def __init__(self,db:Session): self.db=db
    def _headers(self): return {"APCA-API-KEY-ID":settings.alpaca_api_key,"APCA-API-SECRET-KEY":settings.alpaca_secret_key}
    def _conn(self):
        c=self.db.query(BrokerConnection).first()
        if not c:
            c=BrokerConnection(provider="alpaca" if self.alpaca_enabled() else "simulated")
            self.db.add(c);self.db.commit();self.db.refresh(c)
        return c
    def alpaca_enabled(self): return bool(settings.alpaca_api_key and settings.alpaca_secret_key)
    def sync_account(self):
        c=self._conn()
        if self.alpaca_enabled():
            r=httpx.get(settings.alpaca_paper_base_url+"/v2/account",headers=self._headers(),timeout=10);r.raise_for_status();d=r.json()
            c.provider="alpaca";c.equity=float(d["equity"]);c.cash=float(d["cash"]);c.buying_power=float(d["buying_power"]);c.connected=True;c.updated_at=datetime.utcnow();self.db.commit()
        return {"provider":c.provider,"environment":"PAPER","connected":c.connected,"equity":c.equity,"cash":c.cash,"buying_power":c.buying_power,
                "alpaca_credentials_configured":self.alpaca_enabled(),"data_mode":settings.data_mode,"orders_enabled":settings.allow_alpaca_paper_orders}
    def target_portfolio(self,n=20):
        df=build_feature_panel();snap=df[df.date==df.date.max()].sort_values("meta_score",ascending=False);longs=snap.head(n);shorts=snap.tail(n);w=1/n
        return ([{"symbol":r.symbol,"side":"LONG","weight":w,"score":float(r.meta_score),"price":float(r.close)} for r in longs.itertuples()]+
                [{"symbol":r.symbol,"side":"SHORT","weight":-w,"score":float(r.meta_score),"price":float(r.close)} for r in shorts.itertuples()])
    def _alpaca_positions(self):
        if not self.alpaca_enabled(): return []
        r=httpx.get(settings.alpaca_paper_base_url+"/v2/positions",headers=self._headers(),timeout=15);r.raise_for_status();return r.json()
    def sync_positions(self):
        if not self.alpaca_enabled():
            return [{"symbol":p.symbol,"side":p.side,"notional":p.notional,"weight":p.weight,"score":p.score} for p in self.db.query(PaperPosition).all()]
        account=self.sync_account();equity=max(float(account["equity"]),1e-9);remote=self._alpaca_positions()
        self.db.query(PaperPosition).delete();rows=[]
        for p in remote:
            qty=float(p.get("qty") or 0);mv=float(p.get("market_value") or 0);side="LONG" if qty>=0 else "SHORT";weight=mv/equity
            row=PaperPosition(symbol=p["symbol"],side=side,notional=abs(mv),weight=weight,score=0.0)
            self.db.add(row);rows.append({"symbol":row.symbol,"side":row.side,"notional":row.notional,"weight":row.weight,"score":row.score})
        self.db.commit();return rows
    def rebalance(self,n=20,execute=False):
        if execute: raise RuntimeError("Direct broker execution disabled. Use /api/paper/rebalance/execute so the Risk Gate cannot be bypassed.")
        targets=self.target_portfolio(n);c=self._conn();self.db.query(PaperPosition).delete()
        for t in targets:self.db.add(PaperPosition(symbol=t["symbol"],side=t["side"],notional=abs(t["weight"])*c.equity,weight=t["weight"],score=t["score"]))
        self.db.add(ExecutionLog(message=f"Preview/simulated paper rebalance: {len(targets)} target positions"));self.db.commit()
        return {"status":"preview","orders":len(targets),"mode":"PREVIEW"}
    def rebalance_simulated(self,n=20): return self.rebalance(n,False)
