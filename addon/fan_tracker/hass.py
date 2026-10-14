"""Small Home Assistant REST client (standard library only).

Inside the add-on, base_url is http://supervisor/core/api with the
SUPERVISOR_TOKEN. From a workstation it is http://<ha>:8123/api with a
long-lived token.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class HomeAssistant:
    def __init__(self, base_url: str, token: str, timeout: float = 8.0):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body=None):
        req = urllib.request.Request(
            self.base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def state(self, entity_id: str) -> dict | None:
        try:
            return self._call("GET", f"/states/{entity_id}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def service(self, domain: str, service: str, **data):
        return self._call("POST", f"/services/{domain}/{service}", data)

    def set_number(self, entity_id: str, value: float):
        return self.service("number", "set_value", entity_id=entity_id, value=value)

    def publish(self, entity_id: str, state, attributes: dict):
        """Create or update a state-only entity (no integration behind it)."""
        return self._call("POST", f"/states/{entity_id}",
                          {"state": state, "attributes": attributes})
