'use client'

import { CheckCircle2, ShieldAlert, ShieldCheck, RefreshCcw } from 'lucide-react'
import { Badge, Empty, Panel, PanelHeader, SectionHeading, Stat, TableWrap, cn, tdClass, thClass, tableClass } from './ui'
import { Button, JOB_LABELS } from './shell'
import { money, num, pct, safeArray, shortDate } from '../lib/format'

export function PaperView({snapshot}){
  const paper=snapshot?.paper||{}
  const positions=safeArray(paper.positions)
  const orders=safeArray(paper.orders)
  const fills=safeArray(paper.fills)
  const system=snapshot?.system||{}
  return <div className="space-y-6">
    <SectionHeading title="Paper" description="État Alpaca PAPER. Les données d'affichage viennent du cache local, pas d'un appel réseau à chaque refresh."/>
    <Panel className={cn('p-5',system.paper_orders_enabled?'border-rose-400/20 bg-rose-500/[0.04]':'border-emerald-400/15 bg-emerald-500/[0.03]')}>
      <div className="flex flex-wrap items-center gap-4">
        <div className={cn('flex h-11 w-11 items-center justify-center rounded-xl',system.paper_orders_enabled?'bg-rose-500/10 text-rose-300':'bg-emerald-500/10 text-emerald-300')}>{system.paper_orders_enabled?<ShieldAlert className="h-5 w-5"/>:<ShieldCheck className="h-5 w-5"/>}</div>
        <div className="min-w-0 flex-1"><div className="text-sm font-semibold text-white">Execution {system.paper_orders_enabled?'ARMED':'LOCKED'}</div><div className="mt-1 text-xs text-slate-500">{system.paper_orders_enabled?'Paper orders explicitly enabled.':'Research et signaux peuvent tourner, les ordres restent bloqués.'}</div></div>
        <Badge tone={system.paper_orders_enabled?'bad':'good'}>PAPER ONLY</Badge>
      </div>
    </Panel>

    <div className="grid gap-3 sm:grid-cols-3">
      <Stat label="Equity" value={money(snapshot?.account?.equity)} sub={snapshot?.account?.source||'cache'}/>
      <Stat label="Cash" value={money(snapshot?.account?.cash)}/>
      <Stat label="Buying power" value={money(snapshot?.account?.buying_power)}/>
    </div>

    <div className="grid gap-4 xl:grid-cols-2">
      <Panel>
        <PanelHeader title="Positions" eyebrow={positions.length+' open'}/>
        {!positions.length?<Empty>Aucune position Paper.</Empty>:<TableWrap><table className={tableClass}><thead><tr><th className={thClass}>Symbol</th><th className={thClass}>Side</th><th className={thClass}>Notional</th><th className={thClass}>Weight</th></tr></thead><tbody>{positions.map(row=><tr key={row.symbol}><td className={cn(tdClass,'font-semibold text-white')}>{row.symbol}</td><td className={tdClass}>{row.side}</td><td className={tdClass}>{money(row.notional)}</td><td className={tdClass}>{pct(row.weight)}</td></tr>)}</tbody></table></TableWrap>}
      </Panel>
      <Panel>
        <PanelHeader title="Performance Paper" eyebrow="Snapshots"/>
        <div className="grid grid-cols-2 gap-px bg-white/6">
          <div className="bg-[#0d1015] p-5"><div className="text-[11px] text-slate-600">Paper return</div><div className="mt-1 text-xl font-semibold text-white">{pct(paper.performance?.comparison?.paper_return)}</div></div>
          <div className="bg-[#0d1015] p-5"><div className="text-[11px] text-slate-600">Backtest aligned</div><div className="mt-1 text-xl font-semibold text-white">{pct(paper.performance?.comparison?.backtest_return)}</div></div>
        </div>
        <div className="border-t border-white/6 px-5 py-4 text-xs text-slate-600">Snapshots : {paper.performance?.comparison?.paper_snapshots||0} · aligned : {paper.performance?.comparison?.date_aligned?'yes':'no'}</div>
      </Panel>
    </div>

    <Panel>
      <PanelHeader title="Orders & fills" eyebrow="Latest activity"/>
      <div className="grid lg:grid-cols-2">
        <div className="border-b border-white/6 lg:border-b-0 lg:border-r">
          {!orders.length?<Empty>Aucun ordre.</Empty>:orders.slice(0,16).map((row,i)=><div key={row.client_order_id||i} className="flex items-center gap-3 border-b border-white/5 px-5 py-3 text-xs"><b className="w-14 text-white">{row.symbol}</b><span className="w-12 text-slate-500">{row.side}</span><span className="flex-1 text-slate-400">{money(row.notional)}</span><Badge tone={row.status==='filled'?'good':'neutral'}>{row.status}</Badge></div>)}
        </div>
        <div>
          {!fills.length?<Empty>Aucun fill.</Empty>:fills.slice(0,16).map(row=><div key={row.id} className="flex items-center gap-3 border-b border-white/5 px-5 py-3 text-xs"><b className="w-14 text-white">{row.symbol}</b><span className="w-12 text-slate-500">{row.side}</span><span className="flex-1 text-slate-400">{num(row.qty,3)} @ {money(row.price)}</span><span className="text-slate-600">{shortDate(row.created_at)}</span></div>)}
        </div>
      </div>
    </Panel>
  </div>
}

