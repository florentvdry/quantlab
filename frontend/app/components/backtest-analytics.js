'use client'

import { useEffect, useMemo, useState } from 'react'
import { Columns3, GitCompareArrows, Search, X } from 'lucide-react'
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { Badge, Empty, Panel, PanelHeader, TableWrap, cn } from './ui'
import { money, num, pct, price, safeArray, shortDate } from '../lib/format'

const PERIODS=['10D','30D','90D','1Y','ALL']
const COMPARE_COLORS=['#8b9cff','#2dd4bf','#fbbf24','#f472b6']

function compactMoney(v){
  if(v==null||!Number.isFinite(Number(v)))return ''
  return new Intl.NumberFormat('fr-FR',{
    notation:'compact',style:'currency',currency:'USD',maximumFractionDigits:1,
  }).format(Number(v))
}

function normalizedAccount(detail){
  const initial=Number(detail?.metrics?.initial_capital_usd||100000)
  let rows=safeArray(detail?.account_curve).map(row=>({...row}))
  if(!rows.length){
    const rebalances=safeArray(detail?.rebalance_ledger)
    if(rebalances.length){
      rows=[]
      rebalances.forEach((row,i)=>{
        if(i===0)rows.push({
          date:row.entry_date,equity_usd:row.equity_before_usd,balance_usd:row.equity_before_usd,
          floating_pnl_usd:0,rebalance_id:row.rebalance_id,turnover:row.turnover||0,
          trade_count:row.trade_count||0,cost_usd:row.cost_usd||0,
        })
        rows.push({
          date:row.exit_date,equity_usd:row.equity_after_usd,balance_usd:row.equity_after_usd,
          floating_pnl_usd:0,rebalance_id:row.rebalance_id,turnover:0,trade_count:0,cost_usd:0,
        })
      })
    }else{
      rows=safeArray(detail?.equity_curve).map(row=>({
        date:row.date,
        equity_usd:row.equity_usd??initial*Number(row.equity||1),
        balance_usd:row.equity_usd??initial*Number(row.equity||1),
        floating_pnl_usd:0,turnover:0,trade_count:0,cost_usd:0,
      }))
    }
  }

  const unique=new Map()
  rows.forEach(row=>{if(row?.date)unique.set(row.date,row)})
  rows=[...unique.values()].sort((a,b)=>String(a.date).localeCompare(String(b.date)))

  let previousEquity=initial
  let previousBalance=initial
  let peak=initial
  return rows.map(row=>{
    const equity=Number(row.equity_usd??previousEquity)
    const balance=Number(row.balance_usd??equity)
    peak=Math.max(peak,equity)
    const enriched={
      ...row,
      equity_usd:equity,
      balance_usd:balance,
      floating_pnl_usd:Number(row.floating_pnl_usd??equity-balance),
      daily_pnl_usd:row.daily_pnl_usd==null?equity-previousEquity:Number(row.daily_pnl_usd),
      daily_return:row.daily_return==null?equity/Math.max(previousEquity,1e-12)-1:Number(row.daily_return),
      drawdown:row.drawdown==null?equity/Math.max(peak,1e-12)-1:Number(row.drawdown),
      balance_change_usd:row.balance_change_usd==null?balance-previousBalance:Number(row.balance_change_usd),
      turnover:Number(row.turnover||0),
      cost_usd:Number(row.cost_usd||0),
      trade_count:Number(row.trade_count||0),
      gross_exposure:row.gross_exposure==null?null:Number(row.gross_exposure),
      cash_pct:row.cash_pct==null?null:Number(row.cash_pct),
      avg_meta_probability:row.avg_meta_probability==null?null:Number(row.avg_meta_probability),
      meta_threshold:row.meta_threshold==null?null:Number(row.meta_threshold),
      avg_pair_corr:row.avg_pair_corr==null?null:Number(row.avg_pair_corr),
      max_pair_corr:row.max_pair_corr==null?null:Number(row.max_pair_corr),
      portfolio_vol:row.portfolio_vol==null?null:Number(row.portfolio_vol),
      largest_weight:row.largest_weight==null?null:Number(row.largest_weight),
      active_symbols:safeArray(row.active_symbols),
    }
    previousEquity=equity
    previousBalance=balance
    return enriched
  })
}

function periodRows(rows,period){
  if(period==='ALL'||!rows.length)return rows
  const last=new Date(rows[rows.length-1].date+'T00:00:00')
  const days=period==='10D'?10:period==='30D'?30:period==='90D'?90:365
  const cutoff=new Date(last)
  cutoff.setDate(cutoff.getDate()-days)
  return rows.filter(row=>new Date(row.date+'T00:00:00')>=cutoff)
}

function compoundedReturn(rows){
  return rows.reduce((acc,row)=>acc*(1+Number(row.daily_return||0)),1)-1
}

