"""A gateway that forwards incoming calls to us as SIP INVITEs right away
(most SIP trunks, an FXO gateway set to auto-forward, or the fake gateway
used in tests).  The INVITE itself is the ringing; answering is a 200 OK."""
from __future__ import annotations


class GenericSipGateway:
    def __init__(self, hub):
        self.hub = hub

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def on_invite(self, call) -> None:
        s = self.hub.new_inbound(call, call.number)
        if s is None:
            return
        if self.hub.cfg.mode == "pbx":
            from ..pbx_runtime import run_attendant
            await run_attendant(self.hub, s)
        else:
            await self.hub.ring_handsets(s)

    async def answer(self, session) -> bool:
        await session.line.accept()
        return True
