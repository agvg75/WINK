# WINK: what the tools measure and what their settings hide

Attach this to a Claude Project. It is the operating envelope of each tool - the settings that bound what it can detect and what happens to a specimen outside them - plus what each measure computes and how it was validated.

**Answer from this document.** If it does not cover a question, say so and suggest asking Andres. General microscopy advice that sounds reasonable sends a student to fix something that was never the problem, and they have no way to tell.

## Confidence gating  (`confidence`)
*Source: app/confidence_gate.py*

**Setting:** Qualifying stretches are analysed separately and the RESULTS pooled - spans are never joined
**Consequence:** Raising the confidence level gives you less data, not smoother data. Coverage is reported so you can see what was dropped.
**What to do:** Use the sweep to see what each level would cost before choosing one.

## Per-cycle analysis and variability  (`cycles`)
*Source: app/cycle_analysis.py*

**Setting:** Timing is quantised by the frame rate
**Consequence:** Rise and relaxation timing cannot be measured finer than one frame. At 30 fps a 5 Hz pump is 6 frames per cycle - about a 9% floor - which would swamp any real shape variability.
**What to do:** If the report says variability is within the quantisation floor, record faster. The number you are seeing is the camera, not the animal.

**Setting:** Cycles are never formed across a confidence gap
**Consequence:** A cycle spanning a bad stretch would have a period describing the gap rather than the animal, so it is not produced at all.
**What to do:** Expect fewer cycles from a patchy recording.

## Defecation / pBoc  (`defecation`)
*Source: tools/defecation/pboc_engine.py*

**Setting:** Events closer than 5 s are merged (merge_distance = 5 * fps in candidate_events)
**Consequence:** Two real pBoc events less than 5 s apart are counted as ONE. An animal with a short defecation cycle is undercounted, and nothing warns you - the count simply comes out low.
**What to do:** If your genotype speeds the cycle up, check a recording by eye before trusting the count.

**Setting:** Recovery is only searched for 6 s after the peak
**Consequence:** An animal that relaxes more slowly than that is recorded as has_recovery = False, which reads like a FAILED contraction rather than a slow one.
**What to do:** A high rate of has_recovery = False in a slow mutant is a limit of the tool, not a phenotype.

## Head/tail and dorsal/ventral identification  (`head_tail`)
*Source: tools/head_tail.py*

**Setting:** Dorsoventral cues are read off MOVEMENT
**Consequence:** They are clearest in swimming. In crawling or burrowing the asymmetry is expected to be too subtle, so the confidence bar is raised rather than a confident answer returned.
**What to do:** A low-confidence result on a crawling animal means the asymmetry was not visible, NOT that the animal lacks it.

**Setting:** The vulval cue is adult hermaphrodites only
**Consequence:** Larvae have not built a vulva and males never do, so on either it measures nothing.
**What to do:** Do not assert adult_hermaphrodite for larvae or males.

**Setting:** The pharynx cue needs transmitted light
**Consequence:** On fluorescence it refuses, because there it would only score whichever end was brighter.
**What to do:** Give it the DIC channel if you have one.

**Setting:** A wrong head call INVERTS dorsal and ventral
**Consequence:** Not degrades - inverts. Segment 0 becomes the tail, anterior-posterior gradients reverse, and a head-to-tail calcium wave reads as tail-to-head. All of it still looks plausible.
**What to do:** Correct the head by hand if it is wrong; the fix applies to the whole track and flips dorsal/ventral with it.

## Myocyte boundary detection and morphometry  (`myocyte`)
*Source: tools/morphology/myocyte_boundary_proposer.py*

**Setting:** Detection scale assumes a magnification range (DETECT_SCALE per region)
**Consequence:** Head fields are assumed to be more zoomed in than midbody. An unusual magnification is not detected, it is simply handled badly.
**What to do:** Tell the tool the region; do not let it guess.

**Setting:** Held-out recall is 83.5% at midbody, 57.9% at head
**Consequence:** Roughly two in five head boundaries are missed. This is a known open problem, not a fault in your image.
**What to do:** Review and correct head fields; the review layer exists for exactly this.

