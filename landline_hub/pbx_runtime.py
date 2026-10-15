"""Runs the auto-attendant state machine (domain/pbx.py) on a live call:
plays prompts, listens for key presses, rings phones, bridges the call."""
from __future__ import annotations

import asyncio
import time
import wave
from pathlib import Path

from .audio import audioop
from .domain import pbx as P
from .line import dtmf

TICK = 0.2


def load_prompt(prompts_dir: Path, prompt: P.Prompt) -> bytes:
    """8 kHz mono PCM16 for a prompt.  Any WAV is converted; a missing file
    becomes a short beep so the attendant still works while you record."""
    path = prompts_dir / f"{prompt.value}.wav"
    if not path.exists():
        return dtmf.tones("", 8000) + _beep()
    with wave.open(str(path)) as w:
        pcm = w.readframes(w.getnframes())
        width, ch, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if ch == 2:
        pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
    if rate != 8000:
        pcm = audioop.ratecv(pcm, 2, 1, rate, 8000, None)[0]
    return pcm


def _beep() -> bytes:
    import math, struct
    return b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 1000 * i / 8000))) for i in range(2400))


class Attendant:
    def __init__(self, hub, session):
        self.hub, self.s = hub, session
        conf = hub.cfg.pbx
        self.machine = P.Pbx(conf.directory, conf.timers)
        self.prompts = {p: load_prompt(conf.prompts_dir, p) for p in P.Prompt}
        self.detector = dtmf.Detector(8000)
        self.state: P.State = P.Ended()
        self.prompt_playing = False
        self.lock = asyncio.Lock()
        self.ringing: tuple[str, ...] = ()

    def now(self) -> float:
        return time.monotonic()

    async def feed(self, i: P.Input) -> None:
        async with self.lock:
            self.state, actions = self.machine.step(self.state, i, self.now())
            await self._do(actions)

    async def _do(self, actions) -> None:
        s, hub = self.s, self.hub
        for a in actions:
            if isinstance(a, P.Play):
                s.line.clear()
                s.line.play(self.prompts[a.prompt])
                self.prompt_playing = True
            elif isinstance(a, P.Ring):
                self.ringing = a.devices
                s.ring_targets = frozenset(a.devices)
                hub.emit({"type": "incoming", "call_id": s.call_id, "number": s.number, "extension": True},
                         lambda c, d=a.devices: c.client_id in d)
            elif isinstance(a, P.StopRinging):
                devices, self.ringing = self.ringing, ()
                s.ring_targets = frozenset()
                hub.emit({"type": "ring_stopped", "call_id": s.call_id}, lambda c, d=devices: c.client_id in d)
            elif isinstance(a, P.Bridge):
                s.line.clear()
                s.owner = a.device
                s.sink = None              # the phone's WebSocket attaches next
                hub.emit({"type": "answered", "call_id": s.call_id, "by": a.device},
                         lambda c: c.client_id == a.device)
            elif isinstance(a, P.Hangup):
                await s.line.hangup()
            else:  # pragma: no cover - the action set is closed
                raise AssertionError(a)

    async def handset_answered(self, device: str) -> dict:
        if device not in self.s.ring_targets:
            return {"ok": False, "error": "not_ringing_for_you"}
        await self.feed(P.HandsetAnswered(device))
        if isinstance(self.state, P.Connected) and self.state.device == device:
            self.s.state = "connected"
            return {"ok": True}
        return {"ok": False, "error": "already_answered"}

    def on_audio(self, pcm8: bytes) -> None:
        keys = self.detector.feed(pcm8)
        for k in keys:
            asyncio.ensure_future(self.feed(P.Digit(k)))

    async def run(self) -> None:
        s = self.s
        await s.line.accept()
        s.pbx = self
        s.sink = self.on_audio
        async with self.lock:
            self.state, actions = self.machine.start(self.now())
            await self._do(actions)
        pump = asyncio.create_task(self.hub._pump(s))
        try:
            while not s.line.ended.is_set() and not isinstance(self.state, (P.Ended, P.Connected)):
                await asyncio.sleep(TICK)
                if self.prompt_playing and s.line.queued_sec() == 0:
                    self.prompt_playing = False
                    await self.feed(P.PromptFinished())
                await self.feed(P.Tick())
            if s.line.ended.is_set() and not isinstance(self.state, P.Ended):
                await self.feed(P.CallerHungUp())
            await s.line.ended.wait()
        finally:
            pump.cancel()


async def run_attendant(hub, session) -> None:
    att = Attendant(hub, session)
    try:
        await att.run()
    finally:
        if not session.end_reason:
            session.end_reason = "answered" if session.owner else "unanswered"
        await hub._finish(session)
