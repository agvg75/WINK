# NIKE application v11.18

## Resumable single-animal review

- Saves versioned work-in-progress review sessions without forcing final CSV export.
- Restores manual corrections, inferred geometry, flags, provenance, and reference dimensions when the recording is reopened.
- Lets the reviewer mark an interval with **b** (beginning) and **e** (end), then reconstructs only that interval from its trusted boundaries.
- Keeps **f** available to add a manual anchor on any frame; **w** saves while continuing, **q** or window close saves and exits, and **s** explicitly finalizes the CSV.
- Applies the workflow to the single-worm DIC tracker and anterior-neuron body tracker. pBoc event review remains versioned and resumable.

## pBoc calibration and identity

- Replaces typed baseline/peak/recovery frame numbers with a scrollable movie navigator and in-place outlines.
- Saves and restores the three-outline calibration.
- Learns acceptable adult length and area ranges from all three calibration outlines.
- Rejects substantially shorter/smaller larvae as target candidates instead of accepting the former 55%-length and 30%-area limits.

## Installation

- This is an application-only update. Existing NIKE installations can install it through **Help > Check for updates**; no runtime reinstall is required.
