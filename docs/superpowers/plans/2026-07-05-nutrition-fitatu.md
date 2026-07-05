# Nutrition-via-Fitatu (M1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull daily nutrition (protein, calories, macros) from Fitatu into the encrypted Garmin data rows, surface it in the PWA as a "Paliwo" card + progress trends, and wire it into the weekly-priorities and Silnik Dnia logic.

**Architecture:** A new server-side Python module `fitatu.py` (reverse-engineered login + daily fetch, matching the existing `garminconnect` pattern) enriches the per-date rows built by `update_garmin.py` **before** encryption. Per-phase targets live in `plan.json`. The frontend (`index.html`, inline JS) reads the new row fields (`bialko`, `kcal_spozyte`, …) exactly like existing Garmin fields.

**Tech Stack:** Python 3.12 (`requests`, `cryptography`, `garminconnect`), pytest (new dev dep), vanilla inline JS in `index.html`, GitHub Actions.

## Global Constraints

- Data at rest stays AES-256-GCM encrypted; nutrition fields ride **inside** the existing blob — no new plaintext file, no field sent to the frontend unencrypted.
- Fitatu credentials live **only** as GitHub Actions secrets (`FITATU_EMAIL`, `FITATU_PASSWORD`), never in the repo or frontend.
- A Fitatu failure must **never** break the Garmin update or commit (same defensive posture as `send_briefing.py`).
- Row field names are Polish snake_case to match existing fields: `bialko`, `kcal_spozyte`, `wegle`, `tluszcz`, `blonnik`, plus nested `fitatu` for extras.
- Frontend null-handling convention: missing/`undefined`/`NaN` values are filtered by `nz(a)=a.filter(x=>x!=null&&!isNaN(x))`. Absent nutrition keys are therefore safe.
- Per-phase nutrition targets: `proteinG: 180`, `kcalTarget: 2200`, `kcalFloor: 1850` (Phase 1). Protein-priority threshold: 7-day avg < 85% of `proteinG`. Deficit warning: `kcal_spozyte < kcalFloor` for 3+ consecutive days.

---

## File Structure

- `spike_fitatu.py` (temporary, git-ignored) — Task 1 feasibility probe; deleted after.
- `fitatu.py` (new) — Fitatu login + daily nutrition fetch + normalization. One responsibility: talk to Fitatu, return normalized dicts.
- `tests/test_fitatu.py` (new) — unit tests for `normalize_nutrition`.
- `tests/test_nutrition_merge.py` (new) — unit tests for `carry_forward_nutrition` + `enrich_nutrition`.
- `update_garmin.py` (modify) — add merge helpers + `main()` wiring.
- `plan.json` (modify) — add `nutrition` block per phase.
- `.github/workflows/update.yml` (modify) — pass Fitatu secrets as env.
- `requirements-dev.txt` (new) — pytest.
- `index.html` (modify) — nutrition targets helper, Paliwo card, progress trends, priorities + Silnik Dnia integration, INFO explain entries, DEFAULT_PLAN nutrition.

---

## Task 1: Feasibility spike (Fitatu endpoint discovery)

**Gating task.** Exploratory, not TDD. Confirms Path A is viable and captures the real response shape that Task 2 normalizes. If it fails, STOP and revisit Path B/C with the user.

**Files:**
- Create: `spike_fitatu.py` (temporary)
- Modify: `.gitignore` (add `spike_fitatu.py` and `fitatu_sample.json`)

- [ ] **Step 1: Add spike artifacts to .gitignore**

Append to `.gitignore`:
```
# Fitatu feasibility spike (temporary)
spike_fitatu.py
fitatu_sample.json
```

- [ ] **Step 2: Write the spike probe**

