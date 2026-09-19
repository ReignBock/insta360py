"""The certificate authority scripts in tools/pki, run for real and checked by the app's own rules."""

# pylint: disable=redefined-outer-name

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from insvmarkers import update
from insvmarkers.update import UpdateError
PKI = Path(__file__).parent.parent / "tools" / "pki"


def _openssl_3() -> bool:
    """The scripts need OpenSSL 3; macOS's LibreSSL will not do."""
    if shutil.which("openssl") is None:
        return False
    version = subprocess.run(["openssl", "version"], capture_output=True, text=True, check=False).stdout
    return version.startswith("OpenSSL 3")


pytestmark = pytest.mark.skipif(not _openssl_3(), reason="needs OpenSSL 3 on PATH")


class Authority:
    """A throwaway authority made by the scripts, in a temp folder."""

    def __init__(self, root: Path) -> None:
        self.dir = root / "pki"
        self.crl = root / "release_crl.pem"
        self.cert = root / "release.crt"
        self.env = {
            **os.environ,
            "PKI_DIR": str(self.dir),
            "CRL_OUT": str(self.crl),
            "CERT_OUT": str(self.cert),
        }

    def run(self, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run one script; the authority key has no passphrase, so nothing prompts."""
        return subprocess.run(
            [str(PKI / script), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
            stdin=subprocess.DEVNULL,
        )

    @property
    def certificate(self) -> bytes:
        """The authority's public certificate."""
        return (self.dir / "ca.crt").read_bytes()

    def issue(self, *arguments: str) -> Path:
        """Issue a certificate and return the folder it was written to."""
        folder = self.dir / "issued"
        before = set(folder.iterdir()) if folder.exists() else set()
        result = self.run("issue-release-cert.sh", *arguments)
        assert result.returncode == 0, result.stderr
        (created,) = set(folder.iterdir()) - before
        return created

    def check(self, issued: Path, data: bytes = b"release zip") -> None:
        """Apply the app's full check to a certificate the scripts issued."""
        signature = update.sign(data, (issued / "release.key").read_bytes())
        update.check_release(
            data,
            signature.encode(),
            (issued / "release.crt").read_bytes(),
            self.certificate,
            [self.crl.read_bytes()],
            update.utcnow(),
        )


@pytest.fixture
def authority(tmp_path: Path) -> Authority:
    """An authority with a first, empty revocation list."""
    made = Authority(tmp_path)
    assert made.run("new-ca.sh", "--no-passphrase").returncode == 0
    assert made.run("gen-crl.sh").returncode == 0
    return made


def test_a_certificate_the_scripts_issue_is_accepted_by_the_app(authority: Authority) -> None:
    """The whole chain: authority, revocation list, certificate, signature."""
    authority.check(authority.issue())


def test_the_authority_certificate_is_a_ca_that_can_sign_lists(authority: Authority) -> None:
    """Basic constraints and key usage are what the app relies on."""
    certificate = x509.load_pem_x509_certificate(authority.certificate)
    constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
    usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value

    assert constraints.ca
    assert usage.key_cert_sign
    assert usage.crl_sign


def test_a_revoked_certificate_is_refused_after_the_list_is_regenerated(authority: Authority) -> None:
    """Issue, revoke by serial, and the app then refuses it."""
    issued = authority.issue()
    serial = authority.run("status.sh").stdout.split()[2]
    authority.check(issued)

    revoked = authority.run("revoke-release-cert.sh", serial)

    assert revoked.returncode == 0
    with pytest.raises(UpdateError, match="has been revoked"):
        authority.check(issued)


def test_revoking_one_certificate_leaves_another_valid(authority: Authority) -> None:
    """Only the named serial is refused."""
    first = authority.issue()
    first_serial = authority.run("status.sh").stdout.split()[2]
    second = authority.issue()
    assert first != second

    authority.run("revoke-release-cert.sh", first_serial)

    with pytest.raises(UpdateError, match="has been revoked"):
        authority.check(first)
    authority.check(second)


def test_a_certificate_can_be_revoked_by_its_file(authority: Authority) -> None:
    """Either the serial or the certificate file names it."""
    issued = authority.issue()

    assert authority.run("revoke-release-cert.sh", str(issued / "release.crt")).returncode == 0

    with pytest.raises(UpdateError, match="has been revoked"):
        authority.check(issued)


def test_the_list_number_rises_with_each_regeneration(authority: Authority) -> None:
    """Newer lists are distinguishable from older ones."""
    def number() -> int:
        crl = x509.load_pem_x509_crl(authority.crl.read_bytes())
        return crl.extensions.get_extension_for_class(x509.CRLNumber).value.crl_number

    first = number()
    authority.run("gen-crl.sh")

    assert number() == first + 1


def test_the_list_expires_when_asked(authority: Authority) -> None:
    """``--days`` sets how long the list is good for."""
    authority.run("gen-crl.sh", "--days", "7")
    crl = x509.load_pem_x509_crl(authority.crl.read_bytes())

    assert crl.next_update_utc is not None
    assert 6 <= (crl.next_update_utc - crl.last_update_utc).days <= 7


def test_a_certificate_issued_for_fewer_days_expires_sooner(authority: Authority) -> None:
    """``--days`` on issuing sets the certificate's life."""
    issued = authority.issue("--days", "30")
    certificate = x509.load_pem_x509_certificate((issued / "release.crt").read_bytes())

    assert 29 <= (certificate.not_valid_after_utc - certificate.not_valid_before_utc).days <= 30


def test_the_issued_certificate_may_only_sign_code(authority: Authority) -> None:
    """Not a CA, digital signature only, code signing purpose."""
    issued = authority.issue()
    certificate = x509.load_pem_x509_certificate((issued / "release.crt").read_bytes())
    extensions = certificate.extensions

    assert not extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert extensions.get_extension_for_class(x509.KeyUsage).value.digital_signature
    assert ExtendedKeyUsageOID.CODE_SIGNING in extensions.get_extension_for_class(x509.ExtendedKeyUsage).value


def test_the_private_files_are_readable_only_by_their_owner(authority: Authority) -> None:
    """Keys are created with mode 600."""
    issued = authority.issue()

    for key in (authority.dir / "ca.key", issued / "release.key"):
        assert key.stat().st_mode & 0o077 == 0, key


def test_status_lists_each_certificate_and_its_state(authority: Authority) -> None:
    """Valid, then revoked."""
    assert "No certificates issued yet" in authority.run("status.sh").stdout

    authority.issue()
    listing = authority.run("status.sh").stdout
    assert listing.startswith("valid")

    authority.run("revoke-release-cert.sh", listing.split()[2])
    assert authority.run("status.sh").stdout.startswith("REVOKED")


def test_a_second_authority_is_refused(authority: Authority) -> None:
    """Never overwrite an existing authority."""
    before = authority.certificate

    result = authority.run("new-ca.sh", "--no-passphrase")

    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert authority.certificate == before


def test_an_unknown_serial_cannot_be_revoked(authority: Authority) -> None:
    """A typo does not silently do nothing."""
    result = authority.run("revoke-release-cert.sh", "DEADBEEF")

    assert result.returncode == 1
    assert "no certificate with serial" in result.stderr


def test_an_existing_authority_without_a_database_is_adopted(tmp_path: Path) -> None:
    """The scripts work on an authority made by hand, as long as its key and certificate are there."""
    authority = Authority(tmp_path)
    authority.dir.mkdir()
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(authority.dir / "ca.key")],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl", "req", "-x509", "-new", "-key", str(authority.dir / "ca.key"), "-days", "30",
            "-subj", "/CN=Insta360 Markers Release CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-out", str(authority.dir / "ca.crt"),
        ],
        check=True,
        capture_output=True,
    )

    assert authority.run("gen-crl.sh").returncode == 0

    authority.check(authority.issue())


