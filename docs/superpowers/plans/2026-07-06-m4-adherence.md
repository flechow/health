# Adherence (M4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a solo user consistent over an 18-week+ protocol via forgiving (weekly-tolerance) habit streaks, a trend-first weekly check-in card, and Sunday/Saturday push reminders — all derived from data M1–M3 already produce.

**Architecture:** The streak + check-in math is added to the pure, unit-tested `analytics.js` module (M3) and `node --test`. `index.html` renders a "Serie" card + weekly check-in card. `send_briefing.py` gains a day-of-week branch (Sunday summary, Saturday measurement reminder) with `pytest` coverage. Per-phase habit goals live in `plan.json`. No new encrypted data; the only new persistence is a best-streak high-water mark in localStorage.

**Tech Stack:** Vanilla JS (`analytics.js` pure + inline `index.html`), `node --test`, Python (`send_briefing.py`), `pytest`, `plan.json` config.

## Global Constraints

- **Forgiving streaks, not consecutive-day chains.** A habit's streak = count of consecutive **good weeks** up to the most recent *completed* week. A week is "good" if `hits >= ceil(eligibleDays * weekThreshold)` (default `weekThreshold = 0.8`). A week with **zero eligible days is NEUTRAL** — it bridges (neither extends nor breaks) the streak. The **current in-progress week never breaks** a streak (shown as progress only).
- **Four habits, one uniform weekly rule:** 🥩 protein (`bialko >= proteinG`), 🚶 steps (`kroki >= stepGoal`), 😴 sleep (`sen >= sleepGoalH`), 💪 training (`log.days[date].trained === true`, eligible = scheduled non-rest days that week). Training uses the SAME 80% threshold as the others (no separate tolerance rule).
- **Streaks/check-in are DERIVED and pure** — computed from decrypted rows + `log` on every render; no persisted counters. The ONLY new persistent state: `fit-adh-v1 = { bestStreak: {protein,steps,sleep,training} }` (monotonic high-water mark, `max(stored, computed)`).
- **Pure functions in `analytics.js`** take plain data args (rows, sets, config) — no DOM/globals/`Date.now()` in math (deterministic date-string parsing OK). Added to `module.exports`; unit-tested.
- **Per-phase `habits` block in `plan.json`:** `{ "stepGoal": 8000, "sleepGoalH": 7.0, "weekThreshold": 0.8 }`. Missing block → hard-coded defaults (8000 / 7.0 / 0.8). Protein target reuses `nutrition.proteinG` (M1).
- **Push extends `send_briefing.py` only** — no new channel/cron. Every new branch inside the existing top-level try/except that forces `exit 0`; a `weekly_summary` error falls back to the normal readiness briefing. Sunday (`isoweekday()==7`) → weekly summary; Saturday (`==6`) → append a **waist-measurement** reminder (photos are out of scope per M2). Sessions-done in the push uses an **activity proxy** (days with `min_intensywne >= ACTIVE_MIN`, labelled approximate) since `log.days` is browser-only.
- **Readiness score untouched.** M4 adds no readiness input.
- **Graceful degradation:** M1 absent → protein streak/line "—"; M2 absent → waist/body-fat check-in lines omitted; sparse (<1 complete week) → "zbieramy dane" not a "0-week streak"; no NaN/undefined leaks. Reuse `nz`/`mean`/`monday`/`key`.
- Polish UI copy; forgiving tone (a broken streak shows a fresh-start message, never scolding).

## File Structure

- `analytics.js` (modify) — `weeklyGood`, `streakCount`, `computeStreaks`, `weeklyCheckin` (+ exports).
- `tests/analytics.test.js` (modify) — streak + check-in unit tests.
- `plan.json` (modify) — `habits` block per phase.
- `index.html` (modify) — `DEFAULT_PLAN` habits; `habitCfg()`; `trainingWeekdays()`/`trainedDates()` adapters; `adhLog` (`fit-adh-v1`); `serieCard()`; `checkinCard()`; render both; `INFO` `serie`/`checkin`.
- `send_briefing.py` (modify) — `weekly_summary(rows)`, `activity_sessions(rows, week)`, day-of-week branch in `build_message`, `MEASURE_DOW`/`CHECKIN_DOW`/`ACTIVE_MIN` constants.
- `tests/test_briefing.py` (new) — Python unit tests for `weekly_summary` + the day-branch.

