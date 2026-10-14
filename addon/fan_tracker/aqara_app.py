"""Aqara Home app ("legacy RPC") client: account login instead of a developer key.

Unofficial. The endpoints, the per-region app id/key and the RSA key come from
the Aqara Home app as documented by absent42/Aqara-LANLink (hub/cloud_client.py)
and sdavides/AqaraPOST. It can break whenever Aqara changes the app.

Exposes the same query()/write() shape as AqaraClient so the service can use
either one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import urllib.request
import uuid

log = logging.getLogger(__name__)

SERVERS = {
    "US": "https://aiot-rpc-usa.aqara.com",
    "EU": "https://rpc-ger.aqara.com",
    "CN": "https://aiot-rpc.aqara.cn",
    "KR": "https://rpc-kr.aqara.com",
    "RU": "https://rpc-ru.aqara.com",
    "AU": "https://rpc-au.aqara.com",
}
# (appid, appkey) pairs embedded in the app. The first is LANLink's choice for
# US and EU. The others are tried once if the server rejects the signature (106).
SIGNING_PAIRS = (
    ("7be1984f0556276133336839", "Jddz01kIORDYrBzqGYgpUXKBnIHfW8E3"),
    ("94549908487478b220992a70", "euGhPe2rcmxwculATNj45eEtnd50zp0I"),
    ("94549908487478b220992a70", "Jddz01kIORDYrBzqGYgpUXKBnIHfW8E3"),
)
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCG46slB57013JJs4Vvj5cVyMpR
9b+B2F+YJU6qhBEYbiEmIdWpFPpOuBikDs2FcPS19MiWq1IrmxJtkICGurqImRUt
4lP688IWlEmqHfSxSRf2+aH0cH8VWZ2OaZn5DWSIHIPBF2kxM71q8stmoYiV0oZs
rZzBHsMuBwA4LQdxBwIDAQAB
-----END PUBLIC KEY-----"""
LOGIN = "/app/v1.0/lumi/user/login"
DEVICES = "/app/v1.0/lumi/app/position/device/query"
RES_QUERY = "/app/v1.0/lumi/res/query/by/resourceId"
RES_WRITE = "/app/v1.0/lumi/res/write"
AUTH_FAILURE_CODES = {"108", "109", "802", "804"}
CLIENT_HEADERS = {"User-Agent": "okhttp/4.12.0", "App-Version": "6.1.6", "Sys-Type": "1",
                  "Lang": "en", "Phone-Model": "Home Assistant##Server"}


class AqaraAppError(RuntimeError):
    def __init__(self, what: str, resp: dict):
        self.code = str(resp.get("code"))
        self.resp = resp
        super().__init__(f"{what}: code={self.code} {resp.get('message') or resp.get('msg') or ''}".strip())


# ------------------------------------------------------------- RSA (encrypt only)

def _der(buf: bytes, i: int) -> tuple[int, bytes, int]:
    """One DER element at i: (tag, value, index after it)."""
    tag, n = buf[i], buf[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[i:i + k], "big")
        i += k
    return tag, buf[i:i + n], i + n


def rsa_public_key(pem: str) -> tuple[int, int]:
    """(n, e) from a PEM SubjectPublicKeyInfo."""
    body = "".join(l for l in pem.strip().splitlines() if not l.startswith("-----"))
    _, spki, _ = _der(base64.b64decode(body), 0)
    _, _, i = _der(spki, 0)                 # AlgorithmIdentifier
    _, bits, _ = _der(spki, i)              # BIT STRING, first byte = unused bits
    _, rsakey, _ = _der(bits[1:], 0)
    _, n, j = _der(rsakey, 0)
    _, e, _ = _der(rsakey, j)
    return int.from_bytes(n, "big"), int.from_bytes(e, "big")


def rsa_pkcs1v15_encrypt(n: int, e: int, message: bytes) -> bytes:
    k = (n.bit_length() + 7) // 8
    if len(message) > k - 11:
        raise ValueError("message too long")
    pad = b""
    while len(pad) < k - 3 - len(message):
        pad += bytes(b for b in os.urandom(k) if b)
    em = b"\x00\x02" + pad[:k - 3 - len(message)] + b"\x00" + message
    return pow(int.from_bytes(em, "big"), e, n).to_bytes(k, "big")