@pytest.mark.parametrize(
    ("script", "arguments"),
    [
        ("new-ca.sh", ("--bogus",)),
        ("issue-release-cert.sh", ("--bogus",)),
        ("issue-release-cert.sh", ("--days", "many")),
        ("gen-crl.sh", ("--bogus",)),
        ("gen-crl.sh", ("--days", "soon")),
    ],
)
def test_bad_arguments_are_explained(authority: Authority, script: str, arguments: tuple[str, ...]) -> None:
    """Wrong usage fails with a message, and changes nothing."""
    result = authority.run(script, *arguments)

    assert result.returncode != 0
    assert result.stderr.strip()


def test_the_scripts_refuse_a_missing_authority(tmp_path: Path) -> None:
    """Issuing needs an authority to exist."""
    empty = Authority(tmp_path)

    result = empty.run("issue-release-cert.sh")

    assert result.returncode == 1
    assert "no authority certificate" in result.stderr


def test_the_scripts_refuse_openssl_that_is_too_old(authority: Authority, tmp_path: Path) -> None:
    """A stand-in LibreSSL is rejected with a pointer to what to install."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "openssl").write_text('#!/bin/sh\necho "LibreSSL 3.3.6"\n')
    (fake / "openssl").chmod(0o755)
    authority.env["PATH"] = f"{fake}:{authority.env['PATH']}"

    result = authority.run("gen-crl.sh")

    assert result.returncode == 1
    assert "OpenSSL 3 is required" in result.stderr


def test_issuing_copies_the_public_certificate_to_the_repository_location(authority: Authority) -> None:
    """The certificate is public, so it goes where the repository keeps it."""
    issued = authority.issue()

    assert authority.cert.read_bytes() == (issued / "release.crt").read_bytes()


def test_a_second_issue_replaces_the_repository_certificate(authority: Authority) -> None:
    """Only one certificate is current, and it matches the newest key."""
    authority.issue()
    second = authority.issue()

    assert authority.cert.read_bytes() == (second / "release.crt").read_bytes()
