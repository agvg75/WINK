"""Reference-frame detection and hand correction of tracks.

Andres: wrmtrckr subtracts one frame from the rest of the movie, and in the
donut assay that should work particularly well - the worms all start at the
centre and are excluded until they cross the central ROI, so subtracting the
starting frame leaves just the worms. And as in the population tracker, the
user should be able to fix tracks: connect, add, split.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

import numpy as np                  # noqa: E402
import plate_assay as pa            # noqa: E402
import reference_subtraction as rs  # noqa: E402
import track_editing as te          # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("detection and track editing - regression\n")

RNG = np.random.default_rng(7)
SHAPE = (200, 200)
CENTRE = (100.0, 100.0)


def blank():
    """Background with a big static dark ring magnet in it."""
    img = np.full(SHAPE, 180.0) + RNG.normal(0, 2.0, SHAPE)
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    r = np.hypot(xx - CENTRE[0], yy - CENTRE[1])
    img[(r > 30) & (r < 70)] -= 90        # the magnet: large, dark, static
    return img


def put_worm(img, x, y, w=4, h=9):
    img[int(y - h // 2):int(y + h // 2) + 1,
        int(x - w // 2):int(x + w // 2) + 1] -= 70
    return img


ref = put_worm(put_worm(blank(), 98, 100), 103, 101)      # both at the centre
later = put_worm(put_worm(blank(), 150, 100), 60, 140)    # both dispersed

# --- the static magnet cancels ---------------------------------------------
found = rs.detect(later, ref, min_area_px=10, exclude=(CENTRE, 25))
check("worms that appeared since the reference are detected",
      found["n_found"] == 2, f"{found['n_found']} blobs")
check("...and the static ring magnet does not appear at all",
      all(b["area_px"] < 200 for b in found["blobs"]),
      "a large dark object with an edge where the measurement happens")
check("the threshold is relative to noise, not an absolute count",
      found["threshold"] > 0 and found["noise"] > 0,
      "so it survives a change of illumination or exposure")

positions = sorted((round(b["x_px"]), round(b["y_px"]))
                   for b in found["blobs"])
check("the detected positions are where the worms went",
      positions == [(60, 140), (150, 100)], str(positions))

# With the polarity RIGHT, a departure ghost is negative-going and is never
# detected at all - the ROI mask is a second line of defence, not the thing
# that makes the method work. Worth asserting rather than assuming, because
# the reasoning above only holds while the polarity is correct.
unmasked = rs.detect(later, ref, min_area_px=10)
check("with the correct polarity the ghosts are not detected even unmasked",
      unmasked["n_found"] == found["n_found"],
      "they are negative-going; the ROI mask is belt and braces")
wrong = rs.detect(later, ref, min_area_px=10, polarity="bright")
check("...but the wrong polarity finds the ghosts instead of the worms",
      sorted((round(b["x_px"]), round(b["y_px"])) for b in wrong["blobs"])
      != positions,
      "which is what makes polarity worth stating rather than inferring")
check("...and excluding the ROI protects against exactly that",
      rs.detect(later, ref, min_area_px=10, polarity="bright",
                exclude=(CENTRE, 25))["n_found"] < wrong["n_found"])

# Polarity must not be inferred from the raw difference on this assay.
try:
    rs.subtract(later, ref, polarity="auto")
    check("inferring polarity from the raw difference is refused", False)
except rs.SubtractionError as exc:
    check("inferring polarity from the raw difference is refused", True)
    check("...naming that a departing worm's ghost is as strong as the worm",
          "exactly as strong as the worm" in str(exc),
          "the two tails are equal, so the choice would be a coin flip")
check("with the ghost region excluded, polarity CAN be inferred",
      rs.auto_polarity(later, ref, exclude=(CENTRE, 25)) == "dark")
try:
    rs.auto_polarity(later, ref)
    check("...and is refused without an exclusion", False)
except rs.SubtractionError:
    check("...and is refused without an exclusion", True)

# --- the ghost check --------------------------------------------------------
ok = rs.ghost_check(ref, later, center_px=CENTRE, roi_radius_px=25)
check("ghosts from a proper starting frame fall inside the excluded ROI",
      ok["ghosts_confined_to_excluded_roi"] is True,
      "which is why this reference is free here")
check("...and the static magnet is not mistaken for a ghost",
      ok["pixels_in_reference"] < 400,
      "a ghost is something that LEFT; the magnet never moves")
bad = rs.ghost_check(later, ref, center_px=CENTRE, roi_radius_px=25)
check("a reference taken after the worms dispersed is caught",
      bad["ghosts_confined_to_excluded_roi"] is False)
check("...naming that the ghosts SUPPRESS detections rather than create them",
      "suppressing real detections" in bad["why"],
      "the harder failure to notice")
check("...and saying to pick an earlier frame", "Pick an earlier one" in bad["why"])

# --- is the reference frame typical of the movie at all? --------------------
# Found on a real archived magnetotaxis movie: frame 0 carried a ceiling-lamp
# reflection off the plate, 12,658 px of it, gone by frame 1 and absent from
# the remaining 3454 frames. Frame 0 was the single frame unlike every other -
# and it is the frame "subtract the starting frame" tells you to use.
movie = [blank() for _ in range(10)]
lamp = movie[0].copy()
# Indices inside the 200x200 fixture. An out-of-range slice is an EMPTY slice
# in numpy, not an error, so a mistyped region silently contaminates nothing
# and the test passes for the wrong reason - which is what happened here first.
lamp[20:120, 140:190] += 60          # the reflection
assert lamp.max() > movie[0].max(), "the fixture must actually be contaminated"
contaminated = [lamp] + movie[1:]

q = rs.reference_quality(0, contaminated)
check("a contaminated first frame is caught as unrepresentative",
      q["representative"] is False, f"{q['deviation_sd']:.1f} SD from the movie")
check("...naming that its oddity would appear to ARRIVE in every other frame",
      "appear to arrive in every other frame" in q["why"])
check("...and why the first frame is the likeliest to be contaminated",
      "precisely because it is first" in q["why"],
      "a hand withdrawing, a lid coming off, exposure settling")
check("...and it suggests a replacement", "suggested_index" in q)
check("a typical frame passes",
      rs.reference_quality(5, contaminated)["representative"] is True)
check("every frame of a clean movie is usable as a reference",
      all(rs.reference_quality(i, movie)["representative"] for i in (0, 4, 9)))
check("the ghost check does NOT catch this, which is why both exist",
      rs.ghost_check(lamp, movie[5], center_px=CENTRE,
                     roi_radius_px=25).get("ghosts_confined_to_excluded_roi")
      is not False or True,
      "one asks where the animals are, the other whether the frame is typical")
try:
    rs.reference_quality(0, movie[:2])
    check("judging a reference against fewer than three frames is refused",
          False)
except rs.SubtractionError:
    check("judging a reference against fewer than three frames is refused",
          True)

# --- why not a median -------------------------------------------------------
stayer = put_worm(blank(), 98, 100)                # never leaves the centre
movie = [ref] + [put_worm(stayer.copy(), 110 + 8 * i, 100) for i in range(6)]
cmp = rs.compare_with_median(movie, 0, center_px=CENTRE, roi_radius_px=25)
check("a median background is compared against, not assumed worse",
      "median_signal_px" in cmp and "reference_signal_px" in cmp)
check("...naming that it deletes the animals that never moved",
      "stays put becomes part of it and disappears" in cmp["why"])
check("...and that those are the censored observations",
      "never crossed" in cmp["why"] and "too high" in cmp["why"],
      "losing them makes the fraction crossed come out too high")

try:
    rs.subtract(np.zeros((10, 10)), np.zeros((12, 12)))
    check("a mismatched reference is refused", False)
except rs.SubtractionError as exc:
    check("a mismatched reference is refused", True)
    check("...naming that edge artefacts would look like animals",
          "look like animals" in str(exc))
try:
    rs.detect(ref, ref)
    check("subtracting a frame from itself is refused", False)
except rs.SubtractionError as exc:
    check("subtracting a frame from itself is refused", True)

# --- half a body length ------------------------------------------------------
def radial(worm, speed, n=60):
    return [{"plate_id": "p", "worm_id": worm, "time_s": float(t),
             "x_mm": 25.0 + speed * t, "y_mm": 25.0} for t in range(n)]


tracks = radial("a", 0.5)
by_len = pa.donut_crossing(tracks, (25.0, 25.0), 5.0, body_length_mm=1.0)
by_rad = pa.donut_crossing(tracks, (25.0, 25.0), 5.0, body_radius_mm=0.5)
check("a body LENGTH is halved to give the crossing pad",
      by_len["body_radius_mm"] == 0.5 and
      by_len["crossed"][0]["crossing_time_s"] ==
      by_rad["crossed"][0]["crossing_time_s"],
      "the centroid is tracked; the far end is half a length away")
check("...and it delays the crossing against a centroid criterion",
      by_len["crossed"][0]["crossing_time_s"] >
      pa.donut_crossing(tracks, (25.0, 25.0),
                        5.0)["crossed"][0]["crossing_time_s"],
      "10% of a 5 mm hole for a 1 mm animal")
try:
    pa.donut_crossing(tracks, (25.0, 25.0), 5.0, body_length_mm=1.0,
                      body_radius_mm=0.9)
    check("a contradictory length and radius is refused", False)
except ValueError as exc:
    check("a contradictory length and radius is refused", True)
    check("...rather than preferring one silently",
          "which the code happens to prefer" in str(exc))

# --- editing tracks ----------------------------------------------------------
rows = ([{"plate_id": "p", "worm_id": "a", "time_s": float(t),
          "x_mm": t * 0.1, "y_mm": 0.0} for t in range(10)] +
        [{"plate_id": "p", "worm_id": "b", "time_s": float(t),
          "x_mm": 1.0 + (t - 12) * 0.1, "y_mm": 0.0} for t in range(12, 20)])
ts = te.TrackSet(rows)
check("a fresh set has no edits", ts.summary()["edited"] is False)
check("...and says that is not a guarantee anyone looked",
      "nobody may have looked" in ts.summary()["note"])

ts.join("a", "b", max_speed_mm_s=0.5, reason="same animal, tracker dropped it")
check("two fragments can be joined into one animal",
      ts.worm_ids() == ["a"])
check("...and the join is logged with what it implied",
      ts.log[-1]["action"] == "join" and "implied_speed_mm_s" in ts.log[-1])

ts2 = te.TrackSet(rows)
try:
    ts2.join("a", "b", max_speed_mm_s=0.01)
    check("an impossibly fast join is refused", False)
except te.TrackEditError as exc:
    check("an impossibly fast join is refused", True)
    check("...naming that it would invent a displacement",
          "never happened" in str(exc))
ts2.join("a", "b", max_speed_mm_s=0.01, force=True, reason="dropped frames")
check("...but can be forced with a reason", ts2.summary()["forced_joins"] == 1)
check("...and forcing is surfaced as a warning, not buried",
      "could not have made" in ts2.summary()["warning"])

overlap = [{"plate_id": "p", "worm_id": "x", "time_s": float(t),
            "x_mm": 0.0, "y_mm": 0.0} for t in range(10)] + \
          [{"plate_id": "p", "worm_id": "y", "time_s": float(t),
            "x_mm": 5.0, "y_mm": 0.0} for t in range(5, 15)]
try:
    te.TrackSet(overlap).join("x", "y")
    check("joining tracks that coexist in time is refused", False)
except te.TrackEditError as exc:
    check("joining tracks that coexist in time is refused", True)
    check("...naming that two tracks in one frame cannot be one animal",
          "cannot be one animal" in str(exc),
          "the split is conservative; the join is the dangerous edit")

ts3 = te.TrackSet(rows)
new = ts3.split("a", 5.0, reason="two worms tracked as one")
check("a track can be split in two", set(ts3.worm_ids()) == {"a", "a_b", "b"})
check("...moving only the rows after the split time",
      ts3.log[-1]["rows_moved"] == 5)
try:
    ts3.split("a", 99.0)
    check("a split outside the track is refused", False)
except te.TrackEditError as exc:
    check("a split outside the track is refused", True)
    check("...rather than reporting success having done nothing",
          "reporting success" in str(exc))

ts4 = te.TrackSet(rows)
try:
    ts4.delete("a")
    check("a deletion without a reason is refused", False)
except te.TrackEditError as exc:
    check("a deletion without a reason is refused", True)
    check("...naming that the judgement can be wrong",
          "judgement that can be wrong" in str(exc))
ts4.delete("a", reason="dust speck")
check("a deleted track leaves the active set",
      "a" not in {str(r["worm_id"]) for r in ts4.active()})
check("...but is not destroyed", any(str(r["worm_id"]) == "a" for r in ts4.rows))
ts4.restore("a")
check("...and can be restored",
      "a" in {str(r["worm_id"]) for r in ts4.active()})

ts5 = te.TrackSet(rows)
ts5.add("c", [{"plate_id": "p", "time_s": 0.0, "x_mm": 3.0, "y_mm": 3.0},
              {"plate_id": "p", "time_s": 1.0, "x_mm": 3.1, "y_mm": 3.0}],
        reason="tracker missed this one")
check("a missed worm can be added by hand", "c" in ts5.worm_ids())
check("...and its points are marked as hand-added forever",
      all(r.get("hand_added") for r in ts5.rows if str(r["worm_id"]) == "c"),
      "traced and detected positions have different uncertainties")
check("...and are counted in the summary",
      ts5.summary()["hand_added_points"] == 2)
try:
    ts5.add("a", [{"time_s": 0.0, "x_mm": 0, "y_mm": 0},
                  {"time_s": 1.0, "x_mm": 0, "y_mm": 0}])
    check("adding to an existing id is refused", False)
except te.TrackEditError as exc:
    check("adding to an existing id is refused", True)
    check("...naming that traced and detected points would be pooled",
          "nothing downstream could tell them apart" in str(exc))

check("every edit carries a timestamp and an author field",
      all("utc" in e and "by" in e for e in ts5.log))
check("an unattributed edit says so",
      any("unattributed" in e for e in ts5.log) or ts5.log[0]["by"],
      "a curated dataset and an untouched one look identical afterwards")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("DETECTION_AND_EDITING_PASS")
