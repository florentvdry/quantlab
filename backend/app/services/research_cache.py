from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from app.services.json_utils import safe_dumps

ROOT=Path(os.getenv("QUANTLAB_DATA_DIR","/data"))/"research_cache"
ROOT.mkdir(parents=True,exist_ok=True)


def make_key(namespace:str,dataset_fingerprint:str,version:str,config:dict,extra:dict|None=None)->str:
    payload={
        "namespace":namespace,
        "dataset_fingerprint":dataset_fingerprint,
        "version":version,
        "config":config,
        "extra":extra or {},
    }
    raw=safe_dumps(payload,sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _paths(namespace:str):
    safe="".join(ch if ch.isalnum() or ch in ("-","_") else "_" for ch in namespace)
    return ROOT/f"{safe}.parquet",ROOT/f"{safe}.json"


def load(namespace:str,key:str):
    parquet_path,meta_path=_paths(namespace)
    if not parquet_path.exists() or not meta_path.exists():
        return None
    try:
        meta=json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("key")!=key:
            return None
        frame=pd.read_parquet(parquet_path)
        research=meta.get("research")
        if not isinstance(research,dict):
            return None
        return frame,research,meta
    except Exception:
        return None


def save(namespace:str,key:str,frame:pd.DataFrame,research:dict,dataset_fingerprint:str):
    parquet_path,meta_path=_paths(namespace)
    tmp_parquet=parquet_path.with_suffix(".parquet.tmp")
    tmp_meta=meta_path.with_suffix(".json.tmp")

    frame.to_parquet(tmp_parquet,index=False)
    tmp_meta.write_text(
        safe_dumps({
            "key":key,
            "dataset_fingerprint":dataset_fingerprint,
            "stored_at":pd.Timestamp.utcnow().isoformat(),
            "rows":int(len(frame)),
            "research":research,
        }),
        encoding="utf-8",
    )
    os.replace(tmp_parquet,parquet_path)
    os.replace(tmp_meta,meta_path)
    return {"key":key,"rows":int(len(frame)),"path":str(parquet_path)}
