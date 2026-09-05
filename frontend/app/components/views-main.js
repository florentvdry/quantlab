'use client'

import { Activity, CheckCircle2, Cpu, Database, Gauge, ShieldAlert, TrendingUp, XCircle } from 'lucide-react'
import { Badge, Empty, Panel, PanelHeader, Readiness, SectionHeading, Stat, TableWrap, cn, tdClass, thClass, tableClass } from './ui'
import { money, num, pct, safeArray } from '../lib/format'

function LatestBacktest({backtest}){
  if(!backtest)return <Panel><PanelHeader title="Dernier backtest"/><Empty>Aucun backtest disponible.</Empty></Panel>
  const metrics=backtest.metrics||{}
  const items=[
    ['CAGR',pct(backtest.cagr)],
    ['Max DD',pct(backtest.max_drawdown)],
    ['Excess CAGR',pct(metrics.excess_cagr_vs_equal_weight)],
    ['Capital final',money(metrics.ending_capital_usd)],
  ]
  return <Panel>
    <PanelHeader title={backtest.strategy||'Dernier backtest'} eyebrow="Performance OOS" aside={<Badge tone={Number(backtest.sharpe)>=.75?'good':'warn'}>Sharpe {num(backtest.sharpe,2)}</Badge>}/>
    <div className="grid grid-cols-2 gap-px bg-white/6 sm:grid-cols-4">
      {items.map(item=><div key={item[0]} className="bg-[#0d1015] p-4"><div className="text-[11px] text-slate-500">{item[0]}</div><div className="mt-1 text-sm font-semibold text-slate-100">{item[1]}</div></div>)}
    </div>
    <div className="flex flex-wrap items-center gap-2 px-5 py-4 text-xs text-slate-500">
      <Database className="h-3.5 w-3.5"/><span>{backtest.dataset?.mode||'—'}</span><span>·</span><span>{backtest.dataset?.backtest_from||backtest.dataset?.from||'?'}</span><span>→</span><span>{backtest.dataset?.backtest_to||backtest.dataset?.to||'?'}</span>
    </div>
  </Panel>
}

function SignalsPreview({signals,onOpen}){
  const rows=safeArray(signals?.accepted_signals).slice(0,8)
  return <Panel>
    <PanelHeader title="Signaux actuels" eyebrow="META V5" aside={<Badge tone={rows.length?'good':'neutral'}>{signals?.accepted_count||0} acceptés</Badge>}/>
    {!rows.length?<Empty>Aucun signal accepté pour le snapshot courant.</Empty>:<div className="divide-y divide-white/5">
      {rows.map(row=><button key={row.symbol} onClick={()=>onOpen(row.symbol)} className="flex w-full items-center gap-3 px-5 py-3 text-left transition hover:bg-white/[0.025]">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-xs font-bold text-white">{row.symbol.slice(0,2)}</div>
        <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><b className="text-sm text-white">{row.symbol}</b><Badge>{row.regime}</Badge></div><div className="mt-1 text-[11px] text-slate-500">score {num(row.smooth_score,3)} · size {pct(row.position_scale)}</div></div>
        <div className="text-right"><div className="text-sm font-semibold text-emerald-300">{pct(row.meta_probability)}</div><div className="text-[10px] text-slate-600">TRADE</div></div>
      </button>)}
    </div>}
  </Panel>
}

function FactorPreview({factorResearch}){
  const rows=safeArray(factorResearch?.factors).filter(x=>x.mean_rank_ic!=null).sort((a,b)=>Number(b.mean_rank_ic)-Number(a.mean_rank_ic)).slice(0,6)
  return <Panel>
    <PanelHeader title="Facteurs les plus utiles" eyebrow="Rank IC"/>
    {!rows.length?<Empty>Factor Research en attente.</Empty>:<div className="space-y-3 p-5">
      {rows.map(row=><div key={row.feature}>
        <div className="mb-1.5 flex items-center justify-between gap-4 text-xs"><span className="truncate text-slate-300">{row.feature.replaceAll('_',' ')}</span><span className={Number(row.mean_rank_ic)>0?'text-emerald-300':'text-rose-300'}>{num(row.mean_rank_ic,4)}</span></div>
        <div className="h-1.5 overflow-hidden rounded-full bg-white/5"><div className="h-full rounded-full bg-indigo-400" style={{width:Math.min(100,Math.max(4,Math.abs(Number(row.mean_rank_ic))*900))+'%'}}/></div>
      </div>)}
    </div>}
  </Panel>
}

