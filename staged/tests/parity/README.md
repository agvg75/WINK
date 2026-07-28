# Parity harness (trust gate)

Implements the "Parity test: the trust gate" section of
`RGBCaMP_fiji_plugin_handoff.docx`, ahead of the Fiji plugin itself.

The plugin will be a thin Java/SciJava shell that writes a temp CSV +
`config.json`, invokes a bundled Python process running
`worm_rgbcamp_analysis.py` + `worm_channels.py` + `worm_kinetics.py`
unchanged, and reads the result tables back. This harness is the gate that
proves that delegation never silently drifts from a direct run of the same
Python module -- and, since 2026-07-06, that the reference computation itself
exercises the real pipeline (see "Durable lesson" below).

## Six golden cases

| | golden_output | golden_output_bg | golden_output_perchannel | golden_output_coupling | golden_output_kinematics | golden_output_neuromech |
|---|---|---|---|---|---|---|
| Source | pilot recording (single worm, fps=5) | real lab recording, `WT_day1_L4440_a01.csv` | same real recording (independent copy) | same real recording (independent copy) | same real recording (independent copy) | same real recording (independent copy) |
| Extractor contract_version | 2 | 3 | 3 | 3 | 3 | 3 |
| Reference path | legacy hand-rolled (mode="legacy") | legacy hand-rolled | `run_one.analyse_one()` directly (mode="run_one") | `run_one.analyse_one()` directly | `run_one.analyse_one()` directly | `run_one.analyse_one()` directly |
| Background columns | **none** | `bg_blue/green/red` (real) | same | same | same | same |
| Expected `background_applied` | `False` (correct) | `True`, cols used listed | `True`, cols used listed | `True`, cols used listed | `True`, cols used listed | `True`, cols used listed |
| Exercises | everything except background subtraction | the background-subtraction path | the per-channel calcium path (Stage 2a): `region_split_red/blue`, `dorsal_ventral_{green,red,blue}`, `resting_calcium_blue`, `release_reuptake_blue` | the coupling path (Stage 2b): `curvature_phase_lag_{green,red,blue}`, `interchannel_timing` (green_vs_blue, green_vs_red) | the kinematics path (Stage 3a): `undulation_descriptors`, `locomotion_summary` -- posture/velocity, NOT head-masked | the neuromechanical chain (Stage 3c): `curvature_to_translation`, `propulsion_efficiency`, `calcium_output_decomposition_{green,red,blue}` |

All six are frozen, real recordings -- never synthetic. `release_reuptake`
carries every Fix 1-3 flag column (`onset_at_boundary`, `decay_incomplete`,
`tau_extrapolated`, `decay_subresolution`, `confirmatory`), which is why its
per-channel variant is part of case 3.

Cases 1 and 2 use the `mode="legacy"` reference path (hand-rolled load -> QC ->
`apply_normalisation` -> `mask_head` -> the 3 original green-only tables),
frozen before the per-channel work existed and left untouched. Cases 3-6 use
`mode="run_one"`: `compute_reference_via_run_one()` calls
`run_one.analyse_one()` in a throwaway temp directory and pulls specific
table keys out of the returned `AnalysisResult` -- so these cases test the
actual computation path the results browser and CLI launcher use, not a
second hand-written copy of it.

## Tolerance rule (per the handoff)
Integer counts, flags, and labels must match **exactly**. Floats are compared
at `rtol=1e-6` (`atol=1e-9`) to absorb platform floating-point differences.
Both-NA cells are treated as equal. The channel-normalisation report
(`background_applied`, `background_cols_used`) is compared exactly wherever
the golden case carries one -- case 1 predates that gate and is exempt (it
has no background data to gate on).

## Usage
```
python parity_check.py freeze     golden_input_<case>/<file>.csv  golden_output_<case>/
python parity_check.py check      golden_output_<case>/  [--candidate DIR]
python parity_check.py check-all  [harness_dir]
```
`check-all` (no arguments, run from this folder) self-tests every
`golden_output*` case in one call -- this is the command to wire into CI /
a pre-commit gate.

