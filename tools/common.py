"""Workstation helpers shared by the tools.

Settings come from the environment, then from `local.env` at the repo root
(git-ignored, KEY=value lines):

  HA_URL            e.g. http://homeassistant.local:8123/api
  FP2_DID           the FP2's Aqara device id, e.g. lumi1.xxxxxxxxxxxx
  AQARA_REGION      US, EU, CN, KR, RU or AU (default US)
  KEYCHAIN_ACCOUNT  macOS Keychain account for the items below (default fan-tracker)

Secrets come from the environment, then the macOS Keychain, then a prompt:

  HA_TOKEN          or Keychain item `ha-token`     (HA long-lived token)
  AQARA_ACCOUNT     or Keychain item `aqara-app`    (EMAIL:::PASSWORD)
  AQARA_PASSWORD
  AQARA_APP_ID      or Keychain item `aqara-dev`    (APPID:::KEYID:::APPKEY)
  AQARA_KEY_ID      for the official Open API; used instead of the app login
  AQARA_APP_KEY     when present
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from fan_tracker.aqara import AqaraClient, FileTokenStore, KeychainTokenStore  # noqa: E402
from fan_tracker.aqara_app import AqaraAppClient  # noqa: E402
from fan_tracker.hass import HomeAssistant  # noqa: E402


def _load_local_env() -> None:
    f = ROOT / "local.env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_local_env()


def setting(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if not v:
        sys.exit(f"set {name} in the environment or in local.env")
    return v


KEYCHAIN_ACCOUNT = os.environ.get("KEYCHAIN_ACCOUNT", "fan-tracker")
HAS_KEYCHAIN = shutil.which("security") is not None


def keychain(service: str) -> str | None:
    if not HAS_KEYCHAIN:
        return None
    r = subprocess.run(["security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT,
                        "-s", service, "-w"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def fp2_did() -> str:
    return setting("FP2_DID")


def _session_store(name: str):
    if HAS_KEYCHAIN:
        return KeychainTokenStore(name, account=KEYCHAIN_ACCOUNT)
    d = Path.home() / ".config" / "fan-tracker"
    d.mkdir(parents=True, exist_ok=True)
    return FileTokenStore(d / f"{name}.json")


def aqara():
    """Official Open API client if developer keys are available, else the app login."""
    region = os.environ.get("AQARA_REGION", "US")
    dev = [os.environ.get(k) for k in ("AQARA_APP_ID", "AQARA_KEY_ID", "AQARA_APP_KEY")]
    if not all(dev) and keychain("aqara-dev"):
        dev = keychain("aqara-dev").split(":::")[:3]
    if all(dev) and len(dev) == 3:
        return AqaraClient(dev[0], dev[1], dev[2], region, _session_store("aqara-token"))
    account, password = os.environ.get("AQARA_ACCOUNT"), os.environ.get("AQARA_PASSWORD")
    if not (account and password) and keychain("aqara-app"):
        account, password = keychain("aqara-app").split(":::", 1)
    if not (account and password):
        account = input("Aqara Home account (email): ").strip()
        password = getpass.getpass("Aqara Home password: ")
    return AqaraAppClient(account, password, region, _session_store("aqara-app-session"))


def hass() -> HomeAssistant:
    token = os.environ.get("HA_TOKEN") or keychain("ha-token") or getpass.getpass("HA long-lived token: ")
    return HomeAssistant(setting("HA_URL"), token)
