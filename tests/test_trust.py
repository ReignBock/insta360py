"""What makes a release installable: the chain, the certificate's purpose and dates, revocation, the signature."""

# pylint: disable=redefined-outer-name

import base64
from dataclasses import dataclass

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509.oid import ExtendedKeyUsageOID
from pki_kit import DAY, NOW, Authority, Leaf, issue_leaf, make_authority, make_crl, make_rsa_authority, rsa_key

from insvmarkers import update
from insvmarkers.update import UpdateError

DATA = b"the release zip"


@dataclass
class World:
    """An authority, a good certificate from it, and a clean revocation list."""

    authority: Authority
    leaf: Leaf
    crl: bytes

    def signature(self, data: bytes = DATA) -> bytes:
        """The certificate's key signing ``data``."""
        return update.sign(data, self.leaf.key_pem).encode()

    def check(self, **overrides: object) -> None:
        """Run the full check, with any part replaced."""
        arguments: dict[str, object] = {
            "data": DATA,
            "signature": self.signature(),
            "certificate_pem": self.leaf.pem,
            "authority_pem": self.authority.pem,
            "revocation_lists": [self.crl],
            "now": NOW,
        }
        arguments.update(overrides)
        update.check_release(**arguments)  # type: ignore[arg-type]


@pytest.fixture
def world() -> World:
    """A working release setup."""
    authority = make_authority()
    return World(authority, issue_leaf(authority), make_crl(authority))


def test_a_properly_issued_and_signed_release_is_accepted(world: World) -> None:
    """The whole chain in order: nothing is refused."""
    world.check()


def test_a_changed_file_is_refused(world: World) -> None:
    """One altered byte and the signature no longer matches."""
    with pytest.raises(UpdateError, match="signature is not valid"):
        world.check(data=DATA + b"!")


def test_a_signature_from_a_different_key_is_refused(world: World) -> None:
    """Only the certificate's own key may sign."""
    other = issue_leaf(world.authority)

    with pytest.raises(UpdateError, match="signature is not valid"):
        world.check(signature=update.sign(DATA, other.key_pem).encode())


@pytest.mark.parametrize("signature", [b"!!! not base64 !!!", base64.b64encode(b"too short")])
def test_a_damaged_signature_is_refused(world: World, signature: bytes) -> None:
    """Text that is not a signature is refused, not an error."""
    with pytest.raises(UpdateError, match="signature is not valid"):
        world.check(signature=signature)


def test_a_certificate_from_another_authority_is_refused(world: World) -> None:
    """Chaining to a different authority means nothing to this app."""
    stranger = issue_leaf(make_authority("Someone Else"))

    with pytest.raises(UpdateError, match="not issued by the release authority"):
        world.check(certificate_pem=stranger.pem, signature=update.sign(DATA, stranger.key_pem).encode())


def test_a_certificate_that_names_our_authority_but_is_not_signed_by_it_is_refused(world: World) -> None:
    """Copying the authority's name is not enough; the signature must verify."""
    impostor = make_authority()
    forged = issue_leaf(impostor)
    impostor_cert = forged.cert  # issuer name matches: both authorities share a subject
    assert impostor_cert.issuer == world.authority.cert.subject

    with pytest.raises(UpdateError, match="not issued by the release authority"):
        world.check(certificate_pem=forged.pem, signature=update.sign(DATA, forged.key_pem).encode())


def test_something_that_is_not_a_certificate_is_refused(world: World) -> None:
    """Junk in either place is named, not a crash."""
    with pytest.raises(UpdateError, match="update's certificate is not a valid certificate"):
        world.check(certificate_pem=b"junk")

    with pytest.raises(UpdateError, match="release authority is not a valid certificate"):
        world.check(authority_pem=b"junk")


def test_an_authority_certificate_cannot_sign_a_release(world: World) -> None:
    """A certificate that may itself issue certificates is not a signing certificate."""
    grand = issue_leaf(world.authority, is_ca=True)

    with pytest.raises(UpdateError, match="not a release signing certificate"):
        world.check(certificate_pem=grand.pem, signature=update.sign(DATA, grand.key_pem).encode())


def test_a_certificate_that_cannot_make_signatures_is_refused(world: World) -> None:
    """Key usage must include digital signature."""
    leaf = issue_leaf(world.authority, digital_signature=False)

    with pytest.raises(UpdateError, match="not a release signing certificate"):
        world.check(certificate_pem=leaf.pem, signature=update.sign(DATA, leaf.key_pem).encode())


def test_a_certificate_for_another_purpose_is_refused(world: World) -> None:
    """A web-server certificate from the same authority must not sign releases."""
    leaf = issue_leaf(world.authority, purposes=[ExtendedKeyUsageOID.SERVER_AUTH])

    with pytest.raises(UpdateError, match="not a release signing certificate"):
        world.check(certificate_pem=leaf.pem, signature=update.sign(DATA, leaf.key_pem).encode())


def test_a_certificate_with_no_stated_purpose_is_refused(world: World) -> None:
    """Silence about what a certificate is for is not permission."""
    bare = issue_leaf(world.authority, with_extensions=False)

    with pytest.raises(UpdateError, match="not a release signing certificate"):
        world.check(certificate_pem=bare.pem, signature=update.sign(DATA, bare.key_pem).encode())