function PipelinePanel({snapshot}){
  const jobs=safeArray(snapshot?.jobs)
  const latest=jobs.find(j=>j.status==='RUNNING'||j.status==='QUEUED')||jobs[0]
  return <Panel>
    <PanelHeader title="Autopilot" eyebrow="Data → Research → Validation → Signals" aside={<Badge tone={snapshot?.system?.auto_bootstrap_enabled?'good':'bad'}>{snapshot?.system?.auto_bootstrap_enabled?'ACTIVE':'OFF'}</Badge>}/>
    <div className="p-5">
      <Readiness steps={safeArray(snapshot?.readiness?.steps)}/>
      <div className="mt-5 rounded-xl border border-white/6 bg-black/15 p-4">
        <div className="flex items-center gap-3">
          <div className={cn('flex h-9 w-9 items-center justify-center rounded-xl',latest?.status==='FAILED'?'bg-rose-500/10 text-rose-300':'bg-indigo-500/10 text-indigo-300')}>{latest?.status==='FAILED'?<ShieldAlert className="h-4 w-4"/>:<Activity className="h-4 w-4"/>}</div>
          <div className="min-w-0 flex-1"><div className="text-xs font-semibold text-slate-200">{latest?.kind||'Aucun job récent'}</div><div className="mt-1 truncate text-[11px] text-slate-500">{latest?.error||latest?.message||'QuantLab est à jour.'}</div></div>
          {latest&&<span className="text-xs text-slate-500">{latest.progress||0}%</span>}
        </div>
      </div>
    </div>
  </Panel>
}

export function DashboardView({snapshot,onSignal}){
  const last=snapshot?.backtests?.[0]
  const validation=snapshot?.validation||{}
  const quality=snapshot?.quality||{}
  const accepted=snapshot?.signals?.accepted_count||0
  const fs=snapshot?.readiness?.feature_store||{}
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><div className="text-xs font-semibold uppercase tracking-[.18em] text-indigo-300">Quant research workspace</div><h1 className="mt-2 text-3xl font-semibold tracking-[-.035em] text-white">Tout ce qui compte, au même endroit.</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">L’autopilot maintient les données, entraîne META V5, valide la stratégie et produit les signaux. Les actions manuelles sont secondaires.</p></div>
      <div className="text-right text-xs text-slate-600"><div>Feature Store</div><div className="mt-1 text-slate-400">{fs.ready?'ready · schema '+fs.expected_schema:'not ready'}</div></div>
    </div>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Paper equity" value={money(snapshot?.account?.equity)} sub={snapshot?.account?.provider||'local cache'}/>
      <Stat label="Dernier Sharpe" value={num(last?.sharpe,2)} sub={last?last.strategy:'aucun backtest'} tone={Number(last?.sharpe)>=.75?'good':Number(last?.sharpe)>0?'warn':'bad'}/>
      <Stat label="Validation" value={validation.tier||'NOT RUN'} sub={validation.passed?'Paper eligible':'Research gate'} tone={validation.passed?'good':validation.tier==='CANDIDATE'?'warn':'bad'}/>
      <Stat label="Signaux acceptés" value={String(accepted)} sub={snapshot?.signals?.market_date||'pas de snapshot'} tone={accepted>0?'info':'default'}/>
    </div>
    <div className="grid gap-4 xl:grid-cols-[1.25fr_.75fr]"><LatestBacktest backtest={last}/><SignalsPreview signals={snapshot?.signals} onOpen={onSignal}/></div>
    <div className="grid gap-4 xl:grid-cols-2"><FactorPreview factorResearch={snapshot?.factor_research}/><PipelinePanel snapshot={snapshot}/></div>
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel className="p-5"><div className="flex items-center gap-2 text-xs font-semibold text-slate-300"><Database className="h-4 w-4 text-indigo-300"/>Données</div><div className="mt-4 text-2xl font-semibold text-white">{snapshot?.datasets?.features?.rows?.toLocaleString?.()||snapshot?.datasets?.features?.rows||'—'}</div><div className="mt-1 text-xs text-slate-500">lignes · {snapshot?.datasets?.features?.symbols||'—'} symboles</div><div className="mt-4 text-xs text-slate-600">Dernière date : {snapshot?.datasets?.features?.latest||'—'}</div></Panel>
      <Panel className="p-5"><div className="flex items-center gap-2 text-xs font-semibold text-slate-300"><Gauge className="h-4 w-4 text-emerald-300"/>Data Quality</div><div className={cn('mt-4 text-2xl font-semibold',quality.status==='PASS'?'text-emerald-300':'text-amber-300')}>{quality.status||'NOT READY'}</div><div className="mt-2 text-xs text-slate-500">{safeArray(quality.checks).filter(x=>x.ok).length}/{safeArray(quality.checks).length} checks OK</div></Panel>
      <Panel className="p-5"><div className="flex items-center gap-2 text-xs font-semibold text-slate-300"><Cpu className="h-4 w-4 text-sky-300"/>Runtime</div><div className="mt-4 flex items-center gap-2"><Badge tone={snapshot?.system?.worker_online?'good':'bad'}>{snapshot?.system?.worker_online?'ONLINE':'OFFLINE'}</Badge><Badge>{snapshot?.system?.queue_depth??'—'} queued</Badge></div><div className="mt-4 text-xs text-slate-600">Mode {snapshot?.system?.data_mode?.toUpperCase()} · Redis {snapshot?.system?.redis?'OK':'KO'}</div></Panel>
    </div>
  </div>
}

