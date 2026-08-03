"""Headless smoke test for myocyte_morphometry_tool.py.

Drives the real callbacks (image loading, boundary drawing, line proposal,
sarcomere detection, tick editing with add/drag/delete, save, blind
recount) via synthetic matplotlib button/motion events on the actual
embedded canvas, and a mocked file dialog for image loading, rather than
just instantiating the App or poking its attributes directly - per the
project's standing rule that construction-only tests miss layout and
interaction bugs.

That rule is not theoretical here: an earlier version of this test set
`app.image` directly instead of driving `_choose()`, and missed a real bug
where `_choose()` loaded the image and then immediately wiped it back to
None via a `_reset_myocyte()` call missing `keep_image=True` - "image did
not load" in real use, invisible to a test that bypassed the method that
had the bug. Exercise the actual method, not a shortcut around it.

messagebox is mocked to avoid real popups (save-confirmation dialogs block
on a click even with the root withdrawn). The correction log is redirected
to a scratch directory so this test doesn't write into the real per-machine
quality-data folder.
"""
from pathlib import Path
import csv as csv_mod
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "morphology"))
sys.path.insert(0, str(ROOT / "app"))

import myocyte_morphometry_tool as tool
import myocyte_morphometry as mm
import morphometry_corrections as corr

tool.messagebox.showinfo = lambda *a, **k: None
tool.messagebox.showerror = lambda *a, **k: None
tool.messagebox.askyesno = lambda *a, **k: True
_warning_calls = []
tool.messagebox.showwarning = lambda *a, **k: _warning_calls.append((a, k))

_CORR_SCRATCH = Path(tempfile.mkdtemp()) / "corrections"
_RealCorrectionLog = corr.CorrectionLog
corr.CorrectionLog = lambda root=None: _RealCorrectionLog(root=root or _CORR_SCRATCH)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def fake_event(x, y, button=1, inaxes="self"):
    ns = SimpleNamespace(xdata=x, ydata=y, button=button)
    ns.inaxes = app.center_ax if inaxes == "self" else inaxes
    return ns


print("myocyte_morphometry_tool - headless smoke test\n")

