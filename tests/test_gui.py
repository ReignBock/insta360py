"""The marker window, driven headless through Qt's offscreen platform."""

# pylint: disable=redefined-outer-name

import os
import shutil
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
from insvmarkers.gui import EMPTY_TEXT, MainWindow  # noqa: E402

# pylint: enable=wrong-import-position,no-name-in-module

RESOURCES = Path(__file__).parent / "resources"


@pytest.fixture(scope="module")
def app() -> QApplication:
    """One application for the whole module; Qt allows only one per process."""
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def window(app: QApplication) -> MainWindow:  # pylint: disable=unused-argument
    """A fresh, empty window."""
    return MainWindow()


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
    window.add_paths([session_dir, session_dir / "VID_20260620_173803_00_029.insv"])

    assert sum(1 for row in _rows(window) if row[0].startswith("VID_")) == 1


def test_a_recording_without_markers_says_so(window: MainWindow, unmarked_session: Path) -> None:
    """An honest empty answer, and nothing to copy."""
    window.add_paths([unmarked_session])

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

    rows = _rows(window)
    assert rows[1][1] == "Could not read"
    assert "Base timestamp extraction failed" in rows[2][0]


def test_files_that_are_not_recordings_are_explained(window: MainWindow, tmp_path: Path) -> None:
    """Video files with no recording stamp in the name are not a session."""
    (tmp_path / "clip.insv").write_bytes(b"\x00" * 200)

    window.add_paths([tmp_path])

    assert not _rows(window)
    assert window._status.text().startswith("No recordings found.")  # pylint: disable=protected-access
    assert window._pages.currentWidget() is window._empty  # pylint: disable=protected-access


def test_clear_empties_the_window(window: MainWindow, session_dir: Path) -> None:
    """Back to the starting state."""
    window.add_paths([session_dir])

    window.clear()

    assert not _rows(window)
    assert window._status.text() == ""  # pylint: disable=protected-access
    assert not window._clear.isEnabled()  # pylint: disable=protected-access


def test_the_report_matches_the_command_line_file(window: MainWindow, session_dir: Path) -> None:
    """The same text as ``insv-markers -o``, raw seconds included."""
    window.add_paths([session_dir])

    text = window.report_text()

    assert text.startswith("Sequence: VID_20260620_173803 (2 files)\n" + "-" * 40)
    assert "Marker 01 : 00:04:52       292.60s" in text


def test_copy_puts_the_report_on_the_clipboard(window: MainWindow, session_dir: Path) -> None:
    """Copy hands the same text to the clipboard."""
    window.add_paths([session_dir])

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

    window.save_report()

    assert target.read_text(encoding="utf-8") == window.report_text()
    assert window._status.text() == f"Saved to {target}."  # pylint: disable=protected-access


def test_cancelling_save_writes_nothing(
    window: MainWindow, session_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty name from the dialog means the user backed out."""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
    window.add_paths([session_dir])
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

    window.save_report()

    assert len(shown) == 1
    assert "Could not save" in shown[0]


def test_the_file_dialog_adds_the_chosen_files(
    window: MainWindow, x5_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add Files reads whatever the dialog returns."""
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_a, **_k: ([str(x5_insv)], ""))

    window.choose_files()

    assert _rows(window)[0][1] == "3 markers"


def test_the_folder_dialog_adds_the_chosen_folder(
    window: MainWindow, session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add Folder reads the chosen folder."""
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(session_dir))

    window.choose_folder()

    assert _rows(window)[1][0] == "VID_20260620_173803 (2 files)"


def test_cancelling_the_folder_dialog_adds_nothing(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty name means the user backed out."""
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")

    window.choose_folder()

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

    tree = window._tree  # pylint: disable=protected-access
    tops: list[str] = []
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        assert item is not None
        tops.append(item.text(0))
    assert tops == [str(nested_footage), "VID_20260701_120000 (1 file)"]


def test_the_wait_cursor_is_restored_after_a_search(window: MainWindow, session_dir: Path) -> None:
    """The busy cursor must not outlive the search."""
    window.add_paths([session_dir])

    assert QApplication.overrideCursor() is None


def test_the_wait_cursor_is_restored_when_a_search_fails(
    window: MainWindow, session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error mid-search still puts the normal cursor back."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk gone")

    monkeypatch.setattr(gui, "scan", fail)

    with pytest.raises(RuntimeError):
        window.add_paths([session_dir])

    assert QApplication.overrideCursor() is None
