# WINK: Calibration and Ground Truth Pipeline
## Build specification for Codex

Status: draft, ready for Codex review pass
Author: Andres (Vidal Gadea Lab), drafted with Claude
Depends on: existing per module correction logs (append only JSONL, sarcomere peaks and planned flattening/boundary corrections), the batch audit log (see WINK_batch_audit_module_SPEC.md), and legacy human scored datasets that predate the modules entirely

> **Dependency note (added on filing, 2026-08-03):** the batch audit spec
> referenced above is filed alongside this one as
> `docs/specs/batch_audit_module_spec.md`. Sections 2 and 4 here depend on its
> log schema and auto accept threshold, and its own Section 8 defers the
> calibration analysis to *this* spec — build batch audit first, or Section 4
> has no log to read.
>
> What *does* exist today: `app/morphometry_corrections.py` implements the
> append only JSONL correction log described under "Correction logs" below,
> currently written by Myocyte morphometry for every EDITED / MANUAL /
> MANUAL_RECOUNT sarcomere count, with matched / missed / spurious agreement
> counts computed at write time and a `myocyte_id` that joins back to the
> results CSV row.

---

## 0. Purpose

WINK accumulates three structurally different kinds of human judgment, and they are useful for different things. This module reads all three into one queryable store and supports the analyses that turn accumulated review labor into better future analysis.

The three sources, and why the distinction matters:

**Correction logs.** Paired data: what the algorithm proposed, and what the human changed it to. Useful for recalibrating parameters, because you can ask what parameter value would have produced the human's answer. Structurally contaminated by the algorithm's proposal (a human correcting a proposed peak is anchored by where that peak was placed), so these are training and tuning data, not clean ground truth.

**Batch audit logs.** Paired confidence and outcome: what score the module assigned, and whether a human accepted or rejected the item. Useful for calibrating whether a module's confidence score means what it claims to mean.

**Legacy human scored datasets.** Unpaired ground truth: a human's measurement, produced with no algorithm proposal to anchor it. The lab already has these for pharyngeal pumping, defecation cycles, and swimming frequency, movies fully scored by hand that never went through any module. These are the most scientifically valuable of the three precisely because they are uncontaminated, and they should be reserved primarily as a held out validation set rather than spent as training data.

---

## 1. Legacy human scored datasets: intake

### 1.1 Why these are treated differently

Agreement with manual scoring across representative recordings is exactly the definition of technical validation on WINK's existing validation ladder. These datasets are therefore the direct evidence needed to move a module from Experimental to Ready, and that is their highest value use. Spending them as training data would consume that evidence, since a model evaluated on data it was trained on tells you nothing about generalization.

Default policy: legacy human scored data is held out validation data. Any use as training data requires an explicit, recorded decision and a documented split, never a silent default.

### 1.2 Intake requirements

Build an intake path that registers a legacy dataset with, at minimum:

```
{
    dataset_id: str,
    module_target: str,           # which WINK module this is ground truth for
    source_path: str,             # location of the original movies/images
    scoring_records: str,         # path to the human scores (likely a spreadsheet, CSV, or lab notebook export)
    scorer_id: str or None,       # who scored it, if known
    scoring_date: str or None,
    scoring_protocol_notes: str,  # how it was scored, in the scorer's or Andres's words
    blinded: bool or None,        # was the scorer blind to condition
    acquisition_metadata: dict,   # FPS, scale, strain, stage, whatever exists, per WINK's standard fields
    known_limitations: str,       # anything Andres knows about this dataset that a naive user would not
}
```

Expect the scoring records to be heterogeneous, these predate the modules and likely predate any standard format. Build the intake as a mapping step (a small per dataset adapter that reads whatever format exists and emits the standard record) rather than requiring the historical files be reformatted, which would risk transcription error against irreplaceable data.

### 1.3 Known problem: scorer variability is itself unmeasured

Historical manual scoring carries scorer to scorer variability that was probably never quantified, and the manual already flags this for the Fiji kinematics extractor. Where multiple scorers contributed, or where the same movies were scored more than once, capture that, since inter scorer agreement on the ground truth sets an upper bound on how well any module could possibly be expected to agree with them. If a module and a human disagree at about the rate two humans disagree with each other, that is a different finding than a module being wrong.

Where the same movie was never double scored, note it as unknown rather than assuming the single score is exact.

---

## 2. Unified log store

Read all three sources into one queryable store. Do not rewrite the source logs, they stay append only and authoritative, this is a read layer over them.

Minimum common fields across all three sources: module name, module version, item identity, stratum keys (session, plate, strain, batch), human judgment, algorithm output where one exists, timestamp.

