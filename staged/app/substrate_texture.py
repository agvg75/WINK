"""Describe what the animals were on, from the background image.

WHY
---
Whether a plate was seeded with OP50 changes almost everything about
locomotion - speed, dwelling, reversal rate, the basal slowing response
itself. It is metadata that belongs with the data, and it is usually recorded
only in a lab notebook, if at all. The background image every tracking module
already computes carries the evidence: bacterial lawns have texture and an
edge; clean agar does not.

WHAT THIS IS, AND IS NOT
------------------------
These are MEASUREMENTS with a tentative reading attached. The numbers are
objective and reproducible. The label is a heuristic, and a heuristic that has
not been validated against labelled examples should not be trusted to decide
anything.

So: the metrics are always recorded, the label is always marked with its
confidence and its basis, and the label never replaces the numbers. If the
reading turns out to be wrong for a rig, the stored metrics remain usable and
the threshold can be recalibrated afterwards without re-running anything.

The lab can teach it: confirmed examples recorded through
`record_substrate_example` build per-rig thresholds, exactly as the worm
measurement library does, and the heuristic defers to them once enough exist.
"""
from __future__ import annotations

import json
from pathlib import Path

SUBSTRATE_LOG = Path.home() / ".wink" / "substrate_examples.jsonl"
MIN_EXAMPLES_PER_CLASS = 4

CLASSES = ("unseeded", "seeded")


def substrate_metrics(image, mask=None):
    """Objective texture statistics for a background image.

    `mask`, if given, marks pixels to ignore (for example a vessel exterior).
    Every value is scale-free or in intensity units so recordings at different
    resolutions remain comparable.
    """
    try:
        import numpy as np
        import cv2
    except Exception:
        return None
    img = np.asarray(image)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    img = np.clip(img, 0, 255).astype("uint8")
    if mask is not None:
        mask = np.asarray(mask).astype(bool)
        if mask.shape != img.shape:
            mask = None

    values = img[mask] if mask is not None else img.reshape(-1)
    if values.size < 100:
        return None

    # Local texture: how much intensity varies within small neighbourhoods.
    # A lawn is granular at this scale; clean agar is smooth.
    blur = cv2.blur(img.astype("float32"), (9, 9))
    local_var = cv2.blur((img.astype("float32") - blur) ** 2, (9, 9))
    lv = local_var[mask] if mask is not None else local_var.reshape(-1)

    # Edge density: a lawn has a boundary and internal structure.
    edges = cv2.Canny(img, 40, 120) > 0
    ed = edges[mask] if mask is not None else edges.reshape(-1)

    # Otsu separability: how cleanly the frame splits into two intensity
    # populations. A lawn against agar is bimodal; bare agar is not.
    hist = np.bincount(values, minlength=256).astype("float64")
    total = hist.sum()
    prob = hist / total
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = np.where(denom > 0, (mu_t * omega - mu) ** 2 / denom, 0.0)
    k = int(np.argmax(between))
    separability = float(between[k] / (values.var() + 1e-9))
    darker = float((values <= k).mean())

    laplacian = cv2.Laplacian(img, cv2.CV_32F)
    lap = laplacian[mask] if mask is not None else laplacian.reshape(-1)

    return {
        "mean_intensity": float(values.mean()),
        "intensity_sd": float(values.std()),
        "local_variance_mean": float(lv.mean()),
        "local_variance_p90": float(np.percentile(lv, 90)),
        "edge_density": float(ed.mean()),
        "laplacian_energy": float((lap ** 2).mean()),
        "otsu_separability": separability,
        "otsu_threshold": int(k),
        "darker_fraction": darker,
        "pixels_measured": int(values.size),
    }


def _load_examples(paths=None):
    rows = []
    for p in (paths or [SUBSTRATE_LOG]):
        try:
            if not Path(p).exists():
                continue
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        except Exception:
            continue
    return [r for r in rows if r.get("confirmed") and r.get("label") in CLASSES]


