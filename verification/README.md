# 검증 스크립트 (일회성)

PLAN.md의 수치 근거. 데이터는 KIS(PlayMCP 한국주식정보) 응답을 하드코딩했다.
본 구현이 아니라 **계획 단계의 사실 확인용**이며, 정식 계산 엔진은
`core/`에 별도 구현한다.

| 파일 | 검증 내용 | 대응 |
|---|---|---|
| `calib.py`, `calib2.py` | 2025년말 기준값 재현 시도 | PLAN §3 |
| `vwap_method.py` | VWAP 산식 A vs B — 9종목 2개월/일별 비교 | PLAN §2 |
| `eval2026.py` | 2026-05-28~07-27 평가 윈도우 원자료 | — |
| `pipeline.py` | 전체 파이프라인 A/B 점수 영향 | PLAN §2 |

실행:
```
cd stock_kpi/verification
python3 calib2.py      # 기준값 재현
python3 vwap_method.py # 산식 A/B 종목별 비교
python3 pipeline.py    # 점수 영향
```
