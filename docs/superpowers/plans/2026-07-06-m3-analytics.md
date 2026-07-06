# Analytics (M3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the recomposition visible: an honest ETA-to-90kg from a smoothed weight trend, a phase-tuned fat-loss-rate guardrail, and a strength-retention proxy (e1RM + weekly tonnage) once optional reps are logged — all from data already collected.

**Architecture:** The error-prone math lives in a NEW pure module `analytics.js` (loaded by `index.html`, cached by `sw.js`, dual browser-global / CommonJS export), unit-tested with `node --test`. `index.html` stays a thin layer that feeds `mergedWeights()`/`gar.rows`/`log`/config into those functions and renders. Per-phase thresholds live in `plan.json`.

**Tech Stack:** Vanilla JS (`analytics.js` + inline `index.html`), Node's built-in `node --test` (Node v25), `plan.json` config, existing helpers `mergedWeights`, `spark`, `bars`, `priorities`, `readiness`, `render`.

## Global Constraints

- **`analytics.js` is pure:** no DOM, no globals, no `Date.now()`/`new Date()` inside computation (callers pass dates/indices in; functions return day-offsets and plain numbers). Every function takes its data as arguments and returns plain objects/arrays. Footer: `if (typeof module!=='undefined' && module.exports) module.exports = { … }` so the same file is a browser global AND `require()`-able by tests.
- **Load order:** `index.html` loads `<script src="analytics.js"></script>` BEFORE its inline `<script>` (line 171) so the functions are global. `sw.js` `ASSETS` gains `'./analytics.js'` and `CACHE` bumps `protokol-v8` → `protokol-v9` (offline correctness).
- **Readiness SCORE/zone stays recovery-truth and UNCHANGED.** Rate/ETA may feed `priorities()` and a Silnik Dnia **flag line** only (annotate `f.why`, like M1's nutrition flag). Never fold weight-rate into the readiness number.
- **Config in `plan.json` per phase** — new `analytics` block. Phase 1: `emaAlpha 0.10, etaWindowDays 28, rate:{fastPct 1.3, hardFastPct 1.8, stallPct 0.1, stallWeeks 3}, e1rm:{formula "epley", maxValidReps 12}`. Phase 2: same but `rate.fastPct 1.0, hardFastPct 1.5`. Missing block → hard-coded defaults matching Phase 1. Graceful degradation like the M1 `nutrition` / M2 `body` blocks.
- **e1RM math:** Epley `kg·(1+reps/30)`; only trust reps in 1..`maxValidReps` (default 12); above → excluded from the trend. Backward compatible: old `exHist` entries `{kg,d}` lack reps → e1RM null for them, weight-only path unchanged.
- **Everything degrades gracefully:** sparse/early data → ETA `insufficient`; flat/rising trend → no bogus date; no reps → strength card unchanged with a nudge; M2 absent → guardrail runs on rate+kcal only. Reuse `nz`/`mean` null-skipping.
- **No server-side changes:** no `update_garmin.py`/`fitatu.py`/`send_briefing.py`/workflow/worker edits. `sw.js` changes are limited to the ASSETS/CACHE bump.
- **Polish UI copy**, terse inline-JS style, `data-info` tap-to-explain via the existing `ib()`/`INFO` registry.

## File Structure

- `analytics.js` (new) — pure functions: `ema`/`weightTrend`, `linreg`/`weightSlope`, `etaProject`, `rateBand`, `epley`/`brzycki`/`e1rmSeries`, `weeklyVolume`, `strengthRetention`. CommonJS-exported.
- `tests/analytics.test.js` (new) — `node --test` unit tests with hand-computed expectations.
- `index.html` (modify) — script tag; config reader `analyticsCfg()`; ETA card; rate guardrail wiring into `priorities()` + Silnik Dnia flag; EMA overlay on the weight trend; reps/RPE capture in `exRow`/`pushWeight`; e1RM+tonnage in the "Siła — progresja" card; `INFO` entries.
- `plan.json` (modify) — `analytics` block per phase.
- `sw.js` (modify) — ASSETS + CACHE bump.

---

## Task 1: `analytics.js` scaffold + weight-trend core (EMA + slope), tested; wired into the app

**Files:**
- Create: `analytics.js`
- Create: `tests/analytics.test.js`
- Modify: `index.html` (add `<script src="analytics.js"></script>` immediately before the inline `<script>` at line 171)
- Modify: `sw.js` (`ASSETS` add `'./analytics.js'`; `CACHE` → `'protokol-v9'`)

**Interfaces:**
- Produces (in `analytics.js`):
  - `ema(values, alpha)` → `[Number]` — causal EMA; `ema[0]=values[0]`, `ema[i]=ema[i-1]+alpha*(values[i]-ema[i-1])`. Ignores null entries by carrying the previous ema forward.
  - `weightTrend(points, alpha)` where `points=[{k:"YYYY-MM-DD", v:Number}]` (ascending) → `[{k, raw, ema}]`. Gap handling: step the EMA once per **elapsed day** between consecutive points (apply the smoothing toward `v` for each day; intermediate days carry the interpolated ema) — implement as: for each real point, advance `gapDays` steps of `ema += alpha*(v-ema)` (so a 5-day gap moves the trend ~5 steps toward the reading). Only emit an entry at each real point `k`.
  - `linreg(ys)` → `{m, b, seM, n, r2}` — OLS of `ys` against index `0..n-1`; `m` slope per index step, `seM` standard error of the slope, `r2` coefficient of determination. `n<2` → `{m:null,...,n}`.
  - `weightSlope(trend, windowDays)` → `linreg` of the last `windowDays` `ema` values (one per emitted point). Returns the `linreg` object plus `cur` (last ema).

- [ ] **Step 1: Write the failing tests**

Create `tests/analytics.test.js`:
```javascript
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/analytics.test.js`
Expected: FAIL — `Cannot find module '../analytics.js'`.

- [ ] **Step 3: Implement `analytics.js`**

Create `analytics.js`:
```javascript
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

if (typeof module!=='undefined' && module.exports) module.exports = { ema, weightTrend, linreg, weightSlope };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/analytics.test.js`
Expected: PASS (6 tests).

- [ ] **Step 5: Wire `analytics.js` into index.html + sw.js**

In `index.html`, immediately before the inline `<script>` at line 171, add:
```html
<script src="analytics.js"></script>
```
In `sw.js`, add `'./analytics.js',` to the `ASSETS` array (next to `'./plan.json',`) and change `const CACHE = 'protokol-v8';` to `const CACHE = 'protokol-v9';`.

- [ ] **Step 6: Static verification**

Run:
```bash
node --test tests/analytics.test.js
python3 -c "s=open('index.html').read(); assert 'src=\"analytics.js\"' in s; assert s.count('<script')==s.count('</script>'); print('ok: analytics.js loaded, tags balanced')"
python3 -c "s=open('sw.js').read(); assert './analytics.js' in s and 'protokol-v9' in s; print('ok: sw.js caches analytics.js @ v9')"
```
Expected: tests pass, both `ok`.

- [ ] **Step 7: Commit**
```bash
git add analytics.js tests/analytics.test.js index.html sw.js
git commit -m "feat(m3): add tested analytics.js with EMA weight-trend + slope; wire into app + sw cache"
```

---

## Task 2: ETA-to-90kg — `etaProject()` + `analyticsCfg()` + "Prognoza 90 kg" card + EMA overlay

**Files:**
- Modify: `analytics.js` (add `etaProject`)
- Modify: `tests/analytics.test.js` (add ETA cases)
- Modify: `plan.json` (add `analytics` block to both phases)
- Modify: `index.html` — `DEFAULT_PLAN` analytics block; `analyticsCfg()` helper (after `bodyTargets()`); `etaCard()` (near `acwrCard()` ~line 653) + render it in the Today view (near `${acwrCard()}` ~line 950); EMA overlay on the Progress "Waga" trend; `INFO` entry `eta`.

**Interfaces:**
- Consumes: `weightTrend`, `weightSlope` (Task 1), `mergedWeights()` (index.html:429 → `[{k,v}]`), `activePhase()`, goal target 90.
- Produces:
  - `etaProject(trend, slope, target, opts)` → `{status:"ok"|"flat"|"insufficient", daysExpected, daysEarliest, daysLatest, weeklyRateKg, weeklyRatePct, cur, target, m, seM, n, r2}`. `days*` are **day-offsets from the last trend point** (Number|null) — the render layer converts to dates, keeping the function pure/testable. Guards: `n<nMin`(14)→`insufficient`; `m>=0` or `m+k*seM>=0`→`flat`.
  - `analyticsCfg()` (index.html) → the active phase's `analytics` block merged over hard-coded defaults.

- [ ] **Step 1: Write failing tests for `etaProject`**

Add to `tests/analytics.test.js`:
```javascript
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
```

- [ ] **Step 2: Run to verify fail**

Run: `node --test tests/analytics.test.js`
Expected: the 4 new tests FAIL (`etaProject` undefined).

- [ ] **Step 3: Implement `etaProject`**

Add to `analytics.js` (before the `module.exports` line, and add `etaProject` to the exports list):
```javascript
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
```
Run: `node --test tests/analytics.test.js` → all pass.

- [ ] **Step 4: Add `analytics` block to plan.json + DEFAULT_PLAN**

In `plan.json`, add after each phase's `body` block — Phase 1:
```json
      "analytics": { "emaAlpha": 0.10, "etaWindowDays": 28, "rate": { "fastPct": 1.3, "hardFastPct": 1.8, "stallPct": 0.1, "stallWeeks": 3 }, "e1rm": { "formula": "epley", "maxValidReps": 12 } },
```
Phase 2 (tighter rate):
```json
      "analytics": { "emaAlpha": 0.10, "etaWindowDays": 28, "rate": { "fastPct": 1.0, "hardFastPct": 1.5, "stallPct": 0.1, "stallWeeks": 3 }, "e1rm": { "formula": "epley", "maxValidReps": 12 } },
```
In `index.html` `DEFAULT_PLAN`, add after the phase's `body:{…}` line:
```javascript
    analytics:{emaAlpha:0.10,etaWindowDays:28,rate:{fastPct:1.3,hardFastPct:1.8,stallPct:0.1,stallWeeks:3},e1rm:{formula:"epley",maxValidReps:12}},
```

- [ ] **Step 5: Add `analyticsCfg()` helper**

In `index.html`, after `bodyTargets()`, add (merges phase block over defaults):
```javascript
function analyticsCfg(){
  const D={emaAlpha:0.10,etaWindowDays:28,rate:{fastPct:1.3,hardFastPct:1.8,stallPct:0.1,stallWeeks:3},e1rm:{formula:"epley",maxValidReps:12}};
  const a=(activePhase()||{}).analytics||{};
  return {...D, ...a, rate:{...D.rate, ...(a.rate||{})}, e1rm:{...D.e1rm, ...(a.e1rm||{})}};
}
```

- [ ] **Step 6: Add `etaCard()` + render + EMA overlay + INFO**

In `index.html`, near `acwrCard()`, add `etaCard()`. It builds the trend/slope, projects, and formats dates from the day-offsets:
```javascript
function etaCard(){
  const cfg=analyticsCfg();
  const t=weightTrend(mergedWeights(), cfg.emaAlpha);
  if(t.length<2) return "";
  const s=weightSlope(t, cfg.etaWindowDays);
  const eta=etaProject(t, s, (PLANDATA&&PLANDATA.goal&&PLANDATA.goal.target)||90, {nMin:14,k:1});
  const fmtD=(off)=> off==null?null:new Date(Date.parse(t[t.length-1].k)+off*86400000).toLocaleDateString("pl-PL",{day:"numeric",month:"short",year:"numeric"});
  let big, sub;
  if(eta.status==="ok"){
    big=fmtD(eta.daysExpected);
    const e=fmtD(eta.daysEarliest), l=fmtD(eta.daysLatest);
    sub=`między ${e} a ${l||"—"} · ${eta.weeklyRateKg.toFixed(2)} kg/tydz. (${eta.weeklyRatePct.toFixed(1)}%)`;
  } else if(eta.status==="flat"){ big="trend płaski"; sub="brak wiarygodnej prognozy — waga stabilna."; }
  else { big="—"; sub="Za mało danych na prognozę (zbieram trend)."; }
  return `<div class="card" data-info="eta">
    <p class="label">Prognoza 90 kg${ib('eta')}</p>
    <div class="mv mono" style="font-size:22px;margin-top:6px">${big}</div>
    <div class="sub" style="margin-top:4px">${sub}</div>
    <div class="sub" style="margin-top:2px;color:var(--mut)">trend: ${r1(eta.cur)} kg</div>
  </div>`;
}
```
Render it in the Today view near `${acwrCard()}` (add `${etaCard()}` just before it). Add the `INFO` entry:
```javascript
 eta:{t:"Prognoza 90 kg",h:`<p>Data wyliczona z <b>wygładzonego trendu</b> wagi (EMA), nie z pojedynczych ważeń. Pokazujemy zakres „między … a …", bo tempo się waha.</p><p>Gdy trend jest płaski, nie zmyślamy daty — mówimy wprost, że prognoza jest niepewna.</p>`},
```
EMA overlay on the Progress "Waga" trend: in `progressView`, where the Waga `trend("Waga", mw.slice(-60), …)` renders, add beneath it a faint EMA line, e.g. `${spark(weightTrend(mergedWeights(),analyticsCfg().emaAlpha).slice(-60).map(p=>p.ema),"#fbbf24")}` labelled "Waga — trend (EMA)". Keep the raw trend as-is.

- [ ] **Step 7: Static verification**

Run:
```bash
node --test tests/analytics.test.js
python3 -c "import json; d=json.load(open('plan.json')); assert all('analytics' in p for p in d['phases']); print('plan.json analytics ok:', [p['analytics']['rate']['fastPct'] for p in d['phases']])"
python3 -c "s=open('index.html').read(); assert 'function etaCard(' in s and 'function analyticsCfg(' in s; assert '\${etaCard()}' in s; assert 'eta:{' in s; assert s.count('<script')==s.count('</script>'); print('ok: etaCard+cfg+render+INFO')"
```
Expected: tests pass, both `ok`.

- [ ] **Step 8: Manual browser check**

Load real data. Expected: a "Prognoza 90 kg" card in the Today view showing an expected date + "między … a …" range + weekly kg/% (or "trend płaski"/"za mało danych" honestly). Progress tab shows the EMA trend line under raw weight. Tapping the card opens the `eta` explain sheet.

- [ ] **Step 9: Commit**
```bash
git add analytics.js tests/analytics.test.js plan.json index.html
git commit -m "feat(m3): ETA-to-90kg projection card + EMA overlay + per-phase analytics config"
```

---

## Task 3: Fat-loss-rate guardrail — `rateBand()` + priorities + Silnik Dnia flag

**Files:**
- Modify: `analytics.js` (add `rateBand`) + `tests/analytics.test.js`
- Modify: `index.html` — `priorities(rows)` (add `rate` candidates + upgrade the static `key:"weight"` note); Silnik Dnia flag line (near the M1 nutrition flag ~line 871); `INFO` entry `rate`.

**Interfaces:**
- Consumes: `etaProject` output (`weeklyRatePct`, `m`), `analyticsCfg().rate`, last-3-day kcal vs `kcalFloor` (already computed in `priorities`).
- Produces: `rateBand(weeklyRatePct, m, opts)` → `{band:"ok"|"fast"|"hardFast"|"stall", pct}` where `opts={fastPct,hardFastPct,stallPct}`. `m>=0`→`stall` (not losing). Losing: `|pct|>hardFastPct`→hardFast; `>fastPct`→fast; `<stallPct`→stall; else ok.

- [ ] **Step 1: Write failing tests**

Add to `tests/analytics.test.js`:
```javascript
test('rateBand classifies loss speed', () => {
  const o={fastPct:1.3,hardFastPct:1.8,stallPct:0.1};
  assert.strictEqual(A.rateBand(-0.75,-0.01,o).band, 'ok');
  assert.strictEqual(A.rateBand(-1.5,-0.02,o).band, 'fast');
  assert.strictEqual(A.rateBand(-2.0,-0.03,o).band, 'hardFast');
  assert.strictEqual(A.rateBand(-0.05,-0.001,o).band, 'stall');
  assert.strictEqual(A.rateBand(0.3,0.004,o).band, 'stall'); // gaining → stall (not losing)
});
```

- [ ] **Step 2: Run to verify fail** — `node --test tests/analytics.test.js` → new test fails.

- [ ] **Step 3: Implement `rateBand`**

Add to `analytics.js` (+ export):
```javascript
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
```
Run tests → pass.

- [ ] **Step 4: Wire into `priorities()`**

In `priorities(rows)`, before `C.sort(...)`, add (reuse the EMA/ETA already computable; compute kcal-under-floor like the M1 deficit rule):
```javascript
  const _acfg=analyticsCfg();
  const _t=weightTrend(mergedWeights(), _acfg.emaAlpha);
  if(_t.length>=14){
    const _s=weightSlope(_t, _acfg.etaWindowDays);
    const _eta=etaProject(_t,_s,(PLANDATA&&PLANDATA.goal&&PLANDATA.goal.target)||90,{nMin:14,k:1});
    const rb=rateBand(_eta.weeklyRatePct, _s.m, _acfg.rate);
    const _ftg=fuelTargets();
    const kcal3=rows.map(r=>r.kcal_spozyte).filter(x=>x!=null&&!isNaN(x)).slice(-3);
    const underFloor=_ftg&&kcal3.length===3&&kcal3.every(v=>v<_ftg.kcalFloor);
    if(rb.band==="hardFast")
      C.push({key:"rate",icon:"🚨",title:"Hamuj tempo — chronisz mięśnie",note:`Spadek ${rb.pct.toFixed(1)}%/tydz.${underFloor?" i kalorie pod podłogą":""} — zbyt szybko, ryzyko utraty mięśni.`,weight:8});
    else if(rb.band==="fast")
      C.push({key:"rate",icon:"⚠️",title:"Za szybkie tempo",note:`Spadek ${rb.pct.toFixed(1)}%/tydz. — trochę zwolnij, chroń mięśnie.`,weight:6.5});
    else if(rb.band==="stall")
      C.push({key:"rate",icon:"➖",title:"Waga stoi",note:"Trend płaski — dołóż deficytu lub kroków, jeśli chcesz ruszyć.",weight:5.5});
  }
```
Also upgrade the existing static `{key:"weight",…}` candidate's `note` to include the live rate when available (leave it as a low-weight fallback; the engine's `seen`/dedup already lets `rate` outrank it).

- [ ] **Step 5: Add the Silnik Dnia flag line**

Near the M1 nutrition flag (`f.why = … paliwo …`, ~line 871), add a rate flag (annotate-only; readiness score untouched):
```javascript
  try{
    const _ra=analyticsCfg(); const _tt=weightTrend(mergedWeights(),_ra.emaAlpha);
    if(_tt.length>=14){ const _ss=weightSlope(_tt,_ra.etaWindowDays);
      const _ee=etaProject(_tt,_ss,90,{nMin:14,k:1}); const _rb=rateBand(_ee.weeklyRatePct,_ss.m,_ra.rate);
      if(_rb.band==="fast"||_rb.band==="hardFast") f.why=(f.why?f.why+" · ":"")+`tempo: ${_ee.weeklyRatePct.toFixed(1)}%/tydz. — za szybko`;
      else if(_rb.band==="stall") f.why=(f.why?f.why+" · ":"")+`tempo: waga stoi`;
    }
  }catch(e){}
```
Add `INFO` entry `rate`:
```javascript
 rate:{t:"Tempo redukcji",h:`<p>Ile procent masy ciała tracisz na tydzień, licząc z trendu (EMA). Zbyt szybko (dużo powyżej 1%/tydz. przy Twojej wadze) grozi utratą mięśni; zero tygodniami = zastój.</p><p>To sygnał <b>postępu</b>, nie regeneracji — nie zmienia wyniku „Gotowości".</p>`},
```

- [ ] **Step 6: Confirm readiness untouched** — re-read the diff; no line inside `readiness(rows)` changed. State explicitly in the report.

- [ ] **Step 7: Static verification**

Run:
```bash
node --test tests/analytics.test.js
python3 -c "s=open('index.html').read(); assert 'Hamuj tempo' in s and 'Za szybkie tempo' in s and 'Waga stoi' in s; assert 'key:\"rate\"' in s; assert 'rate:{' in s; assert s.count('<script')==s.count('</script>'); print('ok: guardrail wired')"
```
Expected: tests pass, `ok`.

- [ ] **Step 8: Manual browser check** — with real data: the priorities list surfaces a `rate` candidate matching the observed tempo; the Silnik Dnia reason line appends a tempo note when fast/stall; readiness ring score unchanged.

- [ ] **Step 9: Commit**
```bash
git add analytics.js tests/analytics.test.js index.html
git commit -m "feat(m3): fat-loss-rate guardrail into priorities + Silnik Dnia flag"
```

---

## Task 4: Optional reps/RPE logging (exHist extension + exRow input)

**Files:**
- Modify: `index.html` — `pushWeight` (index.html:366, accept optional reps/rpe; ring buffer 12→24); `exRow` (index.html:385, add optional reps input); the `input[data-ex]` save handler (index.html:1001-1006, read the reps field).

**Interfaces:**
- Produces: `pushWeight(id, kg, tk, reps, rpe)` — stores `{kg, d, reps?, rpe?}`; reps/rpe omitted when falsy. Backward compatible with existing `{kg,d}` entries.

- [ ] **Step 1: Extend `pushWeight`**

Change `pushWeight` (index.html:366) to:
```javascript
function pushWeight(id,kg,tk,reps,rpe){
  if(!log.exHist) log.exHist={};
  const h=log.exHist[id]||(log.exHist[id]=[]);
  const entry={kg,d:tk};
  if(reps!=null&&!isNaN(reps)&&reps>0) entry.reps=reps;
  if(rpe!=null&&!isNaN(rpe)&&rpe>0) entry.rpe=rpe;
  const last=h[h.length-1];
  if(last&&last.d===tk){ last.kg=kg; if(entry.reps!=null)last.reps=entry.reps; else delete last.reps; if(entry.rpe!=null)last.rpe=entry.rpe; else delete last.rpe; }
  else h.push(entry);
  if(h.length>24) h.splice(0,h.length-24);
  save("fit-log-v1",log);
}
```

- [ ] **Step 2: Add the optional reps input to `exRow`**

In `exRow` (index.html:385), add a small reps input next to the weight input inside `.exw`:
```javascript
      <input type="text" inputmode="decimal" data-ex="${ex.id}" placeholder="${phv||"kg"}" />
      <input type="text" inputmode="numeric" data-reps="${ex.id}" placeholder="powt." style="width:56px" value="${last&&last.reps!=null?last.reps:""}" />
```
(Keep the existing `.last` line; show reps in history if present — optional: append `×${e.reps}` in the `histTxt` map when `e.reps` exists.)

- [ ] **Step 3: Read reps in the save handler**

In the `input[data-ex]` handler (index.html:1001-1006), read the sibling reps field:
```javascript
    inp.onchange=()=>{ const id=inp.getAttribute("data-ex");
      const v=parseFloat((inp.value||"").replace(",",".")); if(!v||v<=0||v>500) return;
      const rInp=document.querySelector(`input[data-reps="${id}"]`);
      const reps=rInp?parseInt((rInp.value||"").replace(",",""),10):null;
      pushWeight(id, Math.round(v*10)/10, tk, (reps>0?reps:null)); render(); };
```
(Reps is optional: empty → `null` → weight-only behavior, exactly as today.)

- [ ] **Step 4: Static verification**

Run:
```bash
python3 -c "s=open('index.html').read(); assert 'function pushWeight(id,kg,tk,reps,rpe)' in s; assert 'data-reps=' in s; assert 'h.length>24' in s; assert s.count('<script')==s.count('</script>'); print('ok: reps capture + buffer 24')"
```
Expected: `ok`.

- [ ] **Step 5: Manual browser check** — open Dziś on a strength day: each exercise now has a weight + a small "powt." field. Enter weight only → saves as before (no reps). Enter weight + reps → both persist; reload keeps them; the "ost." line still shows weight. Old logged entries still render (no reps) without error.

- [ ] **Step 6: Commit**
```bash
git add index.html
git commit -m "feat(m3): optional reps/RPE capture in strength log (backward compatible, buffer 24)"
```

---

## Task 5: e1RM + weekly volume — `strengthRetention()` + "Siła — progresja" card + priorities

**Files:**
- Modify: `analytics.js` (add `epley`, `brzycki`, `e1rmSeries`, `weeklyVolume`, `strengthRetention`) + `tests/analytics.test.js`
- Modify: `index.html` — extend the "Siła — progresja" card (progressView ~lines 799-830) with e1RM sparkline + tonnage bars + retention headline; add a `strength` retention rule to `priorities()`; `INFO` entries `e1rm`, `tonnage`.

**Interfaces:**
- Produces (analytics.js):
  - `epley(kg, reps)` → `kg*(1+reps/30)`; `brzycki(kg,reps)` → `kg*36/(37-reps)`.
  - `e1rmSeries(hist, maxReps)` → `[{d, e1rm}]` for entries with valid reps in 1..maxReps (Epley); entries without reps or reps>maxReps excluded.
  - `weeklyVolume(hist, schemeReps)` → `[{week, vol}]` where `vol=Σ kg*reps` (actual reps, else `schemeReps` fallback), grouped by ISO week (Monday key).
  - `strengthRetention(exHist, exMeta, cfg)` → `{perExercise:[{id,name,e1rmSeries,e1rmDelta,volSeries,volDelta}], overall:{e1rmTrend, volTrend, dataQuality}}`.

- [ ] **Step 1: Write failing tests**

Add to `tests/analytics.test.js`:
```javascript
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
```

- [ ] **Step 2: Run to verify fail** — new tests fail.

- [ ] **Step 3: Implement the strength functions**

Add to `analytics.js` (+ exports). Keep ISO-week keying pure (derive Monday from the date string via `Date.parse`, no `Date.now`):
```javascript
function epley(kg,reps){ return kg*(1+reps/30); }
function brzycki(kg,reps){ return kg*36/(37-reps); }
function e1rmSeries(hist, maxReps){
  return (hist||[]).filter(e=>e&&e.reps>0&&e.reps<=maxReps&&e.kg>0)
    .map(e=>({d:e.d, e1rm:Math.round(epley(e.kg,e.reps)*10)/10}));
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
  return {perExercise:per, overall:{e1rmTrend:overallE, volTrend:null, dataQuality:anyReps?"reps":"weight-only"}};
}
```
Run tests → pass.

- [ ] **Step 4: Extend the "Siła — progresja" card**

In `progressView` (index.html ~799-830), compute `strengthRetention(log.exHist, exMeta, analyticsCfg().e1rm)` where `exMeta` maps each exId → `{name, schemeReps}` (parse the phase's exercise `scheme` "3×10" → 30 for schemeReps; the exercise names come from the plan's `days[*].exercises`). When `dataQuality==="reps"`, add per-exercise an **e1RM sparkline** (`spark(p.e1rmSeries.map(x=>x.e1rm),color)`) and a **weekly tonnage** bar chart (`bars(p.volSeries.map(v=>({label:v.week.slice(5),v:v.vol})),color)`), plus an overall headline: e1rmTrend `down`→"⚠️ siła spada", `up`/`flat`→"✅ utrzymujesz siłę". When `weight-only`, keep the existing card and add a one-line nudge: `"Zapisuj powtórzenia przy ciężarze, by zobaczyć e1RM."`. Add `INFO` entries:
```javascript
 e1rm:{t:"Szacowany 1RM (e1RM)",h:`<p>Przewidywany ciężar maksymalny z Twojego ciężaru roboczego i liczby powtórzeń (wzór Epleya). Rośnie/utrzymuje się = <b>mięśnie zostają</b> w redukcji.</p><p>Wpisuj powtórzenia w zakładce „Dziś", by go liczyć.</p>`},
 tonnage:{t:"Objętość tygodniowa (tonaż)",h:`<p>Suma ciężar × powtórzenia w tygodniu — miara utrzymanego bodźca treningowego. Stabilny/rosnący tonaż chroni mięśnie podczas cięcia.</p>`},
```

- [ ] **Step 5: Add the strength-retention priority rule**

In `priorities(rows)`, before `C.sort`, compute retention and (only when a cut is active, i.e. the rate trend is downward) fire a rule when e1RM trend is down; it reuses `key:"strength"` so it *replaces and outranks* the static weight-4 "Nie odpuszczaj siły" tip:
```javascript
  try{
    const _ret=strengthRetention(log.exHist, _exMetaForPriorities(), analyticsCfg().e1rm);
    if(_ret.overall.dataQuality==="reps" && _ret.overall.e1rmTrend==="down")
      C.push({key:"strength",icon:"💪",title:"Siła spada w redukcji",note:"e1RM w dół — utrzymaj ciężary i dołóż białka, by chronić mięśnie.",weight:7.5});
  }catch(e){}
```
(`_exMetaForPriorities()` = a tiny helper returning `{id:{name,schemeReps}}` from the active phase's exercises; if factoring is awkward, inline the map. The existing static `key:"strength"` tip at ~line 698 remains as the flat/up fallback — dedup by `key` keeps only the higher-weight one.)

- [ ] **Step 6: Static verification**

Run:
```bash
node --test tests/analytics.test.js
python3 -c "s=open('index.html').read(); assert 'strengthRetention(' in s; assert 'e1rm:{' in s and 'tonnage:{' in s; assert 'Siła spada w redukcji' in s; assert s.count('<script')==s.count('</script>'); print('ok: e1rm card + retention priority')"
```
Expected: tests pass, `ok`.

- [ ] **Step 7: Manual browser check** — log a couple of strength sessions WITH reps for one exercise across different dates; open Postępy → "Siła — progresja" shows an e1RM sparkline + weekly tonnage bars + a retention headline for that exercise; exercises without reps stay weight-only with the nudge. With declining e1RM during a losing weight trend, the "Siła spada w redukcji" priority appears.

- [ ] **Step 8: Commit**
```bash
git add analytics.js tests/analytics.test.js index.html
git commit -m "feat(m3): e1RM + weekly tonnage retention analytic, card, and priority"
```

---

## Self-Review

**Spec coverage:**
- Tested `analytics.js` extraction + `node --test` → Task 1 (harness + EMA/slope), reused by Tasks 2/3/5. ✓
- EMA trend-weight + slope with seM → Task 1. ✓
- ETA-to-90kg with earliest–expected–latest + flat-suppression → Task 2 (`etaProject`) + card. ✓
- Per-phase `analytics` config (phase-tuned rate) + graceful defaults → Task 2 (`analyticsCfg`, plan.json, DEFAULT_PLAN). ✓
- Fat-loss-rate guardrail → priorities + Silnik Dnia flag → Task 3 (`rateBand`). Readiness score untouched. ✓
- Optional reps/RPE logging (backward compatible, buffer 24) → Task 4. ✓
- e1RM (Epley, maxValidReps) + weekly tonnage + retention headline + "siła spada" priority → Task 5. ✓
- EMA overlay on weight chart → Task 2 Step 6. ✓
- INFO explain entries eta/rate/e1rm/tonnage → Tasks 2/3/5. ✓
- sw.js cache correctness → Task 1. ✓
- M2 fat-vs-muscle corroboration is a documented dependency; guardrail runs on rate+kcal now and lights up when M2 waist/body_fat present (nullable) — noted in spec §Analytic 2; not a blocking task here.

**Placeholder scan:** No TBD/TODO. All formulas and thresholds are concrete. `_exMetaForPriorities()`/`exMeta` construction is described (parse scheme "3×10"→30, names from plan days) — the implementer builds the small map; if awkward, inline it (explicitly permitted).

**Type consistency:** `weightTrend`→`[{k,raw,ema}]` consumed by `weightSlope` (reads `.ema`) and the EMA overlay (`.ema`); `weightSlope`→`{m,b,seM,n,r2,cur}` consumed by `etaProject`; `etaProject`→`{status,days*,weeklyRate*,m,...}` consumed by the ETA card and `rateBand`(`weeklyRatePct`,`m`); `e1rmSeries`→`[{d,e1rm}]` and `weeklyVolume`→`[{week,vol}]` consumed by `strengthRetention` and the Siła card. Names/shapes consistent across `analytics.js`, tests, and `index.html`. `pushWeight(id,kg,tk,reps,rpe)` signature matches its one call site (Task 4 Step 3).
