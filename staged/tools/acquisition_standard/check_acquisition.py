"""Check a short test recording against the acquisition standard.

    python check_acquisition.py "D:\\test_clip" --fps 30 --gait crawl
    python check_acquisition.py clip.avi --fps 30 --um-per-px 4.2 --assay crawling

Film ten seconds of the animals you actually intend to record, at the settings
you actually intend to use, and run this before filming the experiment. It
measures the recording, then answers - per measurement - whether the data can
support it, and names the change to the microscope when it cannot.

It is deliberately possible to run this with no calibration at all. Every
floor in the standard is a floor on PIXELS PER ANIMAL, which is measurable
from the image; a scale is only needed to convert a failure into a target in
micrometres. Passing --um-per-px additionally cross-examines the calibration
against the animals in the frame.

Exit code is 0 when every requested measurement is supported, 1 otherwise, so
it can gate a pipeline as well as inform a person.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools" / "population_swimming")]

import acquisition_check as ac          # noqa: E402
import acquisition_probe as ap          # noqa: E402

# Which measurements each assay actually asks for. Named from the tools that
# consume them, so a change to what a tool needs shows up here rather than in
# a document nobody re-reads.
ASSAY_WANTS = {
    "crawling": ("position", "speed", "track_direction", "turning",
                 "curvature"),
    "basal_slowing": ("position", "speed", "track_direction"),
    "swimming": ("position", "speed", "curvature", "omega_turns"),
    "magnetotaxis": ("position", "speed", "track_direction", "body_orientation"),
    "foraging": ("position", "speed", "track_direction", "turning"),
    "pumping": ("pumping",),
    "defecation": ("position", "speed"),
    "all": tuple(ac.MEASUREMENTS),
}
ASSAY_GAIT = {"swimming": "swim"}
# Oblique illumination is deliberate technique for these two, chosen for
# contrast against the cuticle and the gut. It is a property of the assay, not
# of the rig on a given day, so it is checkable and its absence is a defect.
OBLIQUE_REQUIRED = {"pumping", "defecation"}

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"


class Report:
    def __init__(self):
        self.rows = []

    def add(self, verdict, name, detail=""):
        self.rows.append((verdict, name, detail))

    @property
    def failed(self):
        return [r for r in self.rows if r[0] == FAIL]

    def render(self, width=62):
        for verdict, name, detail in self.rows:
            print(f"  {verdict:4}  {name}")
            if detail:
                for line in _wrap(detail, width):
                    print(f"          {line}")


def _wrap(text, width):
    words, line, out = str(text).split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="image folder, TIFF stack, or video")
    p.add_argument("--fps", type=float,
                   help="frame rate the camera was set to (required for an "
                        "image folder, which carries none)")
    p.add_argument("--um-per-px", type=float, dest="um_per_px",
                   help="declared scale; supplying it cross-examines the "
                        "calibration against the animals in the frame")
    p.add_argument("--assay", default="crawling",
                   choices=sorted(ASSAY_WANTS),
                   help="which measurements this recording is for")
    p.add_argument("--gait", choices=("crawl", "swim"),
                   help="overrides the gait implied by --assay")
    p.add_argument("--body-length-um", type=float, default=1140.0,
                   dest="body_length_um")
    p.add_argument("--tier", default="centroid", choices=("centroid", "spine"),
                   help="whether the analysis extracts midlines or centroids")
    p.add_argument("--frames", type=int, default=40,
                   help="how many frames to sample")
    p.add_argument("--json", action="store_true",
                   help="emit the full measurement record as JSON")
    args = p.parse_args()

    gait = args.gait or ASSAY_GAIT.get(args.assay, "crawl")
    wants = ASSAY_WANTS[args.assay]

    print(f"\nAcquisition check - {args.source}")
    print(f"assay {args.assay}, gait {gait}, "
          f"analysis tier {args.tier}\n")

    probe = ap.probe(args.source, sample_frames=args.frames,
                     declared_fps=args.fps, um_per_px=args.um_per_px,
                     body_length_um=args.body_length_um)

    report = Report()

    # ---- what the recording is ------------------------------------------
    h, w = probe["frame_shape"]
    report.add(INFO, f"{probe['n_frames']} frames, {w}x{h}, "
                     f"{probe['source_kind']}",
               f"sampled {probe['frames_sampled']} of them")

    # ---- frame rate ------------------------------------------------------
    fps = args.fps or probe["header_fps"]
    if not fps:
        report.add(FAIL, "Frame rate is unknown",
                   "This source carries no frame rate and none was declared. "
                   "Every temporal floor in the standard is a ratio against "
                   "it, so nothing below can be decided. Re-run with --fps.")
        report.render()
        print(f"\n{len(report.failed)} requirement(s) failed.")
        return 1
    if probe["header_fps"] and args.fps:
        report.add(PASS if not probe["disagreements"] else FAIL,
                   "Declared frame rate matches the file header",
                   f"header {probe['header_fps']:g} fps, "
                   f"declared {args.fps:g} fps")

    # ---- body size, measured --------------------------------------------
    body_px = probe["body_length_px"]
    if body_px is None:
        report.add(FAIL, "Could not measure the animals",
                   probe["body_length_detail"].get("note", ""))
        report.render()
        print(f"\n{len(report.failed)} requirement(s) failed.")
        return 1
    detail = probe["body_length_detail"]
    report.add(PASS if body_px > 20 else FAIL,
               f"Animals span more than 20 px (measured {body_px:.1f} px)",
               f"median of {detail['n_length_samples']} objects, "
               f"{detail['objects_per_frame']:g} per frame; spread "
               f"{detail.get('length_spread_px', 0):g} px. Measured from the "
               f"segmentation, not from the declared scale.")

    # ---- the calibration, if one was declared ----------------------------
    for note in probe["disagreements"]:
        report.add(FAIL, "Declared numbers disagree with the recording", note)

    # ---- two segmentations, kept visible rather than reconciled ----------
    if probe.get("segmentation_disagreement"):
        report.add(WARN, "The two segmentations disagree about body length",
                   probe["segmentation_disagreement"])
    elif probe.get("body_length_px_texture"):
        report.add(INFO,
                   f"Both segmentations agree "
                   f"({probe['body_length_px']:.0f} px illumination, "
                   f"{probe['body_length_px_texture']:.0f} px texture)",
                   f"length reported from the "
                   f"{probe['body_length_method']} rule")

    # ---- per-measurement verdicts ---------------------------------------
    # The check works in pixels per animal; when nothing is calibrated, feed
    # it the scale the measured animal implies so the verdicts rest on the
    # measurement rather than on a declaration.
    scale = args.um_per_px or ap.measured_um_per_px(body_px,
                                                    args.body_length_um)
    verdicts = ac.check(fps=fps, um_per_px=scale,
                        body_length_um=args.body_length_um, wants=wants,
                        gait=gait, tier=args.tier)

    report.add(PASS if verdicts["samples_per_undulation"] >= 4 else FAIL,
               f"Frame rate substantially exceeds the body wave "
               f"({verdicts['samples_per_undulation']:g} samples per cycle)",
               f"{fps:g} fps against a {verdicts['undulation_hz']:g} Hz "
               f"{gait} undulation. Four samples per cycle is the practical "
               f"floor; Nyquist ({verdicts['nyquist_fps']:g} fps) is not.")

    for key in wants:
        m = verdicts["measurements"][key]
        if m["supported"]:
            report.add(PASS, m["label"])
        else:
            report.add(FAIL, m["label"],
                       f"{'; '.join(m['fails'])}. {m['why']} "
                       f"FIX: {m['fix']}.")

    # ---- sensor range ----------------------------------------------------
    it = probe["intensity"]
    report.add(FAIL if it["saturated_fraction"] > ap.SATURATION_TOLERANCE
               else PASS,
               f"Not clipping ({it['saturated_fraction']:.2%} of pixels at "
               f"full scale)",
               "Saturated pixels have lost the value they were meant to "
               "carry, and no analysis restores it.")
    used_fraction = it["grey_levels_used"] / it["grey_levels_available"]
    report.add(FAIL if used_fraction < 0.05 else
               WARN if used_fraction < 0.15 else PASS,
               f"Sensor range in use ({it['grey_levels_used']} of "
               f"{it['grey_levels_available']} usable levels, "
               f"{it['bit_depth_effective']:g} effective bits)",
               "A recording using a few dozen levels with most pixels at "
               "zero is not a dim recording to be normalised later - there "
               "is nothing in it to normalise. Raise exposure, gain or "
               "illumination at the scope.")
    if it["zero_fraction"] > 0.90:
        report.add(FAIL, f"{it['zero_fraction']:.0%} of pixels are exactly "
                         f"zero",
                   "A near-empty frame produces enormous ratios from "
                   "quantisation noise divided by a near-zero baseline.")
    # ---- substrate: an eligibility gate for the feeding readouts ---------
    sub = probe.get("substrate")
    if sub is not None:
        if args.assay in OBLIQUE_REQUIRED and not sub["textured"]:
            report.add(FAIL,
                       f"Substrate is {sub['substrate']}, so {args.assay} was "
                       f"never possible here",
                       f"texture score {sub['texture_score']:g} against "
                       f"{sub['threshold']:g}. {sub['note']}")
        else:
            report.add(INFO, f"Substrate looks like a {sub['substrate']}",
                       f"texture score {sub['texture_score']:g}. "
                       + ("Pumping and defecation are possible here."
                          if sub["textured"] else
                          "No food, so no pumping or defecation - which is "
                          "only a problem if those were the intended "
                          "readouts."))

    # ---- oblique illumination, where the assay requires it ---------------
    if args.assay in OBLIQUE_REQUIRED:
        shadow = probe.get("shadow")
        if shadow is None:
            report.add(WARN, "Oblique illumination could not be assessed",
                       "The animal was not segmented well enough to sample "
                       "either side of it. Not a verdict on the lighting.")
        elif shadow["directional"]:
            report.add(PASS,
                       f"Oblique illumination present, shadow "
                       f"{shadow['direction']} ({shadow['azimuth_deg']:g}deg)",
                       f"consistency {shadow['consistency']:.2f}, contrast "
                       f"{shadow['contrast']:.0f} counts. Deliberate technique "
                       f"for this assay, not an artefact.")
        else:
            report.add(FAIL,
                       "No directional shadow, and this assay needs one",
                       f"consistency {shadow['consistency']:.2f} against "
                       f"{ap.SHADOW_MIN_CONSISTENCY}, contrast "
                       f"{shadow['contrast']:.0f} against "
                       f"{ap.SHADOW_MIN_CONTRAST:.0f}. Oblique lighting is "
                       f"chosen for contrast on pumping and defecation. "
                       f"KNOWN EXCEPTION: an animal immersed in an OP50 lawn "
                       f"casts little shadow even under correct lighting - if "
                       f"that is the case here, record it rather than "
                       f"relighting.")

    report.add(INFO, f"Focus score {probe['focus_laplacian_var']:g}",
               "Laplacian variance - comparable only within one rig and "
               "magnification, so it is reported rather than graded.")

    report.render()
    for w_ in verdicts["warnings"]:
        print("\n  NOTE: " + "\n        ".join(_wrap(w_, 62)))

    n_fail = len(report.failed)
    print(f"\n{len(report.rows) - n_fail} of {len(report.rows)} checks "
          f"passed or informational; {n_fail} failed.")
    if not n_fail:
        rec = ac.recommend(wants=wants, gait=gait,
                           body_length_um=args.body_length_um)
        print(f"\nThis recording clears the floors for {args.assay}. For "
              f"reference the floors are {rec['min_fps']:g} fps and "
              f"{rec['min_body_px']} px of animal.")
        print("  " + "\n  ".join(_wrap(rec["caveat"], 68)))
    if args.json:
        print("\n" + json.dumps({"probe": probe, "verdicts": verdicts},
                                indent=2, default=str))
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
