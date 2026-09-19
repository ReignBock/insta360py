"""The window's updating: prompts, downloads, verification, and rollback."""

# pylint: disable=redefined-outer-name,protected-access

import json
import os
import plistlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# Set before Qt loads: the suite must run with no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

# The imports below need PySide6, so they follow importorskip.
# pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QWidget  # noqa: E402
from pki_kit import DAY, NOW, Authority, Leaf, issue_leaf, make_authority, make_crl  # noqa: E402

from insvmarkers import update, updater  # noqa: E402
from insvmarkers.update import Release, UpdateError  # noqa: E402
from insvmarkers.updater import AppInfo, Choice, UpdateController  # noqa: E402

# pylint: enable=wrong-import-position,no-name-in-module

ZIP = b"pretend this is the release zip"
LATEST = update.LATEST_URL
SIG_URL = "https://example.test/Insta360-Markers-0.4.0-arm64.zip.sig"
ZIP_URL = "https://example.test/Insta360-Markers-0.4.0-arm64.zip"
CERT_URL = "https://example.test/Insta360-Markers-0.4.0-arm64.zip.crt"
CRL_URL = update.CRL_URL


@pytest.fixture(scope="module")
def app() -> QApplication:
    """One application for the whole module; Qt allows only one per process."""
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _make_app(path: Path, version: str) -> Path:
    """A minimal app bundle declaring ``version``."""
    (path / "Contents" / "MacOS").mkdir(parents=True)
    (path / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))
    return path


def _release_json(version: str = "0.4.0") -> bytes:
    """A GitHub ``releases/latest`` response for an arm64 zip and its signature."""
    name = f"Insta360-Markers-{version}-arm64.zip"
    return json.dumps(
        {
            "tag_name": f"v{version}",
            "body": "Notes.",
            "assets": [
                {"name": name, "browser_download_url": f"https://example.test/{name}"},
                {"name": f"{name}.sig", "browser_download_url": f"https://example.test/{name}.sig"},
                {"name": f"{name}.crt", "browser_download_url": f"https://example.test/{name}.crt"},
            ],
        }
    ).encode()


