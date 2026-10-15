"""Phone numbers: normalize once at the boundary, then classify.

Everything here is pure. A `DialNumber` can only be produced by `parse()`,
so code that receives one never has to re-check it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    REGULAR = "regular"        # ordinary landline / mobile number
    PREMIUM = "premium"        # pay-per-call numbers
    EMERGENCY = "emergency"    # police, fire, ambulance


@dataclass(frozen=True)
class DialNumber:
    digits: str
    kind: Kind


@dataclass(frozen=True)
class Rejected:
    raw: str
    reason: str


def normalize(raw: str, country_code: str = "886") -> str:
    """Strip everything but digits and turn an international prefix into a
    national one.  "+886 2-1234-5678" -> "0212345678".

    Separators and trailing symbols are dropped on purpose: "110#", "(110)" and
    "+886110" must all end up as "110", otherwise a string comparison against
    the emergency list can be bypassed.
    """
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("00" + country_code):
        d = d[2:]
    if d.startswith(country_code):
        d = "0" + d[len(country_code):]
    stripped = d.lstrip("0")
    if 0 < len(stripped) <= 4:          # short codes never carry a trunk prefix
        return stripped
    return d


class NumberPolicy:
    """Country rules. Subclass for another country."""

    country_code = "886"
    emergency: frozenset[str] = frozenset()
    regular = re.compile(r"$^")
    premium_prefixes: tuple[str, ...] = ()

    def parse(self, raw: str) -> DialNumber | Rejected:
        d = normalize(raw, self.country_code)
        if d in self.emergency:
            return DialNumber(d, Kind.EMERGENCY)
        if not self.regular.fullmatch(d):
            return Rejected(raw, "not a dialable number")
        if d.startswith(self.premium_prefixes):
            return DialNumber(d, Kind.PREMIUM)
        return DialNumber(d, Kind.REGULAR)


class TaiwanPolicy(NumberPolicy):
    country_code = "886"
    emergency = frozenset({"110", "112", "119"})
    regular = re.compile(r"0\d{7,9}")
    premium_prefixes = ("0204", "0209")


POLICIES = {"tw": TaiwanPolicy}
