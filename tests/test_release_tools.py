"""The scripts that sign a release, check one, and check the revocation list."""

# pylint: disable=redefined-outer-name

import importlib.util
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
from pki_kit import DAY, NOW, Authority, Leaf, issue_leaf, make_authority, make_crl

from insvmarkers import update

TOOLS = Path(__file__).parent.parent / "tools"

# Every test signs or checks against the test authority set up below.
pytestmark = pytest.mark.usefixtures("world")

# Where the tools look for the release certificate, set by the ``world`` fixture.
_STATE: dict[str, Path] = {}


def _tool(name: str) -> ModuleType:
    """Load a script from tools/ as a module, so it can be called in-process."""
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "RELEASE_CERT"):
        setattr(module, "RELEASE_CERT", _STATE["cert"])
    return module


@pytest.fixture
def release_file(tmp_path: Path) -> Path:
    """A stand-in release zip."""
    path = tmp_path / "Insta360-Markers-0.4.0-arm64.zip"
    path.write_bytes(b"pretend this is a zip")
    return path


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Authority, Leaf]:
    """A test authority in place of the real one, with a good certificate and a clean list."""
    authority = make_authority()
    leaf = issue_leaf(authority)
    crl = make_crl(authority)
    monkeypatch.setattr(update, "load_authority", lambda: authority.pem)
    monkeypatch.setattr(update, "load_bundled_crl", lambda: crl)
    monkeypatch.setenv("RELEASE_SIGNING_KEY", leaf.key_pem.decode())
    _STATE["cert"] = tmp_path / "release.crt"
    _STATE["cert"].write_bytes(leaf.pem)
    return authority, leaf


def _use(monkeypatch: pytest.MonkeyPatch, leaf: Leaf) -> None:
    """Sign with ``leaf`` instead of the default certificate."""
    monkeypatch.setenv("RELEASE_SIGNING_KEY", leaf.key_pem.decode())
    _STATE["cert"].write_bytes(leaf.pem)


# Signing


def test_signing_writes_a_signature_and_copies_the_certificate(
    release_file: Path, world: tuple[Authority, Leaf]
) -> None:
    """Both files the app needs appear beside the zip."""
    assert _tool("sign_release").main([str(release_file)]) == 0

    assert Path(f"{release_file}.sig").is_file()
    assert Path(f"{release_file}.crt").read_bytes().strip() == world[1].pem.strip()


