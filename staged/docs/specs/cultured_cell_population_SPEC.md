# WINK cultured cell population analysis — SPEC

Status: draft v1, 7 Aug 2026. **Phase 0 complete**; Phase 1 starting.
Scope: extends the cultured cell calcium viewer (`cell_calcium_lif.py`,
Cultured cell calcium hood). Human cell culture data, first consumer is
Naga's smooth muscle / progenitor calcium stimulation sets.
Reuses: myocyte morphometry measurement set, correction-log JSONL pattern,
abstain gates, contact sheet UI. Reuse over reinvention throughout.

---

## 0. Phase 0 — verify before building. **DONE, 7 Aug 2026.**

### 0.1 Folder loader on the students' real path — PASSES

`L:/02_Duchenne Muscular Dystrophy/Naga/Smooth muscle cells/Progenitor cells
calcium stimulation/hCTM ach 1`

**3,676 files found, matching the folder's actual TIFF count exactly.**

The defect was one character. The scan globbed `*.tif`, which does **not**
match `.tiff` — fnmatch requires the pattern to reach the end of the name —
and every file in that folder is `.tiff`. The viewer reported
"0 image(s), 1 frame(s) each".

Two things were fixed, not one:

- **Extensions are matched explicitly and case-folded**, not left to the
  platform. `Path.glob` is case-insensitive on Windows and case-SENSITIVE on
  macOS and Linux, so a folder of `.TIF` files would have worked here and
  failed silently on the lab's MacBook. Relying on the platform to fold case
  is a portability trap that only surfaces on someone else's machine.
- **"0 images, 1 frame each" is now impossible to print.** A count of zero
  cannot carry a per-item figure; that line existed because the frame count
  defaults to 1 and nothing recorded that the scan came back empty. The
  report now names what was searched for.

Spaces in the path were never a factor — `rglob` is not shell-based.

### 0.2 What the TIFFs are — ONE SERIES, not independent frames

One session stamp (`20260807_125618824`), frame indices **0–3675,
contiguous, no gaps**. Basler `acA1920-155um`, 960x600, 8-bit.

**Ordering rule: filename sequence number.** The mtime tiebreak is not
needed here and was not used; which rule was applied is recorded per
acquisition, as specified.

Consequence: the loader must assemble these into a time series. Until it
does, every time-series measure stays correctly unsupported and the students
get no calcium readouts.

### 0.3 Frame interval — 30 fps, and PROVENANCE IS PER-RIG

No declared interval exists anywhere. TIFF tags are bare — `ImageWidth`,
`BitsPerSample`, `Compression`, no `DateTime`, no custom timing tags. The
filename timestamp is the session start, constant across all 3,676 files.

The file mtimes are monotonic and evenly spaced: **121.273 s over 3,675
intervals = 33.0 ms/frame, 30.30 fps**, with the spacing at the end matching
the spacing at the start, so it is not drift.

**Recorded as 30 fps. On THIS rig the mtime measurement is primary and the
protocol setting corroborates it** — not the other way round.

> **General rule, and it generalises beyond this spec: an acquisition
> constant is recorded together with the rig that established it.** The
> 30 fps ceiling was established for the worm behaviour rigs. This camera,
> a Basler acA1920-155um, is capable of 155 fps. Here the two agree and
> nothing turns on it — but a per-rig constant must never quietly become a
> lab-wide one. A constant without its rig is an assumption wearing a
> measurement's clothes.

Presented proposal-then-accept in the UI: the interval is offered with its
provenance, and a person establishes it. mtimes survive some copy operations
and not others, which a declared interval would not.

### 0.4 Capability check firing 3x — CLOSED, NOT REPRODUCED

Measured: one `run_capability()` call fires `describe_source` **once** and
`check_recording` **once**.

Static causes ruled out: one button binding, no other caller, no `trace_add`
on the variables it sets, no `after()`, no rebinding, no protocol handler, no
per-check logging, and `_say` clears rather than appends.

The original click count is unrecoverable, so the observation cannot be
settled retrospectively. **Instead the log now diagnoses a recurrence
itself**: every hood line carries a clock time and a per-invocation run id.

```
* 17:26:06 info: Capability checked [r001] - 5 supported, 4 not
* 17:26:06 info: Capability checked [r002] - 5 supported, 4 not     <- 3 clicks
...
* 17:26:06 info: Capability checked [r004] - 5 supported, 4 not
* 17:26:06 info: Capability checked [r004] - 5 supported, 4 not     <- 1 click,
* 17:26:06 info: Capability checked [r004] - 5 supported, 4 not        a real bug
```

**Reopen only on a single-id triple.** Three distinct ids are three clicks
and are ordinary.

---

## 1. Segmentation channel declaration — required, blocking

1.1 `segmentation_channel` becomes a required field of the acquisition
    record. The existing warning text is promoted from advisory to gate.

1.2 Until declared, all between-cell comparisons (resting, soce,
    responding_fraction, and every population-level statistic in this spec)
    are withheld with the stated reason. Per-cell within-cell time courses
    remain available.

1.3 If the declared segmentation channel equals the probe channel (e.g.
    outlines drawn on fluo-4 itself), do not block, but attach a standing
    bias note to every population output: dim-loading cells are
    under-sampled; between-cell comparisons are conditional on loading. The
    note travels with exported results, not only the UI.

