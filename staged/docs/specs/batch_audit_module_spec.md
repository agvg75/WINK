# WINK: Batch Audit Module
## Build specification

Status: draft for review
Author: Andres (Vidal Gadea Lab), drafted with Claude
Depends on: an existing per item confidence signal in the calling module (the abstain gate pattern already built in `gcamp_recoverable.py` is the reference implementation), the Sample planner's statistical core (Welch / Mann-Whitney / Shapiro-Wilk / Levene fork already validated against SciPy)

---

## 0. Purpose and philosophy

Human in the loop review does not disappear at terabyte scale, it moves from per animal to per batch, and it has to be a statistically sized, stratified sample rather than an arbitrary "check twenty of them." This module is the shared machinery that lets any WINK tool with a confidence score expose an unsupervised batch mode without each tool inventing its own audit logic.

The risk this module exists to catch is systematic failure, not random noise. Random error averages out with more data, a detector that fails the same way every time contrast is low or two worms are close together does not, it just produces more confidently wrong output at scale. The core design principle follows directly: sampling must be stratified by whatever correlates with acquisition conditions (batch, session, plate, strain), never purely global random, because a global random sample can entirely miss a stratum that failed completely if that stratum is small relative to the whole dataset.

This is not a replacement for existing per animal review workflows. It is an additional mode, opted into explicitly, for datasets where full per item review is not the efficient choice.

---

## 1. The confidence interface contract

Any WINK module that wants to plug into batch audit must expose, per processed item, a small standard record:

```
{
    item_id: str,
    confidence: float,          # 0 to 1, module defined meaning, but must be monotonic (higher = more trustworthy)
    abstained: bool,            # true if the module itself refused to produce a default, per the existing abstain gate pattern
    abstain_reason: str or None,
    stratum_keys: {             # one or more grouping keys the audit sampler will stratify on
        "batch": str or None,
        "session": str or None,
        "plate": str or None,
        "strain": str or None,
        # modules may add their own keys, the sampler treats this as an open dict
    },
    evidence_path: str,         # path to an overlay/figure a human reviewer can inspect quickly, same convention as existing QC overlays
    module_name: str,
    module_version: str,
}
```

Items where `abstained` is true are never eligible for auto accept regardless of any confidence value, they route directly to full review, this is unchanged from the existing per module abstain behavior, batch audit does not override it.

---

## 2. Stratification

Before sampling, group all non abstained items by their `stratum_keys`. A stratum is the smallest unit that plausibly shares a common failure cause, in most WINK datasets this will be one acquisition session or one plate, not the whole dataset and not single animals.

If a module does not supply meaningful `stratum_keys`, batch audit should refuse to run in unsupervised mode for that module's output and say so explicitly, rather than silently falling back to global random sampling. This mirrors the existing calibration rule (a missing scale value stops analysis rather than assuming a default).

---

## 3. Sample size and acceptance criteria

This is acceptance sampling, the same formal problem as accepting or rejecting a manufacturing lot from a small inspected sample, and it should be solved with the same math rather than an intuitive sample size.

