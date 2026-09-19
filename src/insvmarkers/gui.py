"""A desktop window for reading the markers of Insta360 footage.

The window takes footage by drag and drop or from a file dialog, lists each
recording with its markers, and copies or saves the list as text. It reads
files and never changes them.

Everything that decides what to show lives in :mod:`insvmarkers.results`. This
module only arranges it on screen.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

# pylint reads no compiled extensions, so it cannot see Qt's names.
# pylint: disable=no-name-in-module
from PySide6.QtCore import QMimeData, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# pylint: enable=no-name-in-module

from .extractor import VIDEO_SUFFIXES, Sequence, format_timestamp, walk_paths
from .results import (
    FolderNode,
    SessionResult,
    find_recordings,
    group_by_folder,
    read_session,
    report_lines,
)
from .updater import UpdateController, create as create_updater

APP_NAME = "Insta360 Markers"

EMPTY_TEXT = "Drop .insv or .lrv files, or a folder, on this window. Folders are searched all the way down."
VIDEO_FILTER = "Insta360 video (" + " ".join(f"*{suffix}" for suffix in VIDEO_SUFFIXES) + ")"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _local_paths(mime: QMimeData) -> list[Path]:
    """The local files and folders a drop carries."""
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


def _button(text: str, slot: Callable[[], None]) -> QPushButton:
    """A push button that calls ``slot`` when clicked."""
    button = QPushButton(text)
    button.clicked.connect(slot)

    return button


class _Walker(QThread):  # pylint: disable=too-few-public-methods  # a thread's whole job is run()
    """Walks folders off the UI thread, reporting the footage of each folder as it goes.

    ``found`` carries the walk's ``token`` so the window can ignore a walk it
    has replaced, and ``done`` follows the last ``found``.
    """

    found = Signal(int, list)
    done = Signal(int)

    def __init__(self, token: int, paths: list[Path], parent: QMainWindow) -> None:
        super().__init__(parent)
        self.token = token
        self._paths = paths

    def run(self) -> None:
        """Walk until finished or asked to stop."""
        for videos in walk_paths(self._paths):
            if self.isInterruptionRequested():
                return
            self.found.emit(self.token, videos)

        self.done.emit(self.token)


REDRAW_MS = 100


class MainWindow(QMainWindow):  # pylint: disable=too-many-instance-attributes  # a window holds its widgets
    """The one window of the app."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(720, 520)
        self.setAcceptDrops(True)

        self._paths: list[Path] = []
        # A walk runs on its own thread and reports footage folder by folder.
        # Every recording found is listed at once as pending, and the pending
        # ones are read one at a time from the event loop, so the window
        # stays responsive throughout. A new walk replaces the old one, and
        # recordings already read (``_done``) are not read again.
        self._walker: _Walker | None = None
        self._retired: list[_Walker] = []
        self._token = 0
        self._session_ids: set[str] = set()
        self._results: dict[Sequence, SessionResult] = {}
        self._done: dict[Sequence, SessionResult] = {}
        self._items: dict[Sequence, QTreeWidgetItem] = {}
        self._queue: list[Sequence] = []
        self._reader = QTimer(self)
        self._reader.setSingleShot(True)
        self._reader.timeout.connect(self._read_next)
        # Redrawing the whole list for every folder found would be slow, so
        # new footage is drawn at most this often.
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.timeout.connect(lambda: self._refresh(searched=True))
        self._updater: UpdateController | None = None

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Recording", "Time", "Seconds"])
        self._tree.setRootIsDecorated(True)
        self._tree.setColumnWidth(0, 360)

        self._empty = QLabel(EMPTY_TEXT)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)

        self._pages = QStackedLayout()
        self._pages.addWidget(self._empty)
        self._pages.addWidget(self._tree)

        self._status = QLabel("")

        add_files = _button("Add Files…", self.choose_files)
        add_folder = _button("Add Folder…", self.choose_folder)
        self._clear = _button("Clear", self.clear)
        self._copy = _button("Copy", self.copy_report)
        self._save = _button("Save…", self.save_report)

        buttons = QHBoxLayout()
        for button in (add_files, add_folder, self._clear):
            buttons.addWidget(button)
        buttons.addStretch(1)
        for button in (self._copy, self._save):
            buttons.addWidget(button)

        layout = QVBoxLayout()
        layout.addLayout(self._pages, 1)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._refresh()

    def use_updater(self, controller: UpdateController) -> None:
        """Give the window an updater: a Help menu, and a check now and daily."""
        self._updater = controller
        controller.attach_menu(self.menuBar())
        controller.start()

    # Adding footage

    def add_paths(self, paths: list[Path]) -> None:
        """Add files or folders and search them.

        Recordings show up as their folders are walked, each marked as reading
        until its markers are found. Recordings read earlier keep their result.
        """
        for path in paths:
            if path not in self._paths:
                self._paths.append(path)

        self._stop_walking()
        self._token += 1
        self._session_ids = set()
        self._results = {}
        self._queue = []
        self._walker = _Walker(self._token, list(self._paths), self)
        self._walker.found.connect(self._on_found)
        self._walker.done.connect(self._on_done)
        self._refresh(searched=True)
        self._walker.start()

    @property
    def reading(self) -> bool:
        """Whether the search or the reading of markers is still going."""
        return self._walker is not None or bool(self._queue) or self._redraw.isActive()

    def _stop_walking(self) -> None:
        """Stop the walk and the reading. A stopped walk finishes on its own."""
        self._reader.stop()
        self._redraw.stop()
        self._queue = []

        if self._walker is not None:
            self._walker.requestInterruption()
            self._retired = [walker for walker in self._retired if not walker.isFinished()] + [self._walker]
            self._walker = None

    def _on_found(self, token: int, videos: list[Path]) -> None:
        """List the recordings in one more folder, and start reading them."""
        if token != self._token:
            return

        for found in find_recordings(videos):
            sequence = found.sequence
            if sequence.session_id in self._session_ids:
                continue

            self._session_ids.add(sequence.session_id)
            self._results[sequence] = self._done.get(sequence, found)
            if sequence not in self._done:
                self._queue.append(sequence)

        if not self._redraw.isActive():
            self._redraw.start(REDRAW_MS)
        if not self._reader.isActive():
            self._reader.start(0)

    def _on_done(self, token: int) -> None:
        """The walk has listed everything: draw it and let the reading finish."""
        if token != self._token:
            return

        if self._walker is not None:
            self._retired.append(self._walker)
        self._walker = None
        self._redraw.stop()
        self._refresh(searched=True)

    def _read_next(self) -> None:
        """Read the next waiting recording and update its row."""
        if not self._queue:
            return

        sequence = self._queue.pop(0)
        result = read_session(sequence)
        self._results[sequence] = result
        self._done[sequence] = result

        # A recording found a moment ago may not be drawn yet; the redraw will.
        item = self._items.get(sequence)
        if item is not None:
            self._fill_session(item, result)
        self._update_controls(searched=True)

        if self._queue:
            self._reader.start(0)

    def choose_files(self) -> None:
        """Ask for video files."""
        names, _ = QFileDialog.getOpenFileNames(self, "Add Files", "", VIDEO_FILTER)
        self.add_paths([Path(name) for name in names])

    def choose_folder(self) -> None:
        """Ask for a folder of video files."""
        name = QFileDialog.getExistingDirectory(self, "Add Folder")
        if name:
            self.add_paths([Path(name)])

    def clear(self) -> None:
        """Forget everything added so far."""
        self._stop_walking()
        self._token += 1
        self._paths.clear()
        self._results = {}
        self._refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name
        """Stop the walk, and wait for it: a thread must not outlive its window."""
        self._stop_walking()
        for walker in self._retired:
            walker.wait()
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # pylint: disable=invalid-name
        """Accept a drag that carries files."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # pylint: disable=invalid-name
        """Read the files that were dropped."""
        self.add_paths(_local_paths(event.mimeData()))
        event.acceptProposedAction()

    # Sharing the result

    def report_text(self) -> str:
        """The markers of every recording that has any, as plain text."""
        lines: list[str] = []
        for result in self._results.values():
            if result.markers:
                lines += report_lines(result)

        return "\n".join(lines)

    def copy_report(self) -> None:
        """Put the report on the clipboard."""
        QApplication.clipboard().setText(self.report_text())
        self._status.setText("Copied to the clipboard.")

    def save_report(self) -> None:
        """Ask where to save the report, then write it."""
        name, _ = QFileDialog.getSaveFileName(self, "Save Markers", "markers.txt", "Text files (*.txt)")
        if not name:
            return

        try:
            Path(name).write_text(self.report_text(), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, APP_NAME, f"Could not save {name}.\n\n{error}")
            return

        self._status.setText(f"Saved to {name}.")

    # Drawing

    def _refresh(self, searched: bool = False) -> None:
        """Redraw the list and the controls from the current results."""
        self._tree.clear()
        self._items = {}

        scroll = self._tree.verticalScrollBar()
        position = scroll.value()
        results = list(self._results.values())
        folders, loose = group_by_folder(results, [path for path in self._paths if path.is_dir()])
        for folder in folders:
            self._tree.addTopLevelItem(self._folder_item(folder, top=True))
        for result in loose:
            self._tree.addTopLevelItem(self._session_item(result))
        self._tree.expandAll()
        scroll.setValue(position)
        self._update_controls(searched)

    def _update_controls(self, searched: bool) -> None:
        """Set the buttons and the status line from the current results."""
        marked = [result for result in self._results.values() if result.markers]
        has_report = bool(marked)

        self._pages.setCurrentWidget(self._tree if self._results else self._empty)
        self._clear.setEnabled(bool(self._paths))
        self._copy.setEnabled(has_report)
        self._save.setEnabled(has_report)
        self._status.setText(self._summary(searched, marked))

    def _summary(self, searched: bool, marked: list[SessionResult]) -> str:
        """One line saying what the last search found."""
        if not searched:
            return ""

        if self._walker is not None:
            found = _plural(len(self._results), "recording")
            return f"Searching folders: {found} found, {len(self._results) - len(self._queue)} read."

        if not self._results:
            return "No recordings found. Check that the files are .insv or .lrv files from the camera."

        if self._queue:
            read = len(self._results) - len(self._queue)
            return f"Reading markers: {read} of {_plural(len(self._results), 'recording')} done."

        count = sum(len(result.markers) for result in marked)
        return f"{_plural(count, 'marker')} in {_plural(len(self._results), 'recording')}."

    def _folder_item(self, folder: FolderNode, top: bool = False) -> QTreeWidgetItem:
        """A folder's row, with its subfolders and recordings beneath it.

        The folder that was searched shows its whole path, so it is clear where
        the search started. The folders below it show only their names.
        """
        item = QTreeWidgetItem([str(folder.path) if top else folder.path.name])
        item.setText(1, _plural(folder.recording_count, "recording"))

        for subfolder in folder.folders:
            item.addChild(self._folder_item(subfolder))
        for result in folder.sessions:
            item.addChild(self._session_item(result))

        return item

    def _session_item(self, result: SessionResult) -> QTreeWidgetItem:
        """A recording's row, filled in now if it has been read."""
        item = QTreeWidgetItem([f"{result.title} ({_plural(len(result.sequence.files), 'file')})"])
        self._items[result.sequence] = item
        self._fill_session(item, result)

        return item

    @staticmethod
    def _fill_session(item: QTreeWidgetItem, result: SessionResult) -> None:
        """Show what reading a recording found: its state, and a row for each marker."""
        item.takeChildren()

        if result.pending:
            item.setText(1, "Reading…")
        elif result.error is not None:
            item.setText(1, "Could not read")
            item.addChild(QTreeWidgetItem([result.error]))
        elif not result.markers:
            item.setText(1, "No markers")
        else:
            item.setText(1, _plural(len(result.markers), "marker"))
            for index, seconds in enumerate(result.markers, start=1):
                item.addChild(QTreeWidgetItem([f"Marker {index:02d}", format_timestamp(seconds), f"{seconds:.2f}"]))

        item.setExpanded(True)


def main(argv: list[str] | None = None) -> int:
    """Open the window. Paths on the command line are read straight away."""
    arguments = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(arguments)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    if len(arguments) > 1:
        window.add_paths([Path(argument) for argument in arguments[1:]])
    window.show()

    # None unless this is the downloaded Mac app with the release authority certificate built in.
    controller = create_updater(window)
    if controller is not None:
        window.use_updater(controller)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
