from __future__ import annotations
import hashlib, json
from datetime import datetime
from app.models.entities import SystemState
from app.services.json_utils import safe_dumps


def set_state(db, key:str, value:dict):
    row=db.query(SystemState).filter(SystemState.key==key).first()
    if not row:
        row=SystemState(key=key); db.add(row)
    row.value_json=safe_dumps(value,sort_keys=True); row.updated_at=datetime.utcnow(); db.commit()
    return value


def get_state(db,key:str,default=None):
    row=db.query(SystemState).filter(SystemState.key==key).first()
    if not row:return default
    try:return json.loads(row.value_json)
    except Exception:return default


def fingerprint(payload:dict):
    return hashlib.sha256(safe_dumps(payload,sort_keys=True).encode()).hexdigest()[:16]


def states(db):
    rows=db.query(SystemState).order_by(SystemState.key).all(); out={}
    for r in rows:
        try: out[r.key]={**json.loads(r.value_json), 'updated_at':r.updated_at}
        except Exception: out[r.key]={'value':r.value_json,'updated_at':r.updated_at}
    return out
