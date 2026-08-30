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

1. **Assessment:** Verify and assess the reported vulnerability
2. **Fix Development:** Develop and test a fix in a private repository
3. **Advisory:** Create a security advisory with details
4. **Release:** Release a patched version
5. **Disclosure:** Publicly disclose the vulnerability after users have had time to update

## Vulnerability Disclosure Policy

- We follow coordinated disclosure
- Security advisories are published after a fix is released
- We request a 90-day embargo period for critical vulnerabilities
- Reporters are credited in security advisories

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

## Security Audit

Run a security audit of dependencies:

```bash
# Install security dependencies
uv pip install -e ".[security]"

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
