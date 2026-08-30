# install_tools Framework

A reusable Python framework for installing developer tools from GitHub
releases (and other URLs) into the user-local `~/.local/bin` directory.
Lives in [`tools/doit/install_tools.py`](https://github.com/username/package_name/blob/main/tools/doit/install_tools.py)
and is consumed by `doit` install tasks (e.g., `doit install_direnv`).

## Overview

Use this framework when you need to install a developer-facing CLI tool
that ships pre-built binaries from a GitHub release or a stable HTTPS URL.
It handles version discovery, download, archive extraction, and
permissions in a single call. It is **not** a substitute for the OS
package manager — system libraries and services should still be installed
via apt/dnf/brew/pacman.

The framework supports three release shapes:

| Shape | Example tool | Use |
| :--- | :--- | :--- |
| Single binary from a GitHub release | direnv | default — pass `asset_patterns` only |
| Multi-binary archive (tar.gz / zip) from a GitHub release | age, sops | add `extract_binaries=[...]` |
| Single binary or archive from a non-GitHub URL | terraform, opentofu | add `url_template=...`, optionally with `prefer_brew=False` |

## Public API

| Function | Purpose |
| :--- | :--- |
| `get_latest_github_release(repo)` | Query the GitHub API for the latest release tag (strips leading `v`). Honors `GITHUB_TOKEN`. |
| `get_install_dir()` | Return `~/.local/bin`, creating it if missing. |
| `download_github_release_binary(repo, version, asset_pattern, dest_name)` | Download a single binary from a GitHub release and chmod 755. |
| `download_and_extract_archive(url, extract_binaries, dest_dir)` | Download a `.tar.gz`/`.tgz`/`.zip` and extract the requested binaries by basename. |
| `install_tool(name, repo, asset_patterns, ...)` | High-level installer: skip-if-installed, fetch latest, download, extract. |
| `create_install_task(name, repo, asset_patterns, ...)` | Factory returning a doit task dict that calls `install_tool`. |

## Examples

### Single binary from GitHub releases (direnv)

```python
from tools.doit.install_tools import create_install_task

def task_install_direnv():
    return create_install_task(
        name="direnv",
        repo="direnv/direnv",
        asset_patterns={
            "linux": "direnv.linux-amd64",
            "darwin": "direnv.darwin-amd64",
        },
    )
```

### Multi-binary archive from GitHub releases (age)

```python
from tools.doit.install_tools import create_install_task

def task_install_age():
    return create_install_task(
        name="age",
        repo="FiloSottile/age",
        asset_patterns={
            "linux": "age-v{version}-linux-amd64.tar.gz",
            "darwin": "age-v{version}-darwin-amd64.tar.gz",
        },
        extract_binaries=["age", "age-keygen"],
    )
```

`extract_binaries` matches by **basename**, so any directory structure
inside the archive (e.g., `age/age`, `age/age-keygen`) is ignored.

#### Per-platform binary names

When archive members differ per OS — most commonly a `.exe` suffix on
Windows — pass a `dict` keyed by `platform.system().lower()` instead of
a flat list. The same key convention used by `asset_patterns` applies:

```python
from tools.doit.install_tools import create_install_task

def task_install_age():
    return create_install_task(
        name="age",
        repo="FiloSottile/age",
        asset_patterns={
            "linux": "age-v{version}-linux-amd64.tar.gz",
            "darwin": "age-v{version}-darwin-amd64.tar.gz",
            "windows": "age-v{version}-windows-amd64.zip",
        },
        extract_binaries={
            "linux": ["age", "age-keygen"],
            "darwin": ["age", "age-keygen"],
            "windows": ["age.exe", "age-keygen.exe"],
        },
    )
```

If the current OS is missing from the dict the install aborts with the
same `Unsupported OS` error that `asset_patterns` uses.

### Multi-arch archive from GitHub releases via `url_template` (gh)

```python
from tools.doit.install_tools import create_install_task

def task_install_gh():
    return create_install_task(
        name="gh",
        repo="cli/cli",
        asset_patterns={},
        url_template=(
            "https://github.com/cli/cli/releases/download/v{version}/"
            "gh_{version}_{os}_{arch}.tar.gz"
        ),
        extract_binaries=["gh"],
        version_cmd=["gh", "--version"],
        prefer_brew=False,
    )
```

When the release URL itself is on GitHub but includes architecture-specific
filenames (e.g., `gh_2.45.0_linux_amd64.tar.gz`), `url_template` is the
right choice because `asset_patterns` does not support `{arch}` placeholders.

### Zip from a non-GitHub URL (terraform)

```python
from tools.doit.install_tools import create_install_task

def task_install_terraform():
    return create_install_task(
        name="terraform",
        repo="hashicorp/terraform",  # still used for version discovery
        asset_patterns={},            # ignored when url_template is set
        url_template=(
            "https://releases.hashicorp.com/terraform/{version}/"
            "terraform_{version}_{os}_{arch}.zip"
        ),
        extract_binaries=["terraform"],
        prefer_brew=False,  # force download even on macOS
    )
```

The `{version}`, `{os}`, and `{arch}` placeholders are substituted from
`get_latest_github_release(repo)`, `platform.system().lower()`, and
`_get_arch()` respectively.

## Architecture mapping

`_get_arch()` normalizes `platform.machine()` to the values most release
artifacts use:

| `platform.machine()` | `_get_arch()` |
| :--- | :--- |
| `x86_64` | `amd64` |
| `aarch64` | `arm64` |
| `arm64` | `arm64` (passthrough) |
| anything else | passthrough (lowercased) |

## macOS handling

By default, `install_tool()` runs `brew install <name>` on macOS. This
matches expectations on developer machines and avoids fighting Homebrew
over file ownership in `~/.local/bin`.

Pass `prefer_brew=False` to opt out — useful when you want consistent
cross-platform behavior (same binary, same version, same install path)
or when no brew formula exists. Setting `url_template` also implicitly
bypasses brew, since the template only makes sense when the caller wants
the download path on every OS.

## Security notes

- **Tar archives** use `tarfile.data_filter` (Python 3.12+) when
  available. This blocks symlink traversal, absolute paths, and
  parent-directory escapes at the tarfile layer.
- **All extraction** is basename-only — any path components inside the
  archive are stripped before writing into `dest_dir`. Even without
  `data_filter` this prevents writing outside the install directory.
- **Zip archives** additionally do a `Path.resolve()` zip-slip check as
  defense in depth.
- Extracted binaries are chmod'd to `0o755`.

### Integrity: what is and is not verified

Pass `sha256=` to `install_tool()` / `create_install_task()` to state the digest you
expect. It is verified **before** the archive is opened and **before** the executable
bit goes on, and a mismatch deletes the file and aborts — a failed verification can
never be mistaken for a completed install.

```python
create_install_task(
    name="terraform",
    repo="hashicorp/terraform",
    asset_patterns={},
    url_template="https://releases.hashicorp.com/terraform/{version}/terraform_{os}_{arch}.zip",
    sha256={"linux": "9d2b...", "darwin": "1f4c..."},   # per-platform, or a single str
)
```

**A digest is mandatory for hosts outside `IMPLICITLY_TRUSTED_HOSTS`** — that is, for
the `url_template` escape hatch, which exists to reach third parties such as
`releases.hashicorp.com`. Calling it without a digest aborts. GitHub-release installs
are unchanged and stay optional, because fetching them already rests on the same trust
as cloning this template.

**What this does not do, stated plainly:** it does not fetch upstream `*.sha256`
sibling files and verify against those. Over HTTPS from the same origin that serves the
asset, that defends against almost nothing — TLS already covers the transport, and an
attacker who can replace the asset can replace the checksum beside it. The protection
comes from a digest *you* pinned, which is why the parameter takes one from the caller
rather than fetching one.

Neither this nor anything else here defends against a compromised upstream release when
the digest floats with the version. `install_tool` resolves "latest" at run time; pinning
a version alongside a digest is what buys reproducibility, and is a deliberate
non-goal for now — see below.
- Status output uses ASCII `[OK]` rather than a checkmark glyph so it
  encodes cleanly on Windows cp1252 consoles (see issue #328).

## Future work

- **Pinned versions alongside pinned digests.** Today `install_tool` resolves the latest
  release at run time, so a caller-supplied `sha256` only holds for a known version. Pinning
  both would make installs reproducible and would detect a retagged or replaced upstream
  asset — at the cost of a digest matrix per tool per platform that ages and needs a refresh
  task. Deliberately deferred (#694).
- **GPG signature verification** for projects that publish detached signatures. Unlike a
  sibling checksum file, a signature is meaningful against a compromised release host,
  because the signing key is not served alongside the asset.
- **Archive caching** between runs to avoid redownloading on a fresh
  clone or CI runner.
- **Windows binary support** (PowerShell-friendly install path).

## Related ADR

- [ADR-9015: install_tools framework: archive extraction and custom URLs](https://github.com/endavis/pyproject-template/blob/main/docs/decisions/9015-install-tools-framework-archive-extraction-and-custom-urls.md)
