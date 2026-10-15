"""Gateway adapters.  Swap the gateway hardware by swapping this package."""
from __future__ import annotations


def make_gateway(hub):
    kind = hub.cfg.gateway.kind
    if kind == "sip":
        from .generic_sip import GenericSipGateway
        return GenericSipGateway(hub)
    if kind == "ht813":
        from .grandstream_ht813.adapter import Ht813Gateway
        return Ht813Gateway(hub)
    raise ValueError(kind)
