"""Who contributed each method: the literature, Andres, or the assistant.

WHY THIS EXISTS. Andres asked that the manual distinguish "the methods that came
from literature, the ones Claude devised, and the ones I contributed - what I
did, what we adopted, and what the AI derived." That is a reasonable thing to
want and a difficult thing to reconstruct afterwards: by the time a tool works,
the commit history has interleaved an observation, an implementation and a
citation into something that reads as though it arrived whole.

So attribution is recorded HERE, next to the code, at the time the method is
written - not inferred later from a diff.

THE HONEST DEFAULT IS `joint`, AND MOST ENTRIES ARE. Almost nothing here has a
single author. The usual shape is that Andres names something true about the
animal, the assistant turns it into a measurement, and the literature supplies
the statistics or the vocabulary. `contribution` therefore records what EACH
party actually did rather than assigning a winner, and `origin` names only where
the decisive idea came from.

A note on what "the AI derived" honestly means. Where an entry is marked
`claude`, the contribution is the measurement design - choosing what to compute
so that a stated fact becomes separable from its confounds. It does not mean the
biology was discovered here, and entries should not be written as though it was.

WRITTEN FOR WHOEVER COMES NEXT. Andres's point, and it changes what this file
is for: someone later - another lab, a student, or a future version of this
assistant reading the repository - may find a better way to do what we did, or
a way to do what we could not. A list of credits is no use to them. What is
useful is what a method must BEAT, what was already tried and lost, and where
we know we are still weak.

So each entry can carry `known_limits`, `rejected` and `to_supersede`, and the
things we have not solved at all are listed in OPEN_PROBLEMS. The rejected
alternatives matter most: several of them looked better than the method that
won on the obvious metric, and without the numbers recorded a later reader
would reasonably try them again.
"""
from __future__ import annotations

ORIGINS = ("andres", "claude", "literature", "joint")

