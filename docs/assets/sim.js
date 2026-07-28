/* 탭4(27년 과제 설계) 전용 계산 엔진.
 *
 * 사이트는 계산하지 않는다는 원칙(app.js 상단 주석)의 유일한 예외다. 탭4는
 * 슬라이더 값이 사실상 무한하므로(가중치, 점수 스케일, 윈도우 자유조합) 서버에서
 * 미리 계산해 둘 수 없다 — core/calendar.py · core/vwap.py · core/evaluate.py 의
 * 공식을 여기 그대로 옮겨, docs/data/bars.json(원자료)으로 다시 계산한다.
 *
 * 공식이 두 곳(Python·JS)에 있으므로 반드시 어긋날 수 있다. 탭4의 "기본값으로
 * 초기화" 버튼이 잠정(2M·산식B·에화60:배소40·전종목·±15%·상대) 기본값으로
 * 돌아갔을 때 탭2 "오늘의 점수"와 정확히 같은 값을 내는지가 그 어긋남을 잡는
 * 유일한 안전장치다 — app.js 의 defaultsMatchToday() 가 그 확인을 수행한다.
 */

function minusMonthsJS(day, months) {
  const y = day.getUTCFullYear(), m = day.getUTCMonth();
  const total = y * 12 + m - months;
  const year = Math.floor(total / 12);
  const month = total - year * 12;
  const dim = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return new Date(Date.UTC(year, month, Math.min(day.getUTCDate(), dim)));
}

function addDaysJS(d, n) { return new Date(d.getTime() + n * 86400000); }
function toISOJS(d) { return d.toISOString().slice(0, 10); }
function parseISOJS(s) { const [y, m, d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); }

function windowBoundsJS(end, spec) {
  const m = /^(\d+)([DWM])$/i.exec(spec);
  if (!m) throw new Error(`알 수 없는 윈도우: ${spec}`);
  const n = parseInt(m[1], 10), unit = m[2].toUpperCase();
  let start;
  if (unit === "D") start = addDaysJS(end, -(n - 1));
  else if (unit === "W") start = addDaysJS(end, -(n * 7 - 1));
  else start = addDaysJS(minusMonthsJS(end, n), 1);
  return [start, end];
}

function sliceWindowJS(barsObj, start, end) {
  const s = toISOJS(start), e = toISOJS(end), idx = [];
  for (let i = 0; i < barsObj.dates.length; i++) {
    if (barsObj.dates[i] >= s && barsObj.dates[i] <= e) idx.push(i);
  }
  return idx;
}

function vwapJS(barsObj, idx, method) {
  let vol = 0, val = 0, cv = 0;
  idx.forEach(i => { vol += barsObj.volume[i]; val += barsObj.trading_value[i]; cv += barsObj.close[i] * barsObj.volume[i]; });
  if (vol <= 0) throw new Error("윈도우 거래량이 0입니다");
  return method === "A" ? val / vol : cv / vol;
}

/** 단순 종가평균 — "거래량가중 적용" 을 끄면 거래량을 아예 무시하고 종가만 평균한다.
 *  탭4 전용 what-if 다. 확정 공식(core/evaluate.py)은 항상 거래량가중이라 여기 없다. */
function simpleAvgJS(barsObj, idx) {
  if (!idx.length) throw new Error("윈도우 안에 거래일이 없습니다");
  return idx.reduce((a, i) => a + barsObj.close[i], 0) / idx.length;
}

