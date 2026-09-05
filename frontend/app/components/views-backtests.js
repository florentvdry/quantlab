'use client'

import { RefreshCcw } from 'lucide-react'
import { Badge, Empty, Panel, PanelHeader, SectionHeading, TableWrap, cn, tdClass, thClass, tableClass } from './ui'
import { Button } from './shell'
import { BacktestAnalytics } from './backtest-analytics'
import { money, num, pct, price, safeArray, shortDate } from '../lib/format'


function BacktestDetail({detail,registry,fetchBacktest}){
  if(!detail)return <Panel><Empty>Sélectionne un backtest pour ouvrir son audit complet.</Empty></Panel>
  const metrics=detail.metrics||{}
  const positions=safeArray(detail.position_ledger)
  const orders=safeArray(detail.order_ledger)
  const rebalances=safeArray(detail.rebalance_ledger)
  const simulation=detail.meta_v71?.simulation||detail.meta_v7?.simulation||detail.meta_v6?.simulation||detail.meta_v5?.simulation
  const target=detail.meta_v71?.target||detail.meta_v7?.target||detail.meta_v6?.target
  const riskOverlay=detail.meta_v71?.risk_overlay||detail.meta_v7?.risk_overlay
  const exposureOverlay=detail.meta_v71?.exposure_overlay
  const stats=[
    ['CAGR',pct(metrics.cagr)],
    ['Sharpe',num(metrics.sharpe,2)],
    ['Max DD',pct(metrics.max_drawdown)],
    ['Profit factor',num(metrics.profit_factor,2)],
    ['Win rate',pct(metrics.win_rate)],
    ['Net P&L',money(metrics.net_pnl_usd)],
    ['Capital final',money(metrics.ending_capital_usd)],
    ['Costs',money(metrics.estimated_costs_usd)],
  ]
  return <div className="space-y-4">
    <Panel>
      <PanelHeader title={detail.strategy||'Backtest'} eyebrow="Audit complet" aside={<Badge tone={Number(metrics.sharpe)>=.75?'good':'warn'}>{detail.research_status||'OOS'}</Badge>}/>
      <div className="grid gap-px bg-white/6 sm:grid-cols-4">
        {stats.map(item=><div key={item[0]} className="bg-[#0d1015] p-4"><div className="text-[10px] uppercase tracking-wider text-slate-600">{item[0]}</div><div className="mt-1 text-sm font-semibold text-slate-100">{item[1]}</div></div>)}
      </div>
      <div className="border-t border-white/6 px-5 py-3 text-xs text-slate-600">
        <div>{detail.dataset?.mode||'—'} · trades {detail.dataset?.backtest_from||detail.dataset?.from||'?'} → {detail.dataset?.backtest_to||detail.dataset?.to||'?'} · {detail.execution_timing||'timing n/a'}</div>
        {detail.dataset?.raw_market_from&&<div className="mt-1 text-slate-700">raw market {detail.dataset.raw_market_from} → {detail.dataset.raw_market_to||'?'} · feature-valid from {detail.dataset.from||'?'}</div>}
      </div>
      {simulation&&<div className="border-t border-indigo-300/10 bg-indigo-400/[0.035] px-5 py-4">
        <div className="text-[10px] font-semibold uppercase tracking-[.15em] text-indigo-300">Continuous walk-forward</div>
        <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-5">
          <div><div className="text-slate-600">Features valides</div><div className="mt-1 text-slate-300">{simulation.feature_valid_from}</div></div>
          <div><div className="text-slate-600">Premier score live-like</div><div className="mt-1 text-slate-300">{simulation.first_live_like_score}</div></div>
          <div><div className="text-slate-600">Dernier score</div><div className="mt-1 text-slate-300">{simulation.last_live_like_score}</div></div>
          <div><div className="text-slate-600">Couverture simulée</div><div className="mt-1 text-slate-300">{pct(simulation.coverage_ratio)}</div></div>
          <div><div className="text-slate-600">Refresh / Rebalance</div><div className="mt-1 text-slate-300">{simulation.model_refresh_days}j / {simulation.rebalance_days}j</div></div>
        </div>
        <div className="mt-3 text-[11px] leading-5 text-slate-500">Pas de holdout fixe : après le démarrage minimal, chaque date est simulée chronologiquement avec uniquement les données alors connues.</div>
        {target&&<div className="mt-3 rounded-xl border border-white/6 bg-black/15 p-3 text-[11px] leading-5 text-slate-500">
          <div><span className="text-slate-400">Alpha target :</span> {target.alpha}</div>
          <div><span className="text-slate-400">Meta label :</span> {target.meta_label}</div>
          <div><span className="text-slate-400">Coût intégré au label :</span> {target.round_trip_cost_bps} bps round-trip</div>
        </div>}
        {riskOverlay&&<div className="mt-3 rounded-xl border border-emerald-300/10 bg-emerald-400/[0.03] p-3 text-[11px] leading-5 text-slate-500">
          <div className="font-semibold text-emerald-300">V7 risk overlay</div>
          <div className="mt-1">Corrélation {riskOverlay.corr_lookback_days}j · cap {num(riskOverlay.corr_cap,2)} · max {riskOverlay.max_names} titres · poids max {pct(riskOverlay.single_name_weight_cap)}</div>
          <div>Volatility scaling + exposition marché dynamique · {riskOverlay.method}</div>
        </div>}
        {exposureOverlay&&<div className="mt-3 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.03] p-3 text-[11px] leading-5 text-slate-500">
          <div className="font-semibold text-cyan-300">V7.1 balanced exposure</div>
          <div className="mt-1">Gross cible moyen {pct(exposureOverlay.mean_target_gross)} · max {pct(exposureOverlay.max_target_gross)}</div>
          <div>Confiance META + régime + risque marché · {exposureOverlay.method}</div>
        </div>}
      </div>}
      <BacktestAnalytics detail={detail} registry={registry} fetchBacktest={fetchBacktest}/>
    </Panel>

    <Panel>
      <PanelHeader title={'Positions / P&L · '+positions.length} eyebrow="Signal → Entry → Exit"/>
      {!positions.length?<Empty>Pas de ledger détaillé.</Empty>:<TableWrap className="max-h-[520px]">
        <table className={cn(tableClass,'min-w-[1120px]')}>
          <thead className="sticky top-0 bg-[#0f1217]"><tr><th className={thClass}>Signal</th><th className={thClass}>Entry</th><th className={thClass}>Exit</th><th className={thClass}>Symbol</th><th className={thClass}>Side</th><th className={thClass}>Entry px</th><th className={thClass}>Exit px</th><th className={thClass}>Qty</th><th className={thClass}>Return</th><th className={thClass}>Net P&L</th></tr></thead>
          <tbody>{positions.slice().reverse().slice(0,500).map((row,i)=><tr key={(row.rebalance_id||i)+'-'+row.symbol+'-'+i} className="hover:bg-white/[0.02]">
            <td className={tdClass}>{row.signal_date}</td><td className={tdClass}>{row.entry_date}</td><td className={tdClass}>{row.exit_date}</td>
            <td className={cn(tdClass,'font-semibold text-white')}>{row.symbol}</td>
            <td className={cn(tdClass,row.side==='LONG'?'text-emerald-300':'text-rose-300')}>{row.side}</td>
            <td className={tdClass}>{price(row.entry_price)}</td><td className={tdClass}>{price(row.exit_price)}</td><td className={tdClass}>{num(row.qty,3)}</td>
            <td className={cn(tdClass,Number(row.position_return)>=0?'text-emerald-300':'text-rose-300')}>{pct(row.position_return)}</td>
            <td className={cn(tdClass,Number(row.net_pnl_usd)>=0?'text-emerald-300':'text-rose-300')}>{money(row.net_pnl_usd)}</td>
          </tr>)}</tbody>
        </table>
      </TableWrap>}
    </Panel>

    <div className="grid gap-4 xl:grid-cols-2">
      <Panel>
        <PanelHeader title={'Ordres simulés · '+orders.length} eyebrow="Execution ledger"/>
        {!orders.length?<Empty>Aucun ordre disponible.</Empty>:<TableWrap className="max-h-[360px]"><table className={cn(tableClass,'min-w-[760px]')}><thead className="sticky top-0 bg-[#0f1217]"><tr><th className={thClass}>Date</th><th className={thClass}>Symbol</th><th className={thClass}>Action</th><th className={thClass}>Price</th><th className={thClass}>Qty</th><th className={thClass}>Cost</th></tr></thead><tbody>{orders.slice().reverse().slice(0,300).map((row,i)=><tr key={(row.rebalance_id||i)+'-'+row.symbol+'-'+i}><td className={tdClass}>{row.date}</td><td className={cn(tdClass,'font-semibold text-white')}>{row.symbol}</td><td className={tdClass}>{row.action}</td><td className={tdClass}>{price(row.price)}</td><td className={tdClass}>{num(row.qty,3)}</td><td className={tdClass}>{money(row.estimated_cost_usd)}</td></tr>)}</tbody></table></TableWrap>}
      </Panel>
      <Panel>
        <PanelHeader title={'Rebalances · '+rebalances.length} eyebrow="Portfolio lifecycle"/>
        {!rebalances.length?<Empty>Aucun rebalance disponible.</Empty>:<TableWrap className="max-h-[360px]"><table className={cn(tableClass,'min-w-[720px]')}><thead className="sticky top-0 bg-[#0f1217]"><tr><th className={thClass}>#</th><th className={thClass}>Signal</th><th className={thClass}>Turnover</th><th className={thClass}>Net P&L</th><th className={thClass}>Equity</th></tr></thead><tbody>{rebalances.slice().reverse().slice(0,180).map(row=><tr key={row.rebalance_id}><td className={tdClass}>{row.rebalance_id}</td><td className={tdClass}>{row.signal_date}</td><td className={tdClass}>{pct(row.turnover)}</td><td className={cn(tdClass,Number(row.net_pnl_usd)>=0?'text-emerald-300':'text-rose-300')}>{money(row.net_pnl_usd)}</td><td className={tdClass}>{money(row.equity_after_usd)}</td></tr>)}</tbody></table></TableWrap>}
      </Panel>
    </div>
  </div>
}

export function BacktestsView({snapshot,detail,onSelect,onRunCandidate,running,fetchBacktest}){
  const rows=safeArray(snapshot?.backtests)
  return <div className="space-y-6">
    <SectionHeading title="Backtests" description="V7.1 a échoué sur le grand univers. Le challenger courant revient à V7, mais sur Universe V3 : uniquement sociétés opérationnelles établies, SEC-backed, liquides et historiquement éligibles." action={<Button kind="primary" icon={RefreshCcw} disabled={running} onClick={onRunCandidate}>{running?'V7 Solid en cours…':'Tester META V7 · Solid V3'}</Button>}/>
    <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
      <Panel className="h-fit overflow-hidden">
        <PanelHeader title="Registry" eyebrow={rows.length+' runs'}/>
        {!rows.length?<Empty>Aucun backtest.</Empty>:<div className="max-h-[760px] overflow-auto divide-y divide-white/5">
          {rows.map(row=><button key={row.id} onClick={()=>onSelect(row.id)} className={cn('w-full px-5 py-4 text-left transition hover:bg-white/[0.025]',detail?.id===row.id&&'bg-indigo-400/[0.06]')}>
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold text-slate-200">{row.strategy}</div><div className="mt-1 text-[11px] text-slate-600">#{row.id} · {shortDate(row.created_at)}</div></div>
              <div className="text-right"><div className={cn('text-sm font-semibold',Number(row.sharpe)>=.75?'text-emerald-300':'text-amber-300')}>{num(row.sharpe,2)}</div><div className="text-[10px] text-slate-600">Sharpe</div></div>
            </div>
            <div className="mt-3 flex gap-4 text-[11px] text-slate-500"><span>CAGR {pct(row.cagr)}</span><span>DD {pct(row.max_drawdown)}</span></div>
          </button>)}
        </div>}
      </Panel>
      <BacktestDetail detail={detail} registry={rows} fetchBacktest={fetchBacktest}/>
    </div>
  </div>
}
