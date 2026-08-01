# Handoff: Population Swimming → WINK cockpit migration

**Status as of 2026-08-01: Route B (full `ReviewWorkbench` migration) is DONE,
written to both the `staged/` repo payload and the L: deploy snapshot, and its
numeric firewall is proven by an A/B test run. It has NOT been GUI-tested and
NOT been committed, tagged or released.** See `docs/CHANGELOG_v11.116.md` for
exactly what changed, what was verified, and the release steps.

The remaining work is GUI verification and release, not code. Everything below
the "Original handoff" line is kept for context.

## 0. Where the code lives — read this first

There are **two** locations and they are not interchangeable:

- **`…\Documents\Behavior Analysis\LabTools_Reorganization\staged\`** — a git
  repo, and **the source of truth that ships to GitHub** (`agvg75/WINK`).
  Version is single-sourced from `staged/app/release_info.json`; tagging
  `vN` triggers `.github/workflows/release.yml` to build and publish. It also
  holds the **test suite** (`staged/tests/`, ~480 files) which is *not* deployed.
- **`L:\10_AGVG LAB\Lab Tools\WINK_Lab_Tools_v{version}_Current_Files\`** — the
  **deploy target** users on the lab network run. It has no `tests/`.

Edit `staged/`, then deploy to L:. Editing only L: means the change never
reaches GitHub — that is the trap this handoff previously walked into.

The toolset was renamed NIKE → WINK; **WINK is current, NIKE folders are
legacy.** The earlier version of this document told you to look for
`NIKE_Lab_Tools_v11.XX_Current_Files` — wrong, and it is why this file ended up
written into a dead mirror. To resolve the current L: snapshot without guessing:
`Launch_WINK_Latest.ps1` reads `updates\update_manifest.json`, takes
`app_version`, and launches `WINK_Lab_Tools_v{app_version}_Current_Files`.

Note a stale mirror exists: `NIKE_Lab_Tools_v11.115_Current_Files` is a
byte-for-byte copy of the same version **minus** `tools/failure_library/
failure_gallery.py`, plus the old copy of this handoff. Nothing runs from it.
Do not edit it.

The L: tree is **not** a git repo — edits there are plain file edits, so a
stale folder choice silently loses work.

## 0b. How to actually verify a change here

Use `C:\ProgramData\LabTools\.venv\Scripts\python.exe` (Python 3.13.14, with
`cv2` 5.0.0, `pandas` 3.0.3, `matplotlib` 3.11.0). The bare `py -3` launcher on
this machine resolves to a different runtime with **no** `cv2` or `pandas`.

The tests in `staged/tests/` are plain assert scripts — run them directly with
that interpreter (there is no `pytest` installed). For a firewall check, run
the relevant test with the committed code, save its outputs, apply the change,
re-run, and byte-compare. Be aware that re-running rewrites the committed
golden CSVs even with no code change (the goldens predate the current cv2 /
pandas), so `git checkout -- staged/tests/<fixture>/` afterwards.

## 1. What the cockpit is

`app/process_ui.py` defines the shared single-window UI pattern:

- `CockpitApp` (line ~572) — main application window: left `controls`, center
  panel, right hood. Tools subclass it.
- `ReviewWorkbench` (line ~380) — the shared in-cockpit review window
  (controls | matplotlib canvas + toolbar | process hood). Aliased
  `ModuleWorkbench`. Clamps itself to the screen, centres, and is deliberately
  not `transient` so Windows keeps its minimise/maximise buttons.
- `ProcessLog` (line ~301) — the hood's step model.
- `standardize_matplotlib_window(fig, ...)` (line ~265) — best-effort helper for
  figures that are still raw pyplot.
- `apply_wink_theme(root)` (line ~25) — WINK visual theme.

Tools using `ReviewWorkbench`: `egg_counting` (the original reference
implementation, lines 143 and 831) and now `population_swimming`.

## 2. What was done

Both review stages in `tools/population_swimming/population_swimming_tool.py`
were ported off `matplotlib.pyplot` into `ReviewWorkbench`:

| Was | Now |
|---|---|
| line 146 `plt.subplots()` + 4 figure buttons, line 214 `plt.show()` | `ReviewWorkbench`; buttons are control-panel buttons; hood logs accept/reject/stitch/undo |
| line 393 `plt.subplots(figsize=(10,7))`, line 421 `plt.show()` | `ReviewWorkbench`; Play moved to a control button; slider stays matplotlib on purpose |
| line 333 bare `tk.Toplevel` bout list | still a `Toplevel` (it is a table, not a canvas) but themed, screen-clamped, centred, resizable, no longer `transient` |

`import matplotlib.pyplot` is gone from the tool entirely.

Also fixed along the way: dialogs raised inside a review now pass `parent=`, the
bout list gets its Tk grab back after a preview closes, the playback timer and
frame reader are closed on window close, and `preview_bout` no longer leaks the
frame reader on the empty-track path.

## 3. What is left

1. **GUI test.** Run one recording through analysis → track review → bout review
   → bout preview. Confirm: no window opens behind the cockpit, every window can
   be closed on a laptop screen, stitching and undo still work, Play/Pause
   works, closing the preview stops playback.
2. **Release.** Steps are listed at the end of `docs/CHANGELOG_v11.116.md`.

**Firewall check: already done.** `tests/test_population_swimming.py` was run
with the committed v11.115 tool and again with the port; every scientific
output was byte-identical (`detections_and_tracks.csv`, `track_summary.csv`,
`modality_bouts_for_review.csv`, `modality_window_proposals.csv`,
`analysis_rois.json`, in both result sets). Only wall-clock timings differ.
The engine `population_swimming.py` is byte-identical.

## 4. Hard constraints (unchanged)

- **Scientific firewall** (`docs/development/CROSS_TOOL_PROPAGATION_POLICY.md`):
  UI/interface/navigation infrastructure may be shared freely, but segmentation,
  frequency, posture, identity and other assay metrics require assay-specific
  validation. **This work is UI-only — it must not change a single number.**
- **Claude cannot test the GUI.** No Tk/matplotlib window can be opened in the
  agent session. Validate what is validatable headless and then have the user
  run it. Do not claim the UI works from code inspection alone.
- The runtime with the full dependency set is
  `C:\ProgramData\LabTools\.venv\Scripts\python.exe` (Python 3.13.14, with
  `cv2`, `pandas`, `matplotlib`). The bare `py -3` launcher on this machine
  resolves elsewhere and has **no** `cv2` or `pandas` — use the venv.
- Add a `docs/CHANGELOG_v11.XX.md` entry stating what was audited and what
  changed; that is the project convention and the propagation policy requires it.

## 5. Related context worth knowing

- Population Swimming had a performance pass earlier (frame-count fallback,
  histogram contrast stretch, `cv2.moments` orientation, two-sweep skeleton
  diameter). Those are **compute** changes, unrelated to this UI work, but they
  live in the same files — don't disturb them.
- The pharyngeal pumping tool is a good example of both the cockpit style and
  the dialog-layering fix (`pumping_tool.py`, `_install_dialog_front`).
- `tools/failure_library/failure_gallery.py` (edited 2026-08-01) is also present
  in the live tree but absent from the shipped v11.115 zip, so it is likewise
  unreleased.

---

## Original handoff (pre-migration, kept for context)

The defect this document was written about: Population Swimming was
half-migrated — `class App(CockpitApp)` at line 20 was correct, but the
trajectory review and bout review were raw `plt.show()` pop-ups importing none
of `ReviewWorkbench`, `standardize_matplotlib_window`, or `apply_wink_theme`.
The tool's own centre-panel text gave it away: it told the user to review "in
the pop-up windows".

Consequences were: no WINK theme on review windows; no v11.68 screen clamping,
so a large review window could push its close button off a laptop screen; and
`plt.show()` windows opening behind the cockpit.

Two routes were offered — **A**, keep the figures and route them through
`standardize_matplotlib_window()`; **B**, port both stages into
`ReviewWorkbench` per `egg_counting`. The user chose **B**.
