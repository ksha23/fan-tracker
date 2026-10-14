"""The tracking loop: FP2 targets in, Dreo pan/tilt out, status to HA."""

from __future__ import annotations

import logging
import math
import time

from .aqara import AqaraClient, AqaraError, FileTokenStore
from .aqara_app import AqaraAppClient, AqaraAppError
from .config import Config
from .controller import Tracker, TrackerSettings
from .fp2 import REPORTING_SWITCH_RESOURCE, TARGETS_RESOURCE, parse_targets
from .geometry import FanPose
from .hass import HomeAssistant

log = logging.getLogger("fan_tracker")


def build_tracker(cfg: Config) -> Tracker:
    pose = FanPose(cfg.fan_x, cfg.fan_y, cfg.fan_heading_deg, cfg.fan_mirror, cfg.fan_height_m)
    s = TrackerSettings(
        target_height_m=cfg.target_height_m, tilt_mode=cfg.tilt_mode,
        fixed_tilt_deg=cfg.fixed_tilt_deg, tilt_offset_deg=cfg.tilt_offset_deg,
        units_per_meter=cfg.units_per_meter,
        pan_limits=(cfg.pan_min, cfg.pan_max), tilt_limits=(cfg.tilt_min, cfg.tilt_max),
        angle_step_deg=cfg.angle_step_deg,
        pan_deadband_deg=cfg.pan_deadband_deg, tilt_deadband_deg=cfg.tilt_deadband_deg,
        min_command_interval_s=cfg.min_command_interval_s, smoothing=cfg.smoothing,
        lost_after_s=cfg.lost_after_s, fan_exclusion_radius=cfg.fan_exclusion_radius,
        motion_noise=cfg.motion_noise)
    return Tracker(pose, s)


def make_aqara(cfg: Config):
    if cfg.aqara_mode == "open":
        return AqaraClient(cfg.aqara_app_id, cfg.aqara_key_id, cfg.aqara_app_key,
                           cfg.aqara_region, FileTokenStore(cfg.tokens_path))
    return AqaraAppClient(cfg.aqara_account, cfg.aqara_password, cfg.aqara_region,
                          FileTokenStore(cfg.session_path))


class Service:
    def __init__(self, cfg: Config, aqara: AqaraClient | None = None,
                 ha: HomeAssistant | None = None):
        self.cfg = cfg
        self.aqara = aqara or make_aqara(cfg)
        self.ha = ha or HomeAssistant(cfg.ha_url, cfg.ha_token)
        self.tracker = build_tracker(cfg)
        self.enabled = False
        self.fan_on = False
        self.last_flags_check = 0.0
        self.last_reporting_write = -math.inf
        self.last_ts = None
        self.status = None
        self.last_status_push = 0.0

    # -- HA side

    def _refresh_flags(self, now: float) -> None:
        if now - self.last_flags_check < 3.0:
            return
        self.last_flags_check = now
        st = self.ha.state(self.cfg.enable_entity)
        enabled = bool(st and st["state"] == "on")
        fan = self.ha.state(self.cfg.fan_entity) if self.cfg.fan_entity else None
        fan_on = bool(fan and fan["state"] == "on")
        if enabled and not self.enabled:
            log.info("tracking enabled")
            self.last_reporting_write = -math.inf
            self.tracker.forget_command()
            self._stop_oscillation()
        if not enabled and self.enabled:
            log.info("tracking disabled")
            self._set_reporting(False)
        if fan_on and not self.fan_on:
            self.tracker.forget_command()
        self.enabled, self.fan_on = enabled, fan_on

    def _stop_oscillation(self) -> None:
        """Aiming fights oscillation, so switch every oscillation axis off."""
        for sw in filter(None, (s.strip() for s in self.cfg.oscillation_switches.split(","))):
            try:
                self.ha.service("switch", "turn_off", entity_id=sw)
            except Exception as e:
                log.warning("could not turn off %s: %s", sw, e)

    def _push_status(self, now: float, state: str, **attrs) -> None:
        if state == self.status and now - self.last_status_push < 30.0 and not attrs.get("force"):
            return
        attrs.pop("force", None)
        self.status, self.last_status_push = state, now
        try:
            self.ha.publish(self.cfg.status_entity, state,
                            {"friendly_name": "Fan tracker", "icon": "mdi:fan", **attrs})
        except Exception as e:  # status is best effort
            log.debug("status publish failed: %s", e)

    # -- FP2 side

    def _set_reporting(self, on: bool) -> None:
        try:
            self.aqara.write(self.cfg.fp2_did, {REPORTING_SWITCH_RESOURCE: 1 if on else 0})
            log.info("FP2 live position reporting %s", "on" if on else "off")
        except (AqaraError, AqaraAppError) as e:
            log.warning("could not switch FP2 reporting %s: %s", on, e)

    def _read_targets(self):
        items = self.aqara.query(self.cfg.fp2_did, [TARGETS_RESOURCE])
        for it in items:
            if it.get("resourceId") == TARGETS_RESOURCE:
                # Without a timestamp, a changed value is the only sign of a new reading.
                return it.get("timeStamp") or it.get("value"), parse_targets(it.get("value"))
        return None, []

    # -- loop

    def step(self, now: float) -> None:
        self._refresh_flags(now)
        if not self.enabled:
            self._push_status(now, "disabled")
            return
        if not (self.fan_on or self.cfg.aim_when_fan_off):
            self._push_status(now, "fan off")
            return
        if now - self.last_reporting_write > self.cfg.reporting_refresh_s:
            self._set_reporting(True)
            self.last_reporting_write = now

        ts, targets = self._read_targets()
        if ts is None or ts == self.last_ts:
            return
        self.last_ts = ts
        cmd = self.tracker.update(now, targets)
        if cmd:
            log.info("aim pan=%d tilt=%d (target %s at %.0f,%.0f, %.1f m)",
                     cmd.pan, cmd.tilt, cmd.target.id, cmd.target.x, cmd.target.y,
                     cmd.aim.distance_m)
            self.ha.set_number(self.cfg.pan_entity, cmd.pan)
            if self.cfg.tilt_entity:
                self.ha.set_number(self.cfg.tilt_entity, cmd.tilt)
        last = self.tracker.last_command
        if self.tracker.smoothed is None:
            self._push_status(now, "no one", targets=len(targets))
        else:
            sx, sy = self.tracker.smoothed
            self._push_status(now, "tracking", force=cmd is not None, targets=len(targets),
                              x=round(sx), y=round(sy),
                              pan=last.pan if last else None, tilt=last.tilt if last else None)

    def run(self) -> None:
        backoff = 0.0
        while True:
            t0 = time.monotonic()
            try:
                self.step(t0)
                backoff = 0.0
            except Exception as e:
                backoff = min(60.0, max(2.0, backoff * 2))
                log.warning("loop error (retry in %.0fs): %s", backoff, e)
                self._push_status(t0, "error", error=str(e)[:200])
                time.sleep(backoff)
                continue
            time.sleep(max(0.0, self.cfg.poll_interval_s - (time.monotonic() - t0)))
