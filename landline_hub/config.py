"""Configuration (TOML) -> frozen settings.  Validated once at load (fail fast)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .domain.number import POLICIES, NumberPolicy
from .domain.pbx import Directory, Timers, build_directory


@dataclass(frozen=True)
class GatewayConf:
    kind: str                 # "sip" (generic) | "ht813"
    host: str
    port: int = 5062          # gateway SIP port we send INVITEs to
    user: str | None = None
    password: str | None = None
    inbound_sip_port: int = 5090
    rtp_ports: range = range(40100, 40200, 2)
    syslog_port: int = 5520   # ht813 only
    admin_password_file: str | None = None   # ht813 only


@dataclass(frozen=True)
class PbxConf:
    directory: Directory
    timers: Timers
    prompts_dir: Path


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    data_dir: Path
    gateway: GatewayConf
    policy: NumberPolicy
    mode: str                 # "direct" | "pbx"
    direct_ring_timeout: float
    max_call_sec: int
    pbx: PbxConf | None = None
    extra: dict = field(default_factory=dict)


def _range(text: str) -> range:
    a, b = (int(x) for x in str(text).split("-"))
    if a % 2:
        a += 1
    return range(a, b + 1, 2)


def load(path: str | Path) -> Config:
    path = Path(path)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    srv = raw.get("server", {})
    gw = raw.get("gateway", {})
    if "host" not in gw:
        raise ValueError("[gateway].host is required")
    kind = gw.get("kind", "sip")
    if kind not in ("sip", "ht813"):
        raise ValueError(f"[gateway].kind must be 'sip' or 'ht813', not {kind!r}")
    gateway = GatewayConf(
        kind=kind, host=gw["host"], port=int(gw.get("port", 5062)),
        user=gw.get("user"), password=gw.get("password"),
        inbound_sip_port=int(gw.get("inbound_sip_port", 5090)),
        rtp_ports=_range(gw.get("rtp_ports", "40100-40199")),
        syslog_port=int(gw.get("syslog_port", 5520)),
        admin_password_file=gw.get("admin_password_file"),
    )
    pol_name = raw.get("numbers", {}).get("policy", "tw")
    if pol_name not in POLICIES:
        raise ValueError(f"unknown number policy {pol_name!r}; available: {sorted(POLICIES)}")
    fwd = raw.get("forward", {})
    mode = fwd.get("mode", "direct")
    if mode not in ("direct", "pbx"):
        raise ValueError("[forward].mode must be 'direct' or 'pbx'")
    pbx = None
    if mode == "pbx":
        p = raw.get("pbx", {})
        directory = build_directory(p.get("extensions", []), p.get("operator"))
        t = Timers(**{k: p[k] for k in ("digit_timeout", "ring_sec", "choice_timeout", "farewell_sec",
                                         "max_retries", "max_wait_rounds") if k in p})
        pbx = PbxConf(directory, t, (base / p.get("prompts_dir", "prompts")).resolve())
    return Config(
        host=srv.get("host", "127.0.0.1"), port=int(srv.get("port", 8910)),
        data_dir=(base / srv.get("data_dir", "data")).resolve(),
        gateway=gateway, policy=POLICIES[pol_name](), mode=mode,
        direct_ring_timeout=float(fwd.get("ring_timeout", 60)),
        max_call_sec=int(srv.get("max_call_sec", 3600)), pbx=pbx, extra=raw,
    )