---

## 2. Phase 1 — counting and geometry

2.1 Cell segmentation on the declared segmentation channel. Detection is
    proposal only: automation proposes, human establishes.

2.2 Per-cell measurement set = the myocyte morphometry set applied per cell:
    area, perimeter, Feret max/min, aspect ratio, circularity, solidity,
    centroid, plus mean/median intensity per channel (labelled with the
    loading caveat where the probe channel is involved).

2.3 Count is derived from accepted cells, never from raw detections. Report
    both: proposed n and established n.

2.4 Units: physical units only when pixel size is present in metadata;
    otherwise px with the scale field null, never a default scale. Same rule
    as the held `um_per_px` on the worm side: no scale is better than an
    assumed one.

2.5 Correction logging from day one: every human add/remove/split/merge of a
    cell outline goes to append-only JSONL beside the raw auto-detected
    proposals, same schema family as myocyte morphometry.

---

## 3. Phase 2 — populations and status marking

3.1 Cell status: `alive` (default), `dead`, `excluded` (free-text reason).
    Dead is a human call, click-to-toggle, recorded in the correction log
    with who and when.

3.2 Populations: named groups, assignment by (a) clicking cells, (b) drawing
    ROIs (polygon and rectangle minimum) capturing cells by centroid. A cell
    belongs to at most one population per grouping scheme; multiple schemes
    allowed.

3.3 Persistence: sidecar per acquisition beside the stack
    (`<acquisition>.cellpop.json` plus the JSONL correction log), recording
    module version. DECISION: sidecar over session-only; reversible if the
    L-drive write pattern proves awkward for student permissions — flag if
    so, do not silently fall back to session-only.

3.4 All population statistics respect status: dead and excluded cells are
    reported separately, never silently dropped. Denominators always stated
    (responding fraction = responders / alive established n).

---

## 4. Phase 3 — rule-based auto-selection

4.1 Gates on measured features: size (area), shape (aspect, circularity,
    solidity), per-channel intensity. Combinable with AND logic; ranges, not
    single thresholds.

4.2 Auto-selection produces proposals into a population; human accepts, same
    establish step as 2.1. Gate parameters saved with the selection so it is
    reproducible and auditable.

4.3 Intensity gates on the probe channel display the loading-bias warning at
    the point of use, in the gate dialog itself, not only in docs.

4.4 **No default gate values ship enabled.** Any suggested starting value
    must state its derivation or be absent. See the 0.55 acceptance-band
    lesson: an underived constant survives for years and then silently
    decides an experiment.

---

## 5. Validation

5.1 Counting: agreement against hand counts on >=10 images spanning the
    students' real acquisitions, dense and sparse fields. Report
    proposed-vs-established deltas, not just final agreement.

5.2 Geometry: spot-check Feret and area against Fiji/ImageJ on the same
    outlines for a handful of cells; agreement within rounding, since these
    are the same definitions.

5.3 Mask-on-raw overlays are the acceptance artefact for segmentation. Per
    the standing rule: confirm what was segmented before using anything
    derived from it.

5.4 Runtime parity: any dependency present in the lab runtime but not the
    bundled one must fail loudly, never silently change which detector ran.
    Environment may affect availability, never measured values. Implemented
    as `segmentation_review.require_cv2()`, which probes BY USE rather than
    by import and names the interpreter in its error.

---

## 6. Out of scope

- Calcium kinetics changes beyond the interval gating in 0.3.
- Trained models; all detection here is classical. Correction logs are
  future training material only, and audit sampling stays separate from
  training-data curation.
- Multi-acquisition cohort statistics. Per-acquisition outputs are designed
  to feed a later cohort layer; the schema keeps acquisition ID, strain/line
  and condition fields for that purpose.

---

## Appendix A — carried from the worm side: how to derive an acceptance band

Not part of this spec's implementation. Recorded here because the cultured
cell work will need per-cell area gates in 4.1, and the worm tracker's
acceptance band is the cautionary case.

The tracker rejects a detection whose area falls outside 0.55 to 1.60 of a
reference. **Neither number has any derivation in the repository**, and
together they returned ZERO detections across 234 frames of a recording where
the animal is plainly visible — the masks sat at a median 0.300 of the
reference, so the floor rejected every frame.

The cause is structural rather than numerical. The reference was a
**hand-drawn outline**, which traces the whole animal; the masks come from a
**texture rule**, which captures only where fine structure is resolvable. The
two measure different things, so no choice of band reconciles them.

The proposal, as a spec note and not code:

- **`area_ref` should be the median of the rule's OWN masks over an
  initialisation window**, not a hand outline and not a single frame. Then
  reference and measurement are the same quantity produced by the same
  process, and the comparison is meaningful.
- **Band width should be derived from the mask-area DISTRIBUTION** on
  validated footage — how much a correct mask legitimately varies within a
  recording — and not from ratios to a hand outline. Ratios to an outline
  measure the gap between two different definitions, which is a constant
  offset, not a tolerance.

Measured input already available: across 234 frames the fine-texture rule
returned exactly one blob per frame with areas of 10,082–23,243 px. That
within-recording spread is the quantity a band should be derived from.
