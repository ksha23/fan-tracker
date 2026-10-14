"""Turns a stream of FP2 targets into occasional pan/tilt commands.

Keeps following the same target id while it is visible, smooths its position,
and only commands the fan when the aim has moved past a deadband and the
previous move has had time to finish.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .fp2 import Target
from .geometry import Aim, FanPose, aim_at, clamp


@dataclass
class TrackerSettings:
    target_height_m: float = 1.1
    tilt_mode: str = "distance"          # "distance" or "fixed"
    fixed_tilt_deg: float = 10.0
    tilt_offset_deg: float = 0.0
    units_per_meter: float = 800.0 / 7.0
    pan_limits: tuple[float, float] = (-75.0, 75.0)
    tilt_limits: tuple[float, float] = (-10.0, 90.0)
    angle_step_deg: float = 5.0          # the fan only takes multiples of this
    pan_deadband_deg: float = 6.0
    tilt_deadband_deg: float = 5.0
    min_command_interval_s: float = 2.0
    smoothing: float = 0.5               # weight of the newest sample
    lost_after_s: float = 8.0
    # A running fan shows up on the radar as a still target at its own spot.
    fan_exclusion_radius: float = 40.0   # raw FP2 units around the fan pose
    motion_noise: float = 8.0            # raw units of movement that count as moving


@dataclass
class Command:
    pan: int
    tilt: int
    target: Target
    aim: Aim


@dataclass
class Tracker:
    pose: FanPose
    settings: TrackerSettings = field(default_factory=TrackerSettings)
    target_id: str | None = None
    smoothed: tuple[float, float] | None = None
    last_seen: float = -math.inf
    last_command: Command | None = None
    last_command_time: float = -math.inf
    # Per target id: [anchor x, anchor y, last time it moved past motion_noise]
    motion: dict[str, list[float]] = field(default_factory=dict)

    def _note_motion(self, now: float, targets: list[Target]) -> None:
        seen = set()
        for t in targets:
            seen.add(t.id)
            m = self.motion.get(t.id)
            if m is None:
                self.motion[t.id] = [t.x, t.y, -math.inf]
            elif math.hypot(t.x - m[0], t.y - m[1]) > self.settings.motion_noise:
                self.motion[t.id] = [t.x, t.y, now]
        for tid in list(self.motion):
            if tid not in seen:
                del self.motion[tid]

    def _pick(self, targets: list[Target]) -> Target | None:
        r = self.settings.fan_exclusion_radius
        live = [t for t in targets if math.hypot(t.x - self.pose.x, t.y - self.pose.y) > r]
        if not live:
            return None
        moved = lambda t: self.motion.get(t.id, [0, 0, -math.inf])[2]
        current = next((t for t in live if t.id == self.target_id), None)
        # Keep the current target unless it has never moved and another one has
        # (a still radar ghost should not hold the fan).
        if current and (moved(current) > -math.inf or all(moved(t) == -math.inf for t in live)):
            return current
        movers = [t for t in live if moved(t) > -math.inf]
        if movers:
            return max(movers, key=moved)
        ref = self.smoothed or (self.pose.x, self.pose.y)
        return min(live, key=lambda t: math.hypot(t.x - ref[0], t.y - ref[1]))

    def desired(self) -> tuple[float, float, Aim] | None:
        """Exact (unrounded, clamped) pan and tilt toward the smoothed target."""
        if self.smoothed is None:
            return None
        s = self.settings
        aim = aim_at(self.pose, *self.smoothed, target_height_m=s.target_height_m,
                     units_per_meter=s.units_per_meter, tilt_offset_deg=s.tilt_offset_deg)
        tilt = aim.tilt if s.tilt_mode == "distance" else s.fixed_tilt_deg
        return clamp(aim.pan, *s.pan_limits), clamp(tilt, *s.tilt_limits), aim

    def _to_step(self, v: float, lo: float, hi: float) -> int:
        step = self.settings.angle_step_deg
        return int(clamp(step * round(v / step), lo, hi))

    def update(self, now: float, targets: list[Target]) -> Command | None:
        """Feed one FP2 reading. Returns a command when the fan should move."""
        s = self.settings
        self._note_motion(now, targets)
        t = self._pick(targets)
        if t is None:
            if now - self.last_seen > s.lost_after_s:
                self.target_id, self.smoothed = None, None
            return None

        if t.id != self.target_id or self.smoothed is None:
            self.target_id, self.smoothed = t.id, (t.x, t.y)
        else:
            a = s.smoothing
            self.smoothed = (a * t.x + (1 - a) * self.smoothed[0],
                             a * t.y + (1 - a) * self.smoothed[1])
        self.last_seen = now

        pan, tilt, aim = self.desired()
        last = self.last_command
        if last is not None:
            # Compare the exact aim with what the fan was last sent. This gives
            # hysteresis, so standing on a step boundary does not flip the fan.
            moved = (abs(pan - last.pan) >= s.pan_deadband_deg
                     or abs(tilt - last.tilt) >= s.tilt_deadband_deg)
            if not moved or now - self.last_command_time < s.min_command_interval_s:
                return None
        cmd = Command(self._to_step(pan, *s.pan_limits), self._to_step(tilt, *s.tilt_limits), t, aim)
        self.last_command, self.last_command_time = cmd, now
        return cmd

    def forget_command(self) -> None:
        """Make the next update re-send (e.g. after the fan was switched on)."""
        self.last_command, self.last_command_time = None, -math.inf

    def release_target(self) -> None:
        """Drop the followed target and the motion history, so the next mover is
        picked fresh (e.g. after tracking is switched off and on again). A target
        that moved even once is otherwise kept for good, and a radar reflection
        that twitched can hold the fan."""
        self.target_id, self.smoothed = None, None
        self.motion.clear()
        self.forget_command()