def encrypt_password(password: str) -> str:
    n, e = rsa_public_key(PUBLIC_KEY_PEM)
    md5_hex = hashlib.md5(password.encode()).hexdigest().encode()
    return base64.b64encode(rsa_pkcs1v15_encrypt(n, e, md5_hex)).decode()


# ------------------------------------------------------------- client

class AqaraAppClient:
    def __init__(self, account: str, password: str, region: str = "US", store=None,
                 timeout: float = 8.0):
        self.account, self.password = account, password
        self.region = region.upper()
        if self.region not in SERVERS:
            raise ValueError(f"app login does not know region {region!r} (known: {', '.join(SERVERS)})")
        self.server = SERVERS[self.region]
        self.store = store
        self.timeout = timeout
        self.session = store.load() if store else {}
        self.session.setdefault("phone_id", str(uuid.uuid4()).upper())
        pair = self.session.get("pair")
        self.appid, self.appkey = tuple(pair) if pair else SIGNING_PAIRS[0]

    def _save(self) -> None:
        self.session["pair"] = [self.appid, self.appkey]
        if self.store:
            self.store.save(self.session)

    def sign(self, nonce: str, ts: str, body: str, token: str | None) -> str:
        tok = f"&Token={token}" if token else ""
        return hashlib.md5(f"Appid={self.appid}&Nonce={nonce}&Time={ts}{tok}&{body}&{self.appkey}"
                           .encode()).hexdigest()

    def _send(self, method: str, path: str, sign_src: str, body: str | None, token: str | None,
              query: str = "") -> dict:
        nonce = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
        ts = str(round(time.time() * 1000))
        h = {**CLIENT_HEADERS, "PhoneId": self.session["phone_id"], "Area": self.region,
             "Appid": self.appid, "Nonce": nonce, "Time": ts, "Content-Type": "application/json",
             "Sign": self.sign(nonce, ts, sign_src, token)}
        if token:
            h["Token"] = token
        url = self.server + path + (f"?{query}" if query else "")
        req = urllib.request.Request(url, method=method, headers=h,
                                     data=body.encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def _signed(self, method, path, sign_src, body, token, query=""):
        resp = self._send(method, path, sign_src, body, token, query)
        if str(resp.get("code")) != "106" or self.session.get("probed"):
            return resp
        self.session["probed"] = True
        seed = (self.appid, self.appkey)
        for pair in SIGNING_PAIRS:
            if pair == seed:
                continue
            self.appid, self.appkey = pair
            retry = self._send(method, path, sign_src, body, token, query)
            if str(retry.get("code")) != "106":
                log.info("Aqara app signing: switched to appid %s..", pair[0][:8])
                self._save()
                return retry
        self.appid, self.appkey = seed
        return resp

    def login(self) -> None:
        # Body is signed and sent with default json.dumps spacing. The server checks the bytes.
        body = json.dumps({"account": self.account, "encryptType": 2,
                           "password": encrypt_password(self.password)})
        resp = self._signed("POST", LOGIN, body, body, None)
        if str(resp.get("code")) != "0":
            raise AqaraAppError("login", resp)
        r = resp.get("result") or {}
        self.session.update(token=r.get("token"), user_id=r.get("userId"))
        self._save()
        log.info("Aqara app login ok")

    def _authed(self, method, path, body_obj=None, query=""):
        if not self.session.get("token"):
            self.login()
        for attempt in (0, 1):
            body = json.dumps(body_obj) if body_obj is not None else None
            resp = self._signed(method, path, body if body is not None else query, body,
                                self.session["token"], query)
            code = str(resp.get("code"))
            if code in AUTH_FAILURE_CODES and attempt == 0:
                self.login()
                continue
            if code != "0":
                raise AqaraAppError(path, resp)
            return resp.get("result")

    # -- same surface as AqaraClient

    def devices(self) -> list[dict]:
        r = self._authed("GET", DEVICES, query="size=300&startIndex=0")
        return (r or {}).get("devices", [])

    def query(self, did: str, resource_ids: list[str]) -> list[dict]:
        r = self._authed("POST", RES_QUERY, {"data": [{"options": list(resource_ids), "subjectId": did}]})
        return r if isinstance(r, list) else []

    def write(self, did: str, values: dict[str, object]) -> None:
        self._authed("POST", RES_WRITE, {"data": {k: str(v) for k, v in values.items()},
                                         "subjectId": did})
