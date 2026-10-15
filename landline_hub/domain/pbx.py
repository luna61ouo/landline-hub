"""Auto-attendant: answer, ask for an extension, ring the phones behind it.

Pure state machine.  The daemon feeds it inputs (key presses, answers,
hang-ups, prompt finished, time) and carries out the actions it returns.

Security invariant: a caller's key presses can only ever select an
extension or choose "keep waiting / go to the operator".  There is no
action that dials out, so the classic PBX toll-fraud trick (call in, then
punch through to an outside line) cannot be expressed here at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


# -------------------------------------------------------------- directory
@dataclass(frozen=True)
class Extension:
    ext: str
    devices: tuple[str, ...]


@dataclass(frozen=True)
class Directory:
    extensions: dict[str, Extension]
    operator: str | None

    def match(self, digits: str) -> Extension | None:
        return self.extensions.get(digits)

    def is_prefix(self, digits: str) -> bool:
        return any(e.startswith(digits) and e != digits for e in self.extensions)


def build_directory(entries: list[dict], operator: str | None) -> Directory:
    """Validate once at load time; a Directory that exists is a valid one.
    Extensions must be digits, unique and prefix-free ("1" and "10" cannot
    both exist, otherwise "1" would be ambiguous while the caller is typing)."""
    exts: dict[str, Extension] = {}
    for e in entries:
        ext = str(e.get("ext", ""))
        devices = tuple(e.get("devices") or ())
        if not re.fullmatch(r"\d{1,6}", ext):
            raise ValueError(f"extension must be 1-6 digits: {ext!r}")
        if ext in exts:
            raise ValueError(f"duplicate extension: {ext}")
        if not devices:
            raise ValueError(f"extension {ext} has no devices")
        exts[ext] = Extension(ext, devices)
    for a in exts:
        for b in exts:
            if a != b and b.startswith(a):
                raise ValueError(f"extension {a} is a prefix of {b}")
    if operator is not None and operator not in exts:
        raise ValueError(f"operator extension {operator} is not in the directory")
    return Directory(exts, operator)


@dataclass(frozen=True)
class Timers:
    digit_timeout: float = 8.0      # silence while waiting for key presses
    ring_sec: float = 20.0          # one round of ringing an extension
    choice_timeout: float = 8.0     # "press 1 to keep waiting, 0 for the operator"
    farewell_sec: float = 15.0      # safety net if "prompt finished" never arrives
    max_retries: int = 2            # wrong / unknown extensions before giving up
    max_wait_rounds: int = 2        # how many times the caller may choose to keep waiting


# -------------------------------------------------------------- prompts & actions
class Prompt(Enum):
    GREETING = "greeting"                   # "Please enter the extension number"
    INVALID = "invalid"                     # "That extension does not exist"
    TRANSFERRING = "transferring"           # "Connecting you now"
    WAIT_OR_OPERATOR = "wait_or_operator"   # "Press 1 to keep waiting, 0 for the operator"
    NO_ANSWER = "no_answer"                 # "Nobody is available, please call again later"


@dataclass(frozen=True)
class Play:
    prompt: Prompt

@dataclass(frozen=True)
class Ring:
    devices: tuple[str, ...]

@dataclass(frozen=True)
class StopRinging:
    pass

@dataclass(frozen=True)
class Bridge:
    device: str

@dataclass(frozen=True)
class Hangup:
    pass

# Deliberately no Dial action.  See module docstring.
Action = Union[Play, Ring, StopRinging, Bridge, Hangup]
ACTION_TYPES = (Play, Ring, StopRinging, Bridge, Hangup)


# -------------------------------------------------------------- inputs
@dataclass(frozen=True)
class Digit:
    key: str

@dataclass(frozen=True)
class HandsetAnswered:
    device: str

@dataclass(frozen=True)
class CallerHungUp:
    pass

@dataclass(frozen=True)
class PromptFinished:
    pass

@dataclass(frozen=True)
class Tick:
    pass

Input = Union[Digit, HandsetAnswered, CallerHungUp, PromptFinished, Tick]


# -------------------------------------------------------------- states
@dataclass(frozen=True)
class Collecting:
    buffer: str
    retries: int
    deadline: float

@dataclass(frozen=True)
class RingingExt:
    ext: str
    devices: tuple[str, ...]
    deadline: float
    rounds: int = 1
    is_operator: bool = False

@dataclass(frozen=True)
class Choosing:
    ext: str
    devices: tuple[str, ...]
    deadline: float
    rounds: int

@dataclass(frozen=True)
class Farewell:
    deadline: float

@dataclass(frozen=True)
class Connected:
    device: str

@dataclass(frozen=True)
class Ended:
    pass

State = Union[Collecting, RingingExt, Choosing, Farewell, Connected, Ended]
Result = tuple[State, list[Action]]


@dataclass(frozen=True)
class Pbx:
    directory: Directory
    timers: Timers = field(default_factory=Timers)

    # -- entry --
    def start(self, now: float) -> Result:
        """The call has just been picked up."""
        return Collecting("", 0, now + self.timers.digit_timeout), [Play(Prompt.GREETING)]

    # -- helpers --
    def _ring(self, ext: Extension, now: float, rounds: int = 1) -> Result:
        is_op = ext.ext == self.directory.operator
        return (RingingExt(ext.ext, ext.devices, now + self.timers.ring_sec, rounds, is_op),
                [Play(Prompt.TRANSFERRING), Ring(ext.devices)])

    def _to_operator(self, now: float, pre: list[Action]) -> Result:
        op = self.directory.operator
        if op is None:
            return Farewell(now + self.timers.farewell_sec), pre + [Play(Prompt.NO_ANSWER)]
        state, actions = self._ring(self.directory.extensions[op], now)
        return state, pre + actions

    def _invalid(self, s: Collecting, now: float) -> Result:
        if s.retries + 1 > self.timers.max_retries:
            return self._to_operator(now, [])
        return Collecting("", s.retries + 1, now + self.timers.digit_timeout), [Play(Prompt.INVALID)]

    # -- transition --
    def step(self, s: State, i: Input, now: float) -> Result:
        if isinstance(s, Ended):
            return s, []
        if isinstance(i, CallerHungUp):
            return Ended(), ([StopRinging()] if isinstance(s, RingingExt) else [])

        if isinstance(s, Collecting):
            if isinstance(i, Digit):
                if i.key == "#":
                    ext = self.directory.match(s.buffer)
                    return self._ring(ext, now) if ext else self._invalid(s, now)
                if not i.key.isdigit():
                    return s, []
                buf = s.buffer + i.key
                ext = self.directory.match(buf)
                if ext:
                    return self._ring(ext, now)
                if self.directory.is_prefix(buf):
                    return Collecting(buf, s.retries, now + self.timers.digit_timeout), []
                return self._invalid(s, now)
            if isinstance(i, Tick) and now >= s.deadline:
                if s.buffer:
                    return self._invalid(s, now)
                return self._to_operator(now, [])     # caller pressed nothing
            return s, []

        if isinstance(s, RingingExt):
            if isinstance(i, HandsetAnswered) and i.device in s.devices:
                return Connected(i.device), [StopRinging(), Bridge(i.device)]
            if isinstance(i, Tick) and now >= s.deadline:
                if s.is_operator:
                    return Farewell(now + self.timers.farewell_sec), [StopRinging(), Play(Prompt.NO_ANSWER)]
                if s.rounds >= self.timers.max_wait_rounds:
                    return self._to_operator(now, [StopRinging()])
                return (Choosing(s.ext, s.devices, now + self.timers.choice_timeout, s.rounds),
                        [StopRinging(), Play(Prompt.WAIT_OR_OPERATOR)])
            return s, []

        if isinstance(s, Choosing):
            if isinstance(i, Digit) and i.key == "1":
                ext = self.directory.extensions[s.ext]
                state, actions = self._ring(ext, now, s.rounds + 1)
                return state, actions[1:]              # no "connecting you" again, just ring
            if (isinstance(i, Digit) and i.key == "0") or (isinstance(i, Tick) and now >= s.deadline):
                return self._to_operator(now, [])
            return s, []

        if isinstance(s, Farewell):
            if isinstance(i, PromptFinished) or (isinstance(i, Tick) and now >= s.deadline):
                return Ended(), [Hangup()]
            return s, []

        if isinstance(s, Connected):
            return s, []    # key presses during a conversation are just audio

        return s, []
