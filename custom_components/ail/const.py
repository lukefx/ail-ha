"""Constants for the AIL integration."""

from datetime import timedelta

DOMAIN = "ail"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_MFA_CODE = "mfa_code"
CONF_SESSION_STATE = "session_state"
CONF_FIXED_TARIFF = "fixed_tariff"
CONF_PEAK_PRICE = "peak_price"
CONF_OFF_PEAK_PRICE = "off_peak_price"

LEGACY_CONF_FIXED_TARIFF = "Flex Tariff"
LEGACY_CONF_PEAK_PRICE = "Peak price"
LEGACY_CONF_OFF_PEAK_PRICE = "Off-Peak Price"

# Statistic IDs for Home Assistant Energy dashboard
ENERGY_CONSUMPTION_KEY = f"{DOMAIN}:energy_consumption"
ENERGY_DAY_CONSUMPTION_KEY = f"{DOMAIN}:energy_day_consumption"
ENERGY_NIGHT_CONSUMPTION_KEY = f"{DOMAIN}:energy_night_consumption"

ENERGY_CONSUMPTION_COST_DAY_KEY = f"{DOMAIN}:energy_day_consumption_cost"
ENERGY_CONSUMPTION_COST_NIGHT_KEY = f"{DOMAIN}:energy_night_consumption_cost"

# Update interval
DEFAULT_UPDATE_INTERVAL_HOUR = 1
CONSUMPTION_DATA_DAYS_TO_FETCH = 14

# The hourly poll only renews the Energy Buddy session; the Keycloak session is
# never touched, so it idles out long before the portal session does and every
# recovery would need the e-mailed code. This task touches the authorize
# endpoint instead. Keep it below the realm's SSO idle timeout.
SSO_KEEPALIVE_INTERVAL = timedelta(minutes=30)

DAILY_PRICE_CHF = 0.2580  # CHF/kWh
NIGHTLY_PRICE_CHF = 0.2347  # CHF/kWh
