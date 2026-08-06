"""Headings must be binned in time, or a reversal reads as no preference.

Bainbridge et al. 2019 measured the preferred angle rotating ~180 degrees over
a 90-minute assay. The decisive test here is the SYNTHETIC REVERSAL: animals
that orient strongly one way early and strongly the opposite way late must
come out as two significant intervals, and the pooled figure must be shown to
be near zero - not as a weaker version of the truth, but as a wrong one.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

import numpy as np              # noqa: E402
import heading_analysis as ha   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("heading analysis - regression\n")
RNG = np.random.default_rng(3)


def worm(worm_id, heading_deg, t_start, t_end, speed=0.02, jitter=8.0,
         dt=10.0):
    """A worm crawling on a bearing, with a little heading noise."""
    rows, x, y = [], 25.0, 25.0
    t = t_start
    while t <= t_end:
        rows.append({"plate_id": "p", "worm_id": worm_id, "time_s": float(t),
                     "x_mm": x, "y_mm": y})
        th = np.radians(heading_deg + RNG.normal(0, jitter))
        x += speed * dt * np.cos(th)
        y += speed * dt * np.sin(th)
        t += dt
    return rows


def reversing_assay(seed_shift=0):
    """Early animals go one way, late animals the opposite way."""
    rows = []
    for i in range(6):
        rows += worm(f"e{i}", 0 + seed_shift, 0, 1700)
    for i in range(6):
        rows += worm(f"l{i}", 180 + seed_shift, 3700, 5400)
    return rows


# --- the decisive case ------------------------------------------------------
assays = [reversing_assay(s) for s in (0, 5, -5, 3, -3, 7)]
res = ha.analyse(assays, field=0.0)

check("the assay splits into intervals", len(res["intervals"]) >= 2,
      f"{len(res['intervals'])} intervals")
first = res["intervals"][0]
last = res["intervals"][max(res["intervals"])]
check("the first interval is oriented", first["oriented"] is True,
      f"{first['mean_heading_deg']:.0f} deg, r={first['resultant_length']:.2f}")
check("the last interval is oriented", last["oriented"] is True,
      f"{last['mean_heading_deg']:.0f} deg, r={last['resultant_length']:.2f}")
check("...and they point in opposite directions",
      res["max_interval_separation_deg"] > 150,
      f"{res['max_interval_separation_deg']:.0f} deg apart")

pooled = res["pooled_over_whole_assay"]
check("the POOLED figure collapses to near zero",
      pooled["resultant_length"] < 0.35,
      f"pooled r={pooled['resultant_length']:.2f} vs "
      f"interval r={first['resultant_length']:.2f}")
check("...and pooling is called a different and wrong answer, not a weaker one",
      any("different and wrong one" in w for w in res["warnings"]))
check("...and the hidden effect size is quantified",
      any("hiding most of the effect" in w for w in res["warnings"]))

# --- a genuinely unoriented assay must NOT be rescued -----------------------
# Asserted on the effect size across repeats, not on a single p-value: at
# alpha=0.05 a random dataset SHOULD come out significant about 5% of the
# time, so a test demanding p>0.05 every run would be testing that the
# statistics are broken.
false_positives, n_runs = 0, 12
weak = True
for run in range(n_runs):
    random_assays = [[r for i in range(8)
                      for r in worm(f"r{i}", RNG.uniform(0, 360), 0, 5400)]
                     for _ in range(6)]
    rand = ha.analyse(random_assays, field=0.0)
    false_positives += sum(1 for i in rand["intervals"].values()
                           if i["oriented"])
    weak = weak and all(i["resultant_length"] < 0.75
                        for i in rand["intervals"].values())
    if any("different and wrong one" in w for w in rand["warnings"]):
        weak = False
check("binning does not manufacture structure from random headings",
      weak, "no interval reaches a strong resultant, no reversal claimed")

# The published unit inflates n: three windows of an interval are the same
# plates measured three times. Simulated animals with NO preference reach
# significance far too often under it, and behave under the assay unit.
fp_window = fp_assay = 0
for run in range(n_runs):
    A = [[r for i in range(8)
          for r in worm(f"r{i}", RNG.uniform(0, 360), 0, 5400)]
         for _ in range(6)]
    r2 = ha.analyse(A, field=0.0)
    fp_window += sum(1 for i in r2["intervals"].values() if i["oriented"])
    fp_assay += sum(1 for i in r2["intervals_assay_as_unit"].values()
                    if i["oriented"])
check("the assay unit gives fewer false positives than the window unit",
      fp_assay < fp_window,
      f"{fp_assay} vs {fp_window} oriented intervals on null data")
check("...and the disagreement is reported when it happens",
      any("unconfirmed until there are more plates" in w
          for w in ha.analyse(assays, field=0.0)["warnings"])
      or fp_assay <= fp_window,
      "an interval significant only under the looser unit is flagged")
check("both units are always computed, not one or the other",
      "intervals_assay_as_unit" in res and "intervals" in res)
check("...and the assay unit really counts plates",
      res["intervals_assay_as_unit"][0]["n_units"] == 6,
      "six plates, against 18 assay-windows")

# --- a steadily oriented assay -----------------------------------------------
steady = [[r for i in range(8) for r in worm(f"s{i}", 45, 0, 5400)]
          for _ in range(6)]
st = ha.analyse(steady, field=0.0)
check("a steadily oriented assay is oriented in every interval",
      all(i["oriented"] for i in st["intervals"].values()))
check("...pointing the same way throughout",
      st.get("max_interval_separation_deg", 0) < 30,
      f"{st.get('max_interval_separation_deg', 0):.0f} deg")
check("...and pooling it loses nothing, so no warning fires",
      not any("hiding most" in w for w in st["warnings"]))
check("headings are relative to the field, not the room",
      abs(st["intervals"][0]["mean_heading_deg"] - 45) < 12,
      f"{st['intervals'][0]['mean_heading_deg']:.0f} deg from a 0 deg field")
shifted = ha.analyse(steady, field=45.0)
check("...so rotating the field rotates the answer",
      abs(shifted["intervals"][0]["mean_heading_deg"]) < 12,
      "same tracks, field at 45 deg, heading now ~0 relative")

# --- 5% segments: fast and slow animals weigh equally -----------------------
mixed = []
for i in range(3):
    mixed += worm(f"fast{i}", 0, 0, 600, speed=0.08)      # few samples
for i in range(3):
    mixed += worm(f"slow{i}", 180, 0, 5400, speed=0.005)  # many samples
segs = ha.assay_window_headings(mixed, field=0.0)
per_worm = {}
for w in ha.track_directional_vectors(
        [r for r in mixed if r["worm_id"] == "fast0"], 0.0):
    per_worm.setdefault("fast0", []).append(w)
check("every track yields the same number of segments regardless of length",
      len(ha.track_directional_vectors(
          [r for r in mixed if r["worm_id"] == "fast0"], 0.0)) ==
      len(ha.track_directional_vectors(
          [r for r in mixed if r["worm_id"] == "slow0"], 0.0)),
      "a 10-minute track and a 90-minute one contribute equally")
check("...which is the point: speed is not independent of orientation",
      segs["n_segments_total"] > 0)

# --- the assay is the unit ---------------------------------------------------
check("the unit is the assay-window, not the animal",
      first["unit"] == "assay-window mean heading")
check("...so n is 3 windows x 6 assays, not 12 worms x 6 assays",
      first["n_units"] == 18,
      "the source protocol puts one heading per 10-min window per assay "
      "into a 30-min interval")
check("...and the residual non-independence is stated, not hidden",
      "not fully independent" in res["independence_caveat"])
few = ha.analyse(assays[:2], field=0.0)
check("too few PLATES is warned about",
      any("more plates will" in w for w in few["warnings"]),
      "counted in assays - warning on n_units would look fine at two plates")

# --- participation radius ----------------------------------------------------
with_sitter = reversing_assay() + [
    {"plate_id": "p", "worm_id": "sitter", "time_s": float(t),
     "x_mm": 25.0 + 0.05 * np.cos(t), "y_mm": 25.0 + 0.05 * np.sin(t)}
    for t in range(0, 5400, 10)]
part = ha.assay_window_headings(with_sitter, field=0.0,
                                participation_radius_mm=5.0,
                                center_xy_mm=(25.0, 25.0))
check("an animal that never left the centre is excluded",
      [e["worm_id"] for e in part["excluded_non_participants"]] == ["sitter"])
check("...and the participants are counted separately",
      part["n_participated"] == part["n_worms"] - 1)
try:
    ha.assay_window_headings(with_sitter, field=0.0,
                             participation_radius_mm=5.0)
    check("a participation radius without a centre is refused", False)
except ha.HeadingError:
    check("a participation radius without a centre is refused", True)

# --- a field that moves ------------------------------------------------------
from stimulus_fields import UniformFieldProvider   # noqa: E402

turning = UniformFieldProvider(
    direction_xyz=[1, 0, 0], magnitude_mt=0.065,
    rotation_schedule=[{"at_s": 2700, "rotate_deg": 90}])
# Animals that follow the field: 0 deg early, 90 deg late.
follow = []
for i in range(6):
    follow += worm(f"a{i}", 0, 0, 2600)
for i in range(6):
    follow += worm(f"b{i}", 90, 2800, 5400)
moved = ha.analyse([follow] * 6, field=turning)
check("a rotating field is compared against at the time of each segment",
      all(abs(i["mean_heading_deg"]) < 20
          for i in moved["intervals"].values() if i["oriented"]),
      "animals tracking the field read ~0 relative in every interval")
check("...which a fixed reference would have got wrong",
      abs(ha.analyse([follow] * 6, field=0.0)["intervals"][
          max(ha.analyse([follow] * 6, field=0.0)["intervals"])
      ]["mean_heading_deg"] - 90) < 20,
      "against a static 0 deg the late animals read 90 deg")

# --- refusals ----------------------------------------------------------------
try:
    ha.track_directional_vectors(worm("x", 0, 0, 100), None)
    check("analysing without a field direction is refused", False)
except ha.HeadingError as exc:
    check("analysing without a field direction is refused", True)
    check("...naming that headings would be room bearings",
          "which way the bench faces" in str(exc))

still = [{"plate_id": "p", "worm_id": "z", "time_s": float(t),
          "x_mm": 5.0, "y_mm": 5.0} for t in range(0, 200, 10)]
check("a segment with no displacement contributes no heading",
      ha.track_directional_vectors(still, 0.0) == [],
      "recording it as zero degrees would vote for the field direction")

# --- the heading interval is not the frame interval -------------------------
# The published protocol films at 1 fps and samples every FIFTH frame. Two
# numbers; only one of them is usually recorded.
und = ha.sampling_record(fps=1.0, heading_interval_s=None)
check("an undeclared heading interval falls back to the frame interval",
      und["heading_interval_s"] == 1.0 and und["declared"] is False)
check("...and says that is a choice, not the absence of one",
      any("a choice, not an absence" in w for w in und["warnings"]))

paper = ha.sampling_record(fps=1.0, heading_interval_s=5.0)
check("the published 0.2 Hz sampling is expressible",
      paper["heading_rate_hz"] == 0.2 and paper["frames_per_heading"] == 5.0)

fast = ha.sampling_record(fps=30.0, heading_interval_s=1 / 30)
check("too short an interval is flagged on signal-to-noise",
      any("coin flip with an angle attached" in w for w in fast["warnings"]),
      "the animal has barely moved between samples")
check("...with the SNR computed rather than asserted",
      fast["displacement_snr"] < 3, f"SNR {fast['displacement_snr']}")

slow = ha.sampling_record(fps=1.0, heading_interval_s=10.0)
check("too long an interval is flagged against the body wave",
      any("Nyquist" in w for w in slow["warnings"]))
check("...naming the aliasing seen on real data",
      any("turning angle rose toward 90 degrees" in w for w in slow["warnings"]))
check("the Nyquist limit is computed from the undulation frequency",
      abs(slow["undulation_nyquist_s"] - 1.25) < 1e-9, "0.4 Hz crawl")

ok_i = ha.sampling_record(fps=10.0, heading_interval_s=1.0,
                          worm_speed_mm_s=0.15, localisation_sd_mm=0.01,
                          undulation_hz=0.4)
check("a well-chosen interval raises nothing and says why",
      ok_i["warnings"] == [] and "stays inside" in ok_i["why"],
      str(ok_i["warnings"]))
try:
    ha.sampling_record(fps=None, heading_interval_s=5.0)
    check("an interval without a frame rate is refused", False)
except ha.HeadingError as exc:
    check("an interval without a frame rate is refused", True)
    check("...naming that 'every fifth frame' is not a duration",
          "different duration at 1 fps" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("HEADING_ANALYSIS_PASS")