function adjustedPriceJS(barsObj, end, specs, method, weighted) {
  const vals = specs.map(s => {
    const [start, e] = windowBoundsJS(end, s);
    const idx = sliceWindowJS(barsObj, start, e);
    return weighted === false ? simpleAvgJS(barsObj, idx) : vwapJS(barsObj, idx, method);
  });
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function closeAtJS(barsObj, dateISO) {
  const i = barsObj.dates.indexOf(dateISO);
  return i >= 0 ? barsObj.close[i] : null;
}

function scoreOfJS(evalPrice, anchor, scale) {
  const base = scale.base_points;
  const low = anchor * (1 + scale.lower_bound_pct), high = anchor * (1 + scale.upper_bound_pct);
  const raw = evalPrice <= anchor
    ? base * (evalPrice - low) / (anchor - low)
    : base + (scale.max_points - base) * (evalPrice - anchor) / (high - anchor);
  if (!scale.clip) return { raw, value: raw, clipped: false };
  const value = Math.min(Math.max(raw, scale.min_points), scale.max_points);
  return { raw, value, clipped: value !== raw };
}

function priceForPointsJS(scale, anchor, points) {
  const base = scale.base_points;
  if (points <= base) {
    const frac = (points - scale.min_points) / (base - scale.min_points);
    return anchor * (1 + scale.lower_bound_pct * (1 - frac));
  }
  const frac = (points - base) / (scale.max_points - base);
  return anchor * (1 + scale.upper_bound_pct * frac);
}

/** tickers: D.latest.tickers 형태 [{code,name,group,weight}, ...] (그룹 "본사"/"에화"/"배소").
 *  params: {method, windows:[spec,...], weight(에화 비중), excluded:Set(code), scaleWidth, formula,
 *           weighted(거래량가중 적용 여부 — false 면 종목 무관 단순 종가평균)} */
function computeSim(bars, tickers, params, baseDate, evalDate, anchor, baseScale) {
  const subject = tickers.find(t => t.group === "본사");
  const groupOrder = [];
  const membersByGroup = {};
  tickers.forEach(t => {
    if (t.group === "본사") return;
    if (!membersByGroup[t.group]) { membersByGroup[t.group] = []; groupOrder.push(t.group); }
    membersByGroup[t.group].push(t);
  });
  const groupWeight = { [groupOrder[0]]: params.weight, [groupOrder[1]]: 1 - params.weight };

  const specs = params.windows, method = params.method, weighted = params.weighted !== false;
  const now = {}, base = {};
  now[subject.code] = adjustedPriceJS(bars[subject.code], evalDate, specs, method, weighted);
  base[subject.code] = adjustedPriceJS(bars[subject.code], baseDate, specs, method, weighted);
  const subjectChange = now[subject.code] / base[subject.code] - 1;

  const groups = {};
  for (const name of groupOrder) {
    const included = membersByGroup[name].filter(m => !params.excluded.has(m.code));
    const memberRows = included.map(m => {
      now[m.code] = adjustedPriceJS(bars[m.code], evalDate, specs, method, weighted);
      base[m.code] = adjustedPriceJS(bars[m.code], baseDate, specs, method, weighted);
      const change = now[m.code] / base[m.code] - 1;
      return { name: m.name, change };
    });
    const average = memberRows.reduce((a, r) => a + r.change, 0) / memberRows.length;
    groups[name] = { weight: groupWeight[name], average, members: memberRows };
  }
  const peerChange = groupOrder.reduce((a, name) => a + groups[name].weight * groups[name].average, 0);
  const relative = params.formula === "absolute" ? subjectChange : subjectChange - peerChange;
  const subjectPrice = now[subject.code];
  const evalPrice = subjectPrice / (1 - relative);

  const scale = { ...baseScale, lower_bound_pct: -params.scaleWidth, upper_bound_pct: params.scaleWidth };
  const s = scoreOfJS(evalPrice, anchor, scale);
  const windowsFor = end => specs.map(sp => ({
    spec: sp, vwap: adjustedPriceJS(bars[subject.code], end, [sp], method, weighted),
  }));

  return {
    specs, method,
    subject_close: closeAtJS(bars[subject.code], toISOJS(evalDate)),
    windows_now: windowsFor(evalDate), windows_base: windowsFor(baseDate),
    subject_price: subjectPrice, subject_base_price: base[subject.code], subject_change: subjectChange,
    groups, peer_change: peerChange, relative_change: relative,
    multiplier: 1 / (1 - relative), eval_price: evalPrice,
    scores: { V3: { anchor, raw: s.raw, value: s.value, clipped: s.clipped } },
    score_marks: { V3: [0, 40, 80, 100].map(pt => ({ points: pt, price: priceForPointsJS(scale, anchor, pt) })) },
  };
}
