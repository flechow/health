# Milestone 2 — Body composition tracking

**Date:** 2026-07-06
**Status:** Draft design, ready for implementation planning
**Part of:** Protokół 116→90 roadmap (M2 of 4: Nutrition → **Body composition** → Analytics → Adherence)

## Goal

The Protokół target is **muscular 90 kg**, not "90 kg". Scale weight (`waga`) alone cannot
verify this — the user could hit 90 kg skinny-fat. M2 adds inputs that separate **fat** from
**muscle** so progress can be judged as recomposition, not just weight loss.

The cheapest reliable fat-loss truth-teller is **waist circumference**: with roughly stable
weight and rising gym loads, a shrinking waist is a textbook signal that fat is coming off
while muscle is retained.
([Step One](https://mystepone.co.uk/articles/is-body-recomposition-working),
[MNT](https://mnt.com.pk/blogs/weight-loss/scale-not-moving-but-losing-fat))
M2 makes the app read waist and weight **together** instead of trusting the scale in isolation.

## Non-goals

- **No in-app camera / photo pipeline.** Progress photos stay device-local (see Photos); the
  app never uploads, encrypts-to-repo, or transmits image blobs.
- **No smart-scale purchase forced by this milestone.** A Garmin Index would populate
  `body_fat`/`muscle_kg`/`body_water` automatically through the *existing* pipeline (nothing to
  build), so scale support is a **zero-code passthrough** we design the UI to light up when data
  appears — not a task.
- **No new server-side sync.** Circumferences and photo metadata are manual user inputs, like
  `log.weights` today. No `update_garmin.py` change, no new secret, no new Actions step.
- **No bioimpedance / DEXA / caliper skinfold modeling.** YAGNI for a solo user; waist + weight
  + gym-load trend already answer the recomp question.
- ETA projection and fat-loss-**rate** guardrails from the combined trend are **M3 (Analytics)**.
  M2 ships the *inputs and trends*; M3 consumes them.

## Chosen approach

**Track waist as the primary metric, plus a small fixed set of secondary circumferences, all
stored device-local (localStorage), entered on a weekly cadence. Progress photos are supported
as device-local file references only (metadata in the app, pixels never leave the phone).
Smart-scale body-comp fields are surfaced automatically if/when they appear in the encrypted
rows.**

Concretely, three tiers by effort/value:

1. **Waist circumference (build this).** Primary fat-loss signal. One weekly number.
2. **Secondary circumferences (build this, same structure, optional per-entry):** neck, hips,
   chest, arm (flexed), thigh. A *shrinking waist with stable/growing arm & thigh* is the clean
   recomp proof, so a couple of "muscle" sites are worth the tiny extra cost.
   ([alibaba wellness](https://wellness.alibaba.com/fitlife/how-to-tell-if-you're-recomping))
3. **Progress photos (light support):** store user-picked photo references + date + pose label
   in IndexedDB, render a thumbnail timeline. **Device-local only.**
4. **Smart-scale body-comp (no build):** the render layer reads `body_fat`/`muscle_kg`/
   `body_water` from rows and shows them when non-null. Already flows via `get_body_composition`.

### Which sites, and why these

- **Waist at the navel** is the standard, repeatable site and the one most tied to visceral/
  abdominal fat. Measure level with the belly button, tape snug not tight, on a relaxed
  exhale, not holding breath or sucking in.
  ([WebMD](https://www.webmd.com/diet/calculating-your-waist-circumference),
  [Kaiser Permanente](https://healthy.kaiserpermanente.org/health-wellness/health-encyclopedia/he.measuring-your-waist.aa128700))
  A common cross-check target: waist ≈ half of height or less.
- **Neck + hips** enable optional Navy-method body-fat% estimation later (M3) with zero extra
  hardware — cheap to collect now, so the fields exist if M3 wants them.
- **Arm (flexed) + thigh** are the "is muscle holding?" sites for the recomp read.
- Keep the set **fixed and small.** More sites = more friction = fewer entries. YAGNI beyond these.

### Cadence: weekly

Waist is chosen **weekly**, first thing in the morning, ideally same weekday and conditions.
Daily waist is noise (food/water/bloat swings) and invites discouragement; weekly is the sane
tracking interval that still catches meaningful change. This mirrors the app's existing 7-day
trend framing.
([MNT](https://mnt.com.pk/blogs/weight-loss/scale-not-moving-but-losing-fat))
Weight stays daily (unchanged). The interpretation the app teaches: **watch the trend, not the
single reading; waist down + weight ~flat + loads up = recomp working.**

## Rejected alternatives

- **Store circumferences inside the encrypted Garmin row (like nutrition in M1).** Rejected:
  circumferences are *manual user inputs*, and every other manual input (`weights`, `exHist`,
  `days.trained`) already lives in localStorage. Writing them into the encrypted file would
  require a browser-side write-back path to the GitHub repo that **does not exist today** (the
  browser only *reads/decrypts*; `update_garmin.py` is the only writer). Building an encrypted
  write path for one weekly number is disproportionate. See Privacy for the tradeoff.
- **Force a smart scale as the M2 deliverable.** Rejected as the *primary* answer: body-fat% from
  consumer bioimpedance scales is noisy and the user may not own one. We passthrough its data if
  present but do not depend on it. Waist is more reliable per złoty.
- **In-app photo capture + encrypted photo storage in the repo.** Rejected: progress photos are
  the single most sensitive data in the whole system, GitHub Pages/repo blobs are the wrong home
  for them, and image encryption/commit is heavy. Device-local IndexedDB references only.
- **Daily circumference logging.** Rejected: noise > signal, discouraging, contradicts evidence.

## Architecture

### Components

All work is **front-end only** (`index.html`). No Python, no Actions, no worker, no plan-sync
changes. This is the key difference from M1 (which was server-pull heavy).

**New localStorage store `bodycomp-v1`** — parallels `fit-log-v1`/`markers-v1`:

```json
{
  "circ": {
    "2026-07-06": { "waist": 104.0, "neck": 41, "hips": 110, "arm": 36, "thigh": 62, "chest": 112 },
    "2026-07-13": { "waist": 102.5 }
  }
}
```

- Keyed by date (`YYYY-MM-DD`), same shape convention as `log.weights`.
- Every site is optional per entry; only `waist` is "expected". Missing sites are simply absent
  (consistent with the app's pervasive nullable-field handling).
- Units: centimeters. Values sanity-clamped on input (e.g. waist 50–200 cm) like the existing
  weight input clamp (40–250 kg).
- Loaded via the existing `load("bodycomp-v1",{circ:{}})` / `save(...)` helpers.

> `markers-v1` (investigated): it holds **blood-lab markers** — `markers.tg` (triglycerides) and
> `markers.hdl` (HDL), used to compute a TG/HDL ratio on the Today view. It is a manual,
> device-local health-input store — exactly the neighbor circumferences belong beside. We add a
> **sibling** store rather than overloading `markers-v1`, keeping "lab bloods" and "body
> measurements" cleanly separated.

**New IndexedDB store `bodycomp-photos`** (photos only):

- Records: `{ id, date, pose: "front|side|back", blob }` where `blob` is the user-selected
  image (via `<input type="file" accept="image/*">`, which on mobile offers camera or gallery).
- IndexedDB (not localStorage) because localStorage is ~5 MB and string-only; photos need blob
  storage. IndexedDB is the correct browser home for binary and **never syncs anywhere**.
- Optional: downscale to a max dimension (e.g. 1080px) via canvas before storing, to bound size.

### Data model summary

| Data | Store | Encrypted? | Leaves device? |
|---|---|---|---|
| Circumferences | `bodycomp-v1` (localStorage) | No | No |
| Photo pixels + metadata | `bodycomp-photos` (IndexedDB) | No | **Never** |
| `body_fat`/`muscle_kg`/`body_water` (scale) | encrypted Garmin row | Yes (AES-GCM) | Already synced |

### Storage location + privacy reasoning

- **Circumferences in plaintext localStorage** matches the *existing* trust model: `fit-log-v1`
  (weights, gym loads, trained-days) and `markers-v1` (blood labs) are already unencrypted and
  rely on **device lock** for protection. Waist size is no more sensitive than the weights and
  blood markers already stored this way. Adding encryption for it alone would be inconsistent and
  would need a browser write-back path that doesn't exist. **Decision: accept the existing model.**
- **Explicit tradeoff acknowledged:** anyone with an unlocked-device shell / another script on
  the origin can read localStorage. That risk already exists for weight and blood labs. If the
  user later wants at-rest encryption for *all* manual inputs, that's a cross-cutting M-later
  task, not M2 scope.
- **Photos are the sensitive item and get stricter handling:** device-local IndexedDB only, no
  network path whatsoever, no repo commit, no worker. The app can offer an **Export / Delete
  all photos** control so the user stays in control of the blobs. This is the strongest privacy
  posture and costs nothing.

### `plan.json` targets

Each phase gains a `body` block, edited like `cardio`/`nutrition`:

```json
"body": { "waistCm": 94, "bodyFatPct": 15 }
```

- `waistCm`: phase target waist. Phase 1 could target an intermediate (e.g. ~100 cm); the final
  Protokół target waist (e.g. ≈90–94 cm, roughly half-height, **to confirm**) lives on the last
  phase.
- `bodyFatPct`: only meaningful once a smart scale (or Navy estimate) provides body-fat%;
  shown/used only when data exists. Nullable/omittable per phase.
- Missing `body` block → card renders without a target line and body priority rules skip
  (same graceful-degradation contract as the M1 `nutrition` block).

## UI

Match existing conventions: metric cards with `data-info` tap-to-explain sheets, Progress-tab
sparkline trends via `spark(vals,color)` / the `trend(...)` helper, weekly `bars(...)`, and the
`priorities(rows)` / readiness engines.

### New "Sylwetka" (Body/Physique) card — Today view

Placed near the weight card / Regeneracja section:

- **Talia (waist)** — latest value in cm, with target from `plan.json` `body.waistCm`, plus an
  arrow vs. previous entry (down = good; reuse the arrow styling used by weight/HRV).
- **Talia − 4 tygodnie** — change over ~last 4 weekly entries (the honest trend number).
- **Body-fat % / Mięśnie kg** — shown **only when non-null** in rows (smart-scale present),
  exactly like the conditional VO₂max/BodyBattery cards. Absent otherwise (no empty clutter).
- A compact **"+ dodaj pomiar"** entry affordance opening inline numeric inputs for waist
  (required) + optional secondary sites, mirroring the existing weight-entry input+button
  pattern (`parseFloat`, comma→dot, clamp, `save`, `render`).
- Tap-to-explain sheet: how/where to measure (navel, exhale, snug), why weekly, and how to read
  waist-vs-weight for recomp. New `INFO` registry entries: `talia`, `bodyfat`, `sylwetka`.

### Progress tab additions

- **Waist trend line** alongside weight/HRV/VO₂max, via the existing `trend(label, vals, unit,
  goodUp=false, info, color)` helper (waist: `goodUp=false`). Data source: `bodycomp-v1.circ`
  waist values in date order.
- **Overlay read:** render the waist trend directly beneath the weight trend so the
  "weight flat / waist down" recomp story is visible at a glance (no new chart type needed —
  two adjacent sparklines).
- **Body-fat % trend** — only if smart-scale data exists.
- Photos: a simple **thumbnail timeline strip** (date-labeled) from IndexedDB, tap to enlarge.
  No comparison-slider gymnastics in M2 (YAGNI); side-by-side is just two thumbnails.

### Priorities + readiness integration

Add body-comp rules to `priorities(rows)`, weighted into the existing top-3 selection, guarded by
a `bodyTargets()` helper (mirrors `fuelTargets()`):

- **Stale measurement:** no waist entry in ≥14 days → `📏 Zmierz talię` (moderate weight, ~6).
  Keeps the one manual input alive without nagging.
- **Recomp confirmation (positive reinforcement):** over the last ~4 weekly points, waist
  trending down while weight ~flat → `✅ Rekompozycja działa — mięśnie zostają` (low weight,
  informational; surfaces good news, doesn't crowd out corrective priorities).
- **Waist plateau vs target:** waist flat for ≥3 entries and above `body.waistCm` → optional
  `📉 Talia stoi` nudge (moderate weight).

**Readiness score stays recovery-driven and unchanged** (same principle as M1): body-comp is a
*progress* signal, not a *recovery* signal, so it must not move the readiness number. Surface it
via the priorities card and Progress tab only. No penalty.

## Reminders / cadence

- No push/email plumbing added in M2 (keeps scope tight; `send_briefing.py` untouched).
- The **weekly cadence is enforced softly** by the "Zmierz talię" priority appearing after 14
  days stale — in-app, zero new infrastructure.
- **Decision to confirm:** whether the morning briefing (`send_briefing.py`) should later gain a
  "measure waist today" line on the user's chosen weekday. Deferred out of M2 by default.

## Error / empty-state handling

- **No circumference data yet** → Sylwetka card shows a friendly prompt ("Dodaj pierwszy pomiar
  talii") instead of dashes; Progress waist trend hidden until ≥2 points (same `<2 → return ""`
  guard the `trend()` helper already uses).
- **Only waist, no secondary sites** → card shows waist only; secondary-site trends simply absent.
- **Missing `body` block in a phase** → no target line, body priority rules skipped.
- **No smart scale** → body-fat%/muscle rows and their trend never render (null-guarded), never
  as empty placeholders.
- **Invalid input** (non-numeric, out of clamp range) → ignored, no save, no render change — same
  silent-reject behavior as the weight input.
- **No photos** → timeline strip hidden; "Dodaj zdjęcie" affordance still available.
- **IndexedDB unavailable / quota exceeded** → photo feature degrades to unavailable with a note;
  circumference tracking (the core of M2) is unaffected since it's localStorage.

## Testing approach

Front-end logic is the surface, so tests target the pure functions (extract them testably):

1. **Unit tests** (fixture `bodycomp-v1` + fixture rows):
   - Waist series extraction + date ordering from `circ`.
   - 4-week delta / trend math (single point, sparse, dense; nulls skipped).
   - `bodyTargets()` reads `plan.json` `body` block; degrades when block absent.
   - Priority rules: stale (≥14d), recomp-confirmation (waist↓ & weight~flat), plateau — each
     fires correctly and **does not false-fire on sparse/insufficient data** (min-point guards).
   - Smart-scale passthrough: body-fat%/muscle render only when row fields non-null.
   - Input clamp/parse (comma→dot, out-of-range rejected).
2. **Manual verification:** add a few weekly waist entries → Sylwetka card, Progress waist trend,
   and a priority all render with real decrypted data; verify weight-flat/waist-down produces the
   recomp-confirmation priority.
3. **Photo path (manual):** pick an image → thumbnail appears, persists across reload, delete
   works, and confirm (network tab) **no request carries the blob**.

## Decisions to confirm

1. **Final target waist (and per-phase intermediates).** Recommend ≈90–94 cm final (roughly
   half of height / the <102 cm health line, tightened for "muscular"). Needs the user's height
   and preference to set `body.waistCm` per phase. *Assumed ~94 cm final in examples.*
2. **Secondary sites to actually collect.** Recommend the fixed set {neck, hips, arm-flexed,
   thigh, chest}; neck+hips unlock a future Navy body-fat% estimate in M3. Confirm the user
   will measure these or wants **waist-only** to minimize friction.
3. **Photos in scope for M2, and how far.** Recommend light device-local IndexedDB support
   (pick image + pose label + thumbnail timeline, never leaves device). Confirm the user wants
   photos at all vs. deferring them — the recomp question is already answerable from waist +
   weight + gym loads without photos.

Additional lower-stakes confirmations:
- **Storage model:** accept plaintext localStorage for circumferences (consistent with existing
  weights/blood-labs), rather than building an encrypted write-back path? (Recommended: yes.)
- **Weekly briefing nudge** to measure waist on a chosen weekday — include now or defer? (Recommended: defer.)
- **Navy body-fat% estimate** from neck/waist/(hips) — compute in M2 or leave for M3? (Recommended: M3.)