def test_an_expired_certificate_is_refused(world: World) -> None:
    """Past its end date."""
    old = issue_leaf(world.authority, not_before=NOW - 30 * DAY, not_after=NOW - DAY)

    with pytest.raises(UpdateError, match="out of date"):
        world.check(certificate_pem=old.pem, signature=update.sign(DATA, old.key_pem).encode())


def test_a_certificate_not_yet_valid_is_refused(world: World) -> None:
    """Before its start date, which also catches a clock set far in the past."""
    early = issue_leaf(world.authority, not_before=NOW + DAY, not_after=NOW + 30 * DAY)

    with pytest.raises(UpdateError, match="out of date"):
        world.check(certificate_pem=early.pem, signature=update.sign(DATA, early.key_pem).encode())


def test_a_revoked_certificate_is_refused(world: World) -> None:
    """The point of the revocation list."""
    crl = make_crl(world.authority, revoked=(world.leaf.serial,), number=2)

    with pytest.raises(UpdateError, match="has been revoked"):
        world.check(revocation_lists=[crl])


def test_revoked_in_any_current_list_is_revoked(world: World) -> None:
    """An older list that predates the revocation cannot hide it."""
    older = make_crl(world.authority, number=1)
    newer = make_crl(world.authority, revoked=(world.leaf.serial,), number=2)

    with pytest.raises(UpdateError, match="has been revoked"):
        world.check(revocation_lists=[older, newer])
    with pytest.raises(UpdateError, match="has been revoked"):
        world.check(revocation_lists=[newer, older])


def test_another_certificates_revocation_does_not_affect_this_one(world: World) -> None:
    """Only the named serial is refused."""
    other = issue_leaf(world.authority)

    world.check(revocation_lists=[make_crl(world.authority, revoked=(other.serial,), number=2)])


def test_no_revocation_list_means_no_install(world: World) -> None:
    """Without a list there is no way to know the certificate is still good."""
    with pytest.raises(UpdateError, match="No current revocation list"):
        world.check(revocation_lists=[])


def test_an_expired_revocation_list_is_not_relied_on(world: World) -> None:
    """A stale list may be missing recent revocations."""
    stale = make_crl(world.authority, last_update=NOW - 60 * DAY, next_update=NOW - DAY)

    with pytest.raises(UpdateError, match="No current revocation list"):
        world.check(revocation_lists=[stale])


def test_a_stale_list_does_not_spoil_a_current_one(world: World) -> None:
    """The bundled list may have expired while a fresh one was downloaded."""
    stale = make_crl(world.authority, last_update=NOW - 60 * DAY, next_update=NOW - DAY)

    world.check(revocation_lists=[stale, world.crl])


def test_a_list_signed_by_someone_else_is_ignored(world: World) -> None:
    """A list only counts if the authority's key signed it."""
    forged = make_crl(world.authority, signer=ed25519.Ed25519PrivateKey.generate())

    with pytest.raises(UpdateError, match="No current revocation list"):
        world.check(revocation_lists=[forged])


def test_a_forged_list_cannot_hide_a_revocation(world: World) -> None:
    """An attacker's clean list beside the real one changes nothing."""
    real = make_crl(world.authority, revoked=(world.leaf.serial,), number=2)
    forged = make_crl(world.authority, number=9, signer=ed25519.Ed25519PrivateKey.generate())

    with pytest.raises(UpdateError, match="has been revoked"):
        world.check(revocation_lists=[forged, real])


def test_a_list_from_another_authority_is_ignored(world: World) -> None:
    """Its issuer is not ours."""
    other = make_authority("Someone Else")

    with pytest.raises(UpdateError, match="No current revocation list"):
        world.check(revocation_lists=[make_crl(other)])


def test_junk_instead_of_a_list_is_ignored(world: World) -> None:
    """Garbage in a cache file cannot break checking, and good lists still count."""
    world.check(revocation_lists=[b"garbage", world.crl])

    with pytest.raises(UpdateError, match="No current revocation list"):
        world.check(revocation_lists=[b"garbage"])


def test_a_certificate_with_a_key_of_the_wrong_kind_is_refused(world: World) -> None:
    """Only Ed25519 signatures are accepted, even from a certificate the authority issued."""
    leaf = issue_leaf(world.authority, key=rsa_key())

    with pytest.raises(UpdateError, match="signature is not valid"):
        world.check(certificate_pem=leaf.pem, signature=base64.b64encode(b"x" * 64))


def test_signing_needs_an_ed25519_key() -> None:
    """A key of the wrong kind is reported, so a mix-up in the secret shows."""
    pem = rsa_key().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

    with pytest.raises(ValueError, match="Ed25519"):
        update.sign(b"data", pem)


def test_an_authority_with_a_key_of_the_wrong_kind_is_never_trusted(world: World) -> None:
    """Only Ed25519 authorities are accepted, and anything else is refused, not an error."""
    rsa = make_rsa_authority()

    assert not update.is_usable_crl(world.crl, rsa.pem, NOW)


def test_a_crl_is_usable_only_when_signed_and_current(world: World) -> None:
    """The helper the updater uses to decide what to cache."""
    stale = make_crl(world.authority, last_update=NOW - 60 * DAY, next_update=NOW - DAY)

    assert update.is_usable_crl(world.crl, world.authority.pem, NOW)
    assert not update.is_usable_crl(stale, world.authority.pem, NOW)
    assert not update.is_usable_crl(b"junk", world.authority.pem, NOW)
