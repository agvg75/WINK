"""Prospective and retrospective power at the declared inferential unit."""
from __future__ import annotations

import math
import numpy as np
from scipy.stats import norm

TOOL_NAME = "power_analysis"
TOOL_VERSION = "1.0.0"


def _stamp(metric, inputs):
    return {
        "level": "computational_regression", "tool_name": TOOL_NAME,
        "tool_version": TOOL_VERSION, "metric": metric,
        "source_validation_stamps": inputs}


def prospective_linear(*, effect, variance, alpha=.05, power=.8,
                       groups=2, inferential_unit="plate",
                       population_mode=True, requested_n_unit="plate",
                       input_stamps=()):
    if population_mode and requested_n_unit == "worm":
        return {"status": "refused", "reason": (
            "Population assays use plate as the independent replicate. "
            "Worm-level power would be pseudoreplication.")}
    if effect <= 0 or variance < 0:
        raise ValueError("Effect must be positive and variance nonnegative.")
    z = norm.ppf(1 - alpha / 2) + norm.ppf(power)
    multiplier = 2 if groups == 2 else 1
    n = math.ceil(multiplier * z * z * variance / (effect * effect))
    return {
        "status": "complete", "test_family": (
            "two_group_plate_summary" if groups == 2
            else "one_sample_plate_summary"),
        "inferential_unit": inferential_unit,
        "independent_replicates_per_group": max(2, n),
        "validation_stamp": _stamp("prospective_replicate_count",
                                   list(input_stamps))}


def prospective_rayleigh(*, expected_resultant, alpha=.05, power=.8,
                         input_stamps=()):
    """Large-sample Rayleigh planning approximation, n*rho^2 noncentrality."""
    if not 0 < expected_resultant < 1:
        raise ValueError("Expected mean resultant must be between zero and one.")
    # Under H0, 2*n*Rbar^2 is approximately chi-square(2).
    critical = -2 * math.log(alpha)
    # Normal approximation to noncentral radial signal.
    n = math.ceil(
        ((math.sqrt(critical) + norm.ppf(power)) /
         (math.sqrt(2) * expected_resultant)) ** 2)
    return {
        "status": "complete", "test_family": "rayleigh_plate_angles",
        "inferential_unit": "plate",
        "independent_plates": max(3, n),
        "expected_mean_resultant": expected_resultant,
        "validation_stamp": _stamp("prospective_circular_replicate_count",
                                   list(input_stamps))}


def prospective_two_sample_circular(*, angular_effect_deg,
                                    concentration_kappa, alpha=.05,
                                    power=.8, input_stamps=(),
                                    simulations=400, seed=1729):
    """Monte-Carlo Watson U2 planning under two von Mises alternatives."""
    if angular_effect_deg <= 0 or concentration_kappa <= 0:
        raise ValueError("Angular effect and concentration must be positive.")
    rng = np.random.default_rng(seed)

    def watson_u2(a, b):
        a = np.mod(a, 2 * np.pi) / (2 * np.pi)
        b = np.mod(b, 2 * np.pi) / (2 * np.pi)
        pooled = np.sort(np.concatenate([a, b]))
        d = (np.searchsorted(np.sort(a), pooled, side="right") / len(a) -
             np.searchsorted(np.sort(b), pooled, side="right") / len(b))
        centered = d - np.mean(d)
        return len(a) * len(b) / (len(a) + len(b)) ** 2 * np.sum(
            centered * centered)

    delta = math.radians(angular_effect_deg)
    chosen = None
    achieved = None
    for n in range(4, 101):
        null = np.asarray([
            watson_u2(
                rng.vonmises(0, concentration_kappa, n),
                rng.vonmises(0, concentration_kappa, n))
            for _ in range(simulations)])
        critical = float(np.quantile(null, 1 - alpha))
        alternative = np.asarray([
            watson_u2(
                rng.vonmises(0, concentration_kappa, n),
                rng.vonmises(delta, concentration_kappa, n))
            for _ in range(simulations)])
        achieved = float(np.mean(alternative > critical))
        if achieved >= power:
            chosen = n
            break
    return {
        "status": "complete" if chosen is not None else "not_reached",
        "test_family": "two_sample_circular_watson_u2",
        "inferential_unit": "plate",
        "independent_plates_per_group": chosen,
        "estimated_power": achieved,
        "simulations_per_n": simulations, "random_seed": seed,
        "method_note": (
            "Monte Carlo planning under von Mises alternatives using the "
            "Watson U2 empirical-distribution statistic. Re-run with more "
            "simulations before publication."),
        "published_reference": (
            "Landler et al. 2021, Scientific Reports 11:20333, "
            "doi:10.1038/s41598-021-99299-5"),
        "validation_stamp": _stamp("prospective_circular_replicate_count",
                                   list(input_stamps))}


def retrospective_variance(rows, *, assay, strain, value_key="value"):
    selected = [r for r in rows if r.get("assay") == assay and
                r.get("strain") == strain]
    if len(selected) < 2:
        return {"status": "refused",
                "reason": "At least two independent plate summaries required."}
    versions = sorted({str(r.get("tool_version")) for r in selected})
    levels = sorted({str(r.get("validation_level")) for r in selected})
    mixed = len(versions) > 1 or len(levels) > 1
    groups = {}
    for row in selected:
        key = (str(row.get("tool_version")),
               str(row.get("validation_level")))
        groups.setdefault(key, []).append(float(row[value_key]))
    estimates = [{
        "tool_version": key[0], "validation_level": key[1],
        "n_plates": len(values),
        "plate_variance": (
            float(np.var(values, ddof=1)) if len(values) > 1 else None),
        "provisional": len(values) < 6,
        "small_stream_n_multiplier": (
            max(1.0, 6.0 / len(values)) if values else None)}
        for key, values in groups.items()]
    return {
        "status": "complete", "assay": assay, "strain": strain,
        "mixed_instrument_stream": mixed,
        "pooling_status": "flagged_do_not_pool" if mixed else "homogeneous",
        "estimates": estimates,
        "validation_stamp": _stamp(
            "retrospective_plate_variance",
            [{"level": level, "tool_version": version}
             for version, level in groups])}
