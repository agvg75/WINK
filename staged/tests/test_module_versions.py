"""Per-module effective versions: file-set derivation and attribution.

The failure mode this suite is aimed at is SILENT AND ONE-DIRECTIONAL. A file
set that is too narrow reports "your tool did not change" about a release that
changed it, and nothing about that answer looks wrong. So the tests care most
about edges that could go missing: transitive imports, launched scripts, and
the honest admission when a dynamic import makes the set unknowable.

They run entirely on synthetic trees. The real index lives on L: and is built
from 22 published folders; a test that walked it would be measuring the share.
"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import module_versions as mv                       # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


print("module versions - file sets and attribution\n")

tmp = Path(tempfile.mkdtemp(prefix="wink_modver_"))
real_tree = mv.TREE
mv.TREE = tmp
try:
    # ------------------------------------------------------- transitive walk
    write(tmp, "app/shared.py", "import deeper\n")
    write(tmp, "app/deeper.py", "VALUE = 1\n")
    write(tmp, "app/untouched.py", "VALUE = 2\n")
    entry = write(tmp, "tools/thing/tool.py",
                  "import shared\nimport numpy\nfrom helper import go\n")
    write(tmp, "tools/thing/helper.py", "def go(): pass\n")

    files, dynamic = mv.module_files(entry)
    check("a module's own script is in its file set",
          "tools/thing/tool.py" in files)
    check("a sibling imported by bare name resolves against the script's own "
          "directory", "tools/thing/helper.py" in files)
    check("an app/ import resolves", "app/shared.py" in files)
    check("imports are followed TRANSITIVELY - the thing shared imports counts "
          "too, because a change there changes this tool", "app/deeper.py" in files)
    check("an app/ module this tool does NOT import is excluded; a shared file "
          "it never loads cannot change its behaviour",
          "app/untouched.py" not in files)
    check("third-party imports resolve to nothing and are not an uncertainty - "
          "no release of ours can change numpy",
          not any("numpy" in f for f in files), sorted(files))
    check("no dynamic-import flag when there is no dynamic import", not dynamic)

    # -------------------------------------------------- the launch edge
    # A tool that starts another script depends on it. No import says so.
    write(tmp, "tools/thing/worker.py", "print('work')\n")
    write(tmp, "tools/thing/never_run.py", "print('not launched')\n")
    launcher = write(tmp, "tools/thing/launcher.py",
                     'import subprocess\n'
                     'def go():\n'
                     '    """Fails like tools/thing/never_run.py does."""\n'
                     '    # see tools/thing/never_run.py for the old way\n'
                     '    subprocess.Popen(["python", "tools/thing/worker.py"])\n')
    files, _ = mv.module_files(launcher)
    check("a script started via subprocess IS a dependency, though no import "
          "statement names it", "tools/thing/worker.py" in files)
    check("a .py filename mentioned only in a docstring or comment is NOT a "
          "dependency - the first draft treated every .py string as an edge, "
          "pulled in the Hub, and inflated every tool to 40 files",
          "tools/thing/never_run.py" not in files, sorted(files))

    # ----------------------------------------------------- dynamic imports
    dyn = write(tmp, "tools/thing/dyn.py",
                "import importlib\n"
                "def load(n): return importlib.import_module(n)\n")
    _, dynamic = mv.module_files(dyn)
    check("a dynamic import is DETECTED, so the module can say its file set is "
          "incomplete instead of reporting a confident wrong answer",
          "tools/thing/dyn.py" in dynamic, sorted(dynamic))

    # ------------------------------------------------------- own vs shared
    files, _ = mv.module_files(entry)
    own, shared = mv.split_own_shared(files, entry)
    check("own code is the tool's own directory", "tools/thing/helper.py" in own)
    check("shared code is everything else", "app/shared.py" in shared)
    check("own and shared partition the set with nothing lost or doubled",
          own | shared == set(files) and not (own & shared))

    # -------------------------------------------------------- attribution
    index = {
        "11.100": {"a.py": "h1", "b.py": "h1"},
        "11.101": {"a.py": "h2", "b.py": "h1"},   # a changed
        "11.102": {"a.py": "h2", "b.py": "h2"},   # b changed
        "11.103": {"a.py": "h2", "b.py": "h2"},   # nothing changed
    }
    check("the OLDEST version is reported as changing nothing, not everything - "
          "otherwise every module dates to wherever our records happen to start",
          mv.changed_in(index, "11.100") == set())
    check("a version that changed one file reports exactly that file",
          mv.changed_in(index, "11.101") == {"a.py"})
    check("a version that changed nothing reports nothing",
          mv.changed_in(index, "11.103") == set())

    version, history = mv.effective_version({"a.py"}, index)
    check("effective version is the NEWEST release that touched this file set, "
          "not the newest release", version == "11.101", version)
    check("versions where the module did not differ are absent from the "
          "picker - a list of every release is noise",
          [h[0] for h in history] == ["11.101"], [h[0] for h in history])

    version, history = mv.effective_version({"a.py", "b.py"}, index)
    check("a wider file set moves the effective version forward",
          version == "11.102", version)

    version, _ = mv.effective_version({"never_touched.py"}, index)
    check("a file set nothing ever touched yields no version rather than a "
          "guess", version is None, str(version))

    _, history = mv.effective_version({"a.py", "b.py"}, index, own={"b.py"})
    counts = {h[0]: (h[1], h[2]) for h in history}
    check("own and shared changes are counted separately, because 'shared code "
          "changed' and 'this tool's code changed' deserve different suspicion",
          counts == {"11.101": (0, 1), "11.102": (1, 0)}, counts)

    # ------------------------------------------------ the missing share
    check("an unreachable publish share yields no versions rather than raising "
          "- a tool must still start when L: is down",
          mv.published_trees(tmp / "nope") == [])
finally:
    mv.TREE = real_tree

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MODULE_VERSIONS_PASS")
