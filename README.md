# QuantLab V1.1

Plateforme locale de recherche quantitative sur actions US : **Data → Feature Store → Factor Research → Backtest → Walk-forward → Robustness → Validation → Alpaca Paper**.

> **Aucun chemin Live Trading n'est implémenté.** La V1.1 s'arrête volontairement à Alpaca PAPER.

## Démarrage Windows / PowerShell

```powershell
git pull
Copy-Item .env.example .env   # uniquement si .env n'existe pas encore
docker compose down
docker compose up --build --force-recreate
```

UI : `http://localhost:3000`  
API / Swagger : `http://localhost:8000/docs`

Vérifications :

```powershell
docker compose ps
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:8000/ready
```

Tests quant :

```powershell
docker compose exec api pytest -q
```

## Configuration sûre par défaut

```env
DATA_MODE=synthetic
TRADING_ENV=PAPER
ALLOW_ALPACA_PAPER_ORDERS=false
PAPER_AUTO_ENABLED=false
```

Le mode `synthetic` sert uniquement à tester l'infrastructure et les calculs. Ses performances n'ont aucune signification financière.

## Données réelles Alpaca + SEC

Dans `.env` :

```env
DATA_MODE=alpaca
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_FEED=iex
REAL_HISTORY_YEARS=5
REAL_UNIVERSE_SIZE=60

# Remplacer obligatoirement par une vraie identité/contact pour SEC EDGAR
SEC_USER_AGENT=QuantLab Florent contact@example.com

ALLOW_ALPACA_PAPER_ORDERS=false
PAPER_AUTO_ENABLED=false
```

Puis :

```powershell
docker compose down
docker compose up --build --force-recreate
```

Les credentials doivent être ceux d'**Alpaca Paper**. Ne publie jamais tes clés dans Git ou dans un ticket.

## Workflow recommandé

1. **Overview** — vérifier Setup / Readiness.
2. **Data** — lancer `Daily Pipeline`, vérifier Market Data, SEC et Data Quality.
3. **Research** — inspecter Rank IC, IC IR, ratio d'IC positifs et spread Top-Bottom.
4. **Models** — entraîner Ridge / HGB avec walk-forward temporel.
5. **Backtests** — comparer META US v2 à la baseline Momentum 12-1.
6. **Validation** — lancer le Validation Gate complet.
7. **Signals** — inspecter le ranking courant et l'explication par ticker.
8. **Paper** — seulement après validation/promotion ; commencer par Preview / Risk Gate.

## Anti-lookahead

Les règles V1.1 sont explicites :

- les targets futures sont calculées **par symbole** ;
- les fondamentaux SEC sont disponibles à partir de leur date de filing (`available_at`) ;
- aucune valeur fondamentale future n'est backfillée dans le passé ;
- le signal est formé au **close T** ;
- l'exécution du backtest se fait au **prochain open T+1** ;
- les splits ML sont temporels, jamais mélangés aléatoirement.

## Feature Store

Familles principales :

- rendements 5/20/60/120/252 jours ;
- momentum 12-1 ;
- SMA 50/200, trend ;
- volatilité 20/60 jours ;
- liquidité dollar-volume ;
- fondamentaux SEC point-in-time ;
- earnings EPS point-in-time ;
- score news ;
- normalisation cross-sectionnelle en percentiles ;
- Meta Score.

Chaque backtest V2 contient la provenance du dataset : mode, feed, schéma de features, période, nombre de lignes/symboles et fingerprint.

## Backtest V2

Le portefeuille est Top/Bottom cross-sectionnel long/short. Paramètres :

- `long_count`
- `short_count`
- `rebalance_days`
- `commission_bps`
- `slippage_bps`
- `gross_exposure`

Métriques : total return, CAGR, volatilité, Sharpe, Sortino, Calmar, Max Drawdown, turnover, coûts et Rank IC.

Une baseline **Momentum 12-1** est disponible et doit être comparée au Meta Score.

## Walk-forward / Models

