from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "tools" / "morphology"),
    str(ROOT / "tools" / "pharynx_morphometry")]

from nonstriated_morphology import MODES
from pharynx import DAMAGE_DEFINITION


def test_pharynx_is_existing_tissue_mode_with_distinct_features():
    assert "pharynx" in MODES
    assert "grinder_integrity" in DAMAGE_DEFINITION
    assert "radial_myofilament_disorganization" in DAMAGE_DEFINITION


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'reconciliation - pharynx mode'))
