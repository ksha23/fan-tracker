"""Room geometry: where the fan sits in the FP2's frame, and how to aim it.

FP2 frame (raw radar units, about 800 units per 7 m): x runs along the sensor
face, y points away from the sensor. The cloud reports positions in this frame.

A fan pose is the fan's position in that frame, the bearing of its pan=0
direction, and whether positive pan turns toward +x (mirror=+1) or -x (-1).
Bearings are measured from +y toward +x, in degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_UNITS_PER_METER = 800.0 / 7.0


def wrap_deg(a: float) -> float:
    """Wrap an angle to [-180, 180)."""
    return (a + 180.0) % 360.0 - 180.0


def bearing_deg(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, dy))


@dataclass(frozen=True)
class FanPose:
    x: float
    y: float
    heading_deg: float
    mirror: int = 1
    height_m: float = 0.9


@dataclass(frozen=True)
class Aim:
    pan: float
    tilt: float
    distance_m: float


def aim_at(pose: FanPose, tx: float, ty: float, *, target_height_m: float,
           units_per_meter: float = DEFAULT_UNITS_PER_METER,
           tilt_offset_deg: float = 0.0) -> Aim:
    """Pan/tilt (degrees, unclamped) that point the fan at a target position."""
    dx, dy = tx - pose.x, ty - pose.y
    pan = pose.mirror * wrap_deg(bearing_deg(dx, dy) - pose.heading_deg)
    dist = math.hypot(dx, dy) / units_per_meter
    tilt = math.degrees(math.atan2(target_height_m - pose.height_m, max(dist, 0.3)))
    return Aim(pan=pan, tilt=tilt + tilt_offset_deg, distance_m=dist)


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


# ---------------------------------------------------------------- calibration

@dataclass(frozen=True)
class CalSample:
    """Person standing in the airflow while the fan was held at `pan` degrees."""
    pan: float
    x: float
    y: float


@dataclass(frozen=True)
class CalResult:
    pose: FanPose
    rms_deg: float
    residuals_deg: tuple[float, ...]


def _circular_mean_deg(angles: list[float]) -> float:
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(s, c))


def _residuals(fx: float, fy: float, mirror: int, samples: list[CalSample]):
    """Best heading for a fan position, and the per-sample angle residuals."""
    offsets = [bearing_deg(s.x - fx, s.y - fy) - mirror * s.pan for s in samples]
    heading = _circular_mean_deg(offsets)
    return heading, [wrap_deg(o - heading) for o in offsets]


def _nelder_mead(f, x0: list[float], step: float, iters: int = 400) -> list[float]:
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (step if j == i else 0.0) for j in range(n)] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        centroid = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        refl = [centroid[j] + (centroid[j] - pts[-1][j]) for j in range(n)]
        fr = f(refl)
        if fr < vals[0]:
            exp = [centroid[j] + 2.0 * (centroid[j] - pts[-1][j]) for j in range(n)]
            fe = f(exp)
            pts[-1], vals[-1] = (exp, fe) if fe < fr else (refl, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = refl, fr
        else:
            con = [centroid[j] + 0.5 * (pts[-1][j] - centroid[j]) for j in range(n)]
            fc = f(con)
            if fc < vals[-1]:
                pts[-1], vals[-1] = con, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][j] + 0.5 * (pts[i][j] - pts[0][j]) for j in range(n)]
                    vals[i] = f(pts[i])
    return pts[min(range(n + 1), key=lambda i: vals[i])]


def fit_pose(samples: list[CalSample], *, fan_xy: tuple[float, float] | None = None,
             prior_sigma: float = 40.0, height_m: float = 0.9) -> CalResult:
    """Fit fan position, heading and mirror from airflow samples.

    `fan_xy` is a measured fan position (e.g. the FP2 reading while standing
    at the fan), used as a soft prior with `prior_sigma` raw units of slack.
    Without a prior, at least 3 samples at different positions are needed.
    """
    if fan_xy is None and len(samples) < 3:
        raise ValueError("need a fan position prior or at least 3 samples")
    if fan_xy is not None and len(samples) < 2:
        raise ValueError("need at least 2 samples to fix heading and direction")

    best: CalResult | None = None
    starts = [fan_xy] if fan_xy else []
    cx = sum(s.x for s in samples) / len(samples)
    cy = sum(s.y for s in samples) / len(samples)
    starts += [(cx + dx, cy + dy) for dx in (-300, 0, 300) for dy in (-300, 0, 300)]

    for mirror in (1, -1):
        def cost(p, mirror=mirror):
            _, res = _residuals(p[0], p[1], mirror, samples)
            c = sum(r * r for r in res)
            if fan_xy is not None:
                # One prior_sigma of position error costs as much as 10 degrees.
                c += 100.0 * ((p[0] - fan_xy[0]) ** 2 + (p[1] - fan_xy[1]) ** 2) / prior_sigma ** 2
            return c

        for start in starts:
            fx, fy = _nelder_mead(cost, list(start), step=50.0)
            heading, res = _residuals(fx, fy, mirror, samples)
            rms = math.sqrt(sum(r * r for r in res) / len(res))
            if best is None or cost([fx, fy]) < _cost_of(best, samples, fan_xy, prior_sigma):
                best = CalResult(FanPose(fx, fy, heading, mirror, height_m), rms, tuple(res))
    return best


def _cost_of(r: CalResult, samples, fan_xy, prior_sigma) -> float:
    c = sum(x * x for x in r.residuals_deg)
    if fan_xy is not None:
        c += 100.0 * ((r.pose.x - fan_xy[0]) ** 2 + (r.pose.y - fan_xy[1]) ** 2) / prior_sigma ** 2
    return c
