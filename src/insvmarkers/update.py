"""Finding, verifying and installing a newer version of the Mac app.

Nothing here draws a window or touches the network. :mod:`insvmarkers.updater`
does that and calls into this module.

The trust model: the app carries the release authority's certificate. Each
release zip is signed with a release key, and ships with that key's
certificate, which the authority signed. An update is installed only if the
certificate chains to the authority, is in date, is not on the revocation list
(CRL), and its key made the zip's signature. This matters more than it looks,
because a file the app downloads itself carries no macOS quarantine flag, so
Gatekeeper never inspects it. These checks are the only ones an update gets.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import platform
import plistlib
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import ExtendedKeyUsageOID

logger = logging.getLogger(__name__)

REPO = "ReignBock/insta360py"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
APP_NAME = "Insta360 Markers"
CA_FILE = "release_ca.pem"
CRL_FILE = "release_crl.pem"

# Where the current revocation list is published. It is the copy in the repository,
# so revoking a certificate is a commit that running apps see at their next update.
CRL_URL = f"https://raw.githubusercontent.com/{REPO}/main/src/insvmarkers/{CRL_FILE}"

# The most release notes shown in the update prompt.
NOTES_LIMIT = 1200


class UpdateError(Exception):
    """An update could not be checked, verified or installed."""


@dataclass(frozen=True)
class Release:
    """A published version with a zip for this Mac, its signature and its certificate."""

    version: str
    notes: str
    zip_url: str
    sig_url: str
    cert_url: str


def current_version() -> str:
    """The version of the running app."""
    try:
        return version("insta360py")
    except PackageNotFoundError:
        return "0"


def parse_version(text: str) -> tuple[int, ...]:
    """``v1.2.3`` or ``1.2.3`` as ``(1, 2, 3)``.

    Raises:
        ValueError: for anything else, such as a pre-release suffix. An update
            check treats those as not newer rather than guessing an order.
    """
    return tuple(int(part) for part in text.removeprefix("v").split("."))


def is_newer(candidate: str, installed: str) -> bool:
    """Whether ``candidate`` is a later version than ``installed``."""
    try:
        return parse_version(candidate) > parse_version(installed)
    except ValueError:
        return False


def machine_arch() -> str:
    """``arm64`` or ``x86_64``, the two names the release zips use."""
    return platform.machine()


def release_from_json(body: bytes, arch: str) -> Release | None:
    """The release a GitHub ``releases/latest`` response describes, if usable.

    The response is not trusted. Anything missing or oddly shaped gives
    ``None``, and the zip's contents are checked again after download.
    """
    try:
        payload = json.loads(body)
    except ValueError:
        return None

    if not isinstance(payload, dict) or not isinstance(payload.get("tag_name"), str):
        return None

    tag: str = payload["tag_name"]
    number = tag.removeprefix("v")
    zip_name = f"Insta360-Markers-{number}-{arch}.zip"
    urls: dict[str, str] = {}

    for asset in payload.get("assets") or []:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str):
            link = asset.get("browser_download_url")
            if isinstance(link, str):
                urls[asset["name"]] = link

    if any(name not in urls for name in (zip_name, f"{zip_name}.sig", f"{zip_name}.crt")):
        return None

    notes = payload.get("body")
    return Release(
        version=number,
        notes=notes[:NOTES_LIMIT] if isinstance(notes, str) else "",
        zip_url=urls[zip_name],
        sig_url=urls[f"{zip_name}.sig"],
        cert_url=urls[f"{zip_name}.crt"],
    )


# Signatures and trust


def utcnow() -> datetime:
    """The current time, in one place so tests can move it."""
    return datetime.now(timezone.utc)


def sign(data: bytes, private_key_pem: bytes) -> str:
    """The base64 Ed25519 signature of ``data``. Used by the release workflow.

    Raises:
        ValueError: if the key is not an Ed25519 private key in PEM form.
    """
    key = load_pem_private_key(private_key_pem, password=None)

    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("the signing key is not an Ed25519 private key")

    return base64.b64encode(key.sign(data)).decode("ascii")


def _certificate(pem: bytes, what: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(pem)
    except ValueError as error:
        raise UpdateError(f"The {what} is not a valid certificate.") from error


def usable_crls(
    authority: x509.Certificate, lists: Iterable[bytes], now: datetime
) -> list[x509.CertificateRevocationList]:
    """The revocation lists that can be relied on.

    A list counts only if the authority signed it and it has not passed its
    next-update date. Anything else, including junk, is ignored.
    """
    usable = []
    key = authority.public_key()

    if not isinstance(key, Ed25519PublicKey):
        return usable

    for pem in lists:
        try:
            crl = x509.load_pem_x509_crl(pem)
        except ValueError:
            continue

        expiry = crl.next_update_utc
        if crl.issuer != authority.subject or not crl.is_signature_valid(key):
            continue
        if expiry is None or expiry < now:
            continue

        usable.append(crl)

    return usable


def is_usable_crl(pem: bytes, authority_pem: bytes, now: datetime) -> bool:
    """Whether ``pem`` is a revocation list the authority signed that is still current."""
    return bool(usable_crls(_certificate(authority_pem, "release authority"), [pem], now))


def _require_signing_purpose(certificate: x509.Certificate) -> None:
    """Refuse a certificate that was not issued to sign releases.

    The authority could sign other things one day; only a certificate that says
    it is a code-signing leaf may sign an update.
    """
    try:
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
        purposes = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound as error:
        raise UpdateError("The update's certificate is not a release signing certificate.") from error

    if constraints.ca or not usage.digital_signature or ExtendedKeyUsageOID.CODE_SIGNING not in purposes:
        raise UpdateError("The update's certificate is not a release signing certificate.")


def check_certificate(
    certificate_pem: bytes,
    authority_pem: bytes,
    revocation_lists: Iterable[bytes],
    now: datetime,
) -> x509.Certificate:
    """Confirm that a certificate may be used to sign releases, and return it.

    In order: it was issued by the authority, is meant for signing releases, is
    in date, and is not revoked by a current list.

    Raises:
        UpdateError: naming the first check that failed.
    """
    authority = _certificate(authority_pem, "release authority")
    certificate = _certificate(certificate_pem, "update's certificate")

    try:
        certificate.verify_directly_issued_by(authority)
    except (ValueError, TypeError, InvalidSignature) as error:
        raise UpdateError("The update's certificate was not issued by the release authority.") from error

    _require_signing_purpose(certificate)

    if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
        raise UpdateError("The update's certificate is out of date. Check that this Mac's clock is right.")

    live = usable_crls(authority, revocation_lists, now)
    if not live:
        raise UpdateError("No current revocation list is available.")

    if any(crl.get_revoked_certificate_by_serial_number(certificate.serial_number) for crl in live):
        raise UpdateError("The update's certificate has been revoked.")

    return certificate


def check_release(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    data: bytes,
    signature: bytes,
    certificate_pem: bytes,
    authority_pem: bytes,
    revocation_lists: Iterable[bytes],
    now: datetime,
) -> None:
    """Confirm that a release zip may be installed.

    The certificate must pass :func:`check_certificate`, and its key must have
    made the signature over ``data``.

    Raises:
        UpdateError: naming the first check that failed.
    """
    certificate = check_certificate(certificate_pem, authority_pem, revocation_lists, now)
    key = certificate.public_key()

    try:
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("not an Ed25519 key")
        key.verify(base64.b64decode(signature.strip(), validate=True), data)
    except (ValueError, binascii.Error, InvalidSignature) as error:
        raise UpdateError("The update's signature is not valid, so it was not installed.") from error


def _packaged(name: str) -> bytes | None:
    """A data file shipped inside the package, or ``None`` if there is none."""
    item = resources.files("insvmarkers").joinpath(name)
    return item.read_bytes() if item.is_file() else None


def load_authority() -> bytes | None:
    """The release authority's certificate built into this app."""
    return _packaged(CA_FILE)


