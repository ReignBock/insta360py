"""Checking, verifying and installing an update, without a window or a network."""

# pylint: disable=redefined-outer-name

import json
import plistlib
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from cryptography import x509

from insvmarkers import update
from insvmarkers.update import Release, UpdateError


def _release_json(version: str = "0.4.0", arch: str = "arm64", **overrides: object) -> bytes:
    """A GitHub ``releases/latest`` response with a zip and signature for ``arch``."""
    name = f"Insta360-Markers-{version}-{arch}.zip"
    payload: dict[str, object] = {
        "tag_name": f"v{version}",
        "body": "What changed.",
        "assets": [
            {"name": name, "browser_download_url": f"https://example.test/{name}"},
            {"name": f"{name}.sig", "browser_download_url": f"https://example.test/{name}.sig"},
            {"name": f"{name}.crt", "browser_download_url": f"https://example.test/{name}.crt"},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


# Versions


def test_versions_compare_by_number_not_by_text() -> None:
    """0.10.0 is later than 0.9.0, which a string comparison gets wrong."""
    assert update.is_newer("0.10.0", "0.9.0")
    assert update.is_newer("v0.3.1", "0.3.0")
    assert not update.is_newer("0.3.0", "0.3.0")
    assert not update.is_newer("0.2.9", "0.3.0")


def test_a_version_that_is_not_plain_numbers_is_never_newer() -> None:
    """A pre-release tag is not offered, rather than guessed at."""
    assert not update.is_newer("0.4.0rc1", "0.3.0")
    assert not update.is_newer("latest", "0.3.0")


def test_the_running_version_comes_from_the_package_metadata() -> None:
    """The installed version is what the app reports."""
    assert update.current_version() == update.version("insta360py")


def test_an_uninstalled_package_reports_version_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source tree that was never installed is older than any release."""

    def missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(update, "version", missing)

    assert update.current_version() == "0"


def test_the_architecture_is_the_machines(monkeypatch: pytest.MonkeyPatch) -> None:
    """The zip name uses the same word ``uname -m`` gives."""
    monkeypatch.setattr(update.platform, "machine", lambda: "arm64")

    assert update.machine_arch() == "arm64"


# Reading a release


def test_a_release_names_its_zip_signature_and_certificate() -> None:
    """The version, notes and all three download links come through."""
    release = update.release_from_json(_release_json(), "arm64")

    assert release == Release(
        version="0.4.0",
        notes="What changed.",
        zip_url="https://example.test/Insta360-Markers-0.4.0-arm64.zip",
        sig_url="https://example.test/Insta360-Markers-0.4.0-arm64.zip.sig",
        cert_url="https://example.test/Insta360-Markers-0.4.0-arm64.zip.crt",
    )


def test_a_release_without_a_zip_for_this_mac_is_not_offered() -> None:
    """An Intel-only release means nothing to an Apple silicon Mac."""
    assert update.release_from_json(_release_json(arch="x86_64"), "arm64") is None


@pytest.mark.parametrize("missing", [".sig", ".crt"])
def test_a_release_missing_its_signature_or_certificate_is_not_offered(missing: str) -> None:
    """An update that cannot be checked is never offered."""
    name = "Insta360-Markers-0.4.0-arm64.zip"
    parts = [name, f"{name}.sig", f"{name}.crt"]
    kept = [part for part in parts if not part.endswith(missing)]
    assets = [{"name": part, "browser_download_url": f"https://x.test/{part}"} for part in kept]
    body = _release_json(assets=assets)

    assert update.release_from_json(body, "arm64") is None


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"assets": []}', b'{"tag_name": 4}'],
    ids=["not-json", "not-an-object", "no-tag", "tag-not-text"],
)
def test_a_response_that_is_not_a_release_is_ignored(body: bytes) -> None:
    """The response is not trusted; anything odd gives nothing."""
    assert update.release_from_json(body, "arm64") is None


def test_odd_assets_are_skipped_not_fatal() -> None:
    """One malformed asset does not hide the good ones."""
    good = json.loads(_release_json())["assets"]
    body = _release_json(assets=["text", {"name": 7}, {"name": "no-link.zip"}, *good])

    assert update.release_from_json(body, "arm64") is not None


def test_missing_notes_are_empty_and_long_notes_are_cut() -> None:
    """The prompt never shows an unbounded wall of text."""
    empty = update.release_from_json(_release_json(body=None), "arm64")
    long = update.release_from_json(_release_json(body="x" * 5000), "arm64")

    assert empty is not None
    assert empty.notes == ""
    assert long is not None
    assert len(long.notes) == update.NOTES_LIMIT


def test_a_release_with_no_assets_key_is_not_offered() -> None:
    """A release with nothing attached has nothing to install."""
    assert update.release_from_json(_release_json(assets=None), "arm64") is None


# The built-in trust files, and the downloaded revocation list


def test_a_build_without_an_authority_certificate_has_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Nothing to trust means no updates."""
    monkeypatch.setattr(update.resources, "files", lambda _package: tmp_path)

    assert update.load_authority() is None
    assert update.load_bundled_crl() is None


def test_the_built_in_files_are_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The certificate and list beside the code are the ones used."""
    (tmp_path / update.CA_FILE).write_bytes(b"authority")
    (tmp_path / update.CRL_FILE).write_bytes(b"list")
    monkeypatch.setattr(update.resources, "files", lambda _package: tmp_path)

    assert update.load_authority() == b"authority"
    assert update.load_bundled_crl() == b"list"


def test_the_shipped_authority_certificate_is_a_real_ca() -> None:
    """The certificate in the repository parses and is a certificate authority."""
    pem = update.load_authority()
    assert pem is not None

    certificate = x509.load_pem_x509_certificate(pem)
    constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value

    assert constraints.ca
    assert certificate.subject == certificate.issuer


def test_a_downloaded_revocation_list_is_kept_for_offline_checks(tmp_path: Path) -> None:
    """Saved to the support folder and read back."""
    support = tmp_path / "support"
    assert update.cached_crl(support) is None

    update.cache_crl(support, b"list")

    assert update.cached_crl(support) == b"list"


def test_a_cache_that_cannot_be_written_is_not_an_error(tmp_path: Path) -> None:
    """Failing to remember a list must never fail an update."""
    blocker = tmp_path / "support"
    blocker.write_text("a file where the folder should be")

    update.cache_crl(blocker, b"list")

    assert update.cached_crl(blocker) is None


# Where the app is


def test_a_source_install_is_not_an_app_bundle() -> None:
    """Only the frozen Mac app can replace itself."""
    assert update.app_bundle() is None


def test_a_frozen_app_finds_its_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The bundle is three folders above the executable."""
    executable = tmp_path / "Insta360 Markers.app" / "Contents" / "MacOS" / "Insta360 Markers"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert update.app_bundle() == (tmp_path / "Insta360 Markers.app").resolve()


def test_a_frozen_program_outside_an_app_is_not_a_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A frozen build that is not a .app has nothing to replace."""
    executable = tmp_path / "a" / "b" / "c" / "tool"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert update.app_bundle() is None


def test_support_files_live_in_application_support(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The previous version is kept where macOS expects an app's data."""
    monkeypatch.setenv("HOME", str(tmp_path))

    support = update.support_dir()

    assert support == tmp_path / "Library" / "Application Support" / "Insta360 Markers"
    assert update.previous_app(support) == support / "Previous" / "Insta360 Markers.app"


def _make_app(path: Path, version: str = "0.3.0", marker: str = "") -> Path:
    """A minimal app bundle declaring ``version``, with ``marker`` as its content."""
    (path / "Contents" / "MacOS").mkdir(parents=True)
    (path / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))
    (path / "Contents" / "MacOS" / "marker").write_text(marker)
    return path


def test_an_app_reports_the_version_it_declares(tmp_path: Path) -> None:
    """The version comes from the app's own property list."""
    assert update.bundle_version(_make_app(tmp_path / "A.app", "1.2.3")) == "1.2.3"


def test_an_app_with_no_readable_version_reports_none(tmp_path: Path) -> None:
    """A missing, broken or wrong-typed property list has no version."""
    assert update.bundle_version(tmp_path / "Missing.app") is None

    broken = tmp_path / "Broken.app" / "Contents"
    broken.mkdir(parents=True)
    (broken / "Info.plist").write_bytes(b"garbage")
    assert update.bundle_version(tmp_path / "Broken.app") is None

    numeric = tmp_path / "Numeric.app" / "Contents"
    numeric.mkdir(parents=True)
    (numeric / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": 3}))
    assert update.bundle_version(tmp_path / "Numeric.app") is None


def test_an_app_running_from_a_translocated_path_cannot_update() -> None:
    """macOS runs a just-downloaded app read-only until it is moved."""
    bundle = Path("/private/var/folders/x/AppTranslocation/ABC/d/Insta360 Markers.app")

    assert "Applications folder" in (update.install_problem(bundle) or "")


def test_an_app_in_a_folder_the_user_cannot_write_cannot_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """A standard account cannot replace an app in Applications."""
    monkeypatch.setattr(update.os, "access", lambda _path, _mode: False)

    assert "replace the app by hand" in (update.install_problem(Path("/Applications/Insta360 Markers.app")) or "")


def test_an_app_in_a_writable_folder_can_update(tmp_path: Path) -> None:
    """The normal case has nothing to report."""
    assert update.install_problem(tmp_path / "Insta360 Markers.app") is None


# Staging


def _fake_extract(*apps: tuple[str, str]):
    """An extractor that puts the given ``(name, version)`` apps in place."""

    def extract(_archive: Path, destination: Path) -> None:
        for name, version in apps:
            _make_app(destination / name, version)

    return extract


def test_a_good_download_is_staged(tmp_path: Path) -> None:
    """One app, the version the release named."""
    extract = _fake_extract(("Insta360 Markers.app", "0.4.0"))

    staged = update.stage(tmp_path / "z.zip", tmp_path / "stage", "0.4.0", extract)

    assert staged == tmp_path / "stage" / "Insta360 Markers.app"


@pytest.mark.parametrize("apps", [(), (("A.app", "0.4.0"), ("B.app", "0.4.0"))], ids=["none", "two"])
def test_a_download_must_hold_exactly_one_app(tmp_path: Path, apps: tuple[tuple[str, str], ...]) -> None:
    """Anything else is not the release that was signed for."""
    with pytest.raises(UpdateError, match="exactly one app"):
        update.stage(tmp_path / "z.zip", tmp_path / "stage", "0.4.0", _fake_extract(*apps))


def test_an_old_signed_zip_cannot_pass_as_a_new_release(tmp_path: Path) -> None:
    """The version inside the app must match the version the release named."""
    with pytest.raises(UpdateError, match="version 0.3.0, not 0.4.0"):
        update.stage(tmp_path / "z.zip", tmp_path / "stage", "0.4.0", _fake_extract(("A.app", "0.3.0")))


def test_a_download_with_no_program_inside_is_refused(tmp_path: Path) -> None:
    """An app folder with no executable folder is not complete."""

    def hollow(_archive: Path, destination: Path) -> None:
        app = destination / "A.app" / "Contents"
        app.mkdir(parents=True)
        (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.4.0"}))

    with pytest.raises(UpdateError, match="not a complete app"):
        update.stage(tmp_path / "z.zip", tmp_path / "stage", "0.4.0", hollow)


def test_ditto_unpacks_the_zip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The unpacking command is ditto, which keeps symlinks and modes."""
    calls: list[list[str]] = []
    monkeypatch.setattr(update.subprocess, "run", lambda command, **_kw: calls.append(command))

    update.extract_zip(tmp_path / "z.zip", tmp_path / "out")

    assert calls == [["ditto", "-x", "-k", str(tmp_path / "z.zip"), str(tmp_path / "out")]]


@pytest.mark.parametrize("failure", [OSError("no ditto"), subprocess.CalledProcessError(1, "ditto")])
def test_a_failed_unpack_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Exception) -> None:
    """Either way the user gets an error, not a crash."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(update.subprocess, "run", fail)

    with pytest.raises(UpdateError, match="could not be unpacked"):
        update.extract_zip(tmp_path / "z.zip", tmp_path / "out")


# The swap, run for real against folders in a temp directory


@pytest.fixture
def swap_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Folders for a swap, a relaunch stand-in, and a process id that has already ended."""
    with subprocess.Popen(["true"]) as finished:
        finished.wait()
    monkeypatch.setattr(update.os, "getpid", lambda: finished.pid)

    relaunch = tmp_path / "relaunch.sh"
    relaunch.write_text('#!/bin/sh\necho "$1" > "$(dirname "$0")/relaunched"\n')
    relaunch.chmod(0o755)

    return {
        "current": _make_app(tmp_path / "apps" / "Insta360 Markers.app", "0.3.0", "old"),
        "new": _make_app(tmp_path / "stage" / "Insta360 Markers.app", "0.4.0", "new"),
        "previous": tmp_path / "support" / "Previous" / "Insta360 Markers.app",
        "support": tmp_path / "support",
        "relaunch": relaunch,
        "flag": tmp_path / "relaunched",
    }


def _wait_for(path: Path) -> None:
    """Wait for the detached helper to finish and relaunch."""
    for _ in range(100):
        if path.exists():
            return
        time.sleep(0.1)
    raise AssertionError(f"{path.name} never appeared; the helper did not finish")


def _content(app: Path) -> str:
    return (app / "Contents" / "MacOS" / "marker").read_text()


def test_an_update_puts_the_new_app_in_place_and_keeps_the_old_one(swap_setup: dict[str, Path]) -> None:
    """The new version runs, and the version it replaced becomes the previous one."""
    s = swap_setup

    update.start_swap(s["current"], s["new"], s["previous"], s["support"], str(s["relaunch"]))
    _wait_for(s["flag"])

    assert _content(s["current"]) == "new"
    assert _content(s["previous"]) == "old"
    assert not s["new"].exists()
    assert s["flag"].read_text().strip() == str(s["current"])


def test_an_update_replaces_an_older_previous_version(swap_setup: dict[str, Path]) -> None:
    """Only one previous version is kept: the one just replaced."""
    s = swap_setup
    _make_app(s["previous"], "0.2.0", "ancient")

    update.start_swap(s["current"], s["new"], s["previous"], s["support"], str(s["relaunch"]))
    _wait_for(s["flag"])

    assert _content(s["previous"]) == "old"


def test_a_rollback_swaps_the_current_and_previous_apps(swap_setup: dict[str, Path]) -> None:
    """Rolling back installs the previous app and keeps the current one to go forward again."""
    s = swap_setup
    _make_app(s["previous"], "0.2.0", "before")

    update.start_swap(s["current"], s["previous"], s["previous"], s["support"], str(s["relaunch"]))
    _wait_for(s["flag"])

    assert _content(s["current"]) == "before"
    assert _content(s["previous"]) == "old"


def test_a_swap_that_cannot_finish_restores_the_old_app(swap_setup: dict[str, Path]) -> None:
    """If the new app cannot be moved in, the user still has a working app."""
    s = swap_setup
    missing = s["new"].parent / "gone.app"

    update.start_swap(s["current"], missing, s["previous"], s["support"], str(s["relaunch"]))
    _wait_for(s["flag"])

    assert _content(s["current"]) == "old"
    assert "restoring the old one" in (s["support"] / "update.log").read_text()


def test_the_helper_that_cannot_start_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An error starting the helper is an update error, and nothing was changed."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("no shell")

    monkeypatch.setattr(update.subprocess, "Popen", fail)

    with pytest.raises(UpdateError, match="could not be started"):
        update.start_swap(tmp_path / "a", tmp_path / "b", tmp_path / "c", tmp_path / "support")