## Rhythm and regularity statistics  (`rhythm`)
*Source: app/event_rhythm.py*

**Setting:** min_events counts INTERVALS, not events
**Consequence:** Eight defecation intervals need about six minutes of continuous qualifying recording; eight pumping intervals need about two seconds.
**What to do:** If it refuses, the recording is too short for the rhythm you are measuring - it is not a detection failure.

**Setting:** Intervals are never formed across a confidence gap
**Consequence:** Statistics are computed within good stretches and pooled. You will not see a long interval where the recording was simply unusable.
**What to do:** Nothing - this is why no false pauses appear.

## What the measures compute, and how they were validated

- **Myocyte boundaries run longitudinally, not transversely** (`tools/fibre_orientation.py`) — *validated:* 83.5% held-out recall at midbody, 57.9% at head.
- **A dim seam is found with the second derivative, not a gradient** (`tools/fibre_orientation.py`) — *validated:* Cue power 0.915 for valley against 0.788 for gradient.
- **Each myocyte has its own brightness signature** (`tools/fibre_orientation.py`)
- **Split traced fibres at junctions before measuring** (`tools/fibre_trace.py`) — *validated:* Convergence voting reaches boundary evidence 0.849.
- **What degeneration looks like in the pharynx** (`tools/pharynx_continuity.py`) — *validated:* disrupted_fibres: bending 0.849, congruence 0.827.
- **Measure radial organisation in the cortex only** (`tools/pharynx_continuity.py`)
- **Unroll about the lumen so continuity is bending-invariant** (`tools/pharynx_continuity.py`)
- **Score each damage parameter separately, never as one index** (`tools/pharynx_continuity.py`) — *validated:* A single index makes 30% scarring and one detached muscle numerically equal.
- **Measure continuously; bin only at the end** (`tools/pharynx_continuity.py`)
- **Never average an ordinal grade** (`app/event_rhythm.py`)
- **Anchor damage severity to measured function** (`app/event_rhythm.py`)
- **RMSSD, SDNN and Poincare descriptors for pharyngeal pumping** (`app/event_rhythm.py`)
- **Cycle-to-cycle spread of rise, relaxation and excursion** (`app/cycle_analysis.py`)
- **Analyse within confidence spans; never join them** (`app/confidence_gate.py`)
- **Head and tail are told apart by taper SHAPE, not width** (`tools/head_tail.py`)
- **The pharynx is found by CONFINEMENT, not texture** (`tools/head_tail.py`) — *validated:* Smeared texture scores -0.02 against 0.30 for a pharynx.
- **Ventral excursions are deeper, which identifies the side** (`tools/head_tail.py`)
- **The vulval myocyte gap marks the ventral side locally** (`tools/head_tail.py`) — *validated:* Corrected measure scores -0.001 on the no-notch control.
- **A dorsoventral disagreement diagnoses a head error** (`tools/head_tail.py`)
- **A hand-corrected head applies to the whole track** (`tools/head_tail.py`)
- **Independent agreeing cues combine by noisy-OR** (`tools/head_tail.py`)
- **Which brightness statistic to report, and the ROI-area confound** (`app/brightness_statistics.py`) — *validated:* On the hand-curated extraction: the confound is real and signed by side (ventral -0.55, dorsal +0.61 area vs curvature), and it removes 10 of 22 mean-based curvature relationships. Testing on real data reversed the synthetic-only guidance - see REJECTED. — *known limits:* One worm, 135 frames. And median and p90 are absent from the Fiji extraction, so the two statistics expected to be most robust are still untested on real data.
- **Decide column types from data, not from column names** (`app/table_io.py`)

## Things we have NOT solved

