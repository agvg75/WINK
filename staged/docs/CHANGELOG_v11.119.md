# WINK Lab Tools v11.119 — nothing was checking the two numbers everything depends on

Frame rate and micrometres-per-pixel are typed in by hand in every module and
recorded as `"declared"`. Nothing verified either one. Both propagate linearly
into every reported physical quantity:

```
speed     = pixels/frame x fps x um_per_px      (linear in BOTH)
frequency = cycles/frame x fps                  (linear in fps)
```

so a value wrong by a factor of four makes every result wrong by a factor of
four — silently, consistently, and in a way that looks entirely plausible.

**The case that prompted this.** A recording captured at about 7.5 fps but
written with a 30 fps header, analysed at 2.0 µm/px when the true scale was
nearer 11, reported **1.17 Hz and 124 µm/s** for crawling animals. The right
figures are close to **0.29 Hz and 155 µm/s**. Nothing objected — even though
the module had already measured those animals at 100 px long, which at the
declared scale means 200 µm: the size of an L1 larva, not the adults on the
plate. Every ingredient of the contradiction was already in hand and nobody was
asked.

## Independent estimates of scale

Four routes, which now cross-check each other. New controls in Population
tracking: **Stage** (L1 through Adult day 5), **Vessel** (blank unless a vessel
is visible), and **Expected mode**.

| route | how |
|---|---|
| **Trace a worm** | click head to tail along the bends; the stage's published length converts pixels to µm/px |
| **Vessel rim** | auto-detected when the whole vessel is in frame |
| **Vessel arc** | click 3+ points on a *partial* rim — an arc determines the circle, so the vessel need not fit in frame |
| optical estimate | the existing scale calculator |

Vessels: 96/48/24/12/6-well plates and 3/5/6/10 cm dishes, with both nominal and
inner diameters, since a top-down camera may image either edge — for a 10 cm
dish those differ by 14%.

The arc fit reports the angle it spans and grades itself *good / weak / poor*: a
short, nearly straight arc barely constrains a radius, and says so rather than
being quietly trusted. Measured error stayed under 1% down to a 30° arc.

Every estimate is shown beside the declared value with the ratio. Applying it is
optional — **declining still records it.**

## Plausibility checks after every run

Compared against published ranges for the stated stage and locomotion mode:

> **Check: undulation frequency** — 1.17 Hz vs 0.15–0.90 Hz for crawling (the
> published range). Frequency scales with the declared frame rate ALONE, so it
> is the most direct indicator that the frame rate is not what the recording was
> captured at.

Ranges are deliberately wide: they exist to catch 4× and 5× mistakes, not to
police biology. A value outside a range is a prompt to check a declared
parameter, never a claim that the animals are abnormal. Mutants and stressed
animals legitimately fall outside, which is why every check is a warning and
nothing is ever corrected automatically.

## The lab's own reference ranges

Published ranges are broad because they span strains, rigs and temperatures. A
given lab occupies a much narrower band, so its own measurements make a sharper
check — `~/.wink/worm_measurements.jsonl`, with an optional shared path so a
whole lab accumulates one library.

**Only confirmed runs count.** A library built from runs whose declared
parameters were wrong would encode those mistakes as normal — the run above
would have taught it that adults are 200 µm long and crawl at 1.17 Hz.
*Confirm calibration for the lab library* is a separate, explicit action; every
run is recorded, but unconfirmed observations never shape a range, and remain
visible for audit. Verified: ten unconfirmed bad runs taught the library
nothing; twelve confirmed good ones then flagged 300 µm/s, which passes the
published range but not the lab's own.

## Correcting a finished run

**Correct the scale or FPS of a finished run…** re-derives a completed analysis
under corrected parameters without decoding a single frame. Detection, linking
and spine extraction are reused unchanged — they depend only on pixels and frame
numbers. Track summaries and modality proposals are **recomputed, not rescaled**,
because the classifier compares frequency against fixed thresholds and cannot be
multiplied through.

Verified against ground truth: recomputing a wrong run reproduces a direct run
with the correct values **exactly** — every column of the track summary, the
modality windows and the bouts identical — while leaving the original run
byte-for-byte untouched. Results go to a new folder; any human review of the
original does not carry over, and the provenance says so.

## What the recording was on

The background image every module already builds carries evidence of whether a
plate was seeded: bacterial lawns have texture and an edge, clean agar does not.
`substrate_texture.py` records objective statistics — local variance, edge
density, Otsu separability, darker fraction — and attaches a **tentative**
reading.

The numbers are always stored; the label never replaces them, is always marked
with its confidence and basis, and starts as `unvalidated_heuristic` until the
lab records four confirmed examples of each class. Building the controls caught
a real flaw immediately: a synthetic clean-agar frame scored 0.674 separability
— above threshold — because that statistic is normalised by total variance and
stays high on a near-uniform image. It would have misread every smooth plate.
The feature now abstains below a contrast floor and records that it abstained.

## Inference stored with the data

`calibration_provenance.json` is written with **every** run, whether or not
anything looked wrong and whether or not the student acted on it:

```json
"independent_scale_estimates": [
  {"route": "worm_trace", "um_per_px": 11.50, "confidence": "measured_on_this_recording"},
  {"route": "vessel_rim", "um_per_px": 10.96, "confidence": "good"}
],
"estimate_spread": {"ratio_max_over_min": 1.05},
"scale_actually_used_um_per_px": 2.0,
"plausibility_warnings": [ ... ],
"confirmed_by_user": false
```

A value that was inferred and ignored is still evidence. Someone returning to
this dataset in a year can see which routes were available, what each implied,
which was used, and what disagreed at the time.

## Also

An assistant documentation corpus is included at `docs/assistant/` — module
documentation, troubleshooting written as observation-to-explanation, a
versioned system prompt, and a run-summary schema. Drafted from the defects
found in v11.116–v11.118 rather than invented.

## Verification

No measurement changed: `population_swimming.py`'s analysis path is untouched
except for the additive recompute entry point, and the calibration review writes
provenance only — never a summary, a CSV or a classification. Both
population-swimming regression tests pass, along with structural checks for
in-window review, manual-point firewall, track editing, trail control,
stale-review archiving, calibration wiring, recompute equivalence, and
undefined names.

The reference ranges are literature values and a starting point. Adult day 2–5
lengths in particular rest on thinner published data than the earlier stages,
and a lab's own confirmed measurements should replace them.
