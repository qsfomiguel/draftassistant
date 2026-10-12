"""Lineup slot fitting: can a roster of players fill the league's starting slots?"""
from __future__ import annotations

from .constants import BENCH_SLOT, IR_SLOT
from .models import Player


def starting_slots(lineup_slots: dict[int, int]) -> list[int]:
    return [slot for slot, n in sorted(lineup_slots.items())
            if slot not in (BENCH_SLOT, IR_SLOT) for _ in range(n)]


def _match(players: list[Player], slots: list[int]) -> list[int | None]:
    """Max bipartite matching of players to starting slots; returns the player index per slot."""
    slot_owner: list[int | None] = [None] * len(slots)

    def assign(pi: int, seen: set[int]) -> bool:
        for si, slot in enumerate(slots):
            if si in seen or slot not in players[pi].eligible_slots:
                continue
            seen.add(si)
            if slot_owner[si] is None or assign(slot_owner[si], seen):
                slot_owner[si] = pi
                return True
        return False

    for pi in range(len(players)):
        assign(pi, set())
    return slot_owner


def max_starters(players: list[Player], slots: list[int]) -> int:
    return sum(owner is not None for owner in _match(players, slots))


def fits_starting(roster: list[Player], candidate: Player, slots: list[int]) -> bool:
    return max_starters(roster + [candidate], slots) > max_starters(roster, slots)


def open_slots(roster: list[Player], slots: list[int]) -> list[int]:
    return [slots[si] for si, owner in enumerate(_match(roster, slots)) if owner is None]
