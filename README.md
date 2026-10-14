# Fan Tracker

Make the smart fan you already own point at you as you move around the room,
using the presence sensor you already own, through Home Assistant.

Fans that follow you exist (Dyson Find+Follow, Dreame AirPursue PM20 and
others), but each one has its own camera or radar built in. This project
retrofits the idea onto ordinary hardware: an
[Aqara FP2](https://www.aqara.com/en/product/presence-sensor-fp2/) reports
where you are, and a fan with motorized pan (tested with a Dreo DR-HPF015S air
circulator) turns to follow.

```
Aqara FP2 --(Aqara cloud, x/y about every 0.75 s)--> Fan Tracker add-on
    --(HA number entities)--> hass-dreo --(Dreo cloud, about 0.6 s)--> fan pan/tilt
```

## What you need

- Home Assistant OS or Supervised (for add-ons).
- An Aqara FP2 that sees the area the fan covers.
- A fan whose pan angle is a Home Assistant `number` entity. For Dreo air
  circulators that is [hass-dreo](https://github.com/JeffSteinbok/hass-dreo),
  which exposes "Horizontal Angle" and "Vertical Angle". Other Dreo models with
  those entities should work but are untested.
- A computer with Python 3.11 or newer for the one-time calibration.

## Install

1. In Home Assistant, open Settings, Add-ons, Add-on Store, the menu at the
   top right, Repositories, and add `https://github.com/ksha23/fan-tracker`.
2. Install **Fan Tracker**. It builds locally on your machine.
3. Create a toggle helper named "Fan tracking" (Settings, Devices & services,
   Helpers). Its entity is `input_boolean.fan_tracking`.
4. Find your FP2's device id:
   ```
   git clone https://github.com/ksha23/fan-tracker && cd fan-tracker/tools
   python3 aqara_login.py devices
   ```
   It asks for your Aqara Home login and prints each device. Use the `did` of
   the FP2 (`lumi.motion.agl001`), which looks like `lumi1.0123456789ab`.
5. In the add-on's Configuration tab, fill in `aqara_account`,
   `aqara_password`, `aqara_region`, `fp2_did`, and your fan's `fan_entity`,
   `pan_entity` and `tilt_entity`.
6. Calibrate (next section), paste the result into the options, and start the
   add-on.
7. Turn on the "Fan tracking" switch.

## Calibrate

The tracker needs to know where the fan is in the FP2's coordinates and which
way it points. You hold the fan at a few angles and stand where the air hits
you hardest. Put your settings in `local.env` at the repo root (see
`tools/common.py`), at least `HA_URL` and `FP2_DID`. The tools ask for the HA
token and the Aqara login if they are not in the environment.

1. **Find yourself.** Run `python3 calibrate.py look` while you shuffle in
   place. The target whose position changes is you. Note its id.
2. **Give the fan's position.** The FP2 reports raw units, about 800 per 7 m.
   - Wall mounted: the sensor is at `(0, 0)` and `y` points into the room.
   - Corner mounted: the coordinates sit on a grid whose corner is the sensor,
     at about `(-400, 0)` (or `(400, 0)`). This one took a while to figure out.

   If the fan is right next to the sensor, run `python3 calibrate.py fan-at X Y`
   with the sensor's position. The FP2 cannot see you properly when you stand
   right beside it, so `fan-spot` only works when the fan is well inside its view.
3. **Record airflow points.** For three or more angles across the range you
   want (for example -60, -30 and 0):
   ```
   python3 calibrate.py set-pan -60 0
   # stand where the airflow is strongest, 1 to 2 m out, then:
   python3 calibrate.py record --id 8
   ```
4. **Fit.** `python3 calibrate.py fit` prints the fit error and the values for
   `fan_x`, `fan_y`, `fan_heading_deg` and `fan_mirror`. In the author's room,
   three points fit to 2.2 degrees RMS. Predicting each point from the other
   two missed by 0.4, 4.2 and 6.8 degrees.

Set `pan_min` and `pan_max` so the fan never blows into a wall or window.

## Turning it on and off

Everything goes through the toggle helper, so anything that can flip a Home
Assistant switch works.

- **Siri and Apple Home:** add Home Assistant's HomeKit Bridge integration and
  include only `input_boolean.fan_tracking`. "Hey Siri, turn on fan tracking"
  then works, also away from home through a home hub.
- **A URL:** a webhook automation lets scripts and phone shortcuts switch it
  with `?state=on`, `off` or `toggle`. Use a long random webhook id, since the
  id is the only secret.
  ```yaml
  alias: Fan tracking webhook
  mode: queued
  triggers:
    - trigger: webhook
      webhook_id: fan-tracking-CHANGE-ME-TO-SOMETHING-RANDOM
      allowed_methods: [POST, GET]
      local_only: true
  actions:
    - variables:
        s: "{{ (trigger.query.get('state', 'toggle') if trigger.query is defined else 'toggle') | lower }}"
    - choose:
        - conditions: "{{ s == 'on' }}"
          sequence:
            - action: input_boolean.turn_on
              target: {entity_id: input_boolean.fan_tracking}
        - conditions: "{{ s == 'off' }}"
          sequence:
            - action: input_boolean.turn_off
              target: {entity_id: input_boolean.fan_tracking}
      default:
        - action: input_boolean.toggle
          target: {entity_id: input_boolean.fan_tracking}
  ```
  Then `curl -X POST "http://homeassistant.local:8123/api/webhook/<id>?state=toggle"`.

## How it behaves

- It follows one person. If several targets are visible it keeps the one it
  is following. A target that has never moved (a radar ghost) gives way to one
  that moves.
- It moves only when the aim has changed by at least 6 degrees, at most once
  every 2 s, in the fan's 5 degree steps, with hysteresis so it does not flip
  between two steps.
- It turns the fan's oscillation off when tracking starts, and does nothing
  while the fan is off.
- `sensor.fan_tracker` shows what it is doing.

Measured on the author's setup:

| | |
|---|---|
| FP2 position updates | about every 0.75 s |
| Age of a position when read | 0.1 to 0.8 s |
| Aqara request time | about 0.2 s |
| Fan move confirmed by Dreo cloud | about 0.6 s |
| FP2 live reporting turns itself off after | about 226 s (the add-on re-enables it every 60 s) |

## Limitations

- **Cloud dependent.** Positions come through Aqara's cloud and fan commands
  through Dreo's cloud. HomeKit gives the FP2's zones locally but not its x/y,
  and the local alternatives (a hub relay or reflashing the sensor) are
  experimental.
- **Unofficial Aqara login.** The default `app` mode logs in the way the Aqara
  Home app does, using app keys documented by
  [Aqara-LANLink](https://github.com/absent42/Aqara-LANLink). Aqara can change
  or block it at any time. The official Open API (`aqara_mode: open`) is
  implemented but untested end to end, because it needs an approved developer
  project.
- **One sensor, one fan.** The FP2 cannot track you right beside itself.
- **Ghost targets.** The FP2 sometimes reports a still target where nobody is.

## Development

```
python3 -m unittest discover -s tests -t .
```

The add-on lives in `addon/` (the Python package is `addon/fan_tracker/`, with
no dependencies beyond the standard library). `tools/` has the calibration
and diagnostic scripts: `probe_fp2.py` measures the position feed, and
`fan_interference.py` checks whether the fan's motion disturbs the sensor.
`deploy.sh` copies the add-on to a Home Assistant's local add-ons folder over
SSH for testing.

## Credits and license

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for the projects this builds on.
