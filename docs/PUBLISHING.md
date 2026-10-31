# Releasing

1. Align the version in the manifest and pyproject, and update CHANGELOG.md.
2. Run tests, Ruff and `python scripts/check_publication.py --release`.
3. Push the reviewed commit and require all GitHub Checks jobs and Release readiness to pass on that commit.
4. Build into an empty directory with `python scripts/build_release.py --output dist`. Review the contents and SHA256SUMS.
5. Tag the checked commit and publish the installation ZIP, source ZIP and SHA256SUMS as a GitHub release. Verify the downloaded files.

Never replace an existing published tag or archive. Keep LICENSE and third-party notices in every distribution. Publishing a release does not install it on Home Assistant.

HACS uses the normal `custom_components/itho_spider` tree. This repository is available as a custom repository; it is not in the HACS default catalog.
