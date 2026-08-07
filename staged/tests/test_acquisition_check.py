"""Does a recording support what you intend to measure?

The decisive test is the real one: an archived magnetotaxis movie at 1 fps,
49.8 um/px, 1.14 mm worms. It was re-tracked in full and the trajectories were
a random walk - turning 70-95 degrees where uncorrelated is 90, rising as the
sampling interval lengthened. Speed came out plausible. So the module must
pass position and speed and fail everything from direction of travel upward,
or it is not describing what actually happened.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import acquisition_check as ac   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("acquisition check - regression\n")

# --- the recording that failed -----------------------------------------------
MTX = dict(fps=1.0, um_per_px=1000 / 20.1, body_length_um=1140, gait="crawl")
r = ac.check(**MTX)

check("the real recording measures ~23 px of animal",
      22 < r["body_length_px"] < 24, f"{r['body_length_px']} px")
check("...sampled 2 times per undulation", r["samples_per_undulation"] == 2.0)
check("position IS supported", r["measurements"]["position"]["supported"])
check("speed IS supported", r["measurements"]["speed"]["supported"],
      "speed came out plausible on the real data, ~0.1 mm/s")
check("direction of travel is NOT supported",
      not r["measurements"]["track_direction"]["supported"],
      "the empirical finding: headings were a random walk")
check("turning is NOT supported",
      not r["measurements"]["turning"]["supported"])
check("body orientation is NOT supported",
      not r["measurements"]["body_orientation"]["supported"])
check("omega turns are NOT supported",
      not r["measurements"]["omega_turns"]["supported"])

check("the aliasing warning fires at exactly Nyquist",
      any("alias" in w for w in r["warnings"]),
      "written at <2 first, and stayed silent on the recording that aliased")
check("...naming that Nyquist is not a usable threshold",
      any("barely above Nyquist" in w for w in r["warnings"]))
check("...and citing the measurement rather than the theory",
      any("rose toward 90 degrees" in w for w in r["warnings"]))

# --- failures name the fix in microscope units -------------------------------
fix = r["measurements"]["body_orientation"]["fix"]
check("a failure says what to change", fix is not None)
check("...in um/px, not in pixels",
      "um/px" in fix, "the number a microscope is set by")
check("...and in fps", "fps" in fix)
check("...and says spines are needed, pointing at what decides that",
      "tractability" in fix,
      "whether spines are recoverable is measured, not assumed")

# --- a recording that works ---------------------------------------------------
# Scoped to the LOCOMOTION readouts. Pumping is governed by event duration
# rather than by an undulation, so a recording can be excellent for every
# locomotion measurement and still be useless for counting pumps - which is
# the next check, and the reason this one is no longer "everything".
LOCOMOTION = [k for k, s in ac.MEASUREMENTS.items() if not s.get("min_fps")]
good = ac.check(fps=10.0, um_per_px=10.0, body_length_um=1140, gait="crawl",
                tier="spine", wants=LOCOMOTION)
check("a well-sampled, well-magnified recording supports every locomotion "
      "readout", good["n_unsupported"] == 0,
      f"{good['body_length_px']:.0f} px, "
      f"{good['samples_per_undulation']} samples/cycle")
check("...and raises no warning", good["warnings"] == [])

# --- the same recording, for pumping ------------------------------------------
pump = ac.check(fps=10.0, um_per_px=10.0, wants=("pumping",))["measurements"]["pumping"]
check("...while the same 10 fps recording does NOT support pumping",
      not pump["supported"],
      f"{pump['frames_per_event']} frames per pump event")
check("...because a pump is an event, not a waveform",
      "LASTS" in (pump["fix"] or ""),
      "the fix must say so, or someone recomputes the floor from Nyquist")
check("the Nyquist answer for a 4-5 Hz pump rate is explicitly not enough",
      not ac.check(fps=20.0, um_per_px=10.0,
                   wants=("pumping",))["measurements"]["pumping"]["supported"],
      "4 samples x 5 Hz = 20 fps, and a 150 ms pump spans 3 frames there")
# THE COMFORTABLE TIER WAS IMPOSSIBLE AND IS GONE. It read 40 fps (6 frames
# per 150 ms pump), but every rig in this lab tops out at 30. So the warning
# it drove fired on EVERY recording the lab can ever make - at 30 fps a pump
# spans 4.5 frames against a 6-frame threshold - and the acquisition standard
# told a student to film faster than her camera can. A warning nobody can
# clear is noise, and noise teaches people to ignore warnings that matter.
at_ceiling = ac.check(fps=30.0, um_per_px=10.0,
                      wants=("pumping",))["measurements"]["pumping"]
check("30 fps counts pumping",
      at_ceiling["supported"]
      and at_ceiling["pumping_presence"] == "countable")
check("...and is flagged as sitting at the camera ceiling",
      at_ceiling["at_camera_ceiling"]
      and "faster camera" in at_ceiling["margin_note"],
      "the only way to gain margin is hardware, not a setting")
check("...without an unclearable warning attached",
      not any("comfort" in w.lower() for w in
              ac.check(fps=30.0, um_per_px=10.0,
                       wants=("pumping",))["warnings"]),
      "this warning used to fire on every recording the lab will ever own")

# PRESENT BUT NOT COUNTABLE. Andres scores pumping by eye at 15 fps by
# catching the direction reversal, which needs two samples in the event
# rather than four. Between 15 and 30 the pumping is visible and the RATE is
# not recoverable - and since defecation and crawling are often filmed below
# 30, this band is expected to be well populated.
band = ac.check(fps=20.0, um_per_px=10.0,
                wants=("pumping",))["measurements"]["pumping"]
check("20 fps is present but not countable",
      band["pumping_presence"] == "present but not countable")
check("...which is still not 'supported', because the rate is the readout",
      not band["supported"])
check("...and the reason distinguishes seeing from counting",
      "VISIBLE" in " ".join(band["fails"])
      and "COUNT" in " ".join(band["fails"]))
check("below 15 fps pumping is not even present",
      ac.check(fps=10.0, um_per_px=10.0, wants=("pumping",))
      ["measurements"]["pumping"].get("pumping_presence") is None)

check("the fix never says 'or faster' at the ceiling",
      "or faster" not in (band["fix"] or ""),
      "30 fps IS the maximum; there is nothing above it to reach for")

# A RECOMMENDATION NO RIG CAN MEET MUST SAY SO, which is how the 40 fps tier
# got into the standard unnoticed in the first place.
reachable = ac.recommend(wants=("pumping",), gait="crawl")
check("a reachable recommendation carries no warning",
      reachable["exceeds_camera"] == ""
      and reachable["min_fps"] <= reachable["camera_max_fps"])
unreachable = ac.recommend(wants=("omega_turns",), gait="swim",
                           undulation_hz=6.0)
check("a recommendation above the camera maximum says it is impossible",
      unreachable["min_fps"] > unreachable["camera_max_fps"]
      and "cannot be acquired here" in unreachable["exceeds_camera"],
      f"{unreachable['min_fps']:g} fps asked of a 30 fps rig")
check("the spatial requirement abstains rather than guessing from body length",
      "spatial_unverified" in pump,
      "a pumping recording frames the head, not the animal")

# --- the spine tier is not optional for orientation --------------------------
centroid = ac.check(fps=10.0, um_per_px=10.0, tier="centroid")
check("good optics and frame rate still cannot give body orientation "
      "from centroids",
      not centroid["measurements"]["body_orientation"]["supported"],
      "a centroid gives direction of TRAVEL, not orientation of the BODY")
check("...while speed is unaffected by the tier",
      centroid["measurements"]["speed"]["supported"])

# --- swimming is far less forgiving than crawling ----------------------------
swim = ac.check(fps=10.0, um_per_px=10.0, gait="swim", tier="spine")
crawl = ac.check(fps=10.0, um_per_px=10.0, gait="crawl", tier="spine")
check("the same settings support less for a swimming animal",
      swim["n_unsupported"] > crawl["n_unsupported"],
      "swimming undulates ~4x faster, so 10 fps buys 4x fewer samples")
check("...and the undulation rate used is stated, not hidden",
      swim["undulation_hz"] == 2.0 and crawl["undulation_hz"] == 0.5)

# --- planning forwards --------------------------------------------------------
rec = ac.recommend(wants=("speed", "track_direction"), gait="crawl")
check("a plan can be derived from the measurements wanted",
      rec["min_fps"] == 2.0 and rec["min_body_px"] == 20)
hard = ac.recommend(wants=("omega_turns",), gait="swim")
check("harder measurements demand more",
      hard["min_fps"] == 20.0 and hard["max_um_per_px"] == 19.0)
check("...and say spines are required", hard["needs_spine"] is True)
check("...naming that a pile cannot be segmented at any frame rate",
      "any frame rate" in hard["why"])
check("the recommendation admits these are floors, not targets",
      "not targets for a good recording" in rec["caveat"])
try:
    ac.recommend(wants=())
    check("recommending with nothing asked for is refused", False)
except ac.AcquisitionError as exc:
    check("recommending with nothing asked for is refused", True)
    check("...naming that settings follow from measurements",
          "not the other way round" in str(exc))

# --- refusals -----------------------------------------------------------------
for kwargs, phrase in (
    ({"fps": 0, "um_per_px": 10}, "Every temporal check here is a ratio"),
    ({"fps": 10, "um_per_px": 0}, "whether a midline can be fitted"),
):
    try:
        ac.check(**kwargs)
        check(f"missing {'fps' if not kwargs['fps'] else 'scale'} is refused",
              False)
    except ac.AcquisitionError as exc:
        check(f"missing {'fps' if not kwargs['fps'] else 'scale'} is refused",
              True)
        check("...naming the consequence", phrase in str(exc))
try:
    ac.check(fps=10, um_per_px=10, wants=("telepathy",))
    check("an unknown measurement is refused", False)
except ac.AcquisitionError:
    check("an unknown measurement is refused", True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ACQUISITION_CHECK_PASS")
