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
  if(m>=0) return {...base, status:"rising"};
  if((m+k*seM)>=0) return {...base, status:"flat"};
  const off=(slopeM)=> (cur-target)/(-slopeM);           // days at slope (kg/day)
  const mFast=m-k*seM, mSlow=m+k*seM;                    // both negative in "ok" branch
  return {...base, status:"ok",
    daysExpected: Math.round(off(m)),
    daysEarliest: Math.round(off(mFast)),
    daysLatest: mSlow<0 ? Math.round(off(mSlow)) : null}; // mSlow always <0 here (flat guard dominates); null kept defensive
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

function weeklyGood(hits, eligible, threshold){
  if(!eligible) return null;                 // zero eligible → neutral (bridges)
  return hits >= Math.ceil(eligible*threshold);
}
function streakCount(weekFlags){
  let n=0;
  for(let i=weekFlags.length-1;i>=0;i--){
    const f=weekFlags[i];
    if(f===null) continue;                   // neutral bridges
    if(f===true) n++; else break;
  }
  return n;
}
function _weekKey(dstr){                      // Monday (UTC) of the ISO week, deterministic
  const t=Date.parse(dstr); const wd=(new Date(t).getUTCDay()+6)%7;
  return new Date(t-wd*86400000).toISOString().slice(0,10);
}
function computeStreaks(rows, opts){
  const {proteinG,stepGoal,sleepGoalH,weekThreshold,trainedDates,trainingWeekdays,bestStored,todayKey}=opts;
  const thisWeek=_weekKey(todayKey);
  const HAB=[
    {key:'protein',icon:'🥩',label:'Białko', hit:r=>r.bialko!=null&&!isNaN(r.bialko)&&r.bialko>=proteinG, elig:r=>r.bialko!=null&&!isNaN(r.bialko)},
    {key:'steps',  icon:'🚶',label:'Kroki',  hit:r=>r.kroki!=null&&!isNaN(r.kroki)&&r.kroki>=stepGoal,    elig:r=>r.kroki!=null&&!isNaN(r.kroki)},
    {key:'sleep',  icon:'😴',label:'Sen',    hit:r=>r.sen!=null&&!isNaN(r.sen)&&r.sen>=sleepGoalH,        elig:r=>r.sen!=null&&!isNaN(r.sen)},
    {key:'training',icon:'💪',label:'Trening',hit:r=>trainedDates.has(r.data),
       elig:r=>trainingWeekdays.has((new Date(Date.parse(r.data)).getUTCDay())) },
  ];
  return HAB.map(h=>{
    const byWeek={};
    for(const r of rows){ if(!r||!r.data) continue; const wk=_weekKey(r.data);
      const b=(byWeek[wk]=byWeek[wk]||{hits:0,elig:0});
      if(h.elig(r)){ b.elig++; if(h.hit(r)) b.hits++; } }
    const weeks=Object.keys(byWeek).sort();
    const complete=weeks.filter(w=>w<thisWeek);
    const flags=complete.map(w=>weeklyGood(byWeek[w].hits, byWeek[w].elig, weekThreshold));
    const current=streakCount(flags);
    const tw=byWeek[thisWeek]||{hits:0,elig:0};
    const best=Math.max((bestStored&&bestStored[h.key])||0, current);
    return {key:h.key, icon:h.icon, label:h.label, current, best, thisWeek:{hits:tw.hits, elig:tw.elig}};
  });
}

function _mean(vals){
  const v=(vals||[]).filter(x=>x!=null&&!isNaN(x));
  return v.length ? v.reduce((a,b)=>a+b,0)/v.length : null;
}

