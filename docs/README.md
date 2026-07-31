# 사이트 (GitHub Pages)

정적 파일만 있다. **계산은 하지 않는다** — `pipeline/build_site.py` 가 만든
`data/*.json` 을 읽어 그리기만 한다. 계산이 두 곳에 있으면 검증한 값과
화면의 값이 갈라지므로, 산출 로직은 `core/` 한 곳에만 둔다.

```
index.html            셸 (사이드바 메인탭·상단 서브탭)
assets/style.css      디자인 토큰
assets/app.js         렌더링 (탭1~3 · 전 탭 공통 기능)
assets/sim.js         탭4 전용 계산 엔진 — core/ 공식을 JS로 옮긴 것 (아래 참조)
data/latest.json      최신 산출·평가 실적·목표역산·Peer기여도·민감도·커버리지  ← 자동 생성
data/history.json     일별 종가/지수 시계열                                  ← 자동 생성
data/scenarios.json   최종 방식 기준선별 점수·잔여기간 시나리오·점수 시계열(탭3) ← 자동 생성
data/bars.json        원자료(종가·거래량·거래대금) — 탭4 sim.js 가 재계산용   ← 자동 생성
data/changelog.json   config/*.yaml git 변경 이력                            ← 자동 생성
```

## 탭4(27년 과제 설계)와 sim.js — 유일하게 계산이 두 곳에 있는 예외

탭4는 슬라이더(가중치·점수 스케일·윈도우 자유조합)가 사실상 무한해 서버에서
미리 계산해 둘 수 없다. 그래서 `docs/assets/sim.js` 가 `core/calendar.py` ·
`core/vwap.py` · `core/evaluate.py` 의 공식을 그대로 옮겨 `bars.json` 원자료로
브라우저에서 재계산한다. 공식이 두 군데(Python·JS)에 있으므로 반드시 어긋날
위험이 있다 — `app.js`의 `verifyDefaultsMatchToday()`가 탭4 기본값(잠정·산식B·
에화60:배소40·전종목·±15%·상대)이 탭2 "오늘의 점수"와 정확히 일치하는지 페이지
로드 시마다 콘솔에서 확인한다. `core/scenarios.py`(탭2·3 전용)를 고치면
`sim.js`도 같이 확인해야 한다.

## 갱신

```
python3 -c "
import csv
from datetime import date
from core.schema import Bar, load_universe, load_rules, load_calibration
from pipeline.build_site import write_site_data

prices = {}
with open('data/normalized/prices.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        prices.setdefault(row['code'], []).append(Bar(
            day=date.fromisoformat(row['date']), close=int(row['close']),
            volume=int(row['volume']), trading_value=int(row['trading_value']),
        ))
for bars in prices.values():
    bars.sort(key=lambda b: b.day)

write_site_data(prices, load_universe(), load_rules(), load_calibration())
"
```

## 배포

저장소 Settings → Pages → Source: 브랜치의 `/stock_kpi/docs` 디렉터리.

## 알아둘 것

- Pretendard 폰트를 jsDelivr CDN에서 받는다(참고 사이트와 동일). 사내망에서
  CDN이 막히면 시스템 폰트로 폴백되며 레이아웃은 유지된다.
- 차트 x축은 **거래일 순서**다. 수집 공백 구간은 선을 끊고 음영으로 표시한다.
  이어 그리면 51일 공백이 하루 급변처럼 보인다.
