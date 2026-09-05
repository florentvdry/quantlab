from __future__ import annotations
import asyncio,json
from datetime import datetime
import websockets
from app.core.config import settings
from app.db.session import Base,engine,SessionLocal
from app.models.entities import BrokerOrder,ExecutionLog,TradeFill

async def run():
    Base.metadata.create_all(bind=engine)
    uri="wss://paper-api.alpaca.markets/stream"
    while True:
        if not (settings.alpaca_api_key and settings.alpaca_secret_key):
            print("Alpaca credentials missing; trade stream idle.",flush=True);await asyncio.sleep(60);continue
        try:
            async with websockets.connect(uri,ping_interval=20,ping_timeout=20,max_size=2**20) as ws:
                await ws.send(json.dumps({"action":"authenticate","data":{"key_id":settings.alpaca_api_key,"secret_key":settings.alpaca_secret_key}}))
                await ws.send(json.dumps({"action":"listen","data":{"streams":["trade_updates"]}}))
                print("Alpaca PAPER trade stream connected",flush=True)
                async for raw in ws:
                    if isinstance(raw,bytes): raw=raw.decode("utf-8")
                    msg=json.loads(raw)
                    if msg.get("stream")!="trade_updates":continue
                    data=msg.get("data") or {};order=data.get("order") or {};cid=order.get("client_order_id");event=str(data.get("event") or "")
                    db=SessionLocal()
                    try:
                        row=db.query(BrokerOrder).filter(BrokerOrder.client_order_id==cid).first() if cid else None
                        if row:
                            row.status=str(order.get("status") or event or row.status);row.broker_order_id=order.get("id") or row.broker_order_id;row.payload_json=json.dumps(msg);row.updated_at=datetime.utcnow()
                        if event in ("fill","partial_fill"):
                            qty=float(data.get("qty") or order.get("filled_qty") or 0);price=float(data.get("price") or order.get("filled_avg_price") or 0)
                            duplicate=db.query(TradeFill).filter(TradeFill.client_order_id==cid,TradeFill.event==event,TradeFill.qty==qty,TradeFill.price==price).first() if cid else None
                            if not duplicate:
                                db.add(TradeFill(broker_order_id=order.get("id"),client_order_id=cid,symbol=order.get("symbol","") ,side=order.get("side","") ,qty=qty,price=price,notional=abs(qty*price),event=event,payload_json=json.dumps(msg)))
                        db.add(ExecutionLog(message=f"trade_update {event} {order.get('symbol','')} {cid or ''}"));db.commit()
                    finally:db.close()
        except Exception as e:
            print("trade stream reconnect",repr(e),flush=True);await asyncio.sleep(5)

if __name__=="__main__":asyncio.run(run())
