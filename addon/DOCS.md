# Fan Tracker

Points a motorized smart fan at the person an Aqara FP2 presence sensor is
tracking. It reads the FP2's live x/y through the Aqara cloud about once a
second and sets the fan's pan (and optionally tilt) through Home Assistant.

The full setup and calibration guide is in the
[repository README](https://github.com/ksha23/fan-tracker).

## Before you start

1. Your fan's pan angle must be a Home Assistant `number` entity. For Dreo air
   circulators, install [hass-dreo](https://github.com/JeffSteinbok/hass-dreo)
   and look for `number.<fan>_horizontal_angle` and `_vertical_angle`.
2. Create a toggle helper for turning tracking on and off. The default entity
   is `input_boolean.fan_tracking` (Settings, Devices & services, Helpers,
   Create helper, Toggle, named "Fan tracking").
3. Find your FP2's Aqara device id (`lumi1.` followed by 12 hex digits). The
   repository's `tools/aqara_login.py devices` lists it.
4. Calibrate (see the README) to get `fan_x`, `fan_y`, `fan_heading_deg` and
   `fan_mirror`.

## Options

| Option | Meaning |
|---|---|
| `aqara_mode` | `app` logs in like the Aqara Home app (unofficial, tested). `open` uses the official Aqara Open API (needs an approved developer project, untested end to end). |
| `aqara_account`, `aqara_password` | Aqara Home login for `app` mode. |
| `aqara_app_id`, `aqara_key_id`, `aqara_app_key` | Developer keys for `open` mode. Tokens go in `aqara_tokens.json` in this add-on's config folder. |
| `aqara_region` | Server region of your Aqara account. |
| `fp2_did` | The FP2's device id. |
| `enable_entity` | Toggle that turns tracking on and off. |
| `fan_entity` | The fan. Nothing moves while it is off. |
| `pan_entity`, `tilt_entity` | `number` entities for pan and tilt. Leave `tilt_entity` empty to never touch tilt. |
| `fan_x`, `fan_y`, `fan_heading_deg`, `fan_mirror` | Fan pose in the FP2's frame, from calibration. |
| `pan_min`, `pan_max` | Pan limits in degrees. Use them to keep the fan from blowing at a wall. |
| `tilt_mode` | `fixed` holds `fixed_tilt_deg`. `distance` aims at `target_height_m` from `fan_height_m`. |
| `pan_deadband_deg`, `tilt_deadband_deg` | Smallest change worth moving the fan for. |
| `min_command_interval_s` | Minimum time between moves. |
| `smoothing` | Weight of each new position (1 = no smoothing). |
| `fan_exclusion_radius` | Ignore targets this close to the fan (raw FP2 units). |
| `poll_interval_s` | How often to read positions. |
| `reporting_refresh_s` | How often to re-enable the FP2's live reporting, which turns itself off after a few minutes. |

The add-on publishes its state to `sensor.fan_tracker`: `disabled`, `fan off`,
`no one`, `tracking` (with the target position and last pan/tilt) or `error`.