function average(rows,key){
  const values=rows.map(row=>Number(row[key])).filter(Number.isFinite)
  return values.length?values.reduce((a,b)=>a+b,0)/values.length:null
}

function totalRow(rows){
  if(!rows.length)return {}
  return {
    date:'TOTAL',
    daily_pnl_usd:rows.reduce((sum,row)=>sum+Number(row.daily_pnl_usd||0),0),
    daily_return:compoundedReturn(rows),
    equity_usd:rows[rows.length-1]?.equity_usd,
    balance_usd:rows[rows.length-1]?.balance_usd,
    drawdown:Math.min(...rows.map(row=>Number(row.drawdown||0))),
    gross_exposure:average(rows,'gross_exposure'),
    cash_pct:average(rows,'cash_pct'),
    turnover:rows.reduce((sum,row)=>sum+Number(row.turnover||0),0),
    trade_count:rows.reduce((sum,row)=>sum+Number(row.trade_count||0),0),
    avg_meta_probability:average(rows,'avg_meta_probability'),
    meta_threshold:average(rows,'meta_threshold'),
    avg_pair_corr:average(rows,'avg_pair_corr'),
    max_pair_corr:Math.max(...rows.map(row=>Number(row.max_pair_corr)).filter(Number.isFinite),0),
    portfolio_vol:average(rows,'portfolio_vol'),
    largest_weight:Math.max(...rows.map(row=>Number(row.largest_weight)).filter(Number.isFinite),0),
    cost_usd:rows.reduce((sum,row)=>sum+Number(row.cost_usd||0),0),
  }
}

const COLUMNS=[
  {key:'date',label:'Date',format:v=>v},
  {key:'daily_pnl_usd',label:'P&L',format:money},
  {key:'daily_return',label:'Return',format:pct},
  {key:'equity_usd',label:'Equity',format:money},
  {key:'balance_usd',label:'Balance',format:money},
  {key:'drawdown',label:'Drawdown',format:pct},
  {key:'gross_exposure',label:'Exposure',format:pct},
  {key:'cash_pct',label:'Cash',format:pct},
  {key:'turnover',label:'Turnover',format:pct},
  {key:'trade_count',label:'Trades',format:v=>v==null?'—':String(Math.round(v))},
  {key:'cost_usd',label:'Costs',format:money},
  {key:'avg_meta_probability',label:'Meta p',format:v=>v==null?'—':num(v,3)},
  {key:'meta_threshold',label:'Threshold',format:v=>v==null?'—':num(v,3)},
  {key:'regime',label:'Regime',format:v=>v||'—'},
  {key:'avg_pair_corr',label:'Avg corr',format:v=>v==null?'—':num(v,2)},
  {key:'max_pair_corr',label:'Max corr',format:v=>v==null?'—':num(v,2)},
  {key:'portfolio_vol',label:'Port vol',format:pct},
  {key:'largest_weight',label:'Max weight',format:pct},
]
const DEFAULT_VISIBLE=new Set(COLUMNS.map(c=>c.key))

function cellTone(key,value){
  const n=Number(value)
  if(!Number.isFinite(n))return ''
  if(key==='daily_pnl_usd'||key==='daily_return'){
    return n>0?'bg-emerald-400/[0.055] text-emerald-300':n<0?'bg-rose-400/[0.055] text-rose-300':'text-slate-400'
  }
  if(key==='drawdown'){
    return n<=-.08?'bg-rose-500/[0.08] text-rose-300':n<=-.04?'text-amber-300':'text-slate-400'
  }
  if(key==='max_pair_corr'){
    return n>=.9?'bg-rose-500/[0.08] text-rose-300':n>=.8?'text-amber-300':'text-slate-400'
  }
  if(key==='avg_pair_corr'){
    return n>=.75?'text-amber-300':'text-slate-400'
  }
  return ''
}

function ChartTooltip({active,payload,label}){
  if(!active||!payload?.length)return null
  const values=Object.fromEntries(payload.map(item=>[item.dataKey,item.value]))
  const floating=values.equity_usd!=null&&values.balance_usd!=null
    ?Number(values.equity_usd)-Number(values.balance_usd):null
  return <div className="rounded-xl border border-white/10 bg-[#0b0e13]/95 p-3 shadow-2xl backdrop-blur">
    <div className="mb-2 text-[10px] font-semibold uppercase tracking-[.14em] text-slate-500">{label}</div>
    <div className="space-y-1.5 text-xs">
      <div className="flex min-w-[190px] items-center justify-between gap-6"><span className="text-indigo-300">Equity</span><b className="text-white">{money(values.equity_usd)}</b></div>
      <div className="flex items-center justify-between gap-6"><span className="text-amber-300">Balance</span><b className="text-white">{money(values.balance_usd)}</b></div>
      {floating!=null&&<div className="flex items-center justify-between gap-6 border-t border-white/6 pt-1.5"><span className="text-slate-500">Floating</span><b className={floating>=0?'text-emerald-300':'text-rose-300'}>{money(floating)}</b></div>}
    </div>
  </div>
}

