"""Incoming calls on the landline: pure state machine.

Input: gateway signals (already translated by a gateway adapter) plus the
current time.  Output: new state and the events to publish.  Nothing here
knows which gateway hardware is in use, and nothing reads a clock.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Union

ABANDON_AFTER = 7.0   # seconds after the last ring with no new ring = caller gave up


# -- signals (from the gateway adapter) --
@dataclass(frozen=True)
class CallerId:
    number: str

@dataclass(frozen=True)
class RingStart:
    pass

@dataclass(frozen=True)
class RingStop:
    pass

@dataclass(frozen=True)
class LineSeized:       # the line went off-hook (we, or the gateway, picked up)
    pass

@dataclass(frozen=True)
class LineReleased:     # back on-hook
    pass

Signal = Union[CallerId, RingStart, RingStop, LineSeized, LineReleased]


# -- states --
@dataclass(frozen=True)
class Idle:
    pass

@dataclass(frozen=True)
class Ringing:
    call_id: str
    started: float
    number: str | None
    rings: int
    last_activity: float

@dataclass(frozen=True)
class Answered:
    call_id: str
    started: float
    number: str | None
    rings: int
    answered_at: float

State = Union[Idle, Ringing, Answered]


def event(kind: str, call, now: float, **extra) -> dict:
    return {"type": kind, "call_id": call.call_id, "number": call.number, "rings": call.rings,
            "started": call.started, "at": now, **extra}


def step(state: State, signal: Signal, now: float, new_id: Callable[[], str]) -> tuple[State, list[dict]]:
    if isinstance(state, Idle):
        if isinstance(signal, (CallerId, RingStart)):
            number = signal.number if isinstance(signal, CallerId) else None
            call = Ringing(new_id(), now, number, 1 if isinstance(signal, RingStart) else 0, now)
            return call, [event("incoming", call, now)]
        return state, []

    if isinstance(state, Ringing):
        if isinstance(signal, CallerId):
            call = replace(state, number=signal.number, last_activity=now)
            return call, ([event("caller_id", call, now)] if signal.number != state.number else [])
        if isinstance(signal, RingStart):
            call = replace(state, rings=state.rings + 1, last_activity=now)
            return call, [event("ring", call, now)]
        if isinstance(signal, RingStop):
            return replace(state, last_activity=now), []
        if isinstance(signal, LineSeized):
            call = Answered(state.call_id, state.started, state.number, state.rings, now)
            return call, [event("answered", call, now)]
        if isinstance(signal, LineReleased):
            return Idle(), [event("ended", state, now, result="missed")]
        return state, []

    if isinstance(state, Answered):
        if isinstance(signal, LineReleased):
            return Idle(), [event("ended", state, now, result="answered",
                                  talk_sec=round(now - state.answered_at, 1))]
        return state, []

    return state, []


def tick(state: State, now: float) -> tuple[State, list[dict]]:
    """Time alone moves the state forward: the caller gave up."""
    if isinstance(state, Ringing) and now - state.last_activity > ABANDON_AFTER:
        return Idle(), [event("ended", state, now, result="missed")]
    return state, []
