# WINK: pBoc Detection on Three Independent Axes
## Build specification

Changes `tools/defecation/pboc_engine.py`. No existing measurement formula is
replaced; the current detector becomes one of three and keeps its behaviour.

---

## 0. Purpose

Today one composite score decides whether a pBoc happened. This splits the
evidence onto three axes that **fail differently**, and uses their agreement as
a per-event confidence rather than as a vote to be silently resolved.

| Detector | Axis | Fails when |
|---|---|---|
| A — optical flow | motion | contraction is slow or weak; whole-animal translation mimics one |
| B — matched filter on length | geometry | segmentation drops out; animal coils |
| C — periodicity prompt | time | the animal's own cycle is not established |

A and B are image-derived and independent of each other. C uses no image data
at all — only the times of events already found — which is what lets it catch
the case A and B cannot: a contraction they **both** miss. Agreement between A
and B guards against false positives; only C can raise a false negative.

Everything here routes uncertainty to a person. No detector overrules another,
and no detector inserts an event on its own.

---

## 1. What already exists

Grounding, so this is understood as a split rather than a rewrite:

- `calibrated_pboc_score(flow_score, lengths, areas, calibration)` already
  receives flow, per-frame length and area **separately** — the split is cheap
  because the inputs were never actually merged upstream.
- `geodesic_midline(mask)` yields per-frame length; `robust_z` normalises;
  `candidate_events(score_z, fps, contraction_z, recovery_z)` thresholds for
  contraction and recovery.
- `apply_distractor_identity_gate`, `distractor_preflight.py` and
  `defecation_feasibility.py` already handle contamination and feasibility.
- `pboc_reviewer.py` already provides the human review pass this spec routes to.
- Scope stays **pBoc only** — not aBoc, not the expulsion step. Unchanged.

---

## 2. Detector A — flow

Unchanged from the current implementation, but reported as its own verdict
rather than folded into a composite. Emits, per candidate: frame index, score,
and the z-value it crossed.

Keeping it byte-identical matters: any change to interval statistics after this
work must be attributable to B and C, not to A having quietly drifted.

---

## 3. Detector B — matched filter on length

The published approach (Nagy and colleagues for length-based detection; Cermak
and Flavell for the kernel) filters the body-length signal with a kernel shaped
like the DMP contraction, after which simple thresholding suffices.

The difference from the current detector is that a matched filter uses the
event's **shape**, not just its amplitude — so it rejects amplitude-matched
noise that a z-threshold cannot distinguish.

### 3.1 Signal

Per-frame `length_px` from `geodesic_midline`, detrended for slow drift (growth,
posture, focus), resampled to a uniform time base since dropped frames are
common.

### 3.2 Kernel

A contraction–recovery template: shortening to a trough, then recovery to
baseline. Parameterise its width in **seconds** and convert with the declared
fps rather than fixing it in frames — the declared fps is routinely wrong and
`worm_reference.py` exists because of that.

Derive the default width from the lab's own annotated examples, not from a
literature figure, and record which recordings the default came from.

### 3.3 Gaps

Frames with no valid length (segmentation failure, distractor gate, coiling)
are **not** interpolated. Convolution across a fabricated stretch invents a
contraction shape. Mark the span invalid; B abstains there and says so.

---

## 4. Detector C — periodicity prompt

The cycle is regular — roughly 45 s with SD under 3 s at 20 °C — so a missing
event between two confident ones is visible in the timing alone.

### 4.1 The circularity risk, stated first

**Cycle regularity may be the phenotype.** A detector that looks harder where a
regular cycle predicts an event will find more events there, and the intervals
will come out more regular than they are. A mutant whose defect *is* irregular
timing would be corrected toward wild type, and the pipeline would be measuring
its own prior.

The expectation is that most phenotypes shift cycle **duration** rather than
regularity — but that is a hypothesis, not a licence. **Report both, privilege
neither:** mean interval and its dispersion are separate outcomes, each with its
own confidence, and neither is assumed stable in order to measure the other. A
pipeline that assumes regularity in order to recover events cannot then report
regularity as a result.

Every rule below exists to contain that.

### 4.2 Safeguards, all mandatory

1. **The prompt never fills.** C surfaces a time window for human inspection and
   stops. It must not insert, score, or weight an event. A human confirming a
   prompted window is recorded as exactly that.
2. **Period comes from the animal, not the literature.** Estimate the expected
   interval from that recording's own A∧B events. Never seed from 45 s: a
   genuine 70 s mutant would be flagged every 45 s, and each flag is an
   invitation to find something. If the confident events are too few or too
   scattered to establish a period, **C declines** and reports that it did.
3. **Prompted events are tagged for life** (§5), so §8 can report results with
   and without them.
