# WINK Lab Tools v11.88 — project renamed NIKE → WINK

**NIKE is now WINK — Worm Imaging and Kinematics.** This release renames the
project's *user-facing identity*; nothing about how any measurement is computed
changed.

## What changed (display)
- Hub title and brand now read **WINK v{version}**, with **"Worm Imaging and
  Kinematics · formerly NIKE"** on the brand.
- Window titles, update dialogs, the acquisition advisor, the segmentation-review
  window, and the sample planner all say WINK.
- The sample planner page is now `wink_sample_planner.html`.

## Under the hood — dual-support (so nothing breaks)
- **Update channel:** the updater now accepts **both** `WINK_Lab_Tools_v…` and
  the historical `NIKE_Lab_Tools_v…` published-snapshot folder names. This
  release is published under **both** names, so clients running from an existing
  NIKE snapshot still redirect and update. New update packages are named
  `WINK_App_Update_*` (the manifest names the package, so older clients fetch it
  correctly).
- **Provenance:** output stamps now carry **both** `wink_app_version` /
  `wink_runtime_version` and the old `nike_*` keys, so downstream readers of
  pre-rename data still resolve.
- **Prior data:** internal session folders (`NIKE_Review_Sessions/`) and the
  reviewed-segmentation config filename are unchanged, so existing student
  results and sessions load exactly as before.

## Not renamed in this pass (intentional)
- The L: deployment folder, internal data-file/session names, and temp-file
  prefixes stay as-is to protect installed clients and prior data.
- The logo is the WINK text brand for now; the image swaps in once the PNG is
  placed at `resources/WINK_logo.png` (the loader already prefers it).
- Historical changelogs keep their original NIKE naming as dated records.
