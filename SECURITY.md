# Reporting and data handling

This is a local custom integration. Do not post credentials, Home Assistant backups, `.storage`, raw RF captures or identifying screenshots in public issues. Redact serial paths, radio addresses, hostnames, local network addresses and personal room names from logs. The diagnostics exporter redacts fixed configuration fields; exception messages can still contain identifiers or paths.

Private vulnerability reporting is enabled. Report security issues through [GitHub’s private reporting form](https://github.com/dick1980/itho-spider/security/advisories/new); the responsible maintainer is @dick1980. Do not report an unredacted security issue publicly. Ordinary bug reports should use a minimal anonymized reproduction and state whether results came from software simulation or physical hardware.

The integration never needs a Home Assistant access token in its configuration. It accepts local serial device paths only, shares one verified USB transport internally and exposes no arbitrary gateway-command service. Receive-only mode disables RF sends. Supported temperature control and automatic acknowledgements require explicit configuration and bounded protocol validation.
