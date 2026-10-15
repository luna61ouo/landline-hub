"""Paired clients.  Each phone or program has its own credential.

Only the SHA-256 of a credential is stored, so a program running on the
same machine that can read this file still cannot impersonate a phone.
Pairing codes are one-time and expire after 10 minutes.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from .domain.number import Kind
from .domain.permissions import Client, ClientRole

PAIR_TTL = 600


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class ClientStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "clients.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = None
        self._mtime = None

    # -- file --
    def _load(self) -> dict:
        try:
            m = self.path.stat().st_mtime
        except FileNotFoundError:
            return {"clients": {}, "pairing": {}}
        if self._cache is None or m != self._mtime:
            self._cache, self._mtime = json.loads(self.path.read_text()), m
        return self._cache

    def _save(self, d: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        self._cache, self._mtime = None, None

    # -- operator side (CLI) --
    def new_pairing(self, name: str, role: ClientRole) -> str:
        d = self._load()
        if any(c["name"] == name for c in d["clients"].values()):
            raise ValueError(f"a client named {name!r} already exists")
        code = "-".join(secrets.token_hex(2) for _ in range(3))
        now = time.time()
        d["pairing"] = {k: v for k, v in d.get("pairing", {}).items() if v["expires"] > now}
        d["pairing"][_h(code)] = {"name": name, "role": role.value, "expires": now + PAIR_TTL}
        self._save(d)
        return code

    def revoke(self, client_id: str) -> bool:
        d = self._load()
        if d["clients"].pop(client_id, None) is None:
            return False
        self._save(d)
        return True

    def grant(self, client_id: str, kind: Kind) -> None:
        d = self._load()
        c = d["clients"][client_id]
        c["extra_kinds"] = sorted(set(c.get("extra_kinds", [])) | {kind.value})
        self._save(d)

    def list(self) -> list[dict]:
        return [{"id": k, **{x: v[x] for x in ("name", "role", "created")}, "extra_kinds": v.get("extra_kinds", [])}
                for k, v in self._load()["clients"].items()]

    # -- daemon side --
    def pair(self, code: str) -> tuple[Client, str] | None:
        d = self._load()
        entry = d.get("pairing", {}).pop(_h(code or ""), None)
        if not entry or entry["expires"] < time.time():
            return None
        cid, token = entry["name"], secrets.token_urlsafe(32)
        d["clients"][cid] = {"name": entry["name"], "role": entry["role"], "token_sha256": _h(token),
                             "created": time.time(), "extra_kinds": []}
        self._save(d)
        return self._client(cid, d["clients"][cid]), token

    def authenticate(self, token: str) -> Client | None:
        if not token:
            return None
        th = _h(token)
        for cid, c in self._load()["clients"].items():
            if secrets.compare_digest(c["token_sha256"], th):
                return self._client(cid, c)
        return None

    @staticmethod
    def _client(cid: str, c: dict) -> Client:
        return Client(cid, ClientRole(c["role"]), frozenset(Kind(k) for k in c.get("extra_kinds", [])))
