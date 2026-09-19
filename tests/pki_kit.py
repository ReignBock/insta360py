"""Authorities, certificates and revocation lists for tests, built in memory."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric.types import CertificateIssuerPrivateKeyTypes
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from cryptography.hazmat.primitives.asymmetric import rsa

# Fixed once, so every certificate in a test agrees on what "now" is. Whole
# seconds, because certificates do not store fractions.
NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)

CODE_SIGNING = [ExtendedKeyUsageOID.CODE_SIGNING]


@dataclass
class Authority:
    """A certificate authority: its key, its certificate, and the certificate as PEM."""

    key: CertificateIssuerPrivateKeyTypes
    cert: x509.Certificate
    pem: bytes


@dataclass
class Leaf:
    """A certificate issued by an authority, with its private key as PEM."""

    key_pem: bytes
    cert: x509.Certificate
    pem: bytes

    @property
    def serial(self) -> int:
        """The certificate's serial number, which a revocation list names."""
        return self.cert.serial_number


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _usage(*, digital_signature: bool = False, key_cert_sign: bool = False, crl_sign: bool = False) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=digital_signature,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=key_cert_sign,
        crl_sign=crl_sign,
        encipher_only=False,
        decipher_only=False,
    )


def make_authority(name: str = "Test Release Authority") -> Authority:
    """A self-signed authority that may issue certificates and revocation lists."""
    key = ed25519.Ed25519PrivateKey.generate()
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(name))
        .issuer_name(_name(name))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - DAY)
        .not_valid_after(NOW + 3650 * DAY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_usage(key_cert_sign=True, crl_sign=True), critical=True)
        .sign(key, None)
    )
    return Authority(key, cert, cert.public_bytes(Encoding.PEM))


def make_rsa_authority() -> Authority:
    """A self-signed authority whose key is RSA, which this app does not accept."""
    key = rsa_key()
    name = _name("RSA Authority")
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - DAY)
        .not_valid_after(NOW + 3650 * DAY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    return Authority(key, cert, cert.public_bytes(Encoding.PEM))  # type: ignore[arg-type]


def issue_leaf(  # pylint: disable=too-many-arguments
    authority: Authority,
    *,
    key: CertificateIssuerPrivateKeyTypes | None = None,
    not_before: datetime = NOW - DAY,
    not_after: datetime = NOW + 365 * DAY,
    is_ca: bool = False,
    digital_signature: bool = True,
    purposes: list[x509.ObjectIdentifier] | None = None,
    with_extensions: bool = True,
) -> Leaf:
    """A certificate the authority issued. The defaults are a good release certificate.

    ``purposes`` of ``None`` means the code-signing purpose; pass an empty list
    for none. ``with_extensions=False`` leaves out all three extensions.
    """
    key = key or ed25519.Ed25519PrivateKey.generate()
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name("Test Release"))
        .issuer_name(authority.cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
    )

    if with_extensions:
        builder = builder.add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        builder = builder.add_extension(_usage(digital_signature=digital_signature), critical=True)
        builder = builder.add_extension(
            x509.ExtendedKeyUsage(CODE_SIGNING if purposes is None else purposes), critical=False
        )

    cert = builder.sign(authority.key, None)
    pem_key = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    return Leaf(pem_key, cert, cert.public_bytes(Encoding.PEM))


def rsa_key() -> rsa.RSAPrivateKey:
    """An RSA key, for a certificate of the wrong kind."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_crl(  # pylint: disable=too-many-arguments
    authority: Authority,
    revoked: tuple[int, ...] = (),
    *,
    number: int = 1,
    last_update: datetime = NOW - DAY,
    next_update: datetime = NOW + 30 * DAY,
    signer: ed25519.Ed25519PrivateKey | None = None,
) -> bytes:
    """A revocation list from the authority, as PEM. ``signer`` overrides who signs it."""
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(authority.cert.subject)
        .last_update(last_update)
        .next_update(next_update)
        .add_extension(x509.CRLNumber(number), critical=False)
    )

    for serial in revoked:
        builder = builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder().serial_number(serial).revocation_date(NOW - DAY).build()
        )

    return builder.sign(signer or authority.key, None).public_bytes(Encoding.PEM)
