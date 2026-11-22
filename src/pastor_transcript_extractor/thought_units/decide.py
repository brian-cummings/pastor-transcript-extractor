"""Truth table and chunking rule: code decides from Jev's probabilities. Constants are fixed in advance and never tuned."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .candidates import LOOK_AHEAD, Candidate, Piece

HIGH, LOW = 0.7, 0.3
MAX_UNIT_CHARACTERS = 2304
MIN_UNIT_PIECES = 2


def outcome(q1: float, q2: float) -> str:
    """cut / no_cut / unsettled; every combination has an outcome (spec section 4)."""
    if q1 >= HIGH or q2 <= LOW:
        return 'no_cut'
    if q1 <= LOW and q2 >= HIGH:
        return 'cut'
    return 'unsettled'


def resumption(q3_by_skip: Mapping[int, float]) -> tuple[str, int | None]:
    """('aside', skip) at the smallest skip with Q3 >= HIGH; ('unsettled', None) when only mid values occur; else ('break', None)."""
    for skip in sorted(q3_by_skip):
        if q3_by_skip[skip] >= HIGH:
            return 'aside', skip
    if any(LOW < value < HIGH for value in q3_by_skip.values()):
        return 'unsettled', None
    return 'break', None


@dataclass
class Unit:
    first: int                      # first piece index
    last: int                       # last piece index
    asides: list[tuple[int, int]] = field(default_factory=list)  # piece ranges that were merged as asides


def build_units(piece_count: int, pieces: Sequence[Piece], candidate_list: Sequence[Candidate], q2: Mapping[int, float],
                outcomes: Mapping[int, str], asides: Mapping[int, int]) -> list[Unit]:
    """Cut at 'cut' outcomes (not inside a merged aside), split oversize units at the highest Q2, merge undersize units.

    `asides[i] = skip` means the boundaries i .. i+skip are removed (the skipped pieces are an aside and the thought resumes).
    """
    cuts: set[int] = set()
    removed: set[int] = set()
    aside_ranges: dict[int, tuple[int, int]] = {}
    for index in sorted(asides):
        if index in removed:
            continue
        skip = asides[index]
        removed.update(range(index, index + skip + 1))
        aside_ranges[index] = (index + 1, index + skip)
    for candidate in candidate_list:
        if outcomes.get(candidate.index) == 'cut' and candidate.index not in removed:
            cuts.add(candidate.index)

    def units_from(cut_set: set[int]) -> list[Unit]:
        units, first = [], 0
        for index in sorted(cut_set) + [piece_count - 1]:
            units.append(Unit(first, index, [rng for start, rng in aside_ranges.items() if first <= start <= index]))
            first = index + 1
        return [unit for unit in units if unit.first <= unit.last]

    size = lambda unit: pieces[unit.last].end - pieces[unit.first].start
    split = True
    while split:
        split = False
        for unit in units_from(cuts):
            if size(unit) > MAX_UNIT_CHARACTERS:
                inside = [c.index for c in candidate_list if unit.first <= c.index < unit.last and c.index not in cuts and c.index not in removed]
                if inside:
                    cuts.add(max(inside, key=lambda i: (q2.get(i, 0.0), -i)))
                    split = True
                    break
    units = units_from(cuts)
    changed = True
    while changed:
        changed = False
        for number, unit in enumerate(units):
            if unit.last - unit.first + 1 >= MIN_UNIT_PIECES or len(units) == 1:
                continue
            left = q2.get(unit.first - 1, 1.0) if number else None   # Q2 at the boundary before this unit
            right = q2.get(unit.last, 1.0) if number < len(units) - 1 else None
            options = [(value, side) for value, side in ((left, 'left'), (right, 'right')) if value is not None]
            for value, side in sorted(options):  # the weaker boundary first
                other = units[number - 1] if side == 'left' else units[number + 1]
                if size(Unit(min(unit.first, other.first), max(unit.last, other.last))) <= MAX_UNIT_CHARACTERS:
                    cuts.discard(unit.first - 1 if side == 'left' else unit.last)
                    changed = True
                    break
            if changed:
                units = units_from(cuts)
                break
    return units