# Each entry: what the method is, where the decisive idea came from, and what
# each party contributed. `verified` records how we know it works.
METHODS = {

    # ---- body-wall myocyte boundaries -----------------------------------
    "longitudinal_boundary_geometry": dict(
        title="Myocyte boundaries run longitudinally, not transversely",
        module="tools/fibre_orientation.py", origin="andres",
        contribution={
            "andres": ("Hand-marked the boundaries in two fields. Measuring "
                       "his ink showed 99% of it within 30 degrees of the body "
                       "axis, against an initial implementation that searched "
                       "transversely - a ~90 degree error, not a tuning miss."),
            "claude": "Measured the marks and rebuilt the search direction.",
        },
        verified="83.5% held-out recall at midbody, 57.9% at head."),

    "valley_operator": dict(
        title="A dim seam is found with the second derivative, not a gradient",
        module="tools/fibre_orientation.py", origin="claude",
        contribution={
            "claude": ("Gradient magnitude is ZERO at the centre of a dark "
                       "line, so it cannot localise the feature it is looking "
                       "for. d2I/dy2 is the operator that peaks there."),
            "literature": "Standard ridge/valley detection.",
        },
        verified="Cue power 0.915 for valley against 0.788 for gradient.",
        refs=["sato_line_filter_1998"]),

    "per_cell_brightness_signature": dict(
        title="Each myocyte has its own brightness signature",
        module="tools/fibre_orientation.py", origin="andres",
        contribution={
            "andres": ("Phalloidin penetrates each cell individually, so "
                       "brightness differs cell to cell. This corrected an "
                       "opening claim that the boundary was not an intensity "
                       "feature at all."),
            "claude": ("Combined it with orientation as an independent cue - "
                       "gradient DIRECTION is invariant to intensity scaling, "
                       "which is what makes the two independent."),
        }),

    "junction_splitting": dict(
        title="Split traced fibres at junctions before measuring",
        module="tools/fibre_trace.py", origin="claude",
        contribution={"claude": "Sato ridge filter, skeletonise, split at "
                                "junctions so a fibre is not merged with its "
                                "neighbour across a crossing."},
        verified="Convergence voting reaches boundary evidence 0.849.",
        refs=["sato_line_filter_1998"]),

    # ---- pharynx ---------------------------------------------------------
    "pharynx_damage_features": dict(
        title="What degeneration looks like in the pharynx",
        module="tools/pharynx_continuity.py", origin="andres",
        contribution={
            "andres": ("Named four things from marked images: interior holes "
                       "with an intact perimeter, extra-bright scar tissue, "
                       "detached filaments that coil and lose axial "
                       "orientation, and loss of radial congruence - all "
                       "concentrated in the CORTEX, because the centre holds "
                       "the lumen and is intrinsically non-radial."),
            "claude": "Turned each into a measure and validated three.",
        },
        verified="disrupted_fibres: bending 0.849, congruence 0.827."),

    "cortex_only_measurement": dict(
        title="Measure radial organisation in the cortex only",
        module="tools/pharynx_continuity.py", origin="andres",
        contribution={
            "andres": "\"The center has the lumen so it is intrinsically "
                      "non radial.\"",
            "claude": ("A first version measured coiling across 53% of fibre "
                       "area by scoring the core, where radial was never the "
                       "expectation."),
        }),

    "unroll_about_lumen": dict(
        title="Unroll about the lumen so continuity is bending-invariant",
        module="tools/pharynx_continuity.py", origin="claude",
        contribution={"claude": "Measuring continuity in unrolled coordinates "
                                "makes it invariant to how the organ is bent "
                                "by construction, rather than by correction."}),

    # ---- damage scoring --------------------------------------------------
    "splitter_not_lumper": dict(
        title="Score each damage parameter separately, never as one index",
        module="tools/pharynx_continuity.py", origin="literature",
        contribution={
            "literature": ("An ischaemic skeletal muscle scheme scores "
                           "inflammation, fibrosis, necrosis, adipocyte "
                           "infiltration and fibre degeneration/regeneration "
                           "SEPARATELY, with inter-appraiser agreement by "
                           "Kendall's W of 0.92, 0.94 and 0.77 for the first "
                           "three."),
            "andres": ("Independently described the same shape - categories "
                       "with a gradient inside each."),
        },
        verified="A single index makes 30% scarring and one detached muscle "
                 "numerically equal.",
        refs=["ischaemic_muscle_scoring"]),

    "continuous_not_categorical": dict(
        title="Measure continuously; bin only at the end",
        module="tools/pharynx_continuity.py", origin="literature",
        contribution={"literature": ("ISHLT cardiac allograft rejection "
                                     "grading was revised in 2004 to fix "
                                     "reproducibility and did not - "
                                     "disagreement persists AT GRADE "
                                     "BOUNDARIES, which continuous measures "
                                     "do not have.")},
        refs=["ishlt_grading_revision_2005", "ishlt_reproducibility_angelini"]),

    "ordinal_guard": dict(
        title="Never average an ordinal grade",
        module="app/event_rhythm.py", origin="literature",
        contribution={"literature": ("Histopathologic grades are ordinal and "
                                     "semiquantitative: the interval between "
                                     "two grades cannot be objectively "
                                     "justified, so a rational-scale readout "
                                     "is impossible and averaging assumes "
                                     "spacing no scheme guarantees. Report "
                                     "median, IQR and the full distribution, "
                                     "and test non-parametrically.")},
        refs=["gibson_corley_2013_scoring", "schafer_2018_severity_grades",
              "klopfleisch_2013_scoring_review"]),

    "function_anchored_severity": dict(
        title="Anchor damage severity to measured function",
        module="app/event_rhythm.py", origin="joint",
        contribution={
            "literature": ("Histopathology scales are usually validated "
                           "against expert consensus, which is circular."),
            "andres": ("This lab measures pumping, bends and swimming on the "
                       "same animals."),
            "claude": ("It also tests the detection confound - an artefact "
                       "will not track locomotor decline; real damage should."),
        },
        refs=["ishlt_grading_revision_2005", "ishlt_reproducibility_angelini"]),

    # ---- rhythm and cycles ----------------------------------------------
    "cardiac_rhythm_vocabulary": dict(
        title="RMSSD, SDNN and Poincare descriptors for pharyngeal pumping",
        module="app/event_rhythm.py", origin="literature",
        contribution={
            "literature": "Cardiology's validated beat-to-beat vocabulary.",
            "andres": ("The pharynx is closer to cardiac than skeletal - "
                       "myogenic, sharing most ion channels that define "
                       "cardiac physiology. And: because the tool detects "
                       "EACH pumping event, the full interval series is "
                       "available, so every beat-to-beat measure is "
                       "computable where a mean rate gives none."),
        },
        refs=["hrv_task_force_1996", "wormbook_feeding", "pharyngeal_timing_2021"]),

    "cycle_shape_variability": dict(
        title="Cycle-to-cycle spread of rise, relaxation and excursion",
        module="app/cycle_analysis.py", origin="andres",
        contribution={
            "andres": ("Proposed that variability in time-to-peak, "
                       "time-to-relaxation and excursion is a dimension "
                       "separate from the mean, and underreported."),
            "literature": ("Partly confirms it: gon-2/gtl-1 knockdown raises "
                           "defecation cycle variability with NO change in "
                           "mean period. Variability of PERIOD is "
                           "established; variability of waveform SHAPE is "
                           "not."),
            "claude": ("The measure, and the quantisation floor - a timing "
                       "fraction cannot be measured finer than one frame, so "
                       "below step/sqrt(12) the report is of the camera."),
        },
        refs=["trpm_defecation_2008", "thomas_1994_defecation"]),

    "confidence_spans_never_concatenated": dict(
        title="Analyse within confidence spans; never join them",
        module="app/confidence_gate.py", origin="joint",
        contribution={
            "andres": ("Asked for a selectable confidence level so a "
                       "recording with good and bad stretches yields a "
                       "high-confidence output."),
            "claude": ("A cycle or interval spanning a join is an invention - "
                       "its period describes the gap, not the animal - so "
                       "spans are analysed separately and the RESULTS pooled."),
        }),

    # ---- body axis identity ---------------------------------------------
    "taper_shape": dict(
        title="Head and tail are told apart by taper SHAPE, not width",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("Both ends taper. The tail taper is long and shallow "
                       "and comes to a point; the head taper is short, steep "
                       "and round."),
            "claude": ("Replaced a terminal-width comparison, which a steep "
                       "head taper defeats, with taper length and tip "
                       "bluntness."),
        }),

    "pharynx_confinement": dict(
        title="The pharynx is found by CONFINEMENT, not texture",
        module="tools/head_tail.py", origin="joint",
        contribution={
            "andres": ("The pharynx is visible in DIC and makes the head read "
                       "LIGHTER than the region behind it; the tail matches "
                       "the body. Also suggested the confocal pharynx work "
                       "would help here."),
            "claude": ("What transferred was the length scale, not the lumen "
                       "and bulb detectors, which need a magnification these "
                       "movies lack. Measuring both features confined to one "
                       "pharynx length and comparing with the length behind "
                       "makes debris and gut contents cancel."),
        },
        verified="Smeared texture scores -0.02 against 0.30 for a pharynx."),

    "ventral_excursion_depth": dict(
        title="Ventral excursions are deeper, which identifies the side",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("The dorsoventral asymmetry during movement, clearest "
                       "in swimming. Also that failure means the movie could "
                       "not resolve it - a REVERSED mutant would be "
                       "extraordinary."),
            "claude": ("Depth from the 95th percentile rather than the mean, "
                       "and the prior encoded as a raised threshold outside "
                       "swimming rather than a refusal."),
        }),

    "vulval_gap": dict(
        title="The vulval myocyte gap marks the ventral side locally",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("Building the vulva required myocyte apoptosis, so an "
                       "adult hermaphrodite bends differently ventrally than "
                       "dorsally at precisely that one spot."),
            "claude": ("Difference in differences. A first version compared "
                       "each bending sense with its own flanks and scored a "
                       "worm with NO notch at -0.99, reading positional "
                       "curvature bias."),
        },
        verified="Corrected measure scores -0.001 on the no-notch control."),

    "head_error_from_cohort_disagreement": dict(
        title="A dorsoventral disagreement diagnoses a head error",
        module="tools/head_tail.py", origin="joint",
        contribution={
            "andres": ("A reversed animal would be extraordinary, so "
                       "disagreement is a processing fault."),
            "claude": ("A wrong head call inverts the dorsoventral sign "
                       "exactly, so the redundancy becomes an error detector. "
                       "Flags, never corrects - auto-flipping would make a "
                       "genuine reversal permanently invisible."),
        }),

    "human_override_propagates": dict(
        title="A hand-corrected head applies to the whole track",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("Asked that head/tail be correctable and that the "
                       "correction propagate to successive frames, which it "
                       "did not in at least one tool."),
            "claude": ("The call is per-track, so a correction cannot reach "
                       "the frame on screen and leave the rest behind; and it "
                       "propagates sideways too, since flipping the head "
                       "inverts dorsal and ventral."),
        }),

    # ---- infrastructure --------------------------------------------------
    "noisy_or_combination": dict(
        title="Independent agreeing cues combine by noisy-OR",
        module="tools/head_tail.py", origin="literature",
        contribution={
            "literature": "Standard combination of independent evidence.",
            "claude": ("Averaging made two agreeing cues score BELOW the "
                       "stronger alone. Deliberately not used for the head "
                       "cues, which read the same end's anatomy and fail "
                       "together."),
        },
        refs=["pearl_1988_noisy_or"]),

    "brightness_statistic_choice": dict(
        title="Which brightness statistic to report, and the ROI-area confound",
        module="app/brightness_statistics.py", origin="joint",
        contribution={
            "andres": ("Asked what is actually being reported when we measure "
                       "brightness, and then how the statistics behave against "
                       "time and curvature - and asked for it to be tested on "
                       "the RGBCaMP data already measured and hand curated "
                       "rather than left synthetic."),
            "claude": ("The diagnostic, and the ROI-area confound: a "
                       "hemisegment ROI changes area with bending by geometry, "
                       "so a statistic that tracks area appears to track "
                       "curvature. area_control() partials it out and refuses "
                       "when the two are collinear."),
        },
        verified=("On the hand-curated extraction: the confound is real and "
                  "signed by side (ventral -0.55, dorsal +0.61 area vs "
                  "curvature), and it removes 10 of 22 mean-based curvature "
                  "relationships. Testing on real data reversed the "
                  "synthetic-only guidance - see REJECTED."),
        known_limits=("One worm, 135 frames. And median and p90 are absent "
                      "from the Fiji extraction, so the two statistics "
                      "expected to be most robust are still untested on real "
                      "data.")),

    "coerce_numeric_from_data": dict(
        title="Decide column types from data, not from column names",
        module="app/table_io.py", origin="claude",
        contribution={"claude": ("A first version matched column NAMES and "
                                 "would have turned fps_source='declared' "
                                 "into NaN, destroying provenance. Caught by "
                                 "surveying real CSVs before trusting it.")}),
}


