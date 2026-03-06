from __future__ import annotations
from datetime import timedelta

AQUALINK_API_KEY = "EOOEMOW4YR6QNB07"

AQUALINK_LOGIN_URL = "https://prod.zodiac-io.com/users/v1/login"
AQUALINK_DEVICES_URL = "https://r-api.iaqualink.net/devices.json"

KEEPALIVE_EXPIRY = 30
MIN_SECS_TO_REFRESH = 60

"""Constants for the iaqualink component."""
DOMAIN = "iaqualink_exoiq"
UPDATE_INTERVAL = timedelta(seconds=120)

AQUALINK_TEMP_CELSIUS_HIGH = 40
AQUALINK_TEMP_CELSIUS_LOW = 5
AQUALINK_TEMP_FAHRENHEIT_HIGH = 104  # 40°C en Fahrenheit
AQUALINK_TEMP_FAHRENHEIT_LOW = 41    # 5°C en Fahrenheit
