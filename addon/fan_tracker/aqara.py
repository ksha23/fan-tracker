"""Minimal Aqara Open API v3 client (standard library only).

Signing and intents follow Aqara's published API, as also implemented by
Darkdragon14/ha-aqara-devices. Tokens are kept in a TokenStore so the same
client runs on a Mac (Keychain) or in the Home Assistant add-on (a file).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

SERVERS = {
    "US": "https://open-usa.aqara.com",
    "EU": "https://open-ger.aqara.com",
    "CN": "https://open-cn.aqara.com",
    "KR": "https://open-kr.aqara.com",
    "RU": "https://open-ru.aqara.com",
    "SG": "https://open-sg.aqara.com",
}
API_PATH = "/v3.0/open/api"
AUTH_ERROR_CODES = {"108", "401", "403", "1005", "1006", "1008", "1013"}


class AqaraError(RuntimeError):
    def __init__(self, intent: str, resp: dict):
        self.code = str(resp.get("code"))
        self.resp = resp
        detail = resp.get("msgDetails") or resp.get("messageDetail") or ""
        super().__init__(f"{intent}: code={self.code} {resp.get('message')} {detail}".strip())


# ------------------------------------------------------------------ tokens

class FileTokenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def save(self, tokens: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens))
        tmp.chmod(0o600)
        tmp.replace(self.path)


class KeychainTokenStore:
    """macOS Keychain item holding the token JSON."""

    def __init__(self, service: str = "aqara-token", account: str = "fan-tracker"):
        self.service, self.account = service, account

    def load(self) -> dict:
        r = subprocess.run(["security", "find-generic-password", "-a", self.account,
                            "-s", self.service, "-w"], capture_output=True, text=True)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}

    def save(self, tokens: dict) -> None:
        subprocess.run(["security", "add-generic-password", "-U", "-a", self.account,
                        "-s", self.service, "-w", json.dumps(tokens)], check=True)


# ------------------------------------------------------------------ client

class AqaraClient:
    def __init__(self, app_id: str, key_id: str, app_key: str, region: str = "US",
                 store=None, timeout: float = 8.0):
        self.app_id, self.key_id, self.app_key = app_id, key_id, app_key
        if region.upper() not in SERVERS:
            raise ValueError(f"Open API has no region {region!r} (known: {', '.join(SERVERS)})")
        self.url = SERVERS[region.upper()] + API_PATH
        self.store = store
        self.timeout = timeout
        self.tokens = store.load() if store else {}
        self._lock = threading.Lock()

    # -- low level

    def sign(self, headers: dict) -> str:
        parts = []
        if headers.get("Accesstoken"):
            parts.append(f"Accesstoken={headers['Accesstoken']}")
        parts += [f"Appid={headers['Appid']}", f"Keyid={headers['Keyid']}",
                  f"Nonce={headers['Nonce']}", f"Time={headers['Time']}"]
        return hashlib.md5(("&".join(parts) + self.app_key).lower().encode()).hexdigest()

    def _headers(self, access_token: str | None) -> dict:
        h = {"Appid": self.app_id, "Keyid": self.key_id, "Nonce": uuid.uuid4().hex,
             "Time": str(int(time.time() * 1000)), "Lang": "en",
             "Content-Type": "application/json"}
        if access_token:
            h["Accesstoken"] = access_token
        h["Sign"] = self.sign(h)
        return h

    def _post(self, intent: str, data, access_token: str | None) -> dict:
        body = json.dumps({"intent": intent, "data": data}, separators=(",", ":")).encode()
        req = urllib.request.Request(self.url, data=body, headers=self._headers(access_token))
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def request(self, intent: str, data, *, auth: bool = True, retry: bool = True) -> dict:
        token = None
        if auth:
            self._refresh_if_needed()
            token = self.tokens.get("access_token")
            if not token:
                raise AqaraError(intent, {"code": "no_token", "message": "not logged in"})
        resp = self._post(intent, data, token)
        code = str(resp.get("code"))
        if auth and retry and code in AUTH_ERROR_CODES:
            self.refresh(force=True)
            return self.request(intent, data, auth=True, retry=False)
        if code != "0":
            raise AqaraError(intent, resp)
        return resp.get("result")

    # -- auth

    def request_auth_code(self, account: str, validity: str = "30d") -> None:
        """Aqara emails (or texts) a verification code to the account."""
        self.request("config.auth.getAuthCode",
                     {"account": account, "accountType": 0, "accessTokenValidity": validity},
                     auth=False)

    def exchange_auth_code(self, account: str, code: str) -> None:
        r = self.request("config.auth.getToken",
                         {"authCode": code, "account": account, "accountType": 0}, auth=False)
        self._set_tokens(r)

    def _set_tokens(self, r: dict) -> None:
        self.tokens = {
            "access_token": r.get("accessToken"),
            "refresh_token": r.get("refreshToken") or self.tokens.get("refresh_token"),
            "open_id": r.get("openId") or self.tokens.get("open_id"),
            "expires_at": time.time() + int(r.get("expiresIn") or 0) if r.get("expiresIn") else None,
        }
        if self.store:
            self.store.save(self.tokens)

    def _refresh_if_needed(self) -> None:
        exp = self.tokens.get("expires_at")
        if exp and time.time() > exp - 3600:
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not self.tokens.get("refresh_token"):
                raise AqaraError("config.auth.refreshToken", {"code": "no_refresh_token"})
            r = self.request("config.auth.refreshToken",
                             {"refreshToken": self.tokens["refresh_token"]}, auth=False)
            self._set_tokens(r)
            log.info("Aqara access token refreshed")

    # -- devices and resources

    def devices(self) -> list[dict]:
        r = self.request("query.device.info", {"pageNum": 1, "pageSize": 100})
        return r.get("data", []) if isinstance(r, dict) else []

    def query(self, did: str, resource_ids: list[str]) -> list[dict]:
        """Current values: [{resourceId, value, timeStamp, ...}]."""
        r = self.request("query.resource.value",
                         {"resources": [{"subjectId": did, "resourceIds": resource_ids}]})
        return r or []

    def write(self, did: str, values: dict[str, object]) -> None:
        self.request("write.resource.device", [{
            "subjectId": did,
            "resources": [{"resourceId": k, "value": str(v)} for k, v in values.items()],
        }])

    def resource_info(self, model: str, resource_ids: list[str] | None = None):
        data = {"model": model}
        if resource_ids:
            data["resourceIds"] = resource_ids
        return self.request("query.resource.info", data)
