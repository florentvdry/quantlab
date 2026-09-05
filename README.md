# Quant Lab V1 — local Docker

Plateforme locale actions US : données, features cross-sectionnelles, Meta Score, backtests long/short et Alpaca Paper.

## 1. Test immédiat sans compte
```bash
cp .env.example .env
docker compose up --build
```
UI http://localhost:3000 — API http://localhost:8000/docs

Le mode `synthetic` permet de vérifier toute la chaîne sans API externe.

## 2. Vraies actions US + Alpaca Paper
Crée des clés **Paper** Alpaca, puis dans `.env` :
```env
DATA_MODE=alpaca
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_FEED=iex
REAL_HISTORY_YEARS=5
REAL_UNIVERSE_SIZE=60
ALLOW_ALPACA_PAPER_ORDERS=false
```
Redémarre :
```bash
docker compose down
docker compose up --build
```
Le moteur télécharge alors les daily bars Alpaca des actions de l'univers réel, les met en cache dans le volume Docker et calcule momentum, trend, volatilité, liquidité et news score.

### Activer les ordres Paper
Après avoir vérifié le ranking et le preview :
```env
ALLOW_ALPACA_PAPER_ORDERS=true
```
Puis redémarre. Le bouton `Execute PAPER` devient disponible. **Le code n'utilise que `paper-api.alpaca.markets`; aucun endpoint live n'est configuré.**

## Garde-fous
- impossible d'envoyer des ordres si `DATA_MODE != alpaca` ;
- impossible sans clés Alpaca ;
- impossible si `ALLOW_ALPACA_PAPER_ORDERS != true` ;
- confirmation UI avant envoi ;
- `client_order_id` sur les ordres ;
- environnement PAPER figé.

## Ce que la V1 calcule réellement
- rendements 5/20/60/120/252 jours ;
- momentum 12-1 ;
- SMA 50/200 et tendances ;
- volatilité 20/60 jours ;
- liquidité dollar-volume ;
- normalisation cross-sectionnelle percentile ;
- score news simple avec décroissance temporelle ;
- Meta Score ;
- Top/Bottom long-short ;
- coûts commission + slippage ;
- CAGR, Sharpe, volatilité, drawdown, turnover, Rank IC ;
- portefeuille cible ;
- preview puis exécution Alpaca Paper.

## Limite importante de cette livraison
Les fondamentaux/earnings historiques point-in-time ne sont **pas inventés**. En mode Alpaca réel, leur poids est neutre tant qu'un dataset fondamental point-in-time n'est pas chargé. C'est volontaire : utiliser des fondamentaux actuels dans un backtest historique créerait du look-ahead bias. Le prochain module à ajouter est le pipeline SEC/EDGAR point-in-time et/ou un provider d'estimates historiques.

## Execution safety / Paper trading

The V1 now has a persistent paper execution layer: rebalance previews, risk gates, Alpaca market clock/calendar, deterministic rebalance keys, persistent client order IDs, duplicate-execution protection, tracked broker orders and reconciliation.

Useful endpoints:
- `GET /api/paper/rebalance/preview?n=20`
- `POST /api/paper/rebalance/execute?n=20`
- `POST /api/paper/reconcile`
- `GET /api/paper/orders`
- `GET /api/paper/rebalances`
- `GET /api/paper/clock`
- `GET /api/paper/calendar?start=2026-09-01&end=2026-09-30`

Execution remains impossible unless `DATA_MODE=alpaca`, `TRADING_ENV=PAPER`, valid Alpaca paper credentials are present, `ALLOW_ALPACA_PAPER_ORDERS=true`, and the risk gate passes. The execution endpoint also requires the US market to be open.

## V1 operations added

- Persistent Paper portfolio snapshots and equity history.
- Backtest vs Paper return comparison endpoint/UI.
- Strategy promotion gate: data-quality + existing backtest + Sharpe/drawdown checks.
- Background Paper snapshot job.
- Dashboard now polls jobs, strategy registry, paper performance and execution state.
- Alpaca market hours must be read from its clock/calendar APIs; the scheduler does not assume every weekday is a trading day.

Useful endpoints:
- `POST /api/paper/snapshot`
- `GET /api/paper/performance`
- `GET /api/compare/paper-vs-backtest`
- `GET /api/strategies/{id}/promotion-gate`
- `POST /api/jobs/paper-snapshot`

## V1 complete operating loop

The stack now includes a daily post-close research pipeline, persisted dataset/feature fingerprints, data-quality gate, background jobs, strategy/model registries, factor research, parameter sweeps/robustness, walk-forward ML, Alpaca Paper preview/auto execution, trade-update streaming, persisted fills, portfolio snapshots, and paper-vs-backtest monitoring.

Recommended safe first run:
1. Keep `DATA_MODE=synthetic`, `ALLOW_ALPACA_PAPER_ORDERS=false`, `PAPER_AUTO_ENABLED=false`.
2. `docker compose up --build` and validate research/backtests.
3. Add Alpaca PAPER credentials and a real SEC contact user-agent, then switch `DATA_MODE=alpaca`.
4. Run the Daily Pipeline and inspect Data Quality.
5. Keep orders locked while reviewing rankings and rebalance previews.
6. Only then set `ALLOW_ALPACA_PAPER_ORDERS=true`. `TRADING_ENV` remains PAPER in V1.

No live-money execution path is intentionally exposed by this V1.
