# WINK session handoff — orientation assays

Written 2026-08-06 so this work survives a reboot. If the session is lost,
read this first, then `app/assay_parameters.py`, then the commit log from
`fecdba8` onward — the commit messages carry the reasoning, deliberately.

Raw transcript (91 MB, gzipped to 47 MB) is at:
- `LabTools_Reorganization/_session_archive/wink_session_2026-08-06.jsonl.gz`
- `L:\03_Magnetic Transduction\wink_session_2026-08-06.jsonl.gz`

Persistent facts are already in `~/.claude/projects/C--Users-avidal/memory/`,
which loads automatically in any new session — see `wink-population-assay-layer`
and `wink-mtx-retracking-limits`.

---

## What was built, in order

| commit | what |
|---|---|
| `fecdba8` | capability audit across 44 registered tools |
| `8b3691a` | operator identity, three-state omega gate, shared error reporting |
| `441e65b` | `plate_assay.py` — shared layer; stimulus geometry as the only per-assay part |
| `8f47be6` | chemotaxis + thermotaxis wired to the shared `population_layer()` |
| `c816eb5` | gradient ends, food state for every assay, chemotaxis stimulus identity |
| `558a882` | number of animals: placed vs tracked, and the survivorship bias between |
| `1aeeb60` | `UniformFieldProvider` (coil cage), ambient conditions requiring sign-off |
| `4377590` | Merritt cage: four conditions, oscillating and rotating fields |
| `8f5238f` | oscillation is a direction SWEEP, not a polarity reversal |
| `9fa8b6c` | drawn stimulus geometry, donut assay, field-over-movie overlay |
| `01e4c61` | tractability: can this recording give spines, or only centroids |
| `dc6c2a6` | reference-frame detection, track editing, half-body-length crossing |
| `8f32dec` | literature parameter sweep — 24 parameters from Bainbridge 2019 |
| `f819dce` | temporal heading binning, and the pseudoreplication finding |
| `7590edf` | `assay_protocol.py` — the controls that leave no trace in the data |
| `5aca02b` | axis vs polarity; response panel of everything else the stimulus changes |
| `e3cc0f8` | `reference_quality()` — is the reference frame typical of the movie |
| `75df4ce` | averaged reference, and the trap in spending its noise gain |

## The five findings worth not re-deriving

1. **Pooling a heading over a whole assay is wrong, not weak.** The preference
   rotates ~180° over 90 min, so a single mean averages a reversal against
   itself and lands near zero. Confirmed on synthetic data: intervals r=1.00
   in opposite directions, pooled r=0.00.

2. **A 180° reversal is one AXIS with the polarity flipped.** Axial statistics
   would show stable alignment while polar preference reverses — a different
   biological claim. A population aligned to the axis but split on direction
   scores r≈0 on a Rayleigh test.

3. **The published assay-window unit inflates n by ~3x.** Three windows of an
   interval are the same plates measured three times. Simulated animals with
   NO preference reached significance in 52% of tests (63/120) under that
   unit, against 8% with the assay as the unit. Both are computed;
   the published one is the default for comparability and disagreements are
   flagged.

4. **Kinesis is not taxis.** A field that changes speed, turning or pausing
   without changing heading is a real result that an orientation-only analysis
   records as a null. Non-directional measures can also be computed in the
   cancelled-field and sham conditions, where "which way" is undefined.

5. **Unrecorded is not not-done.** A control that ran but was never written
   down is a lost record; one that did not run is a confound. Kept apart
   throughout.

## Real-data test: Assay2_MTX (Christine)

`L:\03_Magnetic Transduction\Christine\Assay2_MTX_8bit_gray_1fps_960-1.tif`,
3455 frames at 1 fps, 540x960, ~58 min.

- **Scale 20.1 px/mm**, FOV 47.8 x 26.9 mm — from Andres's 1.14 mm worm length;
  height matches the 26–27 mm FOV in Bainbridge 2019.
- **Frame 0 has a ceiling-lamp reflection** (Andres identified it): 12,658 px,
  gone by frame 1, never returns. It is the one frame unlike every other, and
  the one "subtract the starting frame" picks.
- **Worms are BRIGHT on dark**; the module defaults to `polarity="dark"` and
  silently detected the ghosts at plausible counts.
- **Archived wrMTrck output is unusable** for time-resolved work: median track
  8 frames, and they are summary tables with no per-frame positions.
- **Re-tracking reaches ~14 tracks ≥10 min but is not biologically clean.**
  Turning 70–95° (uncorrelated is 90°), rising with interval, displacement
  scaling as √t — a random walk. Per-frame linking was worse; 31 s smoothing
  reaches 61.8° but erases the real turns.
- **Root cause is acquisition**: worms are ~23 px long and 1 fps is at Nyquist
  for a 0.3–0.5 Hz undulation, so body-wave wobble aliases into random motion.
- **Field-of-view censoring measured**: tracks ≥100 samples average
  0.063 mm/s against 0.107–0.119 for shorter ones. The longest-trackable
  animals are the slowest.

Re-tracking script (not promoted into WINK — its output is limited by the
source recordings): scratchpad `retrack.py`, reproduced under `docs/`.

## Open, in the order I would take them

1. **Field-of-view censoring** — the last item from the parameter sweep, and
   the real data shows it biases exactly the late windows where the reversal
   lives. Same survival logic as `donut_crossing`.
2. **Heading sample interval** as a recorded parameter, separate from fps.
3. **A magnet-vs-coil paired comparison** — the conditions can now be recorded
   distinctly but nothing contrasts them.
4. **Wire the overlay into the workbench** — `field_overlay.draw()` composes a
   frame; nothing calls it from the GUI and there is no movie export.
5. **Presentation, not assay** (Andres parked this): radial vs linear vs point
   source; Helmholtz cage vs N42 magnet. Geometry belongs to the presentation.
   The three current classes are the presentations this lab runs most, NOT a
   taxonomy.
6. **The wider literature sweep** — only the lab's own methods papers have
   been read. Chemotaxis and thermotaxis appear only where the magnetic paper
   mentioned them.

## Questions outstanding to Andres

- **30 vs 39 minutes** for the food-state reversal. His papers say 30, which is
  what `ENHANCED_SLOWING_S` uses; he said 39 once.
- Does the cage **add to** Earth's field or **cancel and replace** it?
  (Modelled as cancel-and-replace, which is what a Merritt does.)
- Is the field sweep **sinusoidal**? J0 attenuation (0.933 at ±30°) is specific
  to sinusoidal modulation; a square-wave dwell at ±30° gives cos(30°)=0.866.
- Ring magnet dimensions for the donut assay — currently 10/30/5 mm at 1.32 T
  as an editable default.

## Standing constraints

Human always in the loop; automation must not mean blind. Commit and push.
Record decisions to memory. Every refusal names its consequence. Unrecorded is
distinguished from not-done. Findings are reported with what would falsify
them.
