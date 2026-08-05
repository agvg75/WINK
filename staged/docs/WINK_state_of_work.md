# WINK: state of the work

A C. elegans image-analysis toolset built in the Vidal-Gadea lab, Illinois State University. This document is generated from the code's own provenance registry, so it cannot drift from what the tools actually do.

**Read the last three sections first.** They are what is wrong, unfinished, or unverified, and they are where an outside reading is worth most.

## At a glance

- 23 methods with recorded attribution and validation
- 6 stated open problems
- 10 approaches tried, measured and rejected, with numbers
- 16 external sources, all retrieved from origin

## Methods in use

### Myocyte boundaries run longitudinally, not transversely
`tools/fibre_orientation.py`  
**Validated:** 83.5% held-out recall at midbody, 57.9% at head.  
- *Andres Vidal-Gadea:* Hand-marked the boundaries in two fields. Measuring his ink showed 99% of it within 30 degrees of the body axis, against an initial implementation that searched transversely - a ~90 degree error, not a tuning miss.
- *assistant (Claude):* Measured the marks and rebuilt the search direction.

### A dim seam is found with the second derivative, not a gradient
`tools/fibre_orientation.py`  
**Validated:** Cue power 0.915 for valley against 0.788 for gradient.  
- *assistant (Claude):* Gradient magnitude is ZERO at the centre of a dark line, so it cannot localise the feature it is looking for. d2I/dy2 is the operator that peaks there.
- *published literature:* Standard ridge/valley detection.

### Each myocyte has its own brightness signature
`tools/fibre_orientation.py`  
- *Andres Vidal-Gadea:* Phalloidin penetrates each cell individually, so brightness differs cell to cell. This corrected an opening claim that the boundary was not an intensity feature at all.
- *assistant (Claude):* Combined it with orientation as an independent cue - gradient DIRECTION is invariant to intensity scaling, which is what makes the two independent.

### Split traced fibres at junctions before measuring
`tools/fibre_trace.py`  
**Validated:** Convergence voting reaches boundary evidence 0.849.  
- *assistant (Claude):* Sato ridge filter, skeletonise, split at junctions so a fibre is not merged with its neighbour across a crossing.

### What degeneration looks like in the pharynx
`tools/pharynx_continuity.py`  
**Validated:** disrupted_fibres: bending 0.849, congruence 0.827.  
- *Andres Vidal-Gadea:* Named four things from marked images: interior holes with an intact perimeter, extra-bright scar tissue, detached filaments that coil and lose axial orientation, and loss of radial congruence - all concentrated in the CORTEX, because the centre holds the lumen and is intrinsically non-radial.
- *assistant (Claude):* Turned each into a measure and validated three.

### Measure radial organisation in the cortex only
`tools/pharynx_continuity.py`  
- *Andres Vidal-Gadea:* "The center has the lumen so it is intrinsically non radial."
- *assistant (Claude):* A first version measured coiling across 53% of fibre area by scoring the core, where radial was never the expectation.

### Unroll about the lumen so continuity is bending-invariant
`tools/pharynx_continuity.py`  
- *assistant (Claude):* Measuring continuity in unrolled coordinates makes it invariant to how the organ is bent by construction, rather than by correction.

### Score each damage parameter separately, never as one index
`tools/pharynx_continuity.py`  
**Validated:** A single index makes 30% scarring and one detached muscle numerically equal.  
- *published literature:* An ischaemic skeletal muscle scheme scores inflammation, fibrosis, necrosis, adipocyte infiltration and fibre degeneration/regeneration SEPARATELY, with inter-appraiser agreement by Kendall's W of 0.92, 0.94 and 0.77 for the first three.
- *Andres Vidal-Gadea:* Independently described the same shape - categories with a gradient inside each.

### Measure continuously; bin only at the end
`tools/pharynx_continuity.py`  
- *published literature:* ISHLT cardiac allograft rejection grading was revised in 2004 to fix reproducibility and did not - disagreement persists AT GRADE BOUNDARIES, which continuous measures do not have.

### Never average an ordinal grade
`app/event_rhythm.py`  
- *published literature:* Histopathologic grades are ordinal and semiquantitative: the interval between two grades cannot be objectively justified, so a rational-scale readout is impossible and averaging assumes spacing no scheme guarantees. Report median, IQR and the full distribution, and test non-parametrically.

