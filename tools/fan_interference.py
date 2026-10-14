"""Does the fan confuse the FP2? Fan off, fan on and still, then panning.

The person should stand still for the whole run. Prints, per phase, every
target the FP2 reported with its median position and spread, then restores
the fan's on/off state, speed and angles.
"""

import argparse
import statistics
import time

from common import aqara, fp2_did, hass
from fan_tracker.fp2 import REPORTING_SWITCH_RESOURCE, TARGETS_RESOURCE, parse_targets

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lead-in", type=float, default=15)
    p.add_argument("--phase", type=float, default=12)
    p.add_argument("--fan", default="fan.air_circulator")
    p.add_argument("--pan-entity", default="number.air_circulator_horizontal_angle")
    p.add_argument("--tilt-entity", default="number.air_circulator_vertical_angle")
    a = p.parse_args()
    FAN, PAN, TILT = a.fan, a.pan_entity, a.tilt_entity
    c, ha = aqara(), hass()
    fan0 = ha.state(FAN)
    pan0, tilt0 = ha.state(PAN)["state"], ha.state(TILT)["state"]
    print(f"fan was {fan0['state']} at {fan0['attributes'].get('percentage')}%, pan {pan0}, tilt {tilt0}")
    c.write(fp2_did(), {REPORTING_SWITCH_RESOURCE: 1})
    ha.set_number(PAN, 0)

    sweep = [-60, -30, 0, 30, 60, 30, 0, -30, -60, 0]
    phases = [("lead-in (get still)", a.lead_in, lambda: None),
              ("fan off", a.phase, lambda: ha.service("fan", "turn_off", entity_id=FAN)),
              ("fan on, still", a.phase, lambda: ha.service("fan", "turn_on", entity_id=FAN)),
              ("fan panning", 3.0 * len(sweep), None)]
    log: dict[str, dict[str, list]] = {}
    last = None
    try:
        for name, dur, action in phases:
            print(f"-- {name} ({dur:.0f}s)")
            if action:
                action()
            per = log.setdefault(name, {})
            t0 = time.monotonic()
            step = -1
            while time.monotonic() - t0 < dur:
                if action is None:
                    k = int((time.monotonic() - t0) // 3.0)
                    if k != step and k < len(sweep):
                        step = k
                        ha.set_number(PAN, sweep[k])
                it = next((i for i in c.query(fp2_did(), [TARGETS_RESOURCE])
                           if i.get("resourceId") == TARGETS_RESOURCE), {})
                key = it.get("timeStamp") or it.get("value")
                if key != last:
                    last = key
                    ts = parse_targets(it.get("value"))
                    per.setdefault("_counts", []).append(len(ts))
                    for t in ts:
                        per.setdefault(t.id, []).append((t.x, t.y))
                time.sleep(0.7)
    finally:
        if fan0["state"] == "on":
            ha.service("fan", "turn_on", entity_id=FAN)
            pct = fan0["attributes"].get("percentage")
            if pct:
                ha.service("fan", "set_percentage", entity_id=FAN, percentage=pct)
        else:
            ha.service("fan", "turn_off", entity_id=FAN)
        ha.set_number(PAN, float(pan0))
        ha.set_number(TILT, float(tilt0))
        print("fan restored")

    print("\nphase                 readings  targets seen (id: median x,y  spread  share of readings)")
    for name, per in log.items():
        counts = per.pop("_counts", [])
        n = len(counts)
        desc = []
        for tid, pts in sorted(per.items(), key=lambda kv: -len(kv[1])):
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            spread = max(statistics.pstdev(xs), statistics.pstdev(ys)) if len(pts) > 1 else 0
            desc.append(f"{tid}: ({statistics.median(xs):.0f},{statistics.median(ys):.0f}) "
                        f"±{spread:.0f} {len(pts)}/{n}")
        print(f"{name:22s} {n:3d}      " + " | ".join(desc))


if __name__ == "__main__":
    main()
