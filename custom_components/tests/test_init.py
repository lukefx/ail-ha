"""Test component setup."""

from homeassistant.setup import async_setup_component

from custom_components.ail.const import DOMAIN

from custom_components.tests.conftest import auto_enable_custom_integrations  # noqa: F401


async def test_async_setup(hass):
    """Test the component gets setup."""
    assert await async_setup_component(hass, DOMAIN, {}) is True
