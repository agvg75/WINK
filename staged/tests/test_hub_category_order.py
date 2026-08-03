import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from lab_hub import CATEGORY_ORDER, REGISTRY, group_tools_by_category


def test_hub_categories_follow_scientific_workflow_order():
    sections = group_tools_by_category()

    assert list(sections) == CATEGORY_ORDER
    assert sum(len(tools) for tools in sections.values()) == len(REGISTRY)


def test_new_categories_are_appended_without_reordering_known_categories():
    sample_type = type(REGISTRY[0])
    future_tool = sample_type(
        name="Future tool",
        desc="Test-only future category.",
        section="Future category",
        kind="python",
        status="coming",
        filename="future_tool.py",
    )

    sections = group_tools_by_category([*REGISTRY, future_tool])

    assert list(sections)[:-1] == CATEGORY_ORDER
    assert list(sections)[-1] == "Future category"
    assert sections["Future category"] == [future_tool]


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'hub category order'))
