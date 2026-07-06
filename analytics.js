// Pure analytics for Protokół — no DOM, no globals, no Date inside math.
// Browser: functions become globals. Node/tests: require('./analytics.js').
function ema(values, alpha){
  const out=[]; let cur=null;
  for(const v of values){
    if(v==null||isNaN(v)){ out.push(cur); continue; }
    cur = (cur==null) ? v : cur + alpha*(v-cur);
    out.push(cur);
  }
  return out;
}

function _days(a,b){ return Math.round((Date.parse(b)-Date.parse(a))/86400000); }

function weightTrend(points, alpha){
  const out=[]; let cur=null, prevK=null;
  for(const p of points){
    if(p==null||p.v==null||isNaN(p.v)) continue;
    if(cur==null){ cur=p.v; }
    else {
      const gap=Math.max(1, prevK?_days(prevK,p.k):1);
      for(let i=0;i<gap;i++) cur += alpha*(p.v-cur);
    }
    prevK=p.k;
    out.push({k:p.k, raw:p.v, ema:Math.round(cur*1000)/1000});
  }
  return out;
}

function linreg(ys){
  const n=ys.length;
  if(n<2) return {m:null,b:null,seM:null,n,r2:null};
  let sx=0,sy=0,sxx=0,sxy=0;
  for(let i=0;i<n;i++){ sx+=i; sy+=ys[i]; sxx+=i*i; sxy+=i*ys[i]; }
  const dx=n*sxx-sx*sx;
  const m=(n*sxy-sx*sy)/dx;
  const b=(sy-m*sx)/n;
  let ssRes=0, ssTot=0; const my=sy/n;
  for(let i=0;i<n;i++){ const f=m*i+b; ssRes+=(ys[i]-f)**2; ssTot+=(ys[i]-my)**2; }
  const seM = n>2 ? Math.sqrt((ssRes/(n-2))/(sxx-sx*sx/n)) : 0;
  const r2 = ssTot>0 ? 1-ssRes/ssTot : 1;
  return {m,b,seM,n,r2};
}

function weightSlope(trend, windowDays){
  const ys=trend.slice(-windowDays).map(p=>p.ema);
  const r=linreg(ys);
  r.cur = trend.length?trend[trend.length-1].ema:null;
  return r;
}

function etaProject(trend, slope, target, opts){
  const nMin=(opts&&opts.nMin)||14, k=(opts&&opts.k)||1;
  const {m, seM, n, r2, cur} = slope;
  const base = {cur, target, m, seM, n, r2,
    weeklyRateKg: m!=null?m*7:null,
    weeklyRatePct: (m!=null&&cur)?m*7/cur*100:null,
    daysExpected:null, daysEarliest:null, daysLatest:null};
  if(m==null || n<nMin) return {...base, status:"insufficient"};
  if(m>=0 || (m+k*seM)>=0) return {...base, status:"flat"};
  const off=(slopeM)=> (cur-target)/(-slopeM);           // days at slope (kg/day)
  const mFast=m-k*seM, mSlow=m+k*seM;                    // both negative in "ok" branch
  return {...base, status:"ok",
    daysExpected: Math.round(off(m)),
    daysEarliest: Math.round(off(mFast)),
    daysLatest: mSlow<0 ? Math.round(off(mSlow)) : null}; // null → "nieokreślony"
}

function rateBand(weeklyRatePct, m, opts){
  const fast=opts.fastPct, hard=opts.hardFastPct, stall=opts.stallPct;
  if(m==null) return {band:"ok", pct:null};
  const pct=Math.abs(weeklyRatePct);
  if(m>=0) return {band:"stall", pct};
  if(pct>hard) return {band:"hardFast", pct};
  if(pct>fast) return {band:"fast", pct};
  if(pct<stall) return {band:"stall", pct};
  return {band:"ok", pct};
}

function epley(kg,reps){ return reps===1 ? kg : kg*(1+reps/30); }
function brzycki(kg,reps){ return kg*36/(37-reps); }
function e1rmSeries(hist, maxReps){
  return (hist||[]).filter(e=>e&&e.reps>0&&e.reps<=maxReps&&e.kg>0)
    .map(e=>({d:e.d, e1rm:epley(e.kg,e.reps)}));
}
function _mondayKey(dstr){
  const t=Date.parse(dstr); const d=new Date(t);
  const wd=(d.getUTCDay()+6)%7; const mon=new Date(t-wd*86400000);
  return mon.toISOString().slice(0,10);
}
function weeklyVolume(hist, schemeReps){
  const by={};
  for(const e of (hist||[])){ if(!e||e.kg==null||!e.d) continue;
    const reps=(e.reps>0)?e.reps:(schemeReps||0); if(!reps) continue;
    const wk=_mondayKey(e.d); by[wk]=(by[wk]||0)+e.kg*reps; }
  return Object.keys(by).sort().map(week=>({week, vol:Math.round(by[week])}));
}
function _trend(series, key){ if(!series||series.length<2) return null;
  const a=series[0][key], b=series[series.length-1][key];
  return b>a*1.02?"up":b<a*0.98?"down":"flat"; }
function strengthRetention(exHist, exMeta, cfg){
  const maxReps=(cfg&&cfg.maxValidReps)||12;
  const per=[]; let anyReps=false;
  for(const id in (exHist||{})){
    const hist=exHist[id]; const es=e1rmSeries(hist,maxReps);
    if(es.length) anyReps=true;
    const vs=weeklyVolume(hist, (exMeta&&exMeta[id]&&exMeta[id].schemeReps)||0);
    per.push({id, name:(exMeta&&exMeta[id]&&exMeta[id].name)||id,
      e1rmSeries:es.length?es:null,
      e1rmDelta:es.length>=2?Math.round((es[es.length-1].e1rm-es[0].e1rm)*10)/10:null,
      volSeries:vs, volDelta:vs.length>=2?vs[vs.length-1].vol-vs[0].vol:null});
  }
  const e1rmTrends=per.map(p=>p.e1rmSeries&&_trend(p.e1rmSeries,'e1rm')).filter(Boolean);
  const overallE=e1rmTrends.length?(e1rmTrends.includes("down")?"down":e1rmTrends.includes("up")?"up":"flat"):null;
  const volTrends=per.map(p=>_trend(p.volSeries,'vol')).filter(Boolean);
  const overallV=volTrends.length?(volTrends.includes("down")?"down":volTrends.includes("up")?"up":"flat"):null;
  return {perExercise:per, overall:{e1rmTrend:overallE, volTrend:overallV, dataQuality:anyReps?"reps":"weight-only"}};
}

if (typeof module!=='undefined' && module.exports) module.exports = { ema, weightTrend, linreg, weightSlope, etaProject, rateBand, epley, brzycki, e1rmSeries, weeklyVolume, strengthRetention };
