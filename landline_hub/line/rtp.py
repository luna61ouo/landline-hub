"""G.711 RTP stream: 20 ms frames in and out."""
from __future__ import annotations

import asyncio
import random
import struct
import time

from ..audio import FRAME_BYTES, audioop

MAX_QUEUE_SEC = 60.0     # safety cap only; a voice model may queue many seconds of speech


class RtpStream:
    """audio_in: Queue of 20 ms 8 kHz PCM16 chunks from the far end.
    play(pcm) queues our audio; clear() drops what has not been sent yet."""

    def __init__(self, payload_type: int, allowed_source: str | None = None):
        self.pt = payload_type if payload_type in (0, 8) else 0
        self.allowed_source = allowed_source
        self.audio_in: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
        self._out = bytearray()
        self.transport = None
        self.dst = None
        self._task = None

    def on_packet(self, data: bytes, addr) -> None:
        if len(data) < 12 or (self.allowed_source and addr[0] != self.allowed_source):
            return
        cc, ext = data[0] & 0x0F, data[0] & 0x10
        pt = data[1] & 0x7F
        off = 12 + 4 * cc
        if ext and len(data) >= off + 4:
            off += 4 + 4 * struct.unpack("!H", data[off + 2:off + 4])[0]
        payload = data[off:]
        if pt == 0:
            pcm = audioop.ulaw2lin(payload, 2)
        elif pt == 8:
            pcm = audioop.alaw2lin(payload, 2)
        else:
            return
        try:
            self.audio_in.put_nowait(pcm)
        except asyncio.QueueFull:
            pass

    def play(self, pcm8: bytes) -> None:
        self._out += pcm8
        limit = int(MAX_QUEUE_SEC * 16000)
        if len(self._out) > limit:              # runaway producer: keep the newest audio
            del self._out[:len(self._out) - limit]

    def clear(self) -> None:
        self._out.clear()

    def queued_sec(self) -> float:
        return len(self._out) / 16000

    def start(self, transport, dst) -> None:
        self.transport, self.dst = transport, dst
        self._task = asyncio.create_task(self._sender())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self.transport:
            self.transport.close()

    async def _sender(self) -> None:
        seq, ts, ssrc = random.randint(0, 65535), random.randint(0, 2**31), random.randint(0, 2**31)
        enc = audioop.lin2ulaw if self.pt == 0 else audioop.lin2alaw
        nxt = time.monotonic()
        while True:
            if len(self._out) >= FRAME_BYTES:
                frame = bytes(self._out[:FRAME_BYTES]); del self._out[:FRAME_BYTES]
            elif self._out:
                frame = bytes(self._out).ljust(FRAME_BYTES, b"\0"); self._out.clear()
            else:
                frame = bytes(FRAME_BYTES)
            hdr = struct.pack("!BBHII", 0x80, self.pt, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc)
            self.transport.sendto(hdr + enc(frame, 2), self.dst)
            seq += 1
            ts += 160
            nxt += 0.02
            await asyncio.sleep(max(0, nxt - time.monotonic()))