class FakeFetch:  # pylint: disable=too-few-public-methods
    """A network that answers from a table and remembers what was asked."""

    def __init__(self) -> None:
        self.responses: dict[str, bytes | None] = {}
        self.asked: list[str] = []
        self.deferred: list[Callable[[bytes | None], None]] | None = None

    def __call__(
        self,
        url: str,
        done: Callable[[bytes | None], None],
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.asked.append(url)

        if self.deferred is not None:
            self.deferred.append(done)
            return

        if progress is not None:
            progress(5, 10)
        done(self.responses.get(url))


@dataclass
class Rig:  # pylint: disable=too-many-instance-attributes
    """A controller wired to fakes, with everything it did recorded."""

    controller: UpdateController
    fetch: FakeFetch
    settings: QSettings
    bundle: Path
    support: Path
    window: QWidget
    leaf: Leaf
    authority: Authority
    crl: bytes
    informs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    swaps: list[tuple[Path, Path, Path]] = field(default_factory=list)
    quits: list[bool] = field(default_factory=list)
    choice: Choice = Choice.LATER
    confirmed: bool = True

    def offer(self, version: str = "0.4.0") -> None:
        """Make a newer release available: a good zip, signature, certificate and list."""
        self.fetch.responses[LATEST] = _release_json(version)
        name = f"Insta360-Markers-{version}-arm64.zip"
        self.fetch.responses[f"https://example.test/{name}"] = ZIP
        self.fetch.responses[f"https://example.test/{name}.sig"] = update.sign(ZIP, self.leaf.key_pem).encode()
        self.fetch.responses[f"https://example.test/{name}.crt"] = self.leaf.pem
        self.fetch.responses[CRL_URL] = self.crl


@pytest.fixture
def rig(app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Rig]:  # pylint: disable=unused-argument
    """A controller on version 0.3.0 with fake network, dialogs and swap."""
    authority = make_authority()
    leaf = issue_leaf(authority)
    crl = make_crl(authority)

    window = QWidget()
    bundle = _make_app(tmp_path / "apps" / "Insta360 Markers.app", "0.3.0")
    support = tmp_path / "support"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    fetch = FakeFetch()

    info = AppInfo(
        bundle=bundle,
        support=support,
        authority=authority.pem,
        installed="0.3.0",
        arch="arm64",
        bundled_crl=crl,
        relaunch="true",
    )
    controller = UpdateController(window, info, fetch, settings)
    made = Rig(controller, fetch, settings, bundle, support, window, leaf, authority, crl)

    monkeypatch.setattr(updater, "inform", lambda _parent, text: made.informs.append(text))
    monkeypatch.setattr(updater, "warn", lambda _parent, text: made.warnings.append(text))
    monkeypatch.setattr(updater, "confirm", lambda _parent, _text: made.confirmed)
    monkeypatch.setattr(updater, "ask_to_install", lambda _parent, _release, _installed: made.choice)
    monkeypatch.setattr(QApplication, "quit", lambda: made.quits.append(True))

    def fake_stage(_archive: Path, destination: Path, expected: str) -> Path:
        return _make_app(destination / "Insta360 Markers.app", expected)

    monkeypatch.setattr(update, "stage", fake_stage)
    monkeypatch.setattr(
        update,
        "start_swap",
        lambda current, new, previous, _support, _relaunch="open": made.swaps.append((current, new, previous)),
    )

    yield made
    window.deleteLater()


# Checking


def test_no_newer_version_stays_quiet(rig: Rig) -> None:
    """The automatic check says nothing when there is nothing to say."""
    rig.fetch.responses[LATEST] = _release_json("0.3.0")

    rig.controller.check()

    assert not rig.informs
    assert not rig.warnings
    assert not rig.swaps


def test_a_manual_check_says_when_you_are_up_to_date(rig: Rig) -> None:
    """Asking for an answer always gets one."""
    rig.fetch.responses[LATEST] = _release_json("0.3.0")

    rig.controller.check(manual=True)

    assert rig.informs == ["You have the latest version, 0.3.0."]


def test_a_failed_check_is_silent_unless_asked(rig: Rig) -> None:
    """No network is not worth interrupting anyone for."""
    rig.controller.check()
    assert not rig.warnings

    rig.controller.check(manual=True)
    assert "Could not check for updates" in rig.warnings[0]


def test_a_release_with_no_app_for_this_mac_is_treated_as_no_update(rig: Rig) -> None:
    """A release without a signed zip is never offered."""
    rig.fetch.responses[LATEST] = json.dumps({"tag_name": "v0.4.0", "assets": []}).encode()

    rig.controller.check(manual=True)

    assert rig.informs == ["You have the latest version, 0.3.0."]


def test_choosing_not_now_installs_nothing_and_asks_again_later(rig: Rig) -> None:
    """Not Now leaves everything as it was, including the next check."""
    rig.offer()
    rig.choice = Choice.LATER

    rig.controller.check()

    assert not rig.swaps
    assert rig.fetch.asked == [LATEST]
    assert rig.settings.value(updater.SKIPPED_KEY) is None


def test_a_skipped_version_stops_being_offered_automatically(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip This Version silences that version, but not a later one."""
    rig.offer()
    rig.choice = Choice.SKIP
    rig.controller.check()
    asked: list[str] = []

    def record(_parent: object, release: Release, _installed: str) -> Choice:
        asked.append(release.version)
        return Choice.LATER

    monkeypatch.setattr(updater, "ask_to_install", record)
    rig.controller.check()
    rig.offer("0.5.0")
    rig.controller.check()

    assert asked == ["0.5.0"]


def test_a_manual_check_offers_a_skipped_version_again(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Asking is a change of mind."""
    rig.offer()
    rig.settings.setValue(updater.SKIPPED_KEY, "0.4.0")
    prompts: list[str] = []

    def record(_parent: object, release: Release, _installed: str) -> Choice:
        prompts.append(release.version)
        return Choice.LATER

    monkeypatch.setattr(updater, "ask_to_install", record)

    rig.controller.check(manual=True)

    assert prompts == ["0.4.0"]


def test_a_check_already_running_is_not_repeated(rig: Rig) -> None:
    """Two checks at once would prompt twice."""
    rig.fetch.deferred = []

    rig.controller.check()
    rig.controller.check()

    assert rig.fetch.asked == [LATEST]


def test_starting_checks_at_once_and_then_every_day(app: QApplication, rig: Rig) -> None:
    """On launch, and every 24 hours if the window stays open."""
    rig.controller.start()
    app.processEvents()

    assert rig.fetch.asked == [LATEST]
    assert rig.controller._timer.isActive()
    assert rig.controller._timer.interval() == 24 * 60 * 60 * 1000

    rig.controller._timer.timeout.emit()

    assert rig.fetch.asked == [LATEST, LATEST]


# Installing


def test_installing_verifies_then_swaps_and_quits(rig: Rig) -> None:
    """The whole path: download, verify, stage, hand over to the helper, quit."""
    rig.offer()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert rig.fetch.asked == [LATEST, SIG_URL, CERT_URL, ZIP_URL, CRL_URL]
    staged = rig.support / "Staging" / "Insta360 Markers.app"
    assert rig.swaps == [(rig.bundle, staged, update.previous_app(rig.support))]
    assert rig.quits == [True]
    assert not rig.warnings
    assert not list(rig.support.glob("*.zip"))


def test_an_unverifiable_download_is_refused(rig: Rig) -> None:
    """A zip that does not match its signature is never installed."""
    rig.offer()
    rig.fetch.responses[ZIP_URL] = b"a different file"
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert not rig.quits
    assert "signature is not valid" in rig.warnings[0]
    assert "Nothing was changed" in rig.warnings[0]


def test_a_signature_from_another_key_is_refused(rig: Rig) -> None:
    """Only the release key's signature counts."""
    rig.offer()
    other = issue_leaf(rig.authority)
    rig.fetch.responses[SIG_URL] = update.sign(ZIP, other.key_pem).encode()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "signature is not valid" in rig.warnings[0]


def test_a_missing_signature_stops_before_the_zip_is_fetched(rig: Rig) -> None:
    """No point in downloading a file that cannot be verified."""
    rig.offer()
    rig.fetch.responses[SIG_URL] = None
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert ZIP_URL not in rig.fetch.asked
    assert "signature could not be downloaded" in rig.warnings[0]


def test_a_failed_zip_download_is_reported(rig: Rig) -> None:
    """A dropped connection mid-update leaves the app untouched."""
    rig.offer()
    rig.fetch.responses[ZIP_URL] = None
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "could not be downloaded" in rig.warnings[0]


def test_a_download_that_is_not_the_named_version_is_refused(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging rejects a signed zip of the wrong version, and nothing is swapped."""

    def reject(*_args: object) -> Path:
        raise UpdateError("The download is version 0.3.0, not 0.4.0.")

    monkeypatch.setattr(update, "stage", reject)
    rig.offer()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "not 0.4.0" in rig.warnings[0]
    assert not (rig.support / "Staging").exists()


def test_a_helper_that_cannot_start_is_reported(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the swap cannot begin, the app keeps running."""

    def refuse(*_args: object) -> None:
        raise UpdateError("The update could not be started: no shell")

    monkeypatch.setattr(update, "start_swap", refuse)
    rig.offer()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.quits
    assert "could not be started" in rig.warnings[0]


def test_a_disk_error_while_saving_is_reported(rig: Rig) -> None:
    """A full or read-only support folder is an error message, not a crash."""
    rig.offer()
    rig.choice = Choice.INSTALL
    rig.support.parent.mkdir(parents=True, exist_ok=True)
    rig.support.write_text("a file where the folder should be")

    rig.controller.check()

    assert not rig.swaps
    assert "Nothing was changed" in rig.warnings[0]


def test_an_app_that_cannot_replace_itself_is_not_downloaded(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The user is told why before anything is fetched."""
    monkeypatch.setattr(update, "install_problem", lambda _bundle: "Move it first.")
    rig.offer()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert rig.warnings == ["Move it first."]
    assert rig.fetch.asked == [LATEST]


def test_progress_with_an_unknown_size_shows_a_busy_bar(rig: Rig) -> None:
    """A server that does not report a length gives an indeterminate bar."""
    rig.controller._on_progress(10, -1)  # no dialog yet: ignored

    rig.offer()
    rig.choice = Choice.INSTALL
    rig.fetch.deferred = []
    rig.controller.check()
    rig.fetch.deferred.pop()(_release_json())
    rig.controller._on_progress(10, -1)

    assert rig.controller._progress is not None
    assert rig.controller._progress.maximum() == 0


def test_a_missing_certificate_stops_before_the_zip_is_fetched(rig: Rig) -> None:
    """No certificate, no way to check the signature."""
    rig.offer()
    rig.fetch.responses[CERT_URL] = None
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert ZIP_URL not in rig.fetch.asked
    assert "certificate could not be downloaded" in rig.warnings[0]


def test_a_certificate_from_another_authority_is_refused(rig: Rig) -> None:
    """Chaining to anyone but the built-in authority means nothing."""
    rig.offer()
    stranger = issue_leaf(make_authority("Someone Else"))
    rig.fetch.responses[CERT_URL] = stranger.pem
    rig.fetch.responses[SIG_URL] = update.sign(ZIP, stranger.key_pem).encode()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "not issued by the release authority" in rig.warnings[0]


def test_a_revoked_certificate_is_refused_using_the_downloaded_list(rig: Rig) -> None:
    """The list built into the app is clean, but the published one names this certificate."""
    rig.offer()
    rig.fetch.responses[CRL_URL] = make_crl(rig.authority, revoked=(rig.leaf.serial,), number=2)
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert not rig.quits
    assert "has been revoked" in rig.warnings[0]


def test_a_revocation_that_cannot_be_downloaded_still_uses_the_built_in_list(rig: Rig) -> None:
    """Going offline does not stop an update the built-in list allows."""
    rig.offer()
    rig.fetch.responses[CRL_URL] = None
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert rig.quits == [True]
    assert not rig.warnings


def test_a_revocation_the_built_in_list_knows_is_refused_offline(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """A certificate revoked before this build shipped is refused even with no network."""
    rig.offer()
    rig.fetch.responses[CRL_URL] = None
    monkeypatch.setattr(
        rig.controller,
        "_info",
        AppInfo(
            bundle=rig.bundle,
            support=rig.support,
            authority=rig.authority.pem,
            installed="0.3.0",
            arch="arm64",
            bundled_crl=make_crl(rig.authority, revoked=(rig.leaf.serial,), number=2),
            relaunch="true",
        ),
    )
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "has been revoked" in rig.warnings[0]


def test_no_revocation_list_anywhere_means_no_install(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing to check against, the update is refused."""
    rig.offer()
    rig.fetch.responses[CRL_URL] = None
    monkeypatch.setattr(
        rig.controller,
        "_info",
        AppInfo(rig.bundle, rig.support, rig.authority.pem, "0.3.0", "arm64", None, "true"),
    )
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "No current revocation list" in rig.warnings[0]


def test_an_expired_built_in_list_is_replaced_by_a_downloaded_one(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """An app left unopened for a long time still updates while it is online."""
    stale = make_crl(rig.authority, last_update=NOW - 400 * DAY, next_update=NOW - 35 * DAY)
    rig.offer()
    monkeypatch.setattr(
        rig.controller,
        "_info",
        AppInfo(rig.bundle, rig.support, rig.authority.pem, "0.3.0", "arm64", stale, "true"),
    )
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert rig.quits == [True]


def test_a_current_downloaded_list_is_kept_for_next_time(rig: Rig) -> None:
    """So an offline install later still benefits from what was learned."""
    rig.offer()
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert update.cached_crl(rig.support) == rig.crl


def test_a_downloaded_list_that_is_not_trusted_is_not_kept(rig: Rig) -> None:
    """Junk from the network never reaches the cache."""
    rig.offer()
    rig.fetch.responses[CRL_URL] = b"junk"
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert update.cached_crl(rig.support) is None
    assert rig.quits == [True]


def test_a_cached_list_that_revokes_the_certificate_is_honoured_offline(rig: Rig) -> None:
    """What was learned earlier still protects when the network is down."""
    rig.offer()
    update.cache_crl(rig.support, make_crl(rig.authority, revoked=(rig.leaf.serial,), number=3))
    rig.fetch.responses[CRL_URL] = None
    rig.choice = Choice.INSTALL

    rig.controller.check()

    assert not rig.swaps
    assert "has been revoked" in rig.warnings[0]


# Rolling back


def test_rollback_with_no_previous_version_says_so(rig: Rig) -> None:
    """Before any update there is nothing to go back to."""
    rig.controller.rollback()

    assert rig.informs == ["There is no earlier version to go back to."]
    assert not rig.swaps


def test_rollback_swaps_in_the_previous_version_and_quits(rig: Rig) -> None:
    """The previous app becomes current, and this version is not offered again."""
    previous = _make_app(update.previous_app(rig.support), "0.2.0")

    rig.controller.rollback()

    assert rig.swaps == [(rig.bundle, previous, previous)]
    assert rig.quits == [True]
    assert rig.settings.value(updater.SKIPPED_KEY) == "0.3.0"


def test_declining_a_rollback_changes_nothing(rig: Rig) -> None:
    """The confirmation is a real choice."""
    _make_app(update.previous_app(rig.support), "0.2.0")
    rig.confirmed = False

    rig.controller.rollback()

    assert not rig.swaps
    assert rig.settings.value(updater.SKIPPED_KEY) is None


def test_a_rollback_that_cannot_run_explains_why(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same location rules apply as for an update."""
    _make_app(update.previous_app(rig.support), "0.2.0")
    monkeypatch.setattr(update, "install_problem", lambda _bundle: "Move it first.")

    rig.controller.rollback()

    assert rig.warnings == ["Move it first."]


def test_a_rollback_whose_helper_cannot_start_is_reported(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The user is told, and the app carries on."""
    _make_app(update.previous_app(rig.support), "0.2.0")

    def refuse(*_args: object) -> None:
        raise UpdateError("no shell")

    monkeypatch.setattr(update, "start_swap", refuse)

    rig.controller.rollback()

    assert rig.warnings == ["no shell"]
    assert not rig.quits


# The menu


def _help_menu(window: QMainWindow) -> QMenu:
    """The Help menu the updater added."""
    return window.menuBar().findChildren(QMenu)[0]


def test_the_help_menu_offers_updates_and_rollback(app: QApplication, rig: Rig) -> None:  # pylint: disable=unused-argument
    """Both commands exist, and rollback is off with nothing to go back to."""
    window = QMainWindow()
    rig.controller.attach_menu(window.menuBar())

    actions = _help_menu(window).actions()

    assert window.menuBar().actions()[0].text() == "Help"
    assert [action.text() for action in actions] == ["Check for Updates…", "Roll Back"]
    assert not actions[1].isEnabled()


def test_the_rollback_command_names_the_version_it_restores(rig: Rig) -> None:
    """Once there is an earlier version, the menu says which."""
    window = QMainWindow()
    rig.controller.attach_menu(window.menuBar())
    menu = _help_menu(window)
    _make_app(update.previous_app(rig.support), "0.2.0")

    menu.aboutToShow.emit()

    assert menu.actions()[1].text() == "Roll Back to Version 0.2.0"
    assert menu.actions()[1].isEnabled()


def test_the_check_command_runs_a_manual_check(rig: Rig) -> None:
    """The menu item always answers."""
    window = QMainWindow()
    rig.controller.attach_menu(window.menuBar())
    rig.fetch.responses[LATEST] = _release_json("0.3.0")

    _help_menu(window).actions()[0].trigger()

    assert rig.informs == ["You have the latest version, 0.3.0."]


def test_the_rollback_command_starts_a_rollback(rig: Rig) -> None:
    """The menu item reaches the rollback."""
    window = QMainWindow()
    rig.controller.attach_menu(window.menuBar())
    _make_app(update.previous_app(rig.support), "0.2.0")
    menu = _help_menu(window)
    menu.aboutToShow.emit()

    menu.actions()[1].trigger()

    assert len(rig.swaps) == 1


# Where updating applies


def test_a_source_install_gets_no_updater(app: QApplication) -> None:  # pylint: disable=unused-argument
    """Only the downloaded Mac app can replace itself."""
    assert updater.create(QWidget()) is None


def test_a_build_without_an_authority_certificate_gets_no_updater(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path  # pylint: disable=unused-argument
) -> None:
    """It has nothing to trust, so it does not check for updates."""
    monkeypatch.setattr(update, "app_bundle", lambda: tmp_path / "A.app")
    monkeypatch.setattr(update, "load_authority", lambda: None)

    assert updater.create(QWidget()) is None


def test_the_mac_app_with_an_authority_certificate_gets_an_updater(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path  # pylint: disable=unused-argument
) -> None:
    """Both conditions met: a bundle and a certificate to trust."""
    monkeypatch.setattr(update, "app_bundle", lambda: tmp_path / "A.app")
    monkeypatch.setattr(update, "load_authority", lambda: b"authority")
    monkeypatch.setattr(update, "support_dir", lambda: tmp_path / "support")

    created = updater.create(QWidget())

    assert isinstance(created, UpdateController)
    assert isinstance(created._fetch, updater.QtFetcher)


# The questions


def _press(monkeypatch: pytest.MonkeyPatch, label: str) -> None:
    """Make the update prompt behave as if ``label`` was clicked."""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == label)
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [("Install and Restart", Choice.INSTALL), ("Skip This Version", Choice.SKIP), ("Not Now", Choice.LATER)],
)
def test_the_prompt_returns_the_button_pressed(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, label: str, expected: Choice  # pylint: disable=unused-argument
) -> None:
    """Each of the three buttons maps to its choice."""
    _press(monkeypatch, label)
    release = Release("0.4.0", "Notes.", ZIP_URL, SIG_URL, CERT_URL)

    assert updater.ask_to_install(QWidget(), release, "0.3.0") is expected


def test_the_message_helpers_use_the_standard_dialogs(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:  # pylint: disable=unused-argument
    """Inform, warn and confirm are thin wrappers, and confirm means Yes."""
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: shown.append(("info", text)))
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(("warn", text)))
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, _text: QMessageBox.StandardButton.Yes)

    updater.inform(QWidget(), "a")
    updater.warn(QWidget(), "b")

    assert shown == [("info", "a"), ("warn", "b")]
    assert updater.confirm(QWidget(), "c") is True

    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, _text: QMessageBox.StandardButton.No)
    assert updater.confirm(QWidget(), "c") is False


# The real network code, against a server on this machine


class _Handler(BaseHTTPRequestHandler):
    """Serves a body, a redirect to it, and a missing page."""

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Answer the test paths."""
        self.server.seen_agents.append(self.headers.get("User-Agent", ""))  # type: ignore[attr-defined]

        if self.path == "/body":
            self.send_response(200)
            self.send_header("Content-Length", "11")
            self.end_headers()
            self.wfile.write(b"hello world")
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/body")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # pylint: disable=redefined-builtin
        """Keep the test output clean."""


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    """A local web server on a free port."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.seen_agents = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def fetcher(app: QApplication) -> updater.QtFetcher:  # pylint: disable=unused-argument
    """One fetcher for the module, as the app has one for its whole life.

    Qt's network manager must outlive the requests made through it, so a
    fresh one per request is not a fair model of the app.
    """
    return updater.QtFetcher()


def _fetch_one(
    fetcher: updater.QtFetcher, url: str, progress: Callable[[int, int], None] | None = None
) -> bytes | None:
    """Fetch ``url`` with the real fetcher and wait for the answer."""
    loop = QEventLoop()
    result: list[bytes | None] = []

    def done(body: bytes | None) -> None:
        result.append(body)
        loop.quit()

    fetcher(url, done, progress)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()

    assert result, "the fetch never finished"
    return result[0]


def test_the_fetcher_downloads_a_body(fetcher: updater.QtFetcher, server: ThreadingHTTPServer) -> None:
    """A plain download returns its bytes and reports progress."""
    seen: list[tuple[int, int]] = []

    body = _fetch_one(
        fetcher, f"http://127.0.0.1:{server.server_port}/body", lambda got, total: seen.append((got, total))
    )

    assert body == b"hello world"
    assert seen
    assert server.seen_agents[0].startswith("insta360py/")  # type: ignore[attr-defined]


def test_the_fetcher_follows_a_redirect(fetcher: updater.QtFetcher, server: ThreadingHTTPServer) -> None:
    """GitHub serves its downloads through a redirect."""
    assert _fetch_one(fetcher, f"http://127.0.0.1:{server.server_port}/redirect") == b"hello world"


def test_a_missing_page_is_a_failed_download(fetcher: updater.QtFetcher, server: ThreadingHTTPServer) -> None:
    """An error status gives None, not an error page taken as data."""
    assert _fetch_one(fetcher, f"http://127.0.0.1:{server.server_port}/nothing") is None


def test_an_unreachable_server_is_a_failed_download(fetcher: updater.QtFetcher) -> None:
    """No connection gives None."""
    assert _fetch_one(fetcher, "http://127.0.0.1:9/") is None
