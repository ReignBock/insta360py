"""The marker window, driven headless through Qt's offscreen platform."""

# pylint: disable=redefined-outer-name

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

# Set before Qt loads: the suite must run with no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

# The imports below need PySide6, so they follow importorskip.
# pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QTreeWidgetItem  # noqa: E402

from insvmarkers import gui  # noqa: E402
from insvmarkers.gui import EMPTY_TEXT, MainWindow, _Walker  # noqa: E402

# pylint: enable=wrong-import-position,no-name-in-module

RESOURCES = Path(__file__).parent / "resources"


@pytest.fixture(scope="module")
def app() -> QApplication:
    """One application for the whole module; Qt allows only one per process."""
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def window(app: QApplication) -> Iterator[MainWindow]:  # pylint: disable=unused-argument
    """A fresh, empty window. Closing it afterwards waits for any walk still running."""
    opened = MainWindow()
    yield opened
    opened.close()


READ_NEXT = MainWindow._read_next  # pylint: disable=protected-access


@pytest.fixture
def held_window(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:  # pylint: disable=unused-argument
    """A window that finds recordings but never reads them, until a test calls ``_read_one``."""
    monkeypatch.setattr(MainWindow, "_read_next", lambda self: None)
    opened = MainWindow()
    yield opened
    opened.close()


def _read_one(window: MainWindow) -> None:
    """Read the next queued recording on a ``held_window``."""
    READ_NEXT(window)


def _walked(window: MainWindow) -> None:
    """Let the search finish, without asking for the reading to finish too."""
    while window._walker is not None:  # pylint: disable=protected-access
        QApplication.processEvents()


def _rows(window: MainWindow) -> list[list[str]]:
    """Every row of the list as text, sessions first then their children."""
    root = window._tree.invisibleRootItem()  # pylint: disable=protected-access
    rows: list[list[str]] = []

    def visit(item: QTreeWidgetItem) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            assert child is not None
            rows.append([child.text(column) for column in range(3)])
            visit(child)

    visit(root)

    return rows


def _settle(window: MainWindow) -> None:
    """Let the window read every recording it has queued."""
    while window.reading:
        QApplication.processEvents()

    for walker in window._retired:  # pylint: disable=protected-access
        walker.wait()


def _drop(window: MainWindow, paths: list[Path]) -> None:
    """Deliver a drop of local files to the window."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)


def test_a_new_window_asks_for_footage(window: MainWindow) -> None:
    """Nothing to share yet, so the share buttons are off and the hint shows."""
    assert window._empty.text() == EMPTY_TEXT  # pylint: disable=protected-access
    assert window._pages.currentWidget() is window._empty  # pylint: disable=protected-access
    assert not window._copy.isEnabled()  # pylint: disable=protected-access
    assert not window._save.isEnabled()  # pylint: disable=protected-access
    assert not window._clear.isEnabled()  # pylint: disable=protected-access
    assert window.report_text() == ""


def test_a_folder_lists_the_markers_of_its_recording(window: MainWindow, session_dir: Path) -> None:
    """One recording of two chapters, with its three markers under it."""
    window.add_paths([session_dir])
    _settle(window)

    assert _rows(window) == [
        [str(session_dir), "1 recording", ""],
        ["VID_20260620_173803 (2 files)", "3 markers", ""],
        ["Marker 01", "00:04:52", "292.60"],
        ["Marker 02", "00:18:13", "1093.76"],
        ["Marker 03", "00:29:16", "1756.38"],
    ]
    assert window._status.text() == "3 markers in 1 recording."  # pylint: disable=protected-access
    assert window._pages.currentWidget() is window._tree  # pylint: disable=protected-access
    assert window._copy.isEnabled()  # pylint: disable=protected-access


def test_a_dropped_file_is_read(window: MainWindow, x5_insv: Path) -> None:
    """Dropping one chapter reports the whole recording it belongs to."""
    _drop(window, [x5_insv])
    _settle(window)

    assert _rows(window)[0][1] == "3 markers"


def test_a_drag_with_files_is_accepted(window: MainWindow, x5_insv: Path) -> None:
    """The window signals that it takes files."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(x5_insv))])
    event = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.ignore()

    window.dragEnterEvent(event)

    assert event.isAccepted()


def test_a_drag_without_files_is_refused(window: MainWindow) -> None:
    """Dragging selected text over the window does nothing."""
    mime = QMimeData()
    mime.setText("not a file")
    event = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.ignore()

    window.dragEnterEvent(event)

    assert not event.isAccepted()


def test_a_drop_of_something_that_is_not_local_is_ignored(window: MainWindow) -> None:
    """A web link has no file to read."""
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/clip.insv")])
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    window.dropEvent(event)

    assert not _rows(window)


def test_adding_the_same_footage_twice_lists_it_once(window: MainWindow, session_dir: Path) -> None:
    """Dropping a file after its folder must not repeat the recording."""
    window.add_paths([session_dir])
    _settle(window)
    window.add_paths([session_dir, session_dir / "VID_20260620_173803_00_029.insv"])
    _settle(window)

    assert sum(1 for row in _rows(window) if row[0].startswith("VID_")) == 1


def test_a_recording_without_markers_says_so(window: MainWindow, unmarked_session: Path) -> None:
    """An honest empty answer, and nothing to copy."""
    window.add_paths([unmarked_session])
    _settle(window)

    assert _rows(window) == [
        [str(unmarked_session), "1 recording", ""],
        ["VID_20221218_231825 (1 file)", "No markers", ""],
    ]
    assert window._status.text() == "0 markers in 1 recording."  # pylint: disable=protected-access
    assert not window._copy.isEnabled()  # pylint: disable=protected-access


def test_an_unreadable_recording_reports_why(window: MainWindow, tmp_path: Path) -> None:
    """One broken file shows its reason and does not stop the window."""
    (tmp_path / "VID_20260620_173803_00_029.insv").write_bytes(b"\x00" * 200)

    window.add_paths([tmp_path])
    _settle(window)

    rows = _rows(window)
    assert rows[1][1] == "Could not read"
    assert "Base timestamp extraction failed" in rows[2][0]


def test_files_that_are_not_recordings_are_explained(window: MainWindow, tmp_path: Path) -> None:
    """Video files with no recording stamp in the name are not a session."""
    (tmp_path / "clip.insv").write_bytes(b"\x00" * 200)

    window.add_paths([tmp_path])
    _settle(window)

    assert not _rows(window)
    assert window._status.text().startswith("No recordings found.")  # pylint: disable=protected-access
    assert window._pages.currentWidget() is window._empty  # pylint: disable=protected-access


def test_clear_empties_the_window(window: MainWindow, session_dir: Path) -> None:
    """Back to the starting state."""
    window.add_paths([session_dir])
    _settle(window)

    window.clear()

    assert not _rows(window)
    assert window._status.text() == ""  # pylint: disable=protected-access
    assert not window._clear.isEnabled()  # pylint: disable=protected-access


def test_the_report_matches_the_command_line_file(window: MainWindow, session_dir: Path) -> None:
    """The same text as ``insv-markers -o``, raw seconds included."""
    window.add_paths([session_dir])
    _settle(window)

    text = window.report_text()

    assert text.startswith("Sequence: VID_20260620_173803 (2 files)\n" + "-" * 40)
    assert "Marker 01 : 00:04:52       292.60s" in text


def test_copy_puts_the_report_on_the_clipboard(window: MainWindow, session_dir: Path) -> None:
    """Copy hands the same text to the clipboard."""
    window.add_paths([session_dir])
    _settle(window)

    window.copy_report()

    assert QApplication.clipboard().text() == window.report_text()
    assert window._status.text() == "Copied to the clipboard."  # pylint: disable=protected-access


def test_save_writes_the_report(
    window: MainWindow, session_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chosen file receives the report."""
    target = tmp_path / "out" / "markers.txt"
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(target), ""))
    window.add_paths([session_dir])
    _settle(window)

    window.save_report()

    assert target.read_text(encoding="utf-8") == window.report_text()
    assert window._status.text() == f"Saved to {target}."  # pylint: disable=protected-access


def test_cancelling_save_writes_nothing(
    window: MainWindow, session_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty name from the dialog means the user backed out."""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
    window.add_paths([session_dir])
    _settle(window)
    before = window._status.text()  # pylint: disable=protected-access

    window.save_report()

    assert window._status.text() == before  # pylint: disable=protected-access
    assert not list(tmp_path.glob("*.txt"))


def test_a_failed_save_warns_the_user(
    window: MainWindow, session_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder that does not exist produces a message, not a crash."""
    shown: list[str] = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(tmp_path / "missing" / "m.txt"), "")
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: shown.append(text))
    window.add_paths([session_dir])
    _settle(window)

    window.save_report()

    assert len(shown) == 1
    assert "Could not save" in shown[0]


def test_the_file_dialog_adds_the_chosen_files(
    window: MainWindow, x5_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add Files reads whatever the dialog returns."""
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_a, **_k: ([str(x5_insv)], ""))

    window.choose_files()
    _settle(window)

    assert _rows(window)[0][1] == "3 markers"


def test_the_folder_dialog_adds_the_chosen_folder(
    window: MainWindow, session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add Folder reads the chosen folder."""
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(session_dir))

    window.choose_folder()
    _settle(window)

    assert _rows(window)[1][0] == "VID_20260620_173803 (2 files)"


def test_cancelling_the_folder_dialog_adds_nothing(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty name means the user backed out."""
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")

    window.choose_folder()
    _settle(window)

    assert not _rows(window)
    assert window._status.text() == ""  # pylint: disable=protected-access


def test_main_shows_the_window_and_reads_the_paths_given(
    app: QApplication, session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Launching with a folder, as a desktop launcher does, reads it at once."""
    opened: list[MainWindow] = []
    monkeypatch.setattr(MainWindow, "show", lambda self: opened.append(self))  # pylint: disable=unnecessary-lambda
    monkeypatch.setattr(app, "exec", lambda: 0)

    assert gui.main(["insv-markers-gui", str(session_dir)]) == 0

    assert len(opened) == 1
    _settle(opened[0])
    assert _rows(opened[0])[1][1] == "3 markers"


def test_main_opens_empty_without_arguments(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """Double-clicking the app starts with nothing loaded."""
    opened: list[MainWindow] = []
    monkeypatch.setattr(MainWindow, "show", lambda self: opened.append(self))  # pylint: disable=unnecessary-lambda
    monkeypatch.setattr(app, "exec", lambda: 0)

    assert gui.main(["insv-markers-gui"]) == 0

    assert not _rows(opened[0])


def test_a_folder_search_shows_every_folder_on_the_way_to_the_footage(
    window: MainWindow, nested_footage: Path
) -> None:
    """The searched folder shows its path, and each folder below shows its name."""
    window.add_paths([nested_footage])
    _settle(window)

    rows = _rows(window)

    assert [row[0] for row in rows if not row[0].startswith("Marker")] == [
        str(nested_footage),
        "card1",
        "DCIM",
        "Camera01",
        "VID_20260620_173803 (1 file)",
        "card2",
        "DCIM",
        "Camera01",
        "VID_20260621_090000 (1 file)",
    ]
    assert rows[0][1] == "2 recordings"
    assert rows[1][1] == "1 recording"
    assert window._status.text() == "6 markers in 2 recordings."  # pylint: disable=protected-access


def test_folders_with_no_footage_do_not_appear(window: MainWindow, nested_footage: Path) -> None:
    """The window lists the route to footage and nothing else."""
    window.add_paths([nested_footage])
    _settle(window)

    names = [row[0] for row in _rows(window)]

    assert "Notes" not in names
    assert "empty" not in names
    assert ".Trashes" not in names


def test_a_loose_file_is_listed_beside_a_searched_folder(
    window: MainWindow, nested_footage: Path, tmp_path: Path
) -> None:
    """Files added one by one are not put under a folder they are not in."""
    loose = tmp_path / "loose" / "VID_20260701_120000_00_029.insv"
    loose.parent.mkdir()
    shutil.copy(RESOURCES / "x5_indexed.insv", loose)

    window.add_paths([nested_footage, loose])
    _settle(window)

    tree = window._tree  # pylint: disable=protected-access
    tops: list[str] = []
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        assert item is not None
        tops.append(item.text(0))
    assert tops == [str(nested_footage), "VID_20260701_120000 (1 file)"]


def test_the_search_does_not_block_the_caller(window: MainWindow, session_dir: Path) -> None:
    """add_paths returns at once, with the walk still to do."""
    window.add_paths([session_dir])

    assert window.reading
    assert not _rows(window)
    assert window._status.text().startswith("Searching folders")  # pylint: disable=protected-access

    _settle(window)


def test_the_walker_reports_each_folder_then_finishes(window: MainWindow, nested_footage: Path) -> None:
    """Run in this thread, the walk emits a batch per folder and then done."""
    walker = _Walker(7, [nested_footage], window)
    seen: list[tuple[str, int, int]] = []
    walker.found.connect(lambda token, videos: seen.append(("found", token, len(videos))))
    walker.done.connect(lambda token: seen.append(("done", token, 0)))

    walker.run()

    assert seen == [("found", 7, 1), ("found", 7, 1), ("done", 7, 0)]


def test_a_walker_asked_to_stop_reports_nothing_more(
    window: MainWindow, nested_footage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted walk ends without a done signal."""
    walker = _Walker(7, [nested_footage], window)
    seen: list[int] = []
    walker.found.connect(lambda token, _videos: seen.append(token))
    walker.done.connect(seen.append)
    # Qt only honours a request on a running thread, and this one runs here.
    monkeypatch.setattr(walker, "isInterruptionRequested", lambda: True)

    walker.run()

    assert not seen


def test_the_folders_are_listed_before_any_recording_is_read(held_window: MainWindow, session_dir: Path) -> None:
    """The structure shows once the walk ends, each recording marked as reading."""
    held_window.add_paths([session_dir])
    _walked(held_window)

    assert held_window.reading
    assert _rows(held_window)[1] == ["VID_20260620_173803 (2 files)", "Reading…", ""]
    assert "0 of 1 recording" in held_window._status.text()  # pylint: disable=protected-access
    assert not held_window._copy.isEnabled()  # pylint: disable=protected-access

    _read_one(held_window)

    assert _rows(held_window)[1][1] == "3 markers"
    assert held_window._copy.isEnabled()  # pylint: disable=protected-access


def test_recordings_are_read_one_at_a_time(held_window: MainWindow, nested_footage: Path) -> None:
    """Each turn reads one recording, so the window keeps responding."""
    held_window.add_paths([nested_footage])
    _walked(held_window)
    total = len(held_window._results)  # pylint: disable=protected-access
    assert total == 2

    _read_one(held_window)

    assert held_window._queue  # pylint: disable=protected-access
    assert f"1 of {total} recordings" in held_window._status.text()  # pylint: disable=protected-access


def test_a_recording_can_be_read_before_it_is_drawn(window: MainWindow, x5_insv: Path) -> None:
    """Reading a recording the redraw has not reached yet just keeps its result."""
    # pylint: disable=protected-access
    window._on_found(window._token, [x5_insv])
    window._reader.stop()
    window._redraw.stop()
    sequence = next(iter(window._results))
    assert window._results[sequence].pending

    window._read_next()

    assert window._results[sequence].markers
    assert not window._items


def test_a_recording_found_twice_is_listed_once(window: MainWindow, x5_insv: Path) -> None:
    """Two folders that hold the same session give one recording."""
    # pylint: disable=protected-access
    window._on_found(window._token, [x5_insv])
    window._on_found(window._token, [x5_insv])
    window._reader.stop()
    window._redraw.stop()

    assert len(window._results) == 1
    assert len(window._queue) == 1


def test_a_walk_that_was_replaced_is_ignored(window: MainWindow, x5_insv: Path) -> None:
    """Late results from an old walk change nothing."""
    # pylint: disable=protected-access
    window._on_found(window._token + 1, [x5_insv])
    window._on_done(window._token + 1)

    assert not window._results
    assert not window._queue


def test_adding_again_while_searching_starts_over(window: MainWindow, nested_footage: Path) -> None:
    """A second add replaces the walk in progress and every recording is listed once."""
    window.add_paths([nested_footage])
    window.add_paths([nested_footage])
    _settle(window)

    assert len([row for row in _rows(window) if row[0].startswith("VID_")]) == 2


def test_closing_the_window_stops_the_walk(window: MainWindow, nested_footage: Path) -> None:
    """The thread is finished by the time the window has closed."""
    window.add_paths([nested_footage])

    window.close()

    assert not window.reading
    assert all(walker.isFinished() for walker in window._retired)  # pylint: disable=protected-access


def test_adding_more_footage_keeps_what_was_already_read(
    window: MainWindow, session_dir: Path, x5_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished recording is not read again when the list is rebuilt."""
    window.add_paths([session_dir])
    _settle(window)
    calls: list[object] = []
    real = gui.read_session

    def counting(sequence: object) -> object:
        calls.append(sequence)
        return real(sequence)  # type: ignore[arg-type]

    monkeypatch.setattr(gui, "read_session", counting)

    window.add_paths([x5_insv])
    _settle(window)

    assert not calls


def test_clearing_stops_the_search(window: MainWindow, nested_footage: Path) -> None:
    """Nothing is listed after Clear, even from a walk that was still going."""
    window.add_paths([nested_footage])

    window.clear()
    _settle(window)

    assert not window.reading
    assert not _rows(window)


def test_reading_with_nothing_queued_does_nothing(window: MainWindow) -> None:
    """A timer that fires after Clear finds no work."""
    window._read_next()  # pylint: disable=protected-access

    assert not _rows(window)


def test_an_updater_adds_a_help_menu_and_starts(window: MainWindow) -> None:
    """The window hands its menu bar to the updater and lets it start checking."""
    calls: list[str] = []

    class FakeUpdater:
        """Records what the window asks of it."""

        def attach_menu(self, menu_bar: object) -> None:
            """Note the menu bar it was given."""
            calls.append(f"menu:{menu_bar is window.menuBar()}")

        def start(self) -> None:
            """Note that checking began."""
            calls.append("start")

    window.use_updater(FakeUpdater())  # type: ignore[arg-type]

    assert calls == ["menu:True", "start"]
    assert window._updater is not None  # pylint: disable=protected-access


def test_main_starts_the_updater_when_there_is_one(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """The downloaded app checks for updates as it opens."""
    started: list[MainWindow] = []
    monkeypatch.setattr(MainWindow, "show", lambda self: None)  # pylint: disable=unnecessary-lambda
    monkeypatch.setattr(app, "exec", lambda: 0)
    monkeypatch.setattr(gui, "create_updater", lambda window: window)
    monkeypatch.setattr(MainWindow, "use_updater", lambda self, controller: started.append(controller))

    assert gui.main(["insv-markers-gui"]) == 0

    assert len(started) == 1
