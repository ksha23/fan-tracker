"""FP2 resources and parsing of the live target list.

Resource 4.22.700 holds a JSON list of targets, each with id, x, y, rangeId
and state ("1" = active). Resource 4.22.85 switches live position reporting
on (1) or off (0). Both names come from Aqara's own resource catalogue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

TARGETS_RESOURCE = "4.22.700"
REPORTING_SWITCH_RESOURCE = "4.22.85"
PRESENCE_RESOURCE = "3.51.85"


@dataclass(frozen=True)
class Target:
    id: str
    x: float
    y: float


def parse_targets(value) -> list[Target]:
    """Active targets from a 4.22.700 value (JSON string or decoded list)."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        value = value.get("targets") or value.get("data") or [value]
    if not isinstance(value, list):
        return []
    out = []
    for t in value:
        if not isinstance(t, dict) or str(t.get("state", "1")) != "1":
            continue
        try:
            x, y = float(t["x"]), float(t["y"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(Target(id=str(t.get("id", "")), x=x, y=y))
    return out
