"""Checksum-verified, application-only updater for the WINK shared folder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile
import re
import urllib.request
import urllib.error

DEFAULT_SOURCE = Path(r"L:\10_AGVG LAB\Lab Tools\updates")
GITHUB_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_UA = {"User-Agent": "WINK-Updater"}


def _version_tuple(value):
    return tuple(int(part) for part in str(value).split("."))


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={**_UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_text(url, timeout=15):
    req = urllib.request.Request(url, headers=dict(_UA))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8-sig")


def _http_download(url, dest, timeout=300):
    req = urllib.request.Request(url, headers={**_UA, "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


class UpdateError(RuntimeError):
    pass


class ApplicationUpdater:
    def __init__(self, app_root, install_root=None, source=DEFAULT_SOURCE,
                 github_repo=None):
        self.app_root = Path(app_root)
        self.install_root = Path(install_root or self.app_root.parent)
        self.source = Path(source)
        # Optional GitHub Releases fallback (e.g. "agvg75/WINK") for clients that
        # are not on the L: lab network. The L: source is tried first.
        self.github_repo = github_repo
        self._use_github = False
        self._github_assets = {}
        self.version_file = self.install_root / "version.json"
        self.backup = self.install_root / "LabTools.previous"

    def is_versioned_shared_distribution(self):
        # Accept both the current WINK_ naming and the historical NIKE_ naming so
        # clients launched from either published snapshot keep updating.
        return bool(re.fullmatch(
            r"(WINK|NIKE)_Lab_Tools_v[0-9.]+_Current_Files", self.app_root.name,
            flags=re.IGNORECASE))

    def shared_redirect_target(self, manifest):
        """Return an immutable published release instead of mutating an L-drive copy.

        Each version is published under both the WINK_ and (for the transition)
        the NIKE_ folder name; prefer WINK, fall back to NIKE, so a client running
        from either can still be redirected to the next release.
        """
        if not self.is_versioned_shared_distribution():
            return None
        last_missing = None
        for prefix in ("WINK", "NIKE"):
            target = self.app_root.parent / (
                f"{prefix}_Lab_Tools_v{manifest['app_version']}_Current_Files")
            info_path = target / "app" / "release_info.json"
            if not info_path.is_file():
                last_missing = target
                continue
            try:
                info = json.loads(info_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise UpdateError(
                    f"The published update folder has an invalid release stamp:\n{target}") from exc
            if str(info.get("app_version")) != str(manifest["app_version"]):
                raise UpdateError(
                    "The published folder version does not match the update manifest. "
                    "The existing Hub was not changed.")
            return target
        raise UpdateError(
            "The update is announced, but its published student folder is "
            f"not available yet:\n{last_missing}\n\nTry again later or contact the lab.")

    def local_versions(self):
        fallback = self.app_root / "app" / "release_info.json"
        installed = {}
        release = {}
        # A version.json beside several immutable shared releases is not an
        # installation record for any one release. Its stale 11.12 stamp caused
        # the v11.13 folder to offer v11.13 to itself.
        if self.version_file.is_file() and not self.is_versioned_shared_distribution():
            installed = json.loads(
                self.version_file.read_text(encoding="utf-8-sig"))
        if fallback.is_file():
            release = json.loads(fallback.read_text(encoding="utf-8-sig"))
        if not installed and not release:
            return {"installed_app_version": "0", "installed_runtime_version": "0"}
        runtime = installed.get("installed_runtime_version")
        if not runtime or str(runtime) == "0":
            runtime = release.get("runtime_version", "0")
        return {
            "installed_app_version": str(
                installed.get("installed_app_version",
                              release.get("app_version", "0"))),
            "installed_runtime_version": str(runtime)}

    def shared_manifest(self):
        path = self.source / "update_manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _github_manifest(self):
        """Latest GitHub release as a manifest dict, or None.

        The release must attach both ``update_manifest.json`` and the package
        zip as assets - the same two files the L: updater uses."""
        if not self.github_repo:
            return None
        try:
            release = _http_json(GITHUB_LATEST.format(repo=self.github_repo))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        assets = {a.get("name"): a.get("browser_download_url")
                  for a in release.get("assets", [])}
        manifest_url = assets.get("update_manifest.json")
        if not manifest_url:
            return None
        try:
            manifest = json.loads(_http_text(manifest_url))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        self._github_assets = assets
        self._use_github = True
        return manifest

    def check(self):
        manifest = None
        self._use_github = False
        try:
            manifest = self.shared_manifest()
        except OSError:
            manifest = None
        # Fall back to GitHub Releases when the L: source has nothing (off-network).
        if not manifest and self.github_repo:
            manifest = self._github_manifest()
        if not manifest:
            return None
        local = self.local_versions()
        if _version_tuple(manifest["app_version"]) <= _version_tuple(
                local["installed_app_version"]):
            return None
        return manifest

    def apply(self, manifest):
        # The L: shared-snapshot redirect only applies to L: clients, never to a
        # GitHub download.
        if not self._use_github:
            redirect = self.shared_redirect_target(manifest)
            if redirect is not None:
                return redirect
        local = self.local_versions()
        required_runtime = manifest.get("min_runtime_version", "0")
        if (_version_tuple(required_runtime) > (0,)
                and _version_tuple(local["installed_runtime_version"])
                < _version_tuple(required_runtime)):
            raise UpdateError(
                "This update requires a newer runtime. Run the full installer.")
        download_dir = None
        if self._use_github:
            url = self._github_assets.get(manifest["package_filename"])
            if not url:
                raise UpdateError(
                    "The GitHub release is missing its package asset: "
                    f"{manifest['package_filename']}")
            download_dir = Path(tempfile.mkdtemp(
                prefix="wink-dl-", dir=str(self.install_root)))
            package = download_dir / manifest["package_filename"]
            try:
                _http_download(url, package)
            except (urllib.error.URLError, OSError) as exc:
                shutil.rmtree(download_dir, ignore_errors=True)
                raise UpdateError(f"Could not download the update:\n{exc}") from exc
        else:
            package = self.source / manifest["package_filename"]
            if not package.is_file():
                raise UpdateError(f"Update package is missing: {package}")
        try:
            if _sha256(package).lower() != manifest["package_sha256"].lower():
                raise UpdateError("Update package checksum does not match the manifest.")
            staging_parent = Path(tempfile.mkdtemp(
                prefix="nike-update-", dir=str(self.install_root)))
            candidate = staging_parent / "LabTools"
            try:
                with zipfile.ZipFile(package) as archive:
                    archive.extractall(staging_parent)
                if not (candidate / "app" / "lab_hub.py").is_file():
                    raise UpdateError("Update package has no valid application layer.")
                if self.backup.exists():
                    shutil.rmtree(self.backup)
                old_version = (
                    self.version_file.read_bytes()
                    if self.version_file.is_file() else None)
                self.app_root.replace(self.backup)
                try:
                    candidate.replace(self.app_root)
                    self.version_file.write_text(json.dumps({
                        "installed_app_version": manifest["app_version"],
                        "installed_runtime_version":
                            local["installed_runtime_version"],
                    }, indent=2), encoding="utf-8")
                except Exception:
                    if self.app_root.exists():
                        shutil.rmtree(self.app_root, ignore_errors=True)
                    self.backup.replace(self.app_root)
                    if old_version is None:
                        self.version_file.unlink(missing_ok=True)
                    else:
                        self.version_file.write_bytes(old_version)
                    raise
            finally:
                if staging_parent.exists():
                    shutil.rmtree(staging_parent, ignore_errors=True)
        finally:
            if download_dir is not None:
                shutil.rmtree(download_dir, ignore_errors=True)
        return None

    def revert(self):
        if not self.backup.is_dir():
            raise UpdateError("No previous application version is available.")
        failed = self.install_root / "LabTools.failed"
        if failed.exists():
            shutil.rmtree(failed)
        self.app_root.replace(failed)
        try:
            self.backup.replace(self.app_root)
            info = json.loads(
                (self.app_root / "app" / "release_info.json").read_text(
                    encoding="utf-8-sig"))
            runtime = self.local_versions()["installed_runtime_version"]
            self.version_file.write_text(json.dumps({
                "installed_app_version": info["app_version"],
                "installed_runtime_version": runtime}, indent=2),
                encoding="utf-8")
        except Exception:
            failed.replace(self.app_root)
            raise
        shutil.rmtree(failed, ignore_errors=True)