Critical: module_version must be respected in every query. A confidence score or a parameter default can mean different things before and after a recalibration, and mixing versions would quietly corrupt exactly the calibration curve this module exists to produce. Any analysis that pools across module versions should have to say so explicitly rather than doing it by default.

---

## 3. Analysis one: parameter recalibration from correction logs

For each corrected item, determine what parameter value would have produced the human's answer instead of the algorithm's. Aggregate across many corrections spanning many recordings, and look for a stable operating point rather than a value that fits one recording.

Report the distribution, not just a best value. A tight distribution across recordings means a genuinely better global default exists. A wide or multimodal distribution means no single value works and the parameter genuinely needs to stay adaptive or user exposed, which is itself a useful finding and should be reported as such rather than forced into a single number.

Stratify this analysis. A recalibrated default that is better on average but worse for one strain or one imaging setup is a regression for that stratum, and a global mean would hide it.

---

## 4. Analysis two: confidence calibration from audit logs

Plot module reported confidence against observed human accept rate, binned by confidence. A well calibrated module's 0.9 bin should be accepted about 90 percent of the time.

Report both the calibration curve and a summary miscalibration statistic. Systematic overconfidence is the dangerous direction (the module claims certainty it has not earned, and batch audit's auto accept threshold is set on that claim), so flag it specifically rather than reporting only a symmetric error measure.

Output a recommended auto accept threshold for batch mode, with the empirically observed error rate at that threshold attached, replacing the current arbitrary default.

---

## 5. Analysis three: module versus human agreement using legacy data

This is the technical validation analysis. Run the module over a legacy human scored dataset it has never seen, and compare against the human scores at the correct unit of inference.

Report agreement in a form appropriate to the measurement type, not one universal number: Bland Altman style agreement plus correlation for continuous measures (pumping rate, swimming frequency), confusion matrix and per class rates for categorical outputs (frame classification, event present or absent), and event level precision and recall with a defined temporal tolerance window for event detection (pBoc events, egg laying events, individual pumps), since an event matched a few frames off is not the same failure as an event missed entirely.

Report disagreements stratified, not pooled. A module that agrees well overall but fails systematically on one condition is exactly the failure mode the batch audit design is built to catch, and this analysis is where it should first be visible.

Never silently rerun this analysis after tuning a module against the same dataset. Once a legacy dataset has been used to tune anything, it is no longer a clean held out set for that module, and any subsequent agreement number from it is optimistically biased. Track use per dataset per module so this cannot happen by accident.

---

## 6. Training set curation (separate from all of the above)

If and when a module moves toward a learned component (GCaMP frame classification and sarcomere peak detection are the two nearest candidates), curation is a distinct pass with different sampling goals from everything above.

### 6.1 The sampling conflict, stated plainly

Batch audit sampling must be representative of its stratum, because the zero defect acceptance math depends on it, cherry picking hard cases there would invalidate the escalation guarantee.

Training curation benefits from deliberately oversampling uncertain and edge cases, since that is where a classifier learns most.

These are opposite requirements. Keep them as two separate sampling passes over the same item pool, never one review session serving both purposes. Record which pass produced each label so the audit statistics cannot be contaminated by curation driven selection.

### 6.2 Split discipline

Split by session or animal, never by frame. Multiple frames from one worm are not independent examples, the same reason repeated frames are not independent N in a behavioral analysis, and splitting naively would badly overestimate generalization.

Report the condition coverage of any labeled pool, not just its total size. A pool of ten thousand frames from three sessions is a weaker training set than one thousand frames spanning thirty, and only the coverage number reveals that.

---

## 7. Outputs

A per module calibration report: recommended parameter defaults with their distributions, confidence calibration curve and recommended threshold, and agreement statistics against any legacy datasets used, with module version and query date stamped on all of it.

A dataset ledger recording every legacy dataset, which modules have consumed it, and in what role (held out validation versus tuning), so its held out status is auditable rather than remembered.

---

## 8. Open questions for Andres before Codex starts

Which legacy datasets exist in a recoverable, machine readable form right now, versus which exist only as lab notebook or spreadsheet records that would need transcription. This determines whether intake is an adapter writing task or partly a data recovery task, and the estimate changes a lot between those.

Whether any of the legacy pumping, defecation, or swimming datasets were double scored by different people, since that sets the ceiling on achievable module agreement and changes how a disagreement should be interpreted.

Whether the pBoc legacy data includes the full cycle series or only accepted event times, since the module's rhythm statistics are currently withheld pending ten continuously followed accepted cycles, and legacy data might satisfy that criterion directly if it is complete enough.

Whether recalibrated parameter defaults should ship as new module defaults, or as a selectable calibration profile alongside the current defaults, given that changing a default silently changes what every past and future analysis means.