`check` with no `--candidate` re-runs the direct Python path on the frozen
input and diffs the fresh run against the frozen golden output -- a
determinism self-test, since there is no Java plugin yet to produce a
candidate. **When the Fiji plugin exists:** point `--candidate` at the
directory its Python subprocess wrote `release_reuptake.csv` /
`region_split.csv` / `contraction_state.csv` / `qc_report.json` into. No
change to the harness logic is needed.

## Durable lesson (why case 2 exists)

On 2026-07-05, `worm_channels.py` looked for a single background column among
`background_mean`/`bg_mean`/`background`/`outside_mean`/`bkg_mean`. The
extractor had, by then, been writing **per-channel** `bg_blue`/`bg_green`/
`bg_red` columns for a day. None of the candidate names matched, so
`background_applied` was silently `False` on every real recording -- not a
missing measurement, a column-name mismatch between two modules that had
never been run against the same real CSV.

The parity harness was passing the whole time. It couldn't have caught this:
case 1 (the only golden case at the time) predates the background columns
entirely, so the background-subtraction path was never exercised -- a bug
there was invisible to the gate by construction, not by bad luck. Verified
directly: reinstating the old single-column-only detector and re-running
`check()` against case 1 still returns pass (0); against case 2 it fails (1),
citing `channel_report.background_applied: golden=True candidate=False`.

This is also not the first time a column name assumed in one module didn't
match what an upstream module actually writes. The recurring cause is always
the same: a module gets tested against a spec's assumed column names, or
against synthetic data shaped to match those assumptions, rather than against
a real upstream export. `compute_reference()` in this file was itself part of
the problem until this fix -- it called the older `wa.add_dff()` instead of
`wc.apply_normalisation()` (the function the real pipeline, `run_one.py` and
`worm_batch.py`, actually calls), so even a background-bearing golden CSV
would not have exercised `worm_channels.py` at all. Both halves are fixed now:
the reference computation uses the real call path, and a real (not synthetic)
background-bearing export is frozen as a golden case specifically to keep
that path honest.

**Going forward:** any new column, contract-version bump, or normalisation
step needs a golden case built from a real export that actually carries the
new data -- not a synthetic stand-in, and not reuse of an old case that
predates the feature. That's the only way a missing/renamed column shows up
as a failed `check-all` instead of a silently-false report field.

## Durable lesson, part 2 (why case 3 exists -- Stage 2a)