function SingleChart({rows,hoverDate,onHover,onSelect}){
  if(!rows.length)return <Empty>Aucune donnée sur cette période.</Empty>
  return <div className="h-[380px] px-2 pb-4 pr-5">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={rows}
        margin={{top:14,right:8,bottom:0,left:8}}
        onMouseMove={state=>onHover(state?.activeLabel||null)}
        onMouseLeave={()=>onHover(null)}
        onClick={state=>{if(state?.activeLabel)onSelect(state.activeLabel)}}
      >
        <CartesianGrid stroke="rgba(148,163,184,.07)" vertical={false}/>
        <XAxis dataKey="date" minTickGap={46} axisLine={false} tickLine={false} tick={{fontSize:10,fill:'#64748b'}}/>
        <YAxis domain={['auto','auto']} axisLine={false} tickLine={false} width={78} tickFormatter={compactMoney} tick={{fontSize:10,fill:'#64748b'}}/>
        <Tooltip content={<ChartTooltip/>}/>
        {hoverDate&&<ReferenceLine x={hoverDate} stroke="#64748b" strokeDasharray="3 3"/>}
        <Line type="monotone" dataKey="equity_usd" name="Equity" stroke="#8b9cff" strokeWidth={2.5} dot={false} activeDot={{r:3}} isAnimationActive={false}/>
        <Line type="stepAfter" dataKey="balance_usd" name="Balance" stroke="#fbbf24" strokeWidth={1.8} strokeDasharray="5 4" dot={false} activeDot={{r:3}} isAnimationActive={false}/>
      </LineChart>
    </ResponsiveContainer>
  </div>
}

function SortHeader({column,sortKey,sortDir,onSort}){
  const active=sortKey===column.key
  return <th
    onClick={()=>onSort(column.key)}
    className="sticky top-0 z-10 cursor-pointer whitespace-nowrap border-b border-white/8 bg-[#0e1117] px-3 py-3 text-left text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500 hover:text-slate-300"
  >
    {column.label}{active&&<span className="ml-1 text-indigo-300">{sortDir==='asc'?'↑':'↓'}</span>}
  </th>
}

function ColumnsMenu({visible,setVisible}){
  return <details className="relative">
    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/10">
      <Columns3 className="h-3.5 w-3.5"/>Colonnes
    </summary>
    <div className="absolute right-0 z-40 mt-2 grid w-64 grid-cols-2 gap-1 rounded-xl border border-white/10 bg-[#11151b] p-2 shadow-2xl">
      {COLUMNS.map(column=><label key={column.key} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-[11px] text-slate-400 hover:bg-white/5">
        <input
          type="checkbox"
          checked={visible.has(column.key)}
          onChange={()=>{
            const next=new Set(visible)
            if(next.has(column.key)&&column.key!=='date')next.delete(column.key)
            else next.add(column.key)
            setVisible(next)
          }}
        />
        {column.label}
      </label>)}
    </div>
  </details>
}

