"""데이터 구조 및 설정 로딩·검증.

계산 계층은 네트워크·MCP 의존성이 없다. 입력은 항상 이미 수집된 Bar 목록이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass(frozen=True)
class Bar:
    """일별 시세 1건."""

    day: date
    close: int
    volume: int
    trading_value: int

    def __post_init__(self) -> None:
        if self.volume < 0 or self.trading_value < 0 or self.close <= 0:
            raise ValueError(f"비정상 시세: {self}")


@dataclass(frozen=True)
class Ticker:
    name: str
    code: str
    market: str


@dataclass(frozen=True)
class Universe:
    subject: Ticker
    groups: dict[str, tuple[float, tuple[Ticker, ...]]]  # 그룹명 -> (가중치, 종목들)

    @property
    def peers(self) -> tuple[Ticker, ...]:
        return tuple(t for _, members in self.groups.values() for t in members)

    @property
    def all_tickers(self) -> tuple[Ticker, ...]:
        return (self.subject,) + self.peers


@dataclass(frozen=True)
class Candidate:
    """"27년 과제 설계" 탭 전용 실험용 Peer 후보. 어느 그룹에 넣어봤을 때를
    가정하는지(group)만 들고 있을 뿐, Universe.groups 에는 속하지 않는다 —
    core/evaluate.py 의 공식 점수 계산에는 전혀 관여하지 않는다."""

    ticker: Ticker
    group: str


def _to_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def load_universe(path: Path | None = None) -> Universe:
    raw = yaml.safe_load((path or CONFIG_DIR / "universe.yaml").read_text(encoding="utf-8"))
    subject = Ticker(**raw["subject"])
    groups = {
        name: (float(g["weight"]), tuple(Ticker(**m) for m in g["members"]))
        for name, g in raw["groups"].items()
    }
    total = sum(w for w, _ in groups.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"그룹 가중치 합이 1.0이 아니다: {total}")
    return Universe(subject=subject, groups=groups)


def load_candidates(path: Path | None = None) -> tuple[Candidate, ...]:
    """universe.yaml 의 candidates 섹션. 파일에 없으면 빈 튜플이다."""
    raw = yaml.safe_load((path or CONFIG_DIR / "universe.yaml").read_text(encoding="utf-8"))
    entries = raw.get("candidates") or []
    return tuple(
        Candidate(ticker=Ticker(name=e["name"], code=e["code"], market=e["market"]), group=e["group"])
        for e in entries
    )


def load_rules(path: Path | None = None) -> dict:
    raw = yaml.safe_load((path or CONFIG_DIR / "kpi_rules.yaml").read_text(encoding="utf-8"))
    raw["base_date"] = _to_date(raw["base_date"])
    for entry in raw["eval_dates"]:
        entry["date"] = _to_date(entry["date"]) if entry.get("date") else None
    unknown = set(raw["windows"]) - {"잠정", "최종"}
    if unknown:
        raise ValueError(f"알 수 없는 평가 모드: {unknown}")
    return raw


def load_calibration(path: Path | None = None) -> dict:
    raw = yaml.safe_load((path or CONFIG_DIR / "calibration.yaml").read_text(encoding="utf-8"))
    for action in raw.get("corporate_actions") or []:
        action["effective_date"] = _to_date(action["effective_date"])
    official = [k for k, v in raw["baselines"].items() if v.get("official")]
    if len(official) != 1:
        raise ValueError(f"official 기준선은 정확히 1개여야 한다: {official}")
    return raw


def load_peer_criteria(path: Path | None = None) -> dict[str, dict]:
    """Peer 선정 적정성 중 사람이 판단해야 하는 항목(사업 유사도·독립성).

    시가총액·유동성처럼 매일 다시 계산되는 항목과 달리, 이 판단은 근거와 함께
    사람이 등록해야 나중에 왜 그런지 추적할 수 있다 — pipeline/build_site.py 가
    시가총액·유동성과 합쳐 화면에 낸다.
    """
    target = path or CONFIG_DIR / "peer_criteria.yaml"
    if not target.exists():
        return {}
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return raw.get("peers") or {}