# EXTERNAL SOURCES.
#
# `status` is the part that matters and it is not decoration. "retrieved" means
# the source was actually fetched in a session and the URL below is the one it
# came from. "recalled" means the citation is written from memory of the
# literature and has NOT been re-fetched - the finding is what we relied on, the
# bibliographic details need checking before anything is published.
#
# The distinction is kept because a manual that prints both the same way invites
# a reader to trust a half-remembered volume number as much as a verified one,
# and because a wrong citation is worse than a missing one - it sends the reader
# somewhere that does not support the claim and looks like carelessness about
# everything else.
REFERENCES = {
    "trpm_defecation_2008": dict(
        citation=("TRPM channels are required for rhythmicity in the ultradian "
                  "defecation rhythm of C. elegans. BMC Physiology 8:11 (2008)."),
        url="https://bmcphysiol.biomedcentral.com/articles/10.1186/1472-6793-8-11",
        status="retrieved",
        supports=("gon-2/gtl-1 knockdown raises defecation cycle variability "
                  "with NO change in mean period - the precedent that "
                  "variability is a dimension separate from the mean.")),

    "wormbook_feeding": dict(
        citation="C. elegans feeding. WormBook (NCBI Bookshelf NBK116080).",
        url="https://www.ncbi.nlm.nih.gov/books/NBK116080/",
        status="retrieved",
        supports=("Pharyngeal contraction/relaxation cycle, radial muscle "
                  "opening the lumen, and the EPG E/R transients that define "
                  "action potential duration.")),

    "pharyngeal_timing_2021": dict(
        citation=("Pharyngeal timing and particle transport defects in "
                  "Caenorhabditis elegans feeding mutants. Journal of "
                  "Neurophysiology (2021). doi:10.1152/jn.00444.2021"),
        url="https://journals.physiology.org/doi/full/10.1152/jn.00444.2021",
        status="retrieved",
        supports=("Timing differences between corpus, anterior isthmus and "
                  "terminal bulb - contraction and relaxation are ordered, not "
                  "simultaneous.")),

    "intestinal_gaba_2008": dict(
        citation=("Intestinal signaling to GABAergic neurons regulates a "
                  "rhythmic behavior in Caenorhabditis elegans. PNAS (2008). "
                  "doi:10.1073/pnas.0803617105"),
        url="https://www.pnas.org/doi/10.1073/pnas.0803617105",
        status="retrieved",
        supports="The defecation motor program as a tightly controlled rhythm."),

    "thomas_1994_defecation": dict(
        citation=("Thomas JH. Regulation of a periodic motor program in C. "
                  "elegans. Journal of Neuroscience 14(4):1953-1962 (1994)."),
        url="https://www.jneurosci.org/content/14/4/1953",
        status="retrieved",
        supports=("~45 s defecation period with an SD of about 3 s - the "
                  "precision figure the variability work is measured against.")),

    "enteric_action_potentials_2022": dict(
        citation=("C. elegans enteric motor neurons fire synchronized action "
                  "potentials underlying the defecation motor program. Nature "
                  "Communications (2022). doi:10.1038/s41467-022-30452-y"),
        url="https://www.nature.com/articles/s41467-022-30452-y",
        status="retrieved",
        supports="Discrete, detectable events underlying the defecation cycle."),

    "hrv_task_force_1996": dict(
        citation=("Task Force of the European Society of Cardiology and the "
                  "North American Society of Pacing and Electrophysiology. "
                  "Heart rate variability: standards of measurement, "
                  "physiological interpretation and clinical use. Circulation "
                  "93(5):1043-1065 (1996). doi:10.1161/01.CIR.93.5.1043"),
        url="https://doi.org/10.1161/01.CIR.93.5.1043",
        status="retrieved",
        supports=("SDNN, RMSSD and the Poincare descriptors as used in "
                  "app/event_rhythm.py.")),

    "ishlt_grading_revision_2005": dict(
        citation=("Stewart S, Winters GL, Fishbein MC, Tazelaar HD, "
                  "Kobashigawa J, et al. Revision of the 1990 working "
                  "formulation for the standardization of nomenclature in the "
                  "diagnosis of heart rejection. Journal of Heart and Lung "
                  "Transplantation 24(11):1710-1720 (2005). PMID 16297770."),
        url="https://pubmed.ncbi.nlm.nih.gov/16297770/",
        status="retrieved",
        supports=("The 2004/2005 revision itself: grades collapsed to 0R, 1R, "
                  "2R, 3R specifically to improve standardisation.")),

    "ishlt_reproducibility_angelini": dict(
        citation=("Angelini A et al. Has the 2004 revision of the "
                  "International Society of Heart and Lung Transplantation "
                  "grading system improved the reproducibility of the "
                  "diagnosis and grading of cardiac transplant rejection? "
                  "Cardiovascular Pathology."),
        url="https://www.sciencedirect.com/science/article/abs/pii/S1054880708000598",
        status="retrieved",
        supports=("THE ACTUAL SOURCE for the claim the design rests on: the "
                  "revision did NOT improve reproducibility, with a combined "
                  "kappa of 0.39 across 18 pathologists and disagreement "
                  "concentrated at the 1B/1R and 3A/2R boundaries. This is the "
                  "argument for measuring continuously and binning last - "
                  "disagreement lives at boundaries, and continuous measures "
                  "have none."),
        check="Confirm year, volume and pages; the abstract page was reached "
              "but the full citation line was not captured."),

    "ischaemic_muscle_scoring": dict(
        citation=("Sanz-Nogues C et al. Development and Validation of a "
                  "Multiparametric Semiquantitative Scoring System for the "
                  "Histopathological Assessment of Ischaemia Severity in "
                  "Skeletal Muscle. PMC11918935."),
        url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11918935/",
        status="retrieved",
        supports=("Splitter-not-lumper: inflammation, fibrosis, necrosis, "
                  "adipocyte infiltration and fibre degeneration/regeneration "
                  "scored SEPARATELY, with inter-appraiser agreement by "
                  "Kendall's W - inflammation 0.92, fibrosis 0.94, necrosis "
                  "0.77."),
        unconfirmed=("An earlier note claimed this paper found 4-5 levels per "
                     "parameter to be optimal. The retrieval did NOT confirm "
                     "that; do not repeat it without reading the paper. The "
                     "separate-parameters design and the Kendall's W values "
                     "above ARE confirmed."),
        check="Publication year: summarised as 2023, but the PMC identifier "
              "suggests a later date. Confirm before citing a year."),

    "gibson_corley_2013_scoring": dict(
        citation=("Gibson-Corley KN, Olivier AK, Meyerholz DK. Principles for "
                  "Valid Histopathologic Scoring in Research. Veterinary "
                  "Pathology (2013). doi:10.1177/0300985813485099"),
        url="https://journals.sagepub.com/doi/10.1177/0300985813485099",
        status="retrieved",
        supports=("Histopathologic scores are ORDINAL and semiquantitative - "
                  "the interval between two grades cannot be objectively "
                  "justified, so a rational-scale readout is impossible. This "
                  "is the basis for app/event_rhythm.ordinal_guard.")),

    "schafer_2018_severity_grades": dict(
        citation=("Schafer KA, Eighmy J, Fikes JD, Halpern WG, Hukkanen RR, "
                  "Long GG, Meseck EK, Patrick DJ, Thibodeau MS, Wood CE, "
                  "Francke S. Use of Severity Grades to Characterize "
                  "Histopathologic Changes. Toxicologic Pathology (2018). "
                  "doi:10.1177/0192623318761348. PMID 29529947."),
        url="https://journals.sagepub.com/doi/full/10.1177/0192623318761348",
        status="retrieved",
        supports=("Society of Toxicologic Pathology working-group guidance on "
                  "assigning and reporting severity grades, and on analysing "
                  "them non-parametrically rather than as measurements.")),

    "klopfleisch_2013_scoring_review": dict(
        citation=("Klopfleisch R. Multiparametric and semiquantitative scoring "
                  "systems for the evaluation of mouse model histopathology - "
                  "a systematic review. BMC Veterinary Research 9:123 (2013). "
                  "doi:10.1186/1746-6148-9-123"),
        url="https://bmcvetres.biomedcentral.com/articles/10.1186/1746-6148-9-123",
        status="retrieved",
        supports=("Systematic review of multiparametric semiquantitative "
                  "scoring practice."),
        unconfirmed=("An earlier note claimed ~70% of published papers report "
                     "ordinal scores as means and standard deviations. NO "
                     "SOURCE FOR THAT FIGURE HAS BEEN FOUND. This review is "
                     "the most likely place such a prevalence would be "
                     "reported - check it, and until then do not state the "
                     "number. The principle stands without it.")),

    "sato_line_filter_1998": dict(
        citation=("Sato Y, Nakajima S, Shiraga N, Atsumi H, Yoshida S, Koller "
                  "T, Gerig G, Kikinis R. Three-dimensional multi-scale line "
                  "filter for segmentation and visualization of curvilinear "
                  "structures in medical images. Medical Image Analysis "
                  "2(2):143-168 (1998). PMID 10646760."),
        url="https://pubmed.ncbi.nlm.nih.gov/10646760/",
        status="retrieved",
        supports=("The Hessian-eigenvalue ridge filter used in "
                  "tools/fibre_trace.trace_fibres, and its multi-scale "
                  "formulation - which is why FIBRE_WIDTH_UM is a range.")),

    "pearl_1988_noisy_or": dict(
        citation=("Pearl J. Probabilistic Reasoning in Intelligent Systems: "
                  "Networks of Plausible Inference. Series in Representation "
                  "and Reasoning. Morgan Kaufmann, San Mateo, xix + 552 pp "
                  "(1988)."),
        url="https://archive.org/details/probabilisticrea00pear",
        status="retrieved",
        supports=("The noisy-OR gate for combining independent causes of a "
                  "binary outcome - used for the dorsoventral and pharynx "
                  "cues, where each cue can independently establish the "
                  "answer and agreement should therefore accumulate.")),

    "neurite_morphology_2019": dict(
        citation=("In-Vivo Quantitative Image Analysis of Age-Related "
                  "Morphological Changes of C. elegans Neurons Reveals a "
                  "Correlation between Neurite Bending and Novel Neurite "
                  "Outgrowths. eNeuro 6(4) ENEURO.0014-19.2019 (2019)."),
        url="https://www.eneuro.org/content/6/4/ENEURO.0014-19.2019",
        status="retrieved",
        supports=("A semi-automated pipeline measuring soma, neurite "
                  "outgrowths, and the density of BEADS and SHARP BENDS on "
                  "individual neurites - the established vocabulary to reuse "
                  "when damage scoring extends to neurons, and a direct "
                  "parallel to the fibre-bending measure already used for the "
                  "pharynx.")),
}


