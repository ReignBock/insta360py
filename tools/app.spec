# PyInstaller spec for the macOS app. Run through tools/build-app.sh.
#
# The app carries its own Python and Qt, so a user installs nothing. The
# version comes from the installed package, which keeps the app, the wheel and
# `insvtools --version` in step.
from importlib.metadata import version
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

VERSION = version("insta360py")

# The running app reads its own version from package metadata, which
# PyInstaller does not collect unless asked.
datas = copy_metadata("insta360py")

# What updates are checked against: the release authority's certificate, and
# the revocation list as it was at build time. The certificate is required; the
# list is optional because the app also downloads the current one.
PACKAGE = Path(SPECPATH).parent / "src" / "insvmarkers"
for name in ("release_ca.pem", "release_crl.pem"):
    if (PACKAGE / name).is_file():
        datas.append((str(PACKAGE / name), "insvmarkers"))

analysis = Analysis(
    ["app_entry.py"],
    pathex=["../src"],
    datas=datas,
    # Qt pieces the window never loads. Dropping them keeps the download small.
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf"],
)

app = EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Insta360 Markers",
    console=False,
)

bundle = BUNDLE(
    COLLECT(app, analysis.binaries, analysis.datas, name="Insta360 Markers"),
    name="Insta360 Markers.app",
    bundle_identifier="io.github.reignbock.insta360py",
    info_plist={
        "CFBundleName": "Insta360 Markers",
        "CFBundleDisplayName": "Insta360 Markers",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
    },
)
