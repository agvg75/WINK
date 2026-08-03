from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "afd_neuron")]

from neuron_tracker import NeuronTracker


def test_neuron_tracker_refuses_zero_scale_before_background_work():
    frames = np.zeros((3, 16, 16), dtype=np.float32)
    try:
        NeuronTracker(frames, fps=30, um_per_px=0, exposure_ms=10)
    except ValueError as exc:
        assert "um_per_px" in str(exc)
    else:
        raise AssertionError("Zero scale was accepted.")


def test_neuron_tracker_keeps_float32_input_without_source_copy():
    frames = np.zeros((3, 16, 16), dtype=np.float32)
    tracker = NeuronTracker(
        frames, fps=30, um_per_px=1.0, exposure_ms=10)
    assert tracker.G is frames
    assert tracker.G.dtype == np.float32


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'imaging intake order'))
