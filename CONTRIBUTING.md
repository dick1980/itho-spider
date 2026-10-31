# Development

Use Python 3.14 and the exact development dependency pins in `pyproject.toml`:

```sh
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --group dev serialx==1.11.0
.venv/bin/python -m pytest
.venv/bin/ruff check custom_components tests scripts
.venv/bin/python scripts/check_publication.py
.venv/bin/python scripts/build_release.py --output dist --prepared
```

The full suite includes an HTTP test listening only on loopback and serialx software-PTY tests. No physical USB gateway, Home Assistant credentials, network RF proxy or thermostat is required. Tests must never access a physical serial port. `--prepared` explicitly permits local review archives with unresolved publication metadata; ordinary builds refuse unresolved decisions.

The tested runtime is Home Assistant 2026.10.4 with serialx 1.11.0. The runtime manifest declares `serialx>=1.11.0` so Home Assistant can apply its own shared-dependency constraint; the development command above keeps the tested version fixed. Development top-level dependencies are pinned; transitive dependency resolution is not locked and CI failures after upstream changes must be investigated. Do not raise the Home Assistant minimum or upgrade dependency pins without compatibility checks.

Keep the [identity contract](docs/COMPATIBILITY.md). Protocol changes need independent evidence and regression tests for receive-only mode, echo rejection, stale data, local overrides, rate limits, battery cancellation and relay isolation. Document hardware validation separately from simulation. Do not widen allowed messages or claim physical unpairing based on a timer, lack of traffic, or a UI confirmation alone.

Fixtures use synthetic RF addresses and generic names. Do not commit `.storage`, `.env`, tokens, captures, backups, installation reports, screenshots or private paths. Review every new file and generated archive, including metadata. Security and privacy checks are guardrails, not proof that arbitrary new content is safe.