Reference the unofficial `fitatu-sdk` (https://github.com/Capure/fitatu-sdk) `login()` + `getDietAndActivityPlan()` for endpoint/URL discovery. Create `spike_fitatu.py`:
```python
# -*- coding: utf-8 -*-
"""TEMPORARY Fitatu feasibility spike. Run locally with real creds:
   FITATU_EMAIL=... FITATU_PASSWORD=... python spike_fitatu.py 2026-07-04
Confirms login + one day's nutrition summary and dumps the raw JSON so we can
map fields in fitatu.py. DELETE after Task 2."""
import os, sys, json, requests

EMAIL = os.environ["FITATU_EMAIL"]
PW = os.environ["FITATU_PASSWORD"]
DAY = sys.argv[1] if len(sys.argv) > 1 else None

s = requests.Session()
s.headers.update({"User-Agent": "protokol-health/spike", "Accept": "application/json"})

# NOTE: exact login URL + payload + auth-header scheme are what this spike discovers.
# Start from the fitatu-sdk login flow; print everything so we can see the real shape.
login_resp = s.post("https://pl.fitatu.com/api/login", json={"login": EMAIL, "password": PW}, timeout=30)
print("LOGIN", login_resp.status_code)
print(login_resp.text[:800])
login_resp.raise_for_status()
tok = login_resp.json()
print("LOGIN KEYS:", list(tok.keys()))

# Discover the daily-summary/diary endpoint. Print the raw body for one day.
diary = s.get(f"https://pl.fitatu.com/api/diet-diary/{DAY}", timeout=30)
print("DIARY", diary.status_code)
raw = diary.json()
with open("fitatu_sample.json", "w", encoding="utf-8") as f:
    json.dump(raw, f, ensure_ascii=False, indent=2)
print("Saved fitatu_sample.json — inspect for protein/kcal/macro keys.")
```

- [ ] **Step 3: Run the spike locally**

Run: `FITATU_EMAIL='...' FITATU_PASSWORD='...' python spike_fitatu.py 2026-07-04`
Expected: `LOGIN 200`, a token/session established, and `fitatu_sample.json` written containing that day's totals.

**If login returns 4xx / requires captcha / app-attestation:** STOP. Path A is not viable as-is; report the exact failure to the user and revisit Path B (Apple Health / Health Connect) or C (manual export). Do not proceed.

- [ ] **Step 4: Record the field mapping**

Open `fitatu_sample.json`. Identify the JSON paths for: total protein (g), total energy (kcal), carbs (g), fat (g), fiber (g). Write them into a comment block at the top of `spike_fitatu.py` (they seed `KEY_MAP` in Task 2). Do **not** commit `spike_fitatu.py` or `fitatu_sample.json` (git-ignored). Commit only the `.gitignore` change:

```bash
git add .gitignore
git commit -m "chore: ignore Fitatu feasibility spike artifacts"
```

---

## Task 2: `fitatu.py` module — login, fetch, normalize

**Files:**
- Create: `fitatu.py`
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_fitatu.py`

**Interfaces:**
- Produces:
  - `login(email: str, password: str) -> requests.Session` — authenticated session (auth token applied to headers).
  - `fetch_nutrition(session: requests.Session, day: str) -> dict | None` — raw daily summary for `"YYYY-MM-DD"`, or `None` if unavailable.
  - `normalize_nutrition(raw: dict | None) -> dict` — pure mapping to `{"bialko","kcal_spozyte","wegle","tluszcz","blonnik","fitatu"}`, values `float|None`.
  - `fetch_normalized(session, day) -> dict` — convenience: `normalize_nutrition(fetch_nutrition(session, day))`.

- [ ] **Step 1: Create the dev-deps file**

Create `requirements-dev.txt`:
```
pytest==8.3.4
```
Run: `pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing test for `normalize_nutrition`**

Create `tests/__init__.py` (empty) and `tests/test_fitatu.py`. Use a fixture shaped like the spike's `fitatu_sample.json` (adjust key paths in `RAW` to match what Task 1 recorded):
```python
import fitatu

RAW = {  # shape confirmed by Task 1 spike (fitatu_sample.json)
    "summary": {"energy": 2080, "protein": 172.4, "carbohydrate": 190.1, "fat": 68.0, "fiber": 28.2},
    "someExtra": {"sodium": 3200},
}

def test_normalize_maps_core_macros():
    out = fitatu.normalize_nutrition(RAW)
    assert out["bialko"] == 172.4
    assert out["kcal_spozyte"] == 2080
    assert out["wegle"] == 190.1
    assert out["tluszcz"] == 68.0
    assert out["blonnik"] == 28.2

def test_normalize_keeps_raw_in_fitatu_key():
    out = fitatu.normalize_nutrition(RAW)
    assert out["fitatu"] == RAW

def test_normalize_none_returns_all_null():
    out = fitatu.normalize_nutrition(None)
    assert out == {"bialko": None, "kcal_spozyte": None, "wegle": None,
                   "tluszcz": None, "blonnik": None, "fitatu": None}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_fitatu.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fitatu'`.

- [ ] **Step 4: Implement `fitatu.py`**

Fill `LOGIN_URL`, `DIARY_URL`, the login payload, the auth-header scheme, and `KEY_MAP` paths from the Task 1 spike. `normalize_nutrition` reads via `KEY_MAP` so the one shape-dependency is isolated here:
```python
# -*- coding: utf-8 -*-
"""Nieoficjalny pobieracz odzywiania z Fitatu (analogicznie do garminconnect).
Loguje sie, pobiera dzienne podsumowanie makro i normalizuje do pol wiersza."""
import requests

LOGIN_URL = "https://pl.fitatu.com/api/login"          # potwierdzone w spike (Task 1)
DIARY_URL = "https://pl.fitatu.com/api/diet-diary/{day}"  # potwierdzone w spike (Task 1)

# Sciezki do wartosci w surowej odpowiedzi Fitatu (ustalone w Task 1 ze spike'u).
# Kazdy wpis to lista kluczy do zejscia w zagniezdzonym dict.
KEY_MAP = {
    "bialko":       ["summary", "protein"],
    "kcal_spozyte": ["summary", "energy"],
    "wegle":        ["summary", "carbohydrate"],
    "tluszcz":      ["summary", "fat"],
    "blonnik":      ["summary", "fiber"],
}


def login(email, password):
    s = requests.Session()
    s.headers.update({"User-Agent": "protokol-health/1.0", "Accept": "application/json"})
    r = s.post(LOGIN_URL, json={"login": email, "password": password}, timeout=30)
    r.raise_for_status()
    tok = r.json()
    token = tok.get("token") or tok.get("access_token")
    if token:
        s.headers.update({"Authorization": "Bearer " + token})
    return s


def fetch_nutrition(session, day):
    try:
        r = session.get(DIARY_URL.format(day=day), timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Fitatu fetch", day, "blad:", str(e)[:160])
        return None


def _dig(d, path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur if isinstance(cur, (int, float)) else None


def normalize_nutrition(raw):
    if not isinstance(raw, dict):
        return {k: None for k in ("bialko", "kcal_spozyte", "wegle", "tluszcz", "blonnik", "fitatu")}
    out = {dst: _dig(raw, path) for dst, path in KEY_MAP.items()}
    out["fitatu"] = raw
    return out


def fetch_normalized(session, day):
    return normalize_nutrition(fetch_nutrition(session, day))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_fitatu.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Delete the spike and commit**

```bash
rm -f spike_fitatu.py fitatu_sample.json
git add fitatu.py tests/__init__.py tests/test_fitatu.py requirements-dev.txt
git commit -m "feat: add Fitatu nutrition fetch + normalization module"
```

---

## Task 3: Nutrition merge helpers in `update_garmin.py`

**Files:**
- Modify: `update_garmin.py` (add helpers near `merge_rows`, `update_garmin.py:202-208`)
- Create: `tests/test_nutrition_merge.py`

**Interfaces:**
- Consumes: `fitatu.fetch_normalized` (Task 2) — but tests inject a fake `fetch_fn`.
- Produces:
  - `NUTRI_KEYS = ("bialko", "kcal_spozyte", "wegle", "tluszcz", "blonnik", "fitatu")`
  - `carry_forward_nutrition(old_rows: list, new_rows: list) -> None` — mutates `new_rows`, copying `NUTRI_KEYS` from same-date old rows where the new row lacks them.
  - `enrich_nutrition(rows: list, fetch_fn, days: int = 14) -> None` — mutates the last `days` dated `rows`, setting `NUTRI_KEYS` from `fetch_fn(date)` (a dict). Skips when `fetch_fn` returns all-null.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nutrition_merge.py`:
```python
import update_garmin as ug

def _row(d, **kw):
    r = {"data": d}
    r.update(kw)
    return r

def test_carry_forward_copies_nutrition_for_matching_date():
    old = [_row("2026-06-01", bialko=150, kcal_spozyte=2000, wegle=None,
                tluszcz=None, blonnik=None, fitatu={"x": 1})]
    new = [_row("2026-06-01"), _row("2026-06-02")]
    ug.carry_forward_nutrition(old, new)
    assert new[0]["bialko"] == 150
    assert new[0]["kcal_spozyte"] == 2000
    assert "bialko" not in new[1]  # no old data for that date

def test_carry_forward_does_not_overwrite_existing():
    old = [_row("2026-06-01", bialko=150)]
    new = [_row("2026-06-01", bialko=999)]
    ug.carry_forward_nutrition(old, new)
    assert new[0]["bialko"] == 999

def test_enrich_sets_recent_days_from_fetch():
    rows = [_row("2026-06-01"), _row("2026-06-02"), _row("2026-06-03")]
    def fake_fetch(day):
        return {"bialko": 100, "kcal_spozyte": 1800, "wegle": 150,
                "tluszcz": 60, "blonnik": 20, "fitatu": {"day": day}}
    ug.enrich_nutrition(rows, fake_fetch, days=2)
    assert "bialko" not in rows[0]           # outside the 2-day window
    assert rows[1]["bialko"] == 100
    assert rows[2]["kcal_spozyte"] == 1800

def test_enrich_skips_all_null_days():
    rows = [_row("2026-06-03")]
    def fake_fetch(day):
        return {"bialko": None, "kcal_spozyte": None, "wegle": None,
                "tluszcz": None, "blonnik": None, "fitatu": None}
    ug.enrich_nutrition(rows, fake_fetch, days=1)
    assert "bialko" not in rows[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_nutrition_merge.py -v`
Expected: FAIL with `AttributeError: module 'update_garmin' has no attribute 'carry_forward_nutrition'`.

- [ ] **Step 3: Implement the helpers**

In `update_garmin.py`, immediately after `merge_rows` (ends at line 208), add:
```python
NUTRI_KEYS = ("bialko", "kcal_spozyte", "wegle", "tluszcz", "blonnik", "fitatu")

def carry_forward_nutrition(old_rows, new_rows):
    """Kopiuje pola odzywiania ze starych wierszy na wiersze o tej samej dacie,
    ktore ich jeszcze nie maja. Chroni historie przy pelnym przebiegu (bez merge)."""
    old_by = {r["data"]: r for r in (old_rows or []) if isinstance(r, dict) and r.get("data")}
    for r in new_rows:
        src = old_by.get(r.get("data"))
        if not src:
            continue
        for k in NUTRI_KEYS:
            if k not in r and k in src:
                r[k] = src[k]

def enrich_nutrition(rows, fetch_fn, days=14):
    """Dla ostatnich `days` dni ustawia pola odzywiania z fetch_fn(date)->dict.
    Pomija dni bez danych (same None)."""
    window = [r for r in rows if r.get("data")][-days:]
    for r in window:
        nutri = fetch_fn(r["data"])
        if not isinstance(nutri, dict):
            continue
        if all(nutri.get(k) is None for k in ("bialko", "kcal_spozyte")):
            continue
        for k in NUTRI_KEYS:
            r[k] = nutri.get(k)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_nutrition_merge.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add update_garmin.py tests/test_nutrition_merge.py
git commit -m "feat: add nutrition carry-forward + enrichment helpers"
```

---

## Task 4: Wire Fitatu into `update_garmin.main()` + workflow env + plan.json targets

**Files:**
- Modify: `update_garmin.py` (imports near line 18; `main()` between line 366 and the `encrypt_rows` call at line 368)
- Modify: `.github/workflows/update.yml:37-41`
- Modify: `plan.json` (add `nutrition` to each phase)

**Interfaces:**
- Consumes: `carry_forward_nutrition`, `enrich_nutrition` (Task 3), `fitatu.login`, `fitatu.fetch_normalized` (Task 2).

- [ ] **Step 1: Import fitatu (guarded)**

In `update_garmin.py`, after line 18 (`from garminconnect import Garmin`), add:
```python
try:
    import fitatu
except Exception:
    fitatu = None
```

- [ ] **Step 2: Add the enrichment block in `main()`**

In `update_garmin.py`, insert **after** the fast/full `rows` block (after line 366, before `blob = encrypt_rows(rows, passphrase)` at line 368):
```python
    # ---- odzywianie z Fitatu (opcjonalne; nigdy nie psuje aktualizacji Garmina) ----
    f_email = os.environ.get("FITATU_EMAIL")
    f_pw = os.environ.get("FITATU_PASSWORD")
    if fitatu and f_email and f_pw:
        try:
            old_nutri = old if fast else load_existing_rows(passphrase)
            carry_forward_nutrition(old_nutri, rows)
            fsession = fitatu.login(f_email, f_pw)
            f_days = int(os.environ.get("FITATU_DNI") or 14)
            enrich_nutrition(rows, lambda d: fitatu.fetch_normalized(fsession, d), days=f_days)
            print(f"Fitatu: uzupelniono odzywianie dla ostatnich {f_days} dni")
        except Exception as e:
            print("Fitatu pominiete (blad):", str(e)[:200])
    else:
        print("Fitatu: brak FITATU_EMAIL/FITATU_PASSWORD — pomijam odzywianie.")
```
Note: `old` is defined only in the fast branch (line 358). The `old if fast else …` guard handles that; in fast mode `rows` already contains merged history, so carry-forward is a harmless no-op there.

- [ ] **Step 3: Add nutrition summary to the print block**

In `update_garmin.py`, extend the summary loop at line 375 to include a nutrition field:
```python
    for k in ("waga", "hrv", "temp_noc", "miejsce", "body_fat", "training_status", "bialko", "kcal_spozyte"):
        print(f"  {k}: {cnt(k)}")
```

- [ ] **Step 4: Pass Fitatu secrets in the workflow**

In `.github/workflows/update.yml`, extend the `env:` block of the "Pobierz dane z Garmina" step (lines 38-40) to:
```yaml
        env:
          DATA_PASSPHRASE: ${{ secrets.DATA_PASSPHRASE }}
          DNI_OVERRIDE: ${{ github.event.inputs.days }}
          FITATU_EMAIL: ${{ secrets.FITATU_EMAIL }}
          FITATU_PASSWORD: ${{ secrets.FITATU_PASSWORD }}
          FITATU_DNI: "14"
```

- [ ] **Step 5: Add nutrition targets to plan.json**

In `plan.json`, add a `nutrition` key to Phase 1 (after its `cardio` block, `plan.json:13`) and Phase 2 (after its `cardio` block, `plan.json:45`):
```json
      "nutrition": { "proteinG": 180, "kcalTarget": 2200, "kcalFloor": 1850 },
```
(Same values for both phases initially; Phase 2 is adjustable later, like the rest of its sketch.)

- [ ] **Step 6: Verify the full run end-to-end (manual)**

Set the GitHub secrets `FITATU_EMAIL` / `FITATU_PASSWORD` in the repo (Settings → Secrets → Actions). Then run locally in fast mode against real accounts:
Run: `DATA_PASSPHRASE='...' FITATU_EMAIL='...' FITATU_PASSWORD='...' DNI_OVERRIDE=3 python update_garmin.py`
Expected: output includes `Fitatu: uzupelniono odzywianie dla ostatnich 14 dni` and the summary shows non-zero `bialko:` / `kcal_spozyte:` counts. Confirm `garmin-7c1f93a2.json` still parses as an encrypted blob (`{"v":1,...,"ct":...}`).

- [ ] **Step 7: Commit**

```bash
git add update_garmin.py .github/workflows/update.yml plan.json
git commit -m "feat: enrich daily rows with Fitatu nutrition + per-phase targets"
```

---

## Task 5: Frontend nutrition targets helper + DEFAULT_PLAN

**Files:**
- Modify: `index.html` — `DEFAULT_PLAN` phases (lines 183-206); add `fuelTargets()` near `activePhase()` (line 212).

**Interfaces:**
- Produces: `fuelTargets()` → `{proteinG, kcalTarget, kcalFloor}` for the active phase, or `null` if the phase has no `nutrition` block.

- [ ] **Step 1: Add nutrition to DEFAULT_PLAN (offline fallback)**

In `index.html`, add a `nutrition` field to each phase object in `DEFAULT_PLAN` (Phase 1 after its `cardio:{…}` at line 188; Phase 2 similarly if present):
```javascript
     cardio:{baseMin:35,stepMin:5,everyWeeks:2,capMin:50,zone:"tętno 125–140 · oddech nosem"},
     nutrition:{proteinG:180,kcalTarget:2200,kcalFloor:1850},
```

- [ ] **Step 2: Add the `fuelTargets()` helper**

In `index.html`, immediately after the `activePhase()` function (ends near line 228), add:
```javascript
function fuelTargets(){
  const ph=activePhase();
  const n=ph&&ph.nutrition;
  if(!n) return null;
  return {proteinG:n.proteinG, kcalTarget:n.kcalTarget, kcalFloor:n.kcalFloor};
}
```

- [ ] **Step 3: Verify in the browser console (manual)**

Serve the app locally (e.g. `python -m http.server` in the repo root) and open it. In DevTools console, run `fuelTargets()`.
Expected: `{proteinG:180, kcalTarget:2200, kcalFloor:1850}`.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: add per-phase fuel-targets helper + DEFAULT_PLAN nutrition"
```

---

## Task 6: "Paliwo" card + explain-sheet

**Files:**
- Modify: `index.html` — add `fuelCard()` near `garminCard()` (lines 426-460); render it in `render()` (near the Silnik Dnia / garmin cards); add INFO entries to the `INFO` map (lines 490-515).

**Interfaces:**
- Consumes: `gar.rows`, `fuelTargets()`, helpers `nz`, `mean`, `r1`, `spark`, `ic`.
- Produces: `fuelCard()` → HTML string (or `""` when no nutrition data present).

- [ ] **Step 1: Implement `fuelCard()`**

In `index.html`, after `garminCard()` (ends ~line 460), add. It shows protein (actual-today vs 7-day avg vs target), kcal (actual vs target with deficit), a protein sparkline, and a day-freshness label:
```javascript
function fuelCard(){
  if(!gar||!gar.rows||!gar.rows.length) return "";
  const rows=gar.rows;
  const tg=fuelTargets();
  const prot=rows.map(r=>r.bialko), kcal=rows.map(r=>r.kcal_spozyte);
  const protVals=nz(prot);
  if(!protVals.length) return "";                 // brak danych z Fitatu — nie pokazuj karty
  const last=rows[rows.length-1]||{};
  const today=(new Date()).toISOString().slice(0,10);
  const isToday = last.data===today;
  const dayLabel = isToday ? "dziś (na bieżąco)" : "ostatni pełny dzień";
  const protNow = last.bialko!=null&&!isNaN(last.bialko) ? last.bialko : null;
  const kcalNow = last.kcal_spozyte!=null&&!isNaN(last.kcal_spozyte) ? last.kcal_spozyte : null;
  const prot7 = mean(nz(prot).slice(-7));
  const protTgt = tg?tg.proteinG:null, kcalTgt = tg?tg.kcalTarget:null;
  const deficit = (kcalNow!=null&&kcalTgt!=null) ? kcalTgt-kcalNow : null;
  const okStyle="color:#10b981", lowStyle="color:#ef4444";
  const protHit = (protNow!=null&&protTgt!=null&&protNow>=protTgt*0.9);
  return `<div class="card">
    <p class="label">Paliwo (z Fitatu) · ${dayLabel}</p>
    <div class="metrics">
      <div class="m" data-info="bialko">
        <div class="mv mono" style="${protHit?okStyle:lowStyle}">${protNow!=null?r1(protNow):"—"}<span style="font-size:13px;color:var(--mut)"> g</span></div>
        <div class="ml">Białko${protTgt?` / cel ${protTgt} g`:""}${ic()}</div>
      </div>
      <div class="m" data-info="bialko">
        <div class="mv mono">${r1(prot7)}<span style="font-size:13px;color:var(--mut)"> g</span></div>
        <div class="ml">Białko (śr. 7 dni)${ic()}</div>
      </div>
      <div class="m" data-info="kcal">
        <div class="mv mono">${kcalNow!=null?Math.round(kcalNow):"—"}<span style="font-size:13px;color:var(--mut)"> kcal</span></div>
        <div class="ml">Energia${kcalTgt?` / cel ${kcalTgt}`:""}${ic()}</div>
      </div>
      <div class="m" data-info="kcal">
        <div class="mv mono">${deficit!=null?(deficit>=0?"−":"+")+Math.abs(Math.round(deficit)):"—"}<span style="font-size:13px;color:var(--mut)"> kcal</span></div>
        <div class="ml">Deficyt vs cel${ic()}</div>
      </div>
    </div>
    <div style="margin-top:14px"><p class="label" style="margin-bottom:6px">Białko — 14 dni</p>
      ${spark(nz(prot).slice(-14),"#f59e0b")}
    </div>
  </div>`;
}
```

- [ ] **Step 2: Render the card**

Find where `garminCard()` is inserted into the main view HTML in `render()` (the Regeneracja card). Insert `${fuelCard()}` immediately after that `${garminCard()}` call so Paliwo sits under Regeneracja.

- [ ] **Step 3: Add explain-sheet entries**

In the `INFO` object (lines 490-515), add two entries:
```javascript
 bialko:{t:"Białko — paliwo mięśni",h:`<p>W redukcji białko chroni mięśnie. Cel fazy: <b>ok. 2 g na kg wagi docelowej</b> (≈180 g przy 90 kg).</p><p>Liczy się <b>7-dniowa średnia</b>, nie pojedynczy dzień.</p><p class="t">Dane z Fitatu — zaloguj posiłki tam jak zwykle.</p>`},
 kcal:{t:"Energia i deficyt",h:`<p>Umiarkowany deficyt (~300–600 kcal) sprzyja utracie tłuszczu przy zachowaniu mięśni.</p><p>Za duży deficyt = ryzyko utraty mięśni. Nie schodź poniżej <b>podłogi kalorycznej</b> z planu.</p>`},
```

- [ ] **Step 4: Verify in the browser (manual)**

Serve locally, load real data (enter passphrase so `gar.rows` populates with the Task 4 nutrition fields). Expected: a "Paliwo (z Fitatu)" card appears under Regeneracja showing protein now/avg, kcal, deficit, and a 14-day protein sparkline. Tapping "Białko" or "Energia" (with explanations enabled) opens the correct bottom sheet. With a data file that has no nutrition, the card is absent (no error).

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat: add Paliwo nutrition card + explain-sheet entries"
```

---

## Task 7: Progress-tab nutrition trends

**Files:**
- Modify: `index.html` — `progressView(rows)` (lines 646-683), extending its trend list and weekly bars.

**Interfaces:**
- Consumes: the nested `trend(label,vals,unit,goodUp,info,color)` (lines 649-657), `nzslice`, `bars`, `weeklyAgg` output, `mean`.

- [ ] **Step 1: Add protein & kcal trend lines**

In `progressView`, alongside the existing `trend(...)` call sites (lines 664-667), add two more:
```javascript
    ${trend("Białko",nzslice("bialko",60),"g",true,"bialko","#f59e0b")}
    ${trend("Energia",nzslice("kcal_spozyte",60),"kcal",false,"kcal","#ef4444")}
```
(`goodUp:true` for protein — more is better in a cut; `false` for kcal — a controlled downward trend is expected.)

- [ ] **Step 2: Add weekly-average protein bars**

`weeklyAgg` (lines 630-638) aggregates `min_intensywne` per week. Extend it to also sum protein and day-count so we can average. In `weeklyAgg`, change the accumulation line to also track protein:
```javascript
    const v=(r.min_intensywne!=null&&!isNaN(r.min_intensywne))?r.min_intensywne:0;
    const b=(byWeek[k]=byWeek[k]||{minutes:0,trained:0,protSum:0,protN:0});
    b.minutes+=v;
    if(r.bialko!=null&&!isNaN(r.bialko)){ b.protSum+=r.bialko; b.protN++; }
```
And extend the returned week object (the `.map` at the end of `weeklyAgg`) to include:
```javascript
      protein: byWeek[k].protN ? Math.round(byWeek[k].protSum/byWeek[k].protN) : 0,
```
Then, after the existing weekly-volume `bars(...)` call (lines 670-672), add a protein-average bar chart:
```javascript
    <p class="label" style="margin:14px 0 6px">Białko — średnia tygodniowa (g/dzień)</p>
    ${bars(wk.filter(w=>w.protein>0).map(w=>({label:w.short,v:w.protein})),"#f59e0b")}
```

- [ ] **Step 3: Verify in the browser (manual)**

Open the Postępy (Progress) tab with real nutrition-bearing data. Expected: "Białko" and "Energia" trend cards render with sparklines and delta arrows; a "Białko — średnia tygodniowa" bar chart appears under the weekly-volume bars. With no nutrition data, the trends/bars degrade to the existing "za mało danych" fallbacks without errors.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: add protein/kcal trends + weekly protein bars to progress tab"
```

---

## Task 8: Close the loop — priorities rules + Silnik Dnia fuel flag

**Files:**
- Modify: `index.html` — `priorities(rows)` (lines 568-597); readiness/session assembly feeding the `f.why` render (line 750).

**Interfaces:**
- Consumes: `fuelTargets()`, `mean`, `nz`, the candidate array `C` in `priorities`, and the `f.why` string used in the Silnik Dnia render (line 750).

- [ ] **Step 1: Add nutrition candidates to `priorities()`**

Inside `priorities(rows)`, before the `C.sort(...)` at line 594, add:
```javascript
  const _tg=fuelTargets();
  if(_tg){
    const prot7=mean(rows.map(r=>r.bialko).filter(x=>x!=null&&!isNaN(x)).slice(-7));
    if(prot7!=null && prot7 < _tg.proteinG*0.85)
      C.push({key:"protein",icon:"🥩",title:"Dobij białko",note:`Śr. 7 dni ${Math.round(prot7)} g < cel ${_tg.proteinG} g — białko chroni mięśnie w redukcji.`,weight:7});
    const kcal3=rows.map(r=>r.kcal_spozyte).filter(x=>x!=null&&!isNaN(x)).slice(-3);
    if(kcal3.length===3 && kcal3.every(v=>v<_tg.kcalFloor))
      C.push({key:"deficit",icon:"⚠️",title:"Za duży deficyt",note:`3 dni poniżej ${_tg.kcalFloor} kcal — chronisz mięśnie, dodaj jedzenia.`,weight:8});
  }
```

- [ ] **Step 2: Compute a fuel flag for Silnik Dnia**

Locate where the day-focus object `f` is assembled (the object whose `.why` renders at line 750; it is built in `render()` from `readiness(rows)` + session). Immediately before that object is turned into HTML, compute a fuel-flag string and append it to the `why` text:
```javascript
  // paliwo: flaga bialka pod celem (nie zmienia wyniku gotowosci, tylko informuje)
  const _ftg=fuelTargets();
  if(_ftg && gar && gar.rows){
    const _p7=mean(gar.rows.map(r=>r.bialko).filter(x=>x!=null&&!isNaN(x)).slice(-7));
    if(_p7!=null && _p7 < _ftg.proteinG*0.9){
      f.why = (f.why?f.why+" · ":"") + `paliwo: białko ${Math.round(_p7)}/${_ftg.proteinG} g`;
    }
  }
```
(Readiness `score`/`zone` are intentionally **not** modified — the flag only annotates `why`.)

- [ ] **Step 3: Verify in the browser (manual)**

With real data where the 7-day protein average is below target: open the app. Expected: the Silnik Dnia reason line shows an appended `paliwo: białko NN/180 g` note, and the Priorytety Tygodnia list includes `🥩 Dobij białko` (and/or `⚠️ Za duży deficyt` if 3 days below the floor), ranked by weight. With protein at/above target, neither the flag nor the priority appears. Confirm the readiness ring score is unchanged from before this task (score logic untouched).

- [ ] **Step 4: Run the full Python test suite**

Run: `pytest -v`
Expected: all tests from Tasks 2 and 3 PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat: wire nutrition into priorities engine + Silnik Dnia flag"
```

---

## Self-Review

**Spec coverage:**
- Path A server-side pull → Tasks 1, 2, 4. ✓
- Feasibility spike gating → Task 1. ✓
- Store all fields, spotlight protein+kcal → Task 2 (`fitatu` catch-all + core macros), Task 6 (card shows protein/kcal). ✓
- Targets in plan.json per phase → Task 4 (plan.json) + Task 5 (frontend read + fallback). ✓
- Merge into encrypted row before encryption → Task 3 helpers + Task 4 placement before `encrypt_rows`. ✓
- Freshness / day attribution label → Task 6 (`dayLabel`). ✓
- Paliwo card + progress trends → Tasks 6, 7. ✓
- Close the loop (priorities + Silnik Dnia flag; readiness score untouched) → Task 8. ✓
- Fitatu failure never breaks Garmin update → Task 4 try/except. ✓
- Secrets only in Actions → Task 4 workflow env. ✓
- Testing: spike + unit tests + manual card verification → Tasks 1, 2, 3, 8 (pytest), 5-8 (manual). ✓

**Placeholder scan:** The only deliberately spike-dependent values (`LOGIN_URL`, `DIARY_URL`, login payload, `KEY_MAP` paths) are explicitly resolved in Task 1 and isolated to the top of `fitatu.py` — flagged, not hidden. No "TBD"/"handle edge cases"/"similar to" placeholders elsewhere.

**Type consistency:** `NUTRI_KEYS` identical across Tasks 3-4. Row field names (`bialko`, `kcal_spozyte`, `wegle`, `tluszcz`, `blonnik`, `fitatu`) identical across `fitatu.py`, `update_garmin.py`, and all `index.html` reads. `fuelTargets()` shape `{proteinG,kcalTarget,kcalFloor}` consumed identically in Tasks 6 and 8. `trend(label,vals,unit,goodUp,info,color)` signature matches the extracted definition.