function DayDrawer({detail,day,onClose}){
  if(!day)return null
  const positions=safeArray(detail?.position_ledger)
    .filter(row=>Number(row.rebalance_id)===Number(day.rebalance_id))
    .sort((a,b)=>Math.abs(Number(b.weight||0))-Math.abs(Number(a.weight||0)))
  const orders=safeArray(detail?.order_ledger)
    .filter(row=>Number(row.rebalance_id)===Number(day.rebalance_id))
  const rebalance=safeArray(detail?.rebalance_ledger)
    .find(row=>Number(row.rebalance_id)===Number(day.rebalance_id))

  return <div className="fixed inset-0 z-50 flex justify-end bg-black/55 backdrop-blur-sm" onClick={onClose}>
    <aside className="h-full w-full max-w-2xl overflow-y-auto border-l border-white/10 bg-[#0a0d12] shadow-2xl" onClick={e=>e.stopPropagation()}>
      <div className="sticky top-0 z-20 flex items-start justify-between border-b border-white/8 bg-[#0a0d12]/95 px-6 py-5 backdrop-blur">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[.16em] text-slate-600">Daily portfolio audit</div>
          <h3 className="mt-1 text-xl font-semibold text-white">{day.date}</h3>
          <div className="mt-1 text-xs text-slate-500">{detail?.strategy} · rebalance #{day.rebalance_id||'—'}</div>
        </div>
        <button onClick={onClose} className="rounded-xl border border-white/10 bg-white/5 p-2 text-slate-400 hover:bg-white/10 hover:text-white"><X className="h-4 w-4"/></button>
      </div>

      <div className="space-y-5 p-6">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ['P&L jour',money(day.daily_pnl_usd),Number(day.daily_pnl_usd)>=0?'text-emerald-300':'text-rose-300'],
            ['Return',pct(day.daily_return),Number(day.daily_return)>=0?'text-emerald-300':'text-rose-300'],
            ['Equity',money(day.equity_usd),'text-white'],
            ['Balance',money(day.balance_usd),'text-white'],
            ['Drawdown',pct(day.drawdown),Number(day.drawdown)<-.05?'text-rose-300':'text-slate-200'],
            ['Exposure',pct(day.gross_exposure),'text-slate-200'],
            ['Cash',pct(day.cash_pct),'text-slate-200'],
            ['Floating',money(day.floating_pnl_usd),Number(day.floating_pnl_usd)>=0?'text-emerald-300':'text-rose-300'],
          ].map(([label,value,tone])=><div key={label} className="rounded-xl border border-white/6 bg-white/[0.025] p-3"><div className="text-[10px] uppercase tracking-wider text-slate-600">{label}</div><div className={cn('mt-1 text-sm font-semibold',tone)}>{value}</div></div>)}
        </div>

        <Panel>
          <PanelHeader title="Model & risk" eyebrow={day.regime||'No regime'}/>
          <div className="grid grid-cols-2 gap-px bg-white/6 sm:grid-cols-4">
            {[
              ['Meta probability',day.avg_meta_probability==null?'—':num(day.avg_meta_probability,3)],
              ['Threshold',day.meta_threshold==null?'—':num(day.meta_threshold,3)],
              ['Avg corr',day.avg_pair_corr==null?'—':num(day.avg_pair_corr,2)],
              ['Max corr',day.max_pair_corr==null?'—':num(day.max_pair_corr,2)],
              ['Portfolio vol',pct(day.portfolio_vol)],
              ['Largest weight',pct(day.largest_weight)],
              ['Turnover',pct(day.turnover)],
              ['Costs',money(day.cost_usd)],
            ].map(([label,value])=><div key={label} className="bg-[#0d1015] p-3"><div className="text-[10px] text-slate-600">{label}</div><div className="mt-1 text-xs font-semibold text-slate-200">{value}</div></div>)}
          </div>
        </Panel>

        <Panel>
          <PanelHeader title={'Positions actives · '+positions.length} eyebrow={day.signal_date||rebalance?.signal_date}/>
          {!positions.length?<Empty>Pas de détail de positions pour ce backtest.</Empty>:<div className="divide-y divide-white/5">
            {positions.map(row=><div key={row.symbol} className="grid grid-cols-[56px_1fr_auto] items-center gap-3 px-4 py-3 text-xs">
              <div className="font-semibold text-white">{row.symbol}</div>
              <div>
                <div className="text-slate-400">{row.side} · weight {pct(row.weight)} · rank #{row.rank}</div>
                <div className="mt-1 text-[10px] text-slate-600">entry {price(row.entry_price)} · score {num(row.signal_score,4)}</div>
              </div>
              <div className="text-right">
                <div className={Number(row.net_pnl_usd)>=0?'text-emerald-300':'text-rose-300'}>{money(row.net_pnl_usd)}</div>
                <div className="mt-1 text-[9px] uppercase tracking-wider text-slate-700">P&L période</div>
              </div>
            </div>)}
          </div>}
        </Panel>

        <Panel>
          <PanelHeader title={'Ordres du rebalance · '+orders.length} eyebrow={rebalance?.entry_date||day.entry_date}/>
          {!orders.length?<Empty>Aucun ordre sur cette date de rebalance.</Empty>:<div className="divide-y divide-white/5">
            {orders.map((row,i)=><div key={row.symbol+'-'+row.action+'-'+i} className="grid grid-cols-[58px_58px_1fr_auto] items-center gap-2 px-4 py-3 text-xs">
              <b className="text-white">{row.symbol}</b>
              <span className={row.action==='BUY'||row.action==='COVER'?'text-emerald-300':'text-rose-300'}>{row.action}</span>
              <span className="text-slate-500">{num(row.qty,3)} @ {price(row.price)}</span>
              <span className="text-slate-400">{money(row.notional_usd)}</span>
            </div>)}
          </div>}
        </Panel>
      </div>
    </aside>
  </div>
}

