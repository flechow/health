const test = require('node:test');
const assert = require('node:assert');
const A = require('../analytics.js');

test('ema converges to a constant', () => {
  const e = A.ema([100,100,100,100,100], 0.1);
  assert.ok(Math.abs(e[4]-100) < 1e-9);
});

test('ema approaches a step change geometrically', () => {
  // old=100 for i0, then new=110; after k steps value ≈ 110-(110-100)*(1-α)^k
  const e = A.ema([100,110,110,110], 0.1);
  const expectAfter3 = 110 - (110-100)*Math.pow(0.9,3);
  assert.ok(Math.abs(e[3]-expectAfter3) < 1e-9, `${e[3]} vs ${expectAfter3}`);
});

test('linreg recovers a known slope', () => {
  const r = A.linreg([10,9,8,7,6]);       // slope -1 per step
  assert.ok(Math.abs(r.m+1) < 1e-9);
  assert.ok(r.seM < 1e-9);                 // perfect line → ~0 std error
  assert.strictEqual(r.n, 5);
});

test('linreg on noisy data gives positive seM', () => {
  const r = A.linreg([10,9.2,8.1,7.4,5.9]);
  assert.ok(r.m < 0);
  assert.ok(r.seM > 0);
});

test('weightTrend steps ema by elapsed days across a gap', () => {
  const pts = [{k:'2026-01-01',v:80},{k:'2026-01-06',v:100}]; // 5-day gap, value jumps 80->100
  const t = A.weightTrend(pts, 0.1);
  assert.strictEqual(t.length, 2);
  const expected = 100 - (100-80)*Math.pow(0.9,5); // 5 EMA steps ≈ 88.19
  assert.ok(Math.abs(t[1].ema - expected) < 0.01, `gap-stepped ema ${t[1].ema} vs ${expected}`);
  assert.strictEqual(t[1].raw, 100);
});

test('weightTrend gap size changes the ema move', () => {
  const oneDay = A.weightTrend([{k:'2026-01-01',v:80},{k:'2026-01-02',v:100}], 0.1);
  const fiveDay = A.weightTrend([{k:'2026-01-01',v:80},{k:'2026-01-06',v:100}], 0.1);
  // 1 step moves 80->82; 5 steps move much further toward 100
  assert.ok(Math.abs(oneDay[1].ema - 82) < 0.01, `1-day ema ${oneDay[1].ema}`);
  assert.ok(fiveDay[1].ema > oneDay[1].ema + 3, `5-day (${fiveDay[1].ema}) should exceed 1-day (${oneDay[1].ema})`);
});

test('weightSlope returns negative slope + cur on a decline', () => {
  const pts = Array.from({length:30},(_,i)=>({k:`2026-02-${String(i+1).padStart(2,'0')}`, v:116-0.1*i}));
  const t = A.weightTrend(pts, 0.1);
  const s = A.weightSlope(t, 28);
  assert.ok(s.m < 0);
  assert.ok(s.cur < 116);
  assert.strictEqual(s.n, 28);
});

test('etaProject on a clean linear decline gives a sane expected offset', () => {
  const pts = Array.from({length:40},(_,i)=>({k:`2026-03-${String(i+1).padStart(2,'0')}`, v:100-0.1*i}));
  const t = A.weightTrend(pts, 0.1);
  const s = A.weightSlope(t, 28);
  const eta = A.etaProject(t, s, 90, {nMin:14, k:1});
  assert.strictEqual(eta.status, 'ok');
  assert.ok(eta.daysExpected > 0);
  assert.ok(eta.daysEarliest <= eta.daysExpected && eta.daysExpected <= eta.daysLatest);
  assert.ok(eta.weeklyRateKg < 0);
});

test('etaProject flat series → status rising (m=0 ≥ 0)', () => {
  const pts = Array.from({length:30},(_,i)=>({k:`2026-04-${String(i+1).padStart(2,'0')}`, v:100}));
  const t=A.weightTrend(pts,0.1); const s=A.weightSlope(t,28);
  assert.strictEqual(A.etaProject(t,s,90,{nMin:14,k:1}).status, 'rising');
});

test('etaProject rising series is not ok', () => {
  const pts = Array.from({length:30},(_,i)=>({k:`2026-05-${String(i+1).padStart(2,'0')}`, v:100+0.05*i}));
  const t=A.weightTrend(pts,0.1); const s=A.weightSlope(t,28);
  assert.strictEqual(A.etaProject(t,s,90,{nMin:14,k:1}).status, 'rising');
});

