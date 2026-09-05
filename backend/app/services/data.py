from __future__ import annotations
import numpy as np
import pandas as pd
from functools import lru_cache
from app.core.config import settings

SECTORS = ["Technology", "Financials", "Healthcare", "Industrials", "Consumer", "Energy"]

@lru_cache(maxsize=1)
def synthetic_panel() -> pd.DataFrame:
    rng = np.random.default_rng(settings.synthetic_seed)
    n = max(40, settings.synthetic_symbols)
    days = int(settings.synthetic_years * 252)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    symbols = [f"US{i:03d}" for i in range(1, n + 1)]
    rows = []
    market = rng.normal(0.00025, 0.010, days)
    sector_factors = {s: rng.normal(0, 0.004, days) for s in SECTORS}
    for i, sym in enumerate(symbols):
        sector = SECTORS[i % len(SECTORS)]
        quality = rng.normal(0, 1)
        value = rng.normal(0, 1)
        growth = rng.normal(0, 1)
        news_bias = rng.normal(0, .25)
        beta = np.clip(rng.normal(1.0, 0.25), 0.4, 1.8)
        alpha = 0.00008*quality + 0.00005*growth + 0.00003*value
        eps = rng.normal(0, 0.012, days)
        rets = beta*market + sector_factors[sector] + alpha + eps
        prices = 30*np.exp(np.cumsum(rets))
        vols = rng.lognormal(15.5, 0.5, days)
        news = np.clip(news_bias + rng.normal(0, .45, days) + np.sign(rets)*0.2, -1, 1)
        earnings = np.clip(0.3*quality + rng.normal(0, 0.5, days), -1.5, 1.5)
        fundamental = np.clip(0.45*quality + .25*growth + .2*value + rng.normal(0,.25,days), -2, 2)
        for j, d in enumerate(dates):
            p = prices[j]
            intraday = abs(rng.normal(0.008, 0.004))
            rows.append((d, sym, sector, p*(1-rng.normal(0,0.002)), p*(1+intraday), p*(1-intraday), p, vols[j], fundamental[j], earnings[j], news[j]))
    return pd.DataFrame(rows, columns=["date","symbol","sector","open","high","low","close","volume","fundamental_raw","earnings_raw","news_raw"])

def latest_snapshot() -> pd.DataFrame:
    df = synthetic_panel()
    return df[df.date == df.date.max()].copy()