---

## Task 1: Streak engine in analytics.js (pure, tested) + plan.json habits + habitCfg

**Files:**
- Modify: `analytics.js` (add `weeklyGood`, `streakCount`, `computeStreaks` + exports)
- Modify: `tests/analytics.test.js`
- Modify: `plan.json` (add `habits` to both phases)
- Modify: `index.html` — `DEFAULT_PLAN` habits block; `habitCfg()` (after `analyticsCfg()`); `adhLog = load("fit-adh-v1",{bestStreak:{}})` (near the other loads)

**Interfaces:**
- Produces (analytics.js):
  - `weeklyGood(hits, eligible, threshold)` → `true` (good) | `false` (missed) | `null` (neutral: `eligible===0`).
  - `streakCount(weekFlags)` → count of trailing consecutive `true`, bridging `null`, stopping at `false`. (`weekFlags` ascending by week; the caller excludes the in-progress week.)
  - `computeStreaks(rows, opts)` → `[{key,icon,label,current,best,thisWeek}]` for the 4 habits. `opts = {proteinG, stepGoal, sleepGoalH, weekThreshold, trainedDates:Set<string>, trainingWeekdays:Set<number>, bestStored:{}, todayKey:string}`. Groups rows by ISO week (Monday key via a pure helper), computes per-habit weekly hits/eligible, flags via `weeklyGood`, streak via `streakCount` over COMPLETED weeks (week whose Monday < this week's Monday from `todayKey`), `thisWeek` = current-week progress, `best = max(bestStored[key]||0, current)`.

- [ ] **Step 1: Write failing tests**

Add to `tests/analytics.test.js`:
```javascript
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
```

- [ ] **Step 2: Run to verify fail** — `node --test tests/analytics.test.js` → new tests fail.

- [ ] **Step 3: Implement in analytics.js** (add before `module.exports`, add names to exports):
```javascript
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
```
Run tests → pass.

- [ ] **Step 4: plan.json habits + DEFAULT_PLAN + habitCfg + adhLog**

`plan.json` — add after each phase's `analytics` block:
```json
      "habits": { "stepGoal": 8000, "sleepGoalH": 7.0, "weekThreshold": 0.8 },
```
`index.html` `DEFAULT_PLAN` — after the phase `analytics:{…}` line:
```javascript
    habits:{stepGoal:8000,sleepGoalH:7.0,weekThreshold:0.8},
```
`index.html` — after `analyticsCfg()`:
```javascript
function habitCfg(){
  const D={stepGoal:8000,sleepGoalH:7.0,weekThreshold:0.8};
  return {...D, ...((activePhase()||{}).habits||{})};
}
```
`index.html` — near the other `load(...)` calls (after `bodyLog`):
```javascript
const adhLog=load("fit-adh-v1",{bestStreak:{}});
```

- [ ] **Step 5: Static verification**
```bash
node --test tests/analytics.test.js
python3 -c "import json; d=json.load(open('plan.json')); assert all('habits' in p for p in d['phases']); print('plan.json habits ok')"
python3 -c "s=open('index.html').read(); assert 'function habitCfg(' in s and 'load(\"fit-adh-v1\"' in s and 'habits:{stepGoal:8000' in s; assert s.count('<script')==s.count('</script>'); print('ok')"
```
Expected: tests pass, both `ok`.

- [ ] **Step 6: Commit**
```bash
git add analytics.js tests/analytics.test.js plan.json index.html
git commit -m "feat(m4): forgiving weekly-tolerance streak engine (tested) + habit config"
```

---

## Task 2: Weekly check-in aggregation in analytics.js (pure, tested)

**Files:**
- Modify: `analytics.js` (add `weeklyCheckin` + export) + `tests/analytics.test.js`

**Interfaces:**
- Produces: `weeklyCheckin(rows, opts)` → `{ weekOf, deltas:{waga,talia,bodyFat,bialko,sen,hrv}, sessions:{done,planned}, streakSummary:[{label,current}], winLine }`. Compares the **last complete Mon–Sun week** vs the **prior week** using 7-day means (nulls skipped). `opts = {proteinG, waistByDate:{}, trainedDates:Set, trainingWeekdays:Set, streaks:[…from computeStreaks], todayKey}`. Any delta with insufficient data → `null` (caller omits the line). `winLine` picks the single most positive fact (biggest weight/waist drop, or longest streak, or "wszystkie treningi zaliczone"), else neutral encouragement.

- [ ] **Step 1: Write failing tests**

Add to `tests/analytics.test.js`:
```javascript
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
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `weeklyCheckin`** in analytics.js (+export). Use `_weekKey` from Task 1; compute mean over each week's rows for waga/bialko/sen/hrv; waist from `waistByDate` (keys = dates); `deltas.X = lastMean - priorMean` (null if either missing); sessions.done = count of `trainedDates` in the last complete week, planned = count of week dates whose weekday ∈ `trainingWeekdays`; `streakSummary` = streaks filtered to current>0; `winLine` per the rule above. Keep it pure (no Date.now). Run tests → pass.

- [ ] **Step 4: Verify** — `node --test tests/analytics.test.js` (all pass), `python3 -m pytest -q` (12/12 unaffected).

- [ ] **Step 5: Commit**
```bash
git add analytics.js tests/analytics.test.js
git commit -m "feat(m4): weekly check-in aggregation (pure, tested)"
```

---

## Task 3: "Serie" + weekly check-in cards in index.html

**Files:**
- Modify: `index.html` — `trainedDates()`/`trainingWeekdays()` adapters; `serieCard()`; `checkinCard()`; render both in the Dziś view (Serie after `${prioritiesCard()}` ~line 1014; check-in card at the TOP of Dziś on Sundays); best-streak persistence; `INFO` `serie`/`checkin`.

**Interfaces:**
- Consumes: `computeStreaks`, `weeklyCheckin` (Tasks 1–2), `habitCfg()`, `fuelTargets()`, `activePhase()`, `adhLog`, `mergedWeights`, `bodyLog`, `log.days`, `monday()`/`key()`, `arr`, `save`, `render`.

- [ ] **Step 1: Adapters + best-streak persistence**

Add helpers in index.html:
```javascript
function trainingWeekdays(){
  const days=(activePhase()||{}).days||{};
  const s=new Set();
  // plan uses Pn=1..Nd=0; convert to JS getUTCDay (Sun=0..Sat=6) for computeStreaks
  for(const k in days){ if((days[k]||{}).type && days[k].type!=="rest"){ const pl=parseInt(k,10); s.add(pl===0?0:pl); } }
  return s;
}
function trainedDatesSet(){
  const s=new Set(); for(const d in (log.days||{})){ if((log.days[d]||{}).trained) s.add(d); } return s;
}
function currentStreaks(){
  if(!gar||!gar.rows) return [];
  const hc=habitCfg(), ft=fuelTargets();
  const out=computeStreaks(gar.rows, {proteinG:ft?ft.proteinG:180, stepGoal:hc.stepGoal,
    sleepGoalH:hc.sleepGoalH, weekThreshold:hc.weekThreshold, trainedDates:trainedDatesSet(),
    trainingWeekdays:trainingWeekdays(), bestStored:adhLog.bestStreak||{}, todayKey:key(new Date())});
  // persist high-water mark
  let changed=false; adhLog.bestStreak=adhLog.bestStreak||{};
  for(const s of out){ if((adhLog.bestStreak[s.key]||0) < s.best){ adhLog.bestStreak[s.key]=s.best; changed=true; } }
  if(changed) save("fit-adh-v1", adhLog);
  return out;
}
```
Note: `trainingWeekdays()` must map the plan's Pn=1..Nd=0 to the `getUTCDay` (Sun=0..Sat=6) convention `computeStreaks` uses. In the plan, keys "1".."6" are Mon..Sat, "0" is Sun; JS getUTCDay Mon=1..Sat=6, Sun=0 — same numbers, so a non-rest plan key `k` maps directly to weekday `k`. (Verify with the test in Task 1 which used `new Set([1..6])`.)

- [ ] **Step 2: `serieCard()`** — compact row per habit (icon, label, `current` "N tyg", subtle "rekord M", in-progress bar "hits/elig w tym tygodniu"); forgiving copy when `current===0` ("nowy start · w tym tygodniu h/e"); if no rows / all habits have zero eligible-ever → "zbieramy dane — pierwsze podsumowanie po pełnym tygodniu". Reuse the metric-row styling. `data-info="serie"`.

- [ ] **Step 3: `checkinCard()`** — build `weeklyCheckin(...)` (pass `waistByDate` from `bodyLog.circ` mapped date→waist, `streaks` from `currentStreaks()`); render the **win line first**, then non-null delta lines (Waga always; Talia/Tłuszcz only if non-null; Białko if M1; Treningi done/planned; Sen/HRV with `arr()`), then a one-line streak summary. `data-info="checkin"`. Returns "" if <1 complete week of data.

- [ ] **Step 4: Render** — insert `${serieCard()}` right after `${prioritiesCard()}` (~line 1014). Insert `${checkinCard()}` at the TOP of the Dziś (non-progress) branch when today is Sunday (`new Date().getDay()===0`), else make it reachable lower down (e.g. also after serieCard on non-Sundays). Add `INFO` entries:
```javascript
 serie:{t:"Serie (nawyki)",h:`<p>Liczymy <b>dobre tygodnie</b>, nie dni z rzędu. Tydzień jest „dobry", gdy trafisz nawyk w ≥80% dni, w które się liczy. Jeden słaby dzień nie zrywa serii — dlatego to działa długoterminowo.</p><p>Bieżący tydzień nigdy nie zrywa serii; widzisz go jako postęp.</p>`},
 checkin:{t:"Podsumowanie tygodnia",h:`<p>Trend tego tygodnia vs poprzedni: waga, talia, białko, treningi, sen/HRV. Patrzymy na <b>średnie 7-dniowe</b>, nie pojedyncze dni. Zaczynamy od wygranej tygodnia.</p>`},
```

- [ ] **Step 5: Static verification**
```bash
python3 -c "s=open('index.html').read(); assert 'function serieCard(' in s and 'function checkinCard(' in s and 'function currentStreaks(' in s; assert 'serie:{' in s and 'checkin:{' in s; assert '\${serieCard()}' in s; assert s.count('<script')==s.count('</script>'); print('ok')"
node --test tests/analytics.test.js
```
Expected: `ok`, tests pass.

- [ ] **Step 6: Manual browser check** — load real data: a "Serie" card appears after priorities with per-habit streaks + in-progress bars and forgiving copy; a weekly check-in card renders (top on Sundays) opening with a win line, then deltas (waist/fat only if bodycomp data exists, protein only if nutrition data), then streak summary. Best-streak survives reload. New/sparse data shows "zbieramy dane". Tapping either card opens its explain sheet.

- [ ] **Step 7: Commit**
```bash
git add index.html
git commit -m "feat(m4): Serie streak card + weekly check-in card + best-streak persistence"
```

---

## Task 4: send_briefing.py — weekly summary + Saturday reminder + Python tests

**Files:**
- Modify: `send_briefing.py` — constants `MEASURE_DOW=6`, `CHECKIN_DOW=7`, `ACTIVE_MIN=20`; `activity_sessions(rows, week_start)`; `weekly_summary(rows)`; day-of-week branch in `build_message`.
- Create: `tests/test_briefing.py`

**Interfaces:**
- Produces:
  - `weekly_summary(rows) -> (title, body)` — Polish roll-up of the last complete week: weight Δ (7-day avg vs prior), protein avg vs target (if present), sleep/HRV trend, **activity-proxy** sessions (`~N sesji`), and top streaks computable server-side (protein/steps/sleep — training omitted, no `log.days`). Title `📊 Podsumowanie tygodnia · Protokół`. Never raises (returns a safe fallback body on bad data).
  - `activity_sessions(rows, week_start) -> int` — count of days in that Mon–Sun week with `min_intensywne >= ACTIVE_MIN`.

- [ ] **Step 1: Write failing Python tests**

Create `tests/test_briefing.py`:
```python
import send_briefing as sb

def _week(start, **vals):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"data": (d0+timedelta(days=i)).isoformat(), **vals} for i in range(7)]

