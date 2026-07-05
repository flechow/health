# Body Composition (M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track waist + 4 secondary circumferences (weekly, device-local) so progress reads as *recomposition* (fat down, muscle held) rather than scale weight alone; surface a "Sylwetka" card, a Progress-tab waist trend, and body-comp priority rules; auto-light smart-scale body-fat/muscle when present.

**Architecture:** Front-end only — all edits are in the single-file PWA `index.html` (inline JS). Circumferences live in a new plaintext `localStorage` store `bodycomp-v1` (same trust model as the existing `fit-log-v1` weights and `markers-v1` blood labs). Per-phase targets live in `plan.json`. No Python, no Actions, no worker, no encrypted write-back — the browser only reads/decrypts Garmin rows; manual inputs have always lived in localStorage.

**Tech Stack:** Vanilla inline JS in `index.html`; `plan.json` config; existing helpers `load`/`save`, `spark`, `trend`, `activePhase`, `priorities`, `render`.

## Global Constraints

- **Front-end only.** No changes to `update_garmin.py`, `fitatu.py`, `send_briefing.py`, workflows, worker, or `sw.js`. No new secret.
- **Storage:** circumferences in `localStorage` key `bodycomp-v1`, shape `{ "circ": { "YYYY-MM-DD": { "waist": <cm>, "neck": <cm>, "hips": <cm>, "arm": <cm>, "thigh": <cm> } } }`. Every site optional per entry; only `waist` is "expected". Units = centimeters.
- **Photos are OUT of scope for M2** (user decision 2026-07-06). No IndexedDB, no `<input type=file>`, no photo UI.
- **Five sites, fixed:** `waist`, `neck`, `hips`, `arm`, `thigh` (user chose the full set). Polish labels: talia, kark, biodra, ramię, udo.
- **Input hygiene** mirrors the weight input exactly: `parseFloat((v||"").replace(",","."))`, reject falsy/out-of-range, `Math.round(v*10)/10`, then `save(...)` + `render()`. Per-site clamps (cm): waist 50–200, neck 25–70, hips 60–200, arm 20–70, thigh 30–110.
- **Per-phase targets** in `plan.json` `body` block: `{ "waistCm": <n>, "bodyFatPct": <n> }`. Phase 1 waistCm 100 (intermediate), Phase 2 waistCm 94 (final, ≈half of the user's ~190 cm height). Missing `body` block → card renders without a target line and body priority rules skip (same graceful-degradation contract as the M1 `nutrition` block).
- **Readiness score stays recovery-driven and UNCHANGED.** Body-comp is a *progress* signal — it may feed `priorities()` and the Progress tab, but must not alter the `readiness()` score/zone.
- **Null-guard everything** interpolated into the DOM (no `undefined`/`NaN` leaks), using the codebase's `x!=null && !isNaN(x)` / `nz()` conventions and the `${v!=null?…:""}` conditional-render pattern.
- **Testing:** `index.html` is a single self-contained file with inline JS and no module boundary or JS test harness; introducing one would break the offline/`sw.js` PWA model. Per the M1 precedent (frontend tasks verified statically + manually), M2 frontend tasks use **static structural asserts** (`python3 -c` on `index.html`) plus **explicit manual browser checks**. No automated JS unit tests are added.

---

## File Structure

- `plan.json` (modify) — add a `body` block to each phase.
- `index.html` (modify) — all feature code:
  - `DEFAULT_PLAN` offline fallback: add `body` block.
  - `bodyTargets()` helper (after `fuelTargets()`).
  - `bodyLog` global + `load("bodycomp-v1",{circ:{}})` + measurement read/save helpers.
  - `sylwetkaCard()` + its measurement-input handler + render insertion.
  - `INFO` entries: `talia`, `bodyfat`, `sylwetka`.
  - Progress-tab waist (+ secondary) trend.
  - `priorities(rows)` body-comp rules.

Each task ends with a commit.

---

## Task 1: Data layer — `body` targets in plan.json + `bodyTargets()` + `bodycomp-v1` store

**Files:**
- Modify: `plan.json` (add `body` to both phases, after each `nutrition` block)
- Modify: `index.html` — `DEFAULT_PLAN` phase (add `body` after its `nutrition:{…}`); add `bodyTargets()` after `fuelTargets()` (ends ~line 224); add `bodyLog` global + helpers near the other localStorage loads (`log` is loaded ~line 394).

**Interfaces:**
- Produces:
  - `bodyTargets()` → `{waistCm, bodyFatPct}` for the active phase, or `null` if the phase has no `body` block.
  - `bodyLog` (module global) = `load("bodycomp-v1",{circ:{}})`.
  - `saveCirc(date, site, cm)` — writes `bodyLog.circ[date][site]=cm` and persists via `save("bodycomp-v1", bodyLog)`.
  - `circSeries(site)` → array of `{d, v}` sorted ascending by date, for the given site, skipping null/NaN.

- [ ] **Step 1: Add `body` block to plan.json (both phases)**

In `plan.json`, add after the Phase 1 `nutrition` block:
```json
      "body": { "waistCm": 100, "bodyFatPct": 15 },
```
and after the Phase 2 `nutrition` block:
```json
      "body": { "waistCm": 94, "bodyFatPct": 15 },
```

- [ ] **Step 2: Add `body` to DEFAULT_PLAN (offline fallback)**

In `index.html`, in the `DEFAULT_PLAN` constant, add after the phase's `nutrition:{…}` line (~line 189):
```javascript
    body:{waistCm:100,bodyFatPct:15},
```

- [ ] **Step 3: Add the `bodyTargets()` helper**

In `index.html`, immediately after `fuelTargets()` (ends ~line 224), add:
```javascript
function bodyTargets(){
  const ph=activePhase();
  const b=ph&&ph.body;
  if(!b) return null;
  return {waistCm:b.waistCm, bodyFatPct:b.bodyFatPct};
}
```

- [ ] **Step 4: Add the `bodyLog` store + helpers**

In `index.html`, near where `log` is loaded (`const log=load("fit-log-v1",{…})` ~line 394), add:
```javascript
const bodyLog=load("bodycomp-v1",{circ:{}});
function saveCirc(date, site, cm){
  const day=(bodyLog.circ[date]=bodyLog.circ[date]||{});
  day[site]=Math.round(cm*10)/10;
  save("bodycomp-v1", bodyLog);
}
function circSeries(site){
  return Object.keys(bodyLog.circ||{}).sort()
    .map(d=>({d, v:(bodyLog.circ[d]||{})[site]}))
    .filter(x=>x.v!=null && !isNaN(x.v));
}
```

- [ ] **Step 5: Static verification**

Run:
```bash
python3 -c "import json; d=json.load(open('plan.json')); assert all('body' in p and p['body']['waistCm'] for p in d['phases']), 'missing body block'; print('plan.json body:', [p['body'] for p in d['phases']])"
python3 -c "s=open('index.html').read(); assert s.count('function bodyTargets(')==1; assert 'load(\"bodycomp-v1\"' in s; assert 'function saveCirc(' in s and 'function circSeries(' in s; assert 'body:{waistCm:100' in s; assert s.count('<script')==s.count('</script>'); print('ok: bodyTargets + bodycomp store + DEFAULT_PLAN body + tags balanced')"
```
Expected: both print `ok`/values, asserts pass.

- [ ] **Step 6: Manual browser check**

Serve locally (`python3 -m http.server 8000`), open the app, DevTools console:
- `bodyTargets()` → `{waistCm:100, bodyFatPct:15}`.
- `saveCirc("2026-07-06","waist",104); circSeries("waist")` → `[{d:"2026-07-06", v:104}]`.
Then in console: `localStorage.removeItem("bodycomp-v1")` to reset before real use (leave a note in report).

- [ ] **Step 7: Commit**
```bash
git add plan.json index.html
git commit -m "feat(m2): add body-comp targets, bodyTargets() helper, bodycomp-v1 store"
```

---

## Task 2: "Sylwetka" card + measurement input + INFO entries

**Files:**
- Modify: `index.html` — add `sylwetkaCard()` (near `fuelCard()`/`garminCard()`); insert `${sylwetkaCard()}` in `render()` after the weight-input card (~line 857) and before `${garminCard()}` (~line 859); add its input handler in the post-render wiring block (where `wsave.onclick` is set, ~line 897); add `INFO` entries `talia`, `bodyfat`, `sylwetka` (~lines 541–568).

**Interfaces:**
- Consumes: `bodyLog`, `bodyTargets()`, `saveCirc`, `circSeries` (Task 1), `gar.rows` (for smart-scale `body_fat`/`muscle_kg`), helpers `r1`, `ic`, `nz`, `mean`, `render`, `save`.
- Produces: `sylwetkaCard()` → HTML string (never throws; friendly empty-state when no data). Input element ids: `circ-waist`, `circ-neck`, `circ-hips`, `circ-arm`, `circ-thigh`, and a save button `circ-save`.

- [ ] **Step 1: Implement `sylwetkaCard()`**

In `index.html`, after `fuelCard()` (ends ~line, right before `kondycjaCard()` or `garminCard()`), add. It shows latest waist vs target, a 4-week delta, conditional smart-scale body-fat/muscle from the latest row, and inline add-measurement inputs for all five sites:
```javascript
function sylwetkaCard(){
  const tg=bodyTargets();
  const waistS=circSeries("waist");
  const latestRow=(gar&&gar.rows&&gar.rows.length)?gar.rows[gar.rows.length-1]:{};
  const bf=(latestRow.body_fat!=null&&!isNaN(latestRow.body_fat))?latestRow.body_fat:null;
  const mus=(latestRow.muscle_kg!=null&&!isNaN(latestRow.muscle_kg))?latestRow.muscle_kg:null;
  // 4-week (last ~4 weekly entries) waist delta
  const last=waistS.length?waistS[waistS.length-1].v:null;
  const ref=waistS.length>=5?waistS[waistS.length-5].v:(waistS.length?waistS[0].v:null);
  const d4=(last!=null&&ref!=null)?Math.round((last-ref)*10)/10:null;
  const sites=[["waist","Talia",50,200],["neck","Kark",25,70],["hips","Biodra",60,200],["arm","Ramię",20,70],["thigh","Udo",30,110]];
  const inputs=sites.map(([id,label])=>
    `<label class="circ-l">${label}<input type="text" inputmode="decimal" id="circ-${id}" placeholder="cm"></label>`).join("");
  const waistLine = last!=null
    ? `<div class="mv mono">${r1(last)}<span style="font-size:13px;color:var(--mut)"> cm</span>${d4!=null&&Math.abs(d4)>=0.1?`<span class="arrow ${d4<0?"up":"down"}">${d4<0?"▼":"▲"}${Math.abs(d4)}</span>`:""}</div>
       <div class="ml">Talia${tg&&tg.waistCm?` / cel ${tg.waistCm} cm`:""}${ic()}</div>`
    : `<div class="sub">Dodaj pierwszy pomiar talii poniżej.</div>`;
  return `<div class="card">
    <p class="label">Sylwetka</p>
    <div class="metrics">
      <div class="m" data-info="talia">${waistLine}</div>
      ${d4!=null?`<div class="m" data-info="sylwetka"><div class="mv mono">${d4<0?"−":"+"}${Math.abs(d4)}<span style="font-size:13px;color:var(--mut)"> cm</span></div><div class="ml">Talia − 4 tyg.${ic()}</div></div>`:""}
      ${bf!=null?`<div class="m" data-info="bodyfat"><div class="mv mono">${r1(bf)}<span style="font-size:13px;color:var(--mut)"> %</span></div><div class="ml">Tłuszcz (waga)${ic()}</div></div>`:""}
      ${mus!=null?`<div class="m" data-info="bodyfat"><div class="mv mono">${r1(mus)}<span style="font-size:13px;color:var(--mut)"> kg</span></div><div class="ml">Mięśnie (waga)${ic()}</div></div>`:""}
    </div>
    <div class="circ-row">${inputs}<button class="btn-sm" id="circ-save">Zapisz pomiar</button></div>
  </div>`;
}
```

- [ ] **Step 2: Insert the card in render()**

In `render()`, in the "Dziś" (non-progress) branch, insert `${sylwetkaCard()}` immediately after the weight-input card and before `${garminCard()}` (~line 859):
```javascript
    ${sylwetkaCard()}
    ${garminCard()}
```

- [ ] **Step 3: Wire the measurement-input handler**

In the post-render event-wiring block (where `wsave.onclick` is assigned, ~line 897), add after the weight-input wiring:
```javascript
  const cs=document.getElementById("circ-save");
  if(cs){
    const clamps={waist:[50,200],neck:[25,70],hips:[60,200],arm:[20,70],thigh:[30,110]};
    cs.onclick=()=>{
      let wrote=false;
      for(const id in clamps){
        const el=document.getElementById("circ-"+id);
        if(!el||!el.value) continue;
        const v=parseFloat((el.value||"").replace(",","."));
        const [lo,hi]=clamps[id];
        if(!v||v<lo||v>hi) continue;
        saveCirc(tk, id, v); wrote=true;
      }
      if(wrote) render();
    };
  }
```
(`tk` is today's date key, already in scope in render's wiring block — it is the same variable the weight handler uses via `log.weights[tk]`.)

- [ ] **Step 4: Add INFO explain-sheet entries**

In the `INFO` object (~lines 541–568), add:
```javascript
 talia:{t:"Obwód talii",h:`<p>Najtańszy wiarygodny wskaźnik utraty tłuszczu. Mierz na wysokości pępka, na luźnym wydechu, taśma przylega ale nie wciska. Zawsze o tej samej porze (rano).</p><p>Liczy się <b>trend tygodniowy</b>, nie pojedynczy pomiar. Talia w dół + waga ~stała + ciężary w górę = rekompozycja działa.</p><p class="t">Cel końcowy: ok. 94 cm.</p>`},
 bodyfat:{t:"Skład ciała (z wagi)",h:`<p>Procent tłuszczu i masa mięśni pojawiają się tu automatycznie, jeśli używasz wagi Garmin Index. Bez niej ta sekcja jest ukryta — talia i tak odpowiada na pytanie o rekompozycję.</p>`},
 sylwetka:{t:"Obwody ciała",h:`<p>Talia, kark, biodra, ramię, udo. Mierzone co tydzień. <b>Talia spada, a ramię/udo trzymają</b> = tłuszcz schodzi, mięśnie zostają. Wpisuj rano, w tych samych warunkach.</p>`},
```

- [ ] **Step 5: Add minimal CSS for the input row (if needed)**

If `.circ-row` / `.circ-l` aren't styled by existing classes, add near the other component styles a compact rule (match existing look — small inputs in a wrapping row):
```css
.circ-row{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-top:12px}
.circ-l{display:flex;flex-direction:column;font-size:12px;color:var(--mut);gap:4px}
.circ-l input{width:64px}
```
(Reuse existing input styling; only add what's missing.)

- [ ] **Step 6: Static verification**

Run:
```bash
python3 -c "s=open('index.html').read(); assert s.count('function sylwetkaCard(')==1; assert '\${sylwetkaCard()}' in s; assert 'talia:{' in s and 'bodyfat:{' in s and 'sylwetka:{' in s; assert 'circ-save' in s; assert s.count('<script')==s.count('</script>'); print('ok: sylwetkaCard defined+rendered, 3 INFO entries, input wired')"
```
Expected: `ok`.

- [ ] **Step 7: Manual browser check**

Serve locally, load real data (enter passphrase). Expected: a "Sylwetka" card appears after the weight card. With no measurements it prompts "Dodaj pierwszy pomiar talii". Enter waist=104 → Zapisz pomiar → card shows `104 cm / cel 100 cm`. Add a second later-dated entry (or edit via console) → "Talia − 4 tyg." appears with a delta arrow. Tapping "Talia" opens the explain sheet. Body-fat/muscle rows are absent (no smart scale). Reload → measurement persists.

- [ ] **Step 8: Commit**
```bash
git add index.html
git commit -m "feat(m2): add Sylwetka card, measurement input, and explain-sheet entries"
```

---

## Task 3: Progress-tab waist (+ secondary) trend

**Files:**
- Modify: `index.html` — `progressView(rows)` (~lines 708–731): add a waist trend beneath the weight trend, plus optional secondary-site trends.

**Interfaces:**
- Consumes: the nested `trend(label, vals, unit, goodUp, info, color)` helper (~lines 711–719), `circSeries` (Task 1), `spark`.

- [ ] **Step 1: Add the waist trend beneath the weight trend**

In `progressView`, the trend block currently renders Waga, HRV, VO₂max, Kroki, Białko, Energia (~lines 726–731). Insert the waist trend directly after the Waga line so the recomp story (weight flat / waist down) reads together. `trend()` takes a numeric array, so map the waist series to values:
```javascript
    ${trend("Talia",circSeries("waist").map(x=>x.v),"cm",false,"talia","#22d3ee")||""}
```

- [ ] **Step 2: Add secondary-site trends (collapsed under waist)**

After the waist trend line, add the four secondary sites (each self-hides when `<2` points via the existing `trend()` guard):
```javascript
    ${trend("Ramię",circSeries("arm").map(x=>x.v),"cm",true,"sylwetka","#a78bfa")||""}
    ${trend("Udo",circSeries("thigh").map(x=>x.v),"cm",true,"sylwetka","#a78bfa")||""}
    ${trend("Biodra",circSeries("hips").map(x=>x.v),"cm",false,"sylwetka","#a78bfa")||""}
    ${trend("Kark",circSeries("neck").map(x=>x.v),"cm",false,"sylwetka","#a78bfa")||""}
```
(`goodUp=true` for arm/thigh — growth = muscle held; `false` for waist/hips/neck.)

- [ ] **Step 3: Static verification**

Run:
```bash
python3 -c "s=open('index.html').read(); assert 'trend(\"Talia\",circSeries(\"waist\")' in s; assert s.count('circSeries(\"')>=5; assert s.count('<script')==s.count('</script>'); print('ok: waist + 4 secondary trends in progressView')"
```
Expected: `ok`.

- [ ] **Step 4: Manual browser check**

Add ≥2 dated waist entries (console: `saveCirc("2026-06-29","waist",106); saveCirc("2026-07-06","waist",104); render()`), open the Postępy tab. Expected: a "Talia" trend sparkline appears beneath "Waga" with a downward delta. Secondary-site trends appear only for sites with ≥2 entries; otherwise absent (no empty rows). With no circumference data, no body trends render and the existing trends are unaffected.

- [ ] **Step 5: Commit**
```bash
git add index.html
git commit -m "feat(m2): add waist + secondary-circumference trends to Progress tab"
```

---

## Task 4: Priorities integration (stale-measurement, recomp-confirmation, plateau)

**Files:**
- Modify: `index.html` — `priorities(rows)` (~lines 621–657): add body-comp candidates before the `C.sort(...)` call.

**Interfaces:**
- Consumes: `bodyTargets()`, `circSeries` (Task 1), `mergedWeights()` (existing; returns date-sorted `{k,v}` weights) OR `rows` weight, the candidate array `C` in `priorities`.
- Produces: candidates `{key:"measure"|"recomp"|"waistplateau", icon, title, note, weight}`.

- [ ] **Step 1: Add body-comp candidates to `priorities()`**

Inside `priorities(rows)`, before `C.sort((x,y)=>y.weight-x.weight)`, add:
```javascript
  const _bt=bodyTargets();
  const _ws=circSeries("waist");
  if(_ws.length){
    // stale measurement: last waist entry older than 14 days
    const lastD=_ws[_ws.length-1].d;
    const ageDays=Math.round((Date.parse(new Date().toISOString().slice(0,10))-Date.parse(lastD))/86400000);
    if(ageDays>=14)
      C.push({key:"measure",icon:"📏",title:"Zmierz talię",note:`Ostatni pomiar ${ageDays} dni temu — cotygodniowy obwód talii to Twój licznik tłuszczu.`,weight:6});
  } else {
    C.push({key:"measure",icon:"📏",title:"Zacznij mierzyć talię",note:"Cotygodniowy obwód talii pokazuje, czy tłuszcz schodzi, gdy waga stoi.",weight:6});
  }
  if(_ws.length>=4){
    // recomp confirmation: waist down over last ~4 entries while weight ~flat over ~28 days
    const wNow=_ws[_ws.length-1].v, wRef=_ws[_ws.length-4].v;
    const mw=(typeof mergedWeights==="function")?mergedWeights():[];
    const kgNow=mw.length?mw[mw.length-1].v:null;
    const kgRef=mw.length>=28?mw[mw.length-28].v:(mw.length?mw[0].v:null);
    const waistDown=(wNow!=null&&wRef!=null&&wNow<wRef-0.4);
    const weightFlat=(kgNow!=null&&kgRef!=null&&Math.abs(kgNow-kgRef)<=1.0);
    if(waistDown&&weightFlat)
      C.push({key:"recomp",icon:"✅",title:"Rekompozycja działa",note:"Talia spada przy ~stałej wadze — tłuszcz schodzi, mięśnie zostają. Tak trzymaj.",weight:3});
    // waist plateau vs target
    if(_bt&&_bt.waistCm&&!waistDown && wNow!=null && wNow>_bt.waistCm)
      C.push({key:"waistplateau",icon:"📉",title:"Talia stoi",note:`Obwód talii nie spada i jest powyżej celu ${_bt.waistCm} cm — sprawdź deficyt i kroki.`,weight:5});
  }
```

- [ ] **Step 2: Confirm the readiness score is untouched**

Re-read the diff: the only changes are inside `priorities(rows)`. No line inside `readiness(rows)` (score/zone/weights) is modified. State this explicitly in the report.

- [ ] **Step 3: Static verification**

Run:
```bash
python3 -c "s=open('index.html').read(); assert 'Zmierz talię' in s and 'Rekompozycja działa' in s; assert 'key:\"measure\"' in s; assert s.count('<script')==s.count('</script>'); print('ok: body-comp priority rules present')"
```
Expected: `ok`.

- [ ] **Step 4: Manual browser check**

- With no waist data: the priorities list shows `📏 Zacznij mierzyć talię`.
- Add a waist entry dated >14 days ago (console `saveCirc("2026-06-01","waist",106); render()`): shows `📏 Zmierz talię` with the age.
- Add 4 descending weekly waist entries while weight is ~flat: `✅ Rekompozycja działa` appears (weight w/ real decrypted rows). Confirm the readiness ring score is unchanged from before this task.

- [ ] **Step 5: Commit**
```bash
git add index.html
git commit -m "feat(m2): wire body-comp rules into the priorities engine"
```

---

## Self-Review

**Spec coverage:**
- Waist + 4 secondary sites, weekly, localStorage `bodycomp-v1` → Task 1 (store), Task 2 (input for all 5). ✓
- `plan.json` per-phase `body` targets + graceful degradation → Task 1 + Task 2 (target line optional) + Task 4 (rules skip when absent). ✓
- Sylwetka card (waist vs target, 4-week delta, conditional smart-scale body-fat/muscle) → Task 2. ✓
- Progress waist trend beneath weight + secondary trends → Task 3. ✓
- Priorities: stale-measurement, recomp-confirmation, plateau → Task 4. ✓
- Readiness score untouched → Task 4 Step 2 + Global Constraints. ✓
- Photos OUT → not present anywhere. ✓
- Smart-scale passthrough (no build) → Task 2 conditional body_fat/muscle rows, null-guarded. ✓

**Placeholder scan:** No TBD/TODO. Target numbers (waistCm 100/94, bodyFatPct 15) are concrete and user-tunable in `plan.json`. Clamp bounds are explicit per site.

**Type consistency:** `bodyLog.circ[date][site]` shape and site keys (`waist`/`neck`/`hips`/`arm`/`thigh`) are identical across `saveCirc`, `circSeries`, the input handler, and the trends. `bodyTargets()` shape `{waistCm, bodyFatPct}` consumed identically in Task 2 and Task 4. `circSeries(site)` returns `[{d,v}]` — Task 3 maps `.map(x=>x.v)` for `trend()`, Task 4 reads `.v` and `.d`; consistent.
