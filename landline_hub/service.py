"""The hub: owns the line, routes calls between the gateway and clients.

Imperative shell around the pure domain.  Every decision (may this client
dial this number, is the line free, what does the attendant do next) is
made by a domain function; this module only performs the I/O.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import Config
from .domain import ownership
from .domain.number import DialNumber, Rejected
from .domain.permissions import Client, ClientRole, may_dial
from .line import dtmf
from .line.answer_gate import AnswerGate
from .line.sip_uac import OutboundSip
from .line.sip_uas import InboundSip, SipServer


def new_id() -> str:
    return time.strftime("%m%d%H%M%S-") + secrets.token_hex(3)


LIVE_MAX_QUEUE_SEC = 0.2      # a person's voice may lag the line by at most this much


@dataclass
class Session:
    call_id: str
    direction: str                     # "outbound" | "inbound"
    number: str | None
    line: object                       # OutboundSip | InboundSip
    owner: str | None                  # client id currently talking on it
    started: float = field(default_factory=time.time)
    state: str = "ringing"             # ringing | connected | ended
    answer_detection: bool = False
    gate: AnswerGate | None = None
    sink: Callable[[bytes], None] | None = None     # who receives far-end audio right now
    attached: asyncio.Event = field(default_factory=asyncio.Event)
    ring_targets: frozenset[str] = frozenset()      # pbx: devices allowed to answer
    pbx: object | None = None
    end_reason: str = ""


class Bus:
    """Fan-out of JSON events to connected clients."""

    def __init__(self):
        self.subs: dict[int, tuple[Client, asyncio.Queue]] = {}

    def subscribe(self, client: Client) -> tuple[int, asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        key = id(q)
        self.subs[key] = (client, q)
        return key, q

    def unsubscribe(self, key: int) -> None:
        self.subs.pop(key, None)

    def publish(self, event: dict, to: Callable[[Client], bool]) -> None:
        for client, q in list(self.subs.values()):
            if to(client):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass


class Hub:
    def __init__(self, cfg: Config, log=None):
        self.cfg = cfg
        self.log = log or (lambda *a, **k: print(time.strftime("%H:%M:%S"), *a, k, flush=True))
        self.bus = Bus()
        self.line_state: ownership.LineState = ownership.Free()
        self.sessions: dict[str, Session] = {}
        self.sip_server: SipServer | None = None
        self.gateway = None            # gateway adapter (generic SIP or HT813)
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.calls_log = cfg.data_dir / "calls.jsonl"

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        from .gateway import make_gateway
        self.gateway = make_gateway(self)
        g = self.cfg.gateway
        self.sip_server = SipServer(g.host, self._on_invite, g.inbound_sip_port, g.rtp_ports,
                                    log=lambda t, **f: self.log(t, **f))
        await self.sip_server.start()
        await self.gateway.start()

    async def stop(self) -> None:
        for s in list(self.sessions.values()):
            await s.line.hangup()
        if self.gateway:
            await self.gateway.stop()
        if self.sip_server:
            self.sip_server.close()

    # ------------------------------------------------------------ events
    def to_handsets(self, c: Client) -> bool:
        return c.role is ClientRole.HANDSET

    def emit(self, event: dict, to: Callable[[Client], bool]) -> None:
        event = {"at": time.time(), **event}
        self.bus.publish(event, to)

    def ringing_for(self, c: Client) -> list[dict]:
        """Calls this client could answer right now.  Sent when a phone
        (re)connects, so a phone that was offline when the ringing started
        still shows the call."""
        out = []
        for s in self.sessions.values():
            if s.state != "ringing" or s.direction != "inbound" or c.role is not ClientRole.HANDSET:
                continue
            if s.pbx is not None and c.client_id not in s.ring_targets:
                continue
            ev = {"type": "incoming", "call_id": s.call_id, "number": s.number, "at": time.time()}
            if s.pbx is not None:
                ev["extension"] = True
            out.append(ev)
        return out

    def _record(self, s: Session) -> None:
        with self.calls_log.open("a") as f:
            f.write(json.dumps({"call_id": s.call_id, "direction": s.direction, "number": s.number,
                                "owner": s.owner, "started": s.started, "ended": time.time(),
                                "result": s.end_reason}) + "\n")

    # ------------------------------------------------------------ line ownership
    def claim(self, owner: str, purpose: str) -> bool:
        r = ownership.claim(self.line_state, owner, purpose, time.time())
        if isinstance(r, ownership.Busy):
            return False
        self.line_state = r.state
        return True

    def release(self, owner: str) -> None:
        self.line_state = ownership.release(self.line_state, owner)

    # ------------------------------------------------------------ outbound
    async def outbound(self, client: Client, raw_number: str, answer_detection: bool) -> dict:
        parsed = self.cfg.policy.parse(raw_number)
        if isinstance(parsed, Rejected):
            return {"ok": False, "error": "invalid_number", "detail": parsed.reason}
        assert isinstance(parsed, DialNumber)
        if not may_dial(client, parsed):
            return {"ok": False, "error": "not_permitted", "detail": f"{client.role.value} may not dial {parsed.kind.value} numbers"}
        call_id = new_id()
        if not self.claim(f"call:{call_id}", "outbound"):
            return {"ok": False, "error": "busy"}
        g = self.cfg.gateway
        line = OutboundSip(g.host, g.port, g.user, g.password, log=lambda t, **f: self.log(t, call=call_id, **f))
        s = Session(call_id, "outbound", parsed.digits, line, client.client_id, answer_detection=answer_detection)
        if answer_detection:
            s.gate = AnswerGate(log=lambda t, **f: self.emit({"type": "gate", "call_id": call_id, "what": t, **f},
                                                              lambda c, o=client.client_id: c.client_id == o))
        self.sessions[call_id] = s
        asyncio.create_task(self._run_outbound(s))
        self.log("outbound", call=call_id, by=client.client_id, kind=parsed.kind.value)
        return {"ok": True, "call_id": call_id}

    async def _run_outbound(self, s: Session) -> None:
        owner_only = lambda c, o=s.owner: c.client_id == o  # noqa: E731
        try:
            ok = await s.line.dial(s.number)
            if not ok:
                s.end_reason = f"not_connected:{s.line.fail_reason}"
                self.emit({"type": "ended", "call_id": s.call_id, "reason": s.end_reason, "by": "system"}, owner_only)
                return
            s.state = "connected"
            self.emit({"type": "line_connected", "call_id": s.call_id}, owner_only)
            if not s.answer_detection:
                self.emit({"type": "callee_answered", "call_id": s.call_id, "how": "not_detected"}, owner_only)
            await self._pump(s)
        except Exception as e:  # pragma: no cover - logged, call torn down
            self.log("outbound_error", call=s.call_id, err=repr(e))
            s.end_reason = "error"
        finally:
            await self._finish(s)

    # ------------------------------------------------------------ inbound
    async def _on_invite(self, call: InboundSip) -> None:
        await self.gateway.on_invite(call)

    def new_inbound(self, call: InboundSip, number: str | None) -> Session | None:
        """Gateway adapters call this when a call from outside reaches us."""
        call_id = new_id()
        if not self.claim(f"call:{call_id}", "inbound"):
            call.reject()
            return None
        s = Session(call_id, "inbound", number, call, None)
        self.sessions[call_id] = s
        return s

    async def ring_handsets(self, s: Session) -> None:
        """Direct mode: every paired phone rings; the first to answer gets the call."""
        self.emit({"type": "incoming", "call_id": s.call_id, "number": s.number}, self.to_handsets)
        try:
            await asyncio.wait_for(s.line.ended.wait(), timeout=self.cfg.direct_ring_timeout)
        except asyncio.TimeoutError:
            if s.state == "ringing":
                await s.line.hangup()
        if s.state == "ringing":
            s.end_reason = "missed"
            await self._finish(s)

    async def answer(self, client: Client, call_id: str) -> dict:
        s = self.sessions.get(call_id)
        if not s or s.direction != "inbound" or s.state == "ended":
            return {"ok": False, "error": "no_such_call"}
        if client.role is not ClientRole.HANDSET:
            return {"ok": False, "error": "not_permitted"}
        if s.pbx is not None:
            return await s.pbx.handset_answered(client.client_id)
        if s.state != "ringing" or s.owner:
            return {"ok": False, "error": "already_answered"}
        s.owner = client.client_id
        ok = await self.gateway.answer(s)
        if not ok:
            s.owner = None
            return {"ok": False, "error": "answer_failed"}
        self.connected(s)
        return {"ok": True}

    def connected(self, s: Session) -> None:
        s.state = "connected"
        self.emit({"type": "answered", "call_id": s.call_id, "by": s.owner}, self.to_handsets)
        asyncio.create_task(self._pump_then_finish(s))

    async def _pump_then_finish(self, s: Session) -> None:
        try:
            await self._pump(s)
        finally:
            await self._finish(s)

    # ------------------------------------------------------------ media
    async def _pump(self, s: Session) -> None:
        """Far-end audio -> whoever is the sink now (attendant, or a client's WebSocket)."""
        t0 = time.monotonic()
        while not s.line.ended.is_set():
            if time.monotonic() - t0 > self.cfg.max_call_sec:
                s.end_reason = "max_duration"
                await s.line.hangup()
                break
            try:
                raw = await asyncio.wait_for(s.line.audio_in.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            chunks = [raw]
            if s.gate and (not s.gate.open or s.gate.verify_until is not None):
                was_open, recalled = s.gate.open, s.gate.recalled
                chunks = s.gate.feed(raw, time.monotonic() - t0)
                if s.gate.recalled > recalled:
                    # 10-24: the gate had opened on an inference and the ring came back
                    self.emit({"type": "callee_not_answered", "call_id": s.call_id},
                              lambda c, o=s.owner: c.client_id == o)
                if chunks is None:
                    continue
                if not was_open:
                    self.emit({"type": "callee_answered", "call_id": s.call_id, "how": s.gate.reason,
                               "talking": s.gate.voice_ms > 0}, lambda c, o=s.owner: c.client_id == o)
            if s.sink:
                for c in chunks:
                    s.sink(c)

    def play(self, s: Session, pcm8: bytes, live: bool = False) -> None:
        """Audio from a client to the far end.

        live (a person on a phone): nothing is queued before the call is
        connected, and a backlog is dropped rather than played late - a
        person talking wants the delay of a telephone, not a queue.  Without
        this, the seconds a call spends dialling piled up and every word
        afterwards arrived that much later.  A voice model (not live) may
        queue a whole sentence ahead on purpose."""
        if live:
            if s.state != "connected":
                return
            if s.line.queued_sec() > LIVE_MAX_QUEUE_SEC:
                s.line.clear()
        s.line.play(pcm8)

    def press(self, s: Session, digits: str) -> None:
        digits = "".join(c for c in digits if c in "0123456789*#wW")
        s.line.play(dtmf.tones(digits, 8000))

    async def hangup(self, client: Client, call_id: str) -> dict:
        s = self.sessions.get(call_id)
        if not s or s.owner != client.client_id:
            return {"ok": False, "error": "no_such_call"}
        await s.line.hangup()
        return {"ok": True}

    @staticmethod
    def end_reason_of(s: Session) -> str:
        if s.end_reason:
            return s.end_reason
        return {"remote": "remote_hangup", "local": "local_hangup",
                "remote_cancel": "caller_gave_up"}.get(s.line.ended_by or "", s.line.ended_by or "ended")

    async def _finish(self, s: Session) -> None:
        if s.state == "ended":
            return
        if not s.line.ended.is_set():
            await s.line.hangup()
        s.state = "ended"
        s.end_reason = self.end_reason_of(s)
        ev = {"type": "ended", "call_id": s.call_id, "reason": s.end_reason, "by": s.line.ended_by}
        if s.direction == "inbound":
            self.emit(ev, self.to_handsets)
        elif s.owner:
            self.emit(ev, lambda c, o=s.owner: c.client_id == o)
        self.release(f"call:{s.call_id}")
        self.sessions.pop(s.call_id, None)
        self._record(s)
        self.log("ended", call=s.call_id, reason=s.end_reason)
