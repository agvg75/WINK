from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(ROOT / "tools" / "worm_kinematics" / "dic_tracker"))

from run_dic_kinematics import _require_positive_scale


class Dialog:
    def __init__(self, values):
        self.values = iter(values)

    def askfloat(self, *args, **kwargs):
        return next(self.values)


class Messages:
    def __init__(self):
        self.errors = []

    def showerror(self, title, message):
        self.errors.append((title, message))


def test_scale_cancel_refuses_before_loading():
    messages = Messages()
    assert _require_positive_scale(Dialog([None]), messages) is None


def test_scale_requires_positive_finite_value():
    messages = Messages()
    assert _require_positive_scale(Dialog([0, 2.5]), messages) == 2.5
    assert messages.errors
