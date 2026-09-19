# The release authority

This folder holds the scripts that run the release authority: the small
certificate authority that vouches for the key which signs each release of the
Mac app.

## Why there are two keys

The app trusts one thing: the authority's certificate, built into it. The
authority does not sign releases. It signs a certificate for a separate release
key, and the release workflow signs each zip with that key.

```
release authority (ca.key, kept offline)
  signs -> release certificate (release.crt) for the release key
              the release key (release.key, a GitHub secret) signs each zip
```

This gives you two things a single key cannot:

- **Replacing a leaked release key does not need a new app.** Revoke its
  certificate, issue a new one, and every installed app keeps working.
- **The powerful key stays offline.** GitHub holds only the release key, and it
  is the only secret. If it leaks, the damage is limited to what a revoked
  certificate can do.

## What the app checks

Before it installs an update, the app requires all of these:

1. The release certificate was issued by the authority built into the app.
2. It is a code-signing certificate: not a CA, key usage `digitalSignature`,
   purpose `codeSigning`.
3. Today's date is inside its validity dates.
4. Its serial number is not on a current revocation list (CRL) that the
   authority signed. The app looks in three places: the list built into the
   app, the newest one it downloaded before, and the one published in this
   repository. If none is current, it refuses the update.
5. The certificate's key made the signature on the zip.

The code is `check_certificate` and `check_release` in
`src/insvmarkers/update.py`. The release workflow runs the same checks before it
publishes.

## Files

| File | Where it lives | Secret? |
|---|---|---|
| `ca.key` | Offline, outside this repository | Yes. Encrypt it. |
| `ca.crt` | Copied into the repository as `src/insvmarkers/release_ca.pem` | No |
| `release.key` | GitHub secret `RELEASE_SIGNING_KEY` | Yes |
| `release.crt` | Committed as `tools/pki/release.crt` | No |
| the CRL | `src/insvmarkers/release_crl.pem`, committed | No |

The authority lives in `PKI_DIR`, by default `~/release-keys`. Keep it outside
the repository.

## Requirements

OpenSSL 3. macOS ships LibreSSL, which the scripts refuse. Use the project's
Nix shell, `nix-shell -p openssl`, or `brew install openssl` and put it first on
your `PATH`.

## First time

1. **Create the authority.** Skip this if you already have a `ca.key` and
   `ca.crt`. The scripts adopt an existing authority.

   ```bash
   tools/pki/new-ca.sh
   ```

   It asks for a passphrase for `ca.key`. Back the key up somewhere offline.
   Without it you cannot issue certificates or revocation lists.

   An authority made by hand can be protected afterwards with
   `openssl pkey -in ca.key -aes-256-cbc -out ca.key.enc`. Delete the plain
   `ca.key` once you have checked that you can decrypt the encrypted copy. The
   scripts use `ca.key.enc` when `ca.key` is absent and prompt for the
   passphrase.

2. **Give the app the authority's certificate.**

   ```bash
   cp ~/release-keys/ca.crt src/insvmarkers/release_ca.pem
   ```

3. **Issue the release certificate.**

   ```bash
   tools/pki/issue-release-cert.sh
   ```

   The output folder holds `release.key` and `release.crt`. The certificate is
   public, so the script also copies it to `tools/pki/release.crt`. Copy the
   contents of `release.key` into one GitHub secret, `RELEASE_SIGNING_KEY`, under
   Settings, Secrets and variables, Actions. Nothing else is secret.

4. **Write the first revocation list.** It is empty at first. Writing it after
   issuing means the list is newer than the certificate.

   ```bash
   tools/pki/gen-crl.sh
   ```

5. **Commit** `release_ca.pem`, `release_crl.pem` and `tools/pki/release.crt`,
   and push. Then run the Release workflow. It runs `tools/check_setup.py`
   first, which checks the list and the certificate before anything is tagged.

## Routine upkeep

**Renew the CRL before it expires.** A list is valid for 365 days. The app
ignores an expired list, and the release workflow refuses to build with one.
Run `tools/pki/gen-crl.sh`, commit, and push. The workflow warns when fewer than
30 days remain.

**Replace the release certificate before it expires.** It lasts about five
years by default, and `tools/check_setup.py` warns 90 days ahead. Issue a new
one, replace the key secret, commit the new `release.crt`, and run a release.
An update signed with an expired certificate is refused.

The certificate and the secret must change together. Update the secret and push
the new `tools/pki/release.crt` at the same time. If the two disagree,
`tools/check_setup.py` fails the release before anything is tagged, so nothing
broken is published.

**See what has been issued.**

```bash
tools/pki/status.sh
```

## If the release key leaks

1. Revoke its certificate. `SERIAL` comes from `tools/pki/status.sh`, or use the
   path to `release.crt`. This also writes a new CRL.

   ```bash
   tools/pki/revoke-release-cert.sh SERIAL
   ```

2. Commit and push `src/insvmarkers/release_crl.pem`. Apps download it from this
   repository whenever they install an update, so they refuse anything signed
   with the revoked certificate from then on.
3. Issue a new certificate with `tools/pki/issue-release-cert.sh`. It replaces
   `tools/pki/release.crt`.
4. Replace the `RELEASE_SIGNING_KEY` secret, and commit the new `tools/pki/release.crt`.
5. Delete the leaked key everywhere you can, and run a new release.

Revocation stops an app from installing an update signed with the revoked
certificate. It does not remove a version that is already installed, and it
does not help a copy that cannot reach the internet and has only an older list.
A copy that is offline still uses the list built into it and the newest one it
downloaded before.

## Checking a download by hand

A person with a downloaded zip can check it without the app. Save the zip, its
`.sig` and `.crt` files, and `release_ca.pem` from the release page, then run:

```bash
uv run --with cryptography python tools/verify_release.py \
    Insta360-Markers-0.4.0-arm64.zip --authority release_ca.pem
```

It prints `valid` or says which check failed. Add `--crl FILE` with the current
`release_crl.pem` from the repository to include revocations newer than the
copy in your checkout.

## Testing

`tests/test_pki_scripts.py` runs these scripts against a throwaway authority and
checks the results with the app's own rules. It needs OpenSSL 3 on `PATH` and
skips otherwise.