test('etaProject too few points → insufficient', () => {
  const pts = Array.from({length:5},(_,i)=>({k:`2026-06-0${i+1}`, v:100-0.1*i}));
  const t=A.weightTrend(pts,0.1); const s=A.weightSlope(t,28);
  assert.strictEqual(A.etaProject(t,s,90,{nMin:14,k:1}).status, 'insufficient');
});

test('rateBand classifies loss speed', () => {
  const o={fastPct:1.3,hardFastPct:1.8,stallPct:0.1};
  assert.strictEqual(A.rateBand(-0.75,-0.01,o).band, 'ok');
  assert.strictEqual(A.rateBand(-1.5,-0.02,o).band, 'fast');
  assert.strictEqual(A.rateBand(-2.0,-0.03,o).band, 'hardFast');
  assert.strictEqual(A.rateBand(-0.05,-0.001,o).band, 'stall');
  assert.strictEqual(A.rateBand(0.3,0.004,o).band, 'stall'); // gaining → stall (not losing)
});

test('epley & brzycki hand-checked', () => {
  assert.ok(Math.abs(A.epley(100,5)-116.6667) < 1e-3);
  assert.strictEqual(A.epley(100,1), 100);
  assert.ok(Math.abs(A.brzycki(100,5)-112.5) < 1e-3);
});
test('e1rmSeries excludes missing/over-max reps', () => {
  const hist=[{kg:100,d:'2026-01-01',reps:5},{kg:100,d:'2026-01-08'},{kg:100,d:'2026-01-15',reps:20}];
  const s=A.e1rmSeries(hist,12);
  assert.strictEqual(s.length,1);
  assert.ok(Math.abs(s[0].e1rm-116.6667)<1e-3);
});
test('strengthRetention reports weight-only when no reps', () => {
  const r=A.strengthRetention({sq:[{kg:100,d:'2026-01-01'},{kg:102,d:'2026-01-08'}]}, {sq:{name:'Squat'}}, {maxValidReps:12});
  assert.strictEqual(r.overall.dataQuality,'weight-only');
});
test('weeklyVolume sums actual reps and falls back to schemeReps', () => {
  const hist=[{kg:100,d:'2026-01-05'},{kg:100,d:'2026-01-07',reps:8}]; // same ISO week (Mon 2026-01-05)
  const v=A.weeklyVolume(hist,30);   // 30 = fallback for the no-reps entry
  assert.strictEqual(v.length,1);
  assert.strictEqual(v[0].vol, 100*30+100*8);
});
test('rateBand m==null → ok', () => { assert.strictEqual(A.rateBand(null,null,{fastPct:1.3,hardFastPct:1.8,stallPct:0.1}).band,'ok'); });

test('weeklyGood: 80% threshold, neutral on zero-eligible', () => {
  assert.strictEqual(A.weeklyGood(5,6,0.8), true);   // ceil(4.8)=5
  assert.strictEqual(A.weeklyGood(4,6,0.8), false);
  assert.strictEqual(A.weeklyGood(0,0,0.8), null);   // neutral
});
test('streakCount: trailing goods, bridges neutral, stops at false', () => {
  assert.strictEqual(A.streakCount([true,true,true]), 3);
  assert.strictEqual(A.streakCount([true,false,true,true]), 2);
  assert.strictEqual(A.streakCount([true,null,true]), 2);   // neutral bridges
  assert.strictEqual(A.streakCount([false]), 0);
  assert.strictEqual(A.streakCount([]), 0);
});
test('weeklyCheckin: weight delta is week-avg vs prior-week-avg, M2 line null when absent', () => {
  const rows=[];
  const mk=(d,w,b)=>({data:d, waga:w, bialko:b, sen:7.5, hrv:60, kroki:9000});
  // prior week avg 100, last complete week avg 99 (losing)
  for(let i=0;i<7;i++) rows.push(mk(new Date(Date.parse('2026-06-08')+i*86400000).toISOString().slice(0,10),100,190));
  for(let i=0;i<7;i++) rows.push(mk(new Date(Date.parse('2026-06-15')+i*86400000).toISOString().slice(0,10),99,190));
  const ci=A.weeklyCheckin(rows,{proteinG:180, waistByDate:{}, trainedDates:new Set(),
    trainingWeekdays:new Set([1,2,3,4,5,6]), streaks:[], todayKey:'2026-06-23'});
  assert.ok(ci.deltas.waga < 0);               // week-avg lower than prior
  assert.strictEqual(ci.deltas.talia, null);   // no waist data → omitted
  assert.ok(typeof ci.winLine === 'string' && ci.winLine.length>0);
});

