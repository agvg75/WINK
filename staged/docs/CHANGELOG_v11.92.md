# WINK Lab Tools v11.92 — Mechanosensation: reject the probe/pick

## The problem
In mechanosensation assays the experimenter introduces an object (a wire/pick)
to touch the worm and trigger an escape. Because that object is large and moves
into the frame, the single-worm tracker could **jump to the probe instead of the
worm**.

## The fix (uses two cues about the probe)
The probe is distinguishable from the worm by two facts:
1. it is **bigger than the worm** in area, and
2. it is **always contiguous with a frame edge** (it connects to the
   experimenter's hand off-screen).

The tracker now **demotes any candidate component that touches the frame border
*and* is larger than the worm reference**, so the worm is preferred. Details:

- It is a **penalty, not a hard reject**. If the probe is the only candidate —
  e.g. during contact, when it briefly merges with the worm — the blob is still
  selectable, so the worm is not dropped.
- A **worm-sized** animal that happens to crawl to the frame edge is **not**
  penalized (it fails the "larger than the worm" test), so ordinary edge-crawling
  assays are unaffected.
- Before the worm's area is calibrated, the previous frame's worm area is used as
  the size reference, so the cue works from the first contact frame.

## Where it applies
- New setup checkbox in the single-worm tracker: **"Ignore large objects touching
  the frame edge (probe / pick)."**
- The **mechanosensation module launches the tracker with this on by default**
  (`--ignore-border-objects`).
- **Off by default for every other assay** — crawling/swimming/burrowing behave
  exactly as before.

No measurement maths changed; only which connected component is chosen as the
worm.
