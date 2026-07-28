"""테스트 픽스처.

`fixtures/prices.csv` 는 KIS(PlayMCP 한국주식정보) 실 데이터다.
2025-10-28~12-30 (기준일 윈도우) 및 2026-05-15~07-27 (평가일 윈도우) 구간을 담는다.
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schema import Bar, load_calibration, load_rules, load_universe  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def prices() -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    with (FIXTURES / "prices.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["code"], []).append(
                Bar(
                    day=date.fromisoformat(row["date"]),
                    close=int(row["close"]),
                    volume=int(row["volume"]),
                    trading_value=int(row["trading_value"]),
                )
            )
    for bars in out.values():
        bars.sort(key=lambda b: b.day)
    return out


@pytest.fixture(scope="session")
def universe():
    return load_universe()


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def calibration():
    return load_calibration()
