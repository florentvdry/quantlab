'use client'
import {useEffect,useMemo,useState} from 'react'
import {LineChart,Line,XAxis,YAxis,Tooltip,ResponsiveContainer} from 'recharts'

const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000'
const pct=v=>v==null?'—':(Number(v)*100).toFixed(1)+'%'
const num=(v,d=3)=>v==null?'—':Number(v).toFixed(d)
const JOB_LABELS={
  BACKTEST:'META V2 Backtest',ADAPTIVE_BACKTEST:'Adaptive META V3',BASELINE:'Baseline momentum',SWEEP:'Parameter sweep',ROBUSTNESS:'Robustness',
  TRAIN_RIDGE:'Walk-forward Ridge',TRAIN_HGB:'Walk-forward HGB',FACTOR_SUMMARY:'Factor Research',
  VALIDATION:'Validation Gate',DATA_REFRESH:'Market data',SEC_REFRESH:'SEC',DAILY_PIPELINE:'Daily Pipeline',
  PAPER_SNAPSHOT:'Paper Snapshot'
}
const STATUS_LABELS={QUEUED:'En attente',RUNNING:'En cours',COMPLETED:'Terminé',FAILED:'Échec'}

function Card({title,children,className=''}){return <section className={'card '+className}>{title&&<h3>{title}</h3>}{children}</section>}
function Empty({children}){return <div className="empty">{children}</div>}
function Pill({ok,children}){return <span className={'pill '+(ok?'completed':'failed')}>{children}</span>}
function Metric({label,value,sub}){return <Card><div className="muted">{label}</div><div className="big">{value}</div>{sub&&<div className="muted mini">{sub}</div>}</Card>}

