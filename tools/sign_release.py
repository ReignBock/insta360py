"""Sign release files with the release key.

Run by the release workflow. Each file gets two files beside it: ``FILE.sig``,
a base64 Ed25519 signature, and ``FILE.crt``, the certificate the authority
issued to the signing key. The Mac app checks both before it installs an update.

The private key comes from ``RELEASE_SIGNING_KEY``, as PEM text. It is the
only secret. The certificate is public and is read from the repository, at
``tools/pki/release.crt``. Before writing anything this runs the same check
the app runs: the certificate must chain to the authority in
``src/insvmarkers/release_ca.pem``, be in date, not be revoked by
``release_crl.pem``, and belong to the key. A wrong secret, an expired or
revoked certificate, or a missing revocation list fails here and not on a
user's Mac.

    python tools/sign_release.py dist-app/*.zip
"""

import os
import sys
from pathlib import Path

from insvmarkers import update

RELEASE_CERT = Path(__file__).resolve().parent / "pki" / "release.crt"


def main(files: list[str]) -> int:
    """Sign each file, or say why not."""
    key = os.environ.get("RELEASE_SIGNING_KEY", "")
    authority = update.load_authority()
    revocations = update.load_bundled_crl()

    if not key:
        print("RELEASE_SIGNING_KEY must be set", file=sys.stderr)
        return 1

    if not RELEASE_CERT.is_file():
        print(f"{RELEASE_CERT} is missing. Run tools/pki/issue-release-cert.sh", file=sys.stderr)
        return 1

    certificate = RELEASE_CERT.read_bytes()

    if authority is None or revocations is None:
        print("src/insvmarkers/release_ca.pem and release_crl.pem must both exist", file=sys.stderr)
        return 1

    if not files:
        print("no files to sign", file=sys.stderr)
        return 1

    for name in files:
        data = Path(name).read_bytes()

        try:
            signature = update.sign(data, key.encode())
            update.check_release(data, signature.encode(), certificate, authority, [revocations], update.utcnow())
        except (ValueError, update.UpdateError) as error:
            print(f"cannot sign: {error}", file=sys.stderr)
            return 1

        Path(f"{name}.sig").write_text(signature + "\n", encoding="utf-8")
        Path(f"{name}.crt").write_bytes(certificate)
        print(f"signed {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
