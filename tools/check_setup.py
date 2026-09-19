"""Check that the repository is ready to publish a release.

The app refuses every update if its revocation list has expired, or if the
release certificate is revoked, expired or not from the release authority. A
release built like that would be uninstallable, so the release workflow runs
this first, before anything is tagged. It checks:

- ``src/insvmarkers/release_crl.pem`` is signed by the authority and current;
- ``tools/pki/release.crt`` is a code-signing certificate the authority issued,
  in date, and not on that list;
- when ``RELEASE_SIGNING_KEY`` is set, that key belongs to the certificate. A
  new certificate committed before its key reaches the secret, or the reverse,
  is caught here and not after the release is published.

It warns when the list has under 30 days left (run tools/pki/gen-crl.sh) or
the certificate has under 90 (run tools/pki/issue-release-cert.sh).

    python tools/check_setup.py
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

from cryptography import x509

from insvmarkers import update

RELEASE_CERT = Path(__file__).resolve().parent / "pki" / "release.crt"
CRL_WARN_WITHIN = timedelta(days=30)
CERT_WARN_WITHIN = timedelta(days=90)


def _check_list(authority: bytes, revocations: bytes) -> bool:
    """Report on the revocation list. False if the app would not accept it."""
    now = update.utcnow()

    if not update.is_usable_crl(revocations, authority, now):
        print("release_crl.pem is not signed by the authority, or has expired.", file=sys.stderr)
        print("Run tools/pki/gen-crl.sh", file=sys.stderr)
        return False

    expires = x509.load_pem_x509_crl(revocations).next_update_utc
    assert expires is not None  # is_usable_crl already required it
    print(f"revocation list is valid until {expires:%Y-%m-%d}")

    if expires - now < CRL_WARN_WITHIN:
        print("::warning::the revocation list expires within 30 days; run tools/pki/gen-crl.sh")

    return True


def _check_certificate(authority: bytes, revocations: bytes) -> bool:
    """Report on the release certificate. False if the app would refuse what it signs."""
    if not RELEASE_CERT.is_file():
        print(f"{RELEASE_CERT} is missing. Run tools/pki/issue-release-cert.sh", file=sys.stderr)
        return False

    now = update.utcnow()

    try:
        certificate = update.check_certificate(RELEASE_CERT.read_bytes(), authority, [revocations], now)
    except update.UpdateError as error:
        print(f"release certificate: {error}", file=sys.stderr)
        return False

    print(f"release certificate is valid until {certificate.not_valid_after_utc:%Y-%m-%d}")

    if certificate.not_valid_after_utc - now < CERT_WARN_WITHIN:
        print("::warning::the release certificate expires within 90 days; issue a new one")

    return _check_pairing(authority, revocations)


def _check_pairing(authority: bytes, revocations: bytes) -> bool:
    """Check that the signing key in the environment belongs to the certificate.

    Skipped when no key is set, as on a developer's machine.
    """
    key = os.environ.get("RELEASE_SIGNING_KEY", "")

    if not key:
        return True

    sample = b"pairing check"

    try:
        signature = update.sign(sample, key.encode())
        update.check_release(
            sample, signature.encode(), RELEASE_CERT.read_bytes(), authority, [revocations], update.utcnow()
        )
    except (ValueError, update.UpdateError) as error:
        print(f"RELEASE_SIGNING_KEY does not match tools/pki/release.crt: {error}", file=sys.stderr)
        return False

    print("RELEASE_SIGNING_KEY matches the release certificate")
    return True


def main() -> int:
    """Exit 0 if a release could be built and installed, 1 if not."""
    authority = update.load_authority()
    revocations = update.load_bundled_crl()

    if authority is None or revocations is None:
        print("src/insvmarkers/release_ca.pem and release_crl.pem must both exist", file=sys.stderr)
        return 1

    # Both run, so one failure does not hide the other.
    list_ok = _check_list(authority, revocations)
    certificate_ok = _check_certificate(authority, revocations)

    return 0 if list_ok and certificate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
