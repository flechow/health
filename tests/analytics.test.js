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

test('etaProject flat series → status flat, no date', () => {
  const pts = Array.from({length:30},(_,i)=>({k:`2026-04-${String(i+1).padStart(2,'0')}`, v:100}));
  const t=A.weightTrend(pts,0.1); const s=A.weightSlope(t,28);
  assert.strictEqual(A.etaProject(t,s,90,{nMin:14,k:1}).status, 'flat');
});

test('etaProject rising series is not ok', () => {
  const pts = Array.from({length:30},(_,i)=>({k:`2026-05-${String(i+1).padStart(2,'0')}`, v:100+0.05*i}));
  const t=A.weightTrend(pts,0.1); const s=A.weightSlope(t,28);
  assert.notStrictEqual(A.etaProject(t,s,90,{nMin:14,k:1}).status, 'ok');
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