### Anchor damage severity to measured function
`app/event_rhythm.py`  
- *published literature:* Histopathology scales are usually validated against expert consensus, which is circular.
- *Andres Vidal-Gadea:* This lab measures pumping, bends and swimming on the same animals.
- *assistant (Claude):* It also tests the detection confound - an artefact will not track locomotor decline; real damage should.

### RMSSD, SDNN and Poincare descriptors for pharyngeal pumping
`app/event_rhythm.py`  
- *published literature:* Cardiology's validated beat-to-beat vocabulary.
- *Andres Vidal-Gadea:* The pharynx is closer to cardiac than skeletal - myogenic, sharing most ion channels that define cardiac physiology. And: because the tool detects EACH pumping event, the full interval series is available, so every beat-to-beat measure is computable where a mean rate gives none.

### Cycle-to-cycle spread of rise, relaxation and excursion
`app/cycle_analysis.py`  
- *Andres Vidal-Gadea:* Proposed that variability in time-to-peak, time-to-relaxation and excursion is a dimension separate from the mean, and underreported.
- *published literature:* Partly confirms it: gon-2/gtl-1 knockdown raises defecation cycle variability with NO change in mean period. Variability of PERIOD is established; variability of waveform SHAPE is not.
- *assistant (Claude):* The measure, and the quantisation floor - a timing fraction cannot be measured finer than one frame, so below step/sqrt(12) the report is of the camera.

### Analyse within confidence spans; never join them
`app/confidence_gate.py`  
- *Andres Vidal-Gadea:* Asked for a selectable confidence level so a recording with good and bad stretches yields a high-confidence output.
- *assistant (Claude):* A cycle or interval spanning a join is an invention - its period describes the gap, not the animal - so spans are analysed separately and the RESULTS pooled.

### Head and tail are told apart by taper SHAPE, not width
`tools/head_tail.py`  
- *Andres Vidal-Gadea:* Both ends taper. The tail taper is long and shallow and comes to a point; the head taper is short, steep and round.
- *assistant (Claude):* Replaced a terminal-width comparison, which a steep head taper defeats, with taper length and tip bluntness.

### The pharynx is found by CONFINEMENT, not texture
`tools/head_tail.py`  
**Validated:** Smeared texture scores -0.02 against 0.30 for a pharynx.  
- *Andres Vidal-Gadea:* The pharynx is visible in DIC and makes the head read LIGHTER than the region behind it; the tail matches the body. Also suggested the confocal pharynx work would help here.
- *assistant (Claude):* What transferred was the length scale, not the lumen and bulb detectors, which need a magnification these movies lack. Measuring both features confined to one pharynx length and comparing with the length behind makes debris and gut contents cancel.

### Ventral excursions are deeper, which identifies the side
`tools/head_tail.py`  
- *Andres Vidal-Gadea:* The dorsoventral asymmetry during movement, clearest in swimming. Also that failure means the movie could not resolve it - a REVERSED mutant would be extraordinary.
- *assistant (Claude):* Depth from the 95th percentile rather than the mean, and the prior encoded as a raised threshold outside swimming rather than a refusal.

### The vulval myocyte gap marks the ventral side locally
`tools/head_tail.py`  
**Validated:** Corrected measure scores -0.001 on the no-notch control.  
- *Andres Vidal-Gadea:* Building the vulva required myocyte apoptosis, so an adult hermaphrodite bends differently ventrally than dorsally at precisely that one spot.
- *assistant (Claude):* Difference in differences. A first version compared each bending sense with its own flanks and scored a worm with NO notch at -0.99, reading positional curvature bias.

### A dorsoventral disagreement diagnoses a head error
`tools/head_tail.py`  
- *Andres Vidal-Gadea:* A reversed animal would be extraordinary, so disagreement is a processing fault.
- *assistant (Claude):* A wrong head call inverts the dorsoventral sign exactly, so the redundancy becomes an error detector. Flags, never corrects - auto-flipping would make a genuine reversal permanently invisible.

### A hand-corrected head applies to the whole track
`tools/head_tail.py`  
- *Andres Vidal-Gadea:* Asked that head/tail be correctable and that the correction propagate to successive frames, which it did not in at least one tool.
- *assistant (Claude):* The call is per-track, so a correction cannot reach the frame on screen and leave the rest behind; and it propagates sideways too, since flipping the head inverts dorsal and ventral.

