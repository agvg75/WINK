# WINK Lab Tools v11.117 — Population tracking: modality proposals could never be made above 20 fps

A single mis-specified gate meant the locomotion-modality classifier **never
proposed anything** on recordings at 30 fps or above, however good the data.
Every bout came back `uncertain` with confidence `0.00`, and the stated reason —
"insufficient spine or track coverage" — was true but misleading: the coverage
could not be reached by construction.

## The bug

Detailed spines are deliberately sampled at about 15 Hz, not every frame:

```python
stride = max(1, floor(fps / target_spine_fps))     # target 15 Hz
```

At 30 fps that is stride 2, so a spine exists on at most every second frame. The
classifier then measured posture evidence against **every** frame in the window:

```python
valid = len(curves) / len(window)          # ceiling of ~0.5 at 30 fps
if coverage >= .7 and valid >= .65 and ...  # unreachable
```

So the gate demanded 0.65 of a quantity that could not exceed ~0.5. At 20 fps
the stride is 1 and the gate worked, which is why the synthetic fixture — and
therefore the regression tests — never caught it.

Measured on a real 30 fps recording, before the fix, with **both** skeleton
methods:

| skeleton | median `spine_valid_fraction` | max | windows passing the gate | proposals |
|---|---|---|---|---|
| morphological | 0.233 | 0.455 | **0 of 558** | 558 × uncertain |
| thinning (99.7% spine success) | 0.500 | 0.545 | **0 of 558** | 558 × uncertain |

Even a near-perfect skeleton could not clear it.

## The fix

Posture evidence is now measured against the frames where a spine was
**attempted**, which is what the stride defines:

```python
attempted = ceil(len(window) / stride)
valid     = min(1.0, len(curves) / attempted)
```

Same recording, after:

| | before | after |
|---|---|---|
| windows passing the posture gate | 0 of 558 | **439 of 558** |
| bout confidence | 0.000 | median **0.392**, max 0.438 |

The bouts on that recording are still labelled `uncertain` — but now because the
evidence genuinely overlaps, not because the classifier never ran. That is a
scientific verdict rather than a plumbing failure, and it is actionable.

## "Uncertain" now says why

One reason string covered five different situations. They are now distinct,
because they call for different actions:

| reason | what to do |
|---|---|
| `insufficient_track_coverage` | the animal is not tracked through enough of the window — fix linking or gates |
| `insufficient_spine_evidence` | too few usable spines — try the thinning skeleton, or more magnification |
| `possible_collision_in_window` | animals overlapping — split or exclude |
| `no_usable_frequency` | no periodic signal recovered |
| `overlapping_modality_evidence` | the classifier ran and the modalities genuinely overlap |

On the real recording that split as 430 overlapping evidence, 85 sparse spine,
40 low track coverage, 3 collision — a diagnosis instead of one uninformative
label.

## Posture provenance

Every modality window now records how much real posture evidence backs it, and
the bout a human reviews carries it through:

- `spine_frames_used` — frames with a usable curvature profile
- `spine_frames_attempted` — frames where a spine was attempted, given the stride
- `spine_stride_frames` — the sampling interval in force
- `spine_sampling_rate_hz` — effective posture sampling rate
- `spine_fraction_of_all_frames` — for comparison with earlier results
- `window_frames`, and on bouts `spine_evidence_fraction` and `proposal_reason`

A posture metric derived from a partial spine sample is legitimate — but only if
the sample is stated. It now is.

## What did not change

`spine_valid_fraction` is now a fraction of attempted frames rather than of all
frames, so it is **not comparable** with the same column in v11.116 and earlier;
`spine_fraction_of_all_frames` carries the old definition for continuity.

On the synthetic fixture (20 fps, stride 1) every numeric value is unchanged and
every proposal is identical — only `proposal_reason` becomes more specific. Both
population-swimming regression tests pass.

Any recording at 30 fps or above will now produce different modality proposals,
because previously it could produce none. Re-run anything where the modality
call mattered.
