"""Python port of Insv-Marker-Extractor.

Reads the timeline markers a user pressed during recording out of .insv/.lrv
files, and optionally injects them into an Insta360 Studio project as
keyframes.

The PowerShell original shells out to insvtools.exe and re-reads temporary
.json and .meta files off disk; here :mod:`insvtools` is imported directly, so
nothing is written to the working directory just to be read back.
"""
