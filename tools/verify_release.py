"""Check a downloaded release file the way the Mac app does.

    uv run --with cryptography python tools/verify_release.py Insta360-Markers-0.4.0-arm64.zip

Reads ``FILE.sig`` and ``FILE.crt`` beside the file. By default it trusts the
release authority and revocation list in ``src/insvmarkers``. Pass
``--authority`` to check against a certificate you obtained some other way, and
``--crl`` (repeatable) to add a newer revocation list, such as the current one
from the repository. Prints ``valid`` and exits 0 if the file may be installed.
Otherwise it says which check failed and exits 1.
"""

import argparse
import sys
from pathlib import Path

from insvmarkers import update


def main(arguments: list[str]) -> int:
    """Verify one file."""
    parser = argparse.ArgumentParser(
        prog="verify_release.py", description="Check a downloaded release file the way the Mac app does."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--authority", type=Path, help="the release authority's certificate (PEM)")
    parser.add_argument("--crl", type=Path, action="append", default=[], help="a revocation list (PEM)")
    args = parser.parse_args(arguments)

    try:
        data = args.file.read_bytes()
        signature = Path(f"{args.file}.sig").read_bytes()
        certificate = Path(f"{args.file}.crt").read_bytes()
        authority = args.authority.read_bytes() if args.authority else update.load_authority()
        lists = [path.read_bytes() for path in args.crl]
    except OSError as error:
        print(f"cannot read: {error}", file=sys.stderr)
        return 2

    bundled = update.load_bundled_crl()
    if bundled is not None:
        lists.append(bundled)

    if authority is None:
        print("no release authority certificate: pass --authority", file=sys.stderr)
        return 2

    try:
        update.check_release(data, signature, certificate, authority, lists, update.utcnow())
    except update.UpdateError as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1

    print("valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
