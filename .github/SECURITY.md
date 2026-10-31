# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of the following methods:

### Preferred Method: Private Security Advisory

1. Go to the [Security tab](https://github.com/endavis/gnome-connection-manager/security)
2. Click "Report a vulnerability"
3. Fill out the form with details

### Alternative: Email

Send an email to: security@example.com

Include as much information as possible:
- Type of vulnerability
- Affected versions
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### What to Expect

- **Acknowledgment:** We will acknowledge receipt within 48 hours
- **Assessment:** We will assess the vulnerability and determine severity
- **Updates:** We will keep you informed of progress every 7 days
- **Resolution:** We aim to release a fix within 90 days for high-severity issues
- **Credit:** We will credit you in the security advisory (unless you prefer to remain anonymous)

## Security Update Process

A finding takes one of two tracks, depending on the code it is in.

### The package

This track covers `src/`, the code released to users.

1. **Assessment:** Verify and assess the reported vulnerability
2. **Fix Development:** Develop and test a fix in a private repository, such as the security advisory's temporary private fork
3. **Advisory:** Create a security advisory with details
4. **Release:** Release a patched version
5. **Disclosure:** Publicly disclose the vulnerability after users have had time to update

### Development tooling

This track covers `tools/`, the AI agent hooks and the `doit` tasks. That code runs only on a developer's machine. The AI command hook is a guardrail, not a security boundary ([ADR-9019](../docs/decisions/9019-the-dangerous-command-hook-is-a-guardrail-not-a-security-boundary.md)).

1. **Report:** Reproduce the finding, keeping the command and its output, and file it as a private draft security advisory.
2. **Fix in the open, worded neutrally:** The fix takes the normal Issue → Branch → PR → Merge flow, so CI runs on it. The issue, PR and commit messages describe the change, such as "compare the example to HEAD by content". They never describe the bypass, include reproduction commands or name the advisory.
3. **Close:** After the merge, close the advisory without publishing it:
   `gh api -X PATCH repos/{owner}/{repo}/security-advisories/<ghsa_id> -f state=closed`.
   No CVE is requested.

The fix diff is public between push and merge. That is accepted for development tooling, whose exposure is an agent working in the repository, not users of a release. Temporary private forks would keep it private, but CI does not run in them and a fork PR can be merged only from the advisory page.

Projects created from the template pick up these fixes by syncing with it. The session-start update notice tells them when they are behind ([Update notice at session start](../docs/template/updates.md#update-notice-at-session-start)).

## Vulnerability Disclosure Policy

- We follow coordinated disclosure
- Security advisories for the package are published after a fix is released
- Security advisories for development tooling are closed after the fix is merged, not published
- We request a 90-day embargo period for critical vulnerabilities
- Reporters are credited in published security advisories

## Security Best Practices

When using this package:

1. **Keep Updated:** Always use the latest version
2. **Review Dependencies:** Regularly audit dependencies for known vulnerabilities
3. **Secure Configuration:** Follow security best practices in configuration
4. **Environment Variables:** Never commit secrets to version control
5. **Access Control:** Limit access to production systems

## Known Security Considerations

### Environment Variables

This package may read sensitive data from environment variables. Always:
- Use `.envrc.local` for secrets (git-ignored)
- Never commit `.env` files with real credentials
- Use secrets management in production (e.g., AWS Secrets Manager, HashiCorp Vault)

### Dependencies

We use automated tools to monitor dependencies:
- Dependabot for dependency updates
- GitHub Security Advisories for known vulnerabilities
- Regular security audits with `doit audit` (pip-audit)

### Untrusted Branches

Review a branch you don't trust — a fork PR, a dependabot branch, any contributor branch you
haven't read — before running anything on it, `doit` included. Tools that read config from the
working tree (`pre-commit`, `doit`, `uv`) read whatever is checked out, so checking out the branch
is already enough to run its code if the tool fires automatically; see
endavis/pyproject-template#1033 for the case that prompted this.

## Security Audit

Run a security audit of dependencies:

```bash
# Install the security extra with the other development tools
doit install_dev

# Run security audit
doit audit
```

## Bug Bounty Program

We currently do not have a bug bounty program.

## Hall of Fame

We recognize security researchers who help us keep this project secure:

<!-- Add contributors here as vulnerabilities are reported and fixed -->

- *Your name could be here!*

## Questions?

If you have questions about this security policy, please open a GitHub issue with the "security" label or contact us at security@example.com.

---

Last updated: 2025-12-05
