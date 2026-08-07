# Claude Science cohort: execution plan and measurement model

Status: draft for review
Date: 6 August 2026
Project: A whole-animal platform for tissue-specific muscular dystrophy phenotyping
Funded period: 1 September to 1 December 2026

---

## 1. Purpose of this document

The grant proposal commits to a scientific claim and a set of deliverables. This
document translates those into a measurement model and an ordered list of build
tasks. It supersedes nothing in the proposal; where the two differ, the
differences are called out explicitly in section 7.

Read the session index at
`L:\10_AGVG LAB\Lab Tools\_session_archive\SESSION_2026-08-06_INDEX.md`
first for the state of the codebase. This document does not repeat it.

---

## 2. The scientific claim

Duchenne muscular dystrophy does not affect all muscles equally. Comparisons
across separate animals cannot resolve whether tissues decline together or
independently, because biological variation is confounded with tissue identity.

The claim requires **within-individual covariance** across muscle groups. That
requirement, not the pipeline, is what constrains every design decision below.

### Tissue coverage

Three muscle groups are accessible, with different origins and demands:

| tissue | functional readout | structural readout |
|---|---|---|
| body wall (striated) | crawling kinematics, body bends | confocal, head stacks |
| pharyngeal (cardiac-like) | pumping rate | confocal, head stacks |
| enteric | defecation cycle | none currently |

Two facts make this tractable:

1. A single confocal stack of a head contains **both** body wall and pharyngeal
   muscle. Two tissues, one animal, one acquisition, one moment. This is genuine
   within-individual structural covariance, not a between-cohort comparison.
2. A single behavioral recording often contains **more than one** functional
   readout. A defecation movie contains bouts of crawling and bouts of pumping.

The strongest claim available is therefore: **two tissues (body wall and
pharyngeal), paired structurally within individuals, and paired functionally
within individuals.**  Enteric muscle adds a third functional readout with no
structural counterpart.

### What is not available

Behavior and confocal are separate preparations. No animal currently has both.
The morphology leg and the behavior leg are each internally within-individual,
but they are between-individual **with respect to each other** — so no analysis
may pair a structural measurement with a functional one from the same animal.
Do not write code or analysis that implies otherwise. If prospective paired
acquisition (film, then mount and image the same animal) becomes possible, that
is a future extension, not part of this project.

---

## 3. Measurement model

### 3.1 The unit is the bout, not the recording

A recording is not eligible or ineligible. It yields some quantity of usable
material per readout, and that quantity differs by readout within the same file.

For every recording, produce a per-readout budget:

```
recording_id, readout, usable_seconds, n_bouts, longest_bout_s,
  unusable_seconds_not_performing, unusable_seconds_not_visible
```

`usable_seconds` is the aggregate across bouts. A recording can be rich for
pumping and useless for defecation.

### 3.2 Duration thresholds differ by an order of magnitude

These are starting values, to be set from the physiology with margin and then
validated, not tuned until output appears:

| readout | governing rate | minimum usable bout | notes |
|---|---|---|---|
| pumping | approx. 4 to 5 Hz | a few seconds | frame rate set by EVENT DURATION, not by the rate — see 3.2.1 |
| crawling | undulation period | at least one full cycle | waveform metrics need several |
| defecation | approx. 50 s cycle | several cycles, so minutes | duration-bound, not frame-rate-bound |

Frame rate governs eligibility for pumping. Duration governs eligibility for
defecation. Both govern crawling.

**Aliasing is the dangerous failure.** A 10 fps recording will produce a pump
count that looks plausible and is wrong. This is the same failure shape as the
fake dose response fixed in v11.136: a confident number produced from an
inadequate input rather than an obvious failure. Set the frame-rate gate from
the pump event duration with margin, and refuse below it rather than reporting
a number with a caveat.

#### 3.2.1 The pumping floor is not a Nyquist calculation

The four-samples-per-undulation rule used for crawling and swimming assumes a
roughly sinusoidal signal. **Pumping is not one.** It is a brief discrete
event — a grinder contraction on the order of 100 to 200 ms — separated by
longer intervals. The requirement is detecting and counting individual
transients without merging or missing them, not resolving a waveform.

Applying the sinusoid rule to a 4–5 Hz pump rate yields roughly 16–20 fps. At
20 fps a 150 ms pump spans two to four frames, which is marginal, and a pump
falling between frames vanishes entirely. **The floor is set from event
duration and lands nearer 30 fps.**

This reasoning is encoded in `app/acquisition_check.py` alongside the number,
because otherwise someone will apply Nyquist to a non-sinusoidal signal and
"fix" the floor back down to 16. The checker reports **sampling margin** —
frames per pump event — rather than a bare pass.

