"""Use the real Home Assistant test fixtures, with custom integration loading."""

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Enable loading this checkout as a custom integration."""
    yield