test('weeklyCheckin: empty rows → neutral, never throws', () => {
  const ci=A.weeklyCheckin([], {proteinG:180, waistByDate:{}, trainedDates:new Set(),
    trainingWeekdays:new Set([1,2,3,4,5,6]), streaks:[], todayKey:'2026-06-23'});
  assert.strictEqual(ci.deltas.waga, null);
  assert.ok(typeof ci.winLine==='string' && ci.winLine.length>0);
});

test('weeklyCheckin: non-adjacent weeks → neutral (no misleading delta)', () => {
  const rows=[];
  for(const wStart of ['2026-06-01','2026-06-15']){ // gap: 06-08 week missing
    for(let i=0;i<7;i++) rows.push({data:new Date(Date.parse(wStart)+i*86400000).toISOString().slice(0,10), waga:100, bialko:190, sen:7.5, hrv:60, kroki:9000}); }
  const ci=A.weeklyCheckin(rows,{proteinG:180, waistByDate:{}, trainedDates:new Set(),
    trainingWeekdays:new Set([1,2,3,4,5,6]), streaks:[], todayKey:'2026-06-23'});
  assert.strictEqual(ci.deltas.waga, null);
});

test('weeklyCheckin: sessions.done and sessions.planned counts', () => {
  const rows=[];
  const mk=(d)=>({data:d, waga:80, bialko:190, sen:7.5, hrv:60, kroki:9000});
  // priorWeek (2026-06-08) and lastWeek (2026-06-15) — adjacent, so guard passes
  for(let i=0;i<7;i++) rows.push(mk(new Date(Date.parse('2026-06-08')+i*86400000).toISOString().slice(0,10)));
  for(let i=0;i<7;i++) rows.push(mk(new Date(Date.parse('2026-06-15')+i*86400000).toISOString().slice(0,10)));
  // trainedDates: Mon 2026-06-15 (UTC day 1) and Wed 2026-06-17 (UTC day 3) — both in trainingWeekdays
  const trainedDates=new Set(['2026-06-15','2026-06-17']);
  const trainingWeekdays=new Set([1,3,5]); // Mon, Wed, Fri → 3 planned days in lastWeek
  const ci=A.weeklyCheckin(rows,{proteinG:180, waistByDate:{}, trainedDates,
    trainingWeekdays, streaks:[], todayKey:'2026-06-23'});
  assert.strictEqual(ci.sessions.done, 2);
  assert.strictEqual(ci.sessions.planned, 3);
});

test('computeStreaks: protein streak over complete weeks, in-progress excluded', () => {
  // 3 complete weeks all hitting protein 6/7 days, plus an in-progress bad week
  const rows=[];
  const mk=(d,b)=>({data:d, bialko:b, kroki:9000, sen:8});
  // weeks starting Mon 2026-06-01, 06-08, 06-15 (complete), 06-22 in progress
  for(const [wStart,good] of [['2026-06-01',6],['2026-06-08',6],['2026-06-15',6]]){
    for(let i=0;i<7;i++){ const dt=new Date(Date.parse(wStart)+i*86400000).toISOString().slice(0,10);
      rows.push(mk(dt, i<good?200:100)); }   // `good` days above target 180
  }
  rows.push(mk('2026-06-22',100)); // in-progress week, below target
  const out=A.computeStreaks(rows, {proteinG:180, stepGoal:8000, sleepGoalH:7,
    weekThreshold:0.8, trainedDates:new Set(), trainingWeekdays:new Set([1,2,3,4,5,6]),
    bestStored:{}, todayKey:'2026-06-23'});
  const p=out.find(s=>s.key==='protein');
  assert.strictEqual(p.current, 3);          // 3 good complete weeks
  assert.strictEqual(p.best, 3);
});

test('bestRun / computeStreaks best captures a past ended streak', () => {
  assert.strictEqual(A.bestRun([true,true,true,false,true]), 3);
  assert.strictEqual(A.bestRun([true,null,true,false,true,true]), 2); // neutral bridges but doesn't count: true,null,true = 2 hits
  assert.strictEqual(A.bestRun([]), 0);
});
