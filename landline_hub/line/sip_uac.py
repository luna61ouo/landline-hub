"""Minimal SIP user agent client: ask a gateway to dial a number, then
carry G.711 audio.  Handles INVITE retransmission, CANCEL on ring timeout,
401/407 digest auth, BYE in both directions.

The hub decides *whether* a number may be dialled before this class is ever
created; this class only knows how to dial.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time

from .rtp import RtpStream
from .sip_common import Datagram, local_ip_for, parse, rand, sdp

T1 = 0.5
NO_RESPONSE_SEC = 4.0    # not even a 100/180 by then: the gateway is offline


class OutboundSip:
    def __init__(self, host: str, port: int, user: str | None = None, password: str | None = None,
                 sip_port: int = 0, ring_timeout: float = 35, log=None, user_agent: str = "landline-hub"):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.ring_timeout = ring_timeout
        self.log = log or (lambda *a, **k: None)
        self.ua = user_agent
        self.lip = local_ip_for(host)
        self.sip_port = sip_port
        self.call_id = f"{rand(16)}@{self.lip}"
        self.tag = rand(8)
        self.cseq = 1
        self.ended = asyncio.Event()
        self.ended_by: str | None = None
        self.fail_reason: str | None = None
        self.rtp: RtpStream | None = None
        self.number = ""
        self._resp: asyncio.Queue = asyncio.Queue()
        self._remote_tag = None
        self._remote_target = None
        self._tasks: list[asyncio.Task] = []
        self._bye_done = asyncio.Event()

    # -- audio passthrough (the line interface) --
    @property
    def audio_in(self) -> asyncio.Queue:
        return self.rtp.audio_in

    def play(self, pcm8: bytes) -> None:
        self.rtp.play(pcm8)

    def clear(self) -> None:
        self.rtp.clear()

    def queued_sec(self) -> float:
        return self.rtp.queued_sec() if self.rtp else 0.0

    # -- transport --
    async def _open(self) -> None:
        loop = asyncio.get_running_loop()
        self.sip_t, _ = await loop.create_datagram_endpoint(lambda: Datagram(self._on_sip), local_addr=("0.0.0.0", self.sip_port))
        self.sip_port = self.sip_t.get_extra_info("sockname")[1]
        self.rtp = RtpStream(0, allowed_source=None)
        self.rtp_t, _ = await loop.create_datagram_endpoint(lambda: Datagram(self.rtp.on_packet), local_addr=("0.0.0.0", 0))
        self.rtp_port = self.rtp_t.get_extra_info("sockname")[1]

    def _send(self, msg: str) -> None:
        self.sip_t.sendto(msg.encode(), (self.host, self.port))

    def _on_sip(self, data: bytes, addr) -> None:
        start, h, _body = parse(data)
        if start.startswith("SIP/2.0"):
            self._resp.put_nowait((int(start.split()[1]), h, _body))
            return
        method = start.split()[0]
        self.log("sip_in", method=method)
        if "via" not in h or "call-id" not in h:
            return
        ok = ["SIP/2.0 200 OK"] + [f"Via: {v}" for v in h.get("via", [])] + [
            f"From: {h['from'][0]}", f"To: {h['to'][0]}", f"Call-ID: {h['call-id'][0]}",
            f"CSeq: {h['cseq'][0]}", "Content-Length: 0"]
        self.sip_t.sendto(("\r\n".join(ok) + "\r\n\r\n").encode(), addr)
        if method == "BYE":
            self._finish("remote")

    def _req(self, method: str, uri: str, branch: str, extra=(), body: str = "", to_tag: bool = True) -> str:
        to = f"<sip:{self.number}@{self.host}:{self.port}>"
        if to_tag and self._remote_tag:
            to += f";tag={self._remote_tag}"
        lines = [f"{method} {uri} SIP/2.0",
                 f"Via: SIP/2.0/UDP {self.lip}:{self.sip_port};branch={branch};rport",
                 "Max-Forwards: 70",
                 f"From: <sip:hub@{self.lip}:{self.sip_port}>;tag={self.tag}",
                 f"To: {to}", f"Call-ID: {self.call_id}",
                 f"CSeq: {self.cseq} {method}",
                 f"Contact: <sip:hub@{self.lip}:{self.sip_port}>", f"User-Agent: {self.ua}", *extra]
        if body:
            lines.append("Content-Type: application/sdp")
        lines.append(f"Content-Length: {len(body)}")
        return "\r\n".join(lines) + "\r\n\r\n" + body

    def _digest(self, h, code: int, method: str, uri: str) -> str:
        hdr = (h.get("www-authenticate") or h.get("proxy-authenticate") or [""])[0]
        f = dict(re.findall(r'(\w+)="?([^",]+)"?', hdr))
        md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731  (SIP digest is MD5 by spec)
        ha1, ha2 = md5(f"{self.user}:{f.get('realm')}:{self.password}"), md5(f"{method}:{uri}")
        name = "Authorization" if code == 401 else "Proxy-Authorization"
        if "auth" in f.get("qop", ""):
            nc, cn = "00000001", rand(8)
            resp = md5(f"{ha1}:{f['nonce']}:{nc}:{cn}:auth:{ha2}")
            return (f'{name}: Digest username="{self.user}", realm="{f.get("realm")}", nonce="{f["nonce"]}", '
                    f'uri="{uri}", response="{resp}", algorithm=MD5, qop=auth, nc={nc}, cnonce="{cn}"')
        resp = md5(f"{ha1}:{f['nonce']}:{ha2}")
        return (f'{name}: Digest username="{self.user}", realm="{f.get("realm")}", nonce="{f["nonce"]}", '
                f'uri="{uri}", response="{resp}", algorithm=MD5')

    async def _transact(self, msg: str, timeout: float):
        """Send with UDP retransmission; return the final (code, headers, body) or (None, {}, "")."""
        self._send(msg)
        wait, deadline, provisional, t0 = T1, time.monotonic() + timeout, False, time.monotonic()
        while time.monotonic() < deadline:
            if not provisional and time.monotonic() - t0 > NO_RESPONSE_SEC:
                return None, {}, ""
            try:
                code, h, body = await asyncio.wait_for(self._resp.get(), timeout=wait)
            except asyncio.TimeoutError:
                if not provisional:
                    self._send(msg)
                    wait = min(wait * 2, 1.0)
                continue
            if code < 200:
                provisional, wait = True, 1.0
                self.log("sip_provisional", code=code)
                continue
            return code, h, body
        return None, {}, ""

    async def dial(self, number: str) -> bool:
        """True = the line is connected (for an analog line that does NOT mean the
        callee answered; see answer_gate).  False = see fail_reason."""
        self.number = re.sub(r"[^\d*#+]", "", number)
        await self._open()
        uri = f"sip:{self.number}@{self.host}:{self.port}"
        auth: tuple[str, ...] = ()
        h: dict = {}
        body = ""
        for attempt in range(2):
            branch = "z9hG4bK" + rand()
            invite = self._req("INVITE", uri, branch, auth, sdp(self.lip, self.rtp_port, [0, 8]), to_tag=False)
            self.log("sip_invite", attempt=attempt)
            try:
                code, h, body = await asyncio.wait_for(self._transact(invite, self.ring_timeout + 5),
                                                       timeout=self.ring_timeout)
            except asyncio.TimeoutError:
                cancel = self._req("CANCEL", uri, branch, (), "", to_tag=False)
                self._send(cancel)
                self.fail_reason = "no-answer"
                self._close_now()
                return False
            if code is None:
                self.fail_reason = "gateway-no-response"
                self._close_now()
                return False
            m = re.search(r"tag=([^;>\s]+)", h.get("to", [""])[0])
            self._remote_tag = m.group(1) if m else None
            if code in (401, 407) and self.user and attempt == 0:
                self._send(self._req("ACK", uri, branch))
                auth = (self._digest(h, code, "INVITE", uri),)
                self.cseq += 1
                self._remote_tag = None
                continue
            if code >= 300:
                self._send(self._req("ACK", uri, branch))
                self.fail_reason = str(code)
                self.log("sip_failed", code=code)
                self._close_now()
                return False
            break
        m = re.search(r"<([^>]+)>", h.get("contact", [""])[0])
        self._remote_target = m.group(1) if m else uri
        c = re.search(r"c=IN IP4 (\S+)", body)
        mm = re.search(r"m=audio (\d+) RTP/AVP ([\d ]+)", body)
        pt = int(mm.group(2).split()[0]) if mm else 0
        self.rtp.pt = pt if pt in (0, 8) else 0
        self._send(self._req("ACK", self._remote_target, "z9hG4bK" + rand()))
        dst = (c.group(1) if c else self.host, int(mm.group(1)) if mm else 0)
        self.rtp.start(self.rtp_t, dst)
        self.log("sip_connected", pt=self.rtp.pt)
        self._tasks = [asyncio.create_task(self._late_responses())]
        return True

    async def _late_responses(self) -> None:
        """Our ACK got lost and the 200 is retransmitted: ACK again."""
        while not self.ended.is_set():
            code, h, _ = await self._resp.get()
            cseq = h.get("cseq", [""])[0]
            if code == 200 and "INVITE" in cseq:
                self._send(self._req("ACK", self._remote_target, "z9hG4bK" + rand()))
            elif "BYE" in cseq:
                self._bye_done.set()

    async def hangup(self) -> None:
        if self.ended.is_set():
            return
        if self._remote_target is None:          # never connected
            self._finish("local")
            return
        self.cseq += 1
        bye = self._req("BYE", self._remote_target, "z9hG4bK" + rand())
        for wait in (0.5, 1, 2):
            self._send(bye)
            try:
                await asyncio.wait_for(self._bye_done.wait(), timeout=wait)
                break
            except asyncio.TimeoutError:
                pass
        self._finish("local")

    def _finish(self, by: str) -> None:
        if self.ended.is_set():
            return
        self.ended_by = by
        self.ended.set()
        for t in self._tasks:
            t.cancel()
        asyncio.get_running_loop().call_later(0.5, self._close_now)

    def _close_now(self) -> None:
        if self.rtp:
            self.rtp.stop()
        for name in ("sip_t", "rtp_t"):
            tr = getattr(self, name, None)
            if tr:
                tr.close()