`Ridge` et `HistGradientBoostingRegressor` utilisent un vrai découpage temporel expanding-window. QuantLab conserve les métriques OOS par fold, notamment Rank IC et IC IR.

## Robustness / Validation Gate

Le Validation Gate ne passe que si les contrôles essentiels passent :

- Data Quality ;
- provenance du dataset ;
- exécution next-open ;
- Sharpe positif ;
- Rank IC positif ;
- walk-forward OOS positif ;
- drawdown borné ;
- Meta >= baseline ;
- robustesse de paramètres ;
- coûts x2/x3 encore acceptables.

Un résultat `BLOCKED` est normal : QuantLab ne doit pas promouvoir une stratégie simplement parce qu'un backtest isolé semble bon.

## Alpaca PAPER

L'exécution est centralisée dans `ExecutionService`; l'ancien chemin direct broker ne peut plus contourner le Risk Gate.

Le Risk Gate contrôle notamment :

- environnement PAPER ;
- `DATA_MODE=alpaca` ;
- credentials ;
- activation explicite des ordres ;
- gross/net exposure ;
- fraîcheur des données ;
- stratégie promue PAPER ;
- assets tradables / shorts shortables ;
- absence d'ordres ouverts conflictuels ;
- buying power ;
- marché ouvert au moment d'exécuter.

Les ordres utilisent des `client_order_id` déterministes et les états/fills sont suivis par le stream `trade_updates` puis réconciliés avec REST.

### Kill switch PAPER

Le dashboard expose :

- Cancel Open Orders ;
- Flatten PAPER Portfolio.

Le flatten exige une confirmation explicite et reste limité à PAPER en V1.

## Scheduler

Le scheduler conserve ses états dans PostgreSQL afin qu'un redémarrage Docker ne répète pas automatiquement une tâche déjà exécutée.

- Daily Pipeline après clôture US ;
- SEC refresh selon le jour configuré ;
- snapshots Paper ;
- réconciliation périodique des ordres ;
- rebalance Paper automatique uniquement si `PAPER_AUTO_ENABLED=true` **et** que le Risk Gate passe.

## Jobs et messages UI

Les tâches lourdes passent par Redis et exposent :

- `QUEUED`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- progression en % ;
- message d'étape (`Téléchargement des données`, `Construction du Feature Store`, `Validation`, etc.).

Le frontend affiche `Chargement…`, `Backtest en cours…`, `Pipeline en cours…`, erreurs et progression.

## Health / Docker

Les services Postgres, Redis, API et Web ont des healthchecks ; les services persistants utilisent `restart: unless-stopped`.

## CI GitHub

`.github/workflows/ci.yml` exécute automatiquement :

- compilation Python ;
- tests `pytest` anti-lookahead/exécution/coûts ;
- build Next.js.

Cela doit notamment empêcher qu'une erreur JSX comme une accolade manquante soit fusionnée sans être détectée.

## Endpoints utiles

- `GET /health`
- `GET /ready`
- `GET /api/setup`
- `POST /api/jobs/daily-pipeline`
- `GET /api/data/quality`
- `GET /api/research/factors`
- `POST /api/jobs/train/ridge`
- `POST /api/jobs/train/hgb`
- `POST /api/jobs/backtest`
- `POST /api/jobs/baseline`
- `POST /api/jobs/robustness`
- `POST /api/jobs/validation`
- `GET /api/validation/latest`
- `GET /api/factors/{symbol}/explain`
- `GET /api/paper/rebalance/preview`
- `POST /api/paper/rebalance/execute`
- `POST /api/paper/reconcile`
- `POST /api/paper/kill/cancel-orders`
- `POST /api/paper/kill/flatten?confirm=FLATTEN_PAPER`

## Limites V1.1

- Univers réel volontairement encore limité / curated avant montée en charge.
- Feed Alpaca configurable ; IEX n'est pas l'intégralité du marché US.
- Le score news reste heuristique.
- Aucun modèle ne garantit une performance future.
- Paper Trading est une simulation et ne reproduit pas parfaitement l'exécution réelle.
- **Live Trading : non implémenté.**
