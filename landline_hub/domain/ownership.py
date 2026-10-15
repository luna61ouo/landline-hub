"""Who owns the single physical line right now.

One landline does one thing at a time: ring, carry a call, or dial out.
Every use goes through `claim()` so two users never collide on the wire.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class Free:
    pass

@dataclass(frozen=True)
class Taken:
    owner: str          # client id, or "incoming:<call_id>"
    purpose: str        # "incoming" | "outbound"
    since: float

LineState = Union[Free, Taken]


@dataclass(frozen=True)
class Granted:
    state: Taken

@dataclass(frozen=True)
class Busy:
    held_by: Taken


def claim(state: LineState, owner: str, purpose: str, now: float) -> Granted | Busy:
    if isinstance(state, Taken):
        return Busy(state)
    return Granted(Taken(owner, purpose, now))


def release(state: LineState, owner: str) -> LineState:
    """Only the owner can release; anyone else is a no-op."""
    if isinstance(state, Taken) and state.owner == owner:
        return Free()
    return state
