"""Grandstream HT813 (FXO) as the hub's gateway.

direct mode: the HT813 never answers by itself (Number of Rings P798 = 50).
Its syslog tells us a call is ringing and who is calling.  When a phone
presses Answer, we flip P798 to 1: the HT813 picks up after the next ring
and forwards the call to our SIP server, which accepts only that call.  Then
P798 goes back to 50.  Press-to-talk takes about 7 s, mostly waiting for
the next ring.

pbx mode: set P798 = 1 and unconditional forward to VoIP permanently; every
call arrives as a SIP INVITE and the attendant answers it.

One-time device setup is described in docs/ht813-setup.md.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from ...domain import incoming
from ...line.sip_common import Datagram
from .ctl import HT813
from .parse import parse

NORMAL_RINGS = 50
REARM_EVERY = 240            # the web session times out after 10 min
ANSWER_WAIT = 25             # from "answer" to the forwarded INVITE


class PendingLine:
    """Stands in for the SIP leg until the HT813 forwards the call."""

    def __init__(self):
        self.ended = asyncio.Event()
        self.ended_by: str | None = None
        self.audio_in: asyncio.Queue = asyncio.Queue()

    async def hangup(self):
        self.ended_by = self.ended_by or "local"
        self.ended.set()

    def play(self, pcm8):
        pass

    def clear(self):
        pass

    def queued_sec(self):
        return 0.0


class Ht813Gateway:
    def __init__(self, hub, ctl=None):
        self.hub = hub
        g = hub.cfg.gateway
        if ctl is None:
            if not g.admin_password_file:
                raise ValueError("[gateway].admin_password_file is required for kind = 'ht813'")
            ctl = HT813(g.host, Path(g.admin_password_file).expanduser().read_text().strip())
        self.ctl = ctl
        self.state: incoming.State = incoming.Idle()
        self.by_ring: dict[str, object] = {}       # incoming-domain call id -> hub session
        self.armed = None
        self.flipped = False
        self.pending: tuple | None = None          # (session, future) waiting for the forwarded INVITE
        self._seq = 0
        self._tasks: list[asyncio.Task] = []
        self.transport = None

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        g = self.hub.cfg.gateway
        self.transport, _ = await loop.create_datagram_endpoint(lambda: Datagram(self._on_syslog),
                                                                local_addr=("0.0.0.0", g.syslog_port))
        self._tasks.append(asyncio.create_task(self._ticker()))
        if self.hub.cfg.mode == "direct":
            self._tasks.append(asyncio.create_task(self._arm_loop()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self.transport:
            self.transport.close()

    # ------------------------------------------------------------ ring detection
    def _new_id(self) -> str:
        self._seq += 1
        return f"ring{self._seq}"

    def _on_syslog(self, data: bytes, addr) -> None:
        if addr[0] != self.hub.cfg.gateway.host:
            return
        sig = parse(data.decode("utf-8", "replace"))
        if sig is not None:
            self.state, evs = incoming.step(self.state, sig, time.time(), self._new_id)
            self._handle(evs)

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1)
            self.state, evs = incoming.tick(self.state, time.time())
            self._handle(evs)

    def _handle(self, evs) -> None:
        if self.hub.cfg.mode != "direct":
            return
        for ev in evs:
            t, rid = ev["type"], ev["call_id"]
            if t == "incoming":
                s = self.hub.new_inbound(PendingLine(), ev["number"])
                if s is not None:
                    self.by_ring[rid] = s
                    asyncio.create_task(self.hub.ring_handsets(s))
                continue
            s = self.by_ring.get(rid)
            if s is None:
                continue
            if t == "caller_id":
                s.number = ev["number"]
                self.hub.emit({"type": "caller_id", "call_id": s.call_id, "number": ev["number"]},
                              self.hub.to_handsets)
            elif t == "ring":
                self.hub.emit({"type": "ring", "call_id": s.call_id, "rings": ev["rings"]}, self.hub.to_handsets)
            elif t == "ended":
                self.by_ring.pop(rid, None)
                if s.state == "ringing" and isinstance(s.line, PendingLine):
                    s.line.ended_by = "remote_cancel"
                    s.line.ended.set()

    # ------------------------------------------------------------ answering
    async def answer(self, s) -> bool:
        if not isinstance(s.line, PendingLine):
            await s.line.accept()
            return True
        fut = asyncio.get_running_loop().create_future()
        self.pending = (s, fut)
        try:
            prepared, self.armed = self.armed, None
            if prepared is None:
                prepared = await asyncio.to_thread(self.ctl.prepare_answer)
            self.flipped = True
            await asyncio.to_thread(self.ctl.send, prepared)
        except Exception as e:
            self.hub.log("ht813_answer_failed", err=repr(e))
            self.pending = None
            asyncio.create_task(self._restore())
            return False
        try:
            return await asyncio.wait_for(fut, timeout=ANSWER_WAIT)
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending = None
            asyncio.create_task(self._restore())

    async def on_invite(self, call) -> None:
        if self.pending and not self.pending[1].done():
            s, fut = self.pending
            s.line = call
            await call.accept()
            fut.set_result(True)
            return
        if self.hub.cfg.mode == "pbx":
            s = self.hub.new_inbound(call, call.number)
            if s is not None:
                from ...pbx_runtime import run_attendant
                await run_attendant(self.hub, s)
            return
        call.reject()     # direct mode: only the call somebody just answered may come in

    # ------------------------------------------------------------ keeping P798 right
    async def _arm(self) -> None:
        try:
            self.armed = await asyncio.to_thread(self.ctl.prepare_answer)
        except Exception as e:
            self.armed = None
            self.hub.log("ht813_arm_failed", err=repr(e))

    async def _arm_loop(self) -> None:
        try:
            if await asyncio.to_thread(self.ctl.rings) != NORMAL_RINGS:
                self.flipped = True
                await self._restore()
        except Exception as e:
            self.hub.log("ht813_check_failed", err=repr(e))
        while True:
            if not self.flipped and isinstance(self.state, incoming.Idle):
                await self._arm()
            await asyncio.sleep(REARM_EVERY)

    async def _restore(self) -> None:
        if not self.flipped:
            return
        for _ in range(5):
            try:
                await asyncio.to_thread(self.ctl.set_rings, NORMAL_RINGS)
                self.flipped = False
                await self._arm()
                return
            except Exception as e:
                self.hub.log("ht813_restore_failed", err=repr(e))
                await asyncio.sleep(3)
        self.hub.log("ht813_WARNING", msg="could not set Number of Rings back to 50; the HT813 may now auto-answer calls")