function SingleAnalytics({detail}){
  const [period,setPeriod]=useState('30D')
  const [search,setSearch]=useState('')
  const [sortKey,setSortKey]=useState('date')
  const [sortDir,setSortDir]=useState('desc')
  const [visible,setVisible]=useState(new Set(DEFAULT_VISIBLE))
  const [hoverDate,setHoverDate]=useState(null)
  const [selectedDay,setSelectedDay]=useState(null)

  const allRows=useMemo(()=>normalizedAccount(detail),[detail])
  const filtered=useMemo(()=>{
    let rows=periodRows(allRows,period)
    const q=search.trim().toUpperCase()
    if(q)rows=rows.filter(row=>safeArray(row.active_symbols).some(symbol=>String(symbol).toUpperCase().includes(q)))
    return rows
  },[allRows,period,search])

  const displayRows=useMemo(()=>{
    const rows=[...filtered]
    rows.sort((a,b)=>{
      const av=a[sortKey],bv=b[sortKey]
      if(sortKey==='date')return (String(av).localeCompare(String(bv)))*(sortDir==='asc'?1:-1)
      const an=Number(av),bn=Number(bv)
      if(Number.isFinite(an)&&Number.isFinite(bn))return (an-bn)*(sortDir==='asc'?1:-1)
      return String(av??'').localeCompare(String(bv??''))*(sortDir==='asc'?1:-1)
    })
    return rows
  },[filtered,sortKey,sortDir])

  const visibleColumns=COLUMNS.filter(column=>visible.has(column.key))
  const totals=totalRow(filtered)
  const chartRows=[...filtered].sort((a,b)=>String(a.date).localeCompare(String(b.date)))

  const selectDate=date=>{
    const row=allRows.find(item=>item.date===date)
    if(row)setSelectedDay(row)
  }
  const onSort=key=>{
    if(sortKey===key)setSortDir(current=>current==='asc'?'desc':'asc')
    else{setSortKey(key);setSortDir(key==='date'?'desc':'desc')}
  }

  return <div className="border-t border-white/6">
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
      <div>
        <div className="text-xs font-semibold text-slate-200">Equity, Balance & Daily Journal</div>
        <div className="mt-1 text-[11px] text-slate-600">Survole une ligne pour la retrouver sur le graphe. Clique une date ou un point pour auditer le portefeuille.</div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-white/8 bg-black/15 p-1">
          {PERIODS.map(item=><button key={item} onClick={()=>setPeriod(item)} className={cn('rounded-lg px-2.5 py-1.5 text-[10px] font-semibold transition',period===item?'bg-indigo-400/15 text-indigo-300':'text-slate-600 hover:text-slate-300')}>{item}</button>)}
        </div>
        <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2">
          <Search className="h-3.5 w-3.5 text-slate-600"/>
          <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Ticker…" className="w-20 bg-transparent text-xs text-slate-300 outline-none placeholder:text-slate-700"/>
        </label>
        <ColumnsMenu visible={visible} setVisible={setVisible}/>
      </div>
    </div>

    <SingleChart rows={chartRows} hoverDate={hoverDate} onHover={setHoverDate} onSelect={selectDate}/>

    <div className="border-t border-white/6">
      <TableWrap className="max-h-[620px]">
        <table className="w-full min-w-[1750px] border-collapse text-left font-mono text-[11px] tabular-nums">
          <thead>
            <tr>{visibleColumns.map(column=><SortHeader key={column.key} column={column} sortKey={sortKey} sortDir={sortDir} onSort={onSort}/>)}</tr>
          </thead>
          <tbody>
            {displayRows.map(row=><tr
              key={row.date}
              onMouseEnter={()=>setHoverDate(row.date)}
              onMouseLeave={()=>setHoverDate(null)}
              onClick={()=>setSelectedDay(row)}
              className={cn('cursor-pointer transition hover:bg-indigo-400/[0.045]',hoverDate===row.date&&'bg-white/[0.035]')}
            >
              {visibleColumns.map(column=><td key={column.key} className={cn('whitespace-nowrap border-b border-white/5 px-3 py-2.5 text-slate-400',column.key==='date'&&'font-semibold text-slate-200',cellTone(column.key,row[column.key]))}>{column.format(row[column.key])}</td>)}
            </tr>)}
          </tbody>
          <tfoot className="sticky bottom-0 z-20 bg-[#10141b] shadow-[0_-8px_24px_rgba(0,0,0,.35)]">
            <tr>{visibleColumns.map(column=><td key={column.key} className={cn('whitespace-nowrap border-t border-white/12 px-3 py-3 font-semibold text-slate-300',cellTone(column.key,totals[column.key]))}>{column.format(totals[column.key])}</td>)}</tr>
          </tfoot>
        </table>
      </TableWrap>
    </div>

    <DayDrawer detail={detail} day={selectedDay} onClose={()=>setSelectedDay(null)}/>
  </div>
}

function strategyVersion(strategy=''){
  const text=String(strategy)
  if(/v7\.1/i.test(text))return 'V7.1'
  const match=text.match(/v([5-9])/i)
  return match?'V'+match[1]:text.slice(0,18)
}