4. **Prompt rate is reported per recording and per genotype**, never pooled. If
   one strain needs twice the prompting, that is a finding about the animals or
   about the detector, not noise to absorb.
5. **Inspection is blind, then revealed.** The reviewer is shown the window and
   scores it with no indication that anything was expected there. Only after
   their call is recorded is the reason revealed. This is strictly better than
   either alternative: the call is uncontaminated by the prior, the reviewer
   still learns why they were asked, and the disagreement between prompt and
   blind verdict becomes a measurable quantity rather than an untestable
   worry. Blind windows must be interleaved with control windows where nothing
   was predicted, or a reviewer will infer the prompt from being asked at all.

### 4.3 Gap rule

Two distinct categories, because they have different likely causes:

- `suspected_missed_event` — the interval is close to an integer multiple of the
  animal's own local median (the clean case: events at 0, 45, 90, 180 flag 135).
- `long_interval` — the interval is well outside the local spread but not near a
  multiple (0, 45, 90, 160). Flagged separately: this may be a real pause rather
  than a miss, and conflating the two would hide genuine biology.

Both use the recording's own local median and spread, never fixed constants.

---

## 5. Event provenance

Every event carries how it was found. Without this, §8 is impossible.

```
detected_by      : "flow" | "length" | "both"
prompted_by_periodicity : true | false
human_confirmed  : true | false | null
agreement        : "both" | "flow_only" | "length_only" | "prompt_only"
flow_score, length_score, expected_interval_s, local_median_interval_s
detector_abstained : [] | ["length"]      # e.g. B in an invalid span
```

`agreement` is diagnostic, not just a confidence tier — *which* detector fired
narrows the failure mode, and that is more useful to a reviewer than a number.

---

## 6. Routing

| Agreement | Action |
|---|---|
| both | accept, high confidence |
| flow only | review — check for translation or a length dropout |
| length only | review — check for a slow or weak contraction |
| prompt only | review — the window, presented as a window |
| neither | no event |

Anything not `both` goes to `pboc_reviewer.py`. Nothing is discarded silently
and nothing is promoted silently.

### 6.1 The inspection window

The module reports a count — "3 periods flagged for inspection" — and clicking
it moves the scrubber to that stretch of the recording. The reviewer is not
asked to find anything or to name anything. They answer one question: did a
pBoc happen here.

- the window opens **several seconds before and closes several after** the
  stretch in question, long enough to see a full contraction and recovery.
  Derive that padding from the kernel width (§3.2), not from a magic number.
- the reviewer scrubs **forward and backward freely** — confirming that nothing
  happened requires watching it not happen, which a single still cannot show.
- **event present:** mark start, peak and end, clicking the tail tip, matching
  the marking workflow students already use elsewhere in the tool.
- **event absent:** one button.
- advance to the next.

No label, no category, no free text. The reviewer records what they saw; the
module works out what that implies about itself (§8.2).

**Blinding is a property of this window** (§4.2.5), and it is easy to break:

- do **not** draw a marker at the predicted time, and do not centre the window
  on it — either one announces the prediction. Randomise the offset within the
  padding.
- interleave **control windows** where nothing was predicted, drawn from spans
  the detectors called clean, and make them indistinguishable from prompts.
  Without controls, being asked at all is the tell, and the reviewer's answer
  is contaminated no matter what the window looks like.
- reveal the reason **after** the call is recorded, never before.

**Agreement is not truth.** A and B can share a bias — a reversing animal, for
instance. Agreement means "two disjoint failure modes did not both fire here",
which is worth exactly as much as §8 measures it to be worth, and no more.

---

## 7. Censoring and inclusion criteria

The archive is fixed and cannot be re-filmed, so some recordings will not
support scoring at any threshold. That is an acceptable outcome; discovering it
by tuning is not.

1. **Fix the minimum usable fraction per recording before the pipeline runs.**
   Record it in the spec or a config file with a date, not in a notebook after
   the fact.
2. **Never censor on disagreement.** Disagreement preferentially marks
   *ambiguous* events, and ambiguity is not randomly distributed — if a mutant
   has weaker or slower contractions it will disagree more, so censoring would
   cut hardest exactly where the phenotype lives and shrink the difference being
   measured. Disagreement routes to review; review decides.
3. Censor on **segmentation confidence and distractor contamination** — causes
   independent of whether an event occurred — and censor whole spans, not
   individual events.
4. Report the surviving fraction per recording, and compute interval statistics
   with methods that handle censored data rather than concatenating survivors.

---

## 8. Error accounting: every inspection measures the detector

Manual review is not only correction. Each inspected event is a labelled sample
of detector performance, and enough of them turn "we reviewed it" into a
**measured error rate attached to the result**. That is the difference between
a number and a number with a stated certainty.

### 8.1 Use the contract that already exists

