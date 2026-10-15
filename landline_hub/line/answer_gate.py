"""Answer detection for analog lines.

An analog line never tells the gateway "the callee picked up": the gateway
answers SIP as soon as the number is dialled.  So we listen.  Ringback tone
is held back; when a human voice appears, or the ringing pattern breaks,
the gate opens.

Calibrated on Taiwanese ringback (440+480 Hz, 1 s on / 3 s off, measured
1.0-1.1 s on and 2.9-3.0 s off).  Other countries need other constants.
Timing is counted in samples, so late packets do not stretch a ring.
"""
from __future__ import annotations

import array
import math

RATE = 8000
WIN = 800                     # 100 ms analysis window
SCAN = range(300, 710, 10)    # call-progress tones are made of two frequencies in this band
TONE_RATIO = 0.6              # >60% of the energy in two narrow peaks = a machine tone
SILENT_RMS = 150              # raw (un-amplified) level
RING_GAP = 2.95               # silence between two rings
MAX_RING = 1.4                # a ring lasts ~1.1 s; anything longer is not a ring
RING_GAP_OPEN = 3.4           # the next ring did not come = someone picked up
BURST_RMS = 300               # ring level 1100-1900, gaps 3-30
FULL_RING = 0.85              # a ring shorter than this (from the 2nd on) was cut by a pick-up
NO_TONE_OPEN = 4.5            # connected but never heard a ring = answered before ringback reached us


def _goertzel_power(x, f):
    k = 2 * math.cos(2 * math.pi * f / RATE)
    s1 = s2 = 0.0
    for v in x:
        s1, s2 = v + k * s1 - s2, s1
    return s1 * s1 + s2 * s2 - k * s1 * s2


def classify(pcm: bytes) -> tuple[str, float]:
    """'silent' / 'tone' / 'voice', plus rms."""
    x = array.array("h", pcm)
    n = len(x)
    if n == 0:
        return "silent", 0.0
    energy = sum(v * v for v in x)
    rms = math.sqrt(energy / n)
    if rms < SILENT_RMS:
        return "silent", rms
    pw = [_goertzel_power(x, f) / (n / 2) for f in SCAN]
    band = lambda i: sum(pw[max(0, i - 1):i + 2])  # noqa: E731
    i1 = max(range(len(pw)), key=pw.__getitem__)
    rest = [i for i in range(len(pw)) if abs(i - i1) > 3]
    i2 = max(rest, key=pw.__getitem__)
    return ("tone" if (band(i1) + band(i2)) / energy > TONE_RATIO else "voice"), rms


class AnswerGate:
    def __init__(self, log=None):
        self.buf = b""
        self.open = False
        self.reason = ""
        self.heard_tone = False
        self.voice_ms = 0          # is the callee talking at the moment the gate opens?
        self.t_start: float | None = None
        self.pending: list[bytes] = []   # last 300 ms before opening, so the "hello" is not lost
        self.samples = 0
        self.burst_start: float | None = None
        self.ring_end: float | None = None
        self.rings = 0
        self.log = log or (lambda *a, **k: None)

    def _t(self) -> float:
        return self.samples / RATE

    def _expected_ring(self, t: float) -> bool:
        return self.ring_end is not None and abs(t - self.ring_end - RING_GAP) <= 0.4

    def feed(self, pcm8: bytes, now: float) -> list[bytes] | None:
        """Feed a raw 20 ms chunk.  None while closed; on opening, the buffered chunks."""
        if self.open:
            return [pcm8]
        if self.t_start is None:
            self.t_start = now
        self.pending = (self.pending + [pcm8])[-15:]
        self.buf += pcm8
        while len(self.buf) >= WIN * 2:
            win, self.buf = self.buf[:WIN * 2], self.buf[WIN * 2:]
            kind, rms = classify(win)
            if kind == "tone" and not self.heard_tone:
                self.heard_tone = True
                self.log("gate_tone_first", at=round(now, 2))
            t0 = self._t()
            self.samples += WIN
            t = self._t()
            if rms >= BURST_RMS:
                self.voice_ms += 100
                if self.burst_start is None:
                    self.burst_start = t0
                dur = t - self.burst_start
                if self.ring_end is not None and not self._expected_ring(self.burst_start) and dur >= 0.2:
                    return self._open("callee_voice", now)
                if dur > MAX_RING:
                    return self._open("callee_voice", now)
            else:
                self.voice_ms = 0
                if self.burst_start is not None:
                    dur, self.burst_start = t0 - self.burst_start, None
                    if dur >= 0.2:
                        self.rings += 1
                        self.ring_end = t0
                        self.log("gate_ring", n=self.rings, dur=round(dur, 2))
                        if self.rings >= 2 and dur < FULL_RING:
                            return self._open("ring_cut", now)
                if self.ring_end is not None and t - self.ring_end > RING_GAP_OPEN:
                    return self._open("ringback_stopped", now)
        if self.ring_end is None and self.burst_start is None and now - self.t_start > NO_TONE_OPEN:
            return self._open("no_tone", now)
        return None

    def _open(self, reason: str, now: float) -> list[bytes]:
        self.open, self.reason = True, reason
        self.log("gate_open", reason=reason, at=round(now, 2))
        out, self.pending = self.pending, []
        return out