function latestCompareOptions(registry){
  const rows=safeArray(registry)
  const pick=needle=>rows.find(row=>String(row.strategy).toLowerCase().includes(needle))
  return [pick('v5'),pick('v6'),pick('v7 diversified'),pick('v7.1')].filter(Boolean)
}

function CompareTooltip({active,payload,label,details}){
  if(!active||!payload?.length)return null
  return <div className="rounded-xl border border-white/10 bg-[#0b0e13]/95 p-3 shadow-2xl">
    <div className="mb-2 text-[10px] font-semibold uppercase tracking-[.14em] text-slate-500">{label}</div>
    <div className="space-y-1.5 text-xs">
      {payload.map((item,i)=>{
        const detail=details.find(x=>String(x.id)===String(item.dataKey).replace('eq_',''))
        return <div key={item.dataKey} className="flex min-w-[200px] items-center justify-between gap-5"><span style={{color:item.stroke}}>{strategyVersion(detail?.strategy||item.name)}</span><b className="text-white">{money(item.value)}</b></div>
      })}
    </div>
  </div>
}

function CompareDrawer({date,details,onClose}){
  if(!date)return null
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/55 backdrop-blur-sm" onClick={onClose}>
    <aside className="h-full w-full max-w-3xl overflow-y-auto border-l border-white/10 bg-[#0a0d12]" onClick={e=>e.stopPropagation()}>
      <div className="sticky top-0 z-20 flex items-start justify-between border-b border-white/8 bg-[#0a0d12]/95 px-6 py-5">
        <div><div className="text-[10px] uppercase tracking-[.16em] text-slate-600">Strategy comparison</div><h3 className="mt-1 text-xl font-semibold text-white">{date}</h3></div>
        <button onClick={onClose} className="rounded-xl border border-white/10 bg-white/5 p-2 text-slate-400"><X className="h-4 w-4"/></button>
      </div>
      <div className="space-y-4 p-6">
        {details.map((detail,index)=>{
          const day=normalizedAccount(detail).find(row=>row.date===date)
          if(!day)return null
          const positions=safeArray(detail.position_ledger).filter(row=>Number(row.rebalance_id)===Number(day.rebalance_id))
          return <Panel key={detail.id}>
            <PanelHeader title={detail.strategy} eyebrow={'#'+detail.id} aside={<span className="h-2.5 w-2.5 rounded-full" style={{background:COMPARE_COLORS[index%COMPARE_COLORS.length]}}/>}/>
            <div className="grid grid-cols-3 gap-px bg-white/6 sm:grid-cols-6">
              {[
                ['P&L',money(day.daily_pnl_usd),Number(day.daily_pnl_usd)>=0?'text-emerald-300':'text-rose-300'],
                ['Return',pct(day.daily_return),Number(day.daily_return)>=0?'text-emerald-300':'text-rose-300'],
                ['DD',pct(day.drawdown),'text-slate-200'],
                ['Exposure',pct(day.gross_exposure),'text-slate-200'],
                ['Corr',day.avg_pair_corr==null?'—':num(day.avg_pair_corr,2),'text-slate-200'],
                ['Positions',String(positions.length||day.position_count||0),'text-slate-200'],
              ].map(([label,value,tone])=><div key={label} className="bg-[#0d1015] p-3"><div className="text-[9px] uppercase tracking-wider text-slate-600">{label}</div><div className={cn('mt-1 text-xs font-semibold',tone)}>{value}</div></div>)}
            </div>
            {positions.length>0&&<div className="flex flex-wrap gap-1.5 p-4">{positions.map(row=><span key={row.symbol} className="rounded-lg border border-white/6 bg-white/[0.025] px-2 py-1 text-[10px] text-slate-400">{row.symbol} {pct(row.weight)}</span>)}</div>}
          </Panel>
        })}
      </div>
    </aside>
  </div>
}

