# Security Policy

## Supported Versions

The following versions of OpenPaw are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4.0 | :x:                |

## Reporting a Vulnerability

OpenPaw is a pre-1.0 project in active beta development. Security is taken seriously, and we appreciate responsible disclosure.

To report a security vulnerability:

1. **Email:** Send a report to [johnsosoka@gmail.com](mailto:johnsosoka@gmail.com) with details.
2. **GitHub Private Vulnerability Reporting:** Use [GitHub Security Advisories](https://github.com/johnsosoka/OpenPaw/security/advisories) to submit a private report.

Please include the following in your report:

- A clear description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact
- Any suggested remediation

We will acknowledge receipt within 48 hours and provide a timeline for resolution.

## Security Policy

- All dependencies are pinned to minimum versions and regularly audited.
- CI runs on every PR with automated checks.
- API keys and secrets are workspace-scoped and never logged.
- Sandboxed filesystem access prevents agents from escaping their workspace.

## Disclosure Policy

Once a fix is prepared, we will:

1. Coordinate with the reporter on the disclosure timeline.
2. Release a patched version.
3. Publish a security advisory on GitHub.
4. Update the CHANGELOG.md with the fix details.

## Scope

This policy covers the `openpaw` Python package (`openpaw-ai` on PyPI) and the official repository at https://github.com/johnsosoka/OpenPaw.