tmp_dir = Path(tempfile.mkdtemp())
try:
    # A synthetic striated image: bright horizontal stripes every 20px,
    # inside a boundary rectangle - real periodicity for real detection.
    img = np.full((300, 300), 20.0)
    for y0 in range(0, 300, 20):
        img[y0:y0 + 4, :] = 200.0

    app = tool.App()
    app.withdraw()
    app.update_idletasks()

    check("controls frame has nonzero width",
          app.controls.winfo_reqwidth() > 0, app.controls.winfo_reqwidth())
    check("center canvas has nonzero size after layout",
          app.center_canvas.get_tk_widget().winfo_reqwidth() > 0)

    # --- drive the REAL _choose() path -----------------------------------
    synthetic_path = tmp_dir / "synthetic.tif"
    tifffile.imwrite(synthetic_path, img.astype(np.uint8))
    tool.filedialog.askopenfilename = lambda **k: str(synthetic_path)
    app._choose()
    if app._display_job is not None:   # flush the debounced redraw _choose() scheduled
        app.after_cancel(app._display_job)
        app._redraw()
    check("_choose() actually loaded the image (not left None by a stray reset)",
          app.image is not None,
          None if app.image is None else app.image.shape)
    check("_choose() loaded the correct pixel data",
          app.image is not None and np.allclose(app.image, img, atol=1.0))

    # --- display brightness/contrast: view-only, never touches self.image ---
    check("loading an image auto-stretches the display range off the "
          "full 0-255 default",
          app.display_vmin.get() != 0.0 or app.display_vmax.get() != 255.0,
          (app.display_vmin.get(), app.display_vmax.get()))
    check("the displayed image on the axes still shows the RAW pixel data "
          "(brightness/contrast is a colormap-only effect)",
          np.allclose(app.center_ax.images[0].get_array(), img, atol=1.0))
    app.display_vmin.set(50.0); app.display_vmax.set(150.0)
    app._on_display_range_move()
    if app._display_job is not None:
        app.after_cancel(app._display_job)
        app._redraw()
    check("moving the display sliders changes the shown color range (clim)",
          app.center_ax.images[0].get_clim() == (50.0, 150.0),
          app.center_ax.images[0].get_clim())
    check("the underlying image data is still unchanged after adjusting "
          "display range (measurement functions read app.image directly)",
          np.allclose(app.image, img, atol=1.0))
    app._reset_display_range()
    check("Reset sets the display range to the image's actual min/max",
          abs(app.display_vmin.get() - float(img.min())) < 1e-6
          and abs(app.display_vmax.get() - float(img.max())) < 1e-6,
          (app.display_vmin.get(), app.display_vmax.get()))
    app._auto_display_range()
    check("Auto sets a percentile-based range within the image's min/max",
          float(img.min()) <= app.display_vmin.get() <= app.display_vmax.get() <= float(img.max()))

    app.v["worm_id"].set("SMOKE1")
    app.v["day"].set("5")

    # --- real bug: Save with no scale calibrated looked exactly like
    # clicking Save did nothing (status-line message only, panel unchanged,
    # counter unchanged) - "0 myocytes saved, no additional myocyte button
    # in sight" was a direct symptom of this, not a separate crash. -------
    check("scale status label starts out flagging 'not calibrated'",
          "not calibrated" in app.scale_status_label.cget("text").lower(),
          app.scale_status_label.cget("text"))
    app.start_boundary()
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))
    app.accept_line()
    app.accept_auto()
    app.accept_waves()   # fiber review now sits between detection and save
    actions_before_failed_save = [
        w.cget("text") for w in app._actions.winfo_children() if "text" in w.keys()]
    counter_before_failed_save = app.myo_counter
    check("no _warning_calls yet", len(_warning_calls) == 0)
    app.save_myocyte()   # app.scale is still None at this point
    check("saving with no scale calibrated shows an unmissable warning "
          "dialog (a status-line message alone was too easy to miss)",
          len(_warning_calls) == 1, _warning_calls)
    check("saving with no scale calibrated does not advance myo_counter",
          app.myo_counter == counter_before_failed_save, app.myo_counter)
    check("saving with no scale calibrated leaves the Save/Discard panel "
          "up (matches the real report: no 'Start boundary' button "
          "reappeared)",
          [w.cget("text") for w in app._actions.winfo_children() if "text" in w.keys()]
          == actions_before_failed_save)
    check("the boundary/ticks are preserved, so calibrating and clicking "
          "Save again just works",
          app.boundary is not None and app.final_ticks_px is not None)

    app._apply_scale({"um_per_px": 0.1})
    check("scale status label updates once calibrated",
          "0.1" in app.scale_status_label.cget("text")
          and "not calibrated" not in app.scale_status_label.cget("text").lower(),
          app.scale_status_label.cget("text"))
    # Don't actually complete this demo save - "retry succeeds using
    # preserved state" is already covered by the crash-safety test further
    # down, for a different failure mode. Completing a real save here would
    # shift every downstream myocyte_id/count check by one. start_boundary()
    # discards this in-progress (unsaved) myocyte cleanly and begins the
    # real first one below, at counter 0 as the rest of this test expects.

    # --- boundary drawing: a rectangle, closed with a right-click -------
    app.start_boundary()
    check("boundary click handler connected", app._boundary_cid is not None)
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))  # close
    check("boundary captured with 4 vertices",
          app.boundary is not None and len(app.boundary) == 4,
          None if app.boundary is None else len(app.boundary))
    check("boundary click handler disconnected after closing",
          app._boundary_cid is None)

    # --- sampling line auto-proposed from real striped content ----------
    check("a sampling line was proposed", app.line is not None, app.line)

    # --- accept line -> real sarcomere detection -------------------------
    app.accept_line()
    check("profile was sampled from the real striped image",
          app.profile is not None and len(app.profile) > mm.MIN_PROFILE_N,
          None if app.profile is None else len(app.profile))
    check("auto peak detection found real periodic bands (>=3 peaks on a "
          "clean 20px-period striped image)",
          app.auto_ticks_px is not None and len(app.auto_ticks_px) >= 3,
          None if app.auto_ticks_px is None else len(app.auto_ticks_px))

    # --- edit ticks: add one, drag one, delete one -----------------------
    def _marker_artist_count():
        # Count actual "s"-marker Line2D artists on the axes - the real bug
        # here was that _redraw() (used to enter edit mode, pre-loading the
        # auto ticks) drew its OWN untracked marker artist separate from
        # _live_artists, so a later incremental delete cleared only what it
        # knew about and left the original marker orphaned on screen
        # forever - added points worked, deleted ones visually never went
        # away. Checking len(app._live_artists) alone would NOT catch this
        # (one Line2D artist can hold many points and _live_artists ends up
        # length 1 either way) - this counts what's actually still drawn.
        return sum(1 for ln in app.center_ax.lines if ln.get_marker() == "s")

    app.start_edit_ticks()
    check("edit-tick handlers connected", len(app._edit_cids) == 3)
    check("entering edit mode (pre-loaded auto ticks, via the full redraw "
          "path) draws exactly one marker artist for them",
          _marker_artist_count() == 1, _marker_artist_count())
    n_before = len(app._edit_points_img)
    to_delete = app._edit_points_img[0]
    app._edit_press(fake_event(to_delete[0], to_delete[1], button=3))
    check("deleting one of the ORIGINAL (pre-loaded) points removes it from "
          "the data", len(app._edit_points_img) == n_before - 1)
    check("deleting one of the ORIGINAL points leaves exactly one marker "
          "artist on the canvas - not two (the bug: the original untracked "
          "marker never got removed, so a deleted point stayed visible)",
          _marker_artist_count() == 1, _marker_artist_count())
    # A distinct location from the delete/re-add above, so this block's own
    # add->drag->delete sequence is independent of it (reusing the same
    # point would mean "press near it" drags the EARLIER block's point
    # instead of adding + dragging a fresh one, throwing off the count this
    # block's own comments describe).
    app._edit_press(fake_event(170, 255, button=1))   # add a new point far from existing ones
    check("edit: clicking empty space adds a point (back to n_before: one "
          "delete above, one add here)",
          len(app._edit_points_img) == n_before,
          (len(app._edit_points_img), n_before))
    app._edit_press(fake_event(170, 255, button=1))    # press near it -> starts drag
    check("edit: pressing near an existing point starts a drag",
          app._edit_drag_index is not None)
    app._edit_motion(fake_event(170, 205, button=1))
    check("edit: dragging moves the point",
          app._edit_points_img[app._edit_drag_index] == (170.0, 205.0),
          app._edit_points_img[app._edit_drag_index])
    app._edit_release(fake_event(170, 205))
    check("edit: releasing stops the drag", app._edit_drag_index is None)
    n_before_delete = len(app._edit_points_img)
    app._edit_press(fake_event(170, 205, button=3))    # right-click deletes it
    check("edit: right-clicking near a point deletes it",
          len(app._edit_points_img) == n_before_delete - 1)
    check("net effect: one less than the original auto-tick count (two "
          "deletes, one add, across this whole edit sequence)",
          len(app._edit_points_img) == n_before - 1, len(app._edit_points_img))

    app.finish_editing()
    check("edit-tick handlers disconnected after finishing",
          len(app._edit_cids) == 0)
    check("sarc_mode is EDITED after finishing the edit path",
          app.sarc_mode == "EDITED", app.sarc_mode)
    check("final ticks reflect the edited set (one fewer than auto, per "
          "the edit sequence above: two deletes, one add)",
          len(app.final_ticks_px) == len(app.auto_ticks_px) - 1,
          (len(app.final_ticks_px), len(app.auto_ticks_px)))

    # --- save: CSV row + correction log entry ----------------------------
    saved_counter_before = app.myo_counter
    app.save_myocyte()
    check("myo_counter incremented after save", app.myo_counter == saved_counter_before + 1)
    check("csv_path was created", app.csv_path is not None and app.csv_path.exists(),
          app.csv_path)
    if app.csv_path is not None and app.csv_path.exists():
        with app.csv_path.open(encoding="utf-8") as fh:
            rows = list(csv_mod.DictReader(fh))
        check("exactly one CSV row was written", len(rows) == 1, len(rows))
        if rows:
            row = rows[0]
            check("CSV row has the expected sarc_mode", row["sarc_mode"] == "EDITED",
                  row["sarc_mode"])
            check("CSV row has a positive sarc_number", int(row["sarc_number"]) > 0,
                  row["sarc_number"])
            check("CSV row records the worm_id", row["worm_id"] == "SMOKE1")

    log = corr.CorrectionLog()
    corr_rows = [r for r in log.read_all() if r.get("worm_id") == "SMOKE1"]
    check("a correction log entry was written for the EDITED myocyte",
          len(corr_rows) >= 1, len(corr_rows))
    if corr_rows:
        check("correction log entry's myocyte_id matches the saved row",
              corr_rows[-1]["myocyte_id"] == saved_counter_before + 1,
              (corr_rows[-1]["myocyte_id"], saved_counter_before + 1))

    check("state resets after save (ready for next myocyte)",
          app.boundary is None and app.line is None)

    # --- second myocyte, MANUAL path ---------------------------------
    app.start_boundary()
    for (x, y) in [(60, 160), (240, 160), (240, 240), (60, 240)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 240, button=3))
    check("second boundary captured", app.boundary is not None and len(app.boundary) == 4)
    app.accept_line()
    check("second myocyte's profile sampled", app.profile is not None)

    app.start_manual_ticks()
    check("manual mode starts with an empty point set", len(app._edit_points_img) == 0)
    for x in (70, 90, 110, 130):
        app._edit_press(fake_event(x, 200, button=1))
    check("manual clicks added 4 points", len(app._edit_points_img) == 4)
    app.finish_editing()
    check("sarc_mode is MANUAL after the manual path", app.sarc_mode == "MANUAL",
          app.sarc_mode)

    manual_id_expected = app.pending_myocyte_id
    app.save_myocyte()
    manual_rows = [r for r in corr.CorrectionLog().read_all()
                   if r["worm_id"] == "SMOKE1" and r["human"]["correction_type"] == "MANUAL"]
    check("a MANUAL correction log entry was written",
          len(manual_rows) == 1, len(manual_rows))
    if manual_rows:
        check("MANUAL correction log entry's myocyte_id matches the saved row",
              manual_rows[0]["myocyte_id"] == manual_id_expected,
              (manual_rows[0]["myocyte_id"], manual_id_expected))

    # --- blind recount of the just-saved (MANUAL) myocyte -----------------
    check("last_myocyte cached for blind recount", app.last_myocyte is not None)
    original_myocyte_id = app.last_myocyte["myocyte_id"]
    app.start_blind_recount()
    check("blind recount reuses the SAME line as the original myocyte",
          app.line == app.last_myocyte["line"])
    check("blind recount starts with an empty point set (independent count, "
          "auto ticks not preloaded)", len(app._edit_points_img) == 0)
    for x in (65, 95, 125, 155, 185):
        app._edit_press(fake_event(x, 200, button=1))
    app.finish_editing()
    recount_id_expected = app.pending_myocyte_id
    app.save_myocyte()

    with app.csv_path.open(encoding="utf-8") as fh:
        all_rows = list(csv_mod.DictReader(fh))
    check("three CSV rows total after AUTO/EDITED, MANUAL, and the recount",
          len(all_rows) == 3, len(all_rows))
    recount_row = all_rows[-1]
    check("the recount row's sarc_mode is MANUAL_RECOUNT",
          recount_row["sarc_mode"] == "MANUAL_RECOUNT", recount_row["sarc_mode"])
    check("the recount row's linked_myocyte_id points at the original myocyte",
          recount_row["linked_myocyte_id"] == str(original_myocyte_id),
          (recount_row["linked_myocyte_id"], original_myocyte_id))

    recount_corr = [r for r in corr.CorrectionLog().read_all()
                    if r["worm_id"] == "SMOKE1"
                    and r["human"]["correction_type"] == "MANUAL_RECOUNT"]
    check("a MANUAL_RECOUNT correction log entry was written",
          len(recount_corr) == 1, len(recount_corr))
    if recount_corr:
        check("MANUAL_RECOUNT correction log entry's myocyte_id matches the "
              "recount row (not the original myocyte it recounts)",
              recount_corr[0]["myocyte_id"] == recount_id_expected,
              (recount_corr[0]["myocyte_id"], recount_id_expected))

    # --- persistent overlay of completed myocytes -------------------------
    check("all 3 saved myocytes (AUTO/EDITED, MANUAL, MANUAL_RECOUNT) are "
          "tracked for the persistent overlay",
          len(app.completed_myocytes) == 3, len(app.completed_myocytes))
    check("each tracked myocyte carries its boundary and a label",
          all("boundary" in m and "label" in m for m in app.completed_myocytes),
          app.completed_myocytes)

    saved_csv_path = app.csv_path
    saved_myo_counter = app.myo_counter

    # --- choosing a NEW image clears the (per-image) overlay list but does
    # NOT reset csv_path/myo_counter, matching the macro's own documented
    # behavior: a session can span multiple images into the same CSV. ------
    second_synthetic = tmp_dir / "synthetic2.tif"
    tifffile.imwrite(second_synthetic, img.astype(np.uint8))
    tool.filedialog.askopenfilename = lambda **k: str(second_synthetic)
    app._choose()
    if app._display_job is not None:
        app.after_cancel(app._display_job); app._redraw()
    check("choosing a new image clears the completed-myocyte overlay list",
          app.completed_myocytes == [], app.completed_myocytes)
    check("choosing a new image does NOT reset csv_path (session can span "
          "multiple images)", app.csv_path == saved_csv_path)
    check("choosing a new image does NOT reset myo_counter",
          app.myo_counter == saved_myo_counter, app.myo_counter)

    # --- save crash-safety: an exception mid-save must not lose state or -
    # silently strand the user with no way forward. -------------------------
    app.start_boundary()
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))
    app.accept_line()
    app.accept_auto()
    app.accept_waves()   # fiber review now sits between detection and save
    boundary_before = app.boundary.copy()
    ticks_before = app.final_ticks_px.copy()
    counter_before_failed_save = app.myo_counter

    _real_boundary_measurements = mm.boundary_measurements
    mm.boundary_measurements = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        app.save_myocyte()   # must not raise out of the test
    finally:
        mm.boundary_measurements = _real_boundary_measurements
    check("a save failure is reported in the status, not silent",
          "failed" in app.status.get().lower(), app.status.get())
    check("a save failure does NOT lose the in-progress boundary",
          np.array_equal(app.boundary, boundary_before))
    check("a save failure does NOT lose the in-progress ticks",
          np.array_equal(app.final_ticks_px, ticks_before))
    check("a save failure does NOT advance myo_counter (nothing was written)",
          app.myo_counter == counter_before_failed_save, app.myo_counter)
    check("a save failure leaves the Save/Discard panel up, not stuck with "
          "no next action", any(
              "Save myocyte" in str(w.cget("text")) if "text" in w.keys() else False
              for w in app._actions.winfo_children()))

    # now retry the SAME save with the bug removed - it should succeed using
    # the state that was preserved through the failure.
    app.save_myocyte()
    check("retrying Save after fixing the failure succeeds using the "
          "preserved state", app.myo_counter == counter_before_failed_save + 1,
          app.myo_counter)

    # --- session save/resume round-trip ------------------------------------
    session_path = app._session_path()
    check("a session state file exists after saving", session_path is not None
          and session_path.exists(), session_path)
    saved_state_myo_counter = app.myo_counter
    saved_state_overlays = len(app.completed_myocytes)
    saved_state_worm_id = app.v["worm_id"].get()

    app2 = tool.App()
    app2.withdraw(); app2.update_idletasks()
    tool.filedialog.askopenfilename = lambda **k: str(session_path)
    app2._resume_session()
    if app2._display_job is not None:
        app2.after_cancel(app2._display_job); app2._redraw()
    check("resuming restores worm_id", app2.v["worm_id"].get() == saved_state_worm_id,
          app2.v["worm_id"].get())
    check("resuming restores myo_counter",
          app2.myo_counter == saved_state_myo_counter, app2.myo_counter)
    check("resuming restores the completed-myocyte overlay list",
          len(app2.completed_myocytes) == saved_state_overlays,
          len(app2.completed_myocytes))
    check("resuming restores the SAME csv_path (new saves append, don't "
          "start a fresh file)", app2.csv_path == saved_csv_path,
          (app2.csv_path, saved_csv_path))
    check("resuming restores the scale", app2.scale == app.scale, app2.scale)
    check("resuming loads the image (not left None)", app2.image is not None)
    app2.destroy()

    # --- zoom-aware pick radius: shrinks in DATA units as the view zooms in
    app._reset_zoom()
    radius_zoomed_out = app._pick_radius()
    x0, x1 = app.center_ax.get_xlim()
    app.center_ax.set_xlim((x0 + x1) / 2 - 10, (x0 + x1) / 2 + 10)  # zoom way in
    radius_zoomed_in = app._pick_radius()
    check("pick radius (in data/image pixels) shrinks when zoomed in, since "
          "the on-screen tolerance should stay roughly constant regardless "
          "of zoom, not the data-space one",
          radius_zoomed_in < radius_zoomed_out,
          (radius_zoomed_in, radius_zoomed_out))

    # --- incremental live-artist drawing doesn't error and tracks artists --
    app._reset_zoom()
    app.start_boundary()
    app._boundary_click(fake_event(70, 70, button=1))
    check("an incremental boundary click adds a live artist (not a full "
          "clear+rebuild)", len(app._live_artists) == 1, len(app._live_artists))
    app._boundary_click(fake_event(70, 70, button=3))  # too few vertices, cancels cleanly

    # --- final-tick overlay is truly perpendicular to the sampling line,
    # not a "|" marker (always vertical in SCREEN space regardless of the
    # line's actual angle in DATA space - looked crooked on any oblique
    # line, making it hard to check tick placement against real bands). ---
    app.line = (50.0, 50.0, 150.0, 130.0)  # a deliberately oblique line
    segments = app._perpendicular_tick_segments([20.0, 60.0])
    check("_perpendicular_tick_segments returns one segment per tick",
          len(segments) == 2, len(segments))
    ax1, ay1, ax2, ay2 = app.line
    line_len = np.hypot(ax2 - ax1, ay2 - ay1)
    line_dir = np.array([(ax2 - ax1) / line_len, (ay2 - ay1) / line_len])
    for tx1, ty1, tx2, ty2 in segments:
        seg_vec = np.array([tx2 - tx1, ty2 - ty1])
        seg_len = np.hypot(*seg_vec)
        cos_angle = abs(np.dot(seg_vec / seg_len, line_dir))
        check("a tick segment is perpendicular to the oblique sampling "
              "line (dot product with the line's direction is ~0, not "
              "just visually vertical)", cos_angle < 1e-9, cos_angle)

    # --- real bug: zooming in while editing myocyte N's ticks (exactly the
    # workflow the zoom feature exists for) left _zoom_active=True with the
    # OLD zoomed-in view. _redraw() then kept forcing myocyte N+1's view
    # back to that stale region even though its boundary/line were drawn
    # somewhere completely different in the image - "ticks showed up but
    # couldn't edit them" was the real, off-screen ticks being unreachable,
    # not a broken click handler. ------------------------------------------
    big_img = np.full((600, 600), 20.0)
    for y0 in range(0, 600, 20):
        big_img[y0:y0 + 4, :] = 200.0
    app.image = big_img
    app._zoom_active = False
    app._redraw()

    app.start_boundary()
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))
    app.accept_line()
    app.start_edit_ticks()
    app._on_scroll(SimpleNamespace(xdata=150, ydata=90, button="up", inaxes=app.center_ax))
    app._on_scroll(SimpleNamespace(xdata=150, ydata=90, button="up", inaxes=app.center_ax))
    app._on_scroll(SimpleNamespace(xdata=150, ydata=90, button="up", inaxes=app.center_ax))
    check("zooming in while editing ticks sets _zoom_active",
          app._zoom_active is True)
    app.finish_editing()
    app.save_myocyte()
    check("_zoom_active resets to False after a myocyte is saved (ready "
          "for the next one to start from a full view)",
          app._zoom_active is False, app._zoom_active)

    app.start_boundary()
    xlim_at_start = app.center_ax.get_xlim()
    check("the view is back to (near) the full image, not still zoomed "
          "into the previous myocyte's region",
          xlim_at_start[1] - xlim_at_start[0] > 500,
          xlim_at_start)
    far_boundary = [(400, 400), (580, 400), (580, 480), (400, 480)]
    for (x, y) in far_boundary:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(400, 480, button=3))
    app.accept_line()
    ax1, ay1, ax2, ay2 = app.line
    xlim2 = app.center_ax.get_xlim()
    ylim2 = sorted(app.center_ax.get_ylim())
    check("the second myocyte's sampling line is actually visible within "
          "the current view (not off-screen in a stale zoomed region)",
          xlim2[0] <= ax1 <= xlim2[1] and xlim2[0] <= ax2 <= xlim2[1]
          and ylim2[0] <= ay1 <= ylim2[1] and ylim2[0] <= ay2 <= ylim2[1],
          (app.line, xlim2, ylim2))
    app._reset_myocyte(keep_image=True)  # discard the in-progress demo myocyte above

    # --- myocyte body-wall identity (Myo01-24 numbering) -------------------
    check("myo_number starts at 'unknown'", app.v["myo_number"].get() == "unknown")
    app.v["myo_number"].set("5")   # falls in the anterior range (1-10)
    app.start_boundary()
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))
    app.accept_line()
    app.accept_auto()
    app.accept_waves()   # fiber review now sits between detection and save
    counter_before_id_test = app.myo_counter
    app.save_myocyte()
    with app.csv_path.open(encoding="utf-8") as fh:
        rows = list(csv_mod.DictReader(fh))
    last_row = rows[-1]
    check("saving with myo_number=5 records myocyte_number in the CSV row",
          last_row["myocyte_number"] == "5", last_row["myocyte_number"])
    check("myo_number=5 overrides region to 'anterior' (the macro's own "
          "1-10 body-wall mapping), regardless of the session Region field",
          last_row["region"] == "anterior", last_row["region"])
    check("roi_name uses the Myo## identity label",
          "Myo05" in last_row["roi_name"], last_row["roi_name"])
    check("last_myo_number is tracked for the next auto-suggestion",
          app.last_myo_number == 5, app.last_myo_number)
    check("the next myocyte's number field auto-suggests 6 (last+1), "
          "matching the macro's own pickMyoNumber() suggestion",
          app.v["myo_number"].get() == "6", app.v["myo_number"].get())

    # myo_number "unknown"/"other" must NOT touch the auto-suggest chain.
    # Set it AFTER start_boundary(), matching real usage: start_boundary()
    # applies the suggested next number, and the person overrides it in the
    # dropdown for THIS cell if it can't be identified - setting it before
    # start_boundary() would just get overwritten by that same suggestion.
    app.start_boundary()
    app.v["myo_number"].set("unknown")
    for (x, y) in [(260, 60), (340, 60), (340, 140), (260, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(260, 140, button=3))
    app.accept_line()
    app.accept_auto()
    app.accept_waves()   # fiber review now sits between detection and save
    app.save_myocyte()
    check("saving with myo_number='unknown' leaves last_myo_number "
          "unchanged (still 5, not reset/advanced)",
          app.last_myo_number == 5, app.last_myo_number)
    check("the suggestion for the next myocyte still reflects the last "
          "REAL number given (6), skipping the 'unknown' row",
          app.v["myo_number"].get() == "6", app.v["myo_number"].get())

    # --- schematic viewer: opens without crashing (system call mocked) ----
    opened = []
    os_startfile_orig = getattr(os, "startfile", None)
    os.startfile = lambda p: opened.append(p)
    try:
        app._show_schematic()
    finally:
        if os_startfile_orig is not None:
            os.startfile = os_startfile_orig
        else:
            del os.startfile
    check("_show_schematic opens the bundled schematic file without error",
          len(opened) == 1 and Path(opened[0]).name.startswith("myocyte schematic"),
          opened)

    # --- a detection that finds no usable bands must SAY so, and must not
    # be saveable as a real AUTO measurement without an explicit
    # confirmation. Reported from real use as "the second myocyte does not
    # even show tick marks" - there were none, and nothing said so; it then
    # saved silently as sarc_mode=AUTO with sarc_number=0. ------------------
    flat_img = np.full((300, 300), 50.0)   # no banding at all -> no peaks
    app.image = flat_img
    app._zoom_active = False
    app._reset_myocyte(keep_image=True)
    _warning_calls.clear()
    app.start_boundary()
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))
    app.accept_line()
    check("a featureless region detects fewer than 2 bands",
          len(app.auto_ticks_px) < 2, len(app.auto_ticks_px))
    check("a zero/one-band detection raises an explicit warning dialog "
          "instead of silently showing an empty 'review the red ticks' panel",
          len(_warning_calls) == 1, _warning_calls)
    check("the status line explains it as a detection FAILURE, not a "
          "measurement of zero sarcomeres",
          "not a measurement of zero" in app.status.get().lower()
          or "detection failure" in app.status.get().lower(),
          app.status.get())

    app.accept_auto()
    app.accept_waves()   # fiber review now sits between detection and save
    counter_before_zero_save = app.myo_counter
    _askyesno_answers = []
    _real_askyesno = tool.messagebox.askyesno
    tool.messagebox.askyesno = lambda *a, **k: (_askyesno_answers.append(a) or False)
    try:
        app.save_myocyte()   # declining the confirmation must abort the save
    finally:
        tool.messagebox.askyesno = _real_askyesno
    check("saving a <2-band cell asks for explicit confirmation first",
          len(_askyesno_answers) == 1, _askyesno_answers)
    check("declining that confirmation aborts the save (nothing written, "
          "counter unchanged)",
          app.myo_counter == counter_before_zero_save, app.myo_counter)
    check("declining points the user at 'Skip sarcomeres' as the honest "
          "way to record geometry without a sarcomere claim",
          "skip sarcomeres" in app.status.get().lower(), app.status.get())

    # --- fiber review BEFORE save: the whole point is that traces can be
    # seen and corrected while the myocyte is still in progress. Wave
    # detection used to run inside save_myocyte(), so fibers only ever
    # appeared after the row was already committed ("both myocytes showed
    # the fibers AFTER i saved") - no preview, no relabel, no way to add a
    # fiber the tracer missed. ---------------------------------------------
    app.image = img
    app._zoom_active = False
    app._reset_myocyte(keep_image=True)
    app.start_boundary()
    for (x, y) in [(60, 60), (240, 60), (240, 140), (60, 140)]:
        app._boundary_click(fake_event(x, y, button=1))
    app._boundary_click(fake_event(60, 140, button=3))
    app.accept_line()
    check("no fibers exist before the detection step", app.waves is None)
    app.accept_auto()
    check("fibers are computed at REVIEW time, before any save",
          app.waves is not None and app.waves["n_fibers"] > 0,
          None if app.waves is None else app.waves["n_fibers"])
    check("the review panel offers relabel / hand-draw / retry, not just Save",
          any("Relabel" in w.cget("text")
              for w in app._actions.winfo_children() if "text" in w.keys()))

    n_fibers_auto = app.waves["n_fibers"]
    first = app.waves["fibers"][0]
    cls_before = first["class"]
    app.start_fiber_relabel()
    check("relabel mode connects a click handler", app._fiber_cid is not None)
    app._fiber_click(fake_event(float(first["x"][0]), float(first["y"][0]), button=1))
    check("left-clicking a fiber cycles its label",
          app.waves["fibers"][0]["class"] == (cls_before + 1) % 3,
          (cls_before, app.waves["fibers"][0]["class"]))
    check("a relabelled fiber is marked as corrected (so the row records "
          "human judgement, not the automatic first pass)",
          app.waves["fibers"][0].get("corrected") is True)

    target = app.waves["fibers"][-1]
    app._fiber_click(fake_event(float(target["x"][0]), float(target["y"][0]), button=3))
    check("right-clicking a fiber deletes it (for a trace that jumped "
          "between two different real fibers)",
          app.waves["n_fibers"] == n_fibers_auto - 1, app.waves["n_fibers"])
    app.finish_fiber_relabel()
    check("finishing relabel disconnects the handler", app._fiber_cid is None)

    n_before_manual = app.waves["n_fibers"]
    app.manual_fiber_class.set("wavy")
    app.start_manual_fiber()
    for x in (70, 110, 150, 190, 230):
        app._manual_fiber_click(fake_event(x, 100, button=1))
    app._manual_fiber_click(fake_event(230, 100, button=3))   # finish
    check("a hand-drawn fiber is added (the tracer only ever seeds from "
          "detected bands, so a missed fiber can only be added this way)",
          app.waves["n_fibers"] == n_before_manual + 1, app.waves["n_fibers"])
    manual = [f for f in app.waves["fibers"] if f.get("source") == "manual"]
    check("the hand-drawn fiber is tagged as manual, not passed off as an "
          "automatic trace", len(manual) == 1, len(manual))
    check("the hand-drawn fiber carries the label chosen for it",
          manual and manual[0]["class"] == 1, manual[0]["class"] if manual else None)
    check("summary counts include hand-drawn and relabelled fibers",
          app.waves["n_affected"] == sum(
              1 for f in app.waves["fibers"] if f["class"] == 1),
          (app.waves["n_affected"], app.waves["n_fibers"]))

    reviewed = {"n_fibers": app.waves["n_fibers"],
                "n_affected": app.waves["n_affected"]}
    app.accept_waves()
    app.save_myocyte()
    with app.csv_path.open(encoding="utf-8") as fh:
        saved_rows = list(csv_mod.DictReader(fh))
    check("the SAVED row uses the reviewed/corrected fibers, not a fresh "
          "automatic re-run at save time",
          int(saved_rows[-1]["wave_n_fibers"]) == reviewed["n_fibers"]
          and int(saved_rows[-1]["wave_n_affected"]) == reviewed["n_affected"],
          (saved_rows[-1]["wave_n_fibers"], saved_rows[-1]["wave_n_affected"],
           reviewed))
    check("fiber state resets for the next myocyte", app.waves is None)

    app.destroy()
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.rmtree(_CORR_SCRATCH.parent, ignore_errors=True)

print()
failed = [n for n, ok in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for n in failed:
        print(f"   FAILED: {n}")
    raise SystemExit(1)
print("MYOCYTE_TOOL_SMOKE_PASS")