function CompareAnalytics({registry,fetchBacktest,onBack}){
  const options=useMemo(()=>latestCompareOptions(registry),[registry])
  const [selectedIds,setSelectedIds]=useState([])
  const [details,setDetails]=useState([])
  const [loading,setLoading]=useState(false)
  const [period,setPeriod]=useState('30D')
  const [hoverDate,setHoverDate]=useState(null)
  const [selectedDate,setSelectedDate]=useState(null)
  const [search,setSearch]=useState('')

  useEffect(()=>{
    if(!selectedIds.length&&options.length)setSelectedIds(options.map(row=>row.id))
  },[options.map(row=>row.id).join(',')])

  useEffect(()=>{
    let alive=true
    if(!selectedIds.length){setDetails([]);return()=>{alive=false}}
    setLoading(true)
    Promise.all(selectedIds.map(id=>fetchBacktest(id).catch(()=>null))).then(rows=>{
      if(alive)setDetails(rows.filter(Boolean))
    }).finally(()=>{if(alive)setLoading(false)})
    return()=>{alive=false}
  },[selectedIds.join(',')])

  const series=useMemo(()=>details.map(detail=>({detail,rows:normalizedAccount(detail)})),[details])
  const allDates=useMemo(()=>{
    const dates=new Set()
    series.forEach(item=>item.rows.forEach(row=>dates.add(row.date)))
    return [...dates].sort()
  },[series])

  const rawMerged=useMemo(()=>allDates.map(date=>{
    const row={date}
    series.forEach(({detail,rows})=>{
      const day=rows.find(item=>item.date===date)
      if(day)row[detail.id]=day
    })
    return row
  }),[allDates,series])

  const filtered=useMemo(()=>{
    let rows=periodRows(rawMerged.map(row=>({date:row.date})),period)
    const allowed=new Set(rows.map(row=>row.date))
    let merged=rawMerged.filter(row=>allowed.has(row.date))
    const q=search.trim().toUpperCase()
    if(q)merged=merged.filter(row=>details.some(detail=>safeArray(row[detail.id]?.active_symbols).some(symbol=>String(symbol).toUpperCase().includes(q))))
    return merged
  },[rawMerged,period,search,details])

  const chartData=filtered.map(row=>{
    const out={date:row.date}
    details.forEach(detail=>{if(row[detail.id])out['eq_'+detail.id]=row[detail.id].equity_usd})
    return out
  })

  const toggle=id=>setSelectedIds(current=>{
    if(current.includes(id))return current.length>1?current.filter(x=>x!==id):current
    return current.length>=4?[...current.slice(1),id]:[...current,id]
  })

  return <div className="border-t border-white/6">
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
      <div>
        <div className="flex items-center gap-2"><GitCompareArrows className="h-4 w-4 text-indigo-300"/><span className="text-xs font-semibold text-slate-200">V5 / V6 / V7 / V7.1 comparison</span></div>
        <div className="mt-1 text-[11px] text-slate-600">Même date, même lecture : P&L, return et drawdown côte à côte.</div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {options.map(option=><button key={option.id} onClick={()=>toggle(option.id)} className={cn('rounded-xl border px-3 py-2 text-[10px] font-semibold',selectedIds.includes(option.id)?'border-indigo-300/20 bg-indigo-400/10 text-indigo-300':'border-white/8 bg-white/[0.025] text-slate-600')}>{strategyVersion(option.strategy)} #{option.id}</button>)}
        <button onClick={onBack} className="rounded-xl border border-white/8 bg-white/[0.025] px-3 py-2 text-[10px] font-semibold text-slate-500 hover:text-white">Single</button>
      </div>
    </div>

    <div className="flex flex-wrap items-center gap-2 border-y border-white/6 px-5 py-3">
      <div className="flex rounded-xl border border-white/8 bg-black/15 p-1">{PERIODS.map(item=><button key={item} onClick={()=>setPeriod(item)} className={cn('rounded-lg px-2.5 py-1.5 text-[10px] font-semibold',period===item?'bg-indigo-400/15 text-indigo-300':'text-slate-600')}>{item}</button>)}</div>
      <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2"><Search className="h-3.5 w-3.5 text-slate-600"/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Ticker…" className="w-20 bg-transparent text-xs text-slate-300 outline-none"/></label>
      {loading&&<span className="text-[10px] text-slate-600">Chargement…</span>}
    </div>

    <div className="h-[360px] px-2 py-4 pr-5">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} onMouseMove={state=>setHoverDate(state?.activeLabel||null)} onMouseLeave={()=>setHoverDate(null)} onClick={state=>{if(state?.activeLabel)setSelectedDate(state.activeLabel)}}>
          <CartesianGrid stroke="rgba(148,163,184,.07)" vertical={false}/>
          <XAxis dataKey="date" minTickGap={46} axisLine={false} tickLine={false} tick={{fontSize:10,fill:'#64748b'}}/>
          <YAxis domain={['auto','auto']} width={78} tickFormatter={compactMoney} axisLine={false} tickLine={false} tick={{fontSize:10,fill:'#64748b'}}/>
          <Tooltip content={<CompareTooltip details={details}/>}/>
          {hoverDate&&<ReferenceLine x={hoverDate} stroke="#64748b" strokeDasharray="3 3"/>}
          {details.map((detail,index)=><Line key={detail.id} type="monotone" dataKey={'eq_'+detail.id} name={strategyVersion(detail.strategy)} stroke={COMPARE_COLORS[index%COMPARE_COLORS.length]} strokeWidth={2.2} dot={false} connectNulls isAnimationActive={false}/>)}
        </LineChart>
      </ResponsiveContainer>
    </div>

    <TableWrap className="max-h-[620px] border-t border-white/6">
      <table className="w-full min-w-[1100px] border-collapse font-mono text-[11px] tabular-nums">
        <thead className="sticky top-0 z-20 bg-[#0e1117]">
          <tr>
            <th rowSpan={2} className="border-b border-r border-white/8 px-3 py-3 text-left text-[10px] uppercase tracking-[.12em] text-slate-500">Date</th>
            {details.map((detail,index)=><th key={detail.id} colSpan={3} className="border-b border-r border-white/8 px-3 py-2 text-center text-[10px] font-semibold uppercase tracking-[.12em]" style={{color:COMPARE_COLORS[index%COMPARE_COLORS.length]}}>{strategyVersion(detail.strategy)} #{detail.id}</th>)}
          </tr>
          <tr>{details.flatMap(detail=>['P&L','Return','DD'].map(label=><th key={detail.id+'-'+label} className="border-b border-r border-white/8 px-3 py-2 text-right text-[9px] uppercase tracking-wider text-slate-600">{label}</th>))}</tr>
        </thead>
        <tbody>
          {[...filtered].reverse().map(row=><tr key={row.date} onMouseEnter={()=>setHoverDate(row.date)} onMouseLeave={()=>setHoverDate(null)} onClick={()=>setSelectedDate(row.date)} className={cn('cursor-pointer hover:bg-indigo-400/[0.04]',hoverDate===row.date&&'bg-white/[0.035]')}>
            <td className="whitespace-nowrap border-b border-r border-white/5 px-3 py-2.5 font-semibold text-slate-200">{row.date}</td>
            {details.flatMap(detail=>{
              const day=row[detail.id]
              if(!day)return [
                <td key={detail.id+'p'} className="border-b border-white/5 px-3 py-2.5 text-right text-slate-800">—</td>,
                <td key={detail.id+'r'} className="border-b border-white/5 px-3 py-2.5 text-right text-slate-800">—</td>,
                <td key={detail.id+'d'} className="border-b border-r border-white/5 px-3 py-2.5 text-right text-slate-800">—</td>,
              ]
              return [
                <td key={detail.id+'p'} className={cn('border-b border-white/5 px-3 py-2.5 text-right',cellTone('daily_pnl_usd',day.daily_pnl_usd))}>{money(day.daily_pnl_usd)}</td>,
                <td key={detail.id+'r'} className={cn('border-b border-white/5 px-3 py-2.5 text-right',cellTone('daily_return',day.daily_return))}>{pct(day.daily_return)}</td>,
                <td key={detail.id+'d'} className={cn('border-b border-r border-white/5 px-3 py-2.5 text-right',cellTone('drawdown',day.drawdown))}>{pct(day.drawdown)}</td>,
              ]
            })}
          </tr>)}
        </tbody>
        <tfoot className="sticky bottom-0 z-20 bg-[#10141b]">
          <tr>
            <td className="border-t border-r border-white/12 px-3 py-3 font-semibold text-slate-200">TOTAL</td>
            {details.flatMap(detail=>{
              const rows=filtered.map(row=>row[detail.id]).filter(Boolean)
              const total=totalRow(rows)
              return [
                <td key={detail.id+'tp'} className={cn('border-t border-white/12 px-3 py-3 text-right font-semibold',cellTone('daily_pnl_usd',total.daily_pnl_usd))}>{money(total.daily_pnl_usd)}</td>,
                <td key={detail.id+'tr'} className={cn('border-t border-white/12 px-3 py-3 text-right font-semibold',cellTone('daily_return',total.daily_return))}>{pct(total.daily_return)}</td>,
                <td key={detail.id+'td'} className={cn('border-t border-r border-white/12 px-3 py-3 text-right font-semibold',cellTone('drawdown',total.drawdown))}>{pct(total.drawdown)}</td>,
              ]
            })}
          </tr>
        </tfoot>
      </table>
    </TableWrap>

    <CompareDrawer date={selectedDate} details={details} onClose={()=>setSelectedDate(null)}/>
  </div>
}

export function BacktestAnalytics({detail,registry,fetchBacktest}){
  const [compare,setCompare]=useState(false)
  if(!detail)return null
  if(compare)return <CompareAnalytics registry={registry} fetchBacktest={fetchBacktest} onBack={()=>setCompare(false)}/>
  return <div>
    <div className="flex justify-end border-t border-white/6 px-5 pt-4">
      <button onClick={()=>setCompare(true)} className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[10px] font-semibold text-slate-400 hover:bg-white/10 hover:text-white"><GitCompareArrows className="h-3.5 w-3.5"/>Compare V5 / V6 / V7 / V7.1</button>
    </div>
    <SingleAnalytics detail={detail}/>
  </div>
}
