---
title: Consumer Notes
description: Breaking changes and behaviour changes that arrive when a project syncs from the template.
---

# Consumer Notes

Changes that **reach a downstream project through the sync path** and need action, or need
explaining when someone notices them. Newest first.

This page exists because the alternative failed. The `sha256` change below was documented in
ADR-9015 and in the install-tools reference, and neither is read during a sync — so a project
syncing `tools/doit/install_tools.py` got a runtime abort with no prior warning. Per-topic docs are
the right home for *how a thing works*; this is the home for *what will change under you*.

Read it after `bootstrap.py --sync` and before adopting drift. It is also linked from
[Files to Review Carefully](updates.md#files-to-review-carefully) and the
[AI Sync Checklist](ai-sync-checklist.md).

## Breaking

### `install_tools` requires `sha256` for untrusted hosts

**What changed.** A download from any host outside `IMPLICITLY_TRUSTED_HOSTS` — `github.com`,
`objects.githubusercontent.com`, `raw.githubusercontent.com`, `api.github.com` — must now be
accompanied by an expected digest. Without one the install aborts with `IntegrityError` before the
file is made executable.

**Who breaks.** Any caller passing `url_template` for a non-GitHub host. That is precisely the case
`url_template` was introduced for (ADR-9015 names `releases.hashicorp.com`, terraform and opentofu),
so the projects most likely to hit this are the ones the feature was built for.

**What it looks like.**

```
IntegrityError: https://releases.hashicorp.com/... is outside ['api.github.com',
'github.com', 'objects.githubusercontent.com', 'raw.githubusercontent.com'] and no
sha256 was given. Pass sha256= to install_tool()/create_install_task() naming the
digest you expect
```

**The fix.** Pass the digest you expect. `sha256` accepts a single string, or a dict keyed the same
way as `asset_patterns` when the digest differs per platform:

```python
create_install_task(
    name="terraform",
    url_template="https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{os}_{arch}.zip",
    sha256={"linux-x86_64": "…", "darwin-arm64": "…"},
)
```

Publishers of this kind ship a checksums file alongside the release; take the digest from there
rather than computing it from a download you have not yet verified.

**Why it is not optional.** `url_template` fetches from arbitrary third parties, which is exactly
where an implicit trust assumption should not be extended. See
[install-tools framework](../development/install-tools-framework.md) and ADR-9015.

## Needs a one-off action

### Re-run `doit pre_commit_install`

**Who.** Every project that ran it *before* adopting the `.pre-commit-config.yaml` that declares
`default_install_hook_types`.

**Why.** The config now declares four hook types, and `commit-msg` is newly among them. A project
that installed hooks earlier has no `commit-msg` hook on disk, so **neither conventional-commit
enforcement nor the branch/issue check runs for it** — silently, because nothing fails when a hook
that was never installed does not fire.

```bash
doit pre_commit_install
```

Verify with `ls .git/hooks/` — `commit-msg`, `pre-commit`, `post-merge` and `post-checkout` should
all be present.

## Behaviour you will notice

### Conventional-commit enforcement is live

It was configured but dormant while `commit-msg` was never installed. Commit messages that
previously succeeded are now rejected unless they match `<type>: <subject>`. See
[Commit Guidelines](../../.github/CONTRIBUTING.md#commit-guidelines).

### The dangerous-command hook blocks more

`tools/hooks/ai/block-dangerous-commands.py` now scans heredoc bodies that a POSIX shell executes,
so `bash <<EOF` carrying a blocked pattern aborts where it previously ran. It fails safe — the newly
blocked shapes are ones the hook already intended to catch — but a command that worked before may
stop. See [AI Command Blocking](../development/ai/command-blocking.md#heredocs).

### Long commit messages go in a file

A commit message passed by heredoc is scanned as command arguments, so a message that merely *names*
a blocked pattern is refused. Write it to `tmp/agents/<agent-type>/` and pass `git commit -F <file>`;
the block now says so rather than giving a generic reason. See
[Passing the Message](../../.github/CONTRIBUTING.md#commit-guidelines).

### PRs get no benchmark regression comment

The benchmark still runs and uploads its JSON. The comment required `contents: write` on the pull
request path and was removed with it; read the workflow artifact instead.

### Dependabot proposes exact-version action bumps

GitHub Actions are SHA-pinned, so dependabot now proposes `from 6.3.0 to 7.0.0` rather than
major-to-major `from 6 to 7`. The pin is the point — review the SHA, not only the version.

## Adding to this page

An entry belongs here when a downstream project would be **surprised** by the change: it breaks a
call that worked, requires a one-off action, or alters behaviour someone will notice without an
explanation to hand. Ordinary improvements do not need an entry.

Put the *reasoning* in the ADR or the per-topic doc and link it. This page answers "what changes
under me, and what do I do about it" — nothing else.
