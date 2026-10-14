"""Service configuration: one flat JSON object (the add-on's options.json)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Config:
    # Aqara: "app" = Aqara Home account login (unofficial), "open" = developer Open API
    aqara_mode: str = "app"
    aqara_account: str = ""
    aqara_password: str = ""
    session_path: str = "/config/aqara_app_session.json"
    # Aqara Open API
    aqara_app_id: str = ""
    aqara_key_id: str = ""
    aqara_app_key: str = ""
    aqara_region: str = "US"
    fp2_did: str = ""
    tokens_path: str = "/config/aqara_tokens.json"

    # Home Assistant
    ha_url: str = "http://supervisor/core/api"
    ha_token: str = ""
    enable_entity: str = "input_boolean.fan_tracking"
    fan_entity: str = "fan.air_circulator"
    pan_entity: str = "number.air_circulator_horizontal_angle"
    tilt_entity: str = "number.air_circulator_vertical_angle"
    status_entity: str = "sensor.fan_tracker"
    oscillation_switches: str = ("switch.air_circulator_horizontal_oscillation,"
                                 "switch.air_circulator_vertical_oscillation")

    # Fan pose in the FP2 frame (from tools/calibrate.py)
    fan_x: float = 0.0
    fan_y: float = 0.0
    fan_heading_deg: float = 0.0
    fan_mirror: int = 1
    fan_height_m: float = 0.9

    # Aiming
    target_height_m: float = 1.1
    tilt_mode: str = "distance"
    fixed_tilt_deg: float = 10.0
    tilt_offset_deg: float = 0.0
    units_per_meter: float = 800.0 / 7.0
    pan_min: float = -75.0
    pan_max: float = 75.0
    tilt_min: float = -10.0
    tilt_max: float = 90.0
    angle_step_deg: float = 5.0
    pan_deadband_deg: float = 6.0
    tilt_deadband_deg: float = 5.0
    min_command_interval_s: float = 2.0
    smoothing: float = 0.5
    lost_after_s: float = 8.0
    fan_exclusion_radius: float = 40.0
    motion_noise: float = 8.0

    # Loop
    poll_interval_s: float = 1.0
    reporting_refresh_s: float = 60.0      # FP2 drops live reporting after ~226 s
    aim_when_fan_off: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = json.loads(Path(path).read_text())
        known = {f.name: f.type for f in fields(cls)}
        cfg = cls(**{k: v for k, v in raw.items() if k in known})
        if not cfg.ha_token:
            cfg.ha_token = os.environ.get("SUPERVISOR_TOKEN", "")
        return cfg
