"""SNP Heuristic: распределение дефицитного объёма одной позиции между заявками.

Правило (обоснование — в REPORT.md):
  1. Жёсткий приоритет между уровнями: уровень p получает объём раньше уровня p+1.
  2. Внутри уровня — пропорционально demand_qty (метод наибольших остатков),
     с «заливкой»: объём, который заявка не может принять из-за потолка, достаётся остальным.
  3. Заявка получает 0 либо число на сетке кратности в диапазоне [min_lot, demand_qty].
  4. Остаток, который сетка не даёт раздать внутри уровня, переходит на следующий уровень.
  5. Опция overship: после обслуживания ВСЕХ уровней остаток можно потратить на округление вверх.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import groupby
from typing import Iterable, NamedTuple


@dataclass(frozen=True)
class Request:
    request_id: str
    priority: int
    demand_qty: int
    min_lot: int = 0
    rounding_value: int = 0
    dest_location: str = ""


@dataclass
class Result:
    plan: dict[str, int]
    unallocated: int
    issues: list[str] = field(default_factory=list)


class _Item(NamedTuple):
    rid: str
    prio: int
    demand: int
    step: int  # шаг сетки: rounding_value (0 трактуем как 1)
    lo: int    # минимальная допустимая положительная отгрузка
    cap: int   # максимальная допустимая отгрузка: demand, округлённый ВНИЗ до сетки


def _ceil(x: int, step: int) -> int:
    return -(-x // step) * step


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _normalize(requests: list[Request]) -> tuple[list[_Item], list[str]]:
    """Исключает некорректные заявки (им достанется 0) и считает сетку. -> (items, issues)."""
    counts = Counter(r.request_id for r in requests)
    items, issues = [], []
    for r in requests:
        bad = None
        if counts[r.request_id] > 1:
            bad = "дублирующийся request_id (исключены все копии)"
        elif not all(_is_int(v) for v in (r.priority, r.demand_qty, r.min_lot, r.rounding_value)):
            bad = "нечисловое или нецелое значение в полях"
        elif r.priority < 1:
            bad = f"priority={r.priority} < 1"
        elif r.demand_qty < 0:
            bad = f"отрицательный спрос {r.demand_qty}"
        elif r.min_lot < 0 or r.rounding_value < 0:
            bad = "отрицательный min_lot или rounding_value"
        elif r.demand_qty == 0:
            bad = "нулевой спрос"
        if bad:
            issues.append(f"{r.request_id}: {bad} -> 0")
            continue
        if r.rounding_value == 0:
            issues.append(f"{r.request_id}: rounding_value=0 трактуем как 1 (кратности нет)")
        step = r.rounding_value or 1
        lo = _ceil(max(r.min_lot, 1), step)
        cap = r.demand_qty // step * step
        if lo > cap:
            issues.append(f"{r.request_id}: минимальная партия {lo} > потолка {cap} -> 0 (в основном проходе)")
        items.append(_Item(r.request_id, r.priority, r.demand_qty, step, lo, cap))
    return items, issues


def _pro_rata(supply: int, tier: list[_Item]) -> dict[str, Fraction]:
    """Доли пропорционально спросу; заявка не берёт больше потолка, излишек делят остальные."""
    share, free, rest = {}, list(tier), Fraction(supply)
    while free:
        w = sum(i.demand for i in free)
        capped = {i.rid for i in free if rest * i.demand / w >= i.cap}
        if not capped:
            share.update((i.rid, rest * i.demand / w) for i in free)
            break
        for i in free:
            if i.rid in capped:
                share[i.rid] = Fraction(i.cap)
                rest -= i.cap
        free = [i for i in free if i.rid not in capped]
    return share


def _fill_tier(supply: int, tier: list[_Item]) -> tuple[dict[str, int], int]:
    """Раздаёт supply внутри одного уровня приоритета. tier отсортирован по rid. -> (план, остаток)."""
    kept, dropped = list(tier), []
    while True:
        share = _pro_rata(supply, kept)
        alloc = {i.rid: int(share[i.rid] // i.step) * i.step for i in kept}
        below_min = [i for i in kept if alloc[i.rid] < i.lo]
        if not below_min:
            break
        dropped.append(below_min[-1])  # из недобравших min_lot выбывает последний в порядке ничьей
        kept.remove(below_min[-1])
    left = supply - sum(alloc.values())
    remainder = {i.rid: share[i.rid] - alloc[i.rid] for i in kept}
    alloc.update((i.rid, 0) for i in dropped)
    order = sorted(tier, key=lambda i: (-remainder.get(i.rid, 0), i.rid))  # наибольший остаток первым
    progress = True
    while progress:  # по кругу докладываем по одному шагу сетки, пока что-то помещается
        progress = False
        for i in order:
            inc = i.step if alloc[i.rid] else i.lo
            if inc <= left and alloc[i.rid] + inc <= i.cap:
                alloc[i.rid] += inc
                left -= inc
                progress = True
    return alloc, left


def _top_up(left: int, items: list[_Item], plan: dict[str, int]) -> int:
    """overship: тем, кто получил весь «нижний» потолок, добавляем округление вверх из свободного остатка."""
    for i in items:  # items уже отсортированы по (приоритет, rid)
        full = i.cap if i.lo <= i.cap else 0
        up = _ceil(i.demand, i.step)
        if plan[i.rid] == full and up > full and up >= i.lo and up - full <= left:
            left -= up - plan[i.rid]
            plan[i.rid] = up
    return left


def allocate_explained(available_qty: int, requests: Iterable[Request], *, overship: bool = False) -> Result:
    if not _is_int(available_qty) or available_qty < 0:
        raise ValueError(f"available_qty должен быть целым >= 0, получено {available_qty!r}")
    requests = list(requests)
    items, issues = _normalize(requests)
    items.sort(key=lambda i: (i.prio, i.rid))
    plan = {r.request_id: 0 for r in requests}
    left = available_qty
    for _, group in groupby(items, key=lambda i: i.prio):
        got, left = _fill_tier(left, [i for i in group if i.lo <= i.cap])
        plan.update(got)
    if overship:
        left = _top_up(left, items, plan)
    return Result(plan, left, issues)


def allocate(available_qty: int, requests: Iterable[Request], *, overship: bool = False) -> dict[str, int]:
    return allocate_explained(available_qty, requests, overship=overship).plan