export function SystemView({snapshot,onRefresh,refreshing}){
  const jobs=safeArray(snapshot?.jobs)
  const datasets=snapshot?.datasets||{}
  const quality=snapshot?.quality||{}
  return <div className="space-y-6">
    <SectionHeading title="System" description="Observabilité, datasets et opérations. Les relances manuelles restent ici." action={<Button onClick={onRefresh} disabled={refreshing} icon={RefreshCcw}>{refreshing?'En cours…':'Refresh tout'}</Button>}/>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Worker" value={snapshot?.system?.worker_online?'ONLINE':'OFFLINE'} sub={'queue '+(snapshot?.system?.queue_depth??'—')} tone={snapshot?.system?.worker_online?'good':'bad'}/>
      <Stat label="Redis" value={snapshot?.system?.redis?'OK':'ERROR'} tone={snapshot?.system?.redis?'good':'bad'}/>
      <Stat label="Feature Store" value={snapshot?.readiness?.feature_store?.ready?'READY':'NOT READY'} sub={'schema '+(snapshot?.readiness?.feature_store?.expected_schema||'—')} tone={snapshot?.readiness?.feature_store?.ready?'good':'warn'}/>
      <Stat label="Data Quality" value={quality.status||'NOT RUN'} tone={quality.status==='PASS'?'good':'warn'}/>
    </div>

    <div className="grid gap-4 xl:grid-cols-2">
      <Panel>
        <PanelHeader title="Datasets" eyebrow="Versions & freshness"/>
        {!Object.keys(datasets).length?<Empty>Aucun dataset persisté.</Empty>:<div className="divide-y divide-white/5">
          {Object.entries(datasets).map(([key,value])=><div key={key} className="grid grid-cols-[1fr_auto] gap-4 px-5 py-3 text-xs"><div><div className="font-medium text-slate-300">{key}</div><div className="mt-1 text-[10px] text-slate-600">{value.latest||shortDate(value.updated_at)}</div></div><div className="text-right text-slate-500">{value.rows!=null?String(value.rows)+' rows':value.covered!=null?String(value.covered)+' covered':value.status||'—'}</div></div>)}
        </div>}
      </Panel>
      <Panel>
        <PanelHeader title="Data Quality" eyebrow={quality.status||'NOT RUN'}/>
        {!safeArray(quality.checks).length?<Empty>Aucun contrôle.</Empty>:<div className="divide-y divide-white/5">
          {quality.checks.map(check=><div key={check.name} className="flex items-center gap-3 px-5 py-3">{check.ok?<CheckCircle2 className="h-4 w-4 text-emerald-300"/>:<ShieldAlert className="h-4 w-4 text-amber-300"/>}<span className="flex-1 text-xs text-slate-300">{check.name}</span><Badge tone={check.ok?'good':'warn'}>{check.ok?'PASS':check.severity==='critical'?'BLOCK':'WARN'}</Badge></div>)}
        </div>}
      </Panel>
    </div>

    <Panel>
      <PanelHeader title="Background jobs" eyebrow="Last 60"/>
      {!jobs.length?<Empty>Aucun job.</Empty>:<TableWrap className="max-h-[560px]"><table className={tableClass}><thead className="sticky top-0 bg-[#0f1217]"><tr><th className={thClass}>Job</th><th className={thClass}>Status</th><th className={thClass}>Progress</th><th className={thClass}>Message</th><th className={thClass}>Updated</th></tr></thead><tbody>{jobs.map(job=><tr key={job.job_key}><td className={cn(tdClass,'font-medium text-slate-200')}>{JOB_LABELS[job.kind]||job.kind}</td><td className={tdClass}><Badge tone={job.status==='COMPLETED'?'good':job.status==='FAILED'?'bad':job.status==='RUNNING'?'info':'neutral'}>{job.status}</Badge></td><td className={tdClass}>{job.progress}%</td><td className={cn(tdClass,'max-w-[440px] truncate',job.error?'text-rose-300':'')}>{job.error||job.message||'—'}</td><td className={tdClass}>{shortDate(job.updated_at)}</td></tr>)}</tbody></table></TableWrap>}
    </Panel>

    <details className="rounded-2xl border border-white/8 bg-white/[0.025]">
      <summary className="cursor-pointer px-5 py-4 text-sm font-medium text-slate-400">Configuration de sécurité</summary>
      <div className="grid gap-3 border-t border-white/6 p-5 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div><div className="text-slate-600">Trading env</div><div className="mt-1 text-slate-300">{snapshot?.system?.trading_env}</div></div>
        <div><div className="text-slate-600">Orders enabled</div><div className="mt-1 text-slate-300">{String(snapshot?.system?.paper_orders_enabled)}</div></div>
        <div><div className="text-slate-600">Paper auto</div><div className="mt-1 text-slate-300">{String(snapshot?.system?.paper_auto_enabled)}</div></div>
        <div><div className="text-slate-600">Live supported</div><div className="mt-1 text-slate-300">{String(snapshot?.system?.live_trading_supported)}</div></div>
      </div>
    </details>
  </div>
}
