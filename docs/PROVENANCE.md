# Provenance and attribution

Reviewed on 2026-10-31. The [targeted blueprint comparison](BLUEPRINT-COMPARISON.md) supersedes the earlier precautionary block based only on the absence of an upstream license. It found protocol/profile reuse, but no concrete copied expressive code, prose or creative program structure. For that identified use, author permission is no longer treated as a mandatory release condition. This is a scoped technical assessment, not a legal clearance certificate.

| Source | Use and treatment |
| --- | --- |
| Project integration, tests, docs and neutral geometric icon | MIT, `Copyright (c) 2026 jdezine`; see root LICENSE |
| [ramses_rf](https://github.com/ramses-rf/ramses_rf) parsers and regression examples | Protocol interpretation reference. Its local reference copy's complete MIT notice is retained in `docs/third-party/ramses_rf-LICENSE.txt` and the component's THIRD_PARTY_NOTICES.txt. No upstream package or firmware is bundled |
| [Onl1ne1373 Spider blueprint v1.18](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml) | Reference for the fixed manual `01FF` profile and gateway-accept layout. Credit retained. The original YAML, UI instructions and scheduling automation are not distributed; its license is not changed by this project's MIT license |
| [ramses_rf issue 73](https://github.com/ramses-rf/ramses_rf/issues/73) | Evidence about incompletely understood `01FF` fields; no issue body or attached capture distributed |
| Local packet observations | Short protocol fixtures and two strictly matched pairing profiles. Addresses replaced, including packed identity; original captures excluded |

The blueprint reference was verified against Git blob `f3d2ce96699416e1ccd6d1687499f75237fb3f91`, at commit `fbe82495e1f72ab91d62969ce863668dea0c31e0`. It declares version 1.18. This identifies a matching inspectable reference, not necessarily the exact original download by an earlier developer. No inline or repository-root license was found, and GitHub metadata returned `license: null`; this does not make the blueprint public domain. The reassessment rests on the specific material used, not on public visibility.

All 24 fixed bytes of the 26-byte `01FF` profile match. Their meaning is not fully understood, so we do not claim every byte is indispensable or that the profile preserves every device setting. We retain the observed second temperature field instead of the blueprint's calculated target plus one. See the comparison for the address, pairing, acknowledgement, retry, structure and prose findings.

The existing source attribution remains intact. No independent-discovery claim is made for the profile, no upstream permission is claimed, and no author message has been sent. This distribution includes no decompiled software, firmware binaries, vendor manuals, original radio dumps or upstream Git history. Review new third-party additions on their own merits.
