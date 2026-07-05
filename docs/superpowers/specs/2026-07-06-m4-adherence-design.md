# Milestone 4 — Adherence & motivation layer

**Date:** 2026-07-06
**Status:** Draft design, ready for implementation planning
**Part of:** Protokół 116→90 roadmap (M4 of 4: Nutrition → Body composition → Analytics → **Adherence**)

## Goal

Milestones 1–3 gave the Protokół the *data* to know whether the user is on track. M4 is
about **keeping a solo user consistent across an 18-week+ protocol** — the phase where most
body-recomposition attempts quietly die, not from bad programming but from lost momentum.

M4 adds three things, all built **on top of existing surfaces** (daily rows, training log,
priorities engine, morning push):

1. **Habit streaks** — lightweight, forgiving "am I stringing good days together?" signals
   for the four behaviours that actually move a recomp: protein, steps, sleep, training.
2. **Weekly check-in** — the motivational centerpiece. A once-a-week roll-up (weight Δ,
   waist/body-fat Δ, avg protein, sessions done vs planned, HRV/sleep trend, streak status)
   rendered as a card and pushed on Sunday. This is where the user *sees the arc of progress*,
   not just today's number.
3. **Reminders** — weekly measurement/photo nudges (tied to M2), delivered through the
   **existing** push briefing, not a new channel.

Design principle throughout: **surface signal, forgive slips, celebrate the trend.** The
research (below) is unambiguous that rigid "don't break the chain" streaks *increase*
abandonment when life inevitably interrupts. We build forgiving streaks or we don't build them.

## Non-goals

- **No social / sharing / leaderboard features.** Single-user app; community-motivation
  findings don't apply.
- **No new notification channel.** Everything push-borne rides `send_briefing.py` + the
  existing VAPID subscriptions. No email, no SMS, no second worker.
- **No gamified badges/points/levels economy.** YAGNI for one motivated adult; a streak count
  and a weekly card are enough. (Rejected explicitly below.)
- **No new encrypted data stream.** Streaks are *derived* from data M1–M3 already produce.
  Nothing new gets written into the encrypted daily rows.
- **No configurable per-habit reminder scheduler / quiet hours UI.** One weekly cadence,
  hardcoded to Sunday, is enough.
- **No streak history / calendar heatmap.** Current streak + best streak is the whole surface.

## Research grounding

