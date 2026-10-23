---
title: "ADR-9015: install_tools framework: archive extraction and custom URLs"
description: Extend the install_tools framework with archive extraction and custom download URLs, keeping it backward compatible
date: 2026-04-07
audience:
  - contributors
tags:
  - adr
  - tooling
---

# ADR-9015: install_tools framework: archive extraction and custom URLs

## Status

Accepted

## Decision

Extend `tools/doit/install_tools.py` with three orthogonal capabilities while preserving full backward compatibility:

1. **`download_and_extract_archive(url, extract_binaries, dest_dir)`** — new public function for `.tar.gz`/`.tgz`/`.zip` archives with path-traversal protection (tarfile `data_filter` plus basename-only extraction and a defense-in-depth zip-slip check).
2. **`url_template` parameter** on `install_tool()` and `create_install_task()` supporting `{version}`, `{os}`, and `{arch}` placeholders for non-GitHub-release downloads (e.g., `releases.hashicorp.com`).
3. **`prefer_brew` flag** so callers can opt out of the macOS brew fallback when they need consistent cross-platform downloads.

Supporting refactors: a private `_get_arch()` helper that maps `platform.machine()` to amd64/arm64 (passthrough for unknowns), and a private `_build_github_release_url()` so the binary path and the new archive path share URL construction.

`extract_binaries` also accepts an optional per-platform `dict[str, list[str]]` keyed by `platform.system().lower()` (same convention as `asset_patterns`), for tools whose archive members differ per OS (e.g., `.exe` suffix on Windows).

`url_template` likewise accepts a per-platform `dict[str, str]` keyed by `platform.system().lower()`, in addition to the plain string form (#930). This was needed because `{os}`/`{version}` substitution into one template cannot express every release's asset naming: `jq`'s release tag is `jq-1.8.2` rather than `v{version}`, and its macOS asset is named `jq-macos-<arch>` while `{os}` expands to `darwin`. A dict `url_template` is resolved by the current OS exactly like a plain string one — it still bypasses brew on macOS — except that an OS missing from the dict aborts with the same `Unsupported OS for {name}` error `asset_patterns` uses. The plain string form is unchanged.

4. **Integrity verification (#694)** — an optional `sha256` parameter (a single digest, or a per-platform mapping) verified before the archive is opened and before the executable bit is set; a mismatch deletes the file and aborts. A digest is **mandatory** for hosts outside `IMPLICITLY_TRUSTED_HOSTS`, i.e. for the `url_template` escape hatch this ADR introduced.

   The asymmetry is deliberate. `url_template` exists to fetch from arbitrary third parties such as `releases.hashicorp.com`, which bypasses even the implicit trust already extended to GitHub by cloning this template. A caller reaching outside that boundary must state what it expects to receive; a GitHub-release install rests on trust the user has already granted.

   We explicitly did **not** adopt fetching upstream `*.sha256` sibling files. Served over HTTPS from the same origin as the asset, that defends against almost nothing: TLS already covers the transport, and an attacker able to replace the asset can replace the checksum beside it. Shipping it would have read as integrity assurance while providing close to none. Verification value comes from a digest the *caller* pinned.

## Rationale

Downstream consumers (e.g., InfraFoundry) need to install five tools, but only direnv-style single binaries from GitHub releases work today. age and sops ship as multi-binary tar.gz archives; terraform and opentofu ship from non-GitHub URLs. Without these extensions every downstream consumer reinvents download/extract code with inconsistent (often missing) security handling.

The three capabilities are intentionally orthogonal so simple cases stay simple — existing direnv install code does not change — and complex cases compose naturally (`extract_binaries` and `url_template` can be combined).

## Consequences

**Positive:**
- 100% backward compatible — existing direnv install task and the original 22 tests pass unchanged.
- Downstream consumers install age, sops, terraform, and opentofu without custom download/extract code.
- Centralized, audited safe extraction (tarfile data_filter + basename-only + zip-slip resolve check).
- macOS users can opt into brew (default) or force download for cross-platform consistency.

**Negative:**
- Larger public API surface to maintain.
- The framework is now responsible for safe archive extraction; security regressions here affect every downstream consumer.
- Custom-URL callers must now supply a digest. This is a breaking change for any downstream that already passes `url_template` for a non-GitHub host — the call aborts with an `IntegrityError` naming the missing parameter until a digest is added.

**Known limitation:**
- `install_tool` resolves the latest release at run time, so a caller-supplied digest is only valid for a known version. Pinning versions alongside digests is what would deliver reproducibility and detect a retagged upstream asset; it was deferred because the resulting digest matrix ages and would change `doit install_gh` from "install current gh" to "install the version the template froze" (#694).

**Future work:**
- Pinned versions alongside pinned digests, with a refresh task.
- GPG signature verification — meaningful against a compromised release host in a way a sibling checksum file is not, because the signing key is not served alongside the asset.
- Local archive caching between runs.
- Windows binary download support.

## Related Issues

- Issue #326: install_tools framework: archive extraction and custom URLs
- Issue #477: support per-platform `extract_binaries` in install_tool framework
- Issue #694: verify checksums for binaries and scripts downloaded by install_tools and bootstrap
- Issue #930: add doit install_jq and make the statusline report a missing jq

## Related Documentation

- [install_tools Framework](../development/install-tools-framework.md)
