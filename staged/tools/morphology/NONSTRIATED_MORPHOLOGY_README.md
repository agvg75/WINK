# Nonstriated muscle morphology

Manual-assisted feature extraction with pharynx, uterine, somatointestinal, and anal-depressor modes. Uterine mode provides a required interactive mask/skeleton/vector preview with adjustable multiscale ridge detection, then exports `strand_vectors.csv` as well as the segmentation overlay and structural features. Compact bright puncta no longer define the uterine mask merely because they are brighter than the strands. Automatic QC flags implausibly fragmented results for review. It deliberately leaves the composite damage score blank until raw WT, dystrophic, and rescue reference sets are used for calibration.

Uterine analysis requires four expected anatomical territories: anterior um1, anterior um2, posterior um1, and posterior um2. Draw the expected territory even when no fluorescent muscle is visible. `uterine_regions.csv` reports each territory independently as `network_detected`, `weak_or_fragmented`, or `no_detectable_network`. The last label is an observational detection result, not yet a biological absence call; calibrated reference distributions are required for that inference.

The anal-depressor mode requires proximal attachment and distal insertion clicks and reports a force-vector angle in the saved worm coordinate system. Orientation defaults persist per user but provenance is exported for every image.

Reusable interaction improvements (two-point calibration validation, preview before saving, adjustable controls, visible vectors, and QC status) must be audited for the pharyngeal and other morphology adapters. Tissue-specific segmentation parameters and anatomical labels must not be propagated without validation.
