<p align="center">
<img src="custom_components/iaqualink_exoiq/icon.png" width="180">
</p>

# iAqualink eXO-IQ for Home Assistant

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-blue)
![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![GitHub release](https://img.shields.io/github/v/release/dje-dev/iaqualink_exoiq)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

Custom **Home Assistant integration** for **Zodiac / Fluidra iAqualink eXO-IQ pool controllers**.

This integration connects to the **Zodiac / Fluidra cloud API** and exposes pool equipment as Home Assistant entities.

---

# Features

- Native **Home Assistant entities**
- Support for **iAqualink eXO-IQ pool controllers**
- Automatic device discovery
- Automatic entity classification

### Equipment support

- Pool lights (`light`)
- Heat pump / heating (`climate`)
- Chlorinator production modes (`switch`)
- Boost mode
- Low production mode
- Sensors (temperature, ORP, pH, etc.)
- Pump schedules
- Editable schedules
- Schedule clear/reset

### System monitoring

A diagnostic device **Exo System** exposes:

- Serial number
- Firmware version
- Software version
- RSSI (Wi-Fi signal strength)
- MQTT status
- Error state
- Error code
- Last refresh timestamp

---

# Architecture

The integration communicates with the **Zodiac cloud API**.

Home Assistant
│
▼
Custom Integration
│
▼
Zodiac / Fluidra Cloud API
│
▼
eXO-IQ controller


---

# Installation

### Option 1 — HACS (recommended)

1. Open **HACS**
2. Go to **Integrations**
3. Click **Custom repositories**
4. Add: 
    https://github.com/dje-dev/iaqualink_exoiq
    Category: Integration

5. Install **iAqualink eXO-IQ**
6. Restart Home Assistant

---

### Option 2 — Manual installation

Copy the integration folder into:
    /config/custom_components/iaqualink_exoiq

Restart Home Assistant.

---

# Configuration

Add the integration via the Home Assistant UI:
    Settings → Devices & Services → Add Integration

Search for:
    iAqualink eXO-IQ


Then enter your **iAqualink account credentials**.

---

# Entities
Example entities created by the integration:

### Lights
light.pool_light

### Chlorinator
switch.chlorinator_production
switch.chlorinator_boost
switch.chlorinator_low

### Sensors
sensor.pool_temperature
sensor.pool_ph
sensor.pool_orp

### Heating
climate.pool_heater

### Schedules
timer.timer_1
timer.timer_2
timer.timer_3
timer.timer_4

Schedules can be edited directly from Home Assistant.

---

# Diagnostics device
The integration creates a diagnostic device:
- Exo System

Used to monitor connectivity and firmware information.

---

# Stability

The integration includes protections against common API issues:

- Automatic session recovery (`401 retry`)
- Rate limit handling (`429`)
- Request cooldown after schedule edits
- Optimistic state updates

Note:  
The Zodiac cloud API can occasionally be unstable or rate-limited.

---

# Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.iaqualink_exoiq: debug
```

---

# Changelog & Releases

This repository keeps a change log using [GitHub's releases](https://github.com/dej2912/iaqualink_exoiq/releases) functionality.

Releases are based on [Semantic Versioning](https://semver.org/spec/v2.0.0), and use the format of MAJOR.MINOR.PATCH. In a nutshell, the version will be incremented based on the following:

- MAJOR: Incompatible or major changes.
- MINOR: Backwards-compatible new features and enhancements.
- PATCH: Backwards-compatible bugfixes and package updates.

---

# Supported hardware

- Zodiac eXO-IQ
- Fluidra eXO controllers using the iAqualink cloud API

---

# Contributing
Contributions are welcome.

Feel free to open:
- Issues
- Feature requests
- Pull requests

---

# Disclaimer

This project is not affiliated with Zodiac, Fluidra, or iAqualink.

It is an independent open-source integration for Home Assistant.

---

# License

MIT License
