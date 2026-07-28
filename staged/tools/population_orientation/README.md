# Population orientation

Configuration 1 (population state) is the development target. It will use median background subtraction and measure ROI occupancy, radial/angular pixel distributions, arrival, and descriptive blob counts without requiring identities.

`orientation_plate_stats.py` enforces the plate as the inferential unit. The legacy `orientation_stats.py` was audited and must not be used for plate assays because it explicitly treats worms as independent replicates.

Configuration 2 (per-worm paths) is gated until the arena is re-framed and a new clip with declared FPS and scale is supplied.