function weeklyCheckin(rows, opts){
  const {waistByDate, trainedDates, trainingWeekdays, streaks, todayKey}=opts;
  const thisWeek=_weekKey(todayKey);

  // Group rows by week; collect all week keys appearing in data
  const byWeek={};
  for(const r of (rows||[])){
    if(!r||!r.data) continue;
    const wk=_weekKey(r.data);
    (byWeek[wk]=byWeek[wk]||[]).push(r);
  }
  // Also register weeks from waistByDate
  for(const d of Object.keys(waistByDate||{})){
    const wk=_weekKey(d);
    byWeek[wk]=byWeek[wk]||[];
  }

  const completeWeeks=Object.keys(byWeek).filter(w=>w<thisWeek).sort();

  const neutral={weekOf:null,
    deltas:{waga:null,talia:null,bodyFat:null,bialko:null,sen:null,hrv:null},
    sessions:{done:0,planned:0}, streakSummary:[], winLine:'Zbieramy dane — wróć za tydzień!'};
  if(completeWeeks.length<2) return neutral;

  const lastWeek=completeWeeks[completeWeeks.length-1];
  const priorWeek=completeWeeks[completeWeeks.length-2];
  if (Date.parse(lastWeek) - Date.parse(priorWeek) !== 7*86400000) return neutral;
  const lastRows=byWeek[lastWeek]||[];
  const priorRows=byWeek[priorWeek]||[];

  function fieldDelta(f){
    const lm=_mean(lastRows.map(r=>r[f]));
    const pm=_mean(priorRows.map(r=>r[f]));
    return (lm==null||pm==null)?null:lm-pm;
  }
  function waistDelta(){
    const wb=waistByDate||{};
    const lm=_mean(Object.entries(wb).filter(([d])=>_weekKey(d)===lastWeek).map(([,v])=>v));
    const pm=_mean(Object.entries(wb).filter(([d])=>_weekKey(d)===priorWeek).map(([,v])=>v));
    return (lm==null||pm==null)?null:lm-pm;
  }

  const deltas={
    waga:fieldDelta('waga'), talia:waistDelta(),
    bodyFat:fieldDelta('bodyFat'), bialko:fieldDelta('bialko'),
    sen:fieldDelta('sen'), hrv:fieldDelta('hrv'),
  };

  // Sessions in lastWeek (Mon–Sun)
  const t0=Date.parse(lastWeek);
  let done=0, planned=0;
  for(let i=0;i<7;i++){
    const d=new Date(t0+i*86400000);
    const ds=d.toISOString().slice(0,10);
    if(trainedDates&&trainedDates.has(ds)) done++;
    if(trainingWeekdays&&trainingWeekdays.has(d.getUTCDay())) planned++;
  }

  const streakSummary=(streaks||[]).filter(s=>s.current>0).map(s=>({label:s.label,current:s.current}));

  // winLine: pick the single most positive fact
  const candidates=[];
  if(done>=planned&&planned>0)
    candidates.push({msg:'Wszystkie treningi zaliczone!', score:1000});
  const best=streakSummary.reduce((b,s)=>s.current>b.current?s:b,{current:0,label:''});
  if(best.current>0)
    candidates.push({msg:`${best.label}: ${best.current} tyg. z rzędu`, score:best.current});
  if(deltas.waga!=null&&deltas.waga<0)
    candidates.push({msg:`Waga ↓ ${Math.abs(deltas.waga).toFixed(1)} kg w tygodniu`, score:Math.abs(deltas.waga)*10});
  if(deltas.talia!=null&&deltas.talia<0)
    candidates.push({msg:`Talia ↓ ${Math.abs(deltas.talia).toFixed(1)} cm w tygodniu`, score:Math.abs(deltas.talia)*5});
  candidates.sort((a,b)=>b.score-a.score);
  const winLine=candidates.length?candidates[0].msg:'Dobra robota — trzymaj kurs!';

  return {weekOf:lastWeek, deltas, sessions:{done,planned}, streakSummary, winLine};
}

if (typeof module!=='undefined' && module.exports) module.exports = { ema, weightTrend, linreg, weightSlope, etaProject, rateBand, epley, brzycki, e1rmSeries, weeklyVolume, strengthRetention, weeklyGood, streakCount, computeStreaks, weeklyCheckin };
