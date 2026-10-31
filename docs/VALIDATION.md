# Testing

The suite uses Python 3.14, Home Assistant 2026.10.4 and serialx 1.11.0. It covers configuration flows, shared USB ownership, battery waiting, confirmed commands, registry identity, removal procedures, protocol limits and deterministic packages. It uses mocks, loopback HTTP and software PTYs; no physical hardware is required.

GitHub Checks runs pytest, Ruff, package checks, HACS and hassfest for both Home Assistant 2026.10.4 and latest. See [Actions](https://github.com/dick1980/itho-spider/actions) for results. Passing software checks does not establish compatibility with every hardware/firmware variant. A live HACS installation has not yet been verified.
