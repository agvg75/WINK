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
