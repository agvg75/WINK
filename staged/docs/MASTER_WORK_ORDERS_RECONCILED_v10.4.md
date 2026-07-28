# AGVG Lab Tools — Reconciled Master Work Orders v10.4

## Biological aim

Measure worm behavior and anatomy without manufacturing a positive result. The
inferential unit is declared for every assay; plates, not worms, are independent
replicates in population mode.

## Use this system when

Use the Hub when acquisition constants and biological state can be declared,
raw data and reviewed overlays can be retained together, and the recording
passes the per-metric Capability Gate. A red metric is a refusal unless an
expert records a force acknowledgment.

## Biological decisions the user must make

Declare genotype, age, feeding/state variables, assay geometry, controls,
stimulus timing and any event thresholds that cannot be prescribed. Confirm
segmentation, identities, ROIs and events. A non-event remains a valid outcome;
latency non-events are censored.

## User variables and why they matter

FPS, scale, exposure, bit depth, compression, duration, channel and anatomical
orientation travel with every result. Scale is cross-checked against measured
worm size. The Probe report feeds the Capability Gate; it is not a second
quality system.

## Method and dependency ladder

1. S1 validates intake and scale.
2. S2 returns pass/amber/red per metric; S3 records reproducible failures.
3. S4 supplies uncertain stimulus fields; S5 adds departure clocks without
   changing legacy basal-slowing tables.
4. C1 supplies reviewed reversal/escape events; C2 supplies the shared
   orientation frames and circular statistics.
5. Tier 3 assays consume those engines. T3/T5/T10/T11 consume existing reviewed
   Track-one-worm/Kinematics CSVs and do not introduce trackers.

Validation levels are `validated`, `experimental`, `experimental_gated`, and
`refused`. A feature may not silently promote itself.

## Outputs and interpretation

Population analyses summarize each plate first and analyze plate summaries
second. Output stamps include tool/version, acquisition constants, provenance,
review status and validation level. Passing metrics form the menu; gated
metrics show the acquisition bar required.

## Failure modes and cautions

Silent wrong answers outrank crashes. First-run guidance highlights parameters
to inspect. Post-run feedback is stored locally in the Failure Library and may
be prepared for user-approved email to VidalGadeaLab@gmail.com with the
project's sortable subject prefix. Pixels never leave the computer without
explicit opt-in. Unreproducible reports remain labeled unreproducible.

## Special tuning

Thresholds begin as provisional and must be recalibrated from measured manual
correction effort and regression fixtures. See the definitive manual Part II
for installation/workflow and Part VIII for validation and troubleshooting.