### Independent agreeing cues combine by noisy-OR
`tools/head_tail.py`  
- *published literature:* Standard combination of independent evidence.
- *assistant (Claude):* Averaging made two agreeing cues score BELOW the stronger alone. Deliberately not used for the head cues, which read the same end's anatomy and fail together.

### Which brightness statistic to report, and the ROI-area confound
`app/brightness_statistics.py`  
**Validated:** On the hand-curated extraction: the confound is real and signed by side (ventral -0.55, dorsal +0.61 area vs curvature), and it removes 10 of 22 mean-based curvature relationships. Testing on real data reversed the synthetic-only guidance - see REJECTED.  
**Known limits:** One worm, 135 frames. And median and p90 are absent from the Fiji extraction, so the two statistics expected to be most robust are still untested on real data.  
- *Andres Vidal-Gadea:* Asked what is actually being reported when we measure brightness, and then how the statistics behave against time and curvature - and asked for it to be tested on the RGBCaMP data already measured and hand curated rather than left synthetic.
- *assistant (Claude):* The diagnostic, and the ROI-area confound: a hemisegment ROI changes area with bending by geometry, so a statistic that tracks area appears to track curvature. area_control() partials it out and refuses when the two are collinear.

### Decide column types from data, not from column names
`app/table_io.py`  
- *assistant (Claude):* A first version matched column NAMES and would have turned fps_source='declared' into NaN, destroying provenance. Caught by surveying real CSVs before trusting it.


---

## What is NOT solved

*Each names the suspected cause, what a solution would have to show, and the data to work from.*

### head_region_boundary_recall
Myocyte boundary detection reaches 83.5% held-out recall at midbody but only 57.9% at the head.  
**Suspected:** The head is imaged at higher zoom and the cells are smaller and more crowded; DETECT_SCALE compensates only crudely.  
**A solution would show:** Head recall above 75% without midbody regressing.  
**Data:** myocyte_marks_W1_ventral_head.npz, myocyte_marks_W1_midbody.npz

### fibre_length_capture
Per-fibre segmentation captures about 57% of expected fibre length, and pushing it higher makes downstream boundary detection WORSE.  
**Suspected:** Longer traces bridge junctions between neighbouring fibres, so the extra length is partly wrong length.  
**A solution would show:** Higher captured length with boundary evidence held or improved - the pair, not either alone.  
**Data:** myocyte_vertices_head.npz, myocyte_vertices_midbody.npz

### interior_voids_over_called
interior_holes finds 23 voids in a pharynx where Andres marked 1.  
**Suspected:** Unresolved: the 22 may be real sub-threshold texture, lumen branches, or noise. Never diagnosed.  
**A solution would show:** An account of what the 22 are, then a detector whose count matches marked damage.  
**Data:** pharynx_marks_W4_head.png

### bright_scar_unvalidated
bright_scar and the axial scar in Andres's second marked field are implemented but never validated.  
**Suspected:** No second-scorer marks exist for them yet.  
**A solution would show:** Agreement with marks on a field not used to build it.  
**Data:** pharynx_marks_W2_head.png

### no_fiji_parity_check
The Python extraction front-end has never been compared against WormRGBCaMPMap_v1.java on the same recording.  
**Suspected:** Not a defect - the comparison has simply not been run.  
**A solution would show:** One recording processed both ways, agreeing on per-segment intensities and head assignment.  
**Data:** needs a recording already processed through the Fiji plugin

### dv_untested_on_real_animals
Dorsal/ventral identification passes on synthetic worms only. The excursion asymmetry and the vulval gap have never been measured on a real swimming recording.  
**Suspected:** Both effects may be smaller than the fixture's, and the vulval one is local and needs spatial resolution.  
**A solution would show:** Cohort agreement via reconcile_ventral on real swimmers, checked against animals scored by eye.  
**Data:** any swimming recording with adult hermaphrodites

---

## What was tried and rejected

*Several of these WON on the metric anyone would reach for first and were rejected anyway. Before proposing one, read why.*

- **Fibre spacing as a boundary cue.** (considered instead of `valley_operator`) — Scored the HIGHEST pointwise cue power of anything tried, 0.972, and still made the tool worse: end-to-end boundary recall fell from 63.7% to 49.9%. It is diffuse - it says a boundary is nearby, not where. Pointwise AUC is not localisation, and this is the clearest example we have of the difference. *Numbers:* cue power 0.972; recall 63.7% -> 49.9%

