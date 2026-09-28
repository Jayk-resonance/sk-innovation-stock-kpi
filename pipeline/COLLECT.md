# 수집 실행 지침 (kpi-collector)

MCP 커넥터는 Claude 세션에서만 호출된다. 이 문서는 그 호출 규격을 고정한다.
**수집 외의 판단은 하지 않는다.** 계산·검증·배포는 다른 에이전트의 몫이다.

대시보드 가격 기준은 **전 거래일의 KRX 정규장 미조정 일봉**이다. 종가·거래량·
거래대금은 동일한 날짜·출처의 정규장 일봉에서 가져온다. 종가는 15:30 종가이며
시간외·NXT·통합시장 체결은 포함하지 않는다.

## 1. 대상

`config/universe.yaml` 의 공식 KPI 9종목과 `candidates` 후보 2종목 전부.
일일 수집은 총 11종목이며, 하나라도 빠지면 그날 수집은 실패다.
월봉 대조는 공식 KPI 9종목에만 적용한다. 종목코드를 문서에 하드코딩하지 말고
항상 현재 설정에서 읽는다.

## 2. 호출 및 출처

```
1. 날짜가 붙은 KIS 정규장 일봉 호출에 `market_div_code="J"`를 지정할 수 있고
   응답도 KRX임을 명시하면 그것을 우선한다.
2. 현재 PlayMCP의 `stock_get_price_history`에는 시장구분 인자가 없으므로 범용 KIS
   일봉은 사용하지 않는다. 이 제약이 유지되는 동안 Daum Finance의
   `adjusted=false` KRX 일봉을 사용한다.
3. 새로 추가하거나 종가를 바꾸는 모든 행의 종가는 Naver Finance KRX 일봉과
   일치해야 한다. 불일치하면 수집 실패다.
```

- **1회 최대 100건.** 100거래일을 넘는 구간은 반드시 분할 호출한다.
- `adjusted=false`를 명시한다. KIS를 사용할 때는 각 행의 `is_adjusted=false`도
  확인한다. 조정 여부가 불명확하면 수집 실패다.
  → 권리락 보정은 `config/calibration.yaml` 의 `corporate_actions` 로만 처리한다.
- **다음 날 오전 7시(KST)**에 전일까지의 날짜가 붙은 정규장 일봉만 채택한다.
  당일 일봉은 사용하지 않는다. 이후 정정도 가능하므로 최근 저장값을 매번 대조한다.
- `stock_get_quote(market_div_code="J")`는 현재 시점 조회이므로 과거 날짜의 종가·
  거래량·거래대금을 대신할 수 없다.

일일 수집은 당일 1건만 필요하나, 누락 복구를 위해 **직전 5거래일**을 함께 받아
기존 값과 대조한다. 값이 달라지면 데이터 정정이 발생한 것이므로 경고한다.
정정 후보는 같은 조건으로 두 번 조회해 종가·거래량·거래대금이 모두 같아야 한다.

### 백필은 반드시 달 단위로 끊는다

교차검증(`pipeline/verify.py`)은 **KRX 정규장 월간 참조값**과 일봉 합계를 대조한다.
월봉은 그 달 **전체**의 집계이므로, 달의 일부만 수집하면 정상적인 부분 수집인지
진짜 결측인지 구분할 수 없어 **그 달은 검증 자체가 불가능**해진다.

따라서 백필 구간은 항상 `YYYY-MM-01 ~ YYYY-MM-말일` 경계에 맞춘다.
평가 윈도우가 2/17에 시작하더라도 **2월 전체**를 받는다.
윈도우만 받으면 산출은 되지만 분기 검증에서 "검증불가"로 남는다.

### 월봉 참조 데이터

```
KRX 정규장 일봉을 월초부터 기준일까지 합산한다. 같은 기준일까지 독립 집계된
정규장 월봉이 제공되면 그 값과도 원 단위로 대조한다.
```

정규장 `volume` / `trading_value` 합계를 `data/reference/monthly.csv`에 저장한다.
KIS 범용 월봉은 시간외 거래를 포함할 수 있으므로 섞지 않는다.

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
  "source": "Daum Finance KRX unadjusted regular-session daily candles; changed closes cross-checked with Naver Finance",
  "basis": "KRX regular session (15:30 close, regular-session volume and trading value)",
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
