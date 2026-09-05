'use client'

import { Activity, LayoutDashboard, FlaskConical, BarChart3, TrendingUp, WalletCards, ServerCog, LockKeyhole, RefreshCcw, Sparkles, ShieldAlert, XCircle } from 'lucide-react'
import { Badge, cn } from './ui'

export const NAV=[
  {id:'dashboard',label:'Dashboard',icon:LayoutDashboard},
  {id:'research',label:'Research',icon:FlaskConical},
  {id:'backtests',label:'Backtests',icon:BarChart3},
  {id:'signals',label:'Signals',icon:TrendingUp},
  {id:'paper',label:'Paper',icon:WalletCards},
  {id:'system',label:'System',icon:ServerCog},
]

export const JOB_LABELS={
  AUTO_BOOTSTRAP:'Autopilot QuantLab',
  META_V5:'META Ensemble V5',
  META_V5_SIGNALS:'META V5 Signals',
  VALIDATION:'Validation Gate',
  FACTOR_SUMMARY:'Factor Research',
  DAILY_PIPELINE:'Daily Pipeline',
  DATA_REFRESH:'Market Data',
  SEC_REFRESH:'SEC',
  BACKTEST:'Backtest',
  BASELINE:'Momentum baseline',
  ROBUSTNESS:'Robustness',
  PAPER_SNAPSHOT:'Paper snapshot',
}

export function Button({children,onClick,disabled=false,kind='secondary',icon:Icon}){
  const style=kind==='primary'
    ?'border-indigo-300/20 bg-indigo-400 text-slate-950 hover:bg-indigo-300'
    :kind==='danger'
      ?'border-rose-400/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20'
      :'border-white/10 bg-white/5 text-slate-200 hover:bg-white/10'
  return <button disabled={disabled} onClick={onClick} className={cn(
    'inline-flex items-center justify-center gap-2 rounded-xl border px-3.5 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40',
    style
  )}>{Icon&&<Icon className="h-3.5 w-3.5"/>}{children}</button>
}

export function TopNav({view,setView,snapshot,onRefresh,refreshing}){
  const system=snapshot?.system||{}
  return <div className="sticky top-0 z-30 border-b border-white/8 bg-[#080a0d]/90 backdrop-blur-xl">
    <div className="mx-auto flex max-w-[1600px] items-center gap-5 px-4 py-3 lg:px-6">
      <button onClick={()=>setView('dashboard')} className="flex shrink-0 items-center gap-3 text-left">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-indigo-300/20 bg-indigo-400/10"><Sparkles className="h-4 w-4 text-indigo-300"/></div>
        <div className="hidden sm:block"><div className="text-sm font-semibold tracking-tight text-white">QuantLab</div><div className="text-[10px] uppercase tracking-[.18em] text-slate-600">Research OS · v1.3</div></div>
      </button>
      <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {NAV.map(item=>{
          const Icon=item.icon
          return <button key={item.id} onClick={()=>setView(item.id)} className={cn(
            'flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition',
            view===item.id?'bg-white/10 text-white':'text-slate-500 hover:bg-white/5 hover:text-slate-200'
          )}><Icon className="h-3.5 w-3.5"/><span className="hidden md:inline">{item.label}</span></button>
        })}
      </nav>
      <div className="flex shrink-0 items-center gap-2">
        <Badge tone={system.worker_online?'good':'bad'}><span className={cn('h-1.5 w-1.5 rounded-full',system.worker_online?'bg-emerald-300':'bg-rose-300')}/>{system.worker_online?'Worker':'Offline'}</Badge>
        <Badge tone={system.paper_orders_enabled?'bad':'neutral'}><LockKeyhole className="h-3 w-3"/>PAPER {system.paper_orders_enabled?'ARMED':'LOCKED'}</Badge>
        <Button onClick={onRefresh} disabled={refreshing} icon={RefreshCcw}><span className="hidden sm:inline">{refreshing?'Refresh…':'Refresh'}</span></Button>
      </div>
    </div>
  </div>
}

export function ErrorBanner({message,onClose}){
  if(!message)return null
  return <div className="mb-5 flex items-center gap-3 rounded-xl border border-rose-400/20 bg-rose-500/[0.06] px-4 py-3 text-xs text-rose-200"><ShieldAlert className="h-4 w-4"/><span className="flex-1">{message}</span><button onClick={onClose}><XCircle className="h-4 w-4"/></button></div>
}

export function LoadingScreen(){
  return <main className="flex min-h-screen items-center justify-center px-6"><div className="text-center">
    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-300/20 bg-indigo-500/10"><Activity className="h-5 w-5 animate-pulse text-indigo-300"/></div>
    <h1 className="mt-5 text-lg font-semibold text-white">QuantLab démarre</h1>
    <p className="mt-2 text-sm text-slate-600">Chargement du snapshot local. Aucun appel Alpaca n’est nécessaire pour afficher l’interface.</p>
  </div></main>
}