def test_weekly_summary_returns_title_body_and_never_raises():
    rows = _week("2026-06-15", waga=99.0, bialko=190, sen=7.5, hrv=60, kroki=9000, min_intensywne=30)
    rows = _week("2026-06-08", waga=100.0, bialko=190, sen=7.5, hrv=58, kroki=9000, min_intensywne=30) + rows
    title, body = sb.weekly_summary(rows)
    assert "Podsumowanie" in title
    assert isinstance(body, str) and len(body) > 0

def test_weekly_summary_never_raises_on_empty():
    title, body = sb.weekly_summary([])
    assert isinstance(title, str) and isinstance(body, str)

def test_activity_sessions_counts_active_days():
    from datetime import date
    rows = _week("2026-06-15", min_intensywne=30)
    # 7 active days that week
    assert sb.activity_sessions(rows, date.fromisoformat("2026-06-15")) == 7
```

- [ ] **Step 2: Run to verify fail** — `python3 -m pytest tests/test_briefing.py -v` → fails (functions missing).

- [ ] **Step 3: Implement in send_briefing.py**

Add constants near the top (after the existing filename constants):
```python
MEASURE_DOW = 6   # sobota — przypomnienie o pomiarach
CHECKIN_DOW = 7   # niedziela — podsumowanie tygodnia
ACTIVE_MIN = 20   # min. intensywne = "sesja" (proxy, bo log treningów jest tylko w przeglądarce)
```
Add helpers (reuse the existing `_avg`), and a Monday-week helper:
```python
def _week_of(dstr):
    from datetime import date, timedelta
    d = date.fromisoformat(dstr)
    return d - timedelta(days=d.weekday())   # Monday

