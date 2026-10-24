"""Answer detection for analog lines.

An analog line never tells the gateway "the callee picked up": the gateway
answers SIP as soon as the number is dialled.  So we listen.  Ringback tone
is held back; when a human voice appears, or the ringing pattern breaks,
the gate opens.

Calibrated on Taiwanese ringback (440+480 Hz, about 1 s on).  The silence
between rings is not the same everywhere: most lines measured 2.9-3.0 s,
but some exchanges ring 1.1 s on / 1.9 s off.  So the first gap may be
anything from RING_GAP_MIN to RING_GAP_MAX; once a gap has been measured,
the next rings must follow that same rhythm.  Other countries need other
constants.  Timing is counted in samples, so late packets do not stretch a ring.
"""
from __future__ import annotations

import array
import math

RATE = 8000
WIN = 800                     # 100 ms analysis window
SCAN = range(300, 710, 10)    # call-progress tones are made of two frequencies in this band
TONE_RATIO = 0.6              # >60% of the energy in two narrow peaks = a machine tone
SILENT_RMS = 150              # raw (un-amplified) level
RING_GAP_MIN = 1.6            # shortest silence between two rings we accept before the rhythm is known
RING_GAP_MAX = 3.4            # longest (also: no ring after this = someone picked up)
RING_GAP_SLACK = 0.4          # once the gap is measured, a ring must come within this of it
MAX_RING = 1.4                # a ring lasts ~1.1 s; anything longer is not a ring
BURST_RMS = 300               # ring level 1100-1900, gaps 3-30
FULL_RING = 0.85              # a ring shorter than this (from the 2nd on) was cut by a pick-up
NO_TONE_OPEN = 4.5            # connected but never heard a ring = answered before ringback reached us
# Opening on an inference (the next ring did not come / never heard one) can be wrong:
# 10-23 a slow exchange made the gate open while it was still ringing and the assistant
# played its whole greeting into the ringback.  So after such an opening we keep
# listening for a while; one whole ring-shaped burst of machine tone = it is still
# ringing, close again.  Only tone windows count, so the callee talking (or the
# assistant's echo) never looks like a ring.
VERIFY_SEC = 8.0              # keep checking this long after an inferred opening
VERIFY_REASONS = ("ringback_stopped", "no_tone")
RECALL_MIN, RECALL_MAX = 0.6, 1.4   # a resumed ring: this much continuous tone


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
        self.gap: float | None = None    # measured silence between rings, once known
        self.verify_until: float | None = None   # sample-clock time; set after an inferred opening
        self.tone_start: float | None = None
        self.recalled = 0                # times we closed again because it was still ringing
        self.log = log or (lambda *a, **k: None)

    def _t(self) -> float:
        return self.samples / RATE

    def _expected_ring(self, t: float) -> bool:
        if self.ring_end is None:
            return False
        gap = t - self.ring_end
        if self.gap is None:
            return RING_GAP_MIN <= gap <= RING_GAP_MAX
        return abs(gap - self.gap) <= RING_GAP_SLACK

    def _ring_overdue(self, t: float) -> bool:
        limit = RING_GAP_MAX if self.gap is None else min(RING_GAP_MAX, self.gap + RING_GAP_SLACK + 0.05)
        return t - self.ring_end > limit

    def feed(self, pcm8: bytes, now: float) -> list[bytes] | None:
        """Feed a raw 20 ms chunk.  None while closed; on opening, the buffered chunks.
        While open and verifying, a resumed ring closes the gate again (returns None,
        self.recalled goes up) - the caller must tell its client."""
        if self.open:
            if self.verify_until is None:
                return [pcm8]
            return None if self._verify(pcm8, now) else [pcm8]
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
                        if self.ring_end is not None and self.gap is None:
                            self.gap = t0 - dur - self.ring_end
                        self.rings += 1
                        self.ring_end = t0
                        self.log("gate_ring", n=self.rings, dur=round(dur, 2))
                        if self.rings >= 2 and dur < FULL_RING:
                            return self._open("ring_cut", now)
                if self.ring_end is not None and self._ring_overdue(t):
                    return self._open("ringback_stopped", now)
        if self.ring_end is None and self.burst_start is None and now - self.t_start > NO_TONE_OPEN:
            return self._open("no_tone", now)
        return None

    def _verify(self, pcm8: bytes, now: float) -> bool:
        """After an inferred opening: True = a ring came back, the gate is closed again."""
        self.buf += pcm8
        while len(self.buf) >= WIN * 2:
            win, self.buf = self.buf[:WIN * 2], self.buf[WIN * 2:]
            kind, rms = classify(win)
            t0 = self._t()
            self.samples += WIN
            if kind == "tone" and rms >= BURST_RMS:
                if self.tone_start is None:
                    self.tone_start = t0
                if self._t() - self.tone_start > RECALL_MAX:
                    self.tone_start = None          # too long for a ring (a fax, a held tone): ignore
            else:
                if self.tone_start is not None and RECALL_MIN <= t0 - self.tone_start <= RECALL_MAX:
                    return self._reclose(t0, now)
                self.tone_start = None
            if self._t() > self.verify_until:
                self.verify_until = None
                self.buf = b""
                self.log("gate_verified", at=round(now, 2))
                return False
        return False

    def _reclose(self, ring_end: float, now: float) -> bool:
        self.recalled += 1
        self.log("gate_recalled", after=self.reason, at=round(now, 2))
        self.open, self.reason, self.verify_until, self.tone_start = False, "", None, None
        self.rings += 1
        self.ring_end, self.burst_start, self.voice_ms, self.pending, self.buf = ring_end, None, 0, [], b""
        return True

    def _open(self, reason: str, now: float) -> list[bytes]:
        self.open, self.reason = True, reason
        if reason in VERIFY_REASONS and self.recalled < 3:
            self.verify_until = self._t() + VERIFY_SEC
        self.log("gate_open", reason=reason, at=round(now, 2))
        out, self.pending = self.pending, []
        return out
