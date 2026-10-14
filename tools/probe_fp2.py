"""Measure how the FP2's live positions arrive through the Open API.

Switches live reporting on, polls 4.22.700 once per --interval seconds, and
prints each new reading plus a summary of update gaps and API errors.
"""

import argparse
import statistics
import time

from common import aqara, fp2_did
from fan_tracker.aqara import AqaraError
from fan_tracker.aqara_app import AqaraAppError
from fan_tracker.fp2 import PRESENCE_RESOURCE, REPORTING_SWITCH_RESOURCE, TARGETS_RESOURCE, parse_targets


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--no-enable", action="store_true", help="do not write 4.22.85=1 first")
    a = p.parse_args()
    c = aqara()

    before = c.query(fp2_did(), [REPORTING_SWITCH_RESOURCE, PRESENCE_RESOURCE, TARGETS_RESOURCE])
    for it in before:
        print("before:", it.get("resourceId"), repr(it.get("value"))[:200],
              {k: v for k, v in it.items() if k not in ("resourceId", "value")})
    if not a.no_enable:
        c.write(fp2_did(), {REPORTING_SWITCH_RESOURCE: 1})
        print("wrote 4.22.85=1")

    last_ts, arrivals, errors, calls = None, [], 0, 0
    t_end = time.monotonic() + a.seconds
    while time.monotonic() < t_end:
        t0 = time.monotonic()
        calls += 1
        try:
            items = c.query(fp2_did(), [TARGETS_RESOURCE])
        except (AqaraError, AqaraAppError) as e:
            errors += 1
            print(f"{t0:10.1f} error: {e}")
            time.sleep(a.interval)
            continue
        latency = time.monotonic() - t0
        it = next((i for i in items if i.get("resourceId") == TARGETS_RESOURCE), {})
        ts = it.get("timeStamp") or it.get("value")
        if ts != last_ts:
            age = time.time() * 1000 - int(it["timeStamp"]) if it.get("timeStamp") else None
            targets = parse_targets(it.get("value"))
            print(f"new ts={ts} age={age and round(age)}ms api={latency * 1000:.0f}ms "
                  f"targets={[(t.id, t.x, t.y) for t in targets]}")
            if last_ts is not None:
                arrivals.append(time.monotonic())
            last_ts = ts
        time.sleep(max(0.0, a.interval - (time.monotonic() - t0)))

    gaps = [b - a_ for a_, b in zip(arrivals, arrivals[1:])]
    print(f"\ncalls={calls} errors={errors} new readings={len(arrivals)}")
    if gaps:
        print(f"gap between readings: median {statistics.median(gaps):.1f}s, max {max(gaps):.1f}s")


if __name__ == "__main__":
    main()