def test_what_is_signed_verifies_the_way_the_app_checks_it(
    release_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The verification script accepts what the signing script wrote."""
    _tool("sign_release").main([str(release_file)])

    assert _tool("verify_release").main([str(release_file)]) == 0
    assert capsys.readouterr().out.strip().endswith("valid")


def test_a_revoked_certificate_is_not_signed_with(
    release_file: Path,
    world: tuple[Authority, Leaf],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The workflow stops before publishing something the app would refuse."""
    authority, leaf = world
    revoked = make_crl(authority, revoked=(leaf.serial,), number=2)
    monkeypatch.setattr(update, "load_bundled_crl", lambda: revoked)

    assert _tool("sign_release").main([str(release_file)]) == 1

    assert "revoked" in capsys.readouterr().err
    assert not Path(f"{release_file}.sig").exists()


def test_an_expired_certificate_is_not_signed_with(
    release_file: Path,
    world: tuple[Authority, Leaf],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A certificate past its date is caught in the workflow."""
    _use(monkeypatch, issue_leaf(world[0], not_before=NOW - 30 * DAY, not_after=NOW - DAY))

    assert _tool("sign_release").main([str(release_file)]) == 1

    assert "out of date" in capsys.readouterr().err


def test_a_key_that_does_not_belong_to_the_certificate_is_not_signed_with(
    release_file: Path,
    world: tuple[Authority, Leaf],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mixing one key with another key's certificate fails here, not on a Mac."""
    monkeypatch.setenv("RELEASE_SIGNING_KEY", issue_leaf(world[0]).key_pem.decode())

    assert _tool("sign_release").main([str(release_file)]) == 1

    assert "signature is not valid" in capsys.readouterr().err


def test_a_key_that_is_not_a_signing_key_is_reported(
    release_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Junk in the secret is named, without printing it."""
    monkeypatch.setenv("RELEASE_SIGNING_KEY", "junk")

    assert _tool("sign_release").main([str(release_file)]) == 1

    err = capsys.readouterr().err
    assert "cannot sign" in err
    assert "junk" not in err.replace("cannot sign", "")


def test_a_missing_key_is_refused(release_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Signing with no key is an error, never a silent skip."""
    monkeypatch.delenv("RELEASE_SIGNING_KEY")

    assert _tool("sign_release").main([str(release_file)]) == 1


def test_a_missing_certificate_file_is_refused(release_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The certificate is read from the repository, so it has to be there."""
    _STATE["cert"].unlink()

    assert _tool("sign_release").main([str(release_file)]) == 1

    assert "issue-release-cert.sh" in capsys.readouterr().err


def test_signing_needs_the_shipped_authority_and_list(
    release_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without them the app could not check the result either."""
    monkeypatch.setattr(update, "load_bundled_crl", lambda: None)

    assert _tool("sign_release").main([str(release_file)]) == 1

    assert "must both exist" in capsys.readouterr().err


def test_signing_nothing_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    """A glob that matched no zip must not pass quietly."""
    assert _tool("sign_release").main([]) == 1

    assert "no files" in capsys.readouterr().err


# Checking a download by hand


def test_a_changed_file_is_reported_invalid(release_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Editing the zip after signing is caught."""
    _tool("sign_release").main([str(release_file)])
    release_file.write_bytes(b"tampered")

    assert _tool("verify_release").main([str(release_file)]) == 1

    assert "INVALID" in capsys.readouterr().err


def test_a_file_with_no_signature_cannot_be_checked(release_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing ``.sig`` or ``.crt`` is named."""
    assert _tool("verify_release").main([str(release_file)]) == 2

    assert "cannot read" in capsys.readouterr().err


def test_verification_accepts_an_authority_and_lists_given_on_the_command_line(
    release_file: Path, world: tuple[Authority, Leaf], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person with no source tree supplies the authority and the current list."""
    authority, leaf = world
    _tool("sign_release").main([str(release_file)])
    monkeypatch.setattr(update, "load_authority", lambda: None)
    monkeypatch.setattr(update, "load_bundled_crl", lambda: None)

    ca_file = tmp_path / "ca.pem"
    ca_file.write_bytes(authority.pem)
    clean = tmp_path / "clean.pem"
    clean.write_bytes(make_crl(authority))
    revoked = tmp_path / "revoked.pem"
    revoked.write_bytes(make_crl(authority, revoked=(leaf.serial,), number=2))
    verify = _tool("verify_release")
    given = [str(release_file), "--authority", str(ca_file)]

    assert verify.main([*given, "--crl", str(clean)]) == 0
    assert verify.main([*given, "--crl", str(clean), "--crl", str(revoked)]) == 1


def test_verification_without_any_authority_asks_for_one(
    release_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing to trust is stated plainly."""
    _tool("sign_release").main([str(release_file)])
    monkeypatch.setattr(update, "load_authority", lambda: None)

    assert _tool("verify_release").main([str(release_file)]) == 2

    assert "pass --authority" in capsys.readouterr().err


# The check the release workflow runs first


def test_a_current_list_passes_the_check(capsys: pytest.CaptureFixture[str]) -> None:
    """Signed by the authority and in date."""
    assert _tool("check_setup").main() == 0

    assert "valid until" in capsys.readouterr().out


def test_a_list_close_to_expiry_warns(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Time to run gen-crl.sh, said before it becomes a problem."""
    soon = make_crl(world[0], next_update=NOW + timedelta(days=10))
    monkeypatch.setattr(update, "load_bundled_crl", lambda: soon)

    assert _tool("check_setup").main() == 0

    assert "expires within 30 days" in capsys.readouterr().out


def test_an_expired_list_fails_the_check(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A release built with it would be uninstallable."""
    stale = make_crl(world[0], last_update=NOW - 60 * DAY, next_update=NOW - DAY)
    monkeypatch.setattr(update, "load_bundled_crl", lambda: stale)

    assert _tool("check_setup").main() == 1

    assert "gen-crl.sh" in capsys.readouterr().err


def test_a_missing_list_fails_the_check(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing shipped is the same as nothing usable."""
    monkeypatch.setattr(update, "load_bundled_crl", lambda: None)

    assert _tool("check_setup").main() == 1

    assert "must both exist" in capsys.readouterr().err


def test_a_good_certificate_passes_and_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    """Issued by the authority, in date, not revoked."""
    assert _tool("check_setup").main() == 0

    assert "release certificate is valid until" in capsys.readouterr().out


def test_a_certificate_close_to_expiry_warns(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Time to issue a new one, said before it becomes a problem."""
    _use(monkeypatch, issue_leaf(world[0], not_after=NOW + timedelta(days=20)))

    assert _tool("check_setup").main() == 0

    assert "certificate expires within 90 days" in capsys.readouterr().out


def test_a_missing_certificate_fails_the_check(capsys: pytest.CaptureFixture[str]) -> None:
    """A release with no certificate could not be installed."""
    _STATE["cert"].unlink()

    assert _tool("check_setup").main() == 1

    assert "is missing" in capsys.readouterr().err


def test_an_expired_certificate_fails_the_check(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Caught before anything is published."""
    _use(monkeypatch, issue_leaf(world[0], not_before=NOW - 30 * DAY, not_after=NOW - DAY))

    assert _tool("check_setup").main() == 1

    assert "out of date" in capsys.readouterr().err


def test_a_revoked_certificate_fails_the_check(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A certificate on the list means the app would refuse the release."""
    authority, leaf = world
    revoked = make_crl(authority, revoked=(leaf.serial,), number=2)
    monkeypatch.setattr(update, "load_bundled_crl", lambda: revoked)

    assert _tool("check_setup").main() == 1

    assert "has been revoked" in capsys.readouterr().err


def test_a_certificate_from_another_authority_fails_the_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Chaining to anyone but the built-in authority is no use."""
    _use(monkeypatch, issue_leaf(make_authority("Someone Else")))

    assert _tool("check_setup").main() == 1

    assert "not issued by the release authority" in capsys.readouterr().err


def test_both_problems_are_reported_together(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An expired list and a missing certificate do not hide each other."""
    stale = make_crl(world[0], last_update=NOW - 60 * DAY, next_update=NOW - DAY)
    monkeypatch.setattr(update, "load_bundled_crl", lambda: stale)
    _STATE["cert"].unlink()

    assert _tool("check_setup").main() == 1

    err = capsys.readouterr().err
    assert "gen-crl.sh" in err
    assert "is missing" in err


def test_a_key_that_belongs_to_the_certificate_passes_the_pairing_check(capsys: pytest.CaptureFixture[str]) -> None:
    """With the key in the environment, the release workflow confirms the pair."""
    assert _tool("check_setup").main() == 0

    assert "matches the release certificate" in capsys.readouterr().out


def test_a_key_that_does_not_belong_to_the_certificate_fails_the_check(
    world: tuple[Authority, Leaf], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A new certificate pushed before its key reaches the secret is caught before publishing."""
    monkeypatch.setenv("RELEASE_SIGNING_KEY", issue_leaf(world[0]).key_pem.decode())

    assert _tool("check_setup").main() == 1

    assert "does not match tools/pki/release.crt" in capsys.readouterr().err


def test_a_key_that_is_not_a_key_fails_the_pairing_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Junk in the secret is reported, not a crash."""
    monkeypatch.setenv("RELEASE_SIGNING_KEY", "junk")

    assert _tool("check_setup").main() == 1

    assert "does not match" in capsys.readouterr().err


def test_without_a_key_the_pairing_is_not_checked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a developer's machine there is no key, and the rest still passes."""
    monkeypatch.delenv("RELEASE_SIGNING_KEY")

    assert _tool("check_setup").main() == 0

    assert "matches" not in capsys.readouterr().out
