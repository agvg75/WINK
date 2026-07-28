# NIKE application v11.15

## Transmitted-light single-worm tracking

- Registers coherent background translation before temporal-background comparison.
- Tracks away from a trusted anchor in both temporal directions.
- Reconstructs only short failures bracketed by trusted spines on both sides.
- Retains raw geometry and exports explicit temporal-inference and endpoint-stabilization provenance.
- Applies the shared safeguards to DIC kinematics, pBoc, and AFD/neuron body tracking.
- Adds camera-registered temporal-background construction to the RGBCaMP DIC path.

## pBoc calibration

- Requires complete baseline, minimum-length peak, and fully recovered outlines for one example event.
- Learns shortening, area conservation, contraction/recovery duration, and rates.
- Measures posterior and anterior fractions of textured worm pixels participating in axial residual motion.
- Scores later candidates using flow, calibrated shortening, area conservation, axial participation, tracking confidence, and cadence priority.
- Preserves the 30-90 second cadence window as a review aid rather than an acceptance rule.
