"""Keep what the answer gate heard, so its decisions can be replayed later.

The gate holds the far end's audio back until it believes someone picked up,
so nothing downstream ever records the ringing itself.  When enabled, the hub
keeps the raw line audio of each outbound call from the moment the line is up
until the gate has settled (opened and finished verifying, plus a short tail),
together with every gate event on the same sample clock.

Off by default: it is the callee's line audio.  Files are deleted after
keep_days.  The number dialled is not stored, only the hub's call id.

  [answer_detection]
  keep_audio = true
  keep_days = 30

Replay a recording through the gate: tools/gate_replay.py.
"""
from __future__ import annotations

import json
import time
import wave
from pathlib import Path

RATE = 8000
TAIL_SEC = 2.0          # keep this much after the gate settles (the callee's first words)
MAX_SEC = 120.0         # a gate that never settles still stops recording here


class GateRecorder:
    def __init__(self, folder: Path, call_id: str):
        self.folder, self.call_id = Path(folder), call_id
        self.pcm = bytearray()
        self.events: list[dict] = []
        self.active = True
        self._stop_at: float | None = None

    def _t(self) -> float:
        return len(self.pcm) / 2 / RATE

    def feed(self, raw: bytes) -> None:
        if not self.active:
            return
        self.pcm += raw
        t = self._t()
        if (self._stop_at is not None and t >= self._stop_at) or t >= MAX_SEC:
            self.active = False

    def event(self, what: str, **fields) -> None:
        if self.active:
            self.events.append({"t": round(self._t(), 3), "what": what, **fields})

    def settled(self) -> None:
        """The gate is open and no longer verifying: record a short tail, then stop."""
        if self._stop_at is None:
            self._stop_at = self._t() + TAIL_SEC

    def save(self, end_reason: str) -> Path | None:
        if not self.pcm:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("%Y%m%d-%H%M%S-") + self.call_id
        with wave.open(str(self.folder / f"{stem}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(self.pcm))
        meta = {"call_id": self.call_id, "sec": round(self._t(), 2), "end_reason": end_reason,
                "events": self.events,
                # filled in by hand after listening: second the callee really picked up,
                # null = nobody answered, "?" = not labelled yet
                "label": {"answered_at": "?", "note": ""}}
        (self.folder / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.folder / f"{stem}.wav"


def prune(folder: Path, keep_days: float) -> int:
    """Delete recordings older than keep_days.  Returns how many files went."""
    folder = Path(folder)
    if not folder.is_dir():
        return 0
    cutoff, n = time.time() - keep_days * 86400, 0
    for f in folder.iterdir():
        if f.suffix in (".wav", ".json") and f.stat().st_mtime < cutoff:
            f.unlink()
            n += 1
    return n
