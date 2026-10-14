"""macOS only: ask for credentials in dialogs and store them in the Keychain.

  keychain_prompt.py ha-token    HA long-lived token          -> item `ha-token`
  keychain_prompt.py aqara-app   Aqara Home email + password  -> item `aqara-app`
  keychain_prompt.py aqara-dev   Aqara developer keys         -> item `aqara-dev`

Items are stored under KEYCHAIN_ACCOUNT (see common.py). Values go straight
from the dialog to `security`, and nothing is printed or saved to disk.
"""

import subprocess
import sys

from common import KEYCHAIN_ACCOUNT

FIELDS = {
    "ha-token": [("Home Assistant long-lived access token", True)],
    "aqara-app": [("Aqara Home app email", False), ("Aqara Home app password", True)],
    "aqara-dev": [("Aqara developer App ID", False), ("Aqara developer Key ID", False),
                  ("Aqara developer App Key", True)],
}


def ask(prompt: str, hidden: bool) -> str:
    # Keep the dialog record in a variable: `result` is reset by the `if`.
    script = (f'set r to display dialog "Fan tracker: {prompt}" default answer "" '
              f'{"with hidden answer " if hidden else ""}'
              'buttons {"Cancel", "OK"} default button "OK" giving up after 900\n'
              'if gave up of r then error number -128\n'
              'text returned of r')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        why = "cancelled or timed out" if "-128" in r.stderr else r.stderr.strip()
        sys.exit(f"{why} at: {prompt}")
    return r.stdout.rstrip("\n")


def main() -> None:
    service = sys.argv[1]
    values = [ask(p, h).strip() for p, h in FIELDS[service]]
    if not all(values):
        sys.exit("a field was empty, nothing stored")
    subprocess.run(["security", "add-generic-password", "-U", "-a", KEYCHAIN_ACCOUNT, "-s", service,
                    "-w", ":::".join(values)], check=True)
    print(f"stored Keychain item '{service}' with {len(values)} fields")


if __name__ == "__main__":
    main()
