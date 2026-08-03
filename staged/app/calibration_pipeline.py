"""Calibration and ground truth: turning review labour into better analysis.

A read layer over three structurally different kinds of human judgement.
They are NOT interchangeable, and the whole point of keeping them apart is
that using one where another belongs produces a number that looks like
evidence and is not.

  correction logs   PAIRED, and contaminated. What the algorithm proposed
                    and what a person changed it to. A person adjusting a
                    proposed peak is anchored by where that peak already
                    was, so these are tuning data - never clean ground
                    truth about where the peak really is.

  batch audit logs  PAIRED confidence and outcome. What score the module
                    gave and whether a person accepted it. This is what
                    tells you whether a confidence score means what it
                    claims.

  legacy datasets   UNPAIRED ground truth. A human measurement made with
                    no algorithm proposal to anchor it. Scientifically the
                    most valuable of the three precisely because nothing
                    contaminated it, and therefore HELD OUT BY DEFAULT.

WHY LEGACY DATA IS HELD OUT UNLESS SOMEONE SAYS OTHERWISE
----------------------------------------------------------
Agreement with manual scoring across representative recordings is what
moves a module from Experimental to Ready. That evidence can only be spent
once: a module evaluated on data it was tuned against tells you nothing
about how it will behave on the next recording. So this module tracks, per
dataset per module, whether that dataset has ever been used for tuning -
and refuses to report an agreement number from a dataset that has, rather
than quietly returning an optimistic one.

MODULE VERSION IS PART OF THE QUERY, NOT A DETAIL
--------------------------------------------------
A confidence score or a parameter default can mean different things either
side of a recalibration. Pooling across versions would corrupt exactly the
curve this module exists to produce, so every analysis here takes a version
and pooling across versions has to be asked for explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import numpy as np

HELD_OUT, TUNING = "held_out_validation", "tuning"


class CalibrationError(RuntimeError):
    """The requested analysis would not mean what it appears to mean."""


def user_data_root():
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AGVGLab" / "quality"
    return Path.home() / ".agvg_lab_tools" / "quality"


# ---------------------------------------------------------------------------
# 1. Legacy dataset intake and the use ledger
# ---------------------------------------------------------------------------
@dataclass
class LegacyDataset:
    """A hand-scored dataset that predates the modules entirely.

    `scoring_records` is deliberately just a path: these predate any
    standard format, and reformatting irreplaceable historical files risks
    transcription error. Write a small per-dataset adapter that reads
    whatever exists and emits this record instead.
    """
    dataset_id: str
    module_target: str
    source_path: str
    scoring_records: str
    scorer_id: str | None = None
    scoring_date: str | None = None
    scoring_protocol_notes: str = ""
    blinded: bool | None = None
    acquisition_metadata: dict = field(default_factory=dict)
    known_limitations: str = ""
    # Inter-scorer agreement bounds what any module could achieve. Where a
    # movie was never double-scored this stays None, which means UNKNOWN -
    # not "the single score is exact".
    double_scored: bool | None = None
    inter_scorer_agreement: float | None = None


@dataclass
class DatasetLedger:
    """Which modules have consumed which legacy dataset, and in what role.

    Held-out status has to be auditable rather than remembered, because the
    consequence of forgetting is an agreement number that looks clean and
    is not.
    """
    root: Path = field(default_factory=lambda: user_data_root() / "calibration")

    def __post_init__(self):
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _datasets_path(self):
        return self.root / "legacy_datasets.jsonl"

    def _uses_path(self):
        return self.root / "dataset_uses.jsonl"

    def register(self, dataset):
        existing = {d["dataset_id"] for d in self.datasets()}
        if dataset.dataset_id in existing:
            raise CalibrationError(
                f"Dataset '{dataset.dataset_id}' is already registered. "
                "Registering it twice would let the same data be counted as "
                "two independent validations.")
        payload = {"schema_version": 1,
                   "registered_utc": datetime.now(timezone.utc).isoformat(),
                   **asdict(dataset)}
        with self._datasets_path().open("a", encoding="utf-8") as s:
            s.write(json.dumps(payload) + "\n")
        return payload

    def datasets(self):
        return _read_jsonl(self._datasets_path())

    def get(self, dataset_id):
        for row in self.datasets():
            if row["dataset_id"] == dataset_id:
                return row
        raise CalibrationError(f"No legacy dataset registered as '{dataset_id}'.")

    def record_use(self, dataset_id, module_name, module_version, role, note=""):
        if role not in (HELD_OUT, TUNING):
            raise CalibrationError(
                f"role must be '{HELD_OUT}' or '{TUNING}', got '{role}'.")
        self.get(dataset_id)          # raises if unknown
        payload = {"schema_version": 1,
                   "recorded_utc": datetime.now(timezone.utc).isoformat(),
                   "dataset_id": dataset_id, "module_name": module_name,
                   "module_version": module_version, "role": role, "note": note}
        with self._uses_path().open("a", encoding="utf-8") as s:
            s.write(json.dumps(payload) + "\n")
        return payload

    def uses(self, dataset_id=None, module_name=None):
        rows = _read_jsonl(self._uses_path())
        if dataset_id:
            rows = [r for r in rows if r["dataset_id"] == dataset_id]
        if module_name:
            rows = [r for r in rows if r["module_name"] == module_name]
        return rows

    def is_held_out_for(self, dataset_id, module_name):
        """False once this dataset has been used to tune this module."""
        return not any(r["role"] == TUNING
                       for r in self.uses(dataset_id, module_name))


def _read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# 2. Unified read layer over the source logs
# ---------------------------------------------------------------------------
def load_correction_log(root=None):
    root = Path(root) if root else (user_data_root() / "morphometry_corrections")
    rows = []
    for path in sorted(Path(root).glob("*_corrections.jsonl")):
        rows.extend(_read_jsonl(path))
    return rows


def load_audit_log(root=None):
    root = Path(root) if root else (user_data_root() / "batch_audit")
    rows = []
    for path in sorted(Path(root).glob("*_batch_audit.jsonl")):
        rows.extend(_read_jsonl(path))
    return rows


def filter_by_version(rows, module_version, version_key="module_version"):
    """Restrict to one module version.

    Deliberately not optional-by-default anywhere it matters: pooling a
    confidence curve across versions silently mixes scores that mean
    different things.
    """
    if module_version is None:
        return list(rows)
    return [r for r in rows if str(r.get(version_key)) == str(module_version)]


# ---------------------------------------------------------------------------
# 3. Confidence calibration from audit logs
# ---------------------------------------------------------------------------
def confidence_calibration(audit_rows, module_version=None, n_bins=10):
    """Reported confidence against observed accept rate.

    A well-calibrated 0.9 bin is accepted about 90% of the time. Returns
    per-bin counts plus a summary, and flags OVERCONFIDENCE specifically -
    it is the dangerous direction, because the auto-accept threshold is set
    on the module's own claim.
    """
    rows = [r for r in filter_by_version(audit_rows, module_version)
            if r.get("in_audit_sample") and r.get("reviewer_decision")]
    if not rows:
        raise CalibrationError(
            "No reviewed audit records for that module version. A calibration "
            "curve needs items that were sampled AND given a verdict.")
    conf = np.array([float(r["confidence"]) for r in rows])
    # 'uncertain' is not an acceptance: treating it as one would make the
    # module look better calibrated than it is.
    accepted = np.array([1.0 if r["reviewer_decision"] == "accept" else 0.0
                         for r in rows])

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = []
    gaps, weights = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (conf >= lo) & (conf < hi if hi < 1.0 else conf <= hi)
        if not mask.any():
            continue
        mean_conf = float(conf[mask].mean())
        observed = float(accepted[mask].mean())
        bins.append({"bin_low": float(lo), "bin_high": float(hi),
                     "n": int(mask.sum()), "mean_confidence": mean_conf,
                     "observed_accept_rate": observed,
                     "gap": observed - mean_conf})
        gaps.append(observed - mean_conf)
        weights.append(int(mask.sum()))

    gaps, weights = np.array(gaps), np.array(weights, dtype=float)
    ece = float(np.average(np.abs(gaps), weights=weights))
    signed = float(np.average(gaps, weights=weights))
    overconfident = signed < -0.05
    return {
        "module_version": module_version,
        "n_reviewed": len(rows),
        "bins": bins,
        "expected_calibration_error": ece,
        "signed_bias": signed,
        "overconfident": overconfident,
        "interpretation": (
            "The module is systematically OVERCONFIDENT: items are accepted "
            "less often than their score claims. This is the dangerous "
            "direction, because the auto-accept threshold is set on that "
            "claim." if overconfident else
            "No systematic overconfidence detected at this sample size. "
            "Under-confidence wastes review effort but does not admit bad "
            "output."),
    }


def recommended_auto_accept_threshold(audit_rows, module_version=None,
                                      target_error_rate=0.05, min_items=20):
    """Lowest confidence whose observed error rate meets the target.

    Replaces an arbitrary default with a threshold that has a measured
    error rate attached. Returns None - not a guess - when no threshold has
    enough reviewed items behind it to support the claim.
    """
    rows = [r for r in filter_by_version(audit_rows, module_version)
            if r.get("in_audit_sample") and r.get("reviewer_decision")]
    if not rows:
        raise CalibrationError("No reviewed audit records for that version.")
    rows.sort(key=lambda r: float(r["confidence"]), reverse=True)
    conf = [float(r["confidence"]) for r in rows]
    bad = [0 if r["reviewer_decision"] == "accept" else 1 for r in rows]

    best = None
    for i in range(len(rows)):
        n = i + 1
        if n < min_items:
            continue
        rate = sum(bad[:n]) / n
        if rate <= target_error_rate:
            best = {"threshold": conf[i], "n_at_or_above": n,
                    "observed_error_rate": rate}
    if best is None:
        return {"threshold": None, "reason": (
            f"No confidence threshold has at least {min_items} reviewed items "
            f"with an observed error rate at or below {target_error_rate:.0%}. "
            "Auto-accept is not supportable from this evidence yet.")}
    best["reason"] = (
        f"At confidence >= {best['threshold']:.3f}, {best['n_at_or_above']} "
        f"reviewed items showed an observed error rate of "
        f"{best['observed_error_rate']:.1%}.")
    return best


# ---------------------------------------------------------------------------
# 4. Parameter recalibration from correction logs
# ---------------------------------------------------------------------------
def parameter_recalibration(correction_rows, value_fn, module_version=None,
                            stratify_by=None):
    """Distribution of the parameter value each correction implies.

    Reports the DISTRIBUTION, never just a best value. A tight distribution
    across recordings means a better global default genuinely exists; a wide
    or multimodal one means no single value works and the parameter should
    stay adaptive or user-exposed. That second answer is a real finding, not
    a failure to produce a number, so it is stated rather than averaged away.
    """
    rows = filter_by_version(correction_rows, module_version)
    values, strata = [], []
    for row in rows:
        try:
            v = value_fn(row)
        except Exception:
            v = None
        if v is None or not np.isfinite(v):
            continue
        values.append(float(v))
        strata.append(str(row.get(stratify_by)) if stratify_by else "all")
    if not values:
        raise CalibrationError(
            "No correction produced a usable parameter value. Check that "
            "value_fn matches this module's correction record shape.")

    values = np.array(values)
    result = {
        "module_version": module_version,
        "n_corrections": len(values),
        "median": float(np.median(values)),
        "iqr": [float(np.percentile(values, 25)), float(np.percentile(values, 75))],
        "min": float(values.min()), "max": float(values.max()),
        "relative_spread": float(
            (np.percentile(values, 75) - np.percentile(values, 25))
            / abs(np.median(values))) if np.median(values) else float("inf"),
    }
    result["stable_operating_point"] = result["relative_spread"] < 0.25
    result["recommendation"] = (
        f"Corrections cluster tightly (IQR is "
        f"{result['relative_spread']:.0%} of the median), so a global default "
        f"near {result['median']:.4g} is supportable."
        if result["stable_operating_point"] else
        f"Corrections are widely spread (IQR is "
        f"{result['relative_spread']:.0%} of the median). No single default "
        f"fits; this parameter should stay adaptive or user-exposed. That is "
        f"the finding, not a missing number.")

    if stratify_by:
        per = {}
        for name in sorted(set(strata)):
            subset = values[np.array(strata) == name]
            if subset.size:
                per[name] = {"n": int(subset.size),
                             "median": float(np.median(subset))}
        result["per_stratum"] = per
        medians = [v["median"] for v in per.values()]
        if len(medians) > 1 and np.median(values):
            spread = (max(medians) - min(medians)) / abs(np.median(values))
            result["stratum_disagreement"] = float(spread)
            if spread > 0.25:
                result["recommendation"] += (
                    f" Strata disagree with each other by {spread:.0%} of the "
                    f"overall median, so a single recalibrated default would "
                    f"be a regression for some of them.")
    return result


# ---------------------------------------------------------------------------
# 5. Module versus human agreement, using held-out legacy data
# ---------------------------------------------------------------------------
def continuous_agreement(module_values, human_values):
    """Bland-Altman style agreement plus correlation, for rates and
    frequencies. Bias and limits of agreement say more than r alone: two
    measures can correlate almost perfectly while one reads consistently
    high."""
    m = np.asarray(module_values, float)
    h = np.asarray(human_values, float)
    if m.shape != h.shape or m.size == 0:
        raise CalibrationError("Module and human value arrays must match and "
                               "be non-empty.")
    diff = m - h
    bias = float(diff.mean())
    sd = float(diff.std(ddof=1)) if diff.size > 1 else 0.0
    r = float(np.corrcoef(m, h)[0, 1]) if diff.size > 1 else float("nan")
    return {"n": int(m.size), "bias": bias, "sd_of_difference": sd,
            "limits_of_agreement": [bias - 1.96 * sd, bias + 1.96 * sd],
            "correlation": r,
            "note": ("Correlation alone can hide a constant offset; the bias "
                     "and limits of agreement are what say whether the two "
                     "measures are interchangeable.")}


def event_agreement(module_times, human_times, tolerance):
    """Event-level precision and recall with an explicit temporal window.

    An event matched a few frames off is a different failure from an event
    missed entirely, so matching needs a stated tolerance rather than an
    exact-equality test.
    """
    module_times = sorted(float(t) for t in module_times)
    human_times = sorted(float(t) for t in human_times)
    unmatched = list(human_times)
    tp = 0
    for t in module_times:
        best, best_d = None, tolerance
        for i, h in enumerate(unmatched):
            d = abs(t - h)
            if d <= best_d:
                best, best_d = i, d
        if best is not None:
            unmatched.pop(best)
            tp += 1
    fp = len(module_times) - tp
    fn = len(unmatched)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tolerance": tolerance, "matched": tp, "spurious": fp, "missed": fn,
            "precision": precision, "recall": recall, "f1": f1}


def categorical_agreement(module_labels, human_labels):
    """Confusion matrix plus per-class rates. Overall accuracy alone hides a
    class that fails completely when it is rare."""
    labels = sorted(set(map(str, module_labels)) | set(map(str, human_labels)))
    index = {l: i for i, l in enumerate(labels)}
    matrix = np.zeros((len(labels), len(labels)), dtype=int)
    for m, h in zip(module_labels, human_labels):
        matrix[index[str(h)], index[str(m)]] += 1     # rows = human truth
    per_class = {}
    for l in labels:
        i = index[l]
        tp = int(matrix[i, i]); fn = int(matrix[i].sum() - tp)
        fp = int(matrix[:, i].sum() - tp)
        per_class[l] = {
            "n_true": int(matrix[i].sum()),
            "recall": tp / (tp + fn) if (tp + fn) else 0.0,
            "precision": tp / (tp + fp) if (tp + fp) else 0.0}
    total = int(matrix.sum())
    return {"labels": labels, "matrix": matrix.tolist(),
            "overall_accuracy": float(np.trace(matrix) / total) if total else 0.0,
            "per_class": per_class,
            "note": ("Per-class rates matter more than overall accuracy: a "
                     "rare class can fail completely while accuracy stays "
                     "high.")}


def validate_against_legacy(ledger, dataset_id, module_name, module_version,
                            agreement_result, allow_contaminated=False):
    """Attach an agreement result to a legacy dataset, refusing if that
    dataset has already been used to tune this module.

    Once a dataset has tuned anything, any agreement number from it is
    optimistically biased. Tracking that per dataset per module is what
    stops it happening by accident.
    """
    if not ledger.is_held_out_for(dataset_id, module_name) and not allow_contaminated:
        used = [r for r in ledger.uses(dataset_id, module_name)
                if r["role"] == TUNING]
        raise CalibrationError(
            f"'{dataset_id}' has already been used to TUNE {module_name} "
            f"({len(used)} recorded use(s)). An agreement number from it is "
            f"optimistically biased and is not technical validation. Use a "
            f"dataset this module has never seen, or pass "
            f"allow_contaminated=True and report it as such.")
    ledger.record_use(dataset_id, module_name, module_version, HELD_OUT,
                      note="agreement analysis")
    dataset = ledger.get(dataset_id)
    result = {
        "dataset_id": dataset_id, "module_name": module_name,
        "module_version": module_version,
        "held_out": not allow_contaminated,
        "agreement": agreement_result,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    ceiling = dataset.get("inter_scorer_agreement")
    if ceiling is not None:
        result["inter_scorer_ceiling"] = ceiling
        result["ceiling_note"] = (
            f"Two humans agreed at {ceiling:.2f} on this dataset. A module "
            f"disagreeing at about that rate is not evidence the module is "
            f"wrong - it is at the ceiling the ground truth itself sets.")
    elif dataset.get("double_scored") is None:
        result["ceiling_note"] = (
            "This dataset was never double-scored, so scorer-to-scorer "
            "variability is UNKNOWN rather than zero. The achievable "
            "agreement ceiling cannot be stated.")
    return result


# ---------------------------------------------------------------------------
# 6. Training-set curation, kept separate on purpose
# ---------------------------------------------------------------------------
def curation_split(items, session_key="session", train_fraction=0.7, seed=0):
    """Split by SESSION, never by frame.

    Frames from one animal are not independent examples, for the same
    reason repeated frames are not independent N in a behavioural analysis.
    Splitting by frame puts near-duplicates on both sides and badly
    overestimates generalisation.
    """
    import random
    sessions = sorted({str(i.get(session_key)) for i in items})
    if len(sessions) < 2:
        raise CalibrationError(
            f"Only {len(sessions)} distinct '{session_key}' value(s). A split "
            "by session is impossible, and splitting by item would put frames "
            "from the same animal on both sides.")
    rng = random.Random(seed)
    shuffled = sessions[:]
    rng.shuffle(shuffled)
    cut = max(1, int(round(len(shuffled) * train_fraction)))
    cut = min(cut, len(shuffled) - 1)          # never leave the test side empty
    train_sessions = set(shuffled[:cut])
    train = [i for i in items if str(i.get(session_key)) in train_sessions]
    test = [i for i in items if str(i.get(session_key)) not in train_sessions]
    return {"train": train, "test": test,
            "train_sessions": sorted(train_sessions),
            "test_sessions": sorted(set(shuffled[cut:]))}


def coverage_report(items, session_key="session", condition_keys=("strain",)):
    """Size AND breadth. Ten thousand frames from three sessions is a weaker
    training pool than a thousand from thirty, and only coverage shows it."""
    sessions = {str(i.get(session_key)) for i in items}
    report = {"n_items": len(items), "n_sessions": len(sessions),
              "items_per_session": len(items) / len(sessions) if sessions else 0}
    for key in condition_keys:
        values = {str(i.get(key)) for i in items if i.get(key) is not None}
        report[f"n_{key}"] = len(values)
        report[f"{key}_values"] = sorted(values)
    report["note"] = (
        f"{len(items)} items across {len(sessions)} session(s). Breadth "
        f"matters more than total count: items from few sessions are highly "
        f"correlated and will overstate generalisation.")
    return report
