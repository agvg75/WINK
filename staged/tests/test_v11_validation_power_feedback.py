from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "power_analysis")]
from run_feedback import RunFeedbackStore
from validation import publication_certification, stamp
from power import (prospective_linear, prospective_rayleigh,
                   retrospective_variance)


def test_only_publication_label_is_gated():
    s = stamp("tool", "1", "metric")
    result = publication_certification(s)
    assert result["status"] == "refused"
    assert "computational result remains available" in result["reason"]


def test_review_accuracy_has_real_versioned_denominator(tmp_path):
    store = RunFeedbackStore(tmp_path)
    for agreed in (True, True, False):
        store.record_review(
            tool_name="tracker", tool_version="1", run_id=str(agreed),
            agreed=agreed, condition={"density": "crowded"})
    store.record_review(
        tool_name="tracker", tool_version="2", run_id="new",
        agreed=True, condition={"density": "crowded"})
    rates = store.review_accuracy()
    old = [row for row in rates if row["tool_version"] == "1"][0]
    assert old["reviewed_denominator"] == 3
    assert abs(old["accuracy_rate"] - 2 / 3) < 1e-12
    assert len(rates) == 2


def test_power_linear_circular_refusal_and_retrospective():
    linear = prospective_linear(effect=2, variance=4)
    assert linear["independent_replicates_per_group"] == 16
    refused = prospective_linear(
        effect=2, variance=4, requested_n_unit="worm")
    assert refused["status"] == "refused"
    assert "pseudoreplication" in refused["reason"]
    circular = prospective_rayleigh(expected_resultant=.5)
    assert circular["independent_plates"] >= 3
    rows = [
        {"assay": "speed", "strain": "N2", "value": x,
         "tool_version": "1", "validation_level": "computational_regression"}
        for x in (1, 2, 3, 4)]
    result = retrospective_variance(rows, assay="speed", strain="N2")
    assert abs(result["estimates"][0]["plate_variance"] - 5 / 3) < 1e-12
    assert result["estimates"][0]["provisional"]
    rows.append({**rows[0], "tool_version": "2"})
    assert retrospective_variance(
        rows, assay="speed", strain="N2")["mixed_instrument_stream"]


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'v11 validation power feedback'))