- **head_region_boundary_recall** — Myocyte boundary detection reaches 83.5% held-out recall at midbody but only 57.9% at the head. A solution would show: Head recall above 75% without midbody regressing.
- **fibre_length_capture** — Per-fibre segmentation captures about 57% of expected fibre length, and pushing it higher makes downstream boundary detection WORSE. A solution would show: Higher captured length with boundary evidence held or improved - the pair, not either alone.
- **interior_voids_over_called** — interior_holes finds 23 voids in a pharynx where Andres marked 1. A solution would show: An account of what the 22 are, then a detector whose count matches marked damage.
- **bright_scar_unvalidated** — bright_scar and the axial scar in Andres's second marked field are implemented but never validated. A solution would show: Agreement with marks on a field not used to build it.
- **no_fiji_parity_check** — The Python extraction front-end has never been compared against WormRGBCaMPMap_v1.java on the same recording. A solution would show: One recording processed both ways, agreeing on per-segment intensities and head assignment.
- **dv_untested_on_real_animals** — Dorsal/ventral identification passes on synthetic worms only. The excursion asymmetry and the vulval gap have never been measured on a real swimming recording. A solution would show: Cohort agreement via reconcile_ventral on real swimmers, checked against animals scored by eye.

## Approaches already tried and rejected

*Several scored better on the obvious metric and were rejected anyway. If a student proposes one, this is why.*

- **Fibre spacing as a boundary cue.** Scored the HIGHEST pointwise cue power of anything tried, 0.972, and still made the tool worse: end-to-end boundary recall fell from 63.7% to 49.9%. It is diffuse - it says a boundary is nearby, not where. Pointwise AUC is not localisation, and this is the clearest example we have of the difference. (cue power 0.972; recall 63.7% -> 49.9%)
- **Gradient magnitude to find the myocyte seam.** A gradient is zero at the CENTRE of a dark line, so it cannot localise a dim seam - it finds the two shoulders instead. (cue power 0.788 against 0.915 for the valley operator)
- **Let convergence votes follow fibre curvature.** Produced a vote map 14x peakier, which looked like a large improvement, and every downstream metric got worse. (14x peak sharpening, all metrics down)
- **Tell head from tail by mean width over the terminal fifth.** Both ends taper. A steep head taper makes the head's last few percent as narrow as the tail's, so the two ends read as nearly identical and the call falls to noise. (superseded before deployment, on Andres's anatomy note)
- **Compare each bending sense against its own flanking regions to isolate the vulval deficit.** Looked like it removed the global asymmetry, and did not: curvature magnitude varies along the body with where the travelling wave's peaks fall, and that positional bias survives. A worm with NO vulval notch scored -0.99. (no-notch control -0.993; difference-in-differences gives -0.001)
- **Measure pharyngeal texture over the whole worm mask.** Dominated by the body EDGE, and the thin tail has more edge per unit area than anywhere else - so the cue became a second, worse taper detector instead of independent evidence. (fixed by eroding to the interior before measuring)
- **Combine agreeing cues by weighted average.** Two independent cues that AGREE came out below the stronger one alone - the wrong direction for corroborating evidence. (0.234 alone -> 0.170 averaged with an agreeing 0.074)
- **Take pumping rate from the median inter-event interval.** Events land on integer frames, so a period that is not a whole number of frames alternates between two values - 7.5 frames becomes 7, 8, 7, 8 - and the median picks one of them. (several percent rate bias; mean of steady intervals instead)
- **Choosing the brightness statistic from a synthetic ROI: max is area-biased and noisy, mean is fine.** Both halves failed on the lab's own hand-curated extraction. The MEAN tracks ROI area (median r = -0.34, |r| > 0.3 in 27 of 48 hemisegments) and the max barely does (-0.02); controlling for area destroys 10 of 22 mean-based curvature relationships against 1 of 13 for the max. The synthetic ROI had homogeneous pixels, so it measured sampling noise in a uniform region. A real hemisegment is 28 pixels of part muscle and part dark tissue, and its mean is set by how much dark tissue the bend happened to include. (mean-vs-area r -0.34 against max -0.02; 10/22 vs 1/13 relationships lost to area control)
- **Decide which CSV columns are numeric from their names.** Would have coerced fps_source='declared' to NaN, destroying provenance. Caught only by surveying real CSVs. (rejected before shipping)
