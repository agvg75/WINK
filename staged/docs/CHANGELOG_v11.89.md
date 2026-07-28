# WINK Lab Tools v11.89 — WINK brand assets and manual

Follows the v11.88 NIKE → WINK rename. This release ships the WINK visual
identity and the updated reference manual. No measurement logic changed.

## What changed
- **Logo:** the WINK logo image now ships in `resources/WINK_logo.png`. The hub
  loader already prefers it over the historical `NIKE_logo.png`, so the hub now
  shows the WINK mark.
- **Definitive Manual** (`WINK_Lab_Tools_Definitive_Manual_v11.89.docx`),
  regenerated:
  - Title page now reads **WINK — Worm Imaging and Kinematics (formerly NIKE)**.
  - New **Part VII – Mechanosensation and evoked response** documents the
    evoked-mechanosensation tracker (movie-first flow, stimulus categories,
    before/during/after metrics, spontaneous-reversal detection, stop-vs-reverse)
    and the **population tap-response** tool (centroid tracking, tap detection
    from global field motion, paired before/after responder classification).
  - The **sample planner** ("how many more?") is added to the utilities part.
  - Part numbering corrected to **I–IX** with the duplicate part number removed;
    the Contents list matches the headings.

## Still dual-support
- Published under both `WINK_Lab_Tools_v11.89_Current_Files` and
  `NIKE_Lab_Tools_v11.89_Current_Files`, so existing NIKE installs keep updating.
- Provenance stamps still carry both `wink_*` and `nike_*` version keys.