For each stratum of size N, the module computes the smallest sample size n such that, if the true defect rate in the stratum were at or above a specified acceptable quality level (AQL, a target maximum tolerable error rate, module and study specific, default suggestion 5 percent pending Andres's input per module), the probability of the sample containing zero defects is below the chosen alpha (default 0.05). Use the hypergeometric distribution for the exact calculation given finite N, falling back to the binomial approximation only when N is large enough that the two agree closely (standard rule of thumb, sample size under about 5 percent of population).

This produces a zero defect acceptance rule (c = 0 sampling plan): draw n items, if zero are rejected on review, accept the whole stratum's auto accepted output; if one or more are rejected, escalate.

Expose this as a small standalone function so it can be reused anywhere, following the same pattern as the Sample planner being callable both standalone and from a module export:

```
required_sample_size(N: int, aql: float, alpha: float) -> int
```

Also expose the reverse computation, given a chosen n, what error rate would zero defects in that sample actually rule out at the chosen alpha, since Andres will sometimes want to check "is a review budget of n per stratum actually good enough" rather than solve forward from an AQL target.

---

## 4. Escalation rule

If the audit sample for a stratum contains any rejected item, that stratum does not simply get a flag noted next to it, its entire auto accepted output routes to full per item review. This is the mechanism that catches a systematic failure before it propagates into a terabyte of accepted numbers. Do not average the stratum's error rate into a dataset wide number and proceed, one confirmed defect in a zero defect sample is evidence the failure mode is systematic to that stratum specifically, not a rounding error to be diluted.

A stratum that passes its acceptance sample is labeled accepted with the audit's sample size and AQL recorded as provenance, not silently treated as equivalent to a fully reviewed item.

---

## 5. Audit review UI

A minimal reviewer interface, following existing WINK QC overlay conventions rather than inventing a new visual language:

Present the sampled items for one stratum at a time, in a contact sheet style view similar to the GCaMP triage pipeline's existing pagination.

Each item shows its evidence overlay, its module reported confidence score, and accept / reject / uncertain controls. Uncertain does not count as a pass for the zero defect rule, it is treated the same as reject for the purposes of escalation, since ambiguity is itself evidence the item should get full review.

After the reviewer finishes a stratum's sample, immediately report the stratum's outcome (accepted or escalated) rather than waiting until the whole dataset's sampling is complete, so a lab member running this overnight can see partial progress and does not have to wait on every stratum to see any result.

---

## 6. Provenance and logging

One shared, append only JSONL log, following the same schema principle already established for sarcomere corrections and the flattening/boundary modules. Each record captures: module name and version, `item_id`, stratum keys, confidence score, sample inclusion (whether this item was part of the audit sample for its stratum), reviewer decision if sampled, AQL and alpha used for that stratum's sample size calculation, and timestamp.

This log is not just an audit trail. It is the dataset that lets confidence thresholds be recalibrated later per module (see section 8), the same "enabling future recalibration" investment already made elsewhere in WINK.

---

## 7. Status labeling: Batch audited

Add a new status word to the validation ladder, distinct from Ready and Experimental: **Batch audited**. This label means a dataset was processed in unsupervised batch mode, with every stratum either passing a statistically sized zero defect acceptance sample or escalated to full review, and it should never be conflated in a methods section with full per item human review.

Minimum methods reporting for a Batch audited dataset: AQL and alpha used, sample size per stratum, number of strata escalated versus accepted, and the underlying module's confidence score definition. This is an extension of the existing minimum methods reporting list, not a separate one.

Batch audited output can plausibly support technical validation level claims once the acceptance sampling confirms an acceptable error rate, consistent with the existing validation ladder definition, but it does not on its own support biological validation, which still requires the usual cross condition and confound checking any other tool's output needs.

---

## 8. Confidence calibration over time

Because the audit log pairs every sampled item's module confidence score with a human accept/reject outcome, it becomes a growing labeled dataset per module: confidence score versus ground truth correctness. Once enough audit records accumulate for a given module, this can support two things later, neither required for the first version. First, checking whether a module's confidence score is actually well calibrated (does 0.9 confidence really mean about 90 percent correct, or is the module systematically overconfident or underconfident). Second, tuning the auto accept threshold itself away from an arbitrary default toward a value with an empirically measured error rate behind it.

Do not build the calibration analysis in the first version, just make sure the log schema captures what a future calibration pass would need, same enabling versus fine tuning distinction already used elsewhere in WINK's design principles.

---

## 9. Module readiness: which WINK tools are good first candidates

Good candidates, since failure already tends to self flag or the review unit is naturally coarse: **Population orientation** (identity free by design, no per worm identity to get wrong), **Population swimming plus modality review** (already produces a pending versus reviewed bout split, batch audit just replaces the ad hoc pending threshold with a statistically sized sample), and the **GCaMP triage pipeline** (already architected around contact sheets and confidence adjacent classification).

Riskier candidates, where a wrong answer looks identical to a right answer and a single error is expensive: **Track one worm's** spine and head assignment (a flipped head reverses every downstream sign without looking visibly wrong), the **pBoc calibration** (three landmark clicks anchor everything that follows), and the **boundary and volume module** (a wrong surface produces a plausible looking, entirely fabricated volume). These can still use batch audit, but the AQL should be set stricter (lower tolerable error rate) and ideally paired with a known ground truth subset, such as the bead calibration already planned for the volume module, rather than relying on confidence scores alone, since for these modules confidence measures internal consistency, not necessarily correctness.

---

## 10. Relationship to existing infrastructure

Reuse the Sample planner's validated statistical core rather than reimplementing distribution logic from scratch, this module's acceptance sampling calculation is a sibling computation to the planner's power analysis, not a separate statistics stack.

Reuse the abstain gate pattern from `gcamp_recoverable.py` as the reference implementation of what a module's confidence signal should look like, plateau versus isolated spike as the confidence basis, explicit abstain rather than a guessed default, this module generalizes that pattern rather than introducing a new one.

Reuse the existing contact sheet pagination UI pattern from the GCaMP triage tooling for the audit review interface rather than building a new reviewer UI from scratch.

---

## 11. Open questions for Andres before the build starts

Default AQL per module category. A single dataset wide default (5 percent suggested above) is a placeholder, the riskier modules in section 9 probably warrant a stricter default, worth deciding module by module rather than accepting one number everywhere.

Whether escalated strata should automatically fall back to the tool's normal per item human in the loop workflow, or route to a separate expedited review queue, since a fully escalated stratum could still be large.

Whether the Batch audited status should be visible per stratum in the Hub UI (some strata batch audited, others escalated to full review within the same dataset) or only reported at the whole dataset level once every stratum resolves.
