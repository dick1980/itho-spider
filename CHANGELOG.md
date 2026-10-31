# Changelog

## 0.4.1 — 2026-10-31

- Distribute independent source without private Git history or installation evidence.
- Remove personal address/name defaults from new configuration forms. Require explicit identity for transport RF sends; identity-less transport is probe-only.
- Declare serialx with a compatible minimum (>=1.11.0), as required for shared Home Assistant dependencies; Home Assistant 2026.10.4 retains its constrained 1.11.0 version.
- Preserve domain, config version 2, v1 migration, all registry identities and saved options.
- Replace installation-specific test identities with synthetic fixtures; add upgrade and distribution regression checks.
- Add installation, management, battery, troubleshooting, upgrade/rollback, provenance and maintainer documentation.
- Add reproducible archives and validation workflows. Owner/maintainer `dick1980`, repository `dick1980/itho-spider` and copyright holder `jdezine` are confirmed. MIT is applied following the targeted protocol-profile comparison; source attribution and third-party notices are retained.

## 0.4.0

Guided setup/pairing and separate Home Assistant-only removal / guided physical gateway removal. Shared USB connection, battery wakeup option and existing protocol restrictions retained. Physical unpairing is a user action, never automatically proven by Home Assistant.

## Earlier compatibility milestones

- 0.3.1: unchanged repeated local setpoint reports no longer cancel a waiting battery command.
- 0.3.0: optional battery wait and command status.
- 0.2.1: second strictly matched gateway pairing profile.
- 0.1.2: matching W/22C9 reports acknowledge temperature commands.
- 0.1.1: serialx pin aligned with Home Assistant.
