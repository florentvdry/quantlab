'use client'

import { RefreshCcw } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Badge, Empty, Panel, PanelHeader, SectionHeading, TableWrap, cn, tdClass, thClass, tableClass } from './ui'
import { Button } from './shell'
import { money, num, pct, price, safeArray, shortDate } from '../lib/format'

function BacktestDetail({detail}){
  if(!detail)return <Panel><Empty>Sélectionne un backtest pour ouvrir son audit complet.</Empty></Panel>
  const metrics=detail.metrics||{}
  const positions=safeArray(detail.position_ledger)
  const orders=safeArray(detail.order_ledger)
  const rebalances=safeArray(detail.rebalance_ledger)
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
        {detail.dataset?.mode||'—'} · {detail.dataset?.backtest_from||detail.dataset?.from||'?'} → {detail.dataset?.backtest_to||detail.dataset?.to||'?'} · {detail.execution_timing||'timing n/a'}
      </div>
      <div className="h-72 p-5">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={safeArray(detail.equity_curve)}>
            <XAxis dataKey="date" minTickGap={48} axisLine={false} tickLine={false}/>
            <YAxis domain={['auto','auto']} axisLine={false} tickLine={false}/>
            <Tooltip contentStyle={{background:'#11151b',border:'1px solid #242a35',borderRadius:'12px',fontSize:'12px'}}/>
            <Line type="monotone" dataKey="equity" stroke="#8b9cff" strokeWidth={2} dot={false}/>
          </LineChart>
        </ResponsiveContainer>
      </div>
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

export function BacktestsView({snapshot,detail,onSelect,onRunV5,running}){
  const rows=safeArray(snapshot?.backtests)
  return <div className="space-y-6">
    <SectionHeading title="Backtests" description="Un registre lisible, un audit détaillé, un seul bouton pour relancer le candidat actuel." action={<Button kind="primary" icon={RefreshCcw} disabled={running} onClick={onRunV5}>{running?'V5 en cours…':'Relancer META V5'}</Button>}/>
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
      <BacktestDetail detail={detail}/>
    </div>
  </div>
}
