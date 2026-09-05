export const money=v=>v==null?'—':new Intl.NumberFormat('fr-FR',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(Number(v))
export const pct=v=>v==null?'—':(Number(v)*100).toFixed(1)+'%'
export const num=(v,d=3)=>v==null?'—':Number(v).toFixed(d)
export const shortDate=v=>v?new Date(v).toLocaleString('fr-FR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'—'
export const safeArray=v=>Array.isArray(v)?v:[]