- **Gradient magnitude to find the myocyte seam.** (considered instead of `valley_operator`) — A gradient is zero at the CENTRE of a dark line, so it cannot localise a dim seam - it finds the two shoulders instead. *Numbers:* cue power 0.788 against 0.915 for the valley operator

- **Let convergence votes follow fibre curvature.** (considered instead of `junction_splitting`) — Produced a vote map 14x peakier, which looked like a large improvement, and every downstream metric got worse. *Numbers:* 14x peak sharpening, all metrics down

- **Tell head from tail by mean width over the terminal fifth.** (considered instead of `taper_shape`) — Both ends taper. A steep head taper makes the head's last few percent as narrow as the tail's, so the two ends read as nearly identical and the call falls to noise. *Numbers:* superseded before deployment, on Andres's anatomy note

- **Compare each bending sense against its own flanking regions to isolate the vulval deficit.** (considered instead of `vulval_gap`) — Looked like it removed the global asymmetry, and did not: curvature magnitude varies along the body with where the travelling wave's peaks fall, and that positional bias survives. A worm with NO vulval notch scored -0.99. *Numbers:* no-notch control -0.993; difference-in-differences gives -0.001

- **Measure pharyngeal texture over the whole worm mask.** (considered instead of `pharynx_confinement`) — Dominated by the body EDGE, and the thin tail has more edge per unit area than anywhere else - so the cue became a second, worse taper detector instead of independent evidence. *Numbers:* fixed by eroding to the interior before measuring

- **Combine agreeing cues by weighted average.** (considered instead of `noisy_or_combination`) — Two independent cues that AGREE came out below the stronger one alone - the wrong direction for corroborating evidence. *Numbers:* 0.234 alone -> 0.170 averaged with an agreeing 0.074

- **Take pumping rate from the median inter-event interval.** (considered instead of `cardiac_rhythm_vocabulary`) — Events land on integer frames, so a period that is not a whole number of frames alternates between two values - 7.5 frames becomes 7, 8, 7, 8 - and the median picks one of them. *Numbers:* several percent rate bias; mean of steady intervals instead

- **Choosing the brightness statistic from a synthetic ROI: max is area-biased and noisy, mean is fine.** (considered instead of `brightness_statistic_choice`) — Both halves failed on the lab's own hand-curated extraction. The MEAN tracks ROI area (median r = -0.34, |r| > 0.3 in 27 of 48 hemisegments) and the max barely does (-0.02); controlling for area destroys 10 of 22 mean-based curvature relationships against 1 of 13 for the max. The synthetic ROI had homogeneous pixels, so it measured sampling noise in a uniform region. A real hemisegment is 28 pixels of part muscle and part dark tissue, and its mean is set by how much dark tissue the bend happened to include. *Numbers:* mean-vs-area r -0.34 against max -0.02; 10/22 vs 1/13 relationships lost to area control

- **Decide which CSV columns are numeric from their names.** (considered instead of `coerce_numeric_from_data`) — Would have coerced fps_source='declared' to NaN, destroying provenance. Caught only by surveying real CSVs. *Numbers:* rejected before shipping

---

## Claims that did not survive checking

*Statements made during development that the cited source does not actually support. Recorded rather than deleted, so they are not re-derived.*

- **[ischaemic_muscle_scoring]** An earlier note claimed this paper found 4-5 levels per parameter to be optimal. The retrieval did NOT confirm that; do not repeat it without reading the paper. The separate-parameters design and the Kendall's W values above ARE confirmed.

- **[klopfleisch_2013_scoring_review]** An earlier note claimed ~70% of published papers report ordinal scores as means and standard deviations. NO SOURCE FOR THAT FIGURE HAS BEEN FOUND. This review is the most likely place such a prevalence would be reported - check it, and until then do not state the number. The principle stands without it.

---

## Contributions

23 methods are recorded with attribution. Decisive idea: 9 andres, 4 claude, 5 literature, 5 joint. Involvement: Andres Vidal-Gadea 16, assistant (Claude) 19, published literature 8.

### Supervision record

11 occasions where the supervising scientist's input overturned or redirected work already done, 5 of them reversing the direction of a method rather than adjusting it. Output that is reversed is not output that was accepted uncritically.

Every correction names a module, test or fixture in this repository, so the claim can be checked against the code and the commit history rather than taken on this file's word.

