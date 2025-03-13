DOMAIN = "ail"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_FIXED_TARIFF = "Flex Tariff"
CONF_PEAK_PRICE = "Peak price"
CONF_OFF_PEAK_PRICE = "Off-Peak Price"

# Statistic IDs for Home Assistant Energy dashboard
ENERGY_CONSUMPTION_KEY = f"{DOMAIN}:energy_consumption"
ENERGY_DAY_CONSUMPTION_KEY = f"{DOMAIN}:energy_day_consumption"
ENERGY_NIGHT_CONSUMPTION_KEY = f"{DOMAIN}:energy_night_consumption"

ENERGY_CONSUMPTION_COST_DAY_KEY = f"{DOMAIN}:energy_day_consumption_cost"
ENERGY_CONSUMPTION_COST_NIGHT_KEY = f"{DOMAIN}:energy_night_consumption_cost"

# Update interval
DEFAULT_UPDATE_INTERVAL_HOUR = 1

DAILY_PRICE_CHF = 0.1065    # CHF/kWh
NIGHTLY_PRICE_CHF = 0.0920  # CHF/kWh
