'use client'

import { useEffect, useMemo, useState } from 'react'
import { JobBanner } from './components/ui'
import { ErrorBanner, JOB_LABELS, LoadingScreen, TopNav } from './components/shell'
import { DashboardView, ResearchView, SignalDrawer, SignalsView } from './components/views-main'
import { BacktestsView } from './components/views-backtests'
import { PaperView, SystemView } from './components/views-ops'

const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000'

async function api(path,opt={},timeout=9000){
  const controller=new AbortController()
  const timer=setTimeout(()=>controller.abort(),timeout)
  try{
    const response=await fetch(API+path,{...opt,signal:controller.signal,cache:'no-store'})
    let body={}
    try{body=await response.json()}catch{}
    if(!response.ok){
      const detail=body?.detail
      const message=typeof detail==='string'?detail:(detail?.message||body?.message||'HTTP '+response.status)
      throw new Error(message)
    }
    return body
  }finally{
    clearTimeout(timer)
  }
}

export default function Home(){
  const [view,setView]=useState('dashboard')
  const [snapshot,setSnapshot]=useState(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [refreshing,setRefreshing]=useState(false)
  const [selectedBacktest,setSelectedBacktest]=useState(null)
  const [backtestDetail,setBacktestDetail]=useState(null)
  const [selectedSymbol,setSelectedSymbol]=useState(null)
  const [explain,setExplain]=useState(null)

  const loadSnapshot=async initial=>{
    if(initial)setLoading(true)
    try{
      const data=await api('/api/app/snapshot')
      setSnapshot(data)
      setError('')
      if(!selectedBacktest&&data.backtests?.[0]?.id)setSelectedBacktest(data.backtests[0].id)
    }catch(e){
      setError(e.name==='AbortError'?'API timeout':e.message)
    }finally{
      if(initial)setLoading(false)
    }
  }

  useEffect(()=>{
    loadSnapshot(true)
    const timer=setInterval(()=>loadSnapshot(false),5000)
    return()=>clearInterval(timer)
  },[])

  useEffect(()=>{
    if(!selectedBacktest)return
    let mounted=true
    setBacktestDetail(null)
    api('/api/backtests/'+selectedBacktest,{},12000)
      .then(data=>{if(mounted)setBacktestDetail(data)})
      .catch(e=>{if(mounted)setError(e.message)})
    return()=>{mounted=false}
  },[selectedBacktest])

  const activeJob=useMemo(()=>snapshot?.jobs?.find(j=>j.status==='RUNNING'||j.status==='QUEUED'),[snapshot])
  const candidateRunning=Boolean(snapshot?.jobs?.find(j=>j.kind==='META_V7'&&(j.status==='RUNNING'||j.status==='QUEUED')))

  const refreshAll=async()=>{
    setRefreshing(true)
    try{
      await api('/api/jobs/bootstrap?force_market=true&refresh_sec=false',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
      await loadSnapshot(false)
    }catch(e){
      setError(e.message)
    }finally{
      setRefreshing(false)
    }
  }

  const runCandidate=async()=>{
    try{
      await api('/api/jobs/meta-v7',{method:'POST'})
      await loadSnapshot(false)
    }catch(e){
      setError(e.message)
    }
  }

  const openSignal=async symbol=>{
    setSelectedSymbol(symbol)
    setExplain(null)
    try{
      setExplain(await api('/api/factors/'+encodeURIComponent(symbol)+'/explain',{},8000))
    }catch(e){
      setExplain({error:e.message})
    }
  }

  if(loading&&!snapshot)return <LoadingScreen/>

  return <div className="min-h-screen">
    <TopNav view={view} setView={setView} snapshot={snapshot} onRefresh={refreshAll} refreshing={refreshing}/>
    <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-6 lg:py-8">
      <ErrorBanner message={error} onClose={()=>setError('')}/>
      {view!=='dashboard'&&activeJob&&<JobBanner job={{...activeJob,label:JOB_LABELS[activeJob.kind]||activeJob.kind}}/>}
      {view==='dashboard'&&<DashboardView snapshot={snapshot} onSignal={openSignal}/>}
      {view==='research'&&<ResearchView snapshot={snapshot}/>}
      {view==='backtests'&&<BacktestsView snapshot={snapshot} detail={backtestDetail} onSelect={setSelectedBacktest} onRunCandidate={runCandidate} running={candidateRunning} fetchBacktest={id=>api('/api/backtests/'+id,{},12000)}/>} 
      {view==='signals'&&<SignalsView snapshot={snapshot} onSignal={openSignal}/>}
      {view==='paper'&&<PaperView snapshot={snapshot}/>}
      {view==='system'&&<SystemView snapshot={snapshot} onRefresh={refreshAll} refreshing={refreshing}/>}
    </main>
    <SignalDrawer symbol={selectedSymbol} explain={explain} onClose={()=>{setSelectedSymbol(null);setExplain(null)}}/>
  </div>
}