2 entries record where his own stated expectation was revised by evidence. An audit that only ever finds the supervisor correct is advocacy.

- **Myocyte boundaries are an intensity feature** *(reversed)* — The implementation had: Opened by asserting the myocyte boundary is NOT an intensity feature, and built accordingly. AVG: Phalloidin penetrates each cell individually, so each myocyte has its own brightness signature. Consequence: The premise was wrong. Intensity became one of the two combined cues. (`tools/fibre_orientation.py; method per_cell_brightness_signature`)
- **Search direction for the boundary** *(reversed)* — The implementation had: Searched for boundaries TRANSVERSELY across the body. AVG: Hand-marked two fields. His ink was 99% within 30 degrees of the body AXIS. Consequence: A ~90 degree error, not a tuning miss. The whole search was rebuilt longitudinally. (`myocyte_marks_W1_ventral_head.npz; method longitudinal_boundary_geometry`)
- **Cell shape** *(reversed)* — The implementation had: Drew vertical boundary lines. AVG: "The muscles are rhomboid." Consequence: Shape prior replaced; guided seam tracing added. (`tools/fibre_orientation.trace_seam_guided`)
- **Where radial organisation can be measured** *(reversed)* — The implementation had: Measured pharyngeal fibre coiling across the whole organ, reporting 53% of fibre area as disrupted. AVG: "The center has the lumen so it is intrinsically non radial." Consequence: The measure had been scoring the core, where radial was never the expectation. Restricted to the cortex. (`tools/pharynx_continuity.cortex_mask; method cortex_only_measurement`)
- **How boundary recall was scored** *(corrected evaluation)* — The implementation had: Reported a single held-out recall of 63.7%. AVG: Pointed out the field contains two quadrants. Consequence: Scoring split: 84.2% between quadrants, 56.2% within. The single number had been averaging two different problems and describing neither. (`tools/fibre_trace.py boundary_evidence scoring`)
- **Head/tail by terminal width** *(reversed)* — The implementation had: A taper cue comparing mean width over the terminal fifth of each end. AVG: Both ends taper. The tail taper is long and shallow and comes to a point; the head taper is short, steep and round. Consequence: The cue was measuring the wrong property. Rebuilt on taper LENGTH and tip bluntness. (`tools/head_tail.taper_cue; REJECTED[terminal_width_taper]`)
- **Dorsal/ventral identification** *(supplied capability)* — The implementation had: No dorsoventral capability at all; it was listed as a remaining task with no proposed method. AVG: Ventral excursions run deeper than dorsal ones during movement; and the vulva required myocyte apoptosis, so an adult bends differently there at one precise spot. Consequence: Two independent cues, and the step that unblocks hemisegment labelling. (`tools/head_tail.identify_ventral, vulva_cue`)
- **Finding the pharynx in DIC** *(supplied capability)* — The implementation had: A generic texture measure that would score debris and gut contents as readily as a pharynx. AVG: The pharynx is visible in DIC and makes the head read LIGHTER than the region behind it; the tail matches the body. Also that the confocal pharynx work might help. Consequence: Two features instead of one, and confinement to a pharynx length instead of raw texture. Smeared texture now scores -0.02 against 0.30 for a real pharynx. (`tools/head_tail.pharynx_cue; method pharynx_confinement`)
- **Corrections did not propagate** *(found defect)* — The implementation had: Assumed hand corrections propagated through the tracking tools. AVG: Corrections should propagate to successive frames, "which currently does not happen in at least some tools (I believe)." Consequence: Correct. run_neuron_tracker recomputed one frame and left every later frame tracking from the wrong state. (`tools/afd_neuron/run_neuron_tracker.py`)
- **What the GCaMP recordings contain** *(found defect)* — The implementation had: Treated each folder as one recording and failed to detect the worm. AVG: Kiley used transmitted light at low magnification to find a worm, zoomed in, turned transmitted light off, filmed in blue light, then repeated for the next worm. Consequence: One folder holds many separate acquisitions. Session splitting was built from this description. (`GCaMP feasibility/extractor session splitting`)
- **Which physiology the pharynx resembles** *(redirected)* — The implementation had: No stated position. AVG: "Our pharynx is closer to cardiac than skeletal." Consequence: Sent the damage-scale search to cardiology, which supplied both the beat-to-beat vocabulary and the ISHLT reproducibility cautionary tale. (`app/event_rhythm.py; method cardiac_rhythm_vocabulary`)

