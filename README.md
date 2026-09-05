# QuantLab V1.3

Plateforme locale de recherche quantitative sur actions US : **Data → Feature Store → Factor Research → Backtest → Walk-forward → Robustness → Validation → Alpaca Paper**.

> **Aucun chemin Live Trading n'est implémenté.** La V1.3 s'arrête volontairement à Alpaca PAPER.

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

## Interface V1.3

Le frontend a été refait avec Tailwind CSS autour d'un seul snapshot local `GET /api/app/snapshot`.

Navigation principale :

- Dashboard
- Research
- Backtests
- Signals
- Paper
- System

Le parcours normal ne demande plus de lancer une succession de boutons. L'Autopilot maintient les données et les résultats ; les actions manuelles restent secondaires.

Le polling UI ne synchronise plus Alpaca à chaque rafraîchissement : compte, positions, jobs, validations, facteurs et datasets sont lus depuis PostgreSQL / Redis / Feature Store local. Les appels broker réseau restent réservés aux synchronisations et opérations explicites.

## META V6 — challenger expérimental

V5 reste le benchmark de contrôle. V6 est un challenger research-only qui cherche surtout à améliorer Sharpe et drawdown sans modifier Paper :

- cible alpha alignée sur l'exécution réelle : signal close T, entrée open T+1, sortie open T+11 ;
- meta-label absolu : le trade doit être positif après coût round-trip estimé, pas seulement battre le marché ;
- contexte marché : breadth, dispersion, volatilité, tendance et régime ;
- choix du seuil de probabilité et du nombre maximal de positions sur validation passée uniquement ;
- sizing de confiance plus sélectif avec possibilité de rester davantage en cash ;
- stress tests coûts x2/x3 et variantes de construction de portefeuille.

V6 n'est pas utilisé par l'Autopilot ni par les signaux Paper tant qu'il n'a pas démontré une amélioration robuste par rapport à V5.

## Autopilot / workflow recommandé

Avec `AUTO_BOOTSTRAP_ENABLED=true` (défaut), aucun bouton n'est requis pour initialiser QuantLab. Au démarrage, le scheduler lance automatiquement si nécessaire :

`Market Data -> SEC best-effort -> Feature Store -> Factor Research -> META V5 -> Validation -> Signals`.

Le refresh quotidien utilise le même pipeline complet. Les boutons restent disponibles uniquement pour relancer ou comparer des expériences manuellement.

1. **Overview** — suivre l'Autopilot et la progression du job.
2. **Research / Models / Backtests / Validation / Signals** — consulter les résultats chargés automatiquement.
3. **Paper** — seulement après validation/promotion ; commencer par Preview / Risk Gate.

## Stabilisation backend V1.3

- snapshot agrégé local pour réduire fortement le nombre de requêtes frontend ;
- timeout frontend avec `AbortController` ;
- cache data portable via `QUANTLAB_DATA_DIR` ;
- ingestion Alpaca avec retries, contrôle des tokens de pagination et écritures atomiques ;
- news Alpaca best-effort : une panne news ne bloque plus le Feature Store ;
- SEC best-effort avec cache stale fallback et 404 non fatal ;
- heartbeat worker indépendant des jobs longs ;
- déduplication des jobs lourds (`AUTO_BOOTSTRAP`, `META_V5`, validation, refresh data/SEC) ;
- le promotion gate reconnaît désormais les validations produites par l'Autopilot ;
- les lectures UI n'appellent plus `sync_account()` ;
- historique Paper borné pour éviter un polling DB qui grossit sans limite.

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
- score news courant uniquement ; aucun score news récent n'est recopié dans l'historique ;
- normalisation cross-sectionnelle en percentiles ;
- Meta Score.

Chaque backtest V2 contient la provenance du dataset : mode, feed, schéma de features, période, nombre de lignes/symboles et fingerprint.

## META Ensemble V5

META V5 est la couche de recherche principale. Elle évite le simple ajustement manuel de poids après observation du backtest.

```text
Ridge --------------\
HGB -----------------+--> blend RankIC --> regime router --> EWMA --> meta-labeler --> sizing
LightGBM x3 ---------+
Momentum ------------/
```

Principes :

- nested walk-forward : base-train -> embargo -> validation -> embargo -> test ;
- target principale : rendement relatif cross-sectionnel à 20 jours ;
- LightGBM DoubleEnsemble-style : sous-modèles successifs, reweighting des exemples difficiles et feature subsets ;
- poids du blend estimés uniquement sur la validation historique ;
- router simplifié : TREND_UP, NEUTRAL, HIGH_VOL, RISK_OFF ;
- EWMA one-sided du score pour réduire les changements de rang et le turnover ;
- meta-labeler logistique : TRADE / SKIP ;
- calibration Platt sur une fenêtre tenue à l'écart avec embargo ;
- sizing probabiliste ; V5 peut volontairement garder du cash ;
- historique news exclu tant qu'un vrai historique point-in-time n'existe pas ;
- snapshot de signal courant : LOCKED_RESEARCH_SIGNAL_ONLY.

LightGBM est épinglé à 4.7.0.
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

Le Validation Gate V5 ne passe que si les contrôles essentiels passent :

- Data Quality ;
- provenance du dataset ;
- exécution next-open ;
- Sharpe >= 0,75 ;
- CAGR >= 5 % ;
- OOS Rank IC >= 0,02 et stabilité des folds ;
- drawdown >= -25 % ;
- excess CAGR > benchmark equal-weight ;
- turnover moyen <= 35 % ;
- meta-filter non dégénéré ;
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
- Autopilot complet au premier démarrage si les artefacts de recherche manquent ;
- refresh complet quotidien après clôture US ;
- SEC refresh best-effort selon le jour configuré : un ticker sans `companyfacts` ne bloque jamais le pipeline ;
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
- `GET /api/app/snapshot`
- `GET /ready`
- `GET /api/setup`
- `POST /api/jobs/bootstrap`
- `POST /api/jobs/daily-pipeline`
- `GET /api/data/quality`
- `GET /api/research/factors`
- `POST /api/jobs/train/ridge`
- `POST /api/jobs/train/hgb`
- `POST /api/jobs/meta-v5`
- `POST /api/jobs/meta-v5-signals`
- `GET /api/meta-v5/signals`
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

## Limites V1.3

- Univers réel volontairement encore limité / curated avant montée en charge.
- Feed Alpaca configurable ; IEX n'est pas l'intégralité du marché US.
- Le score news courant reste heuristique et n'est pas utilisé historiquement sans archive point-in-time.
- Aucun modèle ne garantit une performance future.
- Paper Trading est une simulation et ne reproduit pas parfaitement l'exécution réelle.
- **Live Trading : non implémenté.**
