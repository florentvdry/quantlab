from __future__ import annotations

import json
import math
from decimal import Decimal
from numbers import Real

import numpy as np


def json_safe(value):
    """Recursively normalize values to strict JSON.

    Python's json module accepts NaN/Infinity by default, while Starlette's
    JSONResponse intentionally rejects them. Quant metrics can legitimately
    produce non-finite values for undefined ratios, so the API boundary maps
    those values to null instead of crashing the whole snapshot.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, np.generic):
        return json_safe(value.item())

    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return float(value)

    if isinstance(value, Real):
        number=float(value)
        return number if math.isfinite(number) else None

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key,item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    return value


def safe_dumps(value, **kwargs):
    kwargs.setdefault("default", str)
    kwargs["allow_nan"]=False
    return json.dumps(json_safe(value), **kwargs)
