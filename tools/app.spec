# PyInstaller spec for the macOS app. Run through tools/build-app.sh.
#
# The app carries its own Python and Qt, so a user installs nothing. The
# version comes from the installed package, which keeps the app, the wheel and
# `insvtools --version` in step.
from importlib.metadata import version

VERSION = version("insta360py")

analysis = Analysis(
    ["app_entry.py"],
    pathex=["../src"],
    # Qt pieces the window never loads. Dropping them keeps the download small.
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtPdf"],
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
