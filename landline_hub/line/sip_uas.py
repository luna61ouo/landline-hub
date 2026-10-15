"""Minimal SIP user agent server: receives calls the gateway forwards to us.

Only the configured gateway may talk to it.  An INVITE becomes an
`InboundSip` that rings (180) until the hub calls accept() or reject().
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Awaitable, Callable

from .rtp import RtpStream
from .sip_common import Datagram, local_ip_for, parse, rand, sdp


class InboundSip:
    def __init__(self, uas: "SipServer", h: dict, addr, body: str):
        self.uas, self.addr, self.h = uas, addr, h
        self.call_id = h["call-id"][0]
        self.from_hdr, self.to_hdr = h["from"][0], h["to"][0]
        self.cseq_invite = h["cseq"][0]
        self.my_tag = rand(8)
        m = re.search(r"<([^>]+)>", h.get("contact", [""])[0])
        self.remote_target = m.group(1) if m else f"sip:{addr[0]}:{addr[1]}"
        m = re.search(r"sip:([^@>;]+)@", self.from_hdr)
        self.number = m.group(1) if m else None
        c = re.search(r"c=IN IP4 (\S+)", body)
        mm = re.search(r"m=audio (\d+) RTP/AVP ([\d ]+)", body)
        self.rtp_dst = (c.group(1) if c else addr[0], int(mm.group(1)) if mm else 0)
        offered = [int(x) for x in mm.group(2).split()] if mm else [0]
        self.rtp = RtpStream(next((p for p in offered if p in (0, 8)), 0), allowed_source=uas.gateway_ip)
        self.ended = asyncio.Event()
        self.ended_by: str | None = None
        self.answered_at: float | None = None
        self.acked = False
        self.cseq = 1
        self._tasks: list[asyncio.Task] = []

    # -- line interface --
    @property
    def audio_in(self) -> asyncio.Queue:
        return self.rtp.audio_in

    def play(self, pcm8: bytes) -> None:
        self.rtp.play(pcm8)

    def clear(self) -> None:
        self.rtp.clear()

    def queued_sec(self) -> float:
        return self.rtp.queued_sec()

    # -- signalling --
    def _resp(self, code: int, reason: str, h: dict | None = None, body: str = "", to_tag: bool = True) -> None:
        h = h or self.h
        to = h["to"][0] + (f";tag={self.my_tag}" if to_tag and "tag=" not in h["to"][0] else "")
        lines = [f"SIP/2.0 {code} {reason}"] + [f"Via: {v}" for v in h.get("via", [])] + [
            f"From: {h['from'][0]}", f"To: {to}", f"Call-ID: {h['call-id'][0]}", f"CSeq: {h['cseq'][0]}",
            f"Contact: <sip:hub@{self.uas.lip}:{self.uas.sip_port}>", f"User-Agent: {self.uas.ua}"]
        if body:
            lines.append("Content-Type: application/sdp")
        lines.append(f"Content-Length: {len(body.encode())}")
        self.uas.send(("\r\n".join(lines) + "\r\n\r\n" + body).encode(), self.addr)

    async def accept(self) -> None:
        if self.ended.is_set() or self.answered_at:
            return
        loop = asyncio.get_running_loop()
        transport, port = None, None
        for p in self.uas.rtp_ports:
            try:
                transport, _ = await loop.create_datagram_endpoint(lambda: Datagram(self.rtp.on_packet),
                                                                   local_addr=("0.0.0.0", p))
                port = p
                break
            except OSError:
                continue
        if transport is None:
            raise RuntimeError("no free RTP port")
        self._sdp = sdp(self.uas.lip, port, [self.rtp.pt])
        self._resp(200, "OK", body=self._sdp)
        self.answered_at = time.time()
        self.rtp.start(transport, self.rtp_dst)
        self._tasks.append(asyncio.create_task(self._resend_ok()))

    async def _resend_ok(self) -> None:
        for wait in (0.5, 1, 2, 4):
            await asyncio.sleep(wait)
            if self.acked or self.ended.is_set():
                return
            self._resp(200, "OK", body=self._sdp)

    def reject(self, code: int = 486, reason: str = "Busy Here") -> None:
        if self.ended.is_set():
            return
        self._resp(code, reason)
        self._finish("rejected")

    async def hangup(self) -> None:
        if self.ended.is_set():
            return
        if not self.answered_at:
            self.reject(480, "Temporarily Unavailable")
            return
        self.cseq += 1
        frm = self.to_hdr if "tag=" in self.to_hdr else f"{self.to_hdr};tag={self.my_tag}"
        req = [f"BYE {self.remote_target} SIP/2.0",
               f"Via: SIP/2.0/UDP {self.uas.lip}:{self.uas.sip_port};branch=z9hG4bK{rand()};rport",
               "Max-Forwards: 70", f"From: {frm}", f"To: {self.from_hdr}", f"Call-ID: {self.call_id}",
               f"CSeq: {self.cseq + 100} BYE", f"User-Agent: {self.uas.ua}", "Content-Length: 0"]
        self.uas.send(("\r\n".join(req) + "\r\n\r\n").encode(), self.addr)
        self._finish("local")

    def _finish(self, by: str) -> None:
        if self.ended.is_set():
            return
        self.ended_by = by
        self.ended.set()
        for t in self._tasks:
            t.cancel()
        self.rtp.stop()
        self.uas.calls.pop(self.call_id, None)


class SipServer:
    def __init__(self, gateway_ip: str, on_invite: Callable[[InboundSip], Awaitable[None]],
                 sip_port: int = 5090, rtp_ports=range(40100, 40200, 2), log=None, user_agent: str = "landline-hub"):
        self.gateway_ip = gateway_ip
        self.on_invite = on_invite
        self.sip_port, self.rtp_ports = sip_port, rtp_ports
        self.log = log or (lambda *a, **k: None)
        self.ua = user_agent
        self.calls: dict[str, InboundSip] = {}
        self.lip = local_ip_for(gateway_ip)

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.t, _ = await loop.create_datagram_endpoint(lambda: Datagram(self._on_sip),
                                                         local_addr=("0.0.0.0", self.sip_port))

    def close(self) -> None:
        self.t.close()

    def send(self, data: bytes, addr) -> None:
        self.t.sendto(data, addr)

    def _on_sip(self, data: bytes, addr) -> None:
        if addr[0] != self.gateway_ip:
            return                                   # only our gateway may talk to us
        try:
            first, h, body = parse(data)
        except Exception:
            return
        if first.startswith("SIP/2.0") or "call-id" not in h:
            return
        method = first.split(" ", 1)[0]
        cid = h["call-id"][0]
        call = self.calls.get(cid)
        if method == "INVITE":
            if call:
                return                               # retransmission
            call = InboundSip(self, h, addr, body)
            self.calls[cid] = call
            call._resp(100, "Trying", to_tag=False)
            call._resp(180, "Ringing")
            self.log("uas_invite", number=call.number)
            asyncio.ensure_future(self.on_invite(call))
        elif method == "ACK" and call:
            call.acked = True
        elif method == "BYE":
            if call:
                call._resp(200, "OK", h)
                call._finish("remote")
            else:
                self.send(f"SIP/2.0 481 Call Does Not Exist\r\nCall-ID: {cid}\r\nContent-Length: 0\r\n\r\n".encode(), addr)
        elif method == "CANCEL" and call:
            call._resp(200, "OK", h)
            call._resp(487, "Request Terminated", {**h, "cseq": [call.cseq_invite]})
            call._finish("remote_cancel")
        elif method == "OPTIONS":
            lines = ["SIP/2.0 200 OK"] + [f"Via: {v}" for v in h.get("via", [])] + [
                f"From: {h.get('from', [''])[0]}", f"To: {h.get('to', [''])[0]}", f"Call-ID: {cid}",
                f"CSeq: {h.get('cseq', [''])[0]}", "Content-Length: 0"]
            self.send(("\r\n".join(lines) + "\r\n\r\n").encode(), addr)
