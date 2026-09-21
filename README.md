# SK이노베이션 CEO KPI '주가' 과제 — 산출·검증·시뮬레이션

SK이노베이션 CEO KPI 중 "주가" 과제(평가주가 산출식·Peer 그룹 상대성과 기반
점수화)의 산출 엔진, 데이터 수집·검증 파이프라인, 대시보드를 담은 저장소다.

가격·거래량·거래대금은 전 거래일의 KIS 미조정 일봉을 동일한 기준으로 사용한다.
KIS 일봉은 15:30 이후 거래를 반영할 수 있으며, KRX 정규장 전용 통계가 아니다.

- 계획·의사결정 이력: [`PLAN.md`](PLAN.md)
- 계산 엔진(순수 함수, 네트워크 의존성 없음): `core/`
- 수집·정규화·QC·교차검증 파이프라인: `pipeline/`
- 대시보드(정적 사이트, GitHub Pages): `docs/` — 구조는 [`docs/README.md`](docs/README.md) 참조
- 테스트: `tests/` (`pytest`)

## 대시보드 보기

GitHub Pages 배포 후: `https://jayk-resonance.github.io/sk-innovation-stock-kpi/`

## 로컬 테스트

```
pip install -r requirements.txt
pytest tests/ -q
```
