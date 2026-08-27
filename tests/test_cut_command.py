"""Output naming and file grouping, ported from CutCommandTest.java."""

# pytest passes fixtures as arguments named after the fixture, which pylint
# reads as shadowing.
# pylint: disable=redefined-outer-name

from pathlib import Path

from insvtools.commands.cut import cut_file_for, files_to_process


def _names(main_file: str, *listing: str, out_file: str | None = None) -> set[str]:
    return {
        p.name
        for p in files_to_process(
            Path(main_file), out_file, True, [Path(f) for f in listing]
        )
    }


def test_cut_file_for_without_out_file() -> None:
    """Default naming adds a .cut infix."""
    main = Path("VID_20231203_220002_00_117.insv")

    for source, expected in [
        ("LRV_20231203_220002_00_117.insv", "LRV_20231203_220002_00_117.cut.insv"),
        ("VID_20231203_220002_00_117.insv", "VID_20231203_220002_00_117.cut.insv"),
        ("VID_20231203_220002_10_117.insv", "VID_20231203_220002_10_117.cut.insv"),
        ("VID_20231203_220002_10_117.mp4", "VID_20231203_220002_10_117.cut.mp4"),
        ("LRV_20231203_220002_10_117.lrv", "LRV_20231203_220002_10_117.cut.lrv"),
    ]:
        assert cut_file_for(main, None, Path(source)).name == expected


def test_cut_file_for_with_out_file_matching_main_name() -> None:
    """Siblings substitute their own stem."""
    main = Path("VID_20231203_220002_00_117.insv")
    out = "CUT_VID_20231203_220002_00_117.CUT"

    for source, expected in [
        ("LRV_20231203_220002_00_117.insv", "CUT_LRV_20231203_220002_00_117.CUT"),
        ("VID_20231203_220002_00_117.insv", "CUT_VID_20231203_220002_00_117.CUT"),
        ("VID_20231203_220002_10_117.insv", "CUT_VID_20231203_220002_10_117.CUT"),
        ("VID_20231203_220002_10_117.mp4", "CUT_VID_20231203_220002_10_117.CUT"),
    ]:
        assert cut_file_for(main, out, Path(source)).name == expected


def test_cut_file_for_with_out_file_not_matching_main_name() -> None:
    """Only the main file takes the given name."""
    main = Path("VID_20231203_220002_00_117.insv")
    out = "cut_file.insv"

    for source, expected in [
        ("LRV_20231203_220002_00_117.insv", "LRV_20231203_220002_00_117.cut.insv"),
        ("VID_20231203_220002_00_117.insv", "cut_file.insv"),
        ("VID_20231203_220002_10_117.insv", "VID_20231203_220002_10_117.cut.insv"),
        ("VID_20231203_220002_10_117.mp4", "VID_20231203_220002_10_117.cut.mp4"),
    ]:
        assert cut_file_for(main, out, Path(source)).name == expected


def test_groups_siblings_of_the_same_recording() -> None:
    """Grouping keys on prefix, timestamp and trailing number."""
    listing = (
        "VID_20231203_220002_00_117.insv",
        "VID_20231203_220002_01_117.insv",
        "LRV_20231203_220002_00_117.insv",
        "TST_20231203_220002_00_117.insv",
        "VID_20231203_220002_00_118.insv",
        "LRV_20231203_220002_00_118.insv",
    )
    expected = {
        "VID_20231203_220002_00_117.insv",
        "VID_20231203_220002_01_117.insv",
        "LRV_20231203_220002_00_117.insv",
    }

    for main in ("VID_20231203_220002_00_117.insv", "VID_20231203_220002_01_117.insv"):
        assert _names(main, *listing) == expected


def test_insv_and_lrv_are_interchangeable() -> None:
    """.insv and .lrv match each other."""
    listing = (
        "VID_20240414_135511_00_027.insv",
        "VID_20240414_135511_00_028.insv",
        "VID_20240414_135511_00_027.mp4",
        "LRV_20240414_135511_01_027.lrv",
    )
    expected = {"VID_20240414_135511_00_027.insv", "LRV_20240414_135511_01_027.lrv"}

    for main in ("VID_20240414_135511_00_027.insv", "LRV_20240414_135511_01_027.lrv"):
        assert _names(main, *listing) == expected


def test_prefix_and_extension_are_honoured() -> None:
    """A prefix and extension both narrow the group."""
    assert _names(
        "PRO_VID_20221010_115706_00_002.mp4",
        "PRO_VID_20221010_115706_00_002.mp4",
        "PRO_LRV_20221010_115706_01_002.mp4",
        "PRO_LRV_20221010_115706_01_002.insv",
        "PRO_VID_20221010_115706_00_003.mp4",
        "VID_20221010_115706_00_002.mp4",
        "LRV_20221010_115706_01_002.mp4",
    ) == {
        "PRO_VID_20221010_115706_00_002.mp4",
        "PRO_LRV_20221010_115706_01_002.mp4",
    }


def test_grouping_disabled_processes_one_file() -> None:
    """--no-group processes only the named file."""
    main = Path("VID_20231203_220002_00_117.insv")

    assert files_to_process(main, None, group=False) == {
        main: Path("VID_20231203_220002_00_117.cut.insv")
    }