**Streaks motivate but backfire when rigid.** Streaks exploit loss aversion
(Kahneman/Tversky) and a dopamine reward loop — effective, but double-edged. The failure mode
is the **abstinence violation effect**: after one or two missed days a rigid all-or-nothing
tracker makes users redefine themselves as "someone who doesn't do this," and they abandon the
habit entirely. Flexible systems (grace days, streak freeze, milestone preservation, or
counting *total* completions rather than *consecutive* days) sharply reduce this. Notably,
~80% adherence produces nearly identical long-term results to 100% while being far more
sustainable psychologically, and **automaticity, not an unbroken chain, is the real marker of
habit formation.** ([Cohorty](https://blog.cohorty.app/the-psychology-of-streaks-why-they-work-and-when-they-backfire/),
[WorkBrighter](https://workbrighter.co/habit-streak-paradox/),
[MooreMomentum](https://mooremomentum.com/blog/why-most-habit-streaks-fail-and-how-to-build-ones-that-dont/),
[Yu-kai Chou](https://yukaichou.com/gamification-analysis/streak-design-gamification-motivation-burnout/),
[Klarity — why rigid streaks fail ADHD users](https://www.helloklarity.com/post/breaking-the-chain-why-streak-features-fail-adhd-users-and-how-to-design-better-alternatives/))

**What makes a weekly fitness check-in work:** anticipated accountability (knowing a review is
coming), celebrating **small wins**, personalized feedback that raises self-efficacy, and a
**trend-focused** framing ("consistency over time," not single-day judgement). Tracking should
"feel empowering, not discouraging." ([NASM](https://blog.nasm.org/fitness/fitness-evaluations-keeping-goals-on-track),
[Mindbody](https://www.mindbodyonline.com/business/education/blog/how-use-progress-tracking-increase-retention-and-motivate-clients),
[Frontiers — fitness tech & behavior change](https://www.frontiersin.org/journals/public-health/articles/10.3389/fpubh.2016.00289/full),
[ACE Fitness](https://www.acefitness.org/blog/3808/motivation-behavior-change-and-program-adherence))

These directly shape the decisions below: **forgiving streaks** (weekly-tolerance model, not
consecutive-day), and a **trend-first, win-celebrating** weekly card that arrives on a
predictable cadence.

## Approach & rejected alternatives

### Chosen approach

- **Streaks are computed on-the-fly, in the browser, from data already present** (decrypted
  daily rows + `log.days`). No new persisted state that can desync — matching the existing
  house rule ("derive from existing data where possible"). The only optional new persistence
  is a *best-streak high-water mark* (see Data model), because "best ever" cannot be derived
  from a rolling window once old data ages out.
- **Streaks use a weekly-tolerance ("grace") model, not a consecutive-day chain.** A streak
  counts **weeks in which the habit was hit on ≥ N of its eligible days**, not unbroken days.
  This is the research-backed forgiving model and it fits the app's existing *weekly* mental
  model (weekly priorities, weekly training checklist, "Ten tydzień" card).
- **The weekly check-in is a pure aggregation** over M1/M2/M3 fields already on the rows,
  rendered as a card in the "Dziś"/"Postępy" tabs and mirrored into the Sunday push.
- **Reminders extend `build_message()` in `send_briefing.py`** by branching on day-of-week.
  Sunday → check-in briefing; a configurable weekday → measurement/photo nudge. Fail-safe:
  wrapped in the same try/except that already guarantees the workflow never breaks.

### Rejected alternatives

- **Consecutive-day "don't break the chain" streaks.** Rejected on the research: highest
  abandonment risk, worst fit for a long protocol with travel/illness/rest days. A single
  sick day shouldn't nuke a 6-week streak.
- **Streak-freeze tokens / earned grace-day economy (Duolingo-style).** Rejected as
  over-engineered for one user (YAGNI). The weekly-tolerance model *is* the grace mechanism,
  with no token accounting to build or store.
- **Badges / points / levels.** Rejected: motivational value for a self-directed adult is low
  vs. build cost, and it clutters a deliberately clean UI. Best-streak high-water mark gives
  the one "personal best" hook that research says matters, at near-zero cost.
- **A separate reminders worker / cron.** Rejected: violates the "extend the existing push"
  constraint and adds a second failure surface. Everything folds into the one daily job.
- **Persisting computed streak counters to localStorage each render.** Rejected: redundant
  derivable state that can desync from the rows; recomputed cheaply on every render instead.

## Architecture

### 1. Streak computation (frontend, derived)

Four habits, each defined as a **per-day boolean predicate** over a date's available data,
plus an **eligibility** predicate (was this day *supposed* to count?). Streaks then aggregate
**by ISO week (Mon–Sun, reusing the existing `monday()`/`key()` helpers)**.

| Habit | "Hit" predicate (per day) | Eligible days | Source |
|---|---|---|---|
| 🥩 Białko | `row.bialko >= fuelTargets().proteinG` | days with any `bialko` logged (M1) | encrypted row |
| 🚶 Kroki | `row.kroki >= stepGoal` | every day with a `kroki` value | encrypted row + `plan.json` goal |
| 😴 Sen | `row.sen >= sleepGoal` | every day with a `sen` value | encrypted row + `plan.json` goal |
| 💪 Trening | `log.days[date].trained === true` | days where `plan` schedules a non-rest session | `fit-log-v1` + `plan.json` |

**Weekly-tolerance rule (the forgiving core).** For each completed week, a habit is a
**"good week"** if `hits >= ceil(eligibleDays * threshold)`, where `threshold` defaults to
**0.8** (the 80% research figure). Special case for training: `eligibleDays` = number of
scheduled training days that week (typically 2), and the good-week rule is
`trainedSessions >= scheduledSessions - 1` (miss at most one). The **streak** is the count of
consecutive good weeks up to and including the most recent *completed* week. The **current
(in-progress) week never breaks a streak** — it's shown as "in progress: 3/4 dni" so a bad
Monday can't induce all-or-nothing abandonment mid-week.

**Empty/sparse handling.** A week with *zero* eligible days for a habit (e.g. no protein
logged all week, or a deload week with no scheduled training) is **neutral** — it neither
extends nor breaks the streak (the streak "bridges" it). This prevents a data-gap or a
legitimately programmed rest week from reading as failure. A habit with no eligible days in
the entire window renders as "—" (not applicable), same posture as M1's "brak danych".

**Function shape** (mirrors `priorities(rows)`):

```
streaks(rows, log, plan) -> [
  { key:'protein', icon:'🥩', label:'Białko',  current:5, best:8, thisWeek:{hits:5,elig:6},  note:'5 tygodni z rzędu' },
  { key:'steps',   icon:'🚶', label:'Kroki',   current:2, best:4, thisWeek:{hits:3,elig:5},  note:'...' },
  { key:'sleep',   icon:'😴', label:'Sen',     current:0, best:3, thisWeek:{hits:2,elig:6},  note:'...' },
  { key:'training',icon:'💪', label:'Trening', current:6, best:6, thisWeek:{done:1,plan:2}, note:'6 tygodni — świetnie' }
]
```

- Pure, no side effects, testable against fixture rows + a fixture `log`.
- `best` is `max(computed-from-window, storedBest)` so it survives data aging out (see Data model).
- Reuses existing helpers: `monday()`, `key()`, the `nz`/filter idioms, `fuelTargets()`,
  `activePhase()`, and the plan's `days` map for scheduled-training detection.

### 2. Weekly check-in (frontend card + push)

A single builder, `weeklyCheckin(rows, log, plan)`, produces a plain data object consumed by
both the card renderer and (conceptually mirrored by) the Python briefing. It aggregates the
**last complete Mon–Sun week vs. the prior week**:

| Line | Value | Source | Degrades if… |
|---|---|---|---|
| Waga Δ | this-week avg weight − last-week avg (trend, not single day) | rows `waga` + `log.weights` (manual override, existing merge) | always available |
| Talia / tłuszcz Δ | waist (`circumference`) Δ, `body_fat` Δ | rows (M2) | **M2 absent → line omitted** |
| Białko śr. | 7-day mean protein vs `proteinG` | rows `bialko` (M1) | **M1 absent → line omitted** |
| Treningi | `done / planned` this week | `log.days` + plan schedule | always available |
| Sen / HRV trend | 7-day mean + arrow vs prior week | rows `sen`, `hrv` | always available |
| Serie | 1-line streak status ("Białko 5 tyg · Trening 6 tyg") | `streaks()` | streak "—" if no data |
| Win line | single celebratory highlight (biggest positive Δ or longest streak) | derived | falls back to neutral encouragement |

The **"win line"** is deliberate (research: celebrate small wins). It picks the single most
positive fact of the week — biggest fat/weight drop, a new best streak, or "wszystkie
treningi zaliczone" — and states it first, so the card *opens on a win* even in a mediocre week.

Framing is **trend-first**: every delta is a 7-day average vs. the prior 7-day average, never
a single-day comparison, matching both the research and the app's existing "patrz na trend,
nie na pojedynczy dzień" language.

### 3. Reminders & weekly-summary push (extends `send_briefing.py`)

`send_briefing.py` already: decrypts rows, computes readiness, reads today's session, and
sends `{title, body, url}` per subscription — all inside a top-level try/except that forces
`exit 0` so the workflow never breaks. M4 adds a **day-of-week branch in `build_message()`**:

- **Sunday (`date.today().isoweekday() == 7`)** → return a **weekly check-in** message instead
  of (or appended after) the normal readiness line. Body is a compact Polish roll-up computed
  by a new `weekly_summary(rows)` helper in the same file (Python mirror of the JS aggregation
  — weight Δ, protein avg, sessions done vs planned from… see decision below on training data,
  sleep/HRV trend, top streak). Title e.g. `📊 Podsumowanie tygodnia · Protokół`.
- **Configured measurement day (default Saturday morning)** → append/emit a **measurement +
  photo reminder** nudge: `⚖️ Dziś pomiary: waga na czczo, talia, zdjęcie sylwetki.` This ties
  to M2's body-composition inputs.
- **All other days** → unchanged morning readiness briefing.

New helpers are additive and wrapped defensively: any exception inside `weekly_summary` falls
back to the normal readiness message (never raises). The reminder text is static; it does not
require decryption, so it works even if data is unavailable.

**Training-data caveat (important):** `log.days` (training completion) lives in browser
localStorage and is **not available server-side**. So the push weekly-summary's
"sessions done vs planned" cannot be computed in Python from `log.days`. Options in Decisions
to confirm — recommended: the push shows *planned* sessions from `plan.json` and a
proxy for "done" derived from `min_intensywne`/strength-day activity on the rows (or omits the
done-count and shows only planned + a "otwórz apkę po pełne podsumowanie" deep-link). The
**full** sessions-done figure lives in the in-app card, which has `log.days`.

## Data model

**Nothing new in the encrypted rows. Nothing new server-side persisted.**

Streaks and the weekly card are recomputed on every render from existing data. The **only**
new persistent state is a best-streak high-water mark, needed because the rolling row window
eventually ages out the data that produced a past best. New localStorage key following the
existing `save()/load()` pattern (not co-mingled into `fit-log-v1`, to keep the training log
clean):

```js
// fit-adh-v1
{
  bestStreak: { protein:8, steps:4, sleep:3, training:6 },   // weeks, high-water mark only
  lastCheckinSeen: "2026-07-05"                              // ISO date of last weekly card dismissed/seen (optional, for a subtle "nowe podsumowanie" badge)
}
```

- `bestStreak[key]` updated on render as `max(stored, currentComputed)`; monotonic, never decremented.
- If the key is absent/corrupt, `load('fit-adh-v1', {bestStreak:{}})` degrades to computing
  best from the window only — no crash, consistent with existing `load` defaults.
- `lastCheckinSeen` is optional polish (a small "new" dot on Sunday's card); cut under YAGNI if
  it complicates the render.

**`plan.json` additions — habit goals.** The plan currently has `nutrition.proteinG` (reused
directly) but **no explicit step or sleep goal**. Add a per-phase `habits` block, edited like
the rest of the plan:

```json
"habits": { "stepGoal": 8000, "sleepGoalH": 7.0, "trainingToleranceMissed": 1, "weekThreshold": 0.8 }
```

- `stepGoal` 8000 (matches the app's existing "celuj w 7–8k" priority copy).
- `sleepGoalH` 7.0 (existing sleep-scoring midpoint is ~6.5–7.8h).
- `trainingToleranceMissed` 1, `weekThreshold` 0.8 surfaced here so the forgiving parameters
  are tunable per phase without code changes.
- Missing `habits` block → sensible hardcoded defaults (8000 / 7.0 / 1 / 0.8); streaks still work.

## UI

Streaks and the check-in fit the **existing tabs**; no new tab.

**"Dziś" tab — new "Serie" card** (placed after `prioritiesCard()`, before or merged with the
"Ten tydzień" checklist, since both are weekly-cadence):
- A compact row per habit: icon, label, **current streak** ("5 tyg"), a subtle best marker
  ("rekord 8"), and an **in-progress bar for the current week** ("3/4 dni w tym tygodniu").
- Forgiving copy: a broken streak shows encouragement, never a scolding — e.g.
  `Sen: nowy start · w tym tygodniu 2/6`. No red "STREAK LOST" styling.
- `data-info="serie"` explain-sheet describing the 80%/weekly-tolerance rule so the user
  understands *why* one bad day didn't break it (this transparency is itself motivational).

**"Dziś" tab — weekly check-in card (Sundays / on-demand):**
- Prominent card at the top of "Dziś" on Sundays (and always reachable). Opens with the **win
  line**, then the delta lines (weight, waist/fat if M2, protein if M1, sessions, sleep/HRV),
  then the streak summary row.
- Reuses existing arrow/trend styling (`arr()`), sparkline (`spark()`), and metric-card layout.

**"Postępy" tab:**
- The check-in's deltas already overlap existing trend charts; add a small **"best streak"**
  annotation or a streak-weeks mini-row alongside the weekly-volume/protein bars, so the
  progress tab tells the *adherence* story next to the *physiology* story. Low priority /
  optional under YAGNI.

**Explain-sheets** (`data-info`) added: `serie`, `checkin` — consistent with every other KPI.

## Push / briefing extension design

```
build_message(rows):
    dow = date.today().isoweekday()          # 1=Mon .. 7=Sun
    if dow == 7:                             # Sunday: weekly check-in
        try:  return weekly_summary(rows)    # (title, body) roll-up
        except Exception: pass               # fall through to normal briefing
    body_extra = ""
    if dow == MEASURE_DOW (default 6):       # Saturday: measurement/photo nudge
        body_extra = " · ⚖️ dziś pomiary + zdjęcie"
    # ...existing readiness+session message, with body_extra appended...
```

- Single daily job, single push per subscription — **no new channel, no new cron**.
- `url` stays `./` (opens the PWA to the relevant card; optionally `./#checkin` if the app
  gains a hash-route to focus the check-in card — nice-to-have, not required).
- Every new branch is inside the existing top-level try/except → `exit 0`. A malformed row, a
  missing M1/M2 field, or a `weekly_summary` bug can never fail the GitHub Actions workflow.
- Measurement-day and Sunday-summary cadence are constants at the top of the file
  (`MEASURE_DOW`, `CHECKIN_DOW`) — trivially editable, no scheduler.

## Error / empty-state handling

- **No subscriptions / no VAPID:** unchanged — `send_briefing.py` already exits cleanly.
- **M1 absent (no protein):** protein streak → "—"; check-in omits the protein line; step/
  sleep/training streaks unaffected.
- **M2 absent (no body-comp):** check-in omits waist/body-fat lines; weight Δ still shown.
- **Sparse rows / new user (<1–2 complete weeks):** "Serie" card shows "zbieramy dane —
  pierwsze podsumowanie po pełnym tygodniu"; no misleading "0-week streak" as failure.
- **Data gap week (zero eligible days):** treated as **neutral** — streak bridges it, never
  breaks. Explicitly tested.
- **Missing `plan.habits`:** hardcoded defaults; streaks compute normally.
- **Broken/absent `fit-adh-v1`:** `load()` default; best falls back to window-only. No crash.
- **Weekly-summary Python exception:** falls back to the normal readiness briefing.
- **In-progress week:** never counted as a break; shown as progress, per the research.

## Testing approach

- **Unit (JS, mirroring M1's fixture-row tests):**
  - `streaks()` per-habit hit predicates (at/above/below target; null values skipped).
  - Weekly-tolerance aggregation: 80% threshold, training miss-one rule, **neutral bridging of
    zero-eligible weeks**, in-progress week never breaks streak.
  - `best` = max(window, stored); monotonic; survives absent `fit-adh-v1`.
  - `weeklyCheckin()` deltas (trend vs. single-day), M1-absent and M2-absent degradation,
    win-line selection.
- **Unit (Python):** `weekly_summary(rows)` roll-up math and that it **never raises** on
  malformed/empty rows (returns fallback). Day-of-week branch selects the right message.
- **Manual verification:** "Serie" and check-in cards render with real decrypted data;
  trigger the Sunday branch by running `send_briefing.py` with a mocked `date.today()` and
  confirm the push body; confirm the workflow still exits 0 when data/subs are missing.

## Dependencies on M1 / M2 / M3

- **M1 (Nutrition):** protein streak + check-in protein line depend on `bialko` and
  `fuelTargets().proteinG`. Degrade gracefully if M1 not shipped.
- **M2 (Body composition):** check-in waist (`circumference`) / `body_fat` deltas and the
  **measurement/photo reminder** are M2-tied. If M2 absent, those lines/reminders are omitted
  (reminder could still fire for weight-only if desired — see decisions).
- **M3 (Analytics):** no hard dependency. The check-in's trend framing is complementary to
  M3's guardrails; if M3 ships an ETA/deficit-rate figure, the check-in could surface it as an
  extra line (optional, additive).
- **Existing (M0):** `readiness()`, `priorities()`, `monday()/key()`, `save()/load()`,
  `send_briefing.py` message-building, VAPID subscriptions — all reused, not replaced.

## Decisions to confirm

1. **Push weekly-summary "sessions done" without `log.days`.** Server-side has no training-log
   access. Recommend: push shows *planned* sessions + an activity-derived proxy (or just
   planned) and defers the true done/planned count to the in-app card via a deep-link.
   Confirm: proxy-from-`min_intensywne`, planned-only, or omit the line in the push?
2. **Streak habit set — ship all four, or fewer?** Recommend all four (protein, steps, sleep,
   training) since each maps to an existing target/log with near-zero marginal cost. Confirm
   whether "sleep" streak is wanted (sleep is partly outside volitional control; some users
   find a sleep streak stressful rather than motivating).
3. **Reminder cadence & content.** Recommend Sunday = weekly check-in push, Saturday morning =
   measurement + photo nudge. Confirm the two weekdays and whether the photo reminder fires
   only when M2 is active or unconditionally.
4. **`plan.json` `habits` block values.** Recommend `stepGoal 8000`, `sleepGoalH 7.0`,
   `weekThreshold 0.8`, `trainingToleranceMissed 1`. Confirm the numbers (esp. step goal vs.
   the existing "7–8k" copy) and whether they should differ per phase.
5. **Best-streak persistence.** Recommend the small `fit-adh-v1` high-water-mark key. Confirm
   it's acceptable to add one new localStorage key (vs. showing only current streak and no
   all-time best).
