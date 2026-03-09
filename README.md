<p align="center">
<img src="custom_components/iaqualink_exoiq/icon.png" width="180">
</p>

# iAqualink ExoIQ for Home Assistant

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![Status](https://img.shields.io/badge/Status-Stable-brightgreen)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

Custom **Home Assistant integration** for **Zodiac / Fluidra iAqualink ExoIQ pool controllers**.

This integration connects to the **Zodiac cloud API** and exposes pool equipment as Home Assistant entities.

Supported equipment:

- Pool lights
- Heat pump / heating
- Chlorinator production modes
- Boost mode
- Low production mode
- Sensors (temperature, ORP, pH, etc.)
- Schedules

---

## Features

- ExoIQ cloud API support
- Native Home Assistant entities
- Automatic entity classification
- Heating control via `climate` entity
- AUX lights via `light` entity
- Chlorinator modes via `switch` entities
- Optimistic UI updates
- Automatic session recovery (401 retry)
- Rate limit handling

---

## Installation

### 1. Copy the integration

Copy the folder into:

```text
/config/custom_components/iaqualink_exoiq
