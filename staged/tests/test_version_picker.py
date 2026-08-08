"""The version picker's core: what it offers and what it would run.

No Tk. The dialog is a thin shell over `offer` and `launch_command`, and those
are where the decisions live: which versions appear, what this user is told
about each, and - the one with teeth - that opening an old version runs THAT
TREE'S copy of the script, never the current one.
"""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import launch_history as lh                         # noqa: E402
import module_versions as mv                        # noqa: E402
import version_picker as vp                         # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("version picker - what is offered and what would run\n")

tmp = Path(tempfile.mkdtemp(prefix="wink_picker_"))
share = tmp / "share"

# Three published trees, each holding its own copy of the same tool.
for version, body, note in (("11.130", "V130", "kinematics fixes"),
                            ("11.136", "V136", "cell calcium"),
                            ("11.138", "V138", "population analysis")):
    tree = share / f"WINK_Lab_Tools_v{version}_Current_Files"
    (tree / "tools" / "egg").mkdir(parents=True, exist_ok=True)
    (tree / "tools" / "egg" / "egg_tool.py").write_text(
        f"MARKER = '{body}'\n", encoding="utf-8")
    (tree / "app").mkdir(parents=True, exist_ok=True)
    (tree / "app" / "release_info.json").write_text(json.dumps({
        "app_version": version, "published_utc": f"2026-0{version[-1]}-01T00:00:00+00:00",
        "note": note}), encoding="utf-8")

check("published trees are found and ordered oldest first",
      [v for v, _p in mv.published_trees(share)] == ["11.130", "11.136", "11.138"])

when, note = vp.release_note("11.136", root=share)
check("a release's date and one-line note come from its own manifest",
      when == "2026-06-01" and note == "cell calcium", f"{when} {note}")
check("a version with no tree yields blanks rather than a guess",
      vp.release_note("9.99", root=share) == ("", ""))

# ---------------------------------------------------------- what is offered
index = {
    "11.130": {"tools/egg/egg_tool.py": "a", "app/shared.py": "s1"},
    "11.132": {"tools/egg/egg_tool.py": "a", "app/shared.py": "s1"},
    "11.136": {"tools/egg/egg_tool.py": "a", "app/shared.py": "s2"},
    "11.138": {"tools/egg/egg_tool.py": "b", "app/shared.py": "s2"},
}
store = lh.LaunchHistory(tmp / "user")
real_tree = mv.TREE
mv.TREE = tmp / "work"
try:
    (mv.TREE / "tools" / "egg").mkdir(parents=True, exist_ok=True)
    (mv.TREE / "app").mkdir(parents=True, exist_ok=True)
    (mv.TREE / "app" / "shared.py").write_text("X = 1\n", encoding="utf-8")
    (mv.TREE / "tools" / "egg" / "egg_tool.py").write_text(
        "import shared\n", encoding="utf-8")

    data = vp.offer("Egg counter", "tools/egg/egg_tool.py", index=index,
                    history=store, root=share)
    offered = [row["version"] for row in data["rows"]]
    check("ONLY versions where this module differed are offered; 11.132 "
          "changed nothing it depends on and is absent",
          offered == ["11.138", "11.136"], offered)
    check("the newest such version is the effective version",
          data["effective"] == "11.138", data["effective"])
    by_version = {row["version"]: row for row in data["rows"]}
    check("a release that changed the tool's own code says so",
          by_version["11.138"]["changed"] == "this tool's own code")
    check("a release that only changed shared code says THAT instead - the "
          "two deserve different suspicion",
          by_version["11.136"]["changed"] == "shared code it depends on")
    check("each offered version carries its date and note, so the list can be "
          "read without opening anything",
          by_version["11.136"]["note"] == "cell calcium"
          and by_version["11.136"]["when"] == "2026-06-01")

    # ------------------------------------------------ this user's own history
    check("with no history, every version reads as never used by you",
          all(row["your_history"] in ("never used by you", "current")
              for row in data["rows"]),
          [r["your_history"] for r in data["rows"]])
    check("and no revert is suggested when nothing has ever worked for this "
          "user", data["revert_to"] is None)

    first = store.record_launch("Egg counter", "11.136")
    store.record_outcome(first, lh.CLEAN)
    second = store.record_launch("Egg counter", "11.138")
    store.record_outcome(second, lh.CRASH, "boom")
    data = vp.offer("Egg counter", "tools/egg/egg_tool.py", index=index,
                    history=store, current="11.138", root=share)
    by_version = {row["version"]: row for row in data["rows"]}
    check("the version in use is marked current",
          by_version["11.138"]["your_history"] == "current")
    check("a version with a clean session for this user says when",
          by_version["11.136"]["your_history"].startswith("last clean session"),
          by_version["11.136"]["your_history"])
    check("revert suggests the user's own last clean version",
          data["revert_to"] == "11.136", data["revert_to"])

    # ------------------------------------------------------------- pins
    check("no pin reported when none is set", data["pinned"] is None)
    store.pin("Egg counter", "11.136")
    data = vp.offer("Egg counter", "tools/egg/egg_tool.py", index=index,
                    history=store, root=share)
    check("a pin is surfaced so the student can see why they are not on the "
          "newest release", data["pinned"] == "11.136", data["pinned"])
finally:
    mv.TREE = real_tree

# --------------------------------------------------- what would actually run
command = vp.launch_command("11.130", "tools/egg/egg_tool.py", root=share)
check("a launch command is produced for a published version", command is not None)
argv, cwd = command
script = Path(argv[-1])
check("IT RUNS THAT TREE'S OWN COPY OF THE SCRIPT - the whole point. A module "
      "from one release against core files from another is a configuration "
      "nobody has tested",
      script.read_text(encoding="utf-8").strip() == "MARKER = 'V130'",
      script.read_text(encoding="utf-8").strip())
check("and the working directory is inside that tree, so its imports resolve "
      "there too", Path(cwd) == script.parent, cwd)
check("v11.138's command runs v11.138's copy, not v11.130's",
      Path(vp.launch_command("11.138", "tools/egg/egg_tool.py",
                             root=share)[0][-1]
           ).read_text(encoding="utf-8").strip() == "MARKER = 'V138'")

check("a version that is not on the share yields no command rather than "
      "running something else",
      vp.launch_command("9.99", "tools/egg/egg_tool.py", root=share) is None)
check("a version whose tree lacks this tool yields no command",
      vp.launch_command("11.130", "tools/nope/absent.py", root=share) is None)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("VERSION_PICKER_PASS")
