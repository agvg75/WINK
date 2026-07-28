# T8 Magnetotaxis — Reconciled Work Order v10.4

## Biological aim

Separate plate-scale magnetic redistribution from the stronger claim that an
individual worm maintains an angle to the local three-dimensional field.

## Use this tool when

Tier 1 accepts validated Population Orientation plate-state results. Tier 2
requires Population Orientation Config 2 technical validation and remains
gated until identity and heading accuracy are demonstrated on crowded plates.

## Biological decisions the user must make

Declare magnet geometry and orientation, plate/magnet rotation design, pulse
condition, humidity, food-removal time, worm age and genotype. Choose controls
and approve the field overlay. Angles from assays missing these state variables
must not be compared.

## User variables and why they matter

The magnet provider takes remanence in tesla and dimensions/positions in metres
internally. Vertical distance dominates uncertainty. The optional Earth field
is expressed in tesla. Rotation at three or more distinct magnet orientations
is required to distinguish field-locked (slope near one) from room-locked
(slope near zero) behavior.

## Method

Magpylib computes the three-component field, magnitude, gradient and
inclination. A closed-form axial cylinder calculation must agree within one
percent. C2 reports radial, field-vector and laboratory frames and refuses a
direction where none is identifiable. The plate aggregator performs the
rotation regression. The Tier 2 harness injects a known 120-degree offset and
requires higher concentration in the correct field frame than in the wrong lab
frame.

## Outputs and interpretation

Tier 1 reports plate occupancy/distribution, arrivals and plate resultants only.
Tier 2, once validated, may report per-worm heading decomposition and S5
departure latency, re-entry and central dwell. Non-departure is censored. A
single orientation cannot certify a magnetic vector response.

## Failure modes and cautions

Wrong vertical distance, magnet position or coordinate sign can produce a
plausible but false field. Endpoint-only data cannot establish fixed-angle
tracking. Intrinsic circling and room cues require sham and rotation controls.
Tier 2 returns a stated refusal while Config 2 validation is incomplete.

## Special tuning and validation ladder

1. SI closed-form provider check.
2. Synthetic 120-degree fixed-angle recovery and wrong-frame rejection.
3. Manual-versus-automatic crowded-plate identity/heading fixture.
4. Config 2 status deliberately changed only after the technical gate passes.
5. Biological targets (including tax-2 and humidity behavior) are validation
   targets, not constants forced into analysis.

See the definitive manual Part II for operation and Part VIII for validation.

## v0.2 covariate and state extension

Assay setup now requires a real time-off-OP50 zero, entered as elapsed time at
assay start or as food-removal and assay-start clock times. The raw per-segment
export retains assay elapsed time and physiological time separately, plus
kinematics, initial roaming/dwelling state, optional pick state, and explicit
primary/exploratory predictor roles.

The within-plate toward/away analysis tests comparable held-angle
concentration, near-180-degree rotation, and conserved signed curvature. Thin
regimes are withheld. Reorientation modes require reviewed spine quality and
otherwise return `unclassified`. Non-departers and their opening-state
composition remain results. All additions remain computational regression
until real crowded-plate Config 2 technical validation passes.