def load_bundled_crl() -> bytes | None:
    """The revocation list that was current when this app was built."""
    return _packaged(CRL_FILE)


def cached_crl(support: Path) -> bytes | None:
    """The newest revocation list this app has downloaded, if any."""
    try:
        return (support / CRL_FILE).read_bytes()
    except OSError:
        return None


def cache_crl(support: Path, crl: bytes) -> None:
    """Keep a downloaded revocation list for offline checks. Best effort."""
    try:
        support.mkdir(parents=True, exist_ok=True)
        (support / CRL_FILE).write_bytes(crl)
    except OSError:
        logger.info("Could not cache the revocation list")


# Where the app is, and whether it can be replaced


def app_bundle() -> Path | None:
    """The ``.app`` this process runs from, or ``None`` when not a Mac app."""
    if not getattr(sys, "frozen", False):
        return None

    bundle = Path(sys.executable).resolve().parents[2]
    return bundle if bundle.suffix == ".app" else None


def support_dir() -> Path:
    """Where the app keeps the previous version and its update files."""
    return Path.home() / "Library" / "Application Support" / APP_NAME


def previous_app(support: Path) -> Path:
    """Where the version before the last update is kept."""
    return support / "Previous" / f"{APP_NAME}.app"


def bundle_version(app: Path) -> str | None:
    """The version a ``.app`` declares, or ``None`` if it cannot be read."""
    try:
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            found = plistlib.load(handle).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException):
        return None

    return found if isinstance(found, str) else None


