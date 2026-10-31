# Publication and release procedure

The public destination is **dick1980/itho-spider**, maintained by **@dick1980**, with MIT copyright attribution to **jdezine**. This repository starts with new history; the original private repository and installation evidence are not included. Issues, topics and private vulnerability reporting are enabled.

The first publication and release v0.4.1 are authorized. A release must wait for every required check below. Publishing a release does not authorize updating a running Home Assistant installation.

## Required checks for every release

1. Review changes and third-party provenance. Keep LICENSE, the [targeted blueprint review](BLUEPRINT-COMPARISON.md) and third-party notices. Reopen the review when adding third-party code or text.
2. Run the tests and Ruff using CONTRIBUTING.md. Verify the upgrade contract preserves the domain, config version, registry identities and stored options.
3. Review all files in `publication-files.txt` for private data, secrets and unintended artifacts. Do not add private installation notes, logs, captures, backups, screenshots or copied Git history.
4. Verify the actual GitHub repository settings and keep `publication.json` accurate. Run `python scripts/check_publication.py --release`.
5. Push the reviewed source. Hassfest uses the official image tagged for the supported Home Assistant version; update that pin with the tested runtime. Require all **Checks** jobs (tests, hassfest, HACS) and the manually dispatched **Release readiness** workflow to pass on the exact release commit. Resolve failures rather than disabling checks. Consult [Actions](https://github.com/dick1980/itho-spider/actions) for the actual outcomes.
6. Align manifest, pyproject, changelog and release tag (`0.4.1` / `v0.4.1`). Build with `python scripts/build_release.py --output dist` using an empty output directory; rebuild twice and compare checksums. Inspect both archives again.
7. Create the version tag on the checked commit. Publish a GitHub release with the installation ZIP, source ZIP and SHA256SUMS. Never overwrite an existing published tag or archive; increment the version instead.
8. Verify the public release and downloaded asset checksums. Record the commit, check runs and asset hashes in the private publication record.

The build script never uploads. The workflows have read-only permissions and do not create tags or releases. `--prepared` produces local review archives with `-prepared` filenames; normal builds enforce the release gate. The allowlist, fixed timestamps/permissions and absence of archive comments exclude unrelated filesystem metadata. The installation ZIP contains `custom_components/itho_spider/`; the source ZIP includes tests and documentation. SHA256SUMS and build.json record the build contents.

HACS uses the normal `custom_components` tree (`zip_release` is deliberately absent). `hacs.json` declares 2026.10.4 as the conservative tested minimum. Local 256px and 512px brand icons are included. A passing HACS validator does not prove a live HACS download or adoption of an existing installation; those remain separate tests. This repository is not submitted to the HACS default catalog.

Use patch versions for compatible fixes and minor versions for features. Schema changes require an explicitly planned migration; a package version increase must never casually change config version or unique IDs. Keep a tested rollback target and follow [UPGRADING.md](UPGRADING.md).

## Official references checked on 2026-10-31

- [Home Assistant manifest](https://contributors.home-assistant.io/core/integrations/manifest/): custom version, documentation, owners, integration type and issue tracker.
- [Config entries](https://contributors.home-assistant.io/core/integrations/config-entries/) and [entity registry](https://contributors.home-assistant.io/core/integrations/entity-registry/): keep stored identity stable; migrate deliberately.
- [Integration brands](https://contributors.home-assistant.io/core/integrations/brands/): local custom-integration icons; do not use Home Assistant branding.
- [HACS integration structure](https://www.hacs.xyz/docs/publish/integration/): one integration, required manifest fields, local brand assets, optional releases.
- [HACS general metadata](https://www.hacs.xyz/docs/publish/start/): public GitHub repository, description/topics, README and hacs.json options.
- [HACS validation action](https://www.hacs.xyz/docs/publish/action/) and [Home Assistant checks](https://contributors.home-assistant.io/core/development/checks/): prepared automated validation. These are distinct from physical protocol verification.
