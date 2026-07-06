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
  const pts = [{k:'2026-01-01',v:100},{k:'2026-01-06',v:100}]; // 5-day gap, same value
  const t = A.weightTrend(pts, 0.1);
  assert.strictEqual(t.length, 2);
  assert.ok(Math.abs(t[1].ema-100) < 1e-9);
  assert.strictEqual(t[1].raw, 100);
});

test('weightSlope returns negative slope + cur on a decline', () => {
  const pts = Array.from({length:30},(_,i)=>({k:`2026-02-${String(i+1).padStart(2,'0')}`, v:116-0.1*i}));
  const t = A.weightTrend(pts, 0.1);
  const s = A.weightSlope(t, 28);
  assert.ok(s.m < 0);
  assert.ok(s.cur < 116);
  assert.ok(s.n >= 14);
});
