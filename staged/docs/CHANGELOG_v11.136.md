# WINK Lab Tools v11.136 — an empty recording must not produce a dose-response

Ships everything in v11.135 (the Cultured cell calcium tool — see that
changelog) plus one guard that release needed and did not have.

## What happened

The new tool was run on the lab's ACh dose-response movies. It reported that
**100% of cells responded in every well**, including caffeine, with ΔF/F₀ up to
32, and produced what looked like a dose-response curve.

None of it was real. In those recordings:

- **96–98% of every pixel is exactly zero**
- only **24–43 of 256 grey levels** are used
- the whole-field mean is **0.4 counts**
- in the brightest frame of the strongest condition, the objects above 5 counts
  numbered **1,121 with a median size of 1 pixel** — shot noise, not cells

Cell baselines came out at 0.00–2.87 counts. ΔF/F₀ divides by that, so a change
of one grey level becomes an amplitude of 10, and the "responses" were
quantisation noise divided by nearly nothing. Time-to-peak was scattered across
the entire recording instead of clustering after drug addition, and decay
constants came back at 121–151 s from a 30 s recording — both signatures of no
event at all.

## The fix, and why the existing guards missed it

`check_recording()` already warned about dim signal and low bit depth, and
`resting_ratio()` already refused ratios built on too few counts. Neither ran
here, because **they check a *recording* and `transient()` takes a *trace***.
Nothing stood between a trace and ΔF/F₀.

`transient()` now refuses a trace whose baseline is indistinguishable from zero.
The test is unit-free, so it needs no declared bit depth: it compares the
baseline against the scatter of the resting part of the trace itself. If the
resting points wander by as much as the baseline is worth, the baseline is not
measurably different from zero and nothing divided by it survives.

The refusal says what to do about it — *fix the exposure; no analysis recovers a
signal that was never collected* — because this is not a threshold to tune.

A companion test confirms the guard does not refuse real data: a genuine
transient on a baseline of 100 counts with an SD of 3 still passes.

## Why this one mattered

This is the failure mode the module exists to prevent, and it got through: a
plausible dose-response, from empty recordings, reported confidently. The lesson
is in the code comment — a guard that checks the recording does not protect the
function that takes the trace.
