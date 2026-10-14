#!/bin/sh
# For development: copy the add-on folder to Home Assistant's local add-ons
# (/local_apps/fan_tracker) over SSH, via the Terminal & SSH add-on.
# Afterwards: ha store reload, then install (first time) or `ha apps update local_fan_tracker`.
# Set HA_SSH (e.g. root@homeassistant.local) in the environment or local.env.
set -eu
cd "$(dirname "$0")"
[ -f local.env ] && . ./local.env
: "${HA_SSH:?set HA_SSH, e.g. root@homeassistant.local}"
COPYFILE_DISABLE=1 tar -cf - --exclude __pycache__ -C addon . |
  ssh -o BatchMode=yes "$HA_SSH" 'mkdir -p "/local_apps/fan_tracker" && rm -rf "/local_apps/fan_tracker/fan_tracker" && tar -xf - -C "/local_apps/fan_tracker" && find "/local_apps/fan_tracker" -type f | sort'
