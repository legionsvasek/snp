"""Точка входа: python main.py [--data data] [--overship]

Считает все кейсы из data/supply.csv + data/requests.csv и печатает план.
Некорректный кейс не валит весь расчёт: он помечается ошибкой, остальные считаются дальше.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from allocator import Request, Result, allocate_explained


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v  # оставляем как есть: валидатор в allocator пометит заявку


def load_cases(data_dir: str | Path):
    base = Path(data_dir)
    supply, requests = defaultdict(list), defaultdict(list)
    with open(base / "supply.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            supply[row["case_id"]].append(row)
    with open(base / "requests.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            requests[row["case_id"]].append(Request(
                row["request_id"], _num(row["priority"]), _num(row["demand_qty"]),
                _num(row["min_lot"]), _num(row["rounding_value"]), row["dest_location"]))
    return supply, requests


def solve_case(supply_rows: list[dict], reqs: list[Request], overship: bool = False):
    """-> (Result | None, ошибка | None). Ошибка уровня кейса: нет/дубль supply, плохой available_qty."""
    if not supply_rows:
        return None, "нет строки в supply.csv для этого кейса"
    if len(supply_rows) > 1:
        return None, f"{len(supply_rows)} строк supply для одного case_id (неоднозначно)"
    try:
        return allocate_explained(_num(supply_rows[0]["available_qty"]), reqs, overship=overship), None
    except ValueError as e:
        return None, str(e)


def _sort_key(r: Request):
    return (r.priority if isinstance(r.priority, int) else 10**9, r.request_id)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--overship", action="store_true", help="разрешить округление вверх за счёт свободного остатка")
    args = ap.parse_args(argv)

    supply, requests = load_cases(args.data)
    failed = 0
    for case_id in sorted(set(supply) | set(requests)):
        rows, reqs = supply.get(case_id, []), requests.get(case_id, [])
        res, err = solve_case(rows, reqs, args.overship)
        head = f"{case_id}"
        if rows:
            s = rows[0]
            head += f"  ({s['item']} @ {s['source_location']}, {s['period']})  доступно: {s['available_qty']}"
        print(head)
        if err:
            failed += 1
            print(f"  ОШИБКА КЕЙСА, пропущен: {err}\n")
            continue
        print(f"  {'request':<8}{'dest':<7}{'prio':>5}{'demand':>8}{'min_lot':>8}{'step':>6}{'отгрузка':>10}{'недопоставка':>14}")
        for r in sorted(reqs, key=_sort_key):
            got = res.plan[r.request_id]
            unmet = r.demand_qty - got if isinstance(r.demand_qty, int) and r.demand_qty > 0 else "-"
            print(f"  {r.request_id:<8}{r.dest_location:<7}{r.priority!s:>5}{r.demand_qty!s:>8}"
                  f"{r.min_lot!s:>8}{r.rounding_value!s:>6}{got:>10}{unmet!s:>14}")
        shipped = sum(res.plan.values())
        print(f"  распределено: {shipped}, нераспределённый остаток: {res.unallocated}")
        for msg in res.issues:
            print(f"  ! {msg}")
        print()
    if failed:
        print(f"Пропущено кейсов с ошибкой: {failed}")


if __name__ == "__main__":
    main()
