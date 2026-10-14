"""Calibrate the fan's pose in the FP2 frame, one step at a time.

  calibrate.py look                  list the targets the FP2 sees right now
  calibrate.py fan-at X Y            set the fan's position directly (see below)
  calibrate.py fan-spot [--id N]     or: record while standing right next to the fan
  calibrate.py set-pan PAN [TILT]    hold the fan at a fixed angle
  calibrate.py record [--id N]       record while standing in the strongest airflow
  calibrate.py fit                   fit and print the add-on options
  calibrate.py show | reset

Where the fan is matters most. The FP2 reports positions in raw units (about
800 per 7 m). Wall mounted, the sensor is at (0, 0) and y points into the room.
Corner mounted (left or right corner in the Aqara app), the grid's corner is
the sensor, at about (-400, 0) or (400, 0). The FP2 cannot see right beside
itself, so if the fan sits next to the sensor, use `fan-at` with the sensor's
position instead of `fan-spot`.

Use `look` to find which target id is you (shuffle in place and see which one
moves), then record 3 or more airflow points across the fan's range, 1 to 2 m
out. Samples are kept in cal.json next to this script (positions only).
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from common import aqara, fp2_did, hass
from fan_tracker.fp2 import REPORTING_SWITCH_RESOURCE, TARGETS_RESOURCE, parse_targets
from fan_tracker.geometry import CalSample, aim_at, fit_pose

STATE = Path(__file__).with_name("cal.json")


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"fan": None, "points": [], "entities": {}}


def save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1))


def positions(seconds: float) -> dict[str, tuple[float, float, float, int]]:
    """Per target id over `seconds`: (median x, median y, spread, readings)."""
    c = aqara()
    c.write(fp2_did(), {REPORTING_SWITCH_RESOURCE: 1})
    seen: dict[str, list[tuple[float, float]]] = {}
    last = None
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        it = next((i for i in c.query(fp2_did(), [TARGETS_RESOURCE])
                   if i.get("resourceId") == TARGETS_RESOURCE), {})
        key = it.get("timeStamp") or it.get("value")
        if key != last:
            last = key
            for t in parse_targets(it.get("value")):
                seen.setdefault(t.id, []).append((t.x, t.y))
        time.sleep(1.0)
    out = {}
    for tid, pts in seen.items():
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        spread = max(statistics.pstdev(xs), statistics.pstdev(ys)) if len(pts) > 1 else 0.0
        out[tid] = (statistics.median(xs), statistics.median(ys), spread, len(pts))
        print(f"  target {tid}: ({out[tid][0]:.0f}, {out[tid][1]:.0f}) "
              f"spread {spread:.0f}, {len(pts)} readings")
    return out


def choose(found: dict, tid: str | None) -> tuple[float, float]:
    if tid is None and len(found) == 1:
        tid = next(iter(found))
    if tid not in found:
        sys.exit(f"pick a target with --id (seen: {', '.join(found) or 'none'})")
    return found[tid][0], found[tid][1]


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fan-spot"); f.add_argument("--seconds", type=float, default=10); f.add_argument("--id")
    fa = sub.add_parser("fan-at"); fa.add_argument("x", type=float); fa.add_argument("y", type=float)
    sub.add_parser("look").add_argument("--seconds", type=float, default=8)
    sp = sub.add_parser("set-pan"); sp.add_argument("pan", type=int); sp.add_argument("tilt", type=int, nargs="?")
    sp.add_argument("--pan-entity"); sp.add_argument("--tilt-entity")
    r = sub.add_parser("record"); r.add_argument("--seconds", type=float, default=10); r.add_argument("--id")
    ft = sub.add_parser("fit"); ft.add_argument("--fan-height", type=float, default=0.9)
    sub.add_parser("show"); sub.add_parser("reset")
    a = p.parse_args()
    s = load()

    if a.cmd == "reset":
        STATE.unlink(missing_ok=True); print("cleared")
    elif a.cmd == "show":
        print(json.dumps(s, indent=1))
    elif a.cmd == "look":
        positions(a.seconds)
    elif a.cmd == "fan-at":
        s["fan"] = [a.x, a.y]; save(s); print(f"fan at ({a.x:.0f}, {a.y:.0f})")
    elif a.cmd == "fan-spot":
        x, y = choose(positions(a.seconds), a.id)
        s["fan"] = [x, y]; save(s); print(f"fan spot = ({x:.0f}, {y:.0f})")
    elif a.cmd == "set-pan":
        ents = s["entities"]
        ents["pan"] = a.pan_entity or ents.get("pan") or "number.air_circulator_horizontal_angle"
        ents["tilt"] = a.tilt_entity or ents.get("tilt") or "number.air_circulator_vertical_angle"
        if not ents["pan"]:
            sys.exit("pass --pan-entity once")
        ha = hass()
        ha.set_number(ents["pan"], a.pan)
        if a.tilt is not None and ents["tilt"]:
            ha.set_number(ents["tilt"], a.tilt)
        s["current_pan"] = a.pan; save(s); print(f"fan held at pan {a.pan}")
    elif a.cmd == "record":
        if "current_pan" not in s:
            sys.exit("run set-pan first")
        x, y = choose(positions(a.seconds), a.id)
        s["points"].append({"pan": s["current_pan"], "x": x, "y": y}); save(s)
        print(f"pan {s['current_pan']}: person at ({x:.0f}, {y:.0f})")
    elif a.cmd == "fit":
        samples = [CalSample(pt["pan"], pt["x"], pt["y"]) for pt in s["points"]]
        r = fit_pose(samples, fan_xy=tuple(s["fan"]) if s["fan"] else None, height_m=a.fan_height)
        pose = r.pose
        print(f"fan at ({pose.x:.0f}, {pose.y:.0f}), heading {pose.heading_deg:.1f} deg, "
              f"mirror {pose.mirror:+d}, rms {r.rms_deg:.1f} deg")
        for pt, res in zip(s["points"], r.residuals_deg):
            print(f"  pan {pt['pan']:4d}: residual {res:+5.1f} deg")
        if s["fan"]:
            print(f"  fitted fan is {((pose.x - s['fan'][0]) ** 2 + (pose.y - s['fan'][1]) ** 2) ** .5:.0f}"
                  " units from the given fan position")
        opts = {"fan_x": round(pose.x, 1), "fan_y": round(pose.y, 1),
                "fan_heading_deg": round(pose.heading_deg, 1), "fan_mirror": pose.mirror,
                "fan_height_m": a.fan_height}
        s["fit"] = opts; save(s)
        print(json.dumps(opts))


if __name__ == "__main__":
    main()