### 3.3 Unusable time must be attributed to a cause

Two reasons a bout is unusable, and they are not interchangeable:

- **Not performing.** The animal was not pumping. This is biology. It is data.
  It should contribute to the rate estimate as a genuine low value.
- **Not visible.** The animal was pumping, but the head was out of focus, out
  of frame, or the contrast was inadequate. This is acquisition failure. It is
  missing data. It must reduce confidence, not the measured rate.

Conflating these lets poor recordings masquerade as low pump rates. The bout
classifier must distinguish them, and only "not visible" reduces the confidence
weight.

Where the classifier cannot tell, it abstains rather than guessing. Reuse the
existing abstain gates rather than inventing a parallel mechanism.

### 3.4 Every metric carries its own n and confidence

A pump rate from 11 scattered seconds is not the same measurement as one from
four continuous minutes. Both are useful; they are not equally weighted.

Each per-animal metric carries `usable_seconds`, `n_bouts`, and a confidence
weight derived from them. These propagate into the covariance analysis: an
animal with plenty of crawling and thin pumping contributes less to the
correlation than one with plenty of both.

Do not impute. Do not fill. Thin is thin, and the analysis should reflect it.

---

## 4. Reference pools and relative scoring

This is the architectural core and it determines the value of the archive.

### 4.1 Two populations, two jobs

**Single-readout recordings** are plentiful and were filmed under conditions
optimised for that one measurement. They are the best available estimate of
what normal looks like for a given strain and condition. They build the
**reference pool**.

**Multi-readout recordings** are compromised for every readout, because they
were optimised for none of them. They are fewer. They carry the
**within-individual claim**.

No eligible recording is wasted. The majority builds the reference; the
minority carries the covariance.

### 4.2 What this buys

It separates two questions the proposal was treating as one:

- *Population level*: does this strain pump more slowly than wild type?
  Answered from the large single-readout pools.
- *Within individual*: does this animal's pumping deficit travel with its
  crawling deficit? Answered from the multi-readout set, with each animal's
  readouts expressed **relative to strain reference** rather than in absolute
  terms.

Expressing relative to reference removes between-strain variance that would
otherwise swamp the covariance being looked for.

### 4.3 Acquisition offset: measure it, or declare it unmeasurable

A pump rate measured from scattered bouts in a defecation movie is not directly
comparable to one from a dedicated pumping recording; the acquisition
conditions differ. Recordings that carry both a good bout and reference-quality
conditions are what would allow this offset to be **measured**.

**Count that set before planning to use it.** It is the intersection of two
uncommon properties and may be small or empty. If it is small, the offset
estimate is noisier than the bias it removes.

- Adequate n: estimate the offset and correct for it.
- Thin n: **report the two populations separately and state in the results that
  cross-calibration was not possible.** Do not apply a noisy offset correction.
  A stated gap is honest; a correction that adds more variance than it removes
  is not.

Do not assume the offset is zero either. Say which of the three cases applies.

### 4.4 Thin reference pools must be flagged, not used

Some strains will have many recordings across several students and years.
Others will have three recordings from one student in one week. A reference
built from three animals makes every deviation look significant.

Set a minimum pool size. Below it, the strain is flagged and excluded from
relative scoring rather than silently producing overconfident deviations.

### 4.5 Held-out validation

The legacy human-scored datasets (pharyngeal pumping, defecation, swimming
frequency) remain held out by default. They are the check on whether the
automated reference is right, and they must not be seen during development.

If the automated pump rate for a strain matches what a person scored by eye
years ago, that validates the whole chain. If it does not, that must be
discovered before the covariance analysis rests on it.

Audit sampling and training data curation stay separated, as already specified
in the batch pipeline design.

---

## 5. Eligibility as the gating unknown

The proposal's October text says "eligible recordings across the archive."
Nothing currently defines eligible. The archive is approximately 16 TB.

This is not housekeeping ahead of the real work. **It determines n.** If a
recording cannot be resolved to individual animals, it cannot contribute to a
within-individual claim regardless of pipeline quality. Historical data contains
mixed multi-worm recordings; session marking exists to solve exactly this.

### 5.1 First question to answer, and it is cheap

Before any general characterisation of the archive, answer this:

> How many recordings clear the frame-rate threshold for pumping, and of those,
> how many also have the whole animal in frame, per strain and condition?

Frame rate and dimensions come from **headers alone**. No pixel needs to be
read.

**Measured, 6 August 2026:** on the L drive, a header read costs a median
84 ms and a listdir 13 ms, giving roughly **3 minutes for a header pass over
the whole folder inventory**. This is not a days-long characterisation and it
is not a one-shot: it is **rerunnable whenever a threshold changes**. Design
0.1 as a repeatable pass whose thresholds are inputs, not constants, so a
revised pumping floor re-classifies the archive in minutes rather than
requiring a new campaign.

