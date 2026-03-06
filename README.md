iAqualink ExoIQ for Home Assistant








Custom Home Assistant integration for Zodiac / Fluidra iAqualink ExoIQ pool controllers.

This integration connects to the Zodiac cloud API and exposes pool equipment as Home Assistant entities.

Supported equipment:

Pool lights

Heat pump / heating

Chlorinator production modes

Boost mode

Low production mode

Sensors (temperature, ORP, pH, etc.)

Schedules

Features

✔ ExoIQ cloud API support
✔ Native Home Assistant entities
✔ Automatic entity classification
✔ Heating control via climate entity
✔ AUX lights via light entity
✔ Chlorinator modes via switch entities
✔ Optimistic UI updates
✔ Automatic session recovery (401 retry)
✔ Rate limit handling

Installation
1️⃣ Copy the integration

Copy the folder into:

/config/custom_components/iaqualink_exoiq

Restart Home Assistant.

2️⃣ Add the integration

Go to:

Settings → Devices & Services → Add Integration

Search for:

iAqualink ExoIQ

Enter your iAqualink credentials.

Entities Created

Example entities created by the integration.

Entity	Type	Description
light.aux1_light	Light	Pool light
climate.aux2_heating	Climate	Heat pump
switch.boost	Switch	Chlorinator boost
switch.low	Switch	Reduced production
switch.production	Switch	Chlorinator production
sensor.water_temp	Sensor	Pool water temperature
Heating (Climate Entity)

The heat pump is exposed as:

climate.aux2_heating

Supported features:

Turn heating ON / OFF

Adjust target temperature

View current water temperature

Attributes exposed:

Attribute	Description
sp	target temperature
sp_min	minimum allowed
sp_max	maximum allowed
enabled	heating enabled
priority_enabled	heating priority
state	heating state

Current temperature uses sensor priority:

sns_3 → water_temp → temp
Light Entities

Example API data:

"aux_1": {
  "color": 0,
  "type": "light",
  "state": 0
}

Created entity:

light.aux1_light

Currently supported:

ON / OFF control

Future support possible for RGB lights.

ExoIQ API Behaviour

The Exo system does not expose a single operating mode.

Instead it exposes separate flags.

Example:

{
  "production": 2,
  "low": 0,
  "boost": 0
}
Mode Derivation

The mode shown in the Zodiac application is derived from those flags:

Priority	Condition	Mode
1	boost == 1	BOOST
2	low == 1	LOW
3	production == 2	AUTO
LOW mode behaviour

LOW is not a strict manual mode.

The controller can force it automatically.

Example triggers:

pool cover closed

internal safety logic

Meaning:

Command	Reliability
low = 1	always works
low = 0	may be overridden
Leaving LOW mode

The official Zodiac application does not disable LOW directly.

Instead it changes context:

Desired Mode	Commands
AUTO	low=0 and boost=0
BOOST	boost=1
Entity Classification Logic

AUX devices are classified using the API attribute:

"type"
Lights
"type": "light"

→ Home Assistant light entity

Example:

aux_1 → light.aux1_light
Heating
"type": "heat"

→ Home Assistant climate entity

Example:

aux_2 → climate.aux2_heating
Ignored AUX

Some AUX entries (example aux230) have no type attribute.

These are ignored by the integration.

Optimistic UI Updates

The Zodiac cloud API can take up to ~120 seconds to reflect commands.

Without mitigation, Home Assistant would revert the UI state.

The integration implements optimistic state handling.

Supported for:

Entity	Supported
Lights	✔
Switches	✔
Climate	✔

Behaviour:

1️⃣ UI updates immediately
2️⃣ Command is sent to API
3️⃣ Next refresh confirms real state

Cloud API Reliability

The Zodiac API frequently returns:

401 Unauthorized

when the session expires.

The integration automatically:

re-authenticates

retries requests

handles rate limits (429)

retries network errors

Refresh Strategy

To avoid excessive API calls:

MIN_SECS_TO_REFRESH = 120

Commands can still trigger forced refresh.

Summary

The Exo controller is not controlled using a single mode but through a combination of independent flags.

This integration converts those flags into stable and user-friendly Home Assistant entities.

Disclaimer

This project is not affiliated with Zodiac or Fluidra.

It is a reverse-engineered integration based on the public behaviour of the iAqualink cloud API.

Author

Developed and maintained by the Home Assistant community.
