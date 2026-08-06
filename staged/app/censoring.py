"""Animals that leave the field of view are censored, and they are the fast ones.

The last gap from the literature sweep, and the real data proved it before this
module existed. On a re-tracked magnetotaxis recording, tracks lasting 100+
samples had a mean speed of 0.063 mm/s against 0.107-0.119 mm/s for shorter
ones. The animals that stay trackable longest are the slowest.

WHY THAT IS WORSE THAN IT SOUNDS. Bainbridge et al. 2019 tracked animals from
5 mm out until they left a 36 x 27 mm field of view, and reported the preferred
heading rotating ~180 degrees over 90 minutes. Those two facts interact: the
late time windows - where the reversal lives - are built from whichever animals
were still in frame, and that is disproportionately the slow ones. A change in
population heading over time and a change in WHICH ANIMALS ARE LEFT produce the
same plot.

THIS IS NOT A NUISANCE, IT IS THE SAME SURVIVAL PROBLEM AS THE DONUT ASSAY,
turned inside out. There the measure is time-to-leave and the non-leavers are
censored; here the measure is heading-over-time and the leavers are censored.
Same statistics, opposite sign.

NOTHING HERE SILENTLY CORRECTS ANYTHING. Inverse-probability weighting could
reweight the survivors, but it would assume the departed animals resemble the
slow ones that stayed, which is exactly what is in doubt. So this measures the
bias, reports its size and direction, and says which windows are affected. A
correction the analyst chooses is defensible; one the software applies quietly
is not.
"""
from __future__ import annotations

import numpy as np


class CensoringError(Exception):
    """Refusals that name the consequence."""


def exit_reason(rows, *, bounds_mm, edge_margin_mm=1.0, recording_end_s=None,
                end_margin_s=None):
    """Why did this track stop: left the frame, ended with the recording, or lost?

    Distinguishing them matters because only one is informative about the
    animal. A track that ends at the frame edge tells you the animal was
    moving outward; a track that just stops in mid-frame tells you the tracker
    failed, which is a fact about the software.
    """
    rows = sorted(rows, key=lambda r: float(r["time_s"]))
    if len(rows) < 2:
        raise CensoringError(
            "A track needs at least two points before its ending means "
            "anything - a single detection has no direction to have left in.")
    x0, x1, y0, y1 = [float(v) for v in bounds_mm]
    last = rows[-1]
    lx, ly = float(last["x_mm"]), float(last["y_mm"])
    m = float(edge_margin_mm)
    at_edge = (lx - x0 < m or x1 - lx < m or ly - y0 < m or y1 - ly < m)
    t_end = float(last["time_s"])
    ends_with_recording = (
        recording_end_s is not None and end_margin_s is not None
        and (float(recording_end_s) - t_end) <= float(end_margin_s))

    if at_edge:
        reason, informative = "left_field_of_view", True
    elif ends_with_recording:
        reason, informative = "recording_ended", True
    else:
        reason, informative = "lost_by_tracker", False
    return {
        "reason": reason,
        "informative": informative,
        "last_time_s": t_end,
        "last_xy_mm": [lx, ly],
        "duration_s": t_end - float(rows[0]["time_s"]),
        "why": {
            "left_field_of_view": (
                "Ended at the frame edge: the animal left. This is censoring - "
                "the animal continued, unobserved."),
            "recording_ended": (
                "Ended with the recording, so nothing about the animal caused "
                "it. Censored by design rather than by behaviour."),
            "lost_by_tracker": (
                "Stopped in mid-frame with the recording still running. This "
                "is a tracking failure, not an animal leaving, and treating it "
                "as departure would attribute a software limit to biology."),
        }[reason],
    }


def retention(tracks, *, bounds_mm, window_s=600.0, edge_margin_mm=1.0,
              recording_end_s=None, end_margin_s=None):
    """How much of the cohort is still in frame in each window, and how fast.

    The speed comparison is the whole point: if the animals still present are
    slower than those that have gone, then every later window describes a
    different, slower population than the first one did.
    """
    by_worm = {}
    for r in tracks:
        by_worm.setdefault(str(r.get("worm_id")), []).append(r)

    profiles = {}
    for worm, rows in by_worm.items():
        rows = sorted(rows, key=lambda r: float(r["time_s"]))
        if len(rows) < 2:
            continue
        try:
            ex = exit_reason(rows, bounds_mm=bounds_mm,
                             edge_margin_mm=edge_margin_mm,
                             recording_end_s=recording_end_s,
                             end_margin_s=end_margin_s)
        except CensoringError:
            continue
        xs = np.array([float(r["x_mm"]) for r in rows])
        ys = np.array([float(r["y_mm"]) for r in rows])
        ts = np.array([float(r["time_s"]) for r in rows])
        step = np.hypot(np.diff(xs), np.diff(ys))
        dt = np.diff(ts)
        ok = dt > 0
        speed = float(np.mean(step[ok] / dt[ok])) if ok.any() else None
        profiles[worm] = {"start_s": ts[0], "end_s": ts[-1],
                          "speed_mm_s": speed, **ex}

    if not profiles:
        raise CensoringError(
            "No track was long enough to have an ending. Retention cannot be "
            "described from single detections.")

    t0 = min(p["start_s"] for p in profiles.values())
    t_last = max(p["end_s"] for p in profiles.values())
    # Ceiling, not floor-plus-one. Data ending exactly on a window boundary -
    # a recording of a round number of minutes, which is the common case -
    # otherwise creates a trailing window that starts AT the last timestamp
    # and contains nothing, reporting 0% retention at the end of every assay.
    span = max(t_last - t0, 1e-9)
    n_win = max(1, int(np.ceil(span / float(window_s))))

    out_windows = {}
    for i in range(n_win):
        lo = t0 + i * float(window_s)
        hi = lo + float(window_s)
        last_window = (i == n_win - 1)
        # A track ending exactly at the final boundary was present for that
        # window; anywhere else, ending at `lo` means it had already gone.
        present = [p for p in profiles.values()
                   if p["start_s"] < hi
                   and (p["end_s"] > lo or (last_window and p["end_s"] >= lo))]
        gone = [p for p in profiles.values() if p["end_s"] <= lo]
        sp_present = [p["speed_mm_s"] for p in present
                      if p["speed_mm_s"] is not None]
        sp_gone = [p["speed_mm_s"] for p in gone if p["speed_mm_s"] is not None]
        entry = {
            "window": i, "t_start_s": lo,
            "n_present": len(present),
            "n_departed_by_now": len(gone),
            "fraction_remaining": round(len(present) / len(profiles), 3),
            "mean_speed_present": (float(np.mean(sp_present))
                                   if sp_present else None),
            "mean_speed_departed": (float(np.mean(sp_gone))
                                    if sp_gone else None),
        }
        if entry["mean_speed_present"] and entry["mean_speed_departed"]:
            entry["speed_ratio_present_over_departed"] = round(
                entry["mean_speed_present"] / entry["mean_speed_departed"], 3)
        out_windows[i] = entry

    reasons = {}
    for p in profiles.values():
        reasons[p["reason"]] = reasons.get(p["reason"], 0) + 1

    return {"n_tracks": len(profiles), "windows": out_windows,
            "exit_reasons": reasons, "window_s": float(window_s)}