**`.lif` measured too, 6 August 2026:** 0.13–0.15 s per file, and **flat with
respect to file size** — a 1.8 GB file and a 9.6 GB file cost the same, because
only the header XML is parsed and no image data is touched. Vendor format is
therefore not the expensive case it was assumed to be, and the confocal census
in 0.2 is minutes rather than hours. Item 0.8 is closed.

### 5.2 Second question, equally cheap

> How many head confocal stacks exist, across which strains and years, and do
> they carry usable calibration metadata?

This is a smaller query than characterising the whole archive. If that set is
healthy, the morphology leg delivers two-tissue within-individual data **without
depending on the behavioral archive being resolved to individuals**. That
derisks the project, because session marking across 16 TB is the largest
unknown.

### 5.3 Branch point

- Healthy dual-readout behavioral pool: October proceeds as proposed.
- Thin dual-readout pool, healthy confocal set: morphology leads in October;
  behavior becomes single-readout across a larger n, feeding reference pools.

Make this decision on data, in September, not on preference. The date depends
on item 0.8, since the confocal census cost is currently unknown.

---

## 6. Work items

Ordered. Items in phase 0 need no grant credits and should be done before
1 September.

### Phase 0: before 1 September

**0.0 SMB mount test from the MacBook.** *(owner: Andrés)*
Whether the MacBook Pro can mount the ISU SMB share. Moved here from section 7
because it is a one-hour test that gates months of phase 1 work: if the share
cannot be mounted, the entire compute topology changes. Does not block the
build queue.
Acceptance: mounted and readable, or a documented failure with the alternative.

**0.1 Header pass for readout eligibility.**
Extend `probe_timing.py` into a production header pass over
`L_drive_inventory.csv`. Output per recording: frame rate, dimensions, duration,
bit depth, channel count. Then classify which readouts each recording could
support on acquisition grounds alone. No pixels.
Thresholds are **inputs, not constants** — see 5.1.
Blocked by 0.4a's pumping floor, which defines the threshold being applied.
Acceptance: a table answering 5.1, plus counts per strain and condition, and a
rerun after a threshold change that completes in minutes.

**0.2 Confocal head stack census.**
Answer 5.2. Count, strains, years, calibration metadata presence.
Unblocked: `.lif` headers read in 0.15 s flat (item 0.8, closed), so the census
costs about a second per ten files and the 5.3 branch date does not depend on
it. `app/cell_calcium_lif.series_list()` already returns name, dimensions,
frame count, channel count and bit depth per series without touching pixels.
Acceptance: a table, and a go or no-go on the morphology leg leading.

**0.3 Folder provenance proposal pass.**
Use `lab_name_authority.xlsx` (101 people, 19 project lines) against
`LABEL_ME_L_drive.csv`. Write proposals to a **separate** file; never write into
the label CSV. Every proposal carries the matched token, source table, and
confidence tier. Exact normalised match ranks above fuzzy. A bare four or five
digit number never matches an allele alone, because dates look identical.

Two findings from the first pass are now requirements:

- **The People sheet needs a `given_name` column.** The drive is organised by
  given name; the authority is keyed by surname. Surnames match **zero** of 551
  paths while `monica` alone matches 475. Seeded from the lab people page;
  the remainder is filled by hand.
