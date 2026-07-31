"""테스트 픽스처.

`data/normalized/prices.csv`의 최신 KIS(PlayMCP 한국주식정보) 실 데이터를 쓴다.
일일 갱신 뒤에도 사이트 산출물과 같은 입력으로 회귀 테스트하기 위함이다.
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schema import Bar, load_calibration, load_rules, load_universe  # noqa: E402

PRICES_CSV = Path(__file__).resolve().parent.parent / "data" / "normalized" / "prices.csv"


@pytest.fixture(scope="session")
def prices() -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    with PRICES_CSV.open(encoding="utf-8") as fh:
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