# Alternatives that were built, measured and lost. Recorded because SEVERAL OF
# THEM WON ON THE OBVIOUS METRIC and were rejected anyway - without the numbers
# a later reader would reasonably try them again and reach the same dead end.
REJECTED = {
    "fibre_spacing_cue": dict(
        instead_of="valley_operator",
        alternative="Fibre spacing as a boundary cue.",
        why=("Scored the HIGHEST pointwise cue power of anything tried, 0.972, "
             "and still made the tool worse: end-to-end boundary recall fell "
             "from 63.7% to 49.9%. It is diffuse - it says a boundary is "
             "nearby, not where. Pointwise AUC is not localisation, and this "
             "is the clearest example we have of the difference."),
        numbers="cue power 0.972; recall 63.7% -> 49.9%"),

    "gradient_magnitude": dict(
        instead_of="valley_operator",
        alternative="Gradient magnitude to find the myocyte seam.",
        why=("A gradient is zero at the CENTRE of a dark line, so it cannot "
             "localise a dim seam - it finds the two shoulders instead."),
        numbers="cue power 0.788 against 0.915 for the valley operator"),

    "curvature_following_vote": dict(
        instead_of="junction_splitting",
        alternative="Let convergence votes follow fibre curvature.",
        why=("Produced a vote map 14x peakier, which looked like a large "
             "improvement, and every downstream metric got worse."),
        numbers="14x peak sharpening, all metrics down"),

    "terminal_width_taper": dict(
        instead_of="taper_shape",
        alternative="Tell head from tail by mean width over the terminal fifth.",
        why=("Both ends taper. A steep head taper makes the head's last few "
             "percent as narrow as the tail's, so the two ends read as nearly "
             "identical and the call falls to noise."),
        numbers="superseded before deployment, on Andres's anatomy note"),

    "own_flank_vulva_normalisation": dict(
        instead_of="vulval_gap",
        alternative=("Compare each bending sense against its own flanking "
                     "regions to isolate the vulval deficit."),
        why=("Looked like it removed the global asymmetry, and did not: "
             "curvature magnitude varies along the body with where the "
             "travelling wave's peaks fall, and that positional bias survives. "
             "A worm with NO vulval notch scored -0.99."),
        numbers="no-notch control -0.993; difference-in-differences gives -0.001"),

    "whole_mask_texture": dict(
        instead_of="pharynx_confinement",
        alternative="Measure pharyngeal texture over the whole worm mask.",
        why=("Dominated by the body EDGE, and the thin tail has more edge per "
             "unit area than anywhere else - so the cue became a second, worse "
             "taper detector instead of independent evidence."),
        numbers="fixed by eroding to the interior before measuring"),

    "averaged_cue_combination": dict(
        instead_of="noisy_or_combination",
        alternative="Combine agreeing cues by weighted average.",
        why=("Two independent cues that AGREE came out below the stronger one "
             "alone - the wrong direction for corroborating evidence."),
        numbers="0.234 alone -> 0.170 averaged with an agreeing 0.074"),

    "median_interval_rate": dict(
        instead_of="cardiac_rhythm_vocabulary",
        alternative="Take pumping rate from the median inter-event interval.",
        why=("Events land on integer frames, so a period that is not a whole "
             "number of frames alternates between two values - 7.5 frames "
             "becomes 7, 8, 7, 8 - and the median picks one of them."),
        numbers="several percent rate bias; mean of steady intervals instead"),

    "synthetic_roi_statistics": dict(
        instead_of="brightness_statistic_choice",
        alternative=("Choosing the brightness statistic from a synthetic ROI: "
                     "max is area-biased and noisy, mean is fine."),
        why=("Both halves failed on the lab's own hand-curated extraction. The "
             "MEAN tracks ROI area (median r = -0.34, |r| > 0.3 in 27 of 48 "
             "hemisegments) and the max barely does (-0.02); controlling for "
             "area destroys 10 of 22 mean-based curvature relationships "
             "against 1 of 13 for the max. The synthetic ROI had homogeneous "
             "pixels, so it measured sampling noise in a uniform region. A "
             "real hemisegment is 28 pixels of part muscle and part dark "
             "tissue, and its mean is set by how much dark tissue the bend "
             "happened to include."),
        numbers=("mean-vs-area r -0.34 against max -0.02; 10/22 vs 1/13 "
                 "relationships lost to area control")),

    "column_name_type_inference": dict(
        instead_of="coerce_numeric_from_data",
        alternative="Decide which CSV columns are numeric from their names.",
        why=("Would have coerced fps_source='declared' to NaN, destroying "
             "provenance. Caught only by surveying real CSVs."),
        numbers="rejected before shipping"),
}