def record_substrate_example(*, label, metrics, module, run_id,
                             confirmed=True, path=None):
    """Store a CONFIRMED example so the lab can calibrate the reading.

    Only record `label` when a person actually knows what the plate was.
    """
    import datetime
    if label not in CLASSES:
        raise ValueError(f"label must be one of {CLASSES}")
    entry = {"recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "label": label, "module": module, "run_id": str(run_id),
             "confirmed": bool(confirmed), "metrics": metrics}
    target = Path(path) if path else SUBSTRATE_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


# Heuristic starting points, deliberately conservative. A seeded plate normally
# shows granular texture and a bimodal split where the lawn meets bare agar.
# These are NOT validated thresholds - they are a first guess that says so.
HEURISTIC = {
    "local_variance_mean": 6.0,
    "edge_density": 0.010,
    "otsu_separability": 0.55,
}

# Otsu separability is the between-class variance divided by the TOTAL
# variance, so on a nearly uniform image it can sit high while describing
# nothing - a synthetic clean-agar control scored 0.674 with an intensity SD of
# about 1.2, which would have misread every smooth plate as possibly seeded.
# The feature only carries information when the frame has real contrast to
# split, so below this it abstains rather than voting.
SEPARABILITY_MIN_SD = 4.0


def read_substrate(metrics, paths=None):
    """A tentative reading of what the animals were on.

    Returns a dict with `label`, `confidence`, `basis` and `evidence`. The
    label may be "uncertain"; that is a legitimate and common outcome.
    """
    if not metrics:
        return None
    examples = _load_examples(paths)
    by_class = {c: [e["metrics"] for e in examples if e["label"] == c] for c in CLASSES}
    enough = all(len(by_class[c]) >= MIN_EXAMPLES_PER_CLASS for c in CLASSES)

    if enough:
        # Nearest-class comparison on the three discriminating features,
        # normalised by each class's own spread.
        import statistics
        score = {}
        for c in CLASSES:
            total = 0.0
            for key in HEURISTIC:
                vals = [m.get(key) for m in by_class[c] if m.get(key) is not None]
                if len(vals) < 2:
                    continue
                mean = statistics.fmean(vals)
                sd = statistics.pstdev(vals) or 1e-6
                total += abs((metrics.get(key, mean) - mean) / sd)
            score[c] = total
        best = min(score, key=score.get)
        other = max(score, key=score.get)
        margin = score[other] - score[best]
        return {"label": best if margin > 1.0 else "uncertain",
                "confidence": "measured" if margin > 2.0 else "weak",
                "basis": (f"compared against {len(by_class['unseeded'])} unseeded and "
                          f"{len(by_class['seeded'])} seeded confirmed examples"),
                "evidence": {"distance": score, "margin": round(margin, 3)},
                "metrics": metrics}

    votes = {
        "local_variance_mean": metrics["local_variance_mean"] > HEURISTIC["local_variance_mean"],
        "edge_density": metrics["edge_density"] > HEURISTIC["edge_density"],
    }
    # Only let the bimodality feature vote when there is contrast to be bimodal
    # about; otherwise it abstains and is recorded as having done so.
    if metrics.get("intensity_sd", 0.0) >= SEPARABILITY_MIN_SD:
        votes["otsu_separability"] = (metrics["otsu_separability"]
                                      > HEURISTIC["otsu_separability"])
    else:
        votes["otsu_separability"] = "abstained_low_contrast"

    counted = [v for v in votes.values() if isinstance(v, bool)]
    seeded_votes = sum(1 for v in counted if v)
    if seeded_votes >= max(2, len(counted) - 1) and seeded_votes > 0:
        label = "seeded"
    elif seeded_votes == 0:
        label = "unseeded"
    else:
        label = "uncertain"
    return {
        "label": label,
        "confidence": "unvalidated_heuristic",
        "basis": (f"no confirmed examples for this lab yet ("
                  f"{len(by_class['unseeded'])} unseeded, {len(by_class['seeded'])} "
                  f"seeded; {MIN_EXAMPLES_PER_CLASS} of each needed). Using generic "
                  f"thresholds, which have NOT been validated on this rig - treat "
                  f"the label as a prompt to record the truth, not as a finding."),
        "evidence": {"votes": votes, "thresholds": dict(HEURISTIC)},
        "metrics": metrics,
    }
