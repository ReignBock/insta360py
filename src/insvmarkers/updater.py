"""The window's side of updating: when to check, what to ask, what to do.

Checking happens when the window opens and every 24 hours after that while it
stays open. An update is never installed without the user asking for it, and
nothing is installed unless its signature verifies. The previous version is
kept so the user can go back.

The rules for versions, signatures and swapping apps live in
:mod:`insvmarkers.update`. This module is the part with windows and a network.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# pylint reads no compiled extensions, so it cannot see Qt's names.
# pylint: disable=no-name-in-module
from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMenuBar, QMessageBox, QProgressDialog, QWidget

# pylint: enable=no-name-in-module
from . import update
from .update import APP_NAME, Release, UpdateError

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000
FETCH_TIMEOUT_MS = 30_000
SKIPPED_KEY = "skipped_version"

# A download: the address, what to call with the bytes (None on failure), and
# optionally what to call with progress as (received, total).
Fetch = Callable[[str, Callable[[bytes | None], None], Callable[[int, int], None] | None], None]


class Choice(Enum):
    """What the user decided about an available update."""

    INSTALL = "install"
    LATER = "later"
    SKIP = "skip"


class QtFetcher:  # pylint: disable=too-few-public-methods
    """Downloads with Qt's network stack.

    Qt uses the system's trusted certificates. A bundled Python does not
    always do so, and a failed certificate check would break every update.
    """

    def __init__(self) -> None:
        self._manager = QNetworkAccessManager()

    def __call__(
        self,
        url: str,
        done: Callable[[bytes | None], None],
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"insta360py/{update.current_version()}".encode())
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(FETCH_TIMEOUT_MS)

        reply = self._manager.get(request)
        if progress is not None:
            reply.downloadProgress.connect(progress)
        reply.finished.connect(lambda: self._finish(reply, done))

    @staticmethod
    def _finish(reply: QNetworkReply, done: Callable[[bytes | None], None]) -> None:
        """Hand the body to ``done``, or ``None`` if the download failed."""
        failed = reply.error() != QNetworkReply.NetworkError.NoError
        body = None if failed else bytes(reply.readAll().data())

        if failed:
            logger.info("Download failed: %s", reply.errorString())

        reply.deleteLater()
        done(body)


# The questions the user is asked. Each is small so the tests can replace it.


def ask_to_install(parent: QWidget, release: Release, installed: str) -> Choice:
    """Offer an update and return what the user chose."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(APP_NAME)
    box.setText(f"Version {release.version} is available. You have version {installed}.")
    box.setInformativeText(release.notes)
    install = box.addButton("Install and Restart", QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton("Skip This Version", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(install)
    box.exec()

    clicked = box.clickedButton()
    if clicked is install:
        return Choice.INSTALL
    if clicked is skip:
        return Choice.SKIP
    return Choice.LATER


def inform(parent: QWidget, text: str) -> None:
    """Tell the user something."""
    QMessageBox.information(parent, APP_NAME, text)


def warn(parent: QWidget, text: str) -> None:
    """Tell the user something went wrong."""
    QMessageBox.warning(parent, APP_NAME, text)


def confirm(parent: QWidget, text: str) -> bool:
    """Ask a yes or no question."""
    answer = QMessageBox.question(parent, APP_NAME, text)
    return answer == QMessageBox.StandardButton.Yes


@dataclass(frozen=True)
class AppInfo:
    """What the updater needs to know about this copy of the app."""

    bundle: Path
    support: Path
    authority: bytes
    installed: str
    arch: str
    bundled_crl: bytes | None = None
    relaunch: str = "open"


@dataclass
class _Download:
    """The parts of an update gathered so far. Nothing is used until all check out."""

    release: Release
    signature: bytes = b""
    certificate: bytes = b""
    archive: bytes = b""


class UpdateController(QObject):
    """Checks for updates, installs one on request, and rolls back."""

    def __init__(self, window: QWidget, info: AppInfo, fetch: Fetch, settings: QSettings) -> None:
        super().__init__(window)
        self._window = window
        self._info = info
        self._fetch = fetch
        self._settings = settings

        self._busy = False
        self._progress: QProgressDialog | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.check)

    def start(self) -> None:
        """Check now, then once a day for as long as the window stays open."""
        QTimer.singleShot(0, self.check)
        self._timer.start()

    def attach_menu(self, menu_bar: QMenuBar) -> None:
        """Add the Help menu with the update and rollback commands."""
        menu = menu_bar.addMenu("Help")
        check = menu.addAction("Check for Updates…")
        check.triggered.connect(lambda: self.check(manual=True))
        rollback = menu.addAction("Roll Back")
        rollback.triggered.connect(self.rollback)
        menu.aboutToShow.connect(lambda: self._refresh_rollback(rollback))
        self._refresh_rollback(rollback)

    def _refresh_rollback(self, action: QAction) -> None:
        """Name the version a rollback would restore, or switch the command off."""
        found = update.bundle_version(update.previous_app(self._info.support))
        action.setEnabled(found is not None)
        action.setText(f"Roll Back to Version {found}" if found else "Roll Back")

    # Checking

    def check(self, manual: bool = False) -> None:
        """Look for a newer version. A manual check always says what it found."""
        if self._busy:
            return

        self._busy = True
        self._fetch(update.LATEST_URL, lambda body: self._on_latest(body, manual), None)

    def _on_latest(self, body: bytes | None, manual: bool) -> None:
        self._busy = False

        if body is None:
            if manual:
                warn(self._window, "Could not check for updates. Check your internet connection and try again.")
            return

        release = update.release_from_json(body, self._info.arch)

        if release is None or not update.is_newer(release.version, self._info.installed):
            if manual:
                inform(self._window, f"You have the latest version, {self._info.installed}.")
            return

        # A version the user skipped stays quiet, unless they ask.
        if not manual and self._settings.value(SKIPPED_KEY) == release.version:
            return

        choice = ask_to_install(self._window, release, self._info.installed)

        if choice is Choice.INSTALL:
            self._install(release)
        elif choice is Choice.SKIP:
            self._settings.setValue(SKIPPED_KEY, release.version)

    # Installing

    def _install(self, release: Release) -> None:
        problem = update.install_problem(self._info.bundle)
        if problem is not None:
            warn(self._window, problem)
            return

        self._progress = QProgressDialog(f"Downloading version {release.version}…", "", 0, 0, self._window)
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.show()

        # The small files first: if either is missing there is no point in
        # downloading the zip.
        pending = _Download(release)
        self._fetch(release.sig_url, lambda body: self._on_signature(pending, body), None)

    def _on_signature(self, pending: _Download, signature: bytes | None) -> None:
        if signature is None:
            self._fail("The update's signature could not be downloaded.")
            return

        pending.signature = signature
        self._fetch(pending.release.cert_url, lambda body: self._on_certificate(pending, body), None)

    def _on_certificate(self, pending: _Download, certificate: bytes | None) -> None:
        if certificate is None:
            self._fail("The update's certificate could not be downloaded.")
            return

        pending.certificate = certificate
        self._fetch(pending.release.zip_url, lambda body: self._on_download(pending, body), self._on_progress)

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress is None:
            return

        self._progress.setMaximum(max(total, 0))
        self._progress.setValue(received)

    def _on_download(self, pending: _Download, data: bytes | None) -> None:
        if data is None:
            self._fail("The update could not be downloaded.")
            return

        pending.archive = data
        # The newest revocation list, so a certificate revoked since this app
        # was built is refused. If it cannot be fetched, the copies already on
        # hand are used.
        self._fetch(update.CRL_URL, lambda body: self._on_revocations(pending, body), None)

    def _on_revocations(self, pending: _Download, fetched: bytes | None) -> None:
        lists = [
            found
            for found in (fetched, update.cached_crl(self._info.support), self._info.bundled_crl)
            if found is not None
        ]
        now = update.utcnow()

        try:
            update.check_release(
                pending.archive, pending.signature, pending.certificate, self._info.authority, lists, now
            )
        except UpdateError as error:
            self._fail(str(error))
            return

        if fetched is not None and update.is_usable_crl(fetched, self._info.authority, now):
            update.cache_crl(self._info.support, fetched)

        self._stage_and_swap(pending.release, pending.archive)

    def _stage_and_swap(self, release: Release, data: bytes) -> None:
        """Unpack the verified zip, hand over to the helper, and quit."""
        staging = self._info.support / "Staging"
        shutil.rmtree(staging, ignore_errors=True)

        try:
            archive = self._info.support / f"Insta360-Markers-{release.version}-{self._info.arch}.zip"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(data)
            staged = update.stage(archive, staging, release.version)
            archive.unlink()
            update.start_swap(
                self._info.bundle,
                staged,
                update.previous_app(self._info.support),
                self._info.support,
                self._info.relaunch,
            )
        except (OSError, UpdateError) as error:
            self._fail(str(error))
            return

        self._finish_and_quit()

    def _fail(self, message: str) -> None:
        """Abandon an install: close the progress, clear leftovers, tell the user."""
        self._close_progress()
        shutil.rmtree(self._info.support / "Staging", ignore_errors=True)
        warn(self._window, f"{message}\n\nNothing was changed.")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None

    def _finish_and_quit(self) -> None:
        """The helper is waiting for this process to end, so quit."""
        self._close_progress()
        QApplication.quit()

    # Rolling back

    def rollback(self) -> None:
        """Go back to the version before the last update, if the user agrees."""
        previous = update.previous_app(self._info.support)
        found = update.bundle_version(previous)

        if found is None:
            inform(self._window, "There is no earlier version to go back to.")
            return

        problem = update.install_problem(self._info.bundle)
        if problem is not None:
            warn(self._window, problem)
            return

        if not confirm(self._window, f"Go back to version {found}? Insta360 Markers will restart."):
            return

        try:
            update.start_swap(self._info.bundle, previous, previous, self._info.support, self._info.relaunch)
        except UpdateError as error:
            warn(self._window, str(error))
            return

        # Leaving this version by choice: do not offer it again at every launch.
        self._settings.setValue(SKIPPED_KEY, self._info.installed)
        self._finish_and_quit()


def create(window: QWidget) -> UpdateController | None:
    """The controller for this app, or ``None`` where updating does not apply.

    Only the downloaded Mac app can replace itself, and only a build that
    carries the release authority's certificate can check what it downloads.
    """
    bundle = update.app_bundle()
    authority = update.load_authority()

    if bundle is None or authority is None:
        return None

    info = AppInfo(
        bundle=bundle,
        support=update.support_dir(),
        authority=authority,
        installed=update.current_version(),
        arch=update.machine_arch(),
        bundled_crl=update.load_bundled_crl(),
    )
    return UpdateController(window, info, QtFetcher(), QSettings("insta360py", APP_NAME))
