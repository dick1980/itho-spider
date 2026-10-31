# Validation of the prepared 0.4.1 source

Checked on 2026-10-31 with Python 3.14, Home Assistant 2026.10.4 and serialx 1.11.0.

| Check | Result |
| --- | --- |
| Original 0.4.0 suite | 159 tests and 46 subtests passed; loopback HTTP test run separately where socket binding is allowed |
| Candidate full suite | 169 tests and 46 subtests passed, including real HTTP form serialization |
| Frozen identity/migration contract against unchanged 0.4.0 code | 4 tests passed in an isolated temporary source copy |
| Same contract against 0.4.1 | Passed as part of the candidate suite |
| Ruff | Passed for component, tests and build/check scripts |
| Packaging | Repeat-build byte equality, exact allowlisted contents, archive metadata and source/content scans passed |
| Privacy preparation | Personal defaults and original radio identities removed; packed pairing identity replaced; no private history, installation artifacts, captures or screenshots included |
| Release gate | After targeted provenance review and MIT application, the only current local release-gate refusal is private vulnerability reporting, now enabled and verified on the public repository |

The ten additional tests cover four migration/registry cases, two existing-options form cases, probe-only default transport and three distribution cases. The existing HTTP test also now asserts that new gateway/Spider address fields have no defaults.

The registry test seeds 26 entities and three devices before candidate setup, preserves user customizations and disabled/hidden state, then unloads and sets up both configurations again. It checks shared USB ownership, battery options, identifiers and absence of startup RF commands. It does not use physical serial hardware. Existing controller/flow tests continue to cover pairing cancellation, physical-removal confirmations, relay isolation, battery waiting, protocol limits and source/echo validation.

Not performed: candidate installation on a live Home Assistant instance, a fresh public HACS download/adoption, hosted hassfest/HACS checks, physical unpairing, temperature changes or relay operations. The earlier 0.4.0 live observations are a baseline, not hardware validation of this candidate. Owner/repository, copyright attribution and conditional MIT choice have since been recorded. Package checks and archive hashes are refreshed with those choices; publication and hosted checks remain pending.

After confirming `dick1980/itho-spider`, maintainer `@dick1980`, copyright attribution to jdezine and conditional MIT selection, eight focused distribution, upgrade and dependency tests passed again. Ruff passed. No executable integration code changed in that follow-up. That historical result was superseded by the targeted blueprint review: MIT is now applied, with provenance documented; private vulnerability reporting has now been enabled and verified.

Following the targeted blueprint comparison, MIT was applied and license/notices were added to both distribution forms. Eight focused distribution/upgrade/dependency tests and Ruff passed again. Existing component files were hash-compared before/after and are unchanged; only two license/notice files were added. The packaging test now explicitly verifies license and third-party-notice inclusion. The source tree contains 63 allowlisted files, of which 24 are component files.

Publication preflight: the full suite passed again (169 tests, 46 subtests), as did Ruff. The repository is public, separate from the original, with issues/topics and private vulnerability reporting verified. Hosted checks are the next release gate; their actual results are available in GitHub Actions. No running Home Assistant installation has been changed.
