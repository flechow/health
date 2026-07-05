# Milestone 1 — Nutrition tracking via Fitatu

**Date:** 2026-07-05
**Status:** Approved design, ready for implementation planning
**Part of:** Protokół 116→90 roadmap (M1 of 4: Nutrition → Body composition → Analytics → Adherence)

## Goal

The Protokół target is not "90 kg" but **muscular 90 kg** — a body-recomposition goal.
The two biggest levers for recomposition are **protein intake** and **calorie balance**,
and neither is currently tracked anywhere in the system. The user already logs every meal
in **Fitatu**, so this milestone pulls those numbers into Protokół automatically (zero new
daily friction) and wires them into the existing readiness and weekly-priorities engines.

## Non-goals

- No in-app food logging / food database (Fitatu remains the logging surface).
- No changes to how Fitatu itself is used.
- Body-composition, ETA projection, and deficit-rate guardrails from weight trend are
  **later milestones** (M2/M3) — this milestone only ships a simple `kcalFloor` guard.

## Integration approach — Path A (server-side pull)

Fitatu has **no official public API**. The chosen path mirrors the existing Garmin pattern:
a reverse-engineered, server-side pull running inside GitHub Actions.

Rationale: `update_garmin.py` already depends on an unofficial library (`garminconnect`)
with a stored credential secret. A reverse-engineered Fitatu pull is the *same class of
risk the system already accepts daily*, and reuses the existing sync layer.

Rejected alternatives:
- **Path B (Apple Health / Health Connect bridge):** officially supported by Fitatu, but the
  pipeline is server-side and Health data is on-device — needs an iOS Shortcut posting to the
  worker. More moving parts, not set-and-forget.
- **Path C (manual GDPR export/import):** no creds, no ToS concern, but manual = the friction
  this milestone exists to remove.

### Feasibility spike (gating first task)

Before building anything, a throwaway script must confirm:
1. Login with `FITATU_EMAIL` / `FITATU_PASSWORD` succeeds.
2. A daily-nutrition summary (protein, kcal, macros) can be fetched for a given date.
3. The shape of the returned JSON.

If the spike fails, stop and fall back to Path B or C — no downstream work is wasted.
The unofficial [`fitatu-sdk`](https://github.com/Capure/fitatu-sdk) (TypeScript, `login()` +
`getDietAndActivityPlan()`) is a reference for endpoint discovery only; it is a 2-commit,
likely-abandoned repo, so the endpoints are reimplemented in Python (`requests`) to match
the existing stack.

## Architecture

### Components

**`fitatu.py`** (new helper module)
- `login(email, password) -> session` — authenticate, return a reusable session/token.
- `fetch_nutrition(session, date) -> dict | None` — return one day's totals, or `None` if
  the day has no data. Returns all fields Fitatu exposes.
- Pure fetch/parse; no encryption or file I/O of its own.

**`update_garmin.py`** (modified)
- During per-day row construction, calls `fitatu.fetch_nutrition(session, date)` and merges
  the result into that date's row **before** the existing AES-GCM encryption + commit step.
- One login per run, reused across days. Failure to reach Fitatu must **not** break the
  Garmin update — nutrition fields are simply omitted for affected days (same defensive
  posture as `send_briefing.py`).

**Secrets** (GitHub Actions): `FITATU_EMAIL`, `FITATU_PASSWORD`. Never sent to the frontend.

### Data model

Nutrition rides **inside the existing encrypted row** (no new plaintext exposure). Flat
fields for the key macros, plus a nested catch-all for everything else:

```json
"bialko": 172,
"kcal_spozyte": 2080,
"wegle": 190,
"tluszcz": 68,
"blonnik": 28,
"fitatu": { "...": "any other fields Fitatu returns, stored verbatim" }
```

All fields are nullable — days before Fitatu integration, or days with no logging, simply
lack these keys (consistent with existing nullable metrics like `vo2max`).

### Targets (`plan.json`)

Each phase gains a `nutrition` block, edited like the rest of the plan:

```json
"nutrition": { "proteinG": 180, "kcalTarget": 2200, "kcalFloor": 1850 }
```

- `proteinG`: 180 (≈ 2 g/kg of the 90 kg target weight) — muscle-protection floor.
- `kcalTarget`: 2200 — the intended daily intake for the phase.
- `kcalFloor`: 1850 — the "do not under-eat" line that protects muscle in the deficit.

Phase 2's `nutrition` block is sketched/adjustable, matching how Phase 2 is already a sketch.

### Freshness / day attribution

- Nutrition attaches to each date row naturally.
- **05:00 UTC cron** captures yesterday's complete day (and today's near-empty running total).
- The **"Odśwież"** button pulls today's running total mid-day.
- The Paliwo card labels whether it is showing **today (live, partial)** or the **last
  complete day**, so a partial "today" is never mistaken for a missed target.

## UI

**New "Paliwo" (Fuel) card** near the Regeneracja section:
- **Białko** — actual vs. `proteinG` cel, plus 7-day average.
- **Kcal** — actual vs. `kcalTarget`, plus a deficit indicator relative to target.
- Protein 7-day sparkline.
- Day label (today-live vs. last-complete).
- Tap-to-explain bottom sheet, consistent with existing KPI cards.

**Progress tab additions:**
- Protein and kcal trend lines alongside the existing weight / HRV / VO₂max trends.
- Weekly-average protein bars next to the existing weekly-volume (intense minutes) chart.

## Closing the loop (readiness + priorities)

**Priorities engine** gains two rules (weighted into the existing 1–3 priority selection):
- 7-day average protein < ~85% of `proteinG` → **`🥩 Dobij białko`** (high weight).
- `kcal_spozyte` below `kcalFloor` for 3+ consecutive days → **`⚠️ Za duży deficyt —
  chronisz mięśnie`** (high weight).

**Readiness score:** the core formula stays **recovery-driven and unchanged** (it must remain
a recovery-truth signal). Instead, the **Silnik Dnia** card surfaces a nutrition *flag line*
(e.g. "paliwo: białko poniżej celu") when protein is under target. A severe-underfuel score
penalty is intentionally left **off by default** — surface the signal, do not punish it.

## Error handling

- Fitatu unreachable / login fails → log and continue; omit nutrition for the run. Garmin
  update and commit proceed normally.
- Day with no Fitatu data → row simply lacks nutrition keys; card shows "brak danych" for
  that day and the 7-day averages skip nulls (existing `_avg` pattern).
- Missing `nutrition` block in a phase → card and priority rules degrade gracefully (no
  targets shown, protein/deficit rules skipped).

## Testing

1. **Feasibility spike** — manual confirmation of login + one day's fetch (gates everything).
2. **Unit tests** against fixture rows:
   - Nutrition merge into a date row (present / absent / partial-day cases).
   - Target math (actual vs. target, 7-day averages skipping nulls).
   - Both priority rules (protein < 85%, deficit < floor for 3+ days) fire and don't
     false-fire on sparse data.
3. **Manual verification** — Paliwo card and Progress-tab additions render correctly with
   real decrypted data.

## Security

- `FITATU_EMAIL` / `FITATU_PASSWORD` stored only as GitHub Actions secrets; never reach the
  frontend (same as Garmin creds today).
- Nutrition fields ride inside the existing AES-256-GCM encrypted blob — **no new plaintext
  data at rest** and no new decryption surface in the browser.

## Rollout / dependencies

This milestone produces a new daily data stream (protein, kcal, macros) that later
milestones consume:
- **M3 (Analytics)** uses `kcal_spozyte` + weight trend for the fat-loss-rate guardrail.
- **M4 (Adherence)** uses protein-target hits for a nutrition streak.
