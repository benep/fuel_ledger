"""Texts the integration writes into Home Assistant itself: device models and default names.

Device registry fields and subentry titles are not translated by Home Assistant, so they are taken from the "device"
section of the translations, in the language of Home Assistant (English for keys a language lacks).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN

# Keys in the "device" section of strings.json.
HEATING_OIL = "heating_oil"  # model of the main device for heating oil, also its default name
TANK = "tank"  # model of a tank, also the default name of the tanks the first setup creates


async def async_texts(hass: HomeAssistant) -> dict[str, str]:
    """Key → text, for the keys above."""
    translations = await async_get_translations(hass, hass.config.language, "device", {DOMAIN})
    prefix, suffix = f"component.{DOMAIN}.device.", ".name"
    return {
        key[len(prefix) : -len(suffix)]: text
        for key, text in translations.items()
        if key.startswith(prefix) and key.endswith(suffix)
    }