### Where the evidence went the other way

- **How underreported cycle variability is** — Expected: That cycle-to-cycle variability in timing and excursion is "going completely underreported in the nematode literature (I believe; but check)". Evidence showed: Partly wrong, and he asked for the check. Variability of defecation PERIOD is established, with a landmark result: gon-2/gtl-1 knockdown raises it with no change in the mean. What is thin is variability of waveform SHAPE. Outcome: The claim was narrowed to the defensible one and the existing result cited rather than rediscovered.
- **Number of myocytes in the marked field** — Expected: Said five myocytes were in view. Evidence showed: He recounted and corrected it to seven. Outcome: Self-corrected before it affected any scoring.

---

## References

- **[trpm_defecation_2008]** TRPM channels are required for rhythmicity in the ultradian defecation rhythm of C. elegans. BMC Physiology 8:11 (2008). <https://bmcphysiol.biomedcentral.com/articles/10.1186/1472-6793-8-11>
  *Supports:* gon-2/gtl-1 knockdown raises defecation cycle variability with NO change in mean period - the precedent that variability is a dimension separate from the mean.
- **[wormbook_feeding]** C. elegans feeding. WormBook (NCBI Bookshelf NBK116080). <https://www.ncbi.nlm.nih.gov/books/NBK116080/>
  *Supports:* Pharyngeal contraction/relaxation cycle, radial muscle opening the lumen, and the EPG E/R transients that define action potential duration.
- **[pharyngeal_timing_2021]** Pharyngeal timing and particle transport defects in Caenorhabditis elegans feeding mutants. Journal of Neurophysiology (2021). doi:10.1152/jn.00444.2021 <https://journals.physiology.org/doi/full/10.1152/jn.00444.2021>
  *Supports:* Timing differences between corpus, anterior isthmus and terminal bulb - contraction and relaxation are ordered, not simultaneous.
- **[intestinal_gaba_2008]** Intestinal signaling to GABAergic neurons regulates a rhythmic behavior in Caenorhabditis elegans. PNAS (2008). doi:10.1073/pnas.0803617105 <https://www.pnas.org/doi/10.1073/pnas.0803617105>
  *Supports:* The defecation motor program as a tightly controlled rhythm.
- **[thomas_1994_defecation]** Thomas JH. Regulation of a periodic motor program in C. elegans. Journal of Neuroscience 14(4):1953-1962 (1994). <https://www.jneurosci.org/content/14/4/1953>
  *Supports:* ~45 s defecation period with an SD of about 3 s - the precision figure the variability work is measured against.
- **[enteric_action_potentials_2022]** C. elegans enteric motor neurons fire synchronized action potentials underlying the defecation motor program. Nature Communications (2022). doi:10.1038/s41467-022-30452-y <https://www.nature.com/articles/s41467-022-30452-y>
  *Supports:* Discrete, detectable events underlying the defecation cycle.
- **[hrv_task_force_1996]** Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology. Heart rate variability: standards of measurement, physiological interpretation and clinical use. Circulation 93(5):1043-1065 (1996). doi:10.1161/01.CIR.93.5.1043 <https://doi.org/10.1161/01.CIR.93.5.1043>
  *Supports:* SDNN, RMSSD and the Poincare descriptors as used in app/event_rhythm.py.
- **[ishlt_grading_revision_2005]** Stewart S, Winters GL, Fishbein MC, Tazelaar HD, Kobashigawa J, et al. Revision of the 1990 working formulation for the standardization of nomenclature in the diagnosis of heart rejection. Journal of Heart and Lung Transplantation 24(11):1710-1720 (2005). PMID 16297770. <https://pubmed.ncbi.nlm.nih.gov/16297770/>
  *Supports:* The 2004/2005 revision itself: grades collapsed to 0R, 1R, 2R, 3R specifically to improve standardisation.
- **[ishlt_reproducibility_angelini]** Angelini A et al. Has the 2004 revision of the International Society of Heart and Lung Transplantation grading system improved the reproducibility of the diagnosis and grading of cardiac transplant rejection? Cardiovascular Pathology. <https://www.sciencedirect.com/science/article/abs/pii/S1054880708000598>
  *Supports:* THE ACTUAL SOURCE for the claim the design rests on: the revision did NOT improve reproducibility, with a combined kappa of 0.39 across 18 pathologists and disagreement concentrated at the 1B/1R and 3A/2R boundaries. This is the argument for measuring continuously and binning last - disagreement lives at boundaries, and continuous measures have none.
  *Still to verify:* Confirm year, volume and pages; the abstract page was reached but the full citation line was not captured.
