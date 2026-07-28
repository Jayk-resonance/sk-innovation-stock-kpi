# 수집 실행 지침 (kpi-collector)

MCP 커넥터는 Claude 세션에서만 호출된다. 이 문서는 그 호출 규격을 고정한다.
**수집 외의 판단은 하지 않는다.** 계산·검증·배포는 다른 에이전트의 몫이다.

## 1. 대상

`config/universe.yaml` 의 9종목 전부. 하나라도 빠지면 그날 수집은 실패다.

## 2. 호출

```
koreaStock-stock_get_price_history(
    stock_code = <6자리 코드>,
    start_date = YYYYMMDD,
    end_date   = YYYYMMDD,
    period     = "D",
)
```

- **1회 최대 100건.** 100거래일을 넘는 구간은 반드시 분할 호출한다.
- `adjusted` 파라미터는 무시해도 된다. 응답은 항상 `is_adjusted: false` 로 온다.
  → 권리락 보정은 `config/calibration.yaml` 의 `corporate_actions` 로만 처리한다.

일일 수집은 당일 1건만 필요하나, 누락 복구를 위해 **직전 5거래일**을 함께 받아
기존 값과 대조한다. 값이 달라지면 데이터 정정이 발생한 것이므로 경고한다.

### 백필은 반드시 달 단위로 끊는다

교차검증(`pipeline/verify.py`)은 **KIS 월봉의 서버측 집계**와 일봉 합계를 대조한다.
월봉은 그 달 **전체**의 집계이므로, 달의 일부만 수집하면 정상적인 부분 수집인지
진짜 결측인지 구분할 수 없어 **그 달은 검증 자체가 불가능**해진다.

따라서 백필 구간은 항상 `YYYY-MM-01 ~ YYYY-MM-말일` 경계에 맞춘다.
평가 윈도우가 2/17에 시작하더라도 **2월 전체**를 받는다.
윈도우만 받으면 산출은 되지만 분기 검증에서 "검증불가"로 남는다.

### 월봉 참조 데이터

```
koreaStock-stock_get_price_history(stock_code=..., period="M",
                                   start_date=..., end_date=...)
```

응답의 `volume` / `trading_value` 를 `data/reference/monthly.csv` 에 저장한다.
한 번 호출로 여러 달이 오므로 종목당 1회면 충분하다.

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

```json
{
  "collected_at": "2026-07-27T16:05:00+09:00",
  "source": "KIS via PlayMCP koreaStock",
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

- 9종목 전부 수신했는가
- 요청한 날짜가 응답에 있는가 (휴장일이면 빈 응답이 정상)
- `volume`, `trading_value` 가 0 또는 음수가 아닌가

이후 정합성 검사는 `pipeline/qc.py` 가 맡는다.
