"""Aqara account helpers.

  aqara_login.py devices                 list devices (find your FP2's did here)
  aqara_login.py request EMAIL           Open API only: Aqara sends a code to EMAIL
  aqara_login.py exchange EMAIL CODE     Open API only: store the access tokens

With the app login (no developer keys) `devices` logs in directly.
"""

import argparse
import json

from common import aqara
from fan_tracker.aqara import AqaraClient


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("request"); r.add_argument("email")
    e = sub.add_parser("exchange"); e.add_argument("email"); e.add_argument("code")
    sub.add_parser("devices")
    a = p.parse_args()
    c = aqara()
    if a.cmd in ("request", "exchange") and not isinstance(c, AqaraClient):
        p.error("request/exchange are for the official Open API (set AQARA_APP_ID, AQARA_KEY_ID, AQARA_APP_KEY)")
    if a.cmd == "request":
        c.request_auth_code(a.email)
        print(f"Code requested. Check {a.email}.")
    elif a.cmd == "exchange":
        c.exchange_auth_code(a.email, a.code)
        print("Tokens stored.")
    else:
        for d in c.devices():
            print(json.dumps({k: d.get(k) for k in ("did", "model", "deviceName", "state")}))


if __name__ == "__main__":
    main()