# What we have NOT solved. Stated plainly, with what a solution would have to
# show - these are the openings for whoever comes next.
OPEN_PROBLEMS = {
    "head_region_boundary_recall": dict(
        problem=("Myocyte boundary detection reaches 83.5% held-out recall at "
                 "midbody but only 57.9% at the head."),
        suspected=("The head is imaged at higher zoom and the cells are "
                   "smaller and more crowded; DETECT_SCALE compensates only "
                   "crudely."),
        would_resolve="Head recall above 75% without midbody regressing.",
        data="myocyte_marks_W1_ventral_head.npz, myocyte_marks_W1_midbody.npz"),

    "fibre_length_capture": dict(
        problem=("Per-fibre segmentation captures about 57% of expected fibre "
                 "length, and pushing it higher makes downstream boundary "
                 "detection WORSE."),
        suspected=("Longer traces bridge junctions between neighbouring "
                   "fibres, so the extra length is partly wrong length."),
        would_resolve=("Higher captured length with boundary evidence held or "
                       "improved - the pair, not either alone."),
        data="myocyte_vertices_head.npz, myocyte_vertices_midbody.npz"),

    "interior_voids_over_called": dict(
        problem=("interior_holes finds 23 voids in a pharynx where Andres "
                 "marked 1."),
        suspected=("Unresolved: the 22 may be real sub-threshold texture, "
                   "lumen branches, or noise. Never diagnosed."),
        would_resolve=("An account of what the 22 are, then a detector whose "
                       "count matches marked damage."),
        data="pharynx_marks_W4_head.png"),

    "bright_scar_unvalidated": dict(
        problem=("bright_scar and the axial scar in Andres's second marked "
                 "field are implemented but never validated."),
        suspected="No second-scorer marks exist for them yet.",
        would_resolve="Agreement with marks on a field not used to build it.",
        data="pharynx_marks_W2_head.png"),

    "no_fiji_parity_check": dict(
        problem=("The Python extraction front-end has never been compared "
                 "against WormRGBCaMPMap_v1.java on the same recording."),
        suspected="Not a defect - the comparison has simply not been run.",
        would_resolve=("One recording processed both ways, agreeing on "
                       "per-segment intensities and head assignment."),
        data="needs a recording already processed through the Fiji plugin"),

    "dv_untested_on_real_animals": dict(
        problem=("Dorsal/ventral identification passes on synthetic worms "
                 "only. The excursion asymmetry and the vulval gap have never "
                 "been measured on a real swimming recording."),
        suspected=("Both effects may be smaller than the fixture's, and the "
                   "vulval one is local and needs spatial resolution."),
        would_resolve=("Cohort agreement via reconcile_ventral on real "
                       "swimmers, checked against animals scored by eye."),
        data="any swimming recording with adult hermaphrodites"),
}


