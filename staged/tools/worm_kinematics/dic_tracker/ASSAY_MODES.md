# Track one worm assay modes

The tracking front end is shared. Identity, head and tail polarity, centerline,
manual correction, provenance, and missing-data rules remain common.

## Crawling

Use for worms moving on agar or food. The existing thickness, motion, and
continuity tracker remains the default. Body length is a diagnostic and lawn
track persistence is a QC target.

## Swimming

Use for one well-resolved swimming worm. Signed segment curvature supports swim
frequency, amplitude profiles, wave propagation, and head/tail phase.

Apparent shortening is treated as possible motion blur, tip truncation, or
out-of-plane roll. Blur-sensitive amplitudes must remain unavailable when
exposure or full-length tracking is inadequate.

The first staged mode exports the shared signed kinematics and acquisition
metadata. Advanced D/V, duty-cycle, coiling, and width-profile analysis will be
added only after real-video validation.

## Burrowing

Use for worms moving through a transparent or partly occluding substrate.
Measurements are limited to intervals where the animal is visible. Occlusion
is missing data, never an interpolated centerline. Reappearance requires an
identity check and may require a new manual head assignment.

Burrowing-specific three-dimensional inference is outside the current
two-dimensional tracker and must not be implied by this mode.
