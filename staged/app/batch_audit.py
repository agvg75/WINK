"""Batch audit: statistically sized, stratified acceptance sampling.

Shared machinery so any WINK module with a per-item confidence signal can
offer an unsupervised batch mode without inventing its own audit logic.

WHAT THIS IS FOR, AND WHAT IT IS NOT
-------------------------------------
The risk being caught is SYSTEMATIC failure, not random noise. Random error
averages out as a dataset grows; a detector that fails the same way every
time contrast is low, or two worms are close together, does not - it just
produces more confidently wrong output. That is why sampling here is
stratified by whatever tracks acquisition conditions (batch, session,
plate, strain) rather than drawn globally at random: a global sample can
miss a stratum that failed completely, if that stratum is small relative to
the whole dataset.

This is an ADDITIONAL mode, opted into explicitly. It does not replace
per-item review, and a stratum that passes its sample is not equivalent to
one a person looked at end to end - it is labelled "batch audited", which
is a weaker and different claim.

THE ACCEPTANCE MATH
-------------------
This is acceptance sampling: decide whether to accept a lot from a small
inspected sample. For a stratum of N items, with an acceptable quality
level `aql` (the maximum tolerable defect rate) and a confidence level
`alpha`, the sample size n is the smallest number such that if the stratum
really were defective at the AQL, seeing ZERO defects in n draws would have
probability <= alpha. Drawing is without replacement from a finite stratum,
so the distribution is hypergeometric, not binomial.

That gives a zero-defect (c = 0) plan: inspect n, and if even one is
rejected the WHOLE stratum escalates to full review. One confirmed defect
in a sample designed to contain none is evidence of a systematic problem in
that stratum, not a rounding error to be averaged into a dataset-wide rate.

A NOTE ON REUSING THE SAMPLE PLANNER
-------------------------------------
The spec asks that this reuse the Sample planner's validated statistical
core rather than building a second statistics stack. In practice the
planner (tools/power_analysis/) is an HTML/JS tool with no importable
Python core, so there is nothing to import. This module instead calls
scipy.stats.hypergeom directly - itself the validated implementation the
rest of WINK's statistics rely on - rather than hand-rolling the
distribution. If the planner ever grows a Python core, this is the place
that should switch to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

DEFAULT_AQL = 0.05
DEFAULT_ALPHA = 0.05

# Reviewer verdicts. "uncertain" counts as a FAILURE for the zero-defect
# rule: ambiguity is itself evidence the item needs full review, and
# treating it as a pass would quietly weaken the guarantee the sample size
# was computed to provide.
ACCEPT, REJECT, UNCERTAIN = "accept", "reject", "uncertain"
FAILING_DECISIONS = (REJECT, UNCERTAIN)


class BatchAuditError(RuntimeError):
    """The audit cannot be run as asked."""


def user_data_root():
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AGVGLab" / "quality"
    return Path.home() / ".agvg_lab_tools" / "quality"


# ---------------------------------------------------------------------------
# The interface a calling module must satisfy
# ---------------------------------------------------------------------------
@dataclass
class AuditItem:
    """One processed item offered for audit."""
    item_id: str
    confidence: float                 # 0..1, monotonic: higher = more trustworthy
    abstained: bool = False
    abstain_reason: str | None = None
    stratum_keys: dict = field(default_factory=dict)
    evidence_path: str | None = None
    module_name: str = ""
    module_version: str = ""

    def stratum_id(self):
        """Stable identity for the group this item belongs to."""
        parts = [f"{k}={self.stratum_keys[k]}" for k in sorted(self.stratum_keys)
                 if self.stratum_keys[k] not in (None, "")]
        return "|".join(parts)


def _validate_items(items):
    if not items:
        raise BatchAuditError("No items were supplied to audit.")
    for item in items:
        if not (0.0 <= float(item.confidence) <= 1.0):
            raise BatchAuditError(
                f"{item.item_id}: confidence {item.confidence} is outside 0..1. "
                "The contract requires a monotonic 0..1 score.")
    # A module with no stratum keys cannot be audited unsupervised. Falling
    # back to a global random sample here would silently discard the whole
    # point of stratification, so this refuses instead - the same principle
    # as a missing scale stopping an analysis rather than defaulting.
    without = [i.item_id for i in items if not i.stratum_id()]
    if without:
        raise BatchAuditError(
            f"{len(without)} item(s) carry no stratum keys "
            f"(e.g. {without[0]}). Unsupervised batch audit needs items "
            "grouped by something that tracks acquisition conditions - "
            "session, plate, batch, strain. Refusing rather than falling "
            "back to a global random sample, which could miss a stratum "
            "that failed completely.")


# ---------------------------------------------------------------------------
# acceptance sampling
# ---------------------------------------------------------------------------
def _p_zero_defects(population, defectives, sample):
    """P(no defective in `sample` draws) from a finite population."""
    if defectives <= 0:
        return 1.0
    if sample > population - defectives:
        return 0.0
    try:
        from scipy.stats import hypergeom
        return float(hypergeom.pmf(0, population, defectives, sample))
    except Exception:
        return (math.comb(population - defectives, sample)
                / math.comb(population, sample))


def required_sample_size(population, aql=DEFAULT_AQL, alpha=DEFAULT_ALPHA):
    """Smallest n whose zero-defect result rules out a defect rate >= `aql`.

    Returns n such that, if the stratum truly contained `aql` defectives,
    the chance of drawing n items and seeing none of them is <= `alpha`.
    """
    population = int(population)
    if population <= 0:
        raise BatchAuditError("Stratum size must be positive.")
    if not (0 < aql < 1):
        raise BatchAuditError("AQL must be between 0 and 1 (a defect rate).")
    if not (0 < alpha < 1):
        raise BatchAuditError("alpha must be between 0 and 1.")
    defectives = max(1, math.ceil(aql * population))
    if defectives >= population:
        return population
    for n in range(1, population + 1):
        if _p_zero_defects(population, defectives, n) <= alpha:
            return n
    return population        # even a full census cannot reach alpha


def detectable_defect_rate(population, sample, alpha=DEFAULT_ALPHA):
    """The reverse question: with a review budget of `sample` per stratum,
    what defect rate does a clean result actually rule out?

    Answers "is n per stratum good enough" without solving forward from an
    AQL target, which is how a review budget usually gets decided in
    practice.
    """
    population, sample = int(population), int(sample)
    if sample <= 0 or population <= 0:
        raise BatchAuditError("Population and sample must be positive.")
    sample = min(sample, population)
    for defectives in range(1, population + 1):
        if _p_zero_defects(population, defectives, sample) <= alpha:
            return defectives / population
    return 1.0


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------
@dataclass
class StratumPlan:
    stratum_id: str
    population: int                  # eligible (non-abstained) items
    sample_size: int
    sample_item_ids: list
    abstained_item_ids: list
    aql: float
    alpha: float

    def summary(self):
        return (f"{self.stratum_id or '(all)'}: {self.population} eligible, "
                f"review {self.sample_size}"
                + (f", {len(self.abstained_item_ids)} abstained -> full review"
                   if self.abstained_item_ids else ""))


def plan_audit(items, aql=DEFAULT_AQL, alpha=DEFAULT_ALPHA, seed=0):
    """Group items by stratum and size a zero-defect sample for each.

    Abstained items are excluded from the sampled population and routed
    straight to full review: the module already declined to stand behind
    them, and no confidence value can override that.
    """
    _validate_items(items)
    rng_state = int(seed)
    strata = {}
    for item in items:
        strata.setdefault(item.stratum_id(), []).append(item)

    plans = []
    for stratum_id in sorted(strata):
        members = strata[stratum_id]
        abstained = [i for i in members if i.abstained]
        eligible = [i for i in members if not i.abstained]
        if not eligible:
            plans.append(StratumPlan(
                stratum_id=stratum_id, population=0, sample_size=0,
                sample_item_ids=[], abstained_item_ids=[i.item_id for i in abstained],
                aql=aql, alpha=alpha))
            continue
        n = required_sample_size(len(eligible), aql, alpha)
        # Representative draw, NOT a confidence-ranked or cherry-picked one:
        # the acceptance math assumes the sample stands for its stratum.
        # Training-set curation deliberately oversamples hard cases and must
        # therefore be a separate pass over the same items, never this one.
        import random
        rng = random.Random(f"{rng_state}:{stratum_id}")
        chosen = rng.sample(eligible, n)
        plans.append(StratumPlan(
            stratum_id=stratum_id, population=len(eligible), sample_size=n,
            sample_item_ids=[i.item_id for i in chosen],
            abstained_item_ids=[i.item_id for i in abstained],
            aql=aql, alpha=alpha))
    return plans


# ---------------------------------------------------------------------------
# outcome
# ---------------------------------------------------------------------------
@dataclass
class StratumOutcome:
    stratum_id: str
    accepted: bool
    reviewed: int
    failures: int
    failing_item_ids: list
    escalated_population: int
    aql: float
    alpha: float
    reason: str


def evaluate_stratum(plan, decisions):
    """Apply the zero-defect rule to one stratum's reviewed sample.

    `decisions` maps item_id -> accept / reject / uncertain.

    Any failure escalates the stratum's ENTIRE auto-accepted output to full
    review. The stratum's error rate is deliberately not averaged into a
    dataset-wide number: one defect in a sample designed to contain none is
    evidence the failure is systematic to this stratum, which pooling would
    dilute away.
    """
    missing = [i for i in plan.sample_item_ids if i not in decisions]
    if missing:
        raise BatchAuditError(
            f"{len(missing)} sampled item(s) in stratum "
            f"'{plan.stratum_id}' have no reviewer decision yet "
            f"(e.g. {missing[0]}).")
    failing = [i for i in plan.sample_item_ids
               if decisions[i] in FAILING_DECISIONS]
    if failing:
        return StratumOutcome(
            stratum_id=plan.stratum_id, accepted=False,
            reviewed=plan.sample_size, failures=len(failing),
            failing_item_ids=failing, escalated_population=plan.population,
            aql=plan.aql, alpha=plan.alpha,
            reason=(f"{len(failing)} of {plan.sample_size} reviewed items did "
                    f"not pass. The sample was sized to contain zero failures "
                    f"if the true defect rate were below {plan.aql:.1%}, so "
                    f"this is evidence of a systematic problem in this "
                    f"stratum. All {plan.population} auto-accepted items here "
                    f"go to full review."))
    return StratumOutcome(
        stratum_id=plan.stratum_id, accepted=True,
        reviewed=plan.sample_size, failures=0, failing_item_ids=[],
        escalated_population=0, aql=plan.aql, alpha=plan.alpha,
        reason=(f"All {plan.sample_size} reviewed items passed. A defect rate "
                f"of {plan.aql:.1%} or worse would have produced at least one "
                f"failure with probability {1 - plan.alpha:.0%}. Accepted as "
                f"BATCH AUDITED, which is a weaker claim than full per-item "
                f"review."))


def methods_summary(plans, outcomes, module_name, module_version,
                    confidence_definition):
    """The minimum a methods section must state for a batch-audited dataset."""
    accepted = [o for o in outcomes if o.accepted]
    escalated = [o for o in outcomes if not o.accepted]
    return {
        "status": "batch_audited",
        "module_name": module_name,
        "module_version": module_version,
        "confidence_definition": confidence_definition,
        "aql": plans[0].aql if plans else None,
        "alpha": plans[0].alpha if plans else None,
        "n_strata": len(plans),
        "n_strata_accepted": len(accepted),
        "n_strata_escalated": len(escalated),
        "sample_sizes_per_stratum": {p.stratum_id: p.sample_size for p in plans},
        "eligible_per_stratum": {p.stratum_id: p.population for p in plans},
        "abstained_per_stratum": {p.stratum_id: len(p.abstained_item_ids)
                                  for p in plans},
        "items_escalated": sum(o.escalated_population for o in escalated),
        "caveat": ("Batch audited is not equivalent to full per-item human "
                   "review. It states that every stratum either passed a "
                   "statistically sized zero-defect acceptance sample or was "
                   "escalated to full review."),
    }


# ---------------------------------------------------------------------------
# append-only log
# ---------------------------------------------------------------------------
@dataclass
class AuditLog:
    root: Path = field(default_factory=lambda: user_data_root() / "batch_audit")

    def __post_init__(self):
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self):
        return self.root / f"{datetime.now().date().isoformat()}_batch_audit.jsonl"

    def record(self, item, plan, decision=None, sampled=False):
        """One line per item considered.

        Confidence is stored beside the reviewer's verdict deliberately:
        that pairing is what later lets a module's confidence score be
        checked for calibration, and the auto-accept threshold moved off an
        arbitrary default onto a measured error rate. Building that analysis
        is a separate job - this only has to capture what it will need.
        """
        payload = {
            "schema_version": 1,
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "module_name": item.module_name,
            "module_version": item.module_version,
            "item_id": item.item_id,
            "stratum_id": plan.stratum_id,
            "stratum_keys": item.stratum_keys,
            "confidence": float(item.confidence),
            "abstained": bool(item.abstained),
            "abstain_reason": item.abstain_reason,
            "in_audit_sample": bool(sampled),
            "reviewer_decision": decision,
            "aql": plan.aql,
            "alpha": plan.alpha,
            "stratum_population": plan.population,
            "stratum_sample_size": plan.sample_size,
            "evidence_path": item.evidence_path,
        }
        with self._path().open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")
        return self._path()

    def read_all(self):
        rows = []
        for path in sorted(self.root.glob("*_batch_audit.jsonl")):
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        return rows