Do **not** build a bespoke error store here. `batch_audit_module_spec.md` §1
already defines a per-item confidence record (`confidence`, `abstained`,
`abstain_reason`, `stratum_keys`, `evidence_path`, `module_name`,
`module_version`), §8 of that spec already notes the audit log becomes a
labelled confidence-versus-truth dataset, and
`calibration_ground_truth_pipeline_spec.md` §4 already turns it into a
calibration curve with a recommended threshold and its observed error rate.

pBoc emits that record per event and becomes the first real consumer of it. A
second, parallel confidence system would have to be reconciled with the first
later, and the two would disagree.

Mapping to the contract:

- `confidence` — derived from §6 agreement (`both` > single detector >
  prompt-only). The mapping is a *claim*, and §8.3 is what tests whether the
  claim is honest.
- `abstained` — true where detector B abstained on an invalid span (§3.3), or
  where detector C declined for want of an establishable period (§4.2.2).
  Abstained items are never auto-accepted, per that contract.
- `stratum_keys` — strain, session, plate, recording, plus `agreement` so the
  sampler can stratify on it.
- `evidence_path` — the length trace and flow score around the event, which is
  what a reviewer actually looks at.

### 8.2 Failure logging on every confirmed miss

When a human confirms an event the detectors did not find — regardless of how
it surfaced — log a failure case, not just a correction:

```
missed_by        : ["flow"] | ["length"] | ["flow","length"]
surfaced_by      : "periodicity" | "review_sweep" | "other"
marked_start_s, marked_peak_s, marked_end_s    # from §6.1
signal_at_event  : length trace, flow score, both detector margins, over the
                   marked span
```

**The reviewer assigns no cause.** Asking a student why the algorithm failed is
asking them to do the developer's job, and a person required to pick a reason
will supply one — invented causes are worse than none, because they look like
data. The reviewer records what they saw; the marked span plus the stored signal
is what makes the failure diagnosable.

Cause is **derived**, later and in bulk, from those stored signals: a set of
confirmed misses whose length excursions are consistently shallower than the
kernel expects says the kernel width is wrong, and it says so from measurement
rather than from a dropdown. A pile of misses is not improvement; a pile of
misses with their signals attached is.

### 8.3 What the results carry

**There is no minimum audit count.** Accuracy is reportable from the first
confirmed event, because it is never reported alone:

```
Accuracy = X% @ N = Y
```

N is not a footnote, it is half the statement, and the two travel together
everywhere — no summary, plot axis or exported column may carry one without the
other. As N grows the claim tightens on its own, and no arbitrary gate is needed
to stop anyone overclaiming, because the claim visibly limits itself.

One addition, because readers systematically under-read small N: report a
**confidence interval alongside**, Wilson score or equivalent, so
`100% @ N=1` presents as `100% (95% CI 21–100), N=1`. The interval does the
work the missing threshold would have done, and does it continuously rather
than at a cliff.

Every reported interval statistic therefore ships with:

- accuracy, N, and interval **for that stratum**, not a global figure
- the fraction of contributing events that were human-confirmed
- the calibration state of the confidence score, or an explicit statement that
  too few audits exist yet to calibrate it

Per `batch_audit_module_spec.md` §8, build the *log schema* now and the
calibration analysis later — but the schema must capture what calibration will
need, or the early data is wasted.

### 8.4 Error is a data stream, not a verdict

Detector accuracy is not a fact established once. It moves every time the code
changes, and a change that buys accuracy often spends processing time — or the
reverse. Both belong on a timeline, keyed by module version, so a trade can be
seen and argued with rather than discovered months later.

Per run, alongside the §8.1 record:

```
module_version, commit_sha
benchmark_set_id                  # which frozen recordings this was measured on
processing_seconds                # excluding human review time
machine_id, cpu, cores            # a faster laptop is not an optimisation
n_events, n_audited
sensitivity, false_positive_rate  # from audits on the benchmark set
```

Four things make the plot trustworthy rather than decorative:

1. **A frozen benchmark set.** Versions can only be compared on the same
   recordings. Measuring v1 on animals A–C and v2 on D–F produces a difference
   that says nothing about the code. Freeze a set with manual ground truth,
   version it, and re-run every release against it.
2. **The benchmark is not the tuning set.** Otherwise the curve plots
   overfitting and calls it progress. Apply
   `calibration_ground_truth_pipeline_spec.md` §6.2: split by session or animal,
   never by frame, and report condition coverage rather than only pool size.
3. **Normalise or record the hardware.** Processing time is meaningless across
   machines. Either pin a reference machine for benchmark runs or record
   `machine_id` and compare only within it.
4. **Link version to commit.** A regression on the plot must point at a diff,
   otherwise the graph tells you something broke and not what.