- **[ischaemic_muscle_scoring]** Sanz-Nogues C et al. Development and Validation of a Multiparametric Semiquantitative Scoring System for the Histopathological Assessment of Ischaemia Severity in Skeletal Muscle. PMC11918935. <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11918935/>
  *Supports:* Splitter-not-lumper: inflammation, fibrosis, necrosis, adipocyte infiltration and fibre degeneration/regeneration scored SEPARATELY, with inter-appraiser agreement by Kendall's W - inflammation 0.92, fibrosis 0.94, necrosis 0.77.
  *Still to verify:* Publication year: summarised as 2023, but the PMC identifier suggests a later date. Confirm before citing a year.
- **[gibson_corley_2013_scoring]** Gibson-Corley KN, Olivier AK, Meyerholz DK. Principles for Valid Histopathologic Scoring in Research. Veterinary Pathology (2013). doi:10.1177/0300985813485099 <https://journals.sagepub.com/doi/10.1177/0300985813485099>
  *Supports:* Histopathologic scores are ORDINAL and semiquantitative - the interval between two grades cannot be objectively justified, so a rational-scale readout is impossible. This is the basis for app/event_rhythm.ordinal_guard.
- **[schafer_2018_severity_grades]** Schafer KA, Eighmy J, Fikes JD, Halpern WG, Hukkanen RR, Long GG, Meseck EK, Patrick DJ, Thibodeau MS, Wood CE, Francke S. Use of Severity Grades to Characterize Histopathologic Changes. Toxicologic Pathology (2018). doi:10.1177/0192623318761348. PMID 29529947. <https://journals.sagepub.com/doi/full/10.1177/0192623318761348>
  *Supports:* Society of Toxicologic Pathology working-group guidance on assigning and reporting severity grades, and on analysing them non-parametrically rather than as measurements.
- **[klopfleisch_2013_scoring_review]** Klopfleisch R. Multiparametric and semiquantitative scoring systems for the evaluation of mouse model histopathology - a systematic review. BMC Veterinary Research 9:123 (2013). doi:10.1186/1746-6148-9-123 <https://bmcvetres.biomedcentral.com/articles/10.1186/1746-6148-9-123>
  *Supports:* Systematic review of multiparametric semiquantitative scoring practice.
- **[sato_line_filter_1998]** Sato Y, Nakajima S, Shiraga N, Atsumi H, Yoshida S, Koller T, Gerig G, Kikinis R. Three-dimensional multi-scale line filter for segmentation and visualization of curvilinear structures in medical images. Medical Image Analysis 2(2):143-168 (1998). PMID 10646760. <https://pubmed.ncbi.nlm.nih.gov/10646760/>
  *Supports:* The Hessian-eigenvalue ridge filter used in tools/fibre_trace.trace_fibres, and its multi-scale formulation - which is why FIBRE_WIDTH_UM is a range.
- **[pearl_1988_noisy_or]** Pearl J. Probabilistic Reasoning in Intelligent Systems: Networks of Plausible Inference. Series in Representation and Reasoning. Morgan Kaufmann, San Mateo, xix + 552 pp (1988). <https://archive.org/details/probabilisticrea00pear>
  *Supports:* The noisy-OR gate for combining independent causes of a binary outcome - used for the dorsoventral and pharynx cues, where each cue can independently establish the answer and agreement should therefore accumulate.
- **[neurite_morphology_2019]** In-Vivo Quantitative Image Analysis of Age-Related Morphological Changes of C. elegans Neurons Reveals a Correlation between Neurite Bending and Novel Neurite Outgrowths. eNeuro 6(4) ENEURO.0014-19.2019 (2019). <https://www.eneuro.org/content/6/4/ENEURO.0014-19.2019>
  *Supports:* A semi-automated pipeline measuring soma, neurite outgrowths, and the density of BEADS and SHARP BENDS on individual neurites - the established vocabulary to reuse when damage scoring extends to neurons, and a direct parallel to the fibre-bending measure already used for the pharynx.