Stage 2a extended calcium analysis from green-only to every active channel,
with a per-channel head mask (blue keeps the head; green/red don't) and two
new analyses (`resting_calcium`, `dorsal_ventral_split`). None of that is
exercised by cases 1 or 2: both call `worm_kinetics` functions directly with
their green-only defaults and never touch a red/blue table or the new
functions at all -- the exact same shape of gap that let the background bug
through. Verified directly, the same way: broke `dorsal_ventral_split` to
always return zero rows, then ran `check()` against all three cases. Cases 1
and 2 still passed (0) -- they never call it, so a real break there is
invisible to them by construction. Case 3 failed (1) immediately, citing
`dorsal_ventral_{green,red,blue}: row count differs (golden=2, candidate=0)`.

This also caught a second, narrower bug in the harness itself while building
case 3: `_diff_table()` decided float-vs-exact comparison from the golden
CSV's dtype alone. A string column that happens to be blank on every row of a
small table (e.g. `resting_calcium_blue`'s `reason` column, when both regions
are valid) round-trips through `pd.read_csv` as all-NaN `float64`, even
though the freshly-computed candidate's in-memory version is real text ("" is
not NaN in memory). Comparing golden's dtype in isolation misclassified the
column as float and crashed trying to parse text as a number. Fixed by
requiring the non-missing values on **both** sides to be numeric before
treating a column as float, and by using `is_string_dtype` instead of
`dtype == object` for the empty-string check (pandas 3.0 defaults to its own
`StringDtype` for text columns, which is a distinct dtype from plain
`object` -- a bug of the identical shape to the one this whole harness
exists to catch, just one layer down, in the harness's own comparison code).

## Durable lesson, part 3 (why case 4 exists -- Stage 2b)

Stage 2b replaced two frame-quantized coupling estimates (the pilot's
`intersignal_timing`, and `amplitude_coupling`'s integer-frame xcorr argmax)
with sub-frame Hilbert-phase and parabolic-interpolation methods
(`curvature_phase_lag`, `interchannel_timing`), sharing a `_band_hilbert_phase`
helper with `wave_propagation`. None of cases 1-3 call any of this: case 3
gates the per-channel *calcium* path (region split, resting calcium, kinetics
per channel), not coupling. Verified the same way as parts 1 and 2: broke
`_band_hilbert_phase` to return a flat zero phase, then ran `check()` against
all four cases. Cases 1, 2, and 3 still passed -- they never call it. Case 4
failed immediately with 12 problems across `curvature_phase_lag_green/red/blue`
and `interchannel_timing`.

## Durable lesson, part 4 (why case 5 exists -- Stage 3a)

Stage 3a added posture-only kinematics (`undulation_descriptors`,
`locomotion_summary`) that are explicitly NOT head-masked -- posture is valid
over the whole body (segments 0-23), unlike every calcium metric in cases
1-4. None of the first four cases call either function; they gate calcium
and coupling paths only. Verified the same way as parts 1-3: monkeypatched
`wave_propagation` to force `direction="undetermined"`/zero coherence
whenever called with `value="seg_curv_deg"` (the kinematic body-wave call
both new functions make), leaving its calcium-facing calls (`value=
"<channel>_dff"`) untouched, then ran `check()` against all five cases.
Cases 1-4 passed regardless -- none of them ever calls `wave_propagation` on
curvature. Case 5 failed immediately on `undulation_descriptors.direction`,
`.wavelength_segments`, `.bend_amplitude_deg`, and `.reason`.

This also confirms `wave_propagation`'s Stage 3a refactor (additive
`frame_numbers`/`frame_slopes`/`frame_r2`/`seg_axis`/`seg_envelope` return
keys, needed so `locomotion_summary` can classify forward/backward per frame
without a second Hilbert/band-pass implementation) didn't disturb any
existing caller: cases 1-4 passed unchanged both before and after that
refactor landed.

## Durable lesson, part 5 (why case 6 exists -- Stage 3c)

Stage 3c added the neuromechanical chain's missing middle link
(`curvature_to_translation`), the propulsion-efficiency spatial breakdown
(`propulsion_efficiency`, whole-body/region/segment), and a per-channel
bending-vs-propulsion split (`calcium_output_decomposition`). None of cases
1-5 call any of these three functions. Verified the same way as parts 1-4:
monkeypatched the shared `_xcorr_lag_parabolic` estimator (used by
`curvature_to_translation` and `calcium_output_decomposition`'s propulsion
half, and also by `interchannel_timing` from Stage 2b) to always return zero
lag/peak -- the pilot's original integer-argmax failure mode this estimator
exists to fix -- then ran `check()` against all six cases. Cases 1-5 passed
regardless (case 4/`golden_output_coupling` happens not to hit the broken
xcorr fallback path for this recording's data, since its channel pairs
resolve via the Hilbert-phase branch instead); case 6 failed immediately on
5 fields: `curvature_to_translation.lag_s`, `.xcorr_peak`, and
`calcium_output_decomposition_{green,red,blue}.propulsion_lag_s`.

This also confirms `propulsion_efficiency`'s per-segment breakdown (which
reuses the ONE whole-body `wave_propagation` fit's per-segment envelope,
Stage 3a's additive `seg_axis`/`seg_envelope` keys, rather than re-fitting a
wave per segment) and `cycle_average`'s additive `vel_col` parameter (used by
the Stage 3c phase-axis overlay figure) didn't disturb any existing caller:
cases 1-5 passed unchanged both before and after these changes landed.

**The pattern across all five durable-lesson entries is the same**: a golden
case only gates what it actually calls. Every new analysis function needs its
own real-data golden case the day it's added, not a promise to add one later
-- "later" is exactly how the background bug and the per-channel gap both
slipped through in the first place.
