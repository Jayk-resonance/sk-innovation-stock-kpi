# 수집 실행 지침 (kpi-collector)

MCP 커넥터는 Claude 세션에서만 호출된다. 이 문서는 그 호출 규격을 고정한다.
**수집 외의 판단은 하지 않는다.** 계산·검증·배포는 다른 에이전트의 몫이다.

대시보드 가격 기준은 **전 거래일의 KIS 확정 미조정 일봉**이다. 종가·거래량·
거래대금은 동일한 날짜의 PlayMCP KIS 일봉 응답에서 가져온다. KIS 일봉의
거래량·거래대금에는 시간외/NXT 통합 체결이 포함될 수 있다.

## 1. 대상

`config/universe.yaml` 의 공식 KPI 9종목과 `candidates` 후보 2종목 전부.
일일 수집은 총 11종목이며, 하나라도 빠지면 그날 수집은 실패다.
월봉 대조는 공식 KPI 9종목에만 적용한다. 종목코드를 문서에 하드코딩하지 말고
항상 현재 설정에서 읽는다.

## 2. 호출 및 출처

`stock_get_price_history(stock_code, period="D", adjusted=false)`를 사용한다.
응답의 `source=KIS`, `is_adjusted=false`, 날짜, 종가, 거래량, 거래대금을 확인한다.
현재 시세나 다른 출처의 종가·거래량을 KIS 일봉과 섞지 않는다.

- **1회 최대 100건.** 100거래일을 넘는 구간은 반드시 분할 호출한다.
- `adjusted=false`를 명시한다. KIS를 사용할 때는 각 행의 `is_adjusted=false`도
  확인한다. 조정 여부가 불명확하면 수집 실패다.
  → 권리락 보정은 `config/calibration.yaml` 의 `corporate_actions` 로만 처리한다.
- **다음 날 오전 7시(KST)**에 전일까지의 날짜가 붙은 확정 일봉만 채택한다.
  당일 일봉은 사용하지 않는다. 이후 정정도 가능하므로 최근 저장값을 매번 대조한다.
- `stock_get_quote(market_div_code="J")`는 현재 시점 조회이므로 과거 날짜의 종가·
  거래량·거래대금을 대신할 수 없다.

일일 수집은 당일 1건만 필요하나, 누락·확정 정정 탐지를 위해 **직전 20거래일**을
함께 받아 기존 값과 대조한다. 휴장일이나 이미 최신 날짜인 날에도 이 대조를 먼저
실행한다. 값이 달라지면 데이터 정정이 발생한 것이므로 경고한다.
정정 후보는 같은 조건으로 두 번 조회해 종가·거래량·거래대금이 모두 같아야 한다.

### 백필은 반드시 달 단위로 끊는다

교차검증(`pipeline/verify.py`)은 **KIS 확정 월봉 참조값**과 일봉 합계를 대조한다.
월봉은 그 달 **전체**의 집계이므로, 달의 일부만 수집하면 정상적인 부분 수집인지
진짜 결측인지 구분할 수 없어 **그 달은 검증 자체가 불가능**해진다.

따라서 백필 구간은 항상 `YYYY-MM-01 ~ YYYY-MM-말일` 경계에 맞춘다.
평가 윈도우가 2/17에 시작하더라도 **2월 전체**를 받는다.
윈도우만 받으면 산출은 되지만 분기 검증에서 "검증불가"로 남는다.

### 월봉 참조 데이터

KIS 확정 일봉을 월초부터 기준일까지 합산하고, 같은 KIS API의 `period="M"`
월봉과 거래량·거래대금을 원 단위로 대조한다. 일봉·월봉 모두 같은 시간외/NXT
통합 집계 기준이어야 한다. 일치한 합계를 `data/reference/monthly.csv`에 저장한다.

## 3. 상장주식수 (발행주식수 변동 감지용)

```
koreaStock-stock_get_quote(stock_code = <6자리 코드>)
```

응답의 `market_cap`(억원)과 `price`로 역산한다.

```
상장주식수 = market_cap × 10^8 ÷ price
```

**과거 소급 조회가 불가능하다.** 시점 조회만 되므로 매일 저장해야 시계열이 쌓인다.
백필 대상이 아니며, 수집 개시일부터 축적된다.

## 4. 저장 규격

`data/raw/YYYY-MM-DD.json` 에 아래 형태로 저장한다. **한 번 쓴 파일은 수정하지 않는다.**
정정은 별도 파일로 추가하며 원본보다 뒤에 병합되도록
`YYYY-MM-DD.z-correction.json` 형식을 사용한다.

```json
{
  "collected_at": "2026-07-27T16:05:00+09:00",
  "source": "PlayMCP KIS unadjusted finalized daily history (inquire-daily-itemchartprice)",
  "basis": "KIS finalized daily bar including after-hours/NXT-integrated volume and trading value",
  "prices": [
    {"code": "096770", "date": "2026-07-27", "close": 116700,
     "volume": 845081, "trading_value": 101028877750}
  ],
  "shares": [
    {"code": "096770", "date": "2026-07-27", "market_cap_100m": 197285,
     "price": 116700, "shares": 169053128}
  ]
}
```

## 5. 수집 직후 확인

여기까지가 collector 의 책임이다. 실패 시 **중단하고 알린다.**
`docs/data` 를 갱신하지 않는 편이 깨진 데이터를 올리는 것보다 안전하다.

- 설정에 있는 KPI 9종목과 후보 2종목을 전부 수신했는가
- 요청한 날짜가 응답에 있는가 (휴장일이면 빈 응답이 정상)
- `volume`, `trading_value` 가 0 또는 음수가 아닌가

이후 정합성 검사는 `pipeline/qc.py` 가 맡는다.