export function ResearchView({snapshot}){
  const factors=safeArray(snapshot?.factor_research?.factors)
  const models=safeArray(snapshot?.models)
  const checks=safeArray(snapshot?.validation?.checks)
  return <div className="space-y-6">
    <SectionHeading title="Research" description="Facteurs, modèles et validation OOS. Les résultats sont chargés automatiquement."/>
    <div className="grid gap-4 xl:grid-cols-[1.25fr_.75fr]">
      <Panel><PanelHeader title="Factor Research" eyebrow="Cross-sectional"/>{!factors.length?<Empty>Autopilot n’a pas encore produit le rapport.</Empty>:<TableWrap><table className={tableClass}><thead><tr><th className={thClass}>Factor</th><th className={thClass}>Mean IC</th><th className={thClass}>IC IR</th><th className={thClass}>IC positif</th><th className={thClass}>Spread 20D</th></tr></thead><tbody>{factors.map(row=><tr key={row.feature} className="hover:bg-white/[0.02]"><td className={cn(tdClass,'font-medium text-slate-200')}>{row.feature}</td><td className={cn(tdClass,Number(row.mean_rank_ic)>=0?'text-emerald-300':'text-rose-300')}>{num(row.mean_rank_ic,4)}</td><td className={tdClass}>{num(row.ic_ir,3)}</td><td className={tdClass}>{pct(row.positive_ic_ratio)}</td><td className={tdClass}>{pct(row.top_bottom_future_20d)}</td></tr>)}</tbody></table></TableWrap>}</Panel>
      <Panel><PanelHeader title="Model registry" eyebrow="Versions"/>{!models.length?<Empty>Aucun modèle persisté.</Empty>:<div className="divide-y divide-white/5">{models.slice(0,12).map(model=><div key={model.id} className="flex items-center gap-3 px-5 py-3"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-300"><Cpu className="h-4 w-4"/></div><div className="min-w-0 flex-1"><div className="text-sm font-medium text-slate-200">{model.name} <span className="text-slate-600">v{model.version}</span></div><div className="mt-1 text-[11px] text-slate-500">{model.type} · OOS IC {num(model.metrics?.oos_mean_rank_ic,4)}</div></div><Badge tone={model.status==='PAPER'?'good':'neutral'}>{model.status}</Badge></div>)}</div>}</Panel>
    </div>
    <Panel><PanelHeader title="Validation Gate" eyebrow={snapshot?.validation?.candidate_strategy||'META V5'} aside={<Badge tone={snapshot?.validation?.passed?'good':'bad'}>{snapshot?.validation?.tier||'NOT RUN'}</Badge>}/>{!checks.length?<Empty>Validation en attente.</Empty>:<div className="grid gap-px bg-white/6 sm:grid-cols-2 lg:grid-cols-3">{checks.map(check=><div key={check.name} className="flex items-start gap-3 bg-[#0d1015] p-4">{check.ok?<CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300"/>:<XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-300"/>}<div className="min-w-0"><div className="text-xs font-medium text-slate-200">{check.name.replaceAll('_',' ')}</div><div className="mt-1 max-h-14 overflow-hidden text-[10px] leading-4 text-slate-600">{typeof check.detail==='object'?JSON.stringify(check.detail):String(check.detail??'')}</div></div></div>)}</div>}</Panel>
  </div>
}

export function SignalsView({snapshot,onSignal}){
  const signals=safeArray(snapshot?.signals?.signals)
  const threshold=snapshot?.signals?.training?.meta_threshold
  return <div className="space-y-6">
    <SectionHeading title="Signals" description="Snapshot META V5 courant : décision, probabilité calibrée, taille et régime."/>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Market date" value={snapshot?.signals?.market_date||'—'} sub="latest scored close"/>
      <Stat label="Accepted" value={String(snapshot?.signals?.accepted_count||0)} sub={signals.length+' symbols'} tone={snapshot?.signals?.accepted_count?'good':'default'}/>
      <Stat label="Meta threshold" value={threshold==null?'—':pct(threshold)} sub="validation-only threshold"/>
      <Stat label="Paper execution" value="LOCKED" sub="research signal only" tone="warn"/>
    </div>
    <Panel><PanelHeader title="Universe ranking" eyebrow="Current snapshot"/>{!signals.length?<Empty>Autopilot n’a pas encore généré les signaux.</Empty>:<TableWrap className="max-h-[680px]"><table className={tableClass}><thead className="sticky top-0 bg-[#0f1217]"><tr><th className={thClass}>#</th><th className={thClass}>Symbol</th><th className={thClass}>Decision</th><th className={thClass}>Probability</th><th className={thClass}>Smooth score</th><th className={thClass}>Size</th><th className={thClass}>Regime</th></tr></thead><tbody>{signals.map(row=><tr key={row.symbol} onClick={()=>onSignal(row.symbol)} className="cursor-pointer hover:bg-white/[0.025]"><td className={tdClass}>{row.rank}</td><td className={cn(tdClass,'font-semibold text-white')}>{row.symbol}</td><td className={tdClass}><Badge tone={row.accepted?'good':'neutral'}>{row.accepted?'TRADE':'SKIP'}</Badge></td><td className={cn(tdClass,row.accepted?'text-emerald-300':'text-slate-500')}>{pct(row.meta_probability)}</td><td className={tdClass}>{num(row.smooth_score,4)}</td><td className={tdClass}>{pct(row.position_scale)}</td><td className={tdClass}>{row.regime}</td></tr>)}</tbody></table></TableWrap>}</Panel>
  </div>
}

export function SignalDrawer({symbol,explain,onClose}){
  if(!symbol)return null
  const factors=safeArray(explain?.factors||explain?.contributors)
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose}><div className="h-full w-full max-w-lg overflow-auto border-l border-white/10 bg-[#0c0f14] p-6 shadow-2xl" onClick={e=>e.stopPropagation()}>
    <div className="flex items-start justify-between gap-4"><div><div className="text-xs uppercase tracking-[.16em] text-slate-600">Explainability</div><h2 className="mt-1 text-2xl font-semibold text-white">{symbol}</h2></div><button onClick={onClose} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300">Fermer</button></div>
    {!explain?<div className="mt-10 text-sm text-slate-500">Chargement…</div>:explain.error?<div className="mt-10 text-sm text-rose-300">{explain.error}</div>:<div className="mt-8 space-y-4"><Panel className="p-5"><div className="text-xs text-slate-500">META score</div><div className="mt-2 text-3xl font-semibold text-white">{num(explain.meta_score,4)}</div><div className="mt-4 text-xs text-slate-600">Rank #{explain.rank||'—'} / {explain.universe_size||'—'}</div></Panel><Panel><PanelHeader title="Contributions"/><div className="space-y-3 p-5">{factors.map((row,i)=>{const label=row.feature||row.name||'factor '+(i+1);const value=row.percentile??row.value??row.score;return <div key={label} className="flex items-center justify-between gap-4 text-xs"><span className="text-slate-400">{label}</span><span className="font-medium text-slate-200">{num(value,3)}</span></div>})}</div></Panel></div>}
  </div></div>
}
