"""Small helpers shared by the SIP client and server."""
from __future__ import annotations

import asyncio
import random
import socket
import string

_ALNUM = string.ascii_lowercase + string.digits


def rand(n: int = 10) -> str:
    return "".join(random.choice(_ALNUM) for _ in range(n))


def local_ip_for(host: str) -> str:
    """The local address the OS would use to reach `host`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def parse(data: bytes) -> tuple[str, dict[str, list[str]], str]:
    text = data.decode("utf-8", "replace")
    head, _, body = text.partition("\r\n\r\n")
    lines = head.split("\r\n")
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers.setdefault(k.strip().lower(), []).append(v.strip())
    return lines[0], headers, body


class Datagram(asyncio.DatagramProtocol):
    def __init__(self, cb):
        self.cb = cb

    def datagram_received(self, data, addr):
        self.cb(data, addr)


def sdp(local_ip: str, rtp_port: int, payload_types: list[int], name: str = "landline-hub") -> str:
    maps = {0: "PCMU/8000", 8: "PCMA/8000"}
    pts = " ".join(str(p) for p in payload_types)
    rtpmap = "".join(f"a=rtpmap:{p} {maps[p]}\r\n" for p in payload_types if p in maps)
    return (f"v=0\r\no={name} 1 1 IN IP4 {local_ip}\r\ns={name}\r\nc=IN IP4 {local_ip}\r\nt=0 0\r\n"
            f"m=audio {rtp_port} RTP/AVP {pts}\r\n{rtpmap}a=ptime:20\r\na=sendrecv\r\n")