- **Matches must be weighted by path depth.** A token found in an ancestor
  folder is inherited by every descendant and is ONE fact, not N. A single
  `\Monica\` parent produced 475 identical proposals in the first pass.
  Match on the most specific component and mark inherited matches as such.

Acceptance: proposals sortable by confidence, high tier reviewable at a glance,
and inherited matches distinguishable from matches on the folder itself.

**0.4a Acquisition floors and checker.** *(done)*
A one page document for the scope and a checker that reads a short test
recording and reports pass or fail per requirement, per readout.
Acceptance: the checker runs on a real test recording and its verdict is
defensible line by line.

**0.4b Bout budget.** *(moved to phase 1)*
Not "can this be analysed" but "what fraction of this yields usable bouts per
readout" — `usable_seconds`, `n_bouts`, and unusable time split by cause. That
is a number Mackenzie can improve by changing how she films. Requires the 3.1
bout classifier, which does not exist, so it is phase 1 work.
The original 0.4 carried one acceptance criterion for two different
deliverables; splitting them is a correction to this document, not a change of
scope.

**0.5 Fix basal slowing area gates.** *(done)*
The stale backlog said `min_area=40, max_area=2500` were "hardcoded near line
691". **That was wrong and was carried into this document unverified.** The
library had derived the gates correctly from `um_per_px` since backlog #12.
The defect was that the GUI held 40 / 2500 / 60 as its defaults and passed them
into `analyze()` as explicit overrides on every run, and `area_gates_for` was
written to always honour an explicit value — so the correct gates were computed
and then discarded, every time, on every machine.
Fixed by removing raw pixel gates from the API entirely and making tuning a
multiplier on the computed value, with a frame-size fallback when no
calibration exists. 4K regression fixture included.

**0.6 Session mark commit path.** *(done)*
The writer existed and was unreachable. `FrameRangeSelector` had "Accept
ranges" and "Cancel", correctly wired to `episode_range`, which the loader
already honoured. They sat in a frame packed after an expanding preview, so Tk
squeezed them to one pixel on any recording with frames of about 512 px or
more. Fixed by packing the fixed-height rows first. Session marks are now
persisted through a new `app/gcamp_session.py`, since `segmentation_review`
names `single_channel_gcamp` in its photometry exclusions and must not be
reused.

**0.7 Operational.**
ReagentHub scheduled task (create from scratch, elevated; `setup_scheduled_task.ps1`
does not exist and never did). Verify v11.137 published complete; check whether
11.127 through 11.133 published incomplete (51 files missing from the 11.133
folder). Upload the v11.125 release asset so off-network machines stop seeing
11.124.

**0.8 Time one `.lif` header read.** *(done)*
Measured on three files spanning 1.8 GB to 9.6 GB: **0.13–0.15 s each, flat
with size.** `series_list()` parses the header XML and touches no image data,
so cost is per file rather than per byte. 0.2 is minutes. The 5.3 branch date
is not gated by census cost.

### Phase 1: September, as proposed

Integration, batch framework, quality control, validation against manually
scored ground truth. Add 0.4b (the bout budget pass) and the 3.1 bout
classifier here. Make the 5.3 branch decision. First monthly cohort update due
around 1 October.

### Phase 2: October

Whichever leg 5.3 selected. Resist adding legs. Thirteen weeks cannot advance
seventeen backlog items, and the cohort will ask what was found, not what was
built.

### Phase 3: November

Stop new work around 15 November. Figures with code and environment attached.
Final update.

---

## 7. Discrepancies with the proposal, to raise with Bailey

1. **Deliverable 3 commits to a Fiji/ImageJ interface** for researchers without
   programming expertise. The morphometry work is being ported off Fiji into
   Python, and WINK is the actual lab-usable interface. Delivering WINK is
   almost certainly better and within the spirit of the commitment, but it
   should be said rather than quietly substituted.

2. **Mackenzie's usability testing is a committed deliverable**, not a
   courtesy. In-tool help currently stands at roughly 10 percent (3 of 29
   tools). That work now has grant standing.

3. **Morphology and physiology appear in the toolset but not in the proposal
   text.** The written methodology is behavior-forward: crawling kinematics and
   defecation timing. The confocal morphology leg is a strengthening of the
   claim, not a departure from it, but the scoping should be deliberate.

4. **Compute amount not marked** on the application copy. Confirm what was
   requested; Modal setup depends on it.

5. **Account governance.** Credits go to `avidal@ilstu.edu`, and that account
   cannot be governed by an enterprise agreement between ISU and Anthropic. If
   the lab subscription sits under an institutional arrangement, resolve before
   1 September.

6. **Platform.** Claude Science is macOS and Linux only. Work will run from a
   MacBook Pro. Whether it can mount the ISU SMB share is now **item 0.0**,
   moved into phase 0 because it gates phase 1 and costs an hour.

---

## 8. Non-negotiables

- Credits are tokens, not compute. Any plan that reprocesses 16 TB through the
  model is wrong. Credits buy judgment, triage, and interpretation; pixel
  crunching stays local or on Modal.
- WINK development runs under the existing subscription, not grant credits.
  Keep the streams separate.
- Deterministic code performs final quantitative measurements. The model
  accelerates development, debugging, validation, orchestration, and
  interpretation. This is what the proposal states and it should remain true.
- Automation proposes, human establishes. Correction logging applies to every
  new detector introduced here.
- Tiers, backends, and performance optimisations never affect measured values.
- **Before fixing any backlog item, check whether anything imports the module
  and whether a user can actually reach the control.** Three of the four items
  worked on 6 August were reachability failures, not missing code: correct
  gates defeated by GUI defaults, a correct commit button collapsed to one
  pixel, and a complete `acquisition_check.py` imported by nothing. The backlog
  describes symptoms, and a symptom is not a location. Budget for investigation
  before implementation, and treat a fix that was never reachable as not
  shipped.