def install_problem(bundle: Path) -> str | None:
    """Why this copy cannot replace itself, or ``None`` if it can.

    macOS runs a freshly downloaded app from a read-only copy until the user
    moves it, and a non-admin user cannot write to Applications. Both are
    common, and both need a clear message instead of a failed update.
    """
    if "AppTranslocation" in bundle.parts:
        return "Move Insta360 Markers to your Applications folder, open it from there, then try again."

    if not os.access(bundle.parent, os.W_OK):
        return f"This account cannot change {bundle.parent}. Download the new version and replace the app by hand."

    return None


# Staging and swapping


def extract_zip(archive: Path, destination: Path) -> None:
    """Unpack a release zip with ``ditto``, which keeps the bundle's symlinks and modes."""
    try:
        subprocess.run(["ditto", "-x", "-k", str(archive), str(destination)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise UpdateError(f"The download could not be unpacked: {error}") from error


def stage(
    archive: Path,
    destination: Path,
    expected_version: str,
    extract: Callable[[Path, Path], None] = extract_zip,
) -> Path:
    """Unpack the zip and confirm it holds the app it claims to.

    The signature already proves who made the zip. This proves the zip is the
    version the release named, so an old signed zip cannot be passed off as a
    new one.

    Raises:
        UpdateError: if it does not hold exactly one app of the expected version.
    """
    destination.mkdir(parents=True, exist_ok=True)
    extract(archive, destination)
    apps = sorted(destination.glob("*.app"))

    if len(apps) != 1:
        raise UpdateError("The download did not contain exactly one app.")

    found = bundle_version(apps[0])
    if found != expected_version:
        raise UpdateError(f"The download is version {found}, not {expected_version}.")

    if not (apps[0] / "Contents" / "MacOS").is_dir():
        raise UpdateError("The download is not a complete app.")

    return apps[0]


# Runs after the app has quit, because a running app cannot replace itself.
# CURRENT moves aside, NEW takes its place, and the old copy becomes the
# previous version. If NEW cannot be moved in, CURRENT goes straight back.
# For a rollback NEW is the previous version itself, so the same steps swap
# the two. Arguments: PID CURRENT NEW PREVIOUS RELAUNCH.
SWAP_SCRIPT = """#!/bin/sh
pid="$1"; current="$2"; new="$3"; previous="$4"; relaunch="$5"

# Wait for the app to exit, for up to a minute.
waited=0
while kill -0 "$pid" 2>/dev/null; do
    waited=$((waited + 1))
    if [ "$waited" -gt 300 ]; then
        echo "the app did not quit; nothing was changed"
        exit 1
    fi
    sleep 0.2
done

mkdir -p "$(dirname "$previous")" || exit 1
aside="$previous.aside"
rm -rf "$aside"

mv "$current" "$aside" || { echo "could not move the current app aside"; exit 1; }

if ! mv "$new" "$current"; then
    echo "could not put the new app in place; restoring the old one"
    mv "$aside" "$current"
    "$relaunch" "$current"
    exit 1
fi

rm -rf "$previous"
mv "$aside" "$previous"
"$relaunch" "$current"
"""


def start_swap(
    current: Path,
    new: Path,
    previous: Path,
    support: Path,
    relaunch: str = "open",
) -> None:
    """Start the helper that swaps the apps once this process has quit.

    The caller must quit straight after. The helper's output goes to
    ``update.log`` in the support folder.

    Raises:
        UpdateError: if the helper could not be started.
    """
    try:
        support.mkdir(parents=True, exist_ok=True)
        script = support / "swap.sh"
        script.write_text(SWAP_SCRIPT, encoding="utf-8")
        script.chmod(0o700)

        with (support / "update.log").open("ab") as log:
            subprocess.Popen(  # pylint: disable=consider-using-with
                ["/bin/sh", str(script), str(os.getpid()), str(current), str(new), str(previous), relaunch],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as error:
        raise UpdateError(f"The update could not be started: {error}") from error