def bias_report(retention_result, *, ratio_tolerance=0.15):
    """Is the surviving population different from the one that started?

    Returns findings, not a correction. The size and DIRECTION of the bias are
    what an analyst needs in order to decide whether a late-window result is
    about time or about who is left.
    """
    wins = retention_result["windows"]
    out = {"warnings": [], "n_windows": len(wins)}

    ratios = {i: w.get("speed_ratio_present_over_departed")
              for i, w in wins.items()
              if w.get("speed_ratio_present_over_departed")}
    if ratios:
        worst_i = min(ratios, key=lambda i: ratios[i])
        worst = ratios[worst_i]
        out["worst_speed_ratio"] = worst
        out["worst_window"] = worst_i
        if worst < 1 - ratio_tolerance:
            out["warnings"].append(
                f"By window {worst_i} the animals still in frame are moving at "
                f"{worst:.2f}x the speed of those that have gone - the "
                f"survivors are {(1 - worst) * 100:.0f}% slower. Later windows "
                f"therefore describe a different, slower population than the "
                f"first window did. A change over time and a change in WHICH "
                f"ANIMALS REMAIN produce the same plot, and nothing in the "
                f"headings distinguishes them.")
        elif worst > 1 + ratio_tolerance:
            out["warnings"].append(
                f"The animals still in frame are FASTER than those that have "
                f"gone ({worst:.2f}x), which is the opposite of leaving-the-"
                f"frame censoring. Check whether tracks are ending for another "
                f"reason - a tracker that loses fast animals would look like "
                f"this.")

    last = wins[max(wins)] if wins else None
    if last and last["fraction_remaining"] < 0.5:
        out["warnings"].append(
            f"Only {last['fraction_remaining']:.0%} of tracks survive to the "
            f"final window. A result there rests on a minority of the cohort, "
            f"selected by their own behaviour rather than at random.")

    # RETENTION CANNOT RISE for a closed cohort. Nobody comes back, so a
    # fraction that goes up means new track IDs are appearing - fragmentation
    # of animals already present, or animals entering a frame they should have
    # started in. Seen on real data at 0.14 -> 0.06 -> 0.21 -> 0.40 -> 0.23,
    # where 77% of endings turned out to be tracker failures.
    fracs = [wins[i]["fraction_remaining"] for i in sorted(wins)]
    rises = [(i, fracs[i - 1], fracs[i]) for i in range(1, len(fracs))
             if fracs[i] > fracs[i - 1] + 0.02]
    if rises:
        out["retention_rises"] = rises
        out["warnings"].append(
            f"Retention INCREASES between windows {[r[0] for r in rises]}. A "
            f"closed cohort cannot grow - nobody returns - so new track IDs "
            f"are appearing mid-assay. Either one animal is being counted as "
            f"several, or animals are entering a frame they should have "
            f"started in. Until that is resolved, 'fraction remaining' is not "
            f"a retention curve and the speed comparison above is drawn from "
            f"fragments rather than animals.")

    reasons = retention_result.get("exit_reasons", {})
    lost = reasons.get("lost_by_tracker", 0)
    total = sum(reasons.values()) or 1
    if lost / total > 0.3:
        out["warnings"].append(
            f"{lost} of {total} tracks ({lost / total:.0%}) end in mid-frame "
            f"with the recording still running - a tracking failure rather "
            f"than an animal leaving. Censoring statistics assume departures "
            f"are informative about the animal; these are not, and treating "
            f"them as departures attributes a software limit to biology.")
    out["no_correction_applied"] = (
        "The bias is measured, not corrected. Reweighting the survivors would "
        "assume the departed resemble the slow animals that stayed, which is "
        "precisely what is in doubt. A correction the analyst chooses is "
        "defensible; one applied quietly is not.")
    return out