export default function Home(){
  const [tab,setTab]=useState('Overview')
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const [msg,setMsg]=useState('')
  const [msgType,setMsgType]=useState('info')
  const [dash,setDash]=useState(null)
  const [sys,setSys]=useState(null)
  const [setup,setSetup]=useState(null)
  const [jobs,setJobs]=useState([])
  const [backtests,setBacktests]=useState([])
  const [factors,setFactors]=useState([])
  const [datasets,setDatasets]=useState({})
  const [strategies,setStrategies]=useState([])
  const [models,setModels]=useState([])
  const [experiments,setExperiments]=useState([])
  const [validation,setValidation]=useState(null)
  const [quality,setQuality]=useState(null)
  const [factorSummary,setFactorSummary]=useState(null)
  const [clock,setClock]=useState(null)
  const [positions,setPositions]=useState([])
  const [orders,setOrders]=useState([])
  const [fills,setFills]=useState([])
  const [perf,setPerf]=useState(null)
  const [preview,setPreview]=useState(null)
  const [selectedSymbol,setSelectedSymbol]=useState(null)
  const [explain,setExplain]=useState(null)
  const [selectedBacktest,setSelectedBacktest]=useState(null)
  const [cfg,setCfg]=useState({long_count:20,short_count:20,rebalance_days:5,commission_bps:6,slippage_bps:5,gross_exposure:2,initial_capital:100000,adaptive_lookback_days:252})

  const request=async(path,opt)=>{
    const r=await fetch(API+path,opt)
    let body={}
    try{body=await r.json()}catch{}
    if(!r.ok){
      const d=body?.detail
      const m=typeof d==='string'?d:(d?.message||body?.message||JSON.stringify(d||body)||('HTTP '+r.status))
      throw new Error(m)
    }
    return body
  }

  const load=async(silent=false)=>{
    if(!silent)setLoading(true)
    const calls=[
      ['/api/dashboard',setDash],['/api/system/status',setSys],['/api/setup',setSetup],['/api/jobs',setJobs],
      ['/api/backtests',setBacktests],['/api/factors/latest',setFactors],['/api/system/datasets',setDatasets],
      ['/api/strategies',setStrategies],['/api/models',setModels],['/api/experiments',setExperiments],
      ['/api/validation/latest',setValidation],['/api/data/quality',setQuality],['/api/paper/positions',setPositions],
      ['/api/paper/orders',setOrders],['/api/paper/fills',setFills],['/api/paper/performance',setPerf]
    ]
    try{
      const values=await Promise.all(calls.map(([p])=>request(p).catch(e=>({__error:e.message}))))
      values.forEach((v,i)=>{if(!v?.__error)calls[i][1](v)})
      try{setClock(await request('/api/paper/clock'))}catch{}
    }finally{if(!silent)setLoading(false)}
  }

  useEffect(()=>{load();const t=setInterval(()=>load(true),5000);return()=>clearInterval(t)},[])

  const activeJobs=useMemo(()=>jobs.filter(j=>j.status==='QUEUED'||j.status==='RUNNING'),[jobs])
  const latestActive=activeJobs[0]

  const flash=(text,type='info')=>{setMsg(text);setMsgType(type)}
  const postJob=async(path,label,body=cfg)=>{
    flash(label+' — mise en file…','loading')
    try{
      const x=await request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      flash(label+' ajouté à la file ('+x.job_key.slice(0,8)+')','success')
      await load(true)
    }catch(e){flash(label+' — '+e.message,'error')}
  }
  const direct=async(label,fn)=>{
    setBusy(true);flash(label+'…','loading')
    try{const r=await fn();flash(label+' terminé','success');await load(true);return r}
    catch(e){flash(label+' — '+e.message,'error')}
    finally{setBusy(false)}
  }

  const showExplain=async(symbol)=>{
    setSelectedSymbol(symbol);setExplain(null)
    try{setExplain(await request('/api/factors/'+encodeURIComponent(symbol)+'/explain'))}
    catch(e){flash(e.message,'error')}
  }
  const openBacktest=async(id)=>{
    setSelectedBacktest(null);setTab('Backtests')
    try{setSelectedBacktest(await request('/api/backtests/'+id))}catch(e){flash(e.message,'error')}
  }

  if(loading&&!dash)return <main className="wrap"><div className="loadingScreen"><span className="spinner"/><h2>Chargement de Quant Lab…</h2><p className="muted">API, dataset, Feature Store et derniers résultats.</p></div></main>

  const tabs=['Overview','Data','Research','Models','Backtests','Validation','Signals','Paper','System']
  return <main className="wrap">
    <header className="head">
      <div><h1>Quant Lab <span className="muted">V1.1</span></h1><div className="muted">Data → Research → Validation → Strategy → Alpaca Paper</div></div>
      <div className="headState"><b>{sys?.data_mode?.toUpperCase()}</b><span>/ PAPER</span><span className={sys?.paper_orders_enabled?'dangerText':'positive'}>{sys?.paper_orders_enabled?'ARMED':'LOCKED'}</span></div>
    </header>

    <nav className="tabs">{tabs.map(x=><button key={x} className={tab===x?'active':''} onClick={()=>setTab(x)}>{x}</button>)}</nav>

    {(msg||latestActive)&&<div className={'statusBanner '+(latestActive?'loading':msgType)}>
      {(latestActive||msgType==='loading')&&<span className="spinner small"/>}
      <div className="grow">
        <b>{latestActive?(JOB_LABELS[latestActive.kind]||latestActive.kind)+' — '+(STATUS_LABELS[latestActive.status]||latestActive.status):msg}</b>
        {latestActive&&<><div className="muted mini">{latestActive.message||('Progression '+latestActive.progress+'%')}</div><div className="progress"><span style={{width:Math.max(3,latestActive.progress||0)+'%'}}/></div></>}
      </div>
    </div>}

    {tab==='Overview'&&<>
      <div className="grid">
        <Metric label="Paper Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()} sub={dash?.broker?.provider}/>
        <Metric label="Dernier Sharpe" value={dash?.last_backtest?.sharpe??'—'} sub={dash?.last_backtest?.dataset?.mode||'legacy'}/>
        <Metric label="Validation" value={validation?.tier||'NOT RUN'} sub={validation?.passed?'Paper ready':'Research gate'}/>
        <Metric label="Market" value={clock?.is_open?'OPEN':'CLOSED'} sub={clock?.next_open?('Next '+clock.next_open):''}/>
      </div>
      <div className="two section">
        <Card title="Setup / Readiness">
          {!setup?.steps?.length?<Empty>Aucun état de setup.</Empty>:setup.steps.map(s=><div className="checkRow" key={s.name}><Pill ok={s.ok}>{s.ok?'PASS':'BLOCK'}</Pill><div><b>{s.name}</b><div className="muted mini">{typeof s.detail==='string'?s.detail:''}</div></div></div>)}
        </Card>
        <Card title="Actions">
          <div className="actionGrid">
            <button className="btn" disabled={busy||activeJobs.some(j=>j.kind==='DAILY_PIPELINE')} onClick={()=>postJob('/api/jobs/daily-pipeline?force_market=true','Daily Pipeline',{})}>{activeJobs.some(j=>j.kind==='DAILY_PIPELINE')?'Pipeline en cours…':'Run Daily Pipeline'}</button>
            <button className="btn2" onClick={()=>postJob('/api/jobs/adaptive-backtest','Adaptive META V3')}>Adaptive META V3</button>
            <button className="btn2" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Validation</button>
            <button className="btn2" onClick={()=>setTab('Research')}>Open Research</button>
          </div>
          <p className="muted mini">Paper execution reste bloqué tant que la stratégie n’est pas validée et promue.</p>
        </Card>
      </div>
      <Card title="Background Jobs" className="section"><JobsTable jobs={jobs}/></Card>
    </>}

    {tab==='Data'&&<>
      <div className="two">
        <Card title="Dataset / Feature Versions">
          {!Object.keys(datasets||{}).length?<Empty>Lance le Daily Pipeline.</Empty>:<table><thead><tr><th>Layer</th><th>Version</th><th>Latest</th><th>Rows</th></tr></thead><tbody>{Object.entries(datasets).map(([k,v])=><tr key={k}><td>{k}</td><td>{v.version||v.status||'—'}</td><td>{v.latest||'—'}</td><td>{v.rows||'—'}</td></tr>)}</tbody></table>}
        </Card>
        <Card title="Data Quality">
          {!quality?<Empty>Pas de rapport.</Empty>:<><div className="big">{quality.status}</div>{(quality.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'WARN'}</Pill><span>{c.name}</span></div>)}</>}
        </Card>
      </div>
      <Card title="Data operations" className="section"><div className="row">
        <button className="btn2" onClick={()=>postJob('/api/jobs/data-refresh','Market data refresh',{})}>Refresh Alpaca</button>
        <button className="btn2" onClick={()=>postJob('/api/jobs/sec-refresh','SEC refresh',{})}>Refresh SEC</button>
        <button className="btn" onClick={()=>postJob('/api/jobs/daily-pipeline?force_market=true&refresh_sec=true','Full Daily Pipeline',{})}>Full Pipeline</button>
      </div></Card>
    </>}

    {tab==='Research'&&<>
      <Card title="Factor Research">
        <div className="row"><button className="btn" onClick={()=>direct('Factor Research',async()=>{const x=await request('/api/research/factors');setFactorSummary(x);return x})}>Load Factor Research</button><button className="btn2" onClick={()=>postJob('/api/jobs/factor-summary','Factor Research',{})}>Queue</button></div>
        {!factorSummary?.factors?.length?<Empty>Charge le rapport pour comparer les facteurs.</Empty>:<table><thead><tr><th>Factor</th><th>Mean IC</th><th>IC IR</th><th>Positive IC</th><th>Top-Bottom 20D</th></tr></thead><tbody>{factorSummary.factors.map(f=><tr key={f.feature}><td>{f.feature}</td><td>{num(f.mean_rank_ic,4)}</td><td>{num(f.ic_ir,3)}</td><td>{pct(f.positive_ic_ratio)}</td><td>{pct(f.top_bottom_future_20d)}</td></tr>)}</tbody></table>}
      </Card>
      <Card title="Research rule" className="section"><p>Le score complexe doit être comparé à une baseline momentum simple et évalué hors échantillon. Un Sharpe in-sample positif ne suffit pas.</p></Card>
    </>}

    {tab==='Models'&&<>
      <div className="two">
        <Card title="Train / Walk-forward"><div className="actionGrid"><button className="btn" onClick={()=>postJob('/api/jobs/train/ridge','Walk-forward Ridge',{})}>Train Ridge</button><button className="btn2" onClick={()=>postJob('/api/jobs/train/hgb','Walk-forward HGB',{})}>Train HGB</button></div></Card>
        <Card title="Model Registry">{!models.length?<Empty>Aucun modèle entraîné.</Empty>:<table><thead><tr><th>Model</th><th>Version</th><th>Status</th><th>OOS IC</th></tr></thead><tbody>{models.map(m=><tr key={m.id}><td>{m.name}</td><td>v{m.version}</td><td>{m.status}</td><td>{num(m.metrics?.oos_mean_rank_ic??m.metrics?.test_mean_rank_ic,4)}</td></tr>)}</tbody></table>}</Card>
      </div>
    </>}

    {tab==='Backtests'&&<>
      <Card title="Strategy Builder">
        <div className="formGrid">{Object.entries(cfg).map(([k,v])=><label key={k}><span>{k}</span><input type="number" step="any" value={v} onChange={e=>setCfg({...cfg,[k]:Number(e.target.value)})}/></label>)}</div>
        <div className="row topGap"><button className="btn" onClick={()=>postJob('/api/jobs/adaptive-backtest','Adaptive META V3')}>Queue Adaptive V3</button><button className="btn2" onClick={()=>postJob('/api/jobs/backtest','META V2')}>Queue META V2</button><button className="btn2" onClick={()=>postJob('/api/jobs/baseline','Momentum baseline')}>Queue Baseline</button><button className="btn2" onClick={()=>postJob('/api/jobs/robustness','Robustness')}>Robustness V2</button><button className="btn2" onClick={()=>postJob('/api/jobs/sweep','Parameter Sweep',{base:cfg,grid:{long_count:[10,20,30],short_count:[10,20,30],rebalance_days:[5,10,21]}})}>Parameter Sweep</button></div>
      </Card>
      {selectedBacktest&&<Card title={selectedBacktest.strategy} className="section">
        <div className="metricRow">
          <span>Sharpe <b>{selectedBacktest.metrics?.sharpe}</b></span><span>CAGR <b>{pct(selectedBacktest.metrics?.cagr)}</b></span><span>Max DD <b>{pct(selectedBacktest.metrics?.max_drawdown)}</b></span><span>IC <b>{num(selectedBacktest.metrics?.mean_rank_ic_20d,4)}</b></span><span>Win rate <b>{pct(selectedBacktest.metrics?.win_rate)}</b></span><span>Profit factor <b>{num(selectedBacktest.metrics?.profit_factor,2)}</b></span>
        </div>
        <div className="metricRow topGap">
          <span>Capital départ <b>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation?.tier||'RESEARCH_ONLY'}</b><div className="mini">Candidat: {validation?.candidate_strategy||'—'}</div></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="Adaptive META V3">{validation?.adaptive_backtest?<><div>Sharpe <b>{validation.adaptive_backtest.sharpe}</b></div><div>CAGR <b>{pct(validation.adaptive_backtest.cagr)}</b></div><div>DD <b>{pct(validation.adaptive_backtest.max_drawdown)}</b></div><div>IC <b>{num(validation.adaptive_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Benchmarks">{validation?.baseline_backtest?<><div>Momentum Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>META V2 Sharpe <b>{validation.fixed_meta_backtest?.sharpe??'—'}</b></div><div>Momentum IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(selectedBacktest.metrics?.initial_capital_usd||0).toLocaleString()}</b></span><span>Capital fin <b>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(selectedBacktest.metrics?.ending_capital_usd||0).toLocaleString()}</b></span><span>P&L net <b className={(selectedBacktest.metrics?.net_pnl_usd||0)>=0?'positive':'negative'}>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(selectedBacktest.metrics?.net_pnl_usd||0).toLocaleString()}</b></span><span>Coûts <b>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(selectedBacktest.metrics?.estimated_costs_usd||0).toLocaleString()}</b></span><span>Long P&L <b>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(selectedBacktest.metrics?.long_pnl_usd||0).toLocaleString()}</b></span><span>Short P&L <b>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(selectedBacktest.metrics?.short_pnl_usd||0).toLocaleString()}</b></span>
        </div>
        <div className="datasetBadge">{selectedBacktest.dataset?.mode||'legacy'} · {selectedBacktest.dataset?.from||'?'} → {selectedBacktest.dataset?.to||'?'} · {selectedBacktest.dataset?.fingerprint||'no fingerprint'}</div>
        <p className="muted mini">{selectedBacktest.audit_note||'Signal au close T, exécution au prochain open.'}</p>
        <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={selectedBacktest.equity_curve||[]}><XAxis dataKey="date" minTickGap={45}/><YAxis domain={['auto','auto']}/><Tooltip/><Line dataKey="equity" dot={false}/></LineChart></ResponsiveContainer></div>
        <h4>Ordres simulés ({selectedBacktest.order_ledger?.length||0})</h4>
        {!selectedBacktest.order_ledger?.length?<Empty>Ancien backtest : relance un V2/V3 pour obtenir le journal détaillé.</Empty>:<div className="tableScroll"><table><thead><tr><th>Date</th><th>Symbole</th><th>Action</th><th>Prix</th><th>Qté</th><th>Notionnel</th><th>Coût</th></tr></thead><tbody>{selectedBacktest.order_ledger.slice(-250).reverse().map((o,i)=><tr key={o.rebalance_id+'-'+o.symbol+'-'+i}><td>{o.date}</td><td><b>{o.symbol}</b></td><td className={o.action==='BUY'||o.action==='COVER'?'positive':'negative'}>{o.action}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(o.price,2)}</td><td>{num(o.qty,3)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(o.notional_usd||0).toLocaleString()}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(o.estimated_cost_usd,2)}</td></tr>)}</tbody></table></div>}
        <h4>Positions / P&L par période ({selectedBacktest.position_ledger?.length||0})</h4>
        {!selectedBacktest.position_ledger?.length?<Empty>Pas de ledger disponible.</Empty>:<div className="tableScroll"><table><thead><tr><th>Signal</th><th>Entrée</th><th>Sortie</th><th>Symbole</th><th>Side</th><th>Rang</th><th>Score</th><th>Prix entrée</th><th>Prix sortie</th><th>Qté</th><th>Return</th><th>P&L brut</th><th>Coût</th><th>P&L net</th></tr></thead><tbody>{selectedBacktest.position_ledger.slice(-250).reverse().map((t,i)=><tr key={t.rebalance_id+'-'+t.symbol+'-'+i}><td>{t.signal_date}</td><td>{t.entry_date}</td><td>{t.exit_date}</td><td><b>{t.symbol}</b></td><td className={t.side==='LONG'?'positive':'negative'}>{t.side}</td><td>#{t.rank}</td><td>{num(t.signal_score,4)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(t.entry_price,2)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(t.exit_price,2)}</td><td>{num(t.qty,3)}</td><td>{pct(t.asset_return)}</td><td className={(t.gross_pnl_usd||0)>=0?'positive':'negative'}>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(t.gross_pnl_usd,2)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(t.estimated_cost_usd,2)}</td><td className={(t.net_pnl_usd||0)>=0?'positive':'negative'}>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(t.net_pnl_usd,2)}</td></tr>)}</tbody></table></div>}
        <h4>Rebalances ({selectedBacktest.rebalance_ledger?.length||0})</h4>
        {selectedBacktest.rebalance_ledger?.length>0&&<div className="tableScroll"><table><thead><tr><th>#</th><th>Signal</th><th>Entrée</th><th>Sortie</th><th>Turnover</th><th>Equity avant</th><th>P&L brut</th><th>Coûts</th><th>P&L net</th><th>Equity après</th></tr></thead><tbody>{selectedBacktest.rebalance_ledger.slice(-100).reverse().map(r=><tr key={r.rebalance_id}><td>#{r.rebalance_id}</td><td>{r.signal_date}</td><td>{r.entry_date}</td><td>{r.exit_date}</td><td>{pct(r.turnover)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(r.equity_before_usd||0).toLocaleString()}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(r.gross_pnl_usd,2)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(r.cost_usd,2)}</td><td className={(r.net_pnl_usd||0)>=0?'positive':'negative'}>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+num(r.net_pnl_usd,2)}</td><td>{'
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
+Number(r.equity_after_usd||0).toLocaleString()}</td></tr>)}</tbody></table></div>}
      </Card>}
      <Card title="Backtest Registry" className="section">{!backtests.length?<Empty>Aucun backtest.</Empty>:<table><thead><tr><th>#</th><th>Strategy</th><th>Data</th><th>Period</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>{backtests.map(b=><tr key={b.id} className="clickable" onClick={()=>openBacktest(b.id)}><td>#{b.id}</td><td>{b.strategy}</td><td>{b.dataset?.mode||'legacy'}</td><td>{b.dataset?.from&&b.dataset?.to?(b.dataset.from+' → '+b.dataset.to):'—'}</td><td>{pct(b.cagr)}</td><td>{b.sharpe}</td><td>{pct(b.max_drawdown)}</td></tr>)}</tbody></table>}</Card>
    </>}

    {tab==='Validation'&&<>
      <Card title="Validation Gate">
        <div className="row"><button className="btn" onClick={()=>postJob('/api/jobs/validation','Validation Gate')}>Run Full Validation</button></div>
        {!validation||validation.status==='NOT_RUN'?<Empty>Aucune validation complète. Lance-la après le Daily Pipeline.</Empty>:<>
          <div className={'validationHero '+(validation.passed?'pass':'block')}><b>{validation.passed?'PAPER ELIGIBLE':'BLOCKED'}</b></div>
          {(validation.checks||[]).map(c=><div className="checkRow" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><div><b>{c.name}</b><div className="muted mini">{typeof c.detail==='object'?JSON.stringify(c.detail):String(c.detail??'')}</div></div></div>)}
        </>}
      </Card>
      <div className="two section">
        <Card title="META">{validation?.meta_backtest?<><div>Sharpe <b>{validation.meta_backtest.sharpe}</b></div><div>IC <b>{num(validation.meta_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
        <Card title="Momentum baseline">{validation?.baseline_backtest?<><div>Sharpe <b>{validation.baseline_backtest.sharpe}</b></div><div>IC <b>{num(validation.baseline_backtest.mean_rank_ic_20d,4)}</b></div></>:<Empty>—</Empty>}</Card>
      </div>
    </>}

    {tab==='Signals'&&<>
      <div className="two">
        <Card title="Latest Ranking">
          {!factors.length?<Empty>Aucun signal.</Empty>:<table><thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>Momentum</th><th>Fund.</th><th>Earnings</th></tr></thead><tbody>{factors.slice(0,30).map((r,i)=><tr className="clickable" key={r.symbol} onClick={()=>showExplain(r.symbol)}><td>{i+1}</td><td><b>{r.symbol}</b></td><td>{r.meta_score}</td><td>{r.momentum_12_1_rank}</td><td>{r.fundamental_raw_rank}</td><td>{r.earnings_raw_rank}</td></tr>)}</tbody></table>}
        </Card>
        <Card title={selectedSymbol?('Why '+selectedSymbol+'?'):'Signal Explainability'}>
          {!explain?<Empty>Clique sur un ticker pour afficher ses contributeurs.</Empty>:<>
            <div className="big">#{explain.rank} <span className="muted">/ {explain.universe_size}</span></div>
            <div>Meta Score <b>{explain.meta_score}</b></div>
            <h4>Factors</h4>{explain.factors.map(f=><div className="factorBar" key={f.key}><span>{f.label}</span><div><i style={{width:(f.rank*100)+'%'}}/></div><b>{pct(f.rank)}</b></div>)}
            <h4>Top contributors</h4>{explain.positive_contributors.map(x=><div className="positive" key={x.key}>+ {x.label} {pct(x.rank)}</div>)}
            <h4>Weak contributors</h4>{explain.negative_contributors.map(x=><div className="negative" key={x.key}>− {x.label} {pct(x.rank)}</div>)}
          </>}
        </Card>
      </div>
    </>}

    {tab==='Paper'&&<>
      <div className="grid">
        <Metric label="Equity" value={'$'+Number(dash?.broker?.equity||0).toLocaleString()}/>
        <Metric label="Buying Power" value={'$'+Number(dash?.broker?.buying_power||0).toLocaleString()}/>
        <Metric label="Paper Return" value={pct(perf?.comparison?.paper_return)}/>
        <Metric label="Orders" value={sys?.paper_orders_enabled?'ARMED':'LOCKED'}/>
      </div>
      <Card title="Rebalance / Risk Gate" className="section">
        <div className="row"><button className="btn2" onClick={()=>direct('Preview Rebalance',async()=>{const x=await request('/api/paper/rebalance/preview?n='+cfg.long_count);setPreview(x);return x})}>Preview Rebalance</button><button className="btn2" onClick={()=>direct('Paper Snapshot',()=>request('/api/paper/snapshot',{method:'POST'}))}>Snapshot</button><button className="btn2" onClick={()=>direct('Reconcile',()=>request('/api/paper/reconcile',{method:'POST'}))}>Reconcile</button></div>
        {preview&&<><div className="checksGrid">{preview.risk?.checks?.map(c=><div className="checkTile" key={c.name}><Pill ok={c.ok}>{c.ok?'PASS':'BLOCK'}</Pill><span>{c.name}</span></div>)}</div><p>{preview.proposed_orders?.length||0} actions proposées.</p></>}
      </Card>
      <div className="two section">
        <Card title="Broker Positions">{!positions.length?<Empty>Aucune position.</Empty>:<table><tbody>{positions.map(p=><tr key={p.symbol}><td><b>{p.symbol}</b></td><td className={p.side==='LONG'?'positive':'negative'}>{p.side}</td><td>{pct(p.weight)}</td><td>${Number(p.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
        <Card title="Tracked Orders">{!orders.length?<Empty>Aucun ordre.</Empty>:<table><tbody>{orders.slice(0,30).map(o=><tr key={o.client_order_id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>${Number(o.notional).toFixed(0)}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="Kill Switch" className="section dangerCard"><p>V1 : PAPER uniquement.</p><div className="row"><button className="dangerBtn" onClick={()=>{if(confirm('Annuler tous les ordres PAPER ouverts ?'))direct('Cancel open PAPER orders',()=>request('/api/paper/kill/cancel-orders',{method:'POST'}))}}>Cancel Open Orders</button><button className="dangerBtn" onClick={()=>{if(confirm('FLATTEN tout le portefeuille PAPER ?'))direct('Flatten PAPER',()=>request('/api/paper/kill/flatten?confirm=FLATTEN_PAPER',{method:'POST'}))}}>Flatten PAPER</button></div></Card>
    </>}

    {tab==='System'&&<>
      <div className="two">
        <Card title="Runtime"><table><tbody><tr><td>Data mode</td><td>{sys?.data_mode}</td></tr><tr><td>Alpaca</td><td>{sys?.alpaca_configured?'connected':'not configured'}</td></tr><tr><td>Trading env</td><td>{sys?.trading_env}</td></tr><tr><td>Live trading</td><td>{sys?.live_trading_supported?'SUPPORTED':'NOT IMPLEMENTED'}</td></tr><tr><td>Paper Auto</td><td>{sys?.paper_auto_enabled?'ON':'OFF'}</td></tr></tbody></table></Card>
        <Card title="Recent Fills">{!fills.length?<Empty>Aucun fill.</Empty>:<table><tbody>{fills.slice(0,20).map(f=><tr key={f.id}><td>{f.symbol}</td><td>{f.side}</td><td>{f.qty}</td><td>${num(f.price,2)}</td><td>{f.event}</td></tr>)}</tbody></table>}</Card>
      </div>
      <Card title="All Jobs" className="section"><JobsTable jobs={jobs}/></Card>
      <Card title="Experiments" className="section">{!experiments.length?<Empty>Aucune expérience.</Empty>:<table><tbody>{experiments.map(e=><tr key={e.id}><td>#{e.id}</td><td>{e.name}</td><td>{e.kind}</td><td>{e.status}</td></tr>)}</tbody></table>}</Card>
    </>}
  </main>
}

function JobsTable({jobs}){
  if(!jobs.length)return <Empty>Aucun job lancé.</Empty>
  return <table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{jobs.slice(0,30).map(j=><tr key={j.job_key}><td>{JOB_LABELS[j.kind]||j.kind}</td><td><span className={'pill '+String(j.status).toLowerCase()}>{STATUS_LABELS[j.status]||j.status}</span></td><td><div className="progress compact"><span style={{width:(j.progress||0)+'%'}}/></div><small>{j.progress}%</small></td><td>{j.error?<span className="negative">{j.error}</span>:(j.message||'—')}</td></tr>)}</tbody></table>
}
