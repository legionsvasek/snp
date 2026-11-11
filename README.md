# SNP Heuristic — распределение дефицита

Python 3.10+, стандартная библиотека (для тестов — `pytest`).

## Запуск
    python main.py                # все кейсы из data/
    python main.py --overship     # с округлением вверх за счёт свободного остатка
    pip install pytest && pytest  # тесты

## Структура
- `allocator.py` — ядро (`allocate`, `allocate_explained`)
- `main.py` — чтение CSV и вывод плана
- `tests/test_allocator.py` — 16 тестов (CSV-кейсы, собственные, инварианты)
- `REPORT.md` — журнал решений и ответы по постановке