def activity_sessions(rows, week_start):
    from datetime import timedelta
    end = week_start + timedelta(days=6)
    n = 0
    for r in rows:
        try:
            d = date.fromisoformat(r.get("data"))
        except Exception:
            continue
        if week_start <= d <= end:
            mi = r.get("min_intensywne")
            if isinstance(mi, (int, float)) and mi >= ACTIVE_MIN:
                n += 1
    return n

def weekly_summary(rows):
    title = "📊 Podsumowanie tygodnia · Protokół"
    try:
        from datetime import date, timedelta
        if not rows:
            return title, "Zbieram dane — pełne podsumowanie po pierwszym tygodniu."
        this_mon = date.today() - timedelta(days=date.today().weekday()) - timedelta(days=7)  # last complete week
        prev_mon = this_mon - timedelta(days=7)
        def wk(mon):
            end = mon + timedelta(days=6)
            return [r for r in rows if _in(r, mon, end)]
        cur, prev = wk(this_mon), wk(prev_mon)
        parts = []
        dw = _delta(_avg([r.get("waga") for r in cur]), _avg([r.get("waga") for r in prev]))
        if dw is not None:
            parts.append(f"waga {dw:+.1f} kg")
        pavg = _avg([r.get("bialko") for r in cur])
        if pavg is not None:
            parts.append(f"białko śr. {round(pavg)} g")
        sess = activity_sessions(rows, this_mon)
        parts.append(f"~{sess} sesji")
        ds = _delta(_avg([r.get("sen") for r in cur]), _avg([r.get("sen") for r in prev]))
        if ds is not None:
            parts.append(f"sen {ds:+.1f} h")
        body = " · ".join(parts) if parts else "Tydzień zaliczony — otwórz apkę po szczegóły."
        body += " · pełne serie w apce."
        return title, body
    except Exception as e:
        print("weekly_summary blad:", e)
        return title, "Podsumowanie tygodnia — otwórz apkę."
