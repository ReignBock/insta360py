"""Port of CutCommandTest.java.

These cases pin down output naming and file grouping, both of which are pure
string logic upstream, so they transfer verbatim.
"""

from pathlib import Path

from insvtools.commands.cut import CutCommand


def _cut_command(file_name: str, cut_file_name: str | None) -> CutCommand:
    return CutCommand(file_name, cut_file_name, 0, 0, 0, False)


def _files_to_process(main_file: str, *files_list: str) -> dict[Path, Path]:
    command = CutCommand(main_file, None, 0, 0, 0, True)
    command.list_files = lambda accept: [Path(f) for f in files_list if accept(Path(f))]
    return command.files_to_process()


def test_cut_file_for_without_out_file() -> None:
    cmd = _cut_command("VID_20231203_220002_00_117.insv", None)

    assert cmd.cut_file_for(Path("LRV_20231203_220002_00_117.insv")).name == \
        "LRV_20231203_220002_00_117.cut.insv"
    assert cmd.cut_file_for(Path("VID_20231203_220002_00_117.insv")).name == \
        "VID_20231203_220002_00_117.cut.insv"
    assert cmd.cut_file_for(Path("VID_20231203_220002_10_117.insv")).name == \
        "VID_20231203_220002_10_117.cut.insv"
    assert cmd.cut_file_for(Path("VID_20231203_220002_10_117.mp4")).name == \
        "VID_20231203_220002_10_117.cut.mp4"
    assert cmd.cut_file_for(Path("LRV_20231203_220002_10_117.lrv")).name == \
        "LRV_20231203_220002_10_117.cut.lrv"


def test_cut_file_for_with_out_file_matching_main_name() -> None:
    cmd = _cut_command("VID_20231203_220002_00_117.insv", "CUT_VID_20231203_220002_00_117.CUT")

    assert cmd.cut_file_for(Path("LRV_20231203_220002_00_117.insv")).name == \
        "CUT_LRV_20231203_220002_00_117.CUT"
    assert cmd.cut_file_for(Path("VID_20231203_220002_00_117.insv")).name == \
        "CUT_VID_20231203_220002_00_117.CUT"
    assert cmd.cut_file_for(Path("VID_20231203_220002_10_117.insv")).name == \
        "CUT_VID_20231203_220002_10_117.CUT"
    assert cmd.cut_file_for(Path("VID_20231203_220002_10_117.mp4")).name == \
        "CUT_VID_20231203_220002_10_117.CUT"


def test_cut_file_for_with_out_file_not_matching_main_name() -> None:
    cmd = _cut_command("VID_20231203_220002_00_117.insv", "cut_file.insv")

    assert cmd.cut_file_for(Path("LRV_20231203_220002_00_117.insv")).name == \
        "LRV_20231203_220002_00_117.cut.insv"
    assert cmd.cut_file_for(Path("VID_20231203_220002_00_117.insv")).name == "cut_file.insv"
    assert cmd.cut_file_for(Path("VID_20231203_220002_10_117.insv")).name == \
        "VID_20231203_220002_10_117.cut.insv"
    assert cmd.cut_file_for(Path("VID_20231203_220002_10_117.mp4")).name == \
        "VID_20231203_220002_10_117.cut.mp4"


def test_files_to_process_groups_siblings() -> None:
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
        found = {p.name for p in _files_to_process(main, *listing)}
        assert found == expected


def test_files_to_process_treats_insv_and_lrv_as_interchangeable() -> None:
    listing = (
        "VID_20240414_135511_00_027.insv",
        "VID_20240414_135511_00_028.insv",
        "VID_20240414_135511_00_027.mp4",
        "LRV_20240414_135511_01_027.lrv",
    )
    expected = {"VID_20240414_135511_00_027.insv", "LRV_20240414_135511_01_027.lrv"}

    for main in ("VID_20240414_135511_00_027.insv", "LRV_20240414_135511_01_027.lrv"):
        found = {p.name for p in _files_to_process(main, *listing)}
        assert found == expected


def test_files_to_process_honours_prefix_and_extension() -> None:
    found = {
        p.name
        for p in _files_to_process(
            "PRO_VID_20221010_115706_00_002.mp4",
            "PRO_VID_20221010_115706_00_002.mp4",
            "PRO_LRV_20221010_115706_01_002.mp4",
            "PRO_LRV_20221010_115706_01_002.insv",
            "PRO_VID_20221010_115706_00_003.mp4",
            "VID_20221010_115706_00_002.mp4",
            "LRV_20221010_115706_01_002.mp4",
        )
    }

    assert found == {
        "PRO_VID_20221010_115706_00_002.mp4",
        "PRO_LRV_20221010_115706_01_002.mp4",
    }