# CORRECTIONS: where Andres's input overturned or redirected work the assistant
# had already done.
#
# This exists because a count of contributed methods cannot answer the question
# that actually matters - whether the person supervising this was exercising
# judgement or accepting output. A list of ideas cannot distinguish the two. A
# record of REJECTED output can: nobody blindly accepts a method they reversed.
#
# Each entry names an artefact - a module, test or fixture - so a reader can
# check it against the repository rather than take this file's word for it.
# `severity` is deliberately blunt, and "reversed" is reserved for cases where
# the direction of the work changed, not where a parameter moved.
CORRECTIONS = [
    dict(severity="reversed", topic="Myocyte boundaries are an intensity feature",
         assistant_had=("Opened by asserting the myocyte boundary is NOT an "
                        "intensity feature, and built accordingly."),
         andres_said=("Phalloidin penetrates each cell individually, so each "
                      "myocyte has its own brightness signature."),
         consequence=("The premise was wrong. Intensity became one of the two "
                      "combined cues."),
         evidence="tools/fibre_orientation.py; method per_cell_brightness_signature"),

    dict(severity="reversed", topic="Search direction for the boundary",
         assistant_had="Searched for boundaries TRANSVERSELY across the body.",
         andres_said=("Hand-marked two fields. His ink was 99% within 30 "
                      "degrees of the body AXIS."),
         consequence=("A ~90 degree error, not a tuning miss. The whole search "
                      "was rebuilt longitudinally."),
         evidence="myocyte_marks_W1_ventral_head.npz; method "
                  "longitudinal_boundary_geometry"),

    dict(severity="reversed", topic="Cell shape",
         assistant_had="Drew vertical boundary lines.",
         andres_said="\"The muscles are rhomboid.\"",
         consequence="Shape prior replaced; guided seam tracing added.",
         evidence="tools/fibre_orientation.trace_seam_guided"),

    dict(severity="reversed", topic="Where radial organisation can be measured",
         assistant_had=("Measured pharyngeal fibre coiling across the whole "
                        "organ, reporting 53% of fibre area as disrupted."),
         andres_said=("\"The center has the lumen so it is intrinsically non "
                      "radial.\""),
         consequence=("The measure had been scoring the core, where radial was "
                      "never the expectation. Restricted to the cortex."),
         evidence="tools/pharynx_continuity.cortex_mask; method "
                  "cortex_only_measurement"),

    dict(severity="corrected evaluation", topic="How boundary recall was scored",
         assistant_had="Reported a single held-out recall of 63.7%.",
         andres_said="Pointed out the field contains two quadrants.",
         consequence=("Scoring split: 84.2% between quadrants, 56.2% within. "
                      "The single number had been averaging two different "
                      "problems and describing neither."),
         evidence="tools/fibre_trace.py boundary_evidence scoring"),

    dict(severity="reversed", topic="Head/tail by terminal width",
         assistant_had=("A taper cue comparing mean width over the terminal "
                        "fifth of each end."),
         andres_said=("Both ends taper. The tail taper is long and shallow and "
                      "comes to a point; the head taper is short, steep and "
                      "round."),
         consequence=("The cue was measuring the wrong property. Rebuilt on "
                      "taper LENGTH and tip bluntness."),
         evidence="tools/head_tail.taper_cue; REJECTED[terminal_width_taper]"),

    dict(severity="supplied capability", topic="Dorsal/ventral identification",
         assistant_had=("No dorsoventral capability at all; it was listed as a "
                        "remaining task with no proposed method."),
         andres_said=("Ventral excursions run deeper than dorsal ones during "
                      "movement; and the vulva required myocyte apoptosis, so "
                      "an adult bends differently there at one precise spot."),
         consequence=("Two independent cues, and the step that unblocks "
                      "hemisegment labelling."),
         evidence="tools/head_tail.identify_ventral, vulva_cue"),

    dict(severity="supplied capability", topic="Finding the pharynx in DIC",
         assistant_had=("A generic texture measure that would score debris and "
                        "gut contents as readily as a pharynx."),
         andres_said=("The pharynx is visible in DIC and makes the head read "
                      "LIGHTER than the region behind it; the tail matches the "
                      "body. Also that the confocal pharynx work might help."),
         consequence=("Two features instead of one, and confinement to a "
                      "pharynx length instead of raw texture. Smeared texture "
                      "now scores -0.02 against 0.30 for a real pharynx."),
         evidence="tools/head_tail.pharynx_cue; method pharynx_confinement"),

    dict(severity="found defect", topic="Corrections did not propagate",
         assistant_had=("Assumed hand corrections propagated through the "
                        "tracking tools."),
         andres_said=("Corrections should propagate to successive frames, "
                      "\"which currently does not happen in at least some "
                      "tools (I believe).\""),
         consequence=("Correct. run_neuron_tracker recomputed one frame and "
                      "left every later frame tracking from the wrong state."),
         evidence="tools/afd_neuron/run_neuron_tracker.py"),

    dict(severity="found defect", topic="What the GCaMP recordings contain",
         assistant_had=("Treated each folder as one recording and failed to "
                        "detect the worm."),
         andres_said=("Kiley used transmitted light at low magnification to "
                      "find a worm, zoomed in, turned transmitted light off, "
                      "filmed in blue light, then repeated for the next worm."),
         consequence=("One folder holds many separate acquisitions. Session "
                      "splitting was built from this description."),
         evidence="GCaMP feasibility/extractor session splitting"),

    dict(severity="redirected", topic="Which physiology the pharynx resembles",
         assistant_had="No stated position.",
         andres_said="\"Our pharynx is closer to cardiac than skeletal.\"",
         consequence=("Sent the damage-scale search to cardiology, which "
                      "supplied both the beat-to-beat vocabulary and the ISHLT "
                      "reproducibility cautionary tale."),
         evidence="app/event_rhythm.py; method cardiac_rhythm_vocabulary"),
]


# The record has to cut both ways or it is advocacy. These are places where
# Andres's stated expectation was revised by evidence, or where he corrected
# himself. Recorded for the same reason as everything above: a one-sided
# account is not an audit.
COUNTER_RECORD = [
    dict(topic="How underreported cycle variability is",
         andres_expected=("That cycle-to-cycle variability in timing and "
                          "excursion is \"going completely underreported in "
                          "the nematode literature (I believe; but check)\"."),
         evidence_showed=("Partly wrong, and he asked for the check. "
                          "Variability of defecation PERIOD is established, "
                          "with a landmark result: gon-2/gtl-1 knockdown "
                          "raises it with no change in the mean. What is thin "
                          "is variability of waveform SHAPE."),
         outcome=("The claim was narrowed to the defensible one and the "
                  "existing result cited rather than rediscovered.")),

    dict(topic="Number of myocytes in the marked field",
         andres_expected="Said five myocytes were in view.",
         evidence_showed="He recounted and corrected it to seven.",
         outcome="Self-corrected before it affected any scoring."),
]


