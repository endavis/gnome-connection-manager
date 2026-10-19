"""Whether this repository has released a newer GCM than the one running (#295).

A release is a `vX.Y.Z` tag (#291), and GitHub lists the repository's tags at TAGS_URL,
measured to answer without signing in. The check this replaced asked the original
author's site, which serves that GCM's version, 1.2.1, and compared versions as
strings, under which "10.0.0" is less than "9.0.0" and 2.0.0 was never told of anything.

Pure: the tags and the running version are arguments, so nothing here needs a network.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

TAGS_URL = "https://api.github.com/repos/endavis/gnome-connection-manager/tags?per_page=100"

# Where the notice of a newer release sends people: the README's Installation.
INSTALL_PAGE = "https://github.com/endavis/gnome-connection-manager#installation"

# A release and nothing else: `v2.0.0`, not `v2.1.0rc1` or `latest`.
_RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def release_version(tag: str) -> tuple[int, int, int] | None:
    """The version a release tag names, as numbers, or None for any other tag."""
    match = _RELEASE_TAG.fullmatch(tag)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def tag_names(answer: object) -> list[str]:
    """The tag names in GitHub's answer, a list of objects each with a `name`. Anything
    else gives none, so that an answer changed or cut short reads as no release."""
    if not isinstance(answer, list):
        return []
    return [
        tag["name"] for tag in answer if isinstance(tag, dict) and isinstance(tag.get("name"), str)
    ]


def newer_release(tags: Iterable[str], running: str) -> str | None:
    """The newest release among `tags`, as `X.Y.Z`, if it is newer than `running`, the
    version as `app_version` gives it. None otherwise, and for a running version that is
    not a release's, such as one a developer has marked."""
    current = release_version("v" + running)
    releases = [version for version in map(release_version, tags) if version]
    if current is None or not releases or max(releases) <= current:
        return None
    return ".".join(map(str, max(releases)))
