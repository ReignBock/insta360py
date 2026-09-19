"""A desktop window for reading the markers of Insta360 footage.

The window takes footage by drag and drop or from a file dialog, lists each
recording with its markers, and copies or saves the list as text. It reads
files and never changes them.

Everything that decides what to show lives in :mod:`insvmarkers.results`. This
module only arranges it on screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

# pylint reads no compiled extensions, so it cannot see Qt's names.
# pylint: disable=no-name-in-module
from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
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

from .extractor import VIDEO_SUFFIXES, Sequence, expand_paths, format_timestamp
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


class MainWindow(QMainWindow):  # pylint: disable=too-many-instance-attributes  # a window holds its widgets
    """The one window of the app."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(720, 520)
        self.setAcceptDrops(True)

        self._paths: list[Path] = []
        # Every recording found, in the order shown. Pending ones are read one
        # at a time from the event loop, so the window stays responsive.
        self._results: dict[Sequence, SessionResult] = {}
        self._items: dict[Sequence, QTreeWidgetItem] = {}
        self._queue: list[Sequence] = []
        self._reader = QTimer(self)
        self._reader.setSingleShot(True)
        self._reader.timeout.connect(self._read_next)
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

        add_files = QPushButton("Add Files…")
        add_files.clicked.connect(self.choose_files)
        add_folder = QPushButton("Add Folder…")
        add_folder.clicked.connect(self.choose_folder)
        self._clear = QPushButton("Clear")
        self._clear.clicked.connect(self.clear)
        self._copy = QPushButton("Copy")
        self._copy.clicked.connect(self.copy_report)
        self._save = QPushButton("Save…")
        self._save.clicked.connect(self.save_report)

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
        """Add files or folders, list the recordings they hold, then read each in turn.

        The list appears as soon as the folders are walked, with every
        recording marked as reading. Recordings read earlier keep their result.
        """
        for path in paths:
            if path not in self._paths:
                self._paths.append(path)

        # Walking a large folder can take a while; show that the app is busy.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            found = find_recordings(expand_paths(self._paths, recursive=True))
        finally:
            QApplication.restoreOverrideCursor()

        self._reader.stop()
        done = {sequence: result for sequence, result in self._results.items() if not result.pending}
        self._results = {entry.sequence: done.get(entry.sequence, entry) for entry in found}
        self._queue = [sequence for sequence, result in self._results.items() if result.pending]
        self._refresh(searched=True)
        self._reader.start(0)

    @property
    def reading(self) -> bool:
        """Whether recordings are still waiting to be read."""
        return bool(self._queue)

    def _read_next(self) -> None:
        """Read the next waiting recording and update its row."""
        if not self._queue:
            return

        sequence = self._queue.pop(0)
        result = read_session(sequence)
        self._results[sequence] = result
        self._fill_session(self._items[sequence], result)
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
        self._reader.stop()
        self._queue.clear()
        self._paths.clear()
        self._results = {}
        self._refresh()

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

        results = list(self._results.values())
        folders, loose = group_by_folder(results, [path for path in self._paths if path.is_dir()])
        for folder in folders:
            self._tree.addTopLevelItem(self._folder_item(folder, top=True))
        for result in loose:
            self._tree.addTopLevelItem(self._session_item(result))
        self._tree.expandAll()
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