class ProvenanceError(Exception):
    """Refusals that name the consequence."""


def contribution_audit():
    """Quantify supervision, not just authorship.

    Two numbers answer different questions. METHODS says who originated what -
    but a reader can dismiss that as a list of suggestions accepted wholesale.
    CORRECTIONS answers the harder question, because a method someone reversed
    is a method they did not blindly accept, and the reversals are checkable
    against the files named in each entry.

    COUNTER_RECORD is included in the same summary on purpose. An audit that
    only ever finds the supervisor was right is not an audit.
    """
    by_sev = {}
    for c in CORRECTIONS:
        by_sev[c["severity"]] = by_sev.get(c["severity"], 0) + 1
    origin = attribution_summary()
    return {
        "methods_total": origin["n_methods"],
        "methods_by_origin": origin["by_origin"],
        "methods_contributed_to": origin["contributed_to"],
        "corrections_total": len(CORRECTIONS),
        "corrections_by_severity": by_sev,
        "reversals": by_sev.get("reversed", 0),
        "counter_record_entries": len(COUNTER_RECORD),
        "rejected_alternatives": len(REJECTED),
        "open_problems": len(OPEN_PROBLEMS),
        "what_this_establishes": (
            f"{len(CORRECTIONS)} occasions where the supervising scientist's "
            f"input overturned or redirected work already done, "
            f"{by_sev.get('reversed', 0)} of them reversing the direction of a "
            f"method rather than adjusting it. Output that is reversed is not "
            f"output that was accepted uncritically."),
        "auditable": (
            "Every correction names a module, test or fixture in this "
            "repository, so the claim can be checked against the code and the "
            "commit history rather than taken on this file's word."),
        "not_one_sided": (
            f"{len(COUNTER_RECORD)} entries record where his own stated "
            f"expectation was revised by evidence. An audit that only ever "
            f"finds the supervisor correct is advocacy."),
    }


def check_registry(methods=None):
    """Validate the registry; a wrong attribution is worse than none."""
    methods = METHODS if methods is None else methods
    problems = []
    for key, m in methods.items():
        if m.get("origin") not in ORIGINS:
            problems.append(f"{key}: origin {m.get('origin')!r} not in {ORIGINS}")
        contrib = m.get("contribution") or {}
        if not contrib:
            problems.append(f"{key}: no contribution recorded")
        for who in contrib:
            if who not in ("andres", "claude", "literature"):
                problems.append(f"{key}: unknown contributor {who!r}")
        origin = m.get("origin")
        if origin in ("andres", "claude", "literature") and origin not in contrib:
            problems.append(
                f"{key}: origin is {origin!r} but {origin!r} contributed nothing")
        if origin == "joint" and len(contrib) < 2:
            problems.append(f"{key}: marked joint but has one contributor")
        # A literature contribution with no reference is an appeal to an
        # authority nobody can look up.
        for ref in m.get("refs", []):
            if ref not in REFERENCES:
                problems.append(f"{key}: unknown reference {ref!r}")
        if "literature" in contrib and not m.get("refs"):
            problems.append(
                f"{key}: claims a literature contribution but cites nothing")
    return problems


def check_references(refs=None):
    """Validate the bibliography, and separate what was fetched from what was not."""
    refs = REFERENCES if refs is None else refs
    problems, recalled = [], []
    for key, r in refs.items():
        if r.get("status") not in ("retrieved", "recalled"):
            problems.append(f"{key}: status {r.get('status')!r} is not "
                            f"'retrieved' or 'recalled'")
        if not r.get("citation") or not r.get("supports"):
            problems.append(f"{key}: missing citation or what it supports")
        if r.get("status") == "retrieved" and not r.get("url"):
            problems.append(f"{key}: marked retrieved but has no URL")
        if r.get("status") == "recalled":
            recalled.append(key)
            if not r.get("check"):
                problems.append(
                    f"{key}: recalled but does not say what to verify")
    cited = {ref for m in METHODS.values() for ref in m.get("refs", [])}
    # A claim we made that the SOURCE DID NOT SUPPORT. This outranks an
    # unverified citation: an unfetched reference is a gap a reader can see,
    # whereas a retrieved reference attached to a claim it does not make reads
    # as fully supported and is not visible to anyone.
    unconfirmed = {k: r["unconfirmed"] for k, r in refs.items()
                   if r.get("unconfirmed")}
    still_to_check = {k: r["check"] for k, r in refs.items()
                      if r.get("check") and r.get("status") == "retrieved"}
    return {
        "problems": problems,
        "n_references": len(refs),
        "retrieved": [k for k, r in refs.items() if r.get("status") == "retrieved"],
        "recalled": recalled,
        "uncited": sorted(set(refs) - cited),
        "unconfirmed_claims": unconfirmed,
        "details_still_to_check": still_to_check,
        "publication_blocker": (
            (f"{len(recalled)} of {len(refs)} references are RECALLED, not "
             f"retrieved, and must be verified before publication. "
             if recalled else
             f"All {len(refs)} references were retrieved from source. ")
            + (f"{len(unconfirmed)} carry a claim the source did NOT confirm - "
               f"these matter more, because a retrieved citation attached to a "
               f"claim it does not make looks fully supported. See "
               f"`unconfirmed_claims`."
               if unconfirmed else "No unconfirmed claims outstanding.")
            + (f" {len(still_to_check)} have a bibliographic detail still to "
               f"pin down." if still_to_check else "")),
    }


