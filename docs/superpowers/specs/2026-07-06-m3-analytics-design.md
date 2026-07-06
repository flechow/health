# Milestone 3 — Smarter analytics on existing data

**Date:** 2026-07-06
**Status:** Design draft, ready for implementation planning
**Part of:** Protokół 116→90 roadmap (M3 of 4: Nutrition → Body composition → **Analytics** → Adherence)

> **Resolved decision (2026-07-06):** Adding the optional **`reps` (+ `rpe`) field** to the
> strength log is **APPROVED.** M3 therefore includes the small logging extension and computes
> a true Epley e1RM + weekly tonnage for the strength-retention analytic (not the tonnage-only
> fallback).
>
> **Resolved decisions (2026-07-06, planning):**
> - **Testing architecture:** the pure math is **extracted into a new `analytics.js`** module
>   (loaded by `index.html`, cached in `sw.js`, dual browser-global / `module.exports`), unit-
>   tested with **`node --test`** (Node v25 available) using the hand-computed cases in Testing.
>   The inline `index.html` code becomes a thin layer calling the tested functions.
> - **Rate thresholds — phase-tuned.** Phase 1 (current, ~116 kg): `fastPct 1.3`, `hardFastPct
>   1.8` (a large male can safely lose faster early). Later phases tighten toward the recomp
>   ceiling: Phase 2 `fastPct 1.0`, `hardFastPct 1.5`. `stallPct 0.1`, `stallWeeks 3` both phases.
> - **Defaults accepted:** `emaAlpha 0.10`, `etaWindowDays 28`, CI `k = 1·SE`, ETA shown as
>   **earliest–expected–latest** and suppressed when the slope CI includes ≥0; **Epley** e1RM,
>   `maxValidReps 12`; weight chart gets an **EMA overlay** (raw as faint reference); EMA uses
>   **elapsed-day** stepping across gaps; exHist **ring buffer 12 → 24**; weekly volume falls
>   back to **prescribed** reps (parsed from the scheme, labelled) when actual reps are absent.

## Goal

Squeeze more decision-grade insight out of data the system already collects — **no new daily
inputs** for the user. Three analytics, all pure client-side functions that plug into the
existing `readiness` / `priorities` / Progress surfaces:

1. **ETA-to-90kg projection** — from a smoothed weight trend, honestly project the date the
   user hits the 90 kg target, with an uncertainty band and the current weekly rate.
2. **Fat-loss-rate guardrail** — turn the same trend slope into a "%bodyweight/week" gauge and
   warn when it is too fast (muscle-loss risk at his size) or stalled; corroborate with kcal
   deficit and, once M2 lands, waist/body-fat to distinguish fat loss from muscle loss.
3. **Strength retention proxy** — estimated-1RM and weekly volume as the "am I keeping muscle
   during the cut?" signal. This one has a **hard data dependency**: reps-per-set are not
   logged today, so a true e1RM is not computable from current data (see §Architecture 3).

The through-line of the whole Protokół is *muscular* 90 kg. M3's job is to make the recomp
visible: weight going down at a *safe* rate, while strength is *retained*.

## Non-goals

- No new daily logging friction for weight, nutrition, or cardio (those pipelines are M1/M2).
- No server-side computation — everything runs in-browser on the already-decrypted rows,
  matching the existing architecture.
- No predictive ML / bodyweight-simulation modelling of calories→weight (Hacker's-Diet-style
  calorie back-calculation is explicitly out; we only fit the observed trend).
