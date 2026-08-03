"""The auto-update path: apply, revert, refuse.

Converted from pytest to the plain runner every other suite here uses. That
is not cosmetic - these six checks had never executed. The file imported
`app.updater`, which only resolves with the repo root on sys.path, and every
case took a `tmp_path` fixture with no main block, so running it as a script
defined six functions and called none of them, then exited 0. A green tick
for nothing, on the code that ships releases to the lab.

Deliberately no pytest: this venv is what Setup_Lab_Tools.bat builds on every
lab machine, and a test framework has no business in a student runtime.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from updater import ApplicationUpdater, UpdateError     # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def _app(path, version):
    (path / "app").mkdir(parents=True)
    (path / "app" / "lab_hub.py").write_text(version)
    (path / "app" / "release_info.json").write_text(json.dumps(
        {"app_version": version, "runtime_version": "1.0.0"}))


def _package(source_dir, payload_root, name):
    """Build a real update zip and return it with its true checksum."""
    package = source_dir / name
    with zipfile.ZipFile(package, "w") as archive:
        for item in payload_root.rglob("*"):
            if item.is_file():
                archive.write(item,
                              Path("LabTools") / item.relative_to(payload_root))
    return package, hashlib.sha256(package.read_bytes()).hexdigest()


print("updater - regression\n")
tmp = Path(tempfile.mkdtemp())
try:
    # ------------------------------------------------------------------
    # 1. Applying an update, and undoing it, are both all-or-nothing
    # ------------------------------------------------------------------
    case = tmp / "atomic"
    root = case / "AGVGLab"
    app = root / "LabTools"
    _app(app, "11.5")
    (root / "version.json").write_text(json.dumps({
        "installed_app_version": "11.5", "installed_runtime_version": "1.0.0"}))
    source = case / "updates"
    source.mkdir(parents=True)
    payload = case / "payload" / "LabTools"
    _app(payload, "11.6")
    package, digest = _package(source, payload, "NIKE_App_Update_v11.6.zip")
    manifest = {"app_version": "11.6", "package_filename": package.name,
                "package_sha256": digest, "min_runtime_version": "1.0.0"}

    updater = ApplicationUpdater(app, root, source)
    updater.apply(manifest)
    check("a verified update replaces the installed app",
          (app / "app" / "lab_hub.py").read_text() == "11.6",
          (app / "app" / "lab_hub.py").read_text())
    updater.revert()
    check("and revert puts the previous version back, so a bad release is "
          "recoverable without a reinstall",
          (app / "app" / "lab_hub.py").read_text() == "11.5",
          (app / "app" / "lab_hub.py").read_text())

    # ------------------------------------------------------------------
    # 2. No update source, and a runtime the package outgrew
    # ------------------------------------------------------------------
    case = tmp / "gate"
    app = case / "root" / "LabTools"
    _app(app, "11.5")
    updater = ApplicationUpdater(app, app.parent, case / "absent")
    check("an unreachable update folder reports 'nothing to do' rather than "
          "raising at a student mid-experiment", updater.check() is None)
    try:
        updater.apply({"app_version": "11.6", "package_filename": "x.zip",
                       "package_sha256": "0", "min_runtime_version": "2.0.0"})
        check("a package needing a newer runtime is refused", False)
    except UpdateError as error:
        check("a package needing a newer runtime is refused", True)
        check("and names Setup_Lab_Tools.bat, the only thing that would "
              "actually fix it - the updater never runs pip",
              "Setup_Lab_Tools.bat" in str(error), str(error))
        check("and states both versions, so it is clear which machine is "
              "behind", "2.0.0" in str(error) and "1.0.0" in str(error),
              str(error))

    # ------------------------------------------------------------------
    # 3. A corrupt download must never touch the working install
    # ------------------------------------------------------------------
    case = tmp / "checksum"
    root = case / "root"
    app = root / "LabTools"
    _app(app, "11.5")
    source = case / "updates"
    source.mkdir(parents=True)
    (source / "bad.zip").write_bytes(b"not a zip")
    updater = ApplicationUpdater(app, root, source)
    try:
        updater.apply({"app_version": "11.6", "package_filename": "bad.zip",
                       "package_sha256": "0" * 64, "min_runtime_version": "0"})
        check("a package whose checksum does not match is refused", False)
    except UpdateError:
        check("a package whose checksum does not match is refused", True)
    check("and the working install is untouched - a failed update must not "
          "cost a student their tools",
          (app / "app" / "lab_hub.py").read_text() == "11.5",
          (app / "app" / "lab_hub.py").read_text())

    # ------------------------------------------------------------------
    # 4. Shared L: distribution redirects instead of overwriting
    # ------------------------------------------------------------------
    case = tmp / "shared"
    root = case / "Lab Tools"
    old = root / "NIKE_Lab_Tools_v11.13_Current_Files"
    target = root / "NIKE_Lab_Tools_v11.14_Current_Files"
    _app(old, "11.13")
    _app(target, "11.14")
    updater = ApplicationUpdater(old, old.parent, case / "updates")
    redirected = updater.apply({"app_version": "11.14"})
    check("on the shared drive an update REDIRECTS to the published folder",
          redirected == target, redirected)
    check("leaving both versions in place, because someone else may be "
          "running the old one right now", old.is_dir() and target.is_dir())
    check("and without renaming anything into a .previous folder on a share",
          not (root / "LabTools.previous").exists())

    # ------------------------------------------------------------------
    # 5. A redirect to a folder that is not published yet
    # ------------------------------------------------------------------
    case = tmp / "unpublished"
    root = case / "Lab Tools"
    old = root / "NIKE_Lab_Tools_v11.13_Current_Files"
    _app(old, "11.13")
    updater = ApplicationUpdater(old, old.parent, case / "updates")
    try:
        updater.apply({"app_version": "11.14"})
        check("a redirect to a folder that does not exist yet is refused",
              False)
    except UpdateError as error:
        check("a redirect to a folder that does not exist yet is refused",
              True)
        check("and says so plainly - the release is announced but not copied",
              "not available yet" in str(error), str(error))
    check("the working copy survives that refusal", old.is_dir())

    # ------------------------------------------------------------------
    # 6. A stale version.json beside a shared release must not win
    # ------------------------------------------------------------------
    case = tmp / "stale"
    root = case / "Lab Tools"
    current = root / "NIKE_Lab_Tools_v11.13_Current_Files"
    _app(current, "11.13")
    root.joinpath("version.json").write_text(json.dumps({
        "installed_app_version": "11.12",
        "installed_runtime_version": "1.0.0"}))
    source = root / "updates"
    source.mkdir()
    source.joinpath("update_manifest.json").write_text(json.dumps({
        "app_version": "11.13", "package_filename": "unused.zip",
        "package_sha256": "0" * 64, "min_runtime_version": "0.0.0"}))
    updater = ApplicationUpdater(current, current.parent, source)
    check("the folder actually in use decides the installed version, not a "
          "stale version.json left in the parent",
          updater.local_versions()["installed_app_version"] == "11.13",
          updater.local_versions()["installed_app_version"])
    check("so a station already on the current release is not offered it "
          "again in a loop", updater.check() is None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("UPDATER_REGRESSION_PASS")
