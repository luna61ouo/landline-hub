"""Who may dial what.  Pure: a client's grants come from configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .number import DialNumber, Kind


class ClientRole(Enum):
    HANDSET = "handset"   # a paired phone held by a person
    AGENT = "agent"       # a program (e.g. landline-agent); it brings its own approval


# A person holding a phone can call emergency services, like with any phone.
# A program cannot, unless the operator explicitly grants it.
DEFAULT_KINDS = {
    ClientRole.HANDSET: frozenset({Kind.REGULAR, Kind.EMERGENCY}),
    ClientRole.AGENT: frozenset({Kind.REGULAR}),
}


@dataclass(frozen=True)
class Client:
    client_id: str
    role: ClientRole
    extra_kinds: frozenset[Kind] = field(default_factory=frozenset)

    def dialable_kinds(self) -> frozenset[Kind]:
        return DEFAULT_KINDS[self.role] | self.extra_kinds


def may_dial(client: Client, number: DialNumber) -> bool:
    return number.kind in client.dialable_kinds()
