# Validation of version 0.4.1

Checked on 2026-10-31 with Python 3.14, Home Assistant 2026.10.4 and serialx 1.11.0.

| Check | Result |
| --- | --- |
| Original 0.4.0 suite | 159 tests and 46 subtests passed |
| 0.4.1 full suite | 169 tests and 46 subtests passed, including real HTTP form serialization; repeated before publication |
| Frozen identity/migration contract against unchanged 0.4.0 code | 4 tests passed in an isolated temporary source copy |
| Same contract against 0.4.1 | Passed as part of the full suite |
| Ruff | Passed for component, tests and build/check scripts |
| Packaging | Repeat-build byte equality, exact allowlisted contents, license/notices and archive metadata checks passed |
| Privacy | Personal defaults and original radio identities removed; no private history, installation artifacts, captures or screenshots included |
| Repository | Separate public repository; issues, topics and private vulnerability reporting enabled and verified |
| Local release gate | Passed after provenance review, MIT application and repository configuration |
| Hosted checks | All Checks jobs and Release readiness must pass on the release commit before a release is published; see [GitHub Actions](https://github.com/dick1980/itho-spider/actions) |

The ten additional tests cover four migration/registry cases, two existing-options form cases, probe-only default transport and three distribution cases. The existing HTTP test also asserts that new gateway/Spider address fields have no defaults.

The registry test seeds 26 entities and three devices before setup, preserves user customizations and disabled/hidden state, then unloads and sets up both configurations again. It checks shared USB ownership, battery options, identifiers and absence of startup RF commands. It does not use physical serial hardware. Existing controller/flow tests continue to cover pairing cancellation, physical-removal confirmations, relay isolation, battery waiting, protocol limits and source/echo validation.

The distribution contains 63 allowlisted files, of which 24 are component files. Both installation and source archives retain the project LICENSE and full third-party notices. The targeted blueprint comparison and its limitations are documented separately; the upstream blueprint itself is not distributed.

Not performed: installation of 0.4.1 on a live Home Assistant instance, a fresh HACS download/adoption, physical unpairing, temperature changes or relay operations. Earlier 0.4.0 live observations are a baseline, not hardware validation of 0.4.1. A passing HACS validator does not prove an existing installation has been adopted successfully. No running Home Assistant installation was changed during publication.
