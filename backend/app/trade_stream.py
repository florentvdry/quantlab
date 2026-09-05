from __future__ import annotations
import asyncio, json
from datetime import datetime
import websockets
from app.core.config import settings
from app.db.session import Base,engine,SessionLocal
from app.models.entities import BrokerOrder,ExecutionLog,TradeFill

async def run():
    Base.metadata.create_all(bind=engine)
    if not (settings.alpaca_api_key and settings.alpaca_secret_key):
        print('Alpaca credentials missing; trade stream sleeping.',flush=True); await asyncio.sleep(3600); return
    uri='wss://paper-api.alpaca.markets/stream'
    while True:
        try:
            async with websockets.connect(uri,ping_interval=20,ping_timeout=20) as ws:
                await ws.send(json.dumps({'action':'authenticate','data':{'key_id':settings.alpaca_api_key,'secret_key':settings.alpaca_secret_key}}))
                await ws.send(json.dumps({'action':'listen','data':{'streams':['trade_updates']}}))
                async for raw in ws:
                    if isinstance(raw,bytes): raw=raw.decode('utf-8')
                    msg=json.loads(raw)
                    if msg.get('stream')!='trade_updates': continue
                    data=msg.get('data') or {}; order=data.get('order') or {}; cid=order.get('client_order_id')
                    db=SessionLocal()
                    try:
                        row=db.query(BrokerOrder).filter(BrokerOrder.client_order_id==cid).first() if cid else None
                        if row:
                            row.status=str(order.get('status') or data.get('event') or row.status);row.broker_order_id=order.get('id') or row.broker_order_id;row.payload_json=json.dumps(msg);row.updated_at=datetime.utcnow()
                        event=str(data.get('event') or '')
                        if event in ('fill','partial_fill'):
                            qty=float(data.get('qty') or order.get('filled_qty') or 0); price=float(data.get('price') or order.get('filled_avg_price') or 0)
                            db.add(TradeFill(broker_order_id=order.get('id'),client_order_id=cid,symbol=order.get('symbol',''),side=order.get('side',''),qty=qty,price=price,notional=abs(qty*price),event=event,payload_json=json.dumps(msg)))
                        db.add(ExecutionLog(message=f"trade_update {data.get('event')} {order.get('symbol','')} {cid or ''}"));db.commit()
                    finally: db.close()
        except Exception as e:
            print('trade stream reconnect',repr(e),flush=True);await asyncio.sleep(5)
if __name__=='__main__': asyncio.run(run())