```
Add the small helpers `_in` and `_delta` (guard None), and ensure `from datetime import date` is available at module scope (it already imports `date`). Then branch in `build_message` at the top:
```python
def build_message(rows):
    dow = date.today().isoweekday()   # 1=Pn..7=Nd
    if dow == CHECKIN_DOW:
        try:
            return weekly_summary(rows)
        except Exception:
            pass
    # ...existing readiness+session logic...
    title, tip = <existing>
    if dow == MEASURE_DOW:
        tip += " · ⚖️ dziś pomiary: waga na czczo + talia."
    return title, tip
```

- [ ] **Step 4: Run tests to verify pass** — `python3 -m pytest tests/test_briefing.py -v` (3 pass); then full `python3 -m pytest -q` (15/15 total).

- [ ] **Step 5: Manual verification (optional)** — run `DATA_PASSPHRASE=… python3 send_briefing.py` locally; confirm it prints a message and still exits 0 with no subscriptions. (The Sunday/Saturday branches are covered by the unit tests + the day-of-week logic.)

- [ ] **Step 6: Commit**
```bash
git add send_briefing.py tests/test_briefing.py
git commit -m "feat(m4): weekly-summary + Saturday measurement reminder in send_briefing (tested)"
```

---

## Self-Review

**Spec coverage:**
- Forgiving weekly-tolerance streaks (4 habits, neutral bridging, in-progress never breaks) → Task 1 (`weeklyGood`/`streakCount`/`computeStreaks`, tested). ✓
- Best-streak high-water mark in `fit-adh-v1` → Task 1 (adhLog) + Task 3 (persist on render). ✓
- Weekly check-in (trend deltas, win line, M1/M2 degradation) → Task 2 (`weeklyCheckin`, tested) + Task 3 (card). ✓
- Serie + check-in cards, forgiving copy, explain sheets → Task 3. ✓
- `plan.json` `habits` + graceful defaults → Task 1. ✓
- Push: Sunday summary + Saturday waist-measurement reminder, activity-proxy sessions, fail-safe → Task 4 (tested, never-raises). ✓
- Readiness untouched; no new encrypted data; no new channel → constraints + Task 4 (extends existing job). ✓
- Photos excluded (M2 decision) → reminder says "waga + talia" only. ✓

**Placeholder scan:** Task 2 Step 3 and Task 3 Steps 2–3 describe the card/aggregation structure rather than full literal code (the pure `weeklyCheckin` has a full test + interface contract; the cards are rendering layers following the established `fuelCard`/`sylwetkaCard` pattern). All numeric params (0.8, 8000, 7.0, ACTIVE_MIN 20, MEASURE_DOW 6, CHECKIN_DOW 7) are concrete. No TBD.

**Type consistency:** `computeStreaks`→`[{key,icon,label,current,best,thisWeek:{hits,elig}}]` consumed by `serieCard` and passed as `streaks` into `weeklyCheckin`/`checkinCard`. `weeklyCheckin`→`{deltas,sessions,streakSummary,winLine}` consumed by `checkinCard`. `trainingWeekdays()` returns weekday numbers in the same `getUTCDay` convention `computeStreaks` uses (verified against Task 1's test set `[1..6]`). Python `weekly_summary`→`(title, body)` matches `build_message`'s return contract.