Plot accuracy against processing time with points labelled by version, so the
frontier is visible and a trade can be accepted or rejected deliberately. A
change that costs three points of sensitivity to halve runtime may be a good
deal for a batch sweep and a bad one for a final analysis; that is a judgement
the lab should make while looking at both numbers.

**Where this belongs.** Nothing above is specific to pBoc, and building it here
would strand it. Half already exists: several modules write per-run timing
records (`_timing.json`, `timing_report.json`) that are currently discarded
after each run. The right home is the unified log store in
`calibration_ground_truth_pipeline_spec.md` §2, with pBoc as the first module to
emit the version-keyed record. Note these records belong in the **log store,
not in git** — they were deliberately excluded from version control precisely
because they change every run, which is what makes them a data stream.

---

## 9. Validation

### 9.1 When two marks are the same event

Pairing a reviewer's marked peak with a detector's decides every count in the
confusion matrices below, so the rule must be measured rather than picked. The
rule is **within 1 SD, taking the most permissive of the available spreads** —
in practice the interval SD, roughly 3 s at 20 °C.

The reason to prefer the widest is that **the costs are asymmetric**:

- Too strict, and a single well-detected event is split into two errors — the
  detector's peak is scored a false positive *and* the reviewer's mark a missed
  event. Strictness does not merely fail to credit a match; it manufactures a
  pair of errors from a success, and it does so precisely where the detector was
  working.
- Too permissive, and two genuinely distinct events could be merged. But events
  sit roughly 45 s apart, so this cannot happen at any tolerance remotely near
  3 s. The failure mode the strict rule invents is real; the one the permissive
  rule risks is not reachable.

Rejected alternative: the detector's own peak error against ground truth. Using
it to define agreement is circular — the detector would be judged against a
tolerance derived from its own performance, so a sloppier detector would earn a
wider one and score no worse.

Report the tolerance in seconds beside every matrix, and state the interval SD
it came from. **Guard rail:** if the tolerance ever exceeds roughly a quarter of
the local median interval, pairing has stopped being meaningful and the matrices
must say so rather than quietly counting.

Worth measuring separately, though not required for the first version: the SD of
**reviewer against reviewer** on the same events. That is the floor on how well
any detector can be scored — a detector cannot be shown to be more precise than
the marks judging it.

### 9.2 Matrices

This is also how the matched filter earns its place, so it is not extra work —
running both detectors *is* the comparison.

Against the lab's existing manual annotations, following Cermak and Flavell's
own validation shape:

- confusion matrix for **A alone**, **B alone**, and **A∧B**
- sensitivity and false-positive rate for each, per recording and pooled
- how many true events A and B **both** missed, and how many of those C surfaced
  — the number that justifies C existing at all
- how often C prompted where no event was there, per genotype
- interval mean and SD computed **with and without** prompt-surfaced events;
  if a conclusion holds only with them, that must be visible

Validation runs must be reproducible from the manifest and must not overwrite
manual annotations.

---

## 10. Outputs

- per-event rows with the §5 provenance fields
- per-recording QC: usable fraction, censored spans with reasons, prompt rate,
  detector abstention spans
- `pboc_detector_provenance.json`: kernel width and where the default came
  from, thresholds, inclusion criteria and the date they were fixed, detector
  versions
- the validation report of §8

---

## 11. Non-goals

- no aBoc or expulsion scoring
- no automatic insertion of events by any detector
- no change to detector A's numbers
- no re-tuning of thresholds after seeing interval results
- not a replacement for human review

---

## 12. Open questions for Andres before the build starts

1. **Minimum usable fraction** — what is it, and is it per recording or per
   animal? Must be fixed before any run (§7.1).
2. **Kernel source** — which annotated recordings should the default kernel
   width be derived from? They should be representative rather than the
   cleanest available.
3. **Manual annotation set** — where does the ground truth for §8 live, and how
   many animals and genotypes does it span?
4. ~~Prompt presentation~~ — resolved: blind, then revealed after the call is
   recorded, with control windows interleaved (§4.2.5).
6. ~~Cause list~~ — dissolved: the reviewer assigns no cause. Presence, absence
   and the marked span are recorded; cause is derived from the stored signals
   in bulk (§8.2).
7. ~~Audit volume~~ — resolved: no minimum. Accuracy is always reported as
   `X% @ N=Y` with an interval, so it limits itself (§8.3).
8. **Control window rate** — what fraction of inspection windows should be
   controls (§6.1)? Too few and blinding leaks; too many and reviewer time goes
   to windows with nothing in them.
9. ~~Marking tolerance~~ — resolved in principle: **within 1 SD**, measured
   rather than chosen, since any fixed number would be a guess. See §9.1 for
   which SD, because three are available and they differ by an order of
   magnitude.
5. **Long-interval category** — is a genuine pause biologically expected in your
   strains? That decides whether `long_interval` is a QC flag or a result.
