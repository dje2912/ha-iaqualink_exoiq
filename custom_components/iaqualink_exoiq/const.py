from __future__ import annotations
from datetime import timedelta

AQUALINK_API_KEY = "EOOEMOW4YR6QNB07"

AQUALINK_LOGIN_URL = "https://prod.zodiac-io.com/users/v1/login"
AQUALINK_DEVICES_URL = "https://r-api.iaqualink.net/devices.json"

KEEPALIVE_EXPIRY = 30
MIN_SECS_TO_REFRESH = 60

"""Constants for the iaqualink component."""
DOMAIN = "iaqualink_exoiq"
MANUFACTURER = "Zodiac by Dje"
UPDATE_INTERVAL = timedelta(seconds=120)

AQUALINK_TEMP_CELSIUS_HIGH = 40
AQUALINK_TEMP_CELSIUS_LOW = 5
AQUALINK_TEMP_FAHRENHEIT_HIGH = 104  # 40°C en Fahrenheit
AQUALINK_TEMP_FAHRENHEIT_LOW = 41    # 5°C en Fahrenheit

ENTITY_ICONS = {
    # System Sensor
    "ph": "mdi:ph",
    "ph_sp": "mdi:ph",
    "orp": "mdi:flash",
    "orp_sp": "mdi:flash",
    "water_temp": "mdi:pool-thermometer",
    "temp": "mdi:thermometer-water",
    "production": "mdi:percent",
    "boost": "mdi:rocket-launch",
    "swc": "mdi:percent",
    "swc_low": "mdi:percent",
    "vsp_speed": "mdi:fan-speed-3",
    
    # Diagnostic Sensor
    "rssi": "mdi:wifi",
    "fw_version": "mdi:memory",
    "vr": "mdi:memory",
    "version": "mdi:chip",
    "sn": "mdi:identifier",
    "error_state": "mdi:alert-circle",
    "error_code": "mdi:alert-circle-outline",
    "cloud_status": "mdi:connection",

    # Diagnostic binary sensors
    "exo_state": "mdi:lan-connect",
    "mqtt_connection": "mdi:connection",
    "filter_pump": "mdi:pump",
}

ENTITY_SYSTEM_SENSOR_NAMES = {
    "ph": "pH",
    "orp": "ORP",
    "water_temp": "Water Temperature",
}

ENTITY_DIAG_SENSOR_NAMES = {
    "sn": "eXO-IQ S/N",
    "vr": "eXO-IQ Firmware Version",
    "version": "eXO-IQ Software Version",
    "error_state": "eXO-IQ Error State",
    "error_code": "eXO-IQ Error Code",
    "rssi": "eXO-IQ RSSI",
    "fw_version": "Cloud Firwware Version",
    "cloud_status": "eXO-IQ Cloud Status",
    "cloud_timestamp": "Cloud Timestamp",
    "last_refresh": "Cloud Last Refresh",
}

ENTITY_DIAG_BINARY_SENSOR_NAMES = {
    "exo_state": "eXO-IQ State",
    "mqtt_connection": "Cloud MQTT Connection",
}