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

DAILY_PRICE_CHF = 0.2580  # CHF/kWh
NIGHTLY_PRICE_CHF = 0.2347  # CHF/kWh