- The **one** unavoidable new input is an *optional* per-set reps/RPE capture for strength
  (analytic #3). It is opt-in, additive, and does not touch the Garmin/nutrition pipelines.

## Approach & rejected alternatives

### Weight-trend smoothing — chosen: EMA "trend weight" (α ≈ 0.10)

Bodyweight is dominated by day-to-day water/glycogen/food noise; the honest signal is the
trend, not any single scale reading. The established solution is an **exponential moving
average** — the "trend weight" of John Walker's *The Hacker's Diet* and TrendWeight:

```
trend[0] = weight[0]
trend[i] = trend[i-1] + α · (weight[i] − trend[i-1])     // α ≈ 0.10
```

α = 0.10 corresponds to roughly a 10-day effective smoothing window and is the value both
Hacker's Diet and TrendWeight ship. It is causal (no look-ahead), O(n), trivially testable,
and needs no windowing edge-cases. Gaps (missing days) are handled by iterating over the
*sorted merged weights* we already have (`mergedWeights()`), optionally advancing by real
elapsed days so a 5-day gap doesn't get treated as one step (decision to confirm).

**Rejected:**
- **Simple moving average (e.g. 7-day):** fine for display but lags harder, discards data
  outside the window, and has awkward warm-up/edge behaviour. EMA uses all history and reacts
  faster to a genuine change of slope.
- **Whole-history linear regression:** great for a *rate* over a fixed window, but a single
  straight line over 120+ days badly misfits a curve that flattens as he leans out. We instead
  use regression *on a recent window of the EMA* only for the ETA slope (below).
- **Kalman / LOESS / spline:** more machinery, not more trustworthy on one noisy 1-D series,
  and harder to unit-test. Rejected on the project's "pure/testable" principle.

### ETA projection — chosen: linear regression on a recent EMA window, with a CI band

Fit a least-squares line to the **last N days of the EMA trend** (default N = 28, decision to
confirm) to get slope `m` (kg/day) and intercept. ETA = day when the fitted line crosses 90.
Honesty comes from the **standard error of the slope**: we also project using `m ± k·SE` to
produce an *earliest / expected / latest* date, and we **refuse to show a date** when the slope
is not meaningfully negative (CI includes ≥ 0) — instead we say "trend flat, no reliable ETA."

**Rejected:** projecting from raw weights (noise inflates SE to uselessness); projecting from
the whole-history slope (ignores that recent rate is what matters); a naïve "goal − current) /
(fixed rate)" (hides all uncertainty — the opposite of the honest treatment we want).

### Fat-loss-rate guardrail — chosen: %/week from the EMA slope, thresholds in `plan.json`

Reuse the ETA window's slope: `pctPerWeek = m · 7 / currentTrendWeight · 100`. Compare against
config thresholds and emit a priorities candidate. Corroborate direction-of-loss with nutrition
(kcal vs `kcalFloor`, already wired in M1) and, when M2 exists, waist/body-fat trend.

### Strength retention — chosen: extend logging with optional reps/RPE, then e1RM + volume

Epley `1RM = w·(1 + reps/30)` and Brzycki `1RM = w·36/(37−reps)` **both require weight AND
reps**. The current log stores only `{kg, d}` per exercise — reps are nowhere (schemes like
"3×10" in `plan.json` are *prescriptions*, not logged actuals). Therefore **a true e1RM is not
computable from existing data.** M3 must first make reps capturable. See §Architecture 3 for the
minimal extension and the interim volume-only fallback.

## Architecture

All three live in `index.html` inline JS as **pure functions** taking `rows` (and/or the
strength `log`) and returning plain objects, mirroring `acwrData(rows)` / `priorities(rows)`.
Rendering and priorities wiring are separate, thin layers.

### Shared helper — `trendWeights()` / `weightTrend(rows)`

New pure helper built on the existing `mergedWeights()` (which already merges `r.waga` +
manual `log.weights`, sorted by date):

```
weightTrend()  → [{ k:"YYYY-MM-DD", raw:Number, ema:Number }]   // α from config, default 0.10
weightSlope(window) → { m, b, seM, n, r2 }   // OLS of ema vs day-index over last `window` days
```

`m` is kg/day. `weightSlope` also returns the standard error of the slope (`seM`) and `n` so
callers can gate on sufficiency. Both are O(n), no DOM, no globals beyond reading `gar`/`log`
via the existing accessors — ideal unit-test targets.

---

### Analytic 1 — ETA-to-90kg projection

**Inputs:** `weightTrend()` (EMA series), `weightSlope(N)` (default N = 28 days), goal target
from `plan.json` (`goal.target = 90`), current EMA weight (last trend point).

**Method:**
- `m, seM, n = weightSlope(N)`; `cur = last ema`.
- Guard: require `n ≥ nMin` (default 14 trend points) and `m < 0` with `m + k·seM < 0`
  (default k = 1, i.e. ~68% one-sided confidence the slope is truly downward). Otherwise return
  `{ status:"flat" }` → UI shows "trend płaski — brak wiarygodnej prognozy".
- Days-to-target from a slope `m'`: `days = (cur − 90) / (−m')`.
- Expected date from `m`; **earliest** from the faster plausible slope `m − k·seM`; **latest**
  from the slower `m + k·seM` (clamped: if the slow bound is ≥ 0, latest = "nieokreślony").
- `weeklyRateKg = m · 7`; `weeklyRatePct = weeklyRateKg / cur · 100`.

**Output:**
```
{ status:"ok"|"flat"|"insufficient",
  etaDate, etaEarliest, etaLatest,        // Date | null
  weeklyRateKg, weeklyRatePct, cur, target:90, m, seM, n, r2 }
```

**Renders:** a new **"Prognoza 90 kg"** card in the main (Today) view, near the weight/priorities
area. Shows the expected date big, the earliest–latest range as a muted sub-line ("między …
a …"), current trend weight, and `weeklyRateKg`/`weeklyRatePct`. On the Progress tab, the
existing raw-weight `trend("Waga", …)` line gains an **EMA overlay** (or is switched to plot
`ema` with raw as faint dots) so the smoothing is visible.

**Feeds priorities:** primarily informational; it upgrades the existing generic
`{key:"weight", …}` candidate note to a concrete "tempo … %/tydz., cel ok. <date>" instead of a
static string. No new high-weight rule from ETA alone (rate handling is analytic 2).

---

### Analytic 2 — Fat-loss-rate guardrail

**Inputs:** `weeklyRatePct` from analytic 1 (same slope, single source of truth); last-3-day
kcal vs `kcalFloor` (already computed in `priorities`); **M2 (pending):** waist-circumference
and `body_fat` trend slope.

**Method — classify the rate band (thresholds from `plan.json`, see below):**
- `pct = |weeklyRatePct|` on a *losing* trend (`m < 0`).
- `pct > fastPct` → **too fast** (muscle-loss risk). Evidence: for muscle-preserving
  recomposition the commonly cited safe ceiling is ~0.5–0.75 %BW/week; a large male can lose
  faster early, so this is a *caution*, not an alarm. Default `fastPct = 1.0` (conservative-ish
  for his current size), with `hardFastPct = 1.5` for a stronger warning — decisions to confirm.
- trend not downward or `pct < stallPct` sustained over `stallWeeks` (default `stallPct = 0.1`,
  `stallWeeks = 3`) → **stalled**.
- else → **on track** (no candidate).

**Fat-vs-muscle corroboration (makes the warning smarter):**
- **kcal:** if "too fast" *and* kcal are also below `kcalFloor` (the M1 deficit signal) → high
  confidence this is over-restriction; strengthen the note.
- **M2 (dependency):** if waist/`body_fat` are dropping in step with weight → reassure ("spadek
  z tłuszczu, trzymaj"). If weight is dropping fast but waist/body-fat are *flat* → escalate
  ("możliwa utrata mięśni"). Until M2 ships, this branch is skipped and the guardrail runs on
  rate + kcal only, degrading gracefully (same nullable pattern as M1).

**Output:**
```
{ band:"fast"|"hardFast"|"stall"|"ok", pct, corroboration:"kcal"|"m2-fat"|"m2-muscle"|null, note }
```

**Feeds priorities (the primary integration):** add candidates to `priorities(rows)`, weighted
to interleave with the existing recovery/ACWR/protein/deficit rules:
- `hardFast` (+ kcal under floor) → `{key:"rate", icon:"🚨", title:"Hamuj tempo — chronisz mięśnie", weight ≈ 8}`.
- `fast` → `{key:"rate", icon:"⚠️", title:"Za szybkie tempo", weight ≈ 6.5}`.
- `stall` → `{key:"rate", icon:"➖", title:"Waga stoi", note:"…dołóż deficytu/kroków", weight ≈ 5.5}`.
- On track → the existing static `{key:"weight", weight:3}` candidate, but with the live rate in
  its note. (De-dup by `key` already handled by the engine's `seen` set — reuse `key:"weight"`
  vs `key:"rate"` deliberately so a firing guardrail can co-exist with, and outrank, the generic
  tip.)

**Readiness rule (respect M1 principle):** the readiness *score* stays a recovery-truth signal —
**do not** fold weight-rate into it. Instead, surface a **flag line** on the Silnik Dnia card
when the band is `fast`/`hardFast`/`stall` (e.g. "tempo: −1,3%/tydz. — za szybko"), exactly like
M1's nutrition flag line. Annotate, don't distort.

---

### Analytic 3 — Strength retention: e1RM & volume landmarks

**Honest assessment (call-out):** **A true e1RM cannot be computed from current data.** Epley
and Brzycki both need *reps at a load*; `log.exHist[id] = [{kg, d}]` stores load + date only.
The `plan.json` schemes ("3×10", "3×max") are prescriptions, and note fields even *ask* the user
to "zapisz liczbę powtórzeń" — confirming reps are currently lost. So M3 has two parts:

#### 3a — Minimal logging extension (DEPENDENCY — must ship before e1RM)

Extend the per-exercise history entry from `{kg, d}` to optionally carry reps and RPE:

```
log.exHist[id] = [{ kg, d, reps?, rpe? }, …]      // reps, rpe optional & backward-compatible
```

- **Backward compatible:** old entries lack `reps`/`rpe`; e1RM simply isn't computed for them
  (nullable, same posture as every other optional metric). No migration needed beyond the
  existing `migrateStrength()`.
- **UI capture:** `exRow()` already renders a weight `<input>`. Add a small optional **reps**
  field (and an optional RPE chip) next to it. Empty reps → behaves exactly as today (weight-only
  progression, `nextTarget()` untouched). This is the single new *optional* input in all of M3.
- Keep the ring buffer cap (currently last 12 entries) — decision to confirm whether 12 is
  enough history for a strength trend or should grow (e.g. 24).

#### 3b — e1RM + weekly volume (once 3a has data)

**e1RM (per exercise, per session with reps):**
- Default **Epley**: `e1RM = kg · (1 + reps/30)`. Rationale: single smooth formula, best in the
  higher-rep ranges this hypertrophy/technique block actually uses (3×10 ≈ 10 reps); Brzycki
  degrades and even breaks as reps → 37. Offer Brzycki `kg·36/(37−reps)` as an alternative/
  cross-check for low-rep phases (decision to confirm which to default).
- **Validity guard:** only trust e1RM for reps in ~1–12 (accuracy falls off fast ≥15 reps).
  Above that, mark the point "estymacja niepewna" and exclude from the trend slope.
- With a single logged set per exercise/session, use that set. If multiple sets are ever logged,
  use the best (max e1RM) of the session.

**Weekly volume load (works even with partial reps data):**
- `volume = Σ (sets · reps · kg)` per exercise per week. Where reps are missing we can fall back
  to the *prescribed* reps from `plan.json` scheme (parse "3×10" → 30 reps) as an estimate,
  clearly labelled as prescription-based, or skip — decision to confirm. Tonnage trend is a
  robust "training stimulus maintained?" proxy that doesn't need failure-set reps.

**Output:**
```
strengthRetention(log, plan) → {
  perExercise:[{ id, name, e1rmSeries:[{d, e1rm}]|null, e1rmDelta, volSeries:[{week, vol}], volDelta }],
  overall:{ e1rmTrend:"up"|"flat"|"down"|null, volTrend, dataQuality:"reps"|"weight-only" }
}
```

**Renders:** extend the existing **"Siła — progresja"** card on the Progress tab. Today it sparklines
raw `kg`; add (when reps exist) an **e1RM sparkline** per exercise and a **weekly tonnage** bar
chart (reuse `bars()`), plus an overall "utrzymujesz siłę ✅ / siła spada ⚠️" headline. When no
reps are logged yet, the card is unchanged (weight-only) with a one-line nudge: "zapisuj powtórzenia,
by widzieć e1RM".

**Feeds priorities:** if e1RM/tonnage trend is **down** during an active cut (weight also
falling) → this is the muscle-loss red flag the whole Protokół cares about:
`{key:"strength", icon:"💪", title:"Siła spada w redukcji", note:"utrzymaj ciężary / dołóż białka", weight ≈ 7.5}`.
This *replaces* (same `key:"strength"`) the existing static weight-4 "Nie odpuszczaj siły" tip
when real retention data says there's a problem, and outranks it. If trend is flat/up → keep the
gentle static tip.

## Data-model / config changes

### `plan.json` — new `analytics` block (per-phase or top-level; recommend per-phase)

```json
"analytics": {
  "emaAlpha": 0.10,
  "etaWindowDays": 28,
  "rate": { "fastPct": 1.0, "hardFastPct": 1.5, "stallPct": 0.1, "stallWeeks": 3 },
  "e1rm": { "formula": "epley", "maxValidReps": 12 }
}
```

Thresholds live in config so they can be tuned per phase (early aggressive cut vs. later
maintenance) exactly like the existing `nutrition` block. Missing block → sane hard-coded
defaults, everything degrades gracefully.

### `fit-log-v1` — additive `reps?`/`rpe?` on exHist entries

Described in §3a. No schema version bump needed; optionality is the compatibility strategy.

## UI summary

- **Today view:** new **"Prognoza 90 kg"** card (ETA + range + weekly rate). Silnik Dnia gains a
  weight-rate **flag line** (annotate-only). Priorities card automatically reflects new candidates.
- **Progress tab:** weight trend shows the **EMA** (raw as faint reference); **"Siła — progresja"**
  card gains e1RM sparkline + weekly tonnage bars + a retention headline.
- All new cards reuse existing components: `spark()`, `bars()`, `ic()`/`ib()` tap-to-explain
  bottom sheets (add info entries: `eta`, `rate`, `e1rm`, `tonnage`), and the card/label styling.

## Error / empty-state handling

- **< ~14 trend points / early days:** ETA returns `insufficient` → card shows "Za mało danych na
  prognozę (zbieram trend)". Guardrail stays silent. (Consistent with `acwrData` returning `null`
  when `rows.length<21`.)
- **Flat / noisy trend:** slope CI includes 0 → ETA shows "trend płaski — brak wiarygodnej
  prognozy" rather than a fake date. This is the core honesty requirement.
- **Weight going up:** ETA to 90 is undefined downward → show "trend rosnący" + the guardrail's
  `stall`/reverse messaging; never render a negative/absurd date.
- **Gaps in weigh-ins:** EMA iterates over sorted merged weights; large gaps handled by (decision)
  either treating each recorded point as one step or scaling α by elapsed days.
- **No reps logged (default state at M3 launch):** e1RM absent everywhere; strength card unchanged;
  volume falls back to prescription-based tonnage only if enabled, else hidden. No errors.
- **M2 not yet shipped:** guardrail's fat-vs-muscle branch simply not evaluated; runs on rate +
  kcal. No dependency failure.
- **Nulls throughout:** reuse existing `nz`/`mean`/`baseField` null-skipping patterns.

## Testing approach

All core logic is pure functions → unit tests against fixture rows/log, mirroring the M1 test
suite in `tests/`.

**`weightTrend` / EMA:**
- Constant weight in → EMA converges to that constant (all points equal). 
- Single step change → EMA approaches new level geometrically; assert value after k steps ≈
  `new − (new−old)·(1−α)^k`.
- Known small series with α=0.1 → assert against hand-computed expected trend.

**`weightSlope` / ETA:**
- Perfect linear decline (e.g. −0.15 kg/day, no noise) → `m ≈ −0.15`, `seM ≈ 0`, ETA date matches
  `(cur−90)/0.15` days out; earliest≈expected≈latest.
- Noisy decline → expected date sane, earliest < expected < latest, all future.
- Flat series → `status:"flat"`, no date.
- Rising series → not "ok", no bogus date.
- Fewer than `nMin` points → `insufficient`.

**Guardrail:**
- Slope = −0.75%/wk → `ok`; −1.2%/wk → `fast`; −1.8%/wk → `hardFast`; ≈0 for 3 wk → `stall`.
- `fast` + kcal all 3 days < floor → corroboration `"kcal"`, higher-weight candidate fires.
- Priorities: assert the `rate` candidate appears, is de-duped, and out-ranks the static
  `weight` tip; assert it does *not* false-fire on sparse (< window) data.

**e1RM / volume:**
- Epley: 100 kg × 5 reps → 116.7; ×1 rep → 100. Brzycki: 100×5 → 112.5. (Hand-checked.)
- reps ≥ maxValidReps → point flagged/excluded from trend.
- Missing reps entry → e1RM null, weight-only path unaffected, `dataQuality:"weight-only"`.
- Volume: two weeks of sets → tonnage delta sign correct; prescription-fallback parses "3×10"→30.
- Retention→priorities: declining e1RM during falling weight fires the "siła spada" candidate.

**Manual verification:** cards render with real decrypted data; EMA overlay visually tracks the
scale cloud; ETA range is plausible against eyeballed trend.

## Decisions to confirm

1. **[Strength — the big one] Reps logging for e1RM.** Confirm we add the optional `reps`(+`rpe`)
   field to `exHist` / `exRow()`. Without it, **e1RM is impossible** and analytic 3 ships as
   *volume/tonnage-only* (and even tonnage needs reps unless we fall back to prescribed schemes).
   Is the extra per-exercise field acceptable given the "no new inputs" spirit (it's optional and
   additive), or do we defer e1RM to M4 and ship only weight-trend tonnage in M3?
2. **Rate thresholds & smoothing constants.** Confirm defaults: `emaAlpha = 0.10`,
   `etaWindowDays = 28`, `fastPct = 1.0`, `hardFastPct = 1.5`, `stallPct = 0.1 %/wk over 3 wk`,
   confidence `k = 1·SE`. At 116 kg a large male can safely lose faster than the 0.5–0.75 %/wk
   recomp ceiling early on — is 1.0 %/wk the right "caution" line, or should it start looser and
   tighten by phase via `plan.json`?
3. **ETA presentation & gap handling.** Confirm we show an **earliest–expected–latest** range
   (not a single false-precision date) and suppress the date entirely when the slope CI includes
   zero. Also confirm EMA gap handling (one-step-per-reading vs. elapsed-day scaling of α) and
   whether the Progress weight chart switches to EMA with raw dots, or overlays both.

### Also to confirm (lower stakes)
- e1RM default formula: **Epley** (recommended for the 8–12-rep blocks) vs Brzycki for low-rep
  phases — or pick per-phase from config.
- Volume fallback to *prescribed* reps when actuals are missing (labelled) vs. showing volume
  only when reps are real.
- exHist ring-buffer size (currently 12) — grow to ~24 for a longer strength trend?

## Dependencies on other milestones

- **M1 (done):** kcal/`kcalFloor` deficit signal — consumed by the guardrail's corroboration.
- **M2 (pending):** `body_fat`, `muscle_kg`, waist circumference — consumed by the guardrail to
  distinguish *fat* loss from *muscle* loss and to reassure/escalate. **M3 must run without it**
  and light up that branch when M2 rows appear (nullable, graceful).
- **M4 (adherence):** may consume the strength-retention and rate signals for streaks/scoring.

## Sources

Weight-trend smoothing (EMA / "trend weight"):
- The Hacker's Diet — Signal and Noise / Moving Averages, John Walker: https://www.fourmilab.ch/hackdiet/e4/signalnoise.html
- TrendWeight — The Math Behind TrendWeight: https://trendweight.com/math
- TrendWeight — Help/FAQ: https://trendweight.com/help/

Safe rate of loss preserving muscle:
- Precision Nutrition — Realistic rates of fat loss and muscle gain: https://www.precisionnutrition.com/rates-of-fat-loss-and-muscle-gain
- Verreijen et al., high-protein + resistance exercise preserves fat-free mass during weight loss (RCT): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5294725/
- Harvard Health — healthy, realistic rate of weight loss: https://www.health.harvard.edu/weight-loss/what-does-a-healthy-realistic-rate-of-weight-loss-look-like-and-why-does-it-matter

Estimated 1RM formulas & inputs:
- Wikipedia — One-repetition maximum (Epley, Brzycki formulas): https://en.wikipedia.org/wiki/One-repetition_maximum
- Arvo — Epley & Brzycki formulas explained: https://arvo.guru/resources/one-rep-max-formulas
