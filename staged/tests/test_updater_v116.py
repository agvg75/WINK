import hashlib
import json
from pathlib import Path
import zipfile

from app.updater import ApplicationUpdater, UpdateError


def _app(path, version):
    (path / "app").mkdir(parents=True)
    (path / "app" / "lab_hub.py").write_text(version)
    (path / "app" / "release_info.json").write_text(json.dumps(
        {"app_version": version, "runtime_version": "1.0.0"}))


def test_update_and_revert_are_atomic(tmp_path):
    root = tmp_path / "AGVGLab"
    app = root / "LabTools"
    _app(app, "11.5")
    (root / "version.json").write_text(json.dumps({
        "installed_app_version": "11.5", "installed_runtime_version": "1.0.0"}))
    source = tmp_path / "updates"
    payload = tmp_path / "payload" / "LabTools"
    _app(payload, "11.6")
    source.mkdir()
    package = source / "NIKE_App_Update_v11.6.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for item in payload.rglob("*"):
            if item.is_file():
                archive.write(item, Path("LabTools") / item.relative_to(payload))
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    manifest = {"app_version": "11.6", "package_filename": package.name,
                "package_sha256": digest, "min_runtime_version": "1.0.0"}
    updater = ApplicationUpdater(app, root, source)
    updater.apply(manifest)
    assert (app / "app" / "lab_hub.py").read_text() == "11.6"
    updater.revert()
    assert (app / "app" / "lab_hub.py").read_text() == "11.5"


def test_unreachable_and_runtime_gate(tmp_path):
    app = tmp_path / "root" / "LabTools"
    _app(app, "11.5")
    updater = ApplicationUpdater(app, app.parent, tmp_path / "absent")
    assert updater.check() is None
    try:
        updater.apply({"app_version": "11.6", "package_filename": "x.zip",
                       "package_sha256": "0", "min_runtime_version": "2.0.0"})
    except UpdateError as error:
        assert "full installer" in str(error)
    else:
        raise AssertionError("runtime mismatch was accepted")


def test_checksum_failure_preserves_application(tmp_path):
    root = tmp_path / "root"
    app = root / "LabTools"
    _app(app, "11.5")
    source = tmp_path / "updates"
    source.mkdir()
    (source / "bad.zip").write_bytes(b"not a zip")
    updater = ApplicationUpdater(app, root, source)
    try:
        updater.apply({"app_version": "11.6", "package_filename": "bad.zip",
                       "package_sha256": "0" * 64,
                       "min_runtime_version": "0"})
    except UpdateError:
        pass
    else:
        raise AssertionError("bad checksum was accepted")
    assert (app / "app" / "lab_hub.py").read_text() == "11.5"


def test_versioned_shared_distribution_redirects_without_rename(tmp_path):
    root = tmp_path / "Lab Tools"
    old = root / "NIKE_Lab_Tools_v11.13_Current_Files"
    target = root / "NIKE_Lab_Tools_v11.14_Current_Files"
    _app(old, "11.13")
    _app(target, "11.14")
    updater = ApplicationUpdater(old, old.parent, tmp_path / "updates")
    redirected = updater.apply({"app_version": "11.14"})
    assert redirected == target
    assert old.is_dir() and target.is_dir()
    assert not (root / "LabTools.previous").exists()


def test_shared_redirect_refuses_missing_published_folder(tmp_path):
    root = tmp_path / "Lab Tools"
    old = root / "NIKE_Lab_Tools_v11.13_Current_Files"
    _app(old, "11.13")
    updater = ApplicationUpdater(old, old.parent, tmp_path / "updates")
    try:
        updater.apply({"app_version": "11.14"})
    except UpdateError as error:
        assert "not available yet" in str(error)
    else:
        raise AssertionError("Missing shared release was accepted")
    assert old.is_dir()


def test_shared_release_ignores_stale_parent_version_file(tmp_path):
    root = tmp_path / "Lab Tools"
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
    assert updater.local_versions()["installed_app_version"] == "11.13"
    assert updater.check() is None
