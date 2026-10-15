"""HT813 syslog (DEBUG level) -> incoming-call signals.  Swap this file to
support another gateway.  FXO is port 1 on the HT813.

Key lines (recorded on a real line):
  Nuvoton::decodeDtmfCidNumber, CID Caller Number 0212345678   (caller id, Taiwan sends DTMF CID)
  Dispatching event 36 (LINE_RING_START) on port 1:0
  Dispatching event 37 (LINE_RING_STOP) on port 1:0
  Nuvoton::fxoHookSet, Set Hook to  OffHook on port 1:0
  Nuvoton::fxoHookSet, Set Hook to  OnHook on port 1:0
"""
from __future__ import annotations

import re

from ...domain.incoming import CallerId, LineReleased, LineSeized, RingStart, RingStop, Signal

_CID = re.compile(r"CID Caller Number\s+(\+?\d+)")


def parse(line: str) -> Signal | None:
    if "GS_ATA" not in line:
        return None
    m = _CID.search(line)
    if m:
        return CallerId(m.group(1))
    if "(LINE_RING_START) on port 1:" in line:
        return RingStart()
    if "(LINE_RING_STOP) on port 1:" in line:
        return RingStop()
    if "fxoHookSet, Set Hook to  OffHook on port 1:" in line:
        return LineSeized()
    if "fxoHookSet, Set Hook to  OnHook on port 1:" in line:
        return LineReleased()
    return None