def references_section(heading="## References"):
    """Render the bibliography, keeping verified and unverified visibly apart."""
    c = check_references()
    lines = [heading, "", "### Retrieved", "",
             "*Fetched during development; the URL is the source used.*", ""]
    for k in c["retrieved"]:
        r = REFERENCES[k]
        lines.append(f"- **[{k}]** {r['citation']}  \n  <{r['url']}>  \n"
                     f"  *Supports:* {r['supports']}")
    if c["recalled"]:
        lines += ["", "### Recalled — VERIFY BEFORE PUBLICATION", "",
                  "*The finding is what the method rests on; the bibliographic "
                  "detail is written from memory and has not been re-fetched. "
                  "A wrong citation sends a reader somewhere that does not "
                  "support the claim, which is worse than no citation.*", ""]
        for k in c["recalled"]:
            r = REFERENCES[k]
            lines.append(f"- **[{k}]** {r['citation']}  \n"
                         f"  *Supports:* {r['supports']}  \n"
                         f"  *To verify:* {r['check']}")
    if c["unconfirmed_claims"]:
        lines += ["", "### Claims the sources did NOT confirm", "",
                  "*Retrieved references attached to something we said that "
                  "the paper does not actually establish. These are more "
                  "dangerous than a missing citation, because the reference "
                  "makes the claim look supported.*", ""]
        for k, note in c["unconfirmed_claims"].items():
            lines.append(f"- **[{k}]** {note}")
    if c["details_still_to_check"]:
        lines += ["", "### Bibliographic details outstanding", ""]
        for k, note in c["details_still_to_check"].items():
            lines.append(f"- **[{k}]** {note}")
    lines += ["", c["publication_blocker"], ""]
    return "\n".join(lines)


def attribution_summary(methods=None):
    """Counts by origin, and how many methods each party contributed to.

    The two are different and both belong in the manual: `by_origin` says where
    the decisive idea came from, `contributed_to` says who was involved at all.
    Reporting only the first would erase everyone but the originator; reporting
    only the second would make every party look equally decisive.
    """
    methods = METHODS if methods is None else methods
    by_origin, contributed = {o: 0 for o in ORIGINS}, {}
    for m in methods.values():
        by_origin[m["origin"]] = by_origin.get(m["origin"], 0) + 1
        for who in (m.get("contribution") or {}):
            contributed[who] = contributed.get(who, 0) + 1
    return {
        "n_methods": len(methods),
        "by_origin": by_origin,
        "contributed_to": contributed,
        "note": ("`by_origin` is where the decisive idea came from; "
                 "`contributed_to` is who was involved at all. Most methods "
                 "here have more than one contributor, which is why both are "
                 "reported."),
    }


LABELS = {"andres": "Andres Vidal-Gadea", "claude": "assistant (Claude)",
          "literature": "published literature"}


def methods_section(keys=None, methods=None, heading="## Methods"):
    """Render the manual's methods section with attribution per method."""
    methods = METHODS if methods is None else methods
    keys = list(methods) if keys is None else list(keys)
    missing = [k for k in keys if k not in methods]
    if missing:
        raise ProvenanceError(
            f"No provenance recorded for {missing}. Add an entry rather than "
            f"publishing a method with no attribution - an unattributed method "
            f"reads as though it came from nowhere, and by the time anyone "
            f"asks, the history has blurred.")

    lines = [heading, ""]
    for k in keys:
        m = methods[k]
        lines.append(f"### {m['title']}")
        lines.append("")
        lines.append(f"*Origin: {LABELS.get(m['origin'], m['origin'])}"
                     f"{' (joint)' if m['origin'] == 'joint' else ''}* — "
                     f"`{m['module']}`")
        lines.append("")
        for who, what in (m.get("contribution") or {}).items():
            lines.append(f"- **{LABELS.get(who, who)}:** {what}")
        if m.get("verified"):
            lines.append(f"- *Verified:* {m['verified']}")
        lines.append("")
    s = attribution_summary(methods)
    lines += [
        "### Attribution summary", "",
        f"{s['n_methods']} methods. Decisive idea: "
        + ", ".join(f"{v} {k}" for k, v in s["by_origin"].items() if v),
        "",
        "Contributed to: "
        + ", ".join(f"{LABELS.get(k, k)} {v}"
                    for k, v in sorted(s["contributed_to"].items())),
        "", s["note"], "",
    ]
    return "\n".join(lines)


def supersession_brief(heading="## For whoever improves on this"):
    """What a better method must beat, what already failed, and what is unsolved.

    Written to be read by someone who was not here - another lab, a student, or
    a later assistant reading the repository. The rejected alternatives are the
    most valuable part and the least obvious: several of them WON on the metric
    anyone would reach for first, and a reader without the numbers would
    reasonably spend their time re-deriving them.
    """
    lines = [heading, "",
             "Nothing here is settled. Each method below records what it must "
             "be beaten on; each rejected alternative records why it lost, "
             "with numbers; each open problem is something we could not do.",
             ""]

    lines += ["### Already tried and rejected", "",
              "*Several of these scored BETTER on the obvious metric and were "
              "rejected anyway. If you are about to try one, read why first.*",
              ""]
    for key, r in REJECTED.items():
        lines.append(f"**{r['alternative']}**  \n"
                     f"Considered instead of `{r['instead_of']}`. {r['why']}  \n"
                     f"*Numbers:* {r['numbers']}")
        lines.append("")

    lines += ["### Open problems", "",
              "*These are the openings. Each names the data to work from.*", ""]
    for key, p in OPEN_PROBLEMS.items():
        lines.append(f"**{key}** — {p['problem']}  \n"
                     f"*Suspected cause:* {p['suspected']}  \n"
                     f"*A solution would show:* {p['would_resolve']}  \n"
                     f"*Data:* {p['data']}")
        lines.append("")

    limits = [(k, m) for k, m in METHODS.items() if m.get("known_limits")]
    if limits:
        lines += ["### Known limits of methods in use", ""]
        for k, m in limits:
            lines.append(f"- **{m['title']}** — {m['known_limits']}")
        lines.append("")
    return "\n".join(lines)


def contribution_statement(heading="## Contributions"):
    """The attribution and the supervision record, rendered together."""
    a = contribution_audit()
    lines = [heading, "",
             f"{a['methods_total']} methods are recorded with attribution. "
             f"Decisive idea: "
             + ", ".join(f"{v} {k}" for k, v in a["methods_by_origin"].items() if v)
             + ". Involvement: "
             + ", ".join(f"{LABELS.get(k, k)} {v}"
                         for k, v in sorted(a["methods_contributed_to"].items()))
             + ".", "",
             "### Supervision record", "", a["what_this_establishes"], "",
             a["auditable"], "", a["not_one_sided"], ""]
    for c in CORRECTIONS:
        lines.append(f"- **{c['topic']}** *({c['severity']})* — "
                     f"The implementation had: {c['assistant_had']} "
                     f"AVG: {c['andres_said']} Consequence: {c['consequence']} "
                     f"(`{c['evidence']}`)")
    lines += ["", "### Where the evidence went the other way", ""]
    for c in COUNTER_RECORD:
        lines.append(f"- **{c['topic']}** — Expected: {c['andres_expected']} "
                     f"Evidence showed: {c['evidence_showed']} "
                     f"Outcome: {c['outcome']}")
    lines.append("")
    return "\n".join(lines)
