'use client'

import { Activity, AlertTriangle, CheckCircle2, Clock3, LoaderCircle } from 'lucide-react'

export const cn=(...items)=>items.filter(Boolean).join(' ')

export function Panel({children,className=''}) {
  return <section className={cn('rounded-2xl border border-white/8 bg-white/[0.035] shadow-[0_16px_60px_rgba(0,0,0,.18)] backdrop-blur-sm',className)}>{children}</section>
}

export function PanelHeader({title,eyebrow,aside}) {
  return <div className="flex items-start justify-between gap-4 border-b border-white/6 px-5 py-4">
    <div>
      {eyebrow&&<div className="mb-1 text-[11px] font-semibold uppercase tracking-[.16em] text-slate-500">{eyebrow}</div>}
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
    </div>
    {aside}
  </div>
}

export function Stat({label,value,sub,tone='default'}) {
  const tones={
    default:'text-white',
    good:'text-emerald-300',
    warn:'text-amber-300',
    bad:'text-rose-300',
    info:'text-indigo-300',
  }
  return <Panel className="p-5">
    <div className="text-xs font-medium text-slate-500">{label}</div>
    <div className={cn('mt-2 text-2xl font-semibold tracking-tight',tones[tone]||tones.default)}>{value}</div>
    {sub&&<div className="mt-1 text-xs text-slate-500">{sub}</div>}
  </Panel>
}

export function Badge({children,tone='neutral'}) {
  const tones={
    neutral:'border-white/10 bg-white/5 text-slate-300',
    good:'border-emerald-400/20 bg-emerald-400/10 text-emerald-300',
    bad:'border-rose-400/20 bg-rose-400/10 text-rose-300',
    warn:'border-amber-400/20 bg-amber-400/10 text-amber-300',
    info:'border-indigo-400/20 bg-indigo-400/10 text-indigo-300',
  }
  return <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold',tones[tone]||tones.neutral)}>{children}</span>
}

export function StatusDot({ok}) {
  return <span className={cn('h-2 w-2 rounded-full',ok?'bg-emerald-400':'bg-rose-400')}/>
}

export function Empty({children}) {
  return <div className="px-5 py-10 text-center text-sm text-slate-500">{children}</div>
}

export function TableWrap({children,className=''}) {
  return <div className={cn('overflow-auto',className)}>{children}</div>
}

export const tableClass='w-full min-w-[680px] border-collapse text-left text-sm'
export const thClass='border-b border-white/8 px-4 py-3 text-[11px] font-semibold uppercase tracking-[.12em] text-slate-500'
export const tdClass='border-b border-white/5 px-4 py-3 text-slate-300'

export function JobBanner({job}) {
  if(!job)return null
  const running=job.status==='RUNNING'||job.status==='QUEUED'
  const failed=job.status==='FAILED'
  const completed=job.status==='COMPLETED'
  return <div className={cn(
    'mb-6 overflow-hidden rounded-2xl border',
    failed?'border-rose-400/20 bg-rose-500/[0.06]':
    completed?'border-emerald-400/20 bg-emerald-500/[0.06]':
    'border-indigo-400/20 bg-indigo-500/[0.06]'
  )}>
    <div className="flex items-center gap-3 px-4 py-3">
      {running?<LoaderCircle className="h-4 w-4 animate-spin text-indigo-300"/>:
       failed?<AlertTriangle className="h-4 w-4 text-rose-300"/>:
       <CheckCircle2 className="h-4 w-4 text-emerald-300"/>}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-semibold text-slate-100">{job.label||job.kind}</span>
          <Badge tone={failed?'bad':completed?'good':'info'}>{job.status}</Badge>
          <span className="text-xs text-slate-500">{job.progress||0}%</span>
        </div>
        <div className={cn('mt-1 truncate text-xs',failed?'text-rose-300':'text-slate-400')}>{job.error||job.message||'Traitement en cours…'}</div>
      </div>
    </div>
    {running&&<div className="h-1 bg-white/5"><div className="h-full bg-indigo-400 transition-all" style={{width:Math.max(2,job.progress||0)+'%'}}/></div>}
  </div>
}

export function Readiness({steps=[]}) {
  return <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
    {steps.map(step=><div key={step.name} className="flex items-center gap-2 rounded-xl border border-white/6 bg-black/10 px-3 py-2.5">
      <StatusDot ok={step.ok}/>
      <span className="text-xs font-medium text-slate-300">{step.name}</span>
    </div>)}
  </div>
}

export function SectionHeading({title,description,action}) {
  return <div className="mb-4 flex items-end justify-between gap-4">
    <div>
      <h2 className="text-lg font-semibold tracking-tight text-white">{title}</h2>
      {description&&<p className="mt-1 text-sm text-slate-500">{description}</p>}
    </div>
    {action}
  </div>
}

export function SmallStatus({type='neutral',children}) {
  const icon=type==='good'?<CheckCircle2 className="h-3.5 w-3.5"/>:type==='warn'?<Clock3 className="h-3.5 w-3.5"/>:<Activity className="h-3.5 w-3.5"/>
  return <div className={cn('inline-flex items-center gap-1.5 text-xs',type==='good'?'text-emerald-300':type==='warn'?'text-amber-300':'text-slate-400')}>{icon}{children}</div>
}
