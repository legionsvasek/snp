"""Каждый тест: в docstring одна строка — что фиксирует / что сломается при изменении поведения."""
import random
from pathlib import Path

import pytest

from allocator import Request, _ceil, allocate, allocate_explained
from main import load_cases, solve_case

DATA = Path(__file__).resolve().parent.parent / "data"


def R(rid, prio, demand, min_lot=0, step=1):
    return Request(rid, prio, demand, min_lot, step)


# ---------- кейсы из CSV ----------

def _csv_case(case_id, overship=False):
    supply, requests = load_cases(DATA)
    res, err = solve_case(supply[case_id], requests[case_id], overship)
    assert err is None
    return res


def test_case01_rounding_never_exceeds_demand():
    """Фиксирует: 3x40 при кратности 25 и запасе 100 -> по 25, остаток 25 не раздаём; сломается, если округлять вверх по умолчанию."""
    res = _csv_case("CASE_01")
    assert res.plan == {"R-101": 25, "R-102": 25, "R-103": 25} and res.unallocated == 25


def test_case01_overship_spends_leftover():
    """Фиксирует: с overship остаток 25 уходит на округление вверх (50/25/25); сломается, если флаг перестанет что-либо делать."""
    res = _csv_case("CASE_01", overship=True)
    assert sorted(res.plan.values()) == [25, 25, 50] and res.unallocated == 0


def test_case02_min_lot_drops_last_and_remainder_goes_to_first():
    """Фиксирует: доля 25 < min_lot 30, поэтому последняя заявка выбывает, остальные 30/30/30 +10 первой; сломается, если вернуться к 'всем по 25 -> все 0'."""
    res = _csv_case("CASE_02")
    assert res.plan == {"R-201": 40, "R-202": 30, "R-203": 30, "R-204": 0} and res.unallocated == 0


def test_case03_bad_rows_get_zero_and_do_not_break_case():
    """Фиксирует: нулевой/отрицательный спрос -> 0 с пометкой, rounding=0 -> шаг 1, остаток идёт низшему приоритету; сломается, если мусор роняет кейс или съедает объём."""
    res = _csv_case("CASE_03")
    assert res.plan == {"R-301": 0, "R-302": 0, "R-303": 30, "R-304": 30}
    assert len(res.issues) == 3


def test_case04_result_independent_of_input_order():
    """Фиксирует: 97 на 5 равных заявок -> 20,20,19,19,19, а порядок строк на результат не влияет; сломается, если ничья решается порядком входа."""
    supply, requests = load_cases(DATA)
    base = allocate(97, requests["CASE_04"])
    assert base == {"R-401": 20, "R-402": 20, "R-403": 19, "R-404": 19, "R-405": 19}
    for seed in range(20):
        shuffled = requests["CASE_04"][:]
        random.Random(seed).shuffle(shuffled)
        assert allocate(97, shuffled) == base


def test_case05_abundant_supply_still_capped_by_floor_grid():
    """Фиксирует: при избытке 500 каждая заявка получает пол своей сетки (25/30/5), остаток 440; сломается, если ограничение 'не больше demand' пропадёт."""
    res = _csv_case("CASE_05")
    assert res.plan == {"R-501": 25, "R-502": 30, "R-503": 5} and res.unallocated == 440


def test_case06_infeasible_min_lot_and_leftover_to_lower_priority():
    """Фиксирует: min_lot 250 > demand -> заявка получает 0 (не 250); остаток 100 уходит приоритету 2 по сетке 7 (77); сломается, если min_lot перебивает demand."""
    res = _csv_case("CASE_06")
    assert res.plan == {"R-601": 100, "R-602": 0, "R-603": 77} and res.unallocated == 23


def test_case07_strict_priority_starves_lower_tiers():
    """Фиксирует: приоритет 1 забирает всё (100), низшие получают 0; сломается, если приоритет станет мягким весом."""
    assert _csv_case("CASE_07").plan == {"R-701": 100, "R-702": 0, "R-703": 0}


# ---------- собственные кейсы ----------

def test_own_water_filling_redistributes_capped_share():
    """Фиксирует: A (спрос 40, сетка 25 -> потолок 25) не может принять свою долю 28, излишек достаётся B (25/45); сломается, если излишек теряется (B получит 42)."""
    plan = allocate(70, [R("A", 1, 40, step=25), R("B", 1, 60)])
    assert plan == {"A": 25, "B": 45}


def test_own_rounding_leftover_flows_to_next_priority():
    """Фиксирует: неизрасходованный из-за сетки остаток приоритета 1 переходит приоритету 2 (25 / 75); сломается, если остаток считается потерянным."""
    plan = allocate(100, [R("A", 1, 40, step=25), R("B", 2, 100)])
    assert plan == {"A": 25, "B": 75}


def test_own_duplicate_request_ids_are_rejected():
    """Фиксирует: повтор request_id исключает все копии с пометкой, остальные считаются; сломается, если словарь ответа молча перезапишет одну из копий."""
    res = allocate_explained(100, [R("A", 1, 10), R("A", 1, 20), R("B", 1, 30)])
    assert res.plan == {"A": 0, "B": 30} and any("дублир" in m for m in res.issues)


def test_own_bad_supply_is_case_level_error():
    """Фиксирует: отрицательный available_qty — ValueError, а не тихий нулевой план; сломается, если ошибка данных маскируется под 'ничего нет'."""
    with pytest.raises(ValueError):
        allocate(-5, [R("A", 1, 10)])


def test_own_zero_supply_and_empty_requests():
    """Фиксирует: нулевой объём и пустой список заявок дают валидный пустой/нулевой план; сломается, если появится деление на ноль или исключение."""
    assert allocate(0, [R("A", 1, 10)]) == {"A": 0}
    assert allocate_explained(50, []).unallocated == 50


def test_own_non_integer_field_is_flagged_not_crashed():
    """Фиксирует: строка вместо числа в demand_qty исключает заявку, а не роняет расчёт; сломается, если нет проверки типов."""
    res = allocate_explained(50, [Request("A", 1, "abc", 0, 1), R("B", 1, 20)])
    assert res.plan == {"A": 0, "B": 20}


# ---------- инварианты на случайных данных ----------

def _random_case(rng):
    reqs = [Request(f"R{i:02d}", rng.randint(1, 3), rng.randint(1, 120),
                    rng.choice([0, 0, 10, 30, 60]), rng.choice([1, 5, 10, 25]))
            for i in range(rng.randint(1, 8))]
    return rng.randint(0, 300), reqs


@pytest.mark.parametrize("overship", [False, True])
def test_invariants_on_random_cases(overship):
    """Фиксирует три жёстких требования: сумма <= доступного, каждая отгрузка 0 или на сетке в [min_lot, потолок], результат детерминирован и не зависит от порядка; сломается любое из них."""
    rng = random.Random(42)
    for _ in range(500):
        avail, reqs = _random_case(rng)
        plan = allocate(avail, reqs, overship=overship)
        assert sum(plan.values()) <= avail
        for r in reqs:
            v = plan[r.request_id]
            if v:
                assert v % r.rounding_value == 0 and v >= max(r.min_lot, 1)
                assert v <= (_ceil(r.demand_qty, r.rounding_value) if overship else r.demand_qty)
        shuffled = reqs[:]
        rng.shuffle(shuffled)
        assert allocate(avail, shuffled, overship=overship) == plan == allocate(avail, reqs, overship=overship)
