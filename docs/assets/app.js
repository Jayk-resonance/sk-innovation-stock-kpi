/* 사이트는 계산하지 않는다. pipeline/build_site.py 가 만든 JSON을 그리기만 한다.
 * 계산이 두 곳에 있으면 검증한 값과 화면의 값이 갈라진다.
 *
 * 색은 여기에 하나도 박지 않는다. SVG 는 CSS 변수를 직접 못 쓰므로
 * tok() 으로 style.css 의 토큰을 읽어 쓴다. 팔레트 변경은 CSS 한 곳에서 끝난다.
 *
 * 커서를 올리면 값을 보여주는(hover) 차트는 전부 svg에 preserveAspectRatio="none"
 * 을 붙인다. 기본값(xMidYMid meet)은 viewBox 비율과 CSS 박스 비율이 어긋나면
 * 콘텐츠를 축소해 레터박스로 띄우는데, hit-rect 히트테스트는 박스 전체 크기
 * 기준으로 좌표를 계산하므로 그 여백 부분이 반응 없는 죽은 영역이 된다.
 * (실제로 CSS 높이와 이 파일의 viewBox 높이가 어긋나 최근 날짜 구간이
 * 죽은 영역에 들어간 적이 있다 — 2026-08-13에 발견.) "none"으로 박스에
 * 꽉 채워 그리면 CSS 크기가 나중에 바뀌어도 이 문제가 재발하지 않는다.
 *
 * 내비게이션 2층 구조:
 *   메인 탭(사이드바, 아이콘) — 주가 평가 / 주가 현황
 *   서브탭(상단, 주가 평가 전용) — 오늘의 점수 / 확정 평가일별 화면
 */
const MAIN_TABS = [
  { key: "score", label: "주가 평가", icon: "📊" },
  { key: "prices", label: "주가 현황", icon: "📈" },
  { key: "case", label: "Case 시뮬레이션", icon: "🧮" },
  { key: "design", label: "27년 과제 설계", icon: "🛠️" },
];
const S = { tab: "score", evalKey: "today", method: null, horizon: 2 };
const D = { latest: null, history: null, scenarios: null, bars: null };
const HIDDEN_EVAL_KEYS = new Set(["2026-1분기"]); // 다시 표시하려면 이 키를 제거한다.
// 점수 시계열을 주가 현황 탭으로 옮기면서 나머지(기준선별 점수·잔여기간 시나리오)만
// 남은 Case 시뮬레이션 탭을 숨겼다. 코드는 그대로 두었으니 이 키를 지우면 복원된다.
const HIDDEN_MAIN_TABS = new Set(["case"]);
const WINDOW_OPTS = ["1D", "1W", "1M", "2M", "3M", "6M"];
let SIM = null;   // 탭4 파라미터 상태. D.latest 로딩 후 첫 방문 시 simDefaults() 로 채운다.
const MOBILE_NAV_MEDIA = window.matchMedia("(max-width: 760px)");

const tok = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g,
  m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
const won = n => n == null ? "—" : Math.round(n).toLocaleString("ko-KR");
const signed = (n, d = 2) => n == null ? "—" : (n >= 0 ? "+" : "") + (n * 100).toFixed(d) + "%";
const dirClass = n => n == null ? "" : (n > 0 ? "up" : n < 0 ? "down" : "");
const pts = n => n == null ? "—" : n.toFixed(2);
const signedPts = n => n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "점";
const jo = n100m => n100m == null ? "—" : (n100m / 10000).toFixed(1) + "조원";   // 억원 단위 입력
const eok = won_ => won_ == null ? "—" : Math.round(won_ / 1e8).toLocaleString("ko-KR") + "억원";
const peerRatingClass = r => ({
  "적정": "ok", "매우 높음": "ok", "높음": "ok",
  "격차 있음": "warn", "중간": "warn",
  "격차 큼": "down", "낮음": "down",
}[r] || "grp");
const koDate = value => {
  const [year, month, day] = String(value || "").split("-").map(Number);
  return year && month && day ? `${year}년 ${month}월 ${day}일` : esc(value);
};
const koMonthDay = value => {
  const [, month, day] = String(value || "").split("-").map(Number);
  return month && day ? `${month}월 ${day}일` : esc(value);
};

/* 그룹 → 시리즈 슬롯. 고정 순서이며 순환하지 않는다. */
const SLOT = { 본사: "--series-1", 에화: "--series-2", 배소: "--series-3" };
const slotColor = group => tok(SLOT[group] || "--muted");

async function j(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} (${r.status})`);
  return r.json();
}

function visibleViews() {
  return D.latest.views.filter(v => !HIDDEN_EVAL_KEYS.has(v.key));
}

function visibleMainTabs() {
  return MAIN_TABS.filter(t => !HIDDEN_MAIN_TABS.has(t.key));
}

function currentView() {
  return visibleViews().find(v => v.key === S.evalKey) || visibleViews()[0];
}

async function init() {
  try {
    [D.latest, D.history, D.scenarios, D.bars] = await Promise.all([
      j("data/latest.json"), j("data/history.json"), j("data/scenarios.json"), j("data/bars.json"),
    ]);
    verifyDefaultsMatchToday();
    wireExportDelegation();
    S.method = D.latest.method_primary;
    // 서브탭 키에 한글이 섞여 있다(예: "2026-상반기"). 주소창을 거쳐 오면
    // 브라우저가 퍼센트 인코딩할 수 있으므로 decodeURIComponent 로 정규화한다.
    // 이미 디코딩된 문자열(% 없음)에 다시 걸어도 그대로 반환되어 안전하다.
    const [hTab, hSubRaw] = location.hash.slice(1).split("/");
    let hSub = hSubRaw;
    try { hSub = hSubRaw ? decodeURIComponent(hSubRaw) : hSubRaw; } catch (e) { /* 잘못된 인코딩은 무시 */ }
    if (visibleMainTabs().some(t => t.key === hTab)) S.tab = hTab;
    if (hSub && visibleViews().some(v => v.key === hSub)) S.evalKey = hSub;
    document.getElementById("todayStr").textContent = koDate(D.latest.as_of) + " 기준";
    wireMobileNav(); renderMainNav(); renderTickerList(); renderSubtabs(); render();
  } catch (e) {
    document.getElementById("view").innerHTML =
      `<div class="empty"><span class="ico">⚠️</span><b style="color:var(--ink)">데이터를 불러오지 못했습니다</b><br><small>${esc(e.message)}</small></div>`;
  }
}

function pushHash() {
  location.hash = S.tab === "score"
    ? `${S.tab}/${encodeURIComponent(S.evalKey)}` : S.tab;
}

function setMobileNavOpen(open) {
  const siteNav = document.getElementById("siteNav");
  const openButton = document.getElementById("mobileNavOpen");
  const focusWasInside = siteNav.contains(document.activeElement);
  open = MOBILE_NAV_MEDIA.matches && open;
  document.body.classList.toggle("mobile-nav-opened", open);
  openButton.setAttribute("aria-expanded", String(open));
  siteNav.inert = MOBILE_NAV_MEDIA.matches && !open;
  if (open) document.getElementById("mobileNavClose").focus();
  else if (MOBILE_NAV_MEDIA.matches && focusWasInside) openButton.focus();
}

function wireMobileNav() {
  document.getElementById("mobileNavOpen").addEventListener("click", () => setMobileNavOpen(true));
  document.getElementById("mobileNavClose").addEventListener("click", () => setMobileNavOpen(false));
  document.getElementById("mobileNavScrim").addEventListener("click", () => setMobileNavOpen(false));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.body.classList.contains("mobile-nav-opened")) {
      setMobileNavOpen(false);
    }
  });
  MOBILE_NAV_MEDIA.addEventListener("change", () => setMobileNavOpen(false));
  setMobileNavOpen(false);
}

function renderMainNav() {
  const current = MAIN_TABS.find(t => t.key === S.tab);
  document.getElementById("mobileSection").textContent = current?.label || "메뉴";
  document.getElementById("mainNav").innerHTML = visibleMainTabs().map(t => `
    <button class="nav-main-item ${S.tab === t.key ? "active" : ""}" data-main="${t.key}">
      <span class="nav-ico" aria-hidden="true">${t.icon}</span>
      <span class="nav-lbl">${esc(t.label)}</span>
    </button>`).join("");
  document.querySelectorAll("[data-main]").forEach(b =>
    b.addEventListener("click", () => {
      S.tab = b.dataset.main;
      if (S.tab === "score" && !visibleViews().some(v => v.key === S.evalKey)) S.evalKey = "today";
      setMobileNavOpen(false); pushHash(); renderMainNav(); renderSubtabs(); render();
    }));
}

function renderSubtabs() {
  const el = document.getElementById("subtabs");
  if (S.tab !== "score") { el.innerHTML = ""; return; }
  el.innerHTML = visibleViews().map(v => `
    <button class="tab ${S.evalKey === v.key ? "active" : ""}" data-sub="${v.key}">
      ${esc(v.label)}
    </button>`).join("");
  document.querySelectorAll("[data-sub]").forEach(b =>
    b.addEventListener("click", () => { S.evalKey = b.dataset.sub; pushHash(); renderSubtabs(); render(); }));
}

function renderTickerList() {
  document.getElementById("tickerChangeBasis").textContent = `전일 종가 대비 · ${koMonthDay(D.latest.as_of)} 기준`;
  document.getElementById("tickerList").innerHTML = D.latest.tickers.map(t =>
    `<div class="nav-item ${t.group === "본사" ? "subject" : ""}">
       <span class="nav-dot" style="background:${slotColor(t.group)}"></span>
       <span class="nav-lbl">${esc(t.name)}</span>
       <span class="nav-chg ${dirClass(t.change_pct)}">${signed(t.change_pct, 1)}</span>
     </div>`).join("");
}

/* ── 내보내기 · 변경이력 (전 탭 공통) ─────────────────────────
 * 버튼은 각 카드가 그릴 때 data-export-* 속성으로 표식만 남기고, 실제
 * 리스너는 #view 컨테이너에 한 번만 위임 등록한다(내용은 매번 innerHTML 로
 * 통째로 바뀌므로, 버튼마다 리스너를 다시 붙이는 대신 위임이 안전하다). */

function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function exportTableCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const rows = [...table.querySelectorAll("tr")].map(tr =>
    [...tr.children].map(td => `"${(td.innerText || "").replace(/"/g, '""').replace(/\s+/g, " ").trim()}"`).join(","));
  downloadBlob("﻿" + rows.join("\n"), filename, "text/csv;charset=utf-8");
}

function exportSVGPNG(svgId, filename) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  const box = svg.viewBox.baseVal, scale = 2;
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = box.width * scale; canvas.height = box.height * scale;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = tok("--surface"); ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, box.width, box.height);
    canvas.toBlob(blob => downloadBlob(blob, filename, "image/png"));
  };
  img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
}

function wireExportDelegation() {
  document.getElementById("view").addEventListener("click", e => {
    const csvBtn = e.target.closest("[data-export-csv]");
    if (csvBtn) { const [id, name] = csvBtn.dataset.exportCsv.split("|"); exportTableCSV(id, name); return; }
    const pngBtn = e.target.closest("[data-export-png]");
    if (pngBtn) { const [id, name] = pngBtn.dataset.exportPng.split("|"); exportSVGPNG(id, name); }
  });
}

function csvButton(tableId, filename) {
  return `<button class="btn-mini" data-export-csv="${tableId}|${esc(filename)}">CSV 저장 ⤓</button>`;
}
function pngButton(svgId, filename) {
  return `<button class="btn-mini" data-export-png="${svgId}|${esc(filename)}">PNG 저장 ⤓</button>`;
}

/* ── 공용 조각 ─────────────────────────────────────────────── */

/** 점수 게이지 — 0·40·80·100 등 임의 개수의 눈금을 각자 위치에 배치한다.
 *  구간 폭이 다르므로(0~40 은 40점, 40~100 은 60점) 균등 배치하면 어긋난다. */
function scoreGauge(marks, value) {
  const min = marks[0].points, max = marks[marks.length - 1].points;
  const pctOf = p => Math.max(0, Math.min(100, (p - min) / (max - min) * 100));
  return `<div class="range">
    <div class="range-track">
      <span class="range-fill" style="width:${pctOf(value)}%"></span>
      ${marks.slice(1, -1).map(m => `<span class="range-tick" style="left:${pctOf(m.points)}%"></span>`).join("")}
      <span class="range-pin" style="left:calc(${pctOf(value)}% - 1.5px)"></span>
    </div>
    <div class="range-marks">${marks.map(m =>
      `<span class="range-mark" style="left:${pctOf(m.points)}%"><b>${m.points}점</b>${won(m.price)}원</span>`
    ).join("")}</div>
  </div>`;
}

function sparkline(values, color, w = 68, h = 22) {
  const v = (values || []).filter(x => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const d = v.map((x, i) =>
    `${i ? "L" : "M"}${(i * w / (v.length - 1)).toFixed(1)} ${(h - 2 - (x - lo) / span * (h - 4)).toFixed(1)}`
  ).join(" ");
  const rising = v[v.length - 1] >= v[0];
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${color || tok(rising ? "--up" : "--down")}"
      stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function statPair(left, right) {
  return `<div class="statpair">
    <span class="k">${esc(left[0])}</span><span class="k r">${esc(right[0])}</span>
    <span class="v">${left[1]}</span><span class="v r">${right[1]}</span></div>`;
}

/* ── 주가 평가 탭 ─────────────────────────────────────────── */

function coverageNotice() {
  const c = D.latest.coverage, items = [];
  if (c.gaps.length) items.push(`수집 공백 ${c.gaps.length}건 — ${c.gaps.map(esc).join(" / ")}`);
  if (c.unverified_months.length) items.push(`월봉 교차검증 불가 ${c.unverified_months.join(", ")}`);
  if (c.mismatched_months.length) items.push(`⚠️ 교차검증 불일치 ${c.mismatched_months.join(", ")}`);
  if (!c.gaps.length && !c.unverified_months.length && !c.mismatched_months.length)
    items.push(`데이터 ${c.verified_months.length}개월 전량 교차검증 통과 — 수집 공백·결측 0건`);
  items.push("공식 기준선 113,109원은 KIS 데이터로 재현되지 않는다 — 잠정 방식 +12.3점 / 최종 방식 −7.3점 편향. 최종평가 시 산술평균 기준으로 재산정되면 해소된다.");
  (D.latest.watchlist || []).forEach(w =>
    items.push(`${esc(w.name)} ${esc(w.report)} (${esc(w.filed_at)}) — 권리락 시 조정계수 등록 필요`));
  return `<div class="notice"><b>⚠ 데이터 신뢰도</b>
    <ul>${items.map(t => `<li>${t}</li>`).join("")}</ul></div>`;
}

/** SK이노베이션 거래량 보정 주가 — 종가에서 시작해 윈도우별 VWAP, 증감율까지. */
function windowSpecLabel(spec) {
  return spec === "1W" ? "1W (최근 5거래일)" : spec;
}

function subjectTable(m, weighted = true, friendlyDates = false) {
  const unit = weighted ? "거래량가중평균" : "종가평균";
  const dailyLabel = m.method === "B"
    ? "1일 거래량가중평균 주가 (종가 × 거래량 기준)"
    : "1일 거래량가중평균 주가 (실제 거래대금 기준)";
  const latestLabel = friendlyDates ? koMonthDay(m.eval_date) : "평가일";
  const baseLabel = friendlyDates ? `${String(D.latest.base_date).slice(0, 4)}년末` : "기준일";
  const rows = m.windows_now.map((w, i) => {
    const base = m.windows_base[i];
    const chg = w.vwap / base.vwap - 1;
    return `<tr><td>${esc(windowSpecLabel(w.spec))} ${unit}</td>
      <td class="num">${won(w.vwap)}원</td>
      <td class="num">${won(base.vwap)}원</td>
      <td class="num ${dirClass(chg)}">${signed(chg)}</td></tr>`;
  });
  return `<div class="group-sec">
    <div class="group-sec-h">SK이노베이션 ${weighted ? "거래량가중평균 주가" : "종가평균 (거래량 무시)"}</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>구간</th><th>${latestLabel}</th><th>${baseLabel}</th><th>증감율</th></tr></thead>
      <tbody>
        <tr><td>단순 종가</td><td class="num">${won(m.subject_close)}원</td>
          <td class="num">${won(m.subject_base_close)}원</td>
          <td class="num ${dirClass(m.subject_close / m.subject_base_close - 1)}">${signed(m.subject_close / m.subject_base_close - 1)}</td></tr>
        <tr><td>${dailyLabel}</td><td class="num">${won(m.subject_daily_weighted_price)}원</td>
          <td class="num">${won(m.subject_base_daily_weighted_price)}원</td>
          <td class="num ${dirClass(m.subject_daily_weighted_price / m.subject_base_daily_weighted_price - 1)}">${signed(m.subject_daily_weighted_price / m.subject_base_daily_weighted_price - 1)}</td></tr>
        ${rows.join("")}
        <tr class="subject"><td><b>${m.windows_now.length > 1 ? `${unit}의 산술평균` : unit}</b></td>
          <td class="num"><b>${won(m.subject_price)}원</b></td>
          <td class="num"><b>${won(m.subject_base_price)}원</b></td>
          <td class="num ${dirClass(m.subject_change)}"><b>${signed(m.subject_change)}</b></td></tr>
      </tbody></table></div>
  </div>`;
}

function subjectPriceChart(m, name = "SK이노베이션", mode = "daily") {
  const points = m.subject_chart || [];
  if (points.length < 2) return "";
  const W = 920, H = 250, P = { l: 46, r: 22, t: 20, b: 30 };
  const series = mode === "evaluation" ? [
    { key: "close", label: "단순 종가", color: "--series-1", width: 2.1 },
    { key: "vwap_2m", label: "2개월 거래량가중평균 주가", color: "--series-2", width: 2.3 },
    { key: "vwap_final", label: "2개월·1개월·최근 5거래일 거래량가중평균 주가의 산술평균", color: "--series-3", width: 2.8 },
  ] : [
    { key: "close", label: "단순 종가", color: "--series-1", width: 2.2 },
    { key: "daily_weighted_price", label: m.method === "B" ? "1일 거래량가중평균 주가 (종가와 동일)" : "1일 거래량가중평균 주가", color: "--series-3", width: 2.7 },
  ];
  const values = points.flatMap(p => series.map(s => p[s.key])).filter(v => v != null);
  let lo = Math.min(...values), hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const x = i => P.l + i / (points.length - 1) * (W - P.l - P.r);
  const y = value => P.t + (hi - value) / (hi - lo) * (H - P.t - P.b);
  const pathFor = key => {
    let d = "", drawing = false;
    points.forEach((p, i) => {
      if (p[key] == null) { drawing = false; return; }
      d += `${drawing ? "L" : "M"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)} `;
      drawing = true;
    });
    return d.trim();
  };
  let baseIndex = points.findIndex(p => p.date === D.latest.base_date);
  if (baseIndex < 0) baseIndex = points.reduce((best, p, i) => p.date <= D.latest.base_date ? i : best, 0);
  const first = points[0], basePoint = points[baseIndex], last = points.at(-1);
  const data = esc(JSON.stringify(points));
  const ticks = [0, baseIndex, points.length - 1].filter((v, i, a) => a.indexOf(v) === i).map(i =>
    `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="10.5" fill="${tok("--muted")}">${esc(koMonthDay(points[i].date))}</text>`
  ).join("");
  const paths = series.map(s => `<path d="${pathFor(s.key)}" fill="none" stroke="${tok(s.color)}" stroke-width="${s.width}" stroke-linejoin="round" stroke-linecap="round"/>`).join("");
  const dots = series.map(s => `<circle class="subject-chart-dot" data-chart-key="${s.key}" r="4" fill="${tok(s.color)}"/>`).join("");
  const legend = series.map(s => `<span><i style="background:${tok(s.color)}"></i>${esc(s.label)}</span>`).join("");
  return `<div class="subject-price-chart" data-subject-chart="${data}" data-subject-range="${esc(JSON.stringify({ lo, hi }))}" data-subject-mode="${mode}" data-subject-method="${esc(m.method)}">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(name)} ${esc(series.map(s => s.label).join(', '))} 추이">
      <line x1="${P.l}" y1="${y(lo).toFixed(1)}" x2="${W - P.r}" y2="${y(lo).toFixed(1)}" stroke="${tok("--grid")}"/>
      <line x1="${P.l}" y1="${y(hi).toFixed(1)}" x2="${W - P.r}" y2="${y(hi).toFixed(1)}" stroke="${tok("--grid")}"/>
      <line x1="${x(baseIndex).toFixed(1)}" y1="${P.t}" x2="${x(baseIndex).toFixed(1)}" y2="${H - P.b}" stroke="${tok("--axis")}" stroke-dasharray="4 4"/>
      ${paths}
      <g class="subject-chart-hover" hidden>
        <line class="subject-chart-guide" y1="${P.t}" y2="${H - P.b}" stroke="${tok("--muted")}" stroke-dasharray="3 3"/>
        ${dots}
      </g>
      <rect class="subject-chart-hit" x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${H - P.t - P.b}" fill="transparent"/>
      ${ticks}
    </svg>
    <div class="subject-chart-legend">${legend}</div>
    <div class="subject-chart-tooltip" hidden></div>
    <div class="mini-chart-meta">
      <span>${koMonthDay(first.date)} <b>단순 ${won(first.close)}원</b></span>
      <span>${String(D.latest.base_date).slice(0,4)}년末 <b>단순 ${won(basePoint.close)}원</b></span>
      <span>${koMonthDay(last.date)} <b>단순 ${won(last.close)}원</b></span>
    </div>
  </div>`;
}

function bindSubjectPriceCharts(root) {
  root.querySelectorAll("[data-subject-chart]").forEach(chart => {
    const points = JSON.parse(chart.dataset.subjectChart);
    const { lo, hi } = JSON.parse(chart.dataset.subjectRange);
    const svg = chart.querySelector("svg"), hit = chart.querySelector(".subject-chart-hit");
    const hover = chart.querySelector(".subject-chart-hover"), guide = chart.querySelector(".subject-chart-guide");
    const series = chart.dataset.subjectMode === "evaluation" ? [
      { key: "close", label: "단순 종가" },
      { key: "vwap_2m", label: "2개월 거래량가중평균 주가" },
      { key: "vwap_final", label: "최종 산술평균" },
    ] : [
      { key: "close", label: "단순 종가" },
      { key: "daily_weighted_price", label: chart.dataset.subjectMethod === "B" ? "1일 거래량가중평균 주가 (종가와 동일)" : "1일 거래량가중평균 주가" },
    ];
    const dots = new Map([...chart.querySelectorAll(".subject-chart-dot")].map(dot => [dot.dataset.chartKey, dot]));
    const tip = chart.querySelector(".subject-chart-tooltip"), W = 920, H = 250, P = { l: 46, r: 22, t: 20, b: 30 };
    const show = event => {
      const rect = svg.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const i = Math.round(((ratio * W) - P.l) / (W - P.l - P.r) * (points.length - 1));
      const p = points[Math.max(0, Math.min(points.length - 1, i))];
      const cx = P.l + i / (points.length - 1) * (W - P.l - P.r);
      const y = value => P.t + (hi - value) / (hi - lo) * (H - P.t - P.b);
      hover.hidden = false;
      guide.setAttribute("x1", cx); guide.setAttribute("x2", cx);
      series.forEach(s => {
        const dot = dots.get(s.key), value = p[s.key];
        dot.setAttribute("cx", cx);
        if (value == null) dot.setAttribute("visibility", "hidden");
        else { dot.setAttribute("cy", y(value)); dot.removeAttribute("visibility"); }
      });
      tip.innerHTML = `<b>${koMonthDay(p.date)}</b>${series.map(s => `<span>${esc(s.label)} <strong>${p[s.key] == null ? "계산 시작 전" : `${won(p[s.key])}원`}</strong></span>`).join("")}`;
      tip.hidden = false;
      tip.style.left = `${Math.max(8, Math.min(chart.clientWidth - tip.offsetWidth - 8, event.clientX - rect.left + 12))}px`;
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerleave", () => { hover.hidden = true; tip.hidden = true; });
  });
}

function graphStartDate() {
  const [year, month, day] = D.latest.base_date.split("-").map(Number);
  const total = year * 12 + month - 1 - 2;
  const startYear = Math.floor(total / 12);
  const startMonth = ((total % 12) + 12) % 12;
  const lastDay = new Date(Date.UTC(startYear, startMonth + 1, 0)).getUTCDate();
  return new Date(Date.UTC(startYear, startMonth, Math.min(day, lastDay) + 1))
    .toISOString().slice(0, 10);
}

function miniCloseChart(code, name, compact = false, endDate = D.latest.as_of) {
  const bars = D.bars[code];
  if (!bars) return "";
  const start = graphStartDate();
  const end = endDate;
  const points = bars.dates.map((date, i) => ({ date, close: bars.close[i] }))
    .filter(p => p.date >= start && p.date <= end && p.close != null);
  if (points.length < 2) return "";

  const W = 640, H = compact ? 129 : 140;
  const P = { l: 62, r: 12, t: 12, b: 24 };
  let lo = Math.min(...points.map(p => p.close));
  let hi = Math.max(...points.map(p => p.close));
  if (lo === hi) { lo *= .99; hi *= 1.01; }
  const x = i => P.l + i / (points.length - 1) * (W - P.l - P.r);
  const y = value => P.t + (hi - value) / (hi - lo) * (H - P.t - P.b);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join(" ");
  let baseIndex = points.findIndex(p => p.date === D.latest.base_date);
  if (baseIndex < 0) baseIndex = points.reduce((best, p, i) => p.date <= D.latest.base_date ? i : best, 0);
  const basePoint = points[baseIndex];
  const first = points[0], last = points.at(-1);
  const meta = D.latest.tickers.find(t => t.code === code);
  const color = slotColor(meta?.group || "본사");

  return `<div class="mini-close-chart${compact ? " compact" : ""}">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)} 종가 추이">
      <line x1="${P.l}" y1="${y(lo)}" x2="${W-P.r}" y2="${y(lo)}" stroke="${tok("--grid")}"/>
      <line x1="${P.l}" y1="${y(hi)}" x2="${W-P.r}" y2="${y(hi)}" stroke="${tok("--grid")}"/>
      <text x="${P.l - 6}" y="${(y(lo) + 3).toFixed(1)}" text-anchor="end" font-size="9.5" fill="${tok("--muted")}">${won(lo)}원</text>
      <text x="${P.l - 6}" y="${(y(hi) + 3).toFixed(1)}" text-anchor="end" font-size="9.5" fill="${tok("--muted")}">${won(hi)}원</text>
      <line x1="${x(baseIndex)}" y1="${P.t}" x2="${x(baseIndex)}" y2="${H-P.b}"
        stroke="${tok("--axis")}" stroke-dasharray="4 4"/>
      <path d="${path}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${x(points.length-1)}" cy="${y(last.close)}" r="3.5" fill="${color}"/>
      <text x="${x(baseIndex)}" y="${H-7}" text-anchor="middle" font-size="10" fill="${tok("--muted")}">${esc(String(D.latest.base_date).slice(0,4)+"년末")}</text>
    </svg>
    <div class="mini-chart-meta">
      <span>${koMonthDay(first.date)} <b>${won(first.close)}원</b></span>
      <span>${String(D.latest.base_date).slice(0,4)}년末 <b>${won(basePoint.close)}원</b></span>
      <span>${koMonthDay(last.date)} <b>${won(last.close)}원</b></span>
    </div>
  </div>`;
}

function peerPopover(mem, m) {
  if (!mem.windows_now?.length || !mem.code) return "";
  const values = mem.windows_now.map(w => won(w.vwap));
  return `<div class="peer-popover" role="tooltip">
    <div class="peer-pop-head"><b>${esc(mem.name)}</b><span>${koMonthDay(m.eval_date)} 기준 · 종가 추이</span></div>
    ${miniCloseChart(mem.code, mem.name, true, m.eval_date)}
    <div class="peer-calc-title">거래량가중평균의 산술평균</div>
    <div class="peer-window-values">
      ${mem.windows_now.map(w => `<span><small>${esc(windowSpecLabel(w.spec))}</small><b>${won(w.vwap)}원</b></span>`).join("")}
    </div>
    <div class="peer-calc-formula">(${values.join(" + ")}) ÷ ${values.length} = <b>${won(mem.price)}원</b></div>
    <div class="peer-base-line">${String(D.latest.base_date).slice(0,4)}년末 ${won(mem.base_price)}원 대비
      <b class="${dirClass(mem.change)}">${signed(mem.change)}</b></div>
  </div>`;
}

/** Peer 선정 적정성 popover — 27년 과제 설계 탭의 Peer 종목 포함/제외에서 쓴다.
 *  ①사업 유사도 ④독립성은 config/peer_criteria.yaml 에 사람이 등록한 판단,
 *  ②시가총액 ③유동성은 pipeline/build_site.py 가 최신 시세로 매번 계산한 값이다. */
function peerCriteriaRow(index, label, ratingBadge, note) {
  return `<div class="peer-eval-row">
      <span class="peer-eval-label">${index} ${esc(label)}</span>${ratingBadge}
    </div>
    <p class="peer-eval-note">${esc(note || "")}</p>`;
}
function peerCriteriaPopover(t) {
  const e = t.peer_eval;
  if (!e) return "";
  const cap = e.market_cap, liq = e.liquidity;
  const capBadge = `<span class="badge ${peerRatingClass(cap.rating)}">${esc(cap.rating)}</span>`;
  const liqBadge = liq.rank
    ? `<span class="badge grp">Peer ${liq.of}개사 중 ${liq.rank}위</span>` : "";
  const bizBadge = e.business_match
    ? `<span class="badge ${peerRatingClass(e.business_match.rating)}">${esc(e.business_match.rating)}</span>` : "";
  const indBadge = e.independence
    ? `<span class="badge ${peerRatingClass(e.independence.rating)}">${esc(e.independence.rating)}</span>` : "";
  return `<div class="peer-popover peer-eval-popover" role="tooltip">
    <div class="peer-pop-head"><b>${esc(t.name)}</b><span>Peer 선정 적정성</span></div>
    ${peerCriteriaRow("①", "사업 유사도", bizBadge, e.business_match?.note)}
    ${peerCriteriaRow("②", "시가총액 비교가능성", capBadge,
      `SK이노베이션 대비 ${cap.ratio_to_subject != null ? cap.ratio_to_subject.toFixed(2) + "배" : "확인 불가"}` +
      (cap.value_100m != null ? ` · 시가총액 ${jo(cap.value_100m)}` : ""))}
    ${peerCriteriaRow("③", "거래 유동성", liqBadge,
      liq.avg_daily_trading_value != null
        ? `최근 ${liq.window_days}거래일 일평균 거래대금 ${eok(liq.avg_daily_trading_value)}`
        : "거래대금 데이터 부족")}
    ${peerCriteriaRow("④", "독립성(이해상충)", indBadge, e.independence?.note)}
  </div>`;
}

/** Peer 보정 — 그룹별로 묶는다. 60:40 가중치가 그룹 단위이므로 개별사가 아니라
 *  그룹 평균이 실제로 점수에 들어가는 값이다. */
function peerSection(m, interactive = false) {
  const grp = (name) => {
    const g = m.groups[name];
    return `<div class="peer-grp">
      <div class="peer-grp-h"><span>${esc(name)} 그룹</span><span class="w">가중치 ${(g.weight * 100).toFixed(0)}%</span></div>
      ${g.members.map(mem => interactive
        ? `<div class="m peer-member" tabindex="0" aria-label="${esc(mem.name)} 상세 보기">
            <span class="peer-name">${esc(mem.name)}<small>그래프 보기</small></span>
            <span class="${dirClass(mem.change)}">${signed(mem.change)}</span>
            ${peerPopover(mem, m)}
          </div>`
        : `<div class="m"><span>${esc(mem.name)}</span><span class="${dirClass(mem.change)}">${signed(mem.change)}</span></div>`
      ).join("")}
      <div class="m"><b>그룹 평균</b><b class="${dirClass(g.average)}">${signed(g.average)}</b></div>
    </div>`;
  };
  return `<div class="group-sec">
    <div class="group-sec-h">Peer 보정 — 그룹별 증감율
      ${interactive ? '<span class="hover-help">회사명에 마우스를 올려 상세 확인</span>' : ""}
    </div>
    ${grp("에화")}${grp("배소")}
    <div class="wtable"><div class="r sum"><span class="k">Peer 증감율 (0.6×에화 + 0.4×배소)</span>
      <span class="v ${dirClass(m.peer_change)}">${signed(m.peer_change)}</span></div></div>
  </div>`;
}

function finalCalculation(m) {
  return `<div class="actual-calc">
    <div class="actual-calc-row">
      <span class="actual-label">상대 증감률</span>
      <div class="actual-expression">
        <span class="actual-tag tag-2">② ${signed(m.subject_change)}</span>
        <span>−</span>
        <span class="actual-tag tag-3">③ ${signed(m.peer_change)}</span>
        <span>=</span>
        <b class="${dirClass(m.relative_change)}">${signed(m.relative_change)}</b>
      </div>
    </div>
    <div class="actual-calc-row final">
      <span class="actual-label">평가주가</span>
      <div class="actual-expression">
        <span class="actual-tag tag-1">① ${won(m.subject_price)}원</span>
        <span>÷ [1 − (${signed(m.relative_change)})] =</span>
        <strong>${won(m.eval_price)}원</strong>
      </div>
    </div>
    <div class="actual-note">화면의 퍼센트와 금액은 보기 쉽게 반올림해 표시합니다.</div>
  </div>`;
}

function calcSection(m, xLabel, friendly = false) {
  return `<div class="group-sec">
    <div class="group-sec-h">평가주가 산출</div>
    <div class="calc-final">
      <div class="r"><span>${esc(xLabel || "상대 증감률 x = SK이노베이션 − Peer")}</span><span class="${dirClass(m.relative_change)}">${signed(m.relative_change)}</span></div>
      <div class="r"><span>${friendly ? "Peer 보정 배수 = 1 ÷ (1 − 위 증감률)" : "배수 1/(1−x)"}</span><span>${m.multiplier.toFixed(4)}배</span></div>
      <div class="r big"><span>평가주가</span><span>${won(m.eval_price)}원</span></div>
    </div>
  </div>`;
}

function modeBlock(m, label, sub, baseline = "V3") {
  const s = m.scores[baseline];
  return `<div class="mode-block">
    <div class="mode-block-head">
      <div class="name">${esc(label)}<span class="sub">${esc(sub)}</span></div>
      <div class="mode-block-score">
        <b class="${dirClass(s.value - 40)}">${pts(s.value)}점</b>
        <span class="raw">산식상 ${pts(s.raw)}점${s.clipped ? " · 0~100점 범위 적용" : ""}</span>
      </div>
    </div>
    ${subjectTable(m)}
    ${peerSection(m)}
    ${calcSection(m)}
  </div>`;
}

function baselineTable(m) {
  return `<div class="tbl-wrap"><table>
    <thead><tr><th>기준선</th><th>앵커</th><th>원값</th><th>점수</th><th>클리핑</th></tr></thead>
    <tbody>${["V3", "V1", "V2"].filter(k => m.scores[k]).map(k => {
      const s = m.scores[k], meta = D.latest.baselines[k] || {};
      return `<tr${meta.official ? ' class="subject"' : ""}>
        <td>${esc(k)} <span class="badge grp">${esc(meta.label || "")}</span>${meta.official ? ' <span class="badge brand">공식</span>' : ""}</td>
        <td class="num">${won(s.anchor)}원</td>
        <td class="num ${dirClass(s.raw)}">${pts(s.raw)}</td>
        <td class="num"><b>${pts(s.value)}점</b></td>
        <td>${s.clipped ? '<span class="badge warn">적용</span>' : "—"}</td></tr>`;
    }).join("")}</tbody></table></div>`;
}

/** 목표 역산 계산기 — "몇 점 받으려면 SK 주가가 얼마여야 하나", Peer 는 현재 수준 고정. */
function targetCard(m) {
  const rows = [0, 40, 80, 100].map(pt => {
    const t = m.targets[pt];
    return `<tr><td>${pt}점</td>
      <td class="num">${won(t.needed_vwap)}원</td>
      <td class="num ${dirClass(t.needed_change_from_base)}">${signed(t.needed_change_from_base)}</td></tr>`;
  }).join("");
  return `<div class="card">
    <h3>목표 역산 계산기 <span class="sub">Peer 현재 수준 고정 · 필요한 SK 거래량 보정 주가</span></h3>
    <div class="tbl-wrap"><table>
      <thead><tr><th>목표 점수</th><th>필요 보정주가</th><th>기준일 대비 필요 변동</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </div>`;
}

/** Peer 기여도 분해(Waterfall) — 출발점(SK 단독 성과)에서 종목을 하나씩 실제
 *  증감율로 되돌리며 점수가 어떻게 바뀌는지 누적한다. */
function waterfallChart(m) {
  const steps = m.waterfall, max = 100;
  const rows = steps.map((s, i) => {
    const isBase = i === 0;
    if (isBase) {
      return `<div class="bar-row"><span class="lb"><b>${esc(s.name)}</b></span>
        <span class="bar"><i style="left:0%;width:${Math.max(0, Math.min(100, s.score))}%;background:${tok("--series-1")}"></i></span>
        <span class="n">${pts(s.score)}점</span></div>`;
    }
    const prev = steps[i - 1].score, cur = s.score;
    const lo = Math.max(0, Math.min(prev, cur)), w = Math.max(Math.abs(cur - prev), 0.6);
    return `<div class="bar-row"><span class="lb">
        <span class="dot" style="background:${slotColor(s.group)}"></span>${esc(s.name)}</span>
      <span class="bar"><i style="left:${lo}%;width:${w}%;background:${s.delta >= 0 ? tok("--up") : tok("--down")}"></i></span>
      <span class="n ${dirClass(s.delta)}">${signedPts(s.delta)}</span></div>`;
  }).join("");
  return `<div class="card">
    <h3>Peer 기여도 분해 <span class="sub">SK 단독 성과에서 출발해 종목별 실제 증감율을 하나씩 반영</span></h3>
    <div style="display:flex;flex-direction:column;gap:9px">${rows}</div>
  </div>`;
}

function sensitivityCard(m) {
  const rows = m.sensitivity.rows.map(r => `<tr>
    <td>${esc(r.target)}</td><td>${esc(r.shift)}</td>
    <td class="num">${pts(r.score)}점</td>
    <td class="num ${dirClass(r.delta)}">${signedPts(r.delta)}</td></tr>`).join("");
  return `<div class="card">
    <h3>민감도 테이블 <span class="sub">기준 ${pts(m.sensitivity.base_score)}점 · ±1%p 변동 시 점수 변화</span></h3>
    <div class="tbl-wrap"><table>
      <thead><tr><th>변수</th><th>변동</th><th>점수</th><th>변화</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </div>`;
}

function historicalPanel(kind, label, sub, body) {
  return `<div class="history-mode-panel ${kind}">
    <div class="history-mode-head">
      <b>${esc(label)}</b><span>${esc(sub)}</span>
    </div>
    ${body}
  </div>`;
}

function historicalStep(step, title, sub, provisionalBody, finalBody) {
  return `<section class="history-compare-step step-${step}">
    <div class="history-step-head">
      <span class="step-badge">${step}</span>
      <div><b>${esc(title)}</b><span>${esc(sub)}</span></div>
    </div>
    <div class="history-compare-grid">
      ${historicalPanel("provisional", "잠정 방식", "2개월 거래량가중평균", provisionalBody)}
      ${historicalPanel("final", "최종 방식", "2개월·1개월·최근 5거래일 산술평균", finalBody)}
    </div>
  </section>`;
}

function historicalSubjectStep(m) {
  return `${indexedScoreFormula(1)}
    <p class="step-copy">각 기간은 (종가 × 거래량) 합계 ÷ 거래량 합계로 계산합니다.</p>
    ${subjectTable(m, true, true)}
    <div class="step-result">① 산식에 사용되는 값 <b>${won(m.subject_price)}원</b></div>`;
}

function historicalChangeStep(m) {
  return `${indexedScoreFormula(2)}
    <p class="step-copy">${koMonthDay(m.eval_date)} 거래량가중평균을 ${String(D.latest.base_date).slice(0,4)}년末 거래량가중평균과 비교합니다.</p>
    <div class="step-equation">
      <span>(</span><b>${won(m.subject_price)}원</b><span>÷</span>
      <b>${won(m.subject_base_price)}원</b><span>) − 1 =</span>
      <strong class="${dirClass(m.subject_change)}">${signed(m.subject_change)}</strong>
    </div>`;
}

function historicalPeerStep(m) {
  return `${indexedScoreFormula(3, true)}
    <p class="step-copy">각 그룹 안의 종목 증감률을 평균한 뒤, 에화 그룹 60%와 배소 그룹 40%를 반영합니다.</p>
    ${peerSection(m, true)}`;
}

function historicalPriceStep(m) {
  return `${indexedScoreFormula(4)}
    <p class="step-copy">①을 분자로 사용하고, ②에서 ③을 뺀 값을 분모에 반영해 평가주가를 계산합니다.</p>
    ${finalCalculation(m)}`;
}

function renderHistoricalScore(V, view) {
  const L = D.latest;
  const baseline = "V3";
  const prov = view.modes["잠정"];
  const fin = view.modes["최종"];
  const officialMode = view.official_mode;
  const officialResult = view.modes[officialMode];
  const officialScore = officialResult.scores[baseline];
  const marks = officialResult.score_marks[baseline];
  const appliedScoreNote = s => s.raw < 0
    ? `산식상 ${pts(s.raw)}점 → 최저 0점 적용`
    : `산식상 ${pts(s.raw)}점`;

  V.innerHTML = `
    <div class="hero">
      <div class="eyebrow">${esc(view.label)} · ${esc(view.date)} 기준${view.confirmed ? " · 확정" : ""} · 연초 안내 기준 가격 ${won(officialScore.anchor)}원 = 40점</div>
      <div class="score-main">
        <b>${pts(officialScore.value)}</b><span class="unit">점</span>
        <span class="raw">평가 당시 적용 방식(${esc(officialMode)}) · ${appliedScoreNote(officialScore)} · 평가주가 ${won(officialResult.eval_price)}원</span>
      </div>
      ${scoreGauge(marks, officialScore.value)}
      <div class="indexed-formula history-formula">
        <div class="formula-kicker">평가주가 산식</div>
        ${indexedScoreFormula(0, true)}
        <div class="formula-guide">같은 번호를 따라가면 잠정 방식과 최종 방식의 차이를 단계별로 비교할 수 있습니다.</div>
      </div>
      <div class="mode-grid">
        <div class="mode"><span class="t">잠정 방식 · 2개월 거래량가중평균</span>
          <span class="v">${pts(prov.scores[baseline].value)}점</span>
          <span class="d">${appliedScoreNote(prov.scores[baseline])} · 평가주가 ${won(prov.eval_price)}원</span></div>
        <div class="mode"><span class="t">최종 방식 · 2개월·1개월·최근 5거래일 산술평균</span>
          <span class="v">${pts(fin.scores[baseline].value)}점</span>
          <span class="d">${appliedScoreNote(fin.scores[baseline])} · 평가주가 ${won(fin.eval_price)}원</span></div>
      </div>
      <div class="hero-note">잠정 방식은 계산값이 0점보다 낮아 최저 0점이 적용됐고, 최종 방식은 <b>${pts(fin.scores[baseline].value)}점</b>입니다.</div>
    </div>

    <div class="card">
      <h3>산출 과정 — 방식별 비교 <span class="sub">기준일 ${esc(L.base_date)} · 연초 안내 기준 가격 ${won(officialScore.anchor)}원 = 40점</span></h3>
      <div class="history-shared-chart">
        <div>
          <b>SK이노베이션 주가 추이</b>
          <span>단순 종가와 1일 거래량가중평균 종가 · ${String(L.base_date).slice(0,4)}년末 기준 2개월 전부터 ${koMonthDay(view.date)}까지</span>
        </div>
        ${subjectPriceChart(fin)}
      </div>
      <div class="history-compare-steps">
        ${historicalStep(1, "SK이노베이션 단순 종가와 1일 거래량가중평균 종가", "산식의 분자",
          historicalSubjectStep(prov), historicalSubjectStep(fin))}
        ${historicalStep(2, "SK이노베이션 증감률", "괄호 안 첫 번째 값",
          historicalChangeStep(prov), historicalChangeStep(fin))}
        ${historicalStep(3, "Peer 증감률", "괄호 안 두 번째 값",
          historicalPeerStep(prov), historicalPeerStep(fin))}
        ${historicalStep(4, "평가주가 산출", "1~3단계 결과를 산식에 결합",
          historicalPriceStep(prov), historicalPriceStep(fin))}
      </div>
    </div>

    <div class="card">
      <h3>점수 기준 <span class="sub">2026년 수립 시 안내된 가격을 40점 기준으로 적용</span></h3>
      <div class="statpair">
        <span class="k">40점 기준 가격</span><span class="v r">${won(officialScore.anchor)}원</span>
        <span class="k">잠정 방식</span><span class="v r">${pts(prov.scores[baseline].value)}점</span>
        <span class="k">최종 방식</span><span class="v r">${pts(fin.scores[baseline].value)}점</span>
      </div>
    </div>

    ${coverageNotice()}`;
  bindSubjectPriceCharts(V);
}

function indexedScoreFormula(active = 0, showPeer = false) {
  const term = (step, label) => {
    const state = active ? (active === step ? " active" : " dimmed") : "";
    return `<span class="formula-term formula-step-${step}${state}"><span class="formula-index">${step}</span>${label}</span>`;
  };
  const outputState = active ? (active === 4 ? " active" : " dimmed") : "";
  return `<div class="score-formula">
      <span class="formula-output${outputState}"><span class="formula-index">4</span>평가주가</span>
      <span class="formula-op">=</span>
      ${term(1, "SK이노베이션 거래량가중평균")}
      <span class="formula-op">÷ [1 − (</span>
      ${term(2, "SK이노베이션 증감률")}
      <span class="formula-op">−</span>
      ${term(3, "Peer 증감률")}
      <span class="formula-op">)]</span>
    </div>
    ${showPeer ? `<div class="peer-formula${active && active !== 3 ? " dimmed" : active === 3 ? " active" : ""}">
      <span class="formula-index">3</span><b>Peer 증감률</b>
      <span>= 0.6 × 에화 그룹 평균 + 0.4 × 배소 그룹 평균</span>
    </div>` : ""}`;
}

function renderScore(V) {
  const view = currentView();
  if (view.key !== "today") return renderHistoricalScore(V, view);
  const result = view.modes["최종"];
  const score = result.scores.V2;
  const marks = result.score_marks.V2;
  const baseYear = String(D.latest.base_date).slice(0, 4);

  V.innerHTML = `
    <div class="hero">
      <div class="eyebrow">${koDate(view.date)} 기준</div>
      <div class="score-main">
        <b>${pts(score.value)}</b><span class="unit">점</span>
        <span class="raw">평가 주가 ${won(result.eval_price)}원</span>
      </div>
      ${scoreGauge(marks, score.value)}
      <div class="hero-note">40점 기준가격 <b>${won(score.anchor)}원</b>은 수기 검산으로 확정한 목표값입니다. 증감률 계산에 쓰는 ${baseYear}년末 평가주가는 아래와 같은 기간 규칙으로 별도 계산합니다.</div>
      <div class="indexed-formula">
        <div class="formula-kicker">평가주가 산식</div>
        ${indexedScoreFormula(0, true)}
        <div class="formula-guide">산식의 번호와 아래 산출 단계의 번호가 서로 연결됩니다.</div>
      </div>
    </div>

    <div class="card">
      <h3>점수 산출 <span class="sub">평가주가를 만드는 네 단계</span></h3>
      <div class="calc-steps">
        <section class="calc-step step-1">
          <div class="calc-step-head">
            <span class="step-badge">1</span>
            <div><b>SK이노베이션 거래량가중평균 주가</b><span>산식의 분자</span></div>
          </div>
          ${indexedScoreFormula(1)}
          <p class="step-copy">각 기간은 (종가 × 거래량) 합계 ÷ 거래량 합계로 계산하고, 2개월·1개월·최근 5거래일 값을 산술평균합니다.</p>
          ${subjectTable(result, true, true)}
          <div class="step-result">① 산식에 사용되는 값 <b>${won(result.subject_price)}원</b></div>
          <div class="chart-caption">SK이노베이션 주가 추이 · 단순 종가·2개월 거래량가중평균 주가·최종 산술평균 · ${baseYear}년末 기준 2개월 전부터 ${koMonthDay(result.eval_date)}까지</div>
          ${subjectPriceChart(result, "SK이노베이션", "evaluation")}
        </section>

        <section class="calc-step step-2">
          <div class="calc-step-head">
            <span class="step-badge">2</span>
            <div><b>SK이노베이션 증감률</b><span>괄호 안 첫 번째 값</span></div>
          </div>
          ${indexedScoreFormula(2)}
          <p class="step-copy">${koMonthDay(result.eval_date)} 거래량가중평균을 ${baseYear}년末 거래량가중평균과 비교합니다.</p>
          <div class="step-equation">
            <span>(</span><b>${won(result.subject_price)}원</b><span>÷</span>
            <b>${won(result.subject_base_price)}원</b><span>) − 1 =</span>
            <strong class="${dirClass(result.subject_change)}">${signed(result.subject_change)}</strong>
          </div>
        </section>

        <section class="calc-step step-3">
          <div class="calc-step-head">
            <span class="step-badge">3</span>
            <div><b>Peer 증감률</b><span>괄호 안 두 번째 값</span></div>
          </div>
          ${indexedScoreFormula(3, true)}
          <p class="step-copy">각 그룹 안의 종목 증감률을 단순 평균한 뒤, 에화 그룹 60%와 배소 그룹 40%를 가중 평균합니다.</p>
          ${peerSection(result, true)}
        </section>

        <section class="calc-step step-4">
          <div class="calc-step-head">
            <span class="step-badge">4</span>
            <div><b>평가주가 산출</b><span>1~3단계 결과를 산식에 결합</span></div>
          </div>
          ${indexedScoreFormula(4)}
          <p class="step-copy">①을 분자로 사용하고, ②에서 ③을 뺀 값을 분모에 반영해 평가주가를 계산합니다.</p>
          ${finalCalculation(result)}
        </section>
      </div>
    </div>

    <div class="card">
      <h3>점수 기준 <span class="sub">기준 가격을 40점으로 환산</span></h3>
      <div class="hero-note"><b>⑤ 점수 환산</b> · 기준 가격의 85%는 0점, 기준 가격은 40점, 기준 가격의 115%는 100점입니다. 범위 밖 값은 0~100점으로 제한합니다.</div>
      <div class="statpair">
        <span class="k">기준 가격</span><span class="v r">${won(score.anchor)}원</span>
        <span class="k">평가 주가</span><span class="v r">${won(result.eval_price)}원</span>
        <span class="k">현재 점수</span><span class="v r">${pts(score.value)}점</span>
      </div>
    </div>`;
  bindSubjectPriceCharts(V);
}

function indexChart() {
  const H = D.history, W = 900, HT = 300, PAD = { t: 16, r: 84, b: 28, l: 48 };
  const series = [
    ["SK이노베이션", H.indexed[H.subject], tok("--series-1"), 2.6],
    ["에/화 그룹 평균", H.groups["에화"], tok("--series-2"), 1.9],
    ["배/소 그룹 평균", H.groups["배소"], tok("--series-3"), 1.9],
  ];
  const n = H.dates.length;
  const vals = series.flatMap(s => s[1].filter(v => v != null));
  if (!n || !vals.length) return `<div class="empty">차트 데이터가 없습니다</div>`;
  const lo = Math.min(...vals, 100), hi = Math.max(...vals, 100);
  const pad = (hi - lo) * 0.1 || 5, yMin = lo - pad, yMax = hi + pad;
  const X = i => PAD.l + (n === 1 ? 0 : i * (W - PAD.l - PAD.r) / (n - 1));
  const Y = v => PAD.t + (yMax - v) * (HT - PAD.t - PAD.b) / (yMax - yMin);
  const gaps = new Set(H.gap_after || []);

  const grid = [yMin, (yMin + yMax) / 2, yMax, 100].map(v =>
    `<line x1="${PAD.l}" y1="${Y(v).toFixed(1)}" x2="${W - PAD.r}" y2="${Y(v).toFixed(1)}"
       stroke="${v === 100 ? tok("--axis") : tok("--grid")}" stroke-width="1"
       ${v === 100 ? 'stroke-dasharray="4 3"' : ""}/>
     <text x="${PAD.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" font-size="10.5"
       fill="${tok("--muted")}">${v.toFixed(0)}</text>`).join("");

  const paths = series.map(([name, ys, color, wdt]) => {
    let d = "", pen = false;
    ys.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)} `;
      pen = !gaps.has(i);
    });
    const last = ys.reduce((a, v, i) => v == null ? a : i, -1);
    const label = last >= 0
      ? `<text x="${(X(last) + 7).toFixed(1)}" y="${(Y(ys[last]) + 3.5).toFixed(1)}"
           font-size="10.5" fill="${color}" font-weight="700">${esc(ys[last].toFixed(0))}</text>` : "";
    return `<path d="${d.trim()}" fill="none" stroke="${color}" stroke-width="${wdt}"
      stroke-linejoin="round" stroke-linecap="round"/>${label}`;
  }).join("");

  const ticks = [0, Math.floor(n / 3), Math.floor(2 * n / 3), n - 1].map(i =>
    `<text x="${X(i).toFixed(1)}" y="${HT - 7}" text-anchor="middle" font-size="10.5"
       fill="${tok("--muted")}">${esc(H.dates[i].slice(2))}</text>`).join("");

  const hoverDots = series.map(([, , color], i) =>
    `<circle class="index-chart-dot" data-series="${i}" r="4" fill="${color}"/>`).join("");

  return `<div class="index-chart-wrap" data-index-chart data-y-min="${yMin}" data-y-max="${yMax}">
    <div class="chart"><svg id="indexChartSvg" viewBox="0 0 ${W} ${HT}" preserveAspectRatio="none" role="img"
      aria-label="기준일 대비 주가 지수 추이 — SK이노베이션, 에/화 그룹 평균, 배/소 그룹 평균">
      ${grid}${paths}
      <g class="index-chart-hover" hidden>
        <line class="index-chart-guide" y1="${PAD.t}" y2="${HT - PAD.b}" stroke="${tok("--muted")}" stroke-dasharray="3 3"/>
        ${hoverDots}
      </g>
      <rect class="index-chart-hit" x="${PAD.l}" y="${PAD.t}" width="${W - PAD.l - PAD.r}"
        height="${HT - PAD.t - PAD.b}" fill="transparent"/>
      ${ticks}</svg></div>
    <div class="index-chart-tooltip" role="status" aria-live="polite" hidden></div>
  </div>
    <div class="legend">${series.map(([name, , c]) =>
      `<span><i style="background:${c}"></i>${esc(name)}</span>`).join("")}</div>`;
}

function bindIndexChart(root) {
  const wrap = root.querySelector("[data-index-chart]");
  if (!wrap) return;
  const H = D.history, W = 900, HT = 300, PAD = { t: 16, r: 84, b: 28, l: 48 };
  const series = [
    ["SK이노베이션", H.indexed[H.subject], tok("--series-1")],
    ["에/화 그룹 평균", H.groups["에화"], tok("--series-2")],
    ["배/소 그룹 평균", H.groups["배소"], tok("--series-3")],
  ];
  const svg = wrap.querySelector("svg"), hit = wrap.querySelector(".index-chart-hit");
  const hover = wrap.querySelector(".index-chart-hover"), guide = wrap.querySelector(".index-chart-guide");
  const dots = [...wrap.querySelectorAll(".index-chart-dot")];
  const tooltip = wrap.querySelector(".index-chart-tooltip");
  const yMin = Number(wrap.dataset.yMin), yMax = Number(wrap.dataset.yMax);
  const X = i => PAD.l + i * (W - PAD.l - PAD.r) / Math.max(1, H.dates.length - 1);
  const Y = v => PAD.t + (yMax - v) * (HT - PAD.t - PAD.b) / (yMax - yMin);

  const show = event => {
    const svgRect = svg.getBoundingClientRect();
    const svgX = (event.clientX - svgRect.left) / svgRect.width * W;
    const ratio = (svgX - PAD.l) / (W - PAD.l - PAD.r);
    const index = Math.max(0, Math.min(H.dates.length - 1, Math.round(ratio * (H.dates.length - 1))));
    const cx = X(index);
    guide.setAttribute("x1", cx); guide.setAttribute("x2", cx);
    hover.hidden = false;
    dots.forEach((dot, i) => {
      const value = series[i][1][index];
      dot.setAttribute("cx", cx);
      if (value == null) dot.setAttribute("visibility", "hidden");
      else {
        dot.setAttribute("cy", Y(value));
        dot.removeAttribute("visibility");
      }
    });
    tooltip.innerHTML = `<b>${koDate(H.dates[index])}</b>${series.map(([name, values, color]) => {
      const value = values[index];
      return `<span><i style="background:${color}"></i><em>${esc(name)}</em><strong>${value == null ? "—" : value.toFixed(2)}</strong><small>${value == null ? "" : signed(value / 100 - 1)}</small></span>`;
    }).join("")}`;
    tooltip.hidden = false;
    const wrapRect = wrap.getBoundingClientRect();
    const pointerX = event.clientX - wrapRect.left;
    tooltip.style.left = `${Math.max(8, Math.min(wrap.clientWidth - tooltip.offsetWidth - 8, pointerX + 12))}px`;
  };
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerdown", show);
  hit.addEventListener("pointerleave", () => { hover.hidden = true; tooltip.hidden = true; });
}

function groupBars() {
  const rows = D.latest.tickers.filter(t => t.group !== "본사")
    .concat(D.latest.tickers.filter(t => t.group === "본사"));
  const max = Math.max(...rows.map(t => Math.abs(t.change_from_base || 0)), 0.01);
  return rows.map(t => {
    const v = t.change_from_base, w = Math.abs(v) / max * 50, left = v >= 0 ? 50 : 50 - w;
    return `<div class="bar-row">
      <span class="lb"><span class="dot" style="background:${slotColor(t.group)}"></span>
        ${t.group === "본사" ? "<b>" : ""}${esc(t.name)}${t.group === "본사" ? "</b>" : ""}</span>
      <span class="bar"><span class="zero" style="left:50%"></span>
        <i style="left:${left}%;width:${w}%;background:${v >= 0 ? tok("--up") : tok("--down")}"></i></span>
      <span class="n ${dirClass(v)}">${signed(v, 1)}</span></div>`;
  }).join("");
}

function renderPrices(V) {
  const L = D.latest, sk = L.tickers[0];
  const v2 = D.latest.views.find(v => v.key === "today")?.modes?.["최종"]?.scores?.V2;
  V.innerHTML = `
    <div class="card">
      <h3>SK이노베이션 <span class="sub">${esc(L.as_of)} 종가 기준</span></h3>
      ${statPair(["종가", `${won(sk.close)}<span style="font-size:13px">원</span>`],
                 ["전일 대비", `<span class="${dirClass(sk.change_pct)}">${signed(sk.change_pct)}</span>`])}
      ${statPair(["2개월 거래량 보정 주가", `${won(sk.vwap_2m)}<span style="font-size:13px">원</span>`],
                 ["기준일 대비", `<span class="${dirClass(sk.change_from_base)}">${signed(sk.change_from_base)}</span>`])}
    </div>

    <div class="card">
      <h3>기준일 대비 주가 지수 <span class="sub">${esc(L.base_date)} = 100 · 종가 기준 · 그래프에 커서를 올리거나 눌러 날짜별 지수 확인</span>
        ${pngButton("indexChartSvg", "기준일대비주가지수.png")}</h3>
      ${indexChart()}
    </div>

    <div class="card">
      <h3>종목별 현황 <span class="sub">2개월 거래량가중평균 주가 · (종가 × 거래량) 합계 ÷ 거래량 합계</span>
        ${csvButton("tickerTbl", "종목별현황.csv")}</h3>
      <div class="tbl-wrap"><table id="tickerTbl">
        <thead><tr><th>종목</th><th>그룹</th><th>최근 추세</th><th>종가</th><th>전일 대비</th><th>2M 보정주가</th><th>기준일 대비</th></tr></thead>
        <tbody>${L.tickers.map(t => `<tr${t.group === "본사" ? ' class="subject"' : ""}>
          <td><span class="dot" style="background:${slotColor(t.group)};margin-right:7px"></span>${esc(t.name)}</td>
          <td><span class="badge grp">${esc(t.group)}${t.weight ? ` ${t.weight * 100}%` : ""}</span></td>
          <td style="text-align:center">${sparkline(t.spark)}</td>
          <td class="num">${won(t.close)}</td>
          <td class="num ${dirClass(t.change_pct)}">${signed(t.change_pct)}</td>
          <td class="num">${won(t.vwap_2m)}</td>
          <td class="num ${dirClass(t.change_from_base)}">${signed(t.change_from_base)}</td>
        </tr>`).join("")}</tbody></table></div>
    </div>

    <div class="card">
      <h3>기준일 대비 거래량 보정 주가 증감율 <span class="sub">이 값들이 Peer 증감율을 만든다</span></h3>
      <div style="display:flex;flex-direction:column;gap:10px">${groupBars()}</div>
    </div>

    <div class="card">
      <h3>점수 시계열 <span class="sub">연초 이후 일별 "그날 최종 평가했다면" 점수 · 2개월·1개월·최근 5거래일 거래량가중평균의 산술평균과 Peer 보정 · 수기 확정 가격${v2 ? `(${won(v2.anchor)}원)` : ""}을 40점 기준으로 적용</span>
        ${pngButton("timeseriesSvg", "점수시계열.png")}</h3>
      ${timeseriesChart()}
    </div>

    ${coverageNotice()}`;
  bindIndexChart(V);
  bindScoreTimeseries(V);
}

/* ── Case 시뮬레이션 탭 ───────────────────────────────────── */

/** 최종 평가 방식으로 계산한 기준가격별 점수 비교. */
function scoreTier(v) {
  if (v <= 20) return "--down-soft";
  if (v >= 70) return "--ok-soft";
  return null;
}
function matrixTable() {
  const M = D.scenarios.matrix;
  const baselines = [
    {
      key: "V2",
      name: "수기 확정 목표가격",
      badge: "현재 적용",
      note: "수기로 검산한 2개월·1개월·1주(5거래일) 산술평균 109,922원을 40점 기준으로 사용",
    },
    {
      key: "V3",
      name: "2026년 수립 목표",
      badge: "수립 목표",
      note: "2026년 수립 시 안내된 113,109원을 40점 기준으로 사용",
    },
    {
      key: "V1",
      name: "2개월 기준가격",
      badge: "참고",
      note: "2025년末 2개월 거래량가중평균을 40점 기준으로 사용",
    },
  ];
  const rows = baselines.map(b => {
    const c = M.find(r => r.baseline === b.key);
    const tier = scoreTier(c.value);
    const scoreNote = c.clipped
      ? `<div style="font-size:10.5px;color:var(--muted)">계산값 ${pts(c.raw)}점 → 0~100점 범위 적용</div>`
      : "";
    return `<tr>
      <td><b>${esc(b.name)}</b> <span class="badge ${b.key === "V2" ? "brand" : "grp"}" style="padding:1px 5px">${esc(b.badge)}</span></td>
      <td class="num">${won(c.anchor)}원</td>
      <td class="num" style="${tier ? `background:var(${tier})` : ""}"><b>${pts(c.value)}점</b>${scoreNote}</td>
      <td style="font-size:12px;color:var(--muted)">${esc(b.note)}</td>
    </tr>`;
  }).join("");
  return `<div class="card">
    <h3>최종 방식 기준선별 점수 <span class="sub">종가 × 거래량 기준 · 2개월·1개월·최근 5거래일의 거래량가중평균 산술평균과 Peer 보정 적용 · ${esc(D.scenarios.as_of)} 기준</span>
      ${csvButton("matrixTbl", "최종방식_기준선별점수.csv")}</h3>
    <div class="tbl-wrap"><table id="matrixTbl">
      <thead><tr><th>점수 기준</th><th>40점 기준가격</th><th>현재 점수</th><th>설명</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="hero-note">세 행 모두 같은 최종 평가 방식으로 계산했으며, 40점의 기준이 되는 가격만 다릅니다.
      대시보드의 오늘의 점수는 <b>수기 확정 목표가격</b>을 적용합니다.</div>
  </div>`;
}

function remainingPathCard() {
  const p = D.scenarios.remaining_paths[String(S.horizon)];
  const rows = p.scenarios.map(s => {
    const w = Math.max(0, Math.min(100, s.value));
    const color = s.annual_rate > 0 ? tok("--up") : s.annual_rate < 0 ? tok("--down") : tok("--muted-2");
    return `<div class="bar-row"><span class="lb">${esc(s.label)}</span>
      <span class="bar"><i style="left:0%;width:${w}%;background:${color}"></i></span>
      <span class="n">${pts(s.value)}점</span></div>`;
  }).join("");
  return `<div class="card">
    <h3>잔여기간 경로 시나리오 <span class="sub">최종 평가 방식 · 2026년 수립 목표 기준 · 가상 평가일 ${esc(p.horizon)} · Peer 현재 수준 고정</span></h3>
    <div class="tabs" style="padding-bottom:2px">
      ${[1, 2, 3].map(m => `<button class="tab ${S.horizon === m ? "active" : ""}" data-horizon="${m}">${m}개월 후</button>`).join("")}
    </div>
    <div style="display:flex;flex-direction:column;gap:9px">${rows}</div>
    <div class="range"><div class="range-track" style="background:var(--track)">
      <span class="range-fill" style="width:${(p.lock_in_pct * 100).toFixed(1)}%;opacity:.6"></span>
    </div></div>
    <div class="hero-note">평가 구간 확정도 <b>${(p.lock_in_pct * 100).toFixed(0)}%</b> —
      2개월·1개월·최근 5거래일 평가 구간에서 이미 지나간 기간의 평균 비중입니다. 가장 긴 2개월 구간 시작일은
      ${esc(p.window_start)}이며, 100%에 가까울수록 남은 기간의 주가가 점수에 미치는 영향이 작습니다.</div>
  </div>`;
}

function timeseriesChart() {
  const T = D.scenarios.timeseries, W = 900, HT = 260, PAD = { t: 26, r: 20, b: 28, l: 40 };
  const n = T.length;
  if (!n) return `<div class="empty">데이터가 없습니다</div>`;
  const X = i => PAD.l + (n === 1 ? 0 : i * (W - PAD.l - PAD.r) / (n - 1));
  const Y = v => PAD.t + (100 - v) * (HT - PAD.t - PAD.b) / 100;
  const grid = [0, 40, 80, 100].map(v =>
    `<line x1="${PAD.l}" y1="${Y(v).toFixed(1)}" x2="${W - PAD.r}" y2="${Y(v).toFixed(1)}"
       stroke="${v === 40 ? tok("--axis") : tok("--grid")}" stroke-width="1" ${v === 40 ? 'stroke-dasharray="4 3"' : ""}/>
     <text x="${PAD.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" font-size="10.5"
       fill="${tok("--muted")}">${v}</text>`).join("");
  let d = "";
  T.forEach((t, i) => { d += `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(Math.max(0, Math.min(100, t.value))).toFixed(1)} `; });
  const path = `<path d="${d.trim()}" fill="none" stroke="${tok("--series-1")}" stroke-width="2.2"
    stroke-linejoin="round" stroke-linecap="round"/>`;
  const markers = (D.scenarios.events || []).map(e => {
    const idx = T.findIndex(t => t.date >= e.date);
    if (idx < 0) return "";
    return `<line x1="${X(idx).toFixed(1)}" y1="${PAD.t}" x2="${X(idx).toFixed(1)}" y2="${HT - PAD.b}"
      stroke="${tok("--warn")}" stroke-width="1.3" stroke-dasharray="3 3"/>
      <text x="${X(idx).toFixed(1)}" y="${PAD.t - 6}" text-anchor="middle" font-size="10" fill="${tok("--warn")}">${esc(e.label)}</text>`;
  }).join("");
  const ticks = [0, Math.floor(n / 3), Math.floor(2 * n / 3), n - 1].map(i =>
    `<text x="${X(i).toFixed(1)}" y="${HT - 7}" text-anchor="middle" font-size="10.5"
       fill="${tok("--muted")}">${esc(T[i].date.slice(2))}</text>`).join("");
  return `<div class="score-timeseries-wrap" data-score-timeseries="${esc(JSON.stringify(T))}">
    <div class="chart"><svg id="timeseriesSvg" viewBox="0 0 ${W} ${HT}" preserveAspectRatio="none" role="img"
      aria-label="일별 점수 시계열, 확정 평가일 마커 포함">${grid}${path}${markers}${ticks}
      <g class="score-timeseries-hover" hidden>
        <line class="score-timeseries-guide" y1="${PAD.t}" y2="${HT - PAD.b}" stroke="${tok("--muted")}" stroke-dasharray="3 3"/>
        <circle class="score-timeseries-dot" r="4.5" fill="${tok("--series-1")}"/>
      </g>
      <rect class="score-timeseries-hit" x="${PAD.l}" y="${PAD.t}" width="${W - PAD.l - PAD.r}" height="${HT - PAD.t - PAD.b}" fill="transparent"/>
    </svg></div>
    <div class="score-timeseries-tooltip" hidden></div>
  </div>`;
}

function bindScoreTimeseries(root) {
  root.querySelectorAll("[data-score-timeseries]").forEach(chart => {
    const points = JSON.parse(chart.dataset.scoreTimeseries);
    const svg = chart.querySelector("svg"), hit = chart.querySelector(".score-timeseries-hit");
    const hover = chart.querySelector(".score-timeseries-hover"), guide = chart.querySelector(".score-timeseries-guide");
    const dot = chart.querySelector(".score-timeseries-dot"), tip = chart.querySelector(".score-timeseries-tooltip");
    const W = 900, HT = 260, PAD = { t: 26, r: 20, b: 28, l: 40 };
    const show = event => {
      const rect = svg.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const i = Math.max(0, Math.min(points.length - 1,
        Math.round(((ratio * W) - PAD.l) / (W - PAD.l - PAD.r) * (points.length - 1))));
      const p = points[i];
      const cx = PAD.l + i * (W - PAD.l - PAD.r) / Math.max(1, points.length - 1);
      const cy = PAD.t + (100 - Math.max(0, Math.min(100, p.value))) * (HT - PAD.t - PAD.b) / 100;
      hover.hidden = false;
      guide.setAttribute("x1", cx); guide.setAttribute("x2", cx);
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
      tip.innerHTML = `<b>${koDate(p.date)}</b>
        <span>점수 <strong>${pts(p.value)}점</strong></span>
        <span>SK이노베이션 최종 산술평균 <strong>${won(p.subject_price)}원</strong></span>
        <span>SK이노베이션 증감률 <strong>${signed(p.subject_change)}</strong></span>
        <span>Peer 증감률 <strong>${signed(p.peer_change)}</strong></span>
        <span>Peer 보정 평가주가 <strong>${won(p.eval_price)}원</strong></span>`;
      tip.hidden = false;
      tip.style.left = `${Math.max(8, Math.min(chart.clientWidth - tip.offsetWidth - 8, event.clientX - rect.left + 12))}px`;
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerleave", () => { hover.hidden = true; tip.hidden = true; });
  });
}

function renderCase(V) {
  V.innerHTML = `
    ${matrixTable()}
    ${remainingPathCard()}
    ${coverageNotice()}`;
  document.querySelectorAll("[data-horizon]").forEach(b =>
    b.addEventListener("click", () => { S.horizon = Number(b.dataset.horizon); renderCase(V); }));
}

/* ── 27년 과제 설계 탭 ─────────────────────────────────────── */

function simDefaults() {
  const today = D.latest.views.find(v => v.key === "today").modes["최종"];
  return {
    method: D.latest.method_primary,
    weighted: true,
    periodMode: "average",
    windows: [...today.specs],
    weight: today.groups["에화"].weight,
    excluded: new Set(),
    candidatesOn: new Set(),
    scaleWidth: D.latest.score_scale.upper_bound_pct,
    formula: "relative",
  };
}

/** 정식 8개 Peer(D.latest.tickers) 에, 사용자가 탭4에서 켠 실험용 후보를 얹은
 *  목록 — computeSim() 은 이 목록을 그대로 그룹별로 묶어 평균을 낸다. 후보를
 *  하나도 켜지 않으면 D.latest.tickers 와 완전히 같으므로 "오늘의 점수"는
 *  건드리지 않는다. */
function simActiveTickers() {
  const active = (D.latest.candidates || []).filter(c => SIM.candidatesOn.has(c.code));
  return D.latest.tickers.concat(active.map(c => ({ code: c.code, name: c.name, group: c.group, weight: null })));
}

function simMethodLabel(method) {
  return method === "A" ? "실제 거래대금 기준" : "종가·거래량 기준";
}

function simWindowLabel(spec) {
  return ({ "1D": "최근 1일", "1W": "최근 5거래일", "1M": "최근 1개월", "2M": "최근 2개월", "3M": "최근 3개월", "6M": "최근 6개월" })[spec] || spec;
}

function simFormulaLabel(formula) {
  return formula === "absolute" ? "SK이노베이션만 반영" : "Peer 대비 성과 반영";
}

function simPeriodSummary(params) {
  const periods = params.windows.map(simWindowLabel).join("·");
  return params.periodMode === "single" || params.windows.length === 1
    ? `${periods} 한 기간 사용`
    : `${periods} 거래량가중평균 주가의 산술평균`;
}

function usesManualFinalTarget(params) {
  const windows = [...params.windows].sort().join(",");
  return params.weighted !== false
    && params.method === D.latest.method_primary
    && windows === ["2M", "1M", "1W"].sort().join(",");
}

function simAnchor(params, baseDate) {
  if (usesManualFinalTarget(params)) {
    return D.latest.views.find(v => v.key === "today").modes["최종"].scores.V2.anchor;
  }
  const subject = D.latest.tickers.find(t => t.group === "본사");
  return adjustedPriceJS(D.bars[subject.code], baseDate, params.windows, params.method, params.weighted);
}

function simAnchorDescription(params) {
  return usesManualFinalTarget(params) ? "수기 확정 목표가격" : "선택한 평가 방식으로 재계산한 기준가격";
}

function designScorePrices(result) {
  const marks = result.score_marks.V3.filter(mark => [0, 40, 100].includes(mark.points));
  return `<div class="design-scale-card">
    <div class="group-sec-h">선택한 평가 방식으로 다시 계산한 2025년末 점수 기준가격</div>
    <div class="design-scale-grid">
      ${marks.map(mark => `<div><span>${mark.points}점</span><b>${won(mark.price)}원</b></div>`).join("")}
    </div>
    <div class="control-help">기본 최종 방식은 수기 확정 목표가격 109,922원을 사용합니다. 평균주가 계산 기준이나 산정기간을 바꾸면 선택한 방식의 2025년末 가격으로 다시 계산합니다.</div>
  </div>`;
}

/** 기본값(최종 방식·종가와 거래량 기준·에화60:배소40·전종목·±15%·Peer 보정)이 탭2 "오늘의 점수"와
 *  정확히 같은 값을 내는지 확인한다. sim.js 는 core/ 의 공식을 옮겨 적은
 *  두 번째 구현이므로, 이 확인이 둘이 어긋나지 않았다는 유일한 안전장치다. */
function verifyDefaultsMatchToday() {
  try {
    const today = D.latest.views.find(v => v.key === "today").modes["최종"];
    const params = simDefaults();
    const baseDate = parseISOJS(D.latest.base_date), evalDate = parseISOJS(D.latest.as_of);
    const anchor = simAnchor(params, baseDate);
    const result = computeSim(D.bars, D.latest.tickers, params, baseDate, evalDate, anchor, D.latest.score_scale);
    const diff = Math.abs(result.scores.V3.value - today.scores.V2.value);
    const anchorDiff = Math.abs(anchor - today.scores.V2.anchor);
    if (diff > 0.05 || anchorDiff > 0.05) {
      console.error(`[sim.js] 기본값이 탭2 오늘의 점수와 어긋납니다 — 점수 차이 ${diff.toFixed(4)}점, 40점 기준가격 차이 ${anchorDiff.toFixed(2)}원. ` +
        `core/scenarios.py 와 docs/assets/sim.js 공식이 갈라졌을 수 있습니다.`);
    }
  } catch (e) {
    console.error("[sim.js] 기본값 검증 실패:", e);
  }
}

function controlsPanel() {
  const groupNames = D.latest.tickers.map(t => t.group).filter((g, i, a) => g !== "본사" && a.indexOf(g) === i);
  const membersOf = name => D.latest.tickers.filter(t => t.group === name);
  return `<div class="card">
    <h3>평가 조건 <span class="sub">조건을 바꾸면 평가주가와 최종 점수가 즉시 다시 계산됩니다</span></h3>
    <div style="display:flex;flex-direction:column;gap:16px">
      <div>
        <div class="group-sec-h">평균주가 계산 방식</div>
        <div class="tabs" style="padding-bottom:0">
          <button class="tab ${SIM.weighted ? "active" : ""}" data-sim-weighted="1">거래량가중평균 주가</button>
          <button class="tab ${!SIM.weighted ? "active" : ""}" data-sim-weighted="0">단순 종가평균</button>
        </div>
      </div>
      <div ${SIM.weighted ? "" : 'style="opacity:.4;pointer-events:none"'}>
        <div class="group-sec-h">거래량가중평균 계산 기준 <span style="font-weight:var(--w-reg)">(선택에 따라 아래 최종 점수도 달라집니다)</span></div>
        <div class="tabs" style="padding-bottom:0">
          ${["A", "B"].map(m => `<button class="tab ${SIM.method === m ? "active" : ""}" data-sim-method="${m}">${simMethodLabel(m)}</button>`).join("")}
        </div>
        <div class="control-help">실제 거래대금 기준 = 거래대금 합계 ÷ 거래량 합계 · 종가·거래량 기준 = (종가 × 거래량) 합계 ÷ 거래량 합계</div>
      </div>
      <div>
        <div class="group-sec-h">평가주가 구성</div>
        <div class="tabs" style="padding-bottom:0">
          <button class="tab ${SIM.periodMode === "single" ? "active" : ""}" data-sim-period-mode="single">한 기간의 평균주가 사용</button>
          <button class="tab ${SIM.periodMode === "average" ? "active" : ""}" data-sim-period-mode="average">여러 기간 평균주가의 산술평균</button>
        </div>
      </div>
      <div>
        <div class="group-sec-h">평균 산정기간 <span style="font-weight:var(--w-reg)">(${SIM.periodMode === "single" ? "한 기간을 선택합니다" : "두 개 이상의 기간을 선택합니다"})</span></div>
        ${SIM.periodMode === "single" ? `
          <div class="tabs" style="padding-bottom:0">
            ${WINDOW_OPTS.map(w => `<button class="tab ${SIM.windows[0] === w ? "active" : ""}" data-sim-single-window="${w}">${simWindowLabel(w)}</button>`).join("")}
          </div>` : `
          <div style="display:flex;flex-wrap:wrap;gap:10px 16px">
            ${WINDOW_OPTS.map(w => {
              const checked = SIM.windows.includes(w);
              const lockedOn = checked && SIM.windows.length <= 2;
              return `<label style="display:flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer">
                <input type="checkbox" data-sim-window="${w}" ${checked ? "checked" : ""} ${lockedOn ? "disabled" : ""}>${simWindowLabel(w)}</label>`;
            }).join("")}
          </div>`}
        <div class="control-help">현재 적용: ${simPeriodSummary(SIM)}</div>
      </div>
      <div>
        <div class="group-sec-h">그룹 가중치 — 에화 ${(SIM.weight * 100).toFixed(0)}% · 배소 ${(100 - SIM.weight * 100).toFixed(0)}%</div>
        <input type="range" id="simWeight" min="0" max="100" step="5" value="${SIM.weight * 100}" style="width:100%">
        <div class="group-sec-h" style="margin-top:10px">사업부문별 비유동자산 (2025년 사업보고서 기준)</div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>부문</th><th>금액</th><th>비중</th></tr></thead>
          <tbody>
            <tr><td>에너지·화학</td><td class="num">12.97조원</td><td class="num">24.9%</td></tr>
            <tr><td>배터리·소재</td><td class="num">26.00조원</td><td class="num">49.8%</td></tr>
            <tr><td>E&S</td><td class="num">12.49조원</td><td class="num">23.9%</td></tr>
            <tr><td>기타부문</td><td class="num">0.71조원</td><td class="num">1.4%</td></tr>
          </tbody>
        </table></div>
      </div>
      <div>
        <div class="group-sec-h">Peer 종목 포함/제외 <span style="font-weight:var(--w-reg)">(그룹당 최소 1종목 · ⓘ에 커서를 올리면 선정 적정성 확인)</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:20px">
          ${groupNames.map(name => {
            const members = membersOf(name);
            const includedCount = members.filter(t => !SIM.excluded.has(t.code)).length;
            return `<div>
              <b style="font-size:11.5px;color:var(--muted-2)">${esc(name)}</b>
              <div style="display:flex;flex-direction:column;gap:4px;margin-top:4px">
                ${members.map(t => {
                  const checked = !SIM.excluded.has(t.code);
                  const lockedOn = checked && includedCount <= 1;
                  return `<div class="sim-peer-row">
                    <label style="display:flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer">
                      <input type="checkbox" data-sim-peer="${t.code}" ${checked ? "checked" : ""} ${lockedOn ? "disabled" : ""}>${esc(t.name)}
                    </label>
                    <span class="peer-eval-trigger" tabindex="0" aria-label="${esc(t.name)} Peer 선정 적정성 보기">ⓘ${peerCriteriaPopover(t)}</span>
                  </div>`;
                }).join("")}
              </div>
            </div>`;
          }).join("")}
        </div>
      </div>
      ${(D.latest.candidates || []).length ? `<div>
        <div class="group-sec-h">추가 후보 <span style="font-weight:var(--w-reg)">(실험용 · 기본 제외 · 켜면 해당 그룹 평균에 포함됩니다)</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:20px">
          ${D.latest.candidates.map(c => {
            const checked = SIM.candidatesOn.has(c.code);
            return `<div>
              <b style="font-size:11.5px;color:var(--muted-2)">${esc(c.group)}</b>
              <div style="display:flex;flex-direction:column;gap:4px;margin-top:4px">
                <div class="sim-peer-row">
                  <label style="display:flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer">
                    <input type="checkbox" data-sim-candidate="${c.code}" ${checked ? "checked" : ""}>${esc(c.name)}
                  </label>
                  <span class="peer-eval-trigger" tabindex="0" aria-label="${esc(c.name)} Peer 선정 적정성 보기">ⓘ${peerCriteriaPopover(c)}</span>
                </div>
              </div>
            </div>`;
          }).join("")}
        </div>
      </div>` : ""}
      <div>
        <div class="group-sec-h">점수 범위 — 40점 기준가격 대비 ±${(SIM.scaleWidth * 100).toFixed(0)}%</div>
        <input type="range" id="simScale" min="5" max="30" step="1" value="${SIM.scaleWidth * 100}" style="width:100%">
      </div>
      <div>
        <div class="group-sec-h">Peer 보정 방식</div>
        <div class="tabs" style="padding-bottom:0">
          <button class="tab ${SIM.formula === "relative" ? "active" : ""}" data-sim-formula="relative">Peer 대비 성과 반영</button>
          <button class="tab ${SIM.formula === "absolute" ? "active" : ""}" data-sim-formula="absolute">SK이노베이션만 반영</button>
        </div>
      </div>
      <button class="btn-mini" id="simReset" style="align-self:flex-start">최종 방식으로 초기화</button>
    </div>
  </div>`;
}

function wireDesignEvents(V) {
  document.getElementById("simReset")?.addEventListener("click", () => { SIM = simDefaults(); renderDesign(V); });
  document.querySelectorAll("[data-sim-weighted]").forEach(b =>
    b.addEventListener("click", () => { SIM.weighted = b.dataset.simWeighted === "1"; renderDesign(V); }));
  document.querySelectorAll("[data-sim-method]").forEach(b =>
    b.addEventListener("click", () => { SIM.method = b.dataset.simMethod; renderDesign(V); }));
  document.querySelectorAll("[data-sim-period-mode]").forEach(b =>
    b.addEventListener("click", () => {
      SIM.periodMode = b.dataset.simPeriodMode;
      if (SIM.periodMode === "single") {
        SIM.windows = [SIM.windows.includes("2M") ? "2M" : (SIM.windows[0] || "2M")];
      } else if (SIM.windows.length < 2) {
        SIM.windows = ["2M", "1M", "1W"];
      }
      renderDesign(V);
    }));
  document.querySelectorAll("[data-sim-single-window]").forEach(b =>
    b.addEventListener("click", () => { SIM.windows = [b.dataset.simSingleWindow]; renderDesign(V); }));
  document.querySelectorAll("[data-sim-window]").forEach(cb =>
    cb.addEventListener("change", () => {
      const w = cb.dataset.simWindow;
      if (cb.checked) { if (!SIM.windows.includes(w)) SIM.windows.push(w); }
      else if (SIM.windows.length > 2) { SIM.windows = SIM.windows.filter(x => x !== w); }
      renderDesign(V);
    }));
  document.getElementById("simWeight")?.addEventListener("change", e => { SIM.weight = Number(e.target.value) / 100; renderDesign(V); });
  document.querySelectorAll("[data-sim-peer]").forEach(cb =>
    cb.addEventListener("change", () => {
      const code = cb.dataset.simPeer;
      if (cb.checked) SIM.excluded.delete(code); else SIM.excluded.add(code);
      renderDesign(V);
    }));
  document.querySelectorAll("[data-sim-candidate]").forEach(cb =>
    cb.addEventListener("change", () => {
      const code = cb.dataset.simCandidate;
      if (cb.checked) SIM.candidatesOn.add(code); else SIM.candidatesOn.delete(code);
      renderDesign(V);
    }));
  document.getElementById("simScale")?.addEventListener("change", e => { SIM.scaleWidth = Number(e.target.value) / 100; renderDesign(V); });
  document.querySelectorAll("[data-sim-formula]").forEach(b =>
    b.addEventListener("click", () => { SIM.formula = b.dataset.simFormula; renderDesign(V); }));
}

function renderDesign(V) {
  if (!SIM) SIM = simDefaults();
  const baseDate = parseISOJS(D.latest.base_date), evalDate = parseISOJS(D.latest.as_of);
  const anchor = simAnchor(SIM, baseDate);

  let result, methodScores = [], error = null;
  try {
    const activeTickers = simActiveTickers();
    result = computeSim(D.bars, activeTickers, SIM, baseDate, evalDate, anchor, D.latest.score_scale);
    if (SIM.weighted) {
      methodScores = ["A", "B"].map(method => {
        const params = { ...SIM, method };
        const comparedAnchor = simAnchor(params, baseDate);
        return {
          method,
          result: computeSim(D.bars, activeTickers, params, baseDate, evalDate, comparedAnchor, D.latest.score_scale),
        };
      });
    }
  } catch (e) {
    error = e.message;
  }

  const xLabel = SIM.formula === "absolute"
    ? "SK이노베이션 증감률만 반영 (Peer 보정 없음)"
    : "SK이노베이션 증감률 − Peer 증감률";
  V.innerHTML = `
    <div class="design-layout">
      ${controlsPanel()}
      ${error ? `<div class="empty"><span class="ico">⚠️</span>계산할 수 없습니다 — ${esc(error)}</div>` : `
      <div class="card">
        <h3>산출 결과 <span class="sub">${simAnchorDescription(SIM)} ${won(anchor)}원을 40점 기준으로 적용</span></h3>
        ${SIM.weighted ? `<div class="mode-grid design-score-compare">
          ${methodScores.map(({ method, result: compared }) => `<div class="mode ${SIM.method === method ? "active" : ""}">
            <span class="t">${simMethodLabel(method)}${SIM.method === method ? " · 현재 선택" : ""}</span>
            <span class="v">${pts(compared.scores.V3.value)}점</span>
            <span class="d">평가주가 ${won(compared.eval_price)}원 · 40점 기준가격 ${won(compared.score_marks.V3.find(mark => mark.points === 40).price)}원</span>
          </div>`).join("")}
        </div>` : ""}
        <div class="mode-block" style="border:none;padding:0">
          <div class="mode-block-head">
            <div class="name">선택 조건에 따른 최종 평가 점수<span class="sub">${SIM.weighted ? simMethodLabel(SIM.method) : "단순 종가평균"} · ${simFormulaLabel(SIM.formula)} · 선택한 모든 조건이 반영된 결과입니다</span></div>
            <div class="mode-block-score">
              <b class="${dirClass(result.scores.V3.value - 40)}">${pts(result.scores.V3.value)}점</b>
              <span class="raw">${result.scores.V3.clipped ? `산식상 ${pts(result.scores.V3.raw)}점 → 0~100점 범위 적용` : "0~100점 범위 내"}</span>
            </div>
          </div>
          ${scoreGauge(result.score_marks.V3, result.scores.V3.value)}
          ${designScorePrices(result)}
          ${subjectTable(result, SIM.weighted)}
          ${peerSection(result)}
          ${calcSection(result, xLabel, true)}
        </div>
      </div>`}
    </div>
    ${coverageNotice()}`;
  wireDesignEvents(V);
}

function render() {
  const V = document.getElementById("view");
  if (S.tab === "score") return renderScore(V);
  if (S.tab === "case") return renderCase(V);
  if (S.tab === "design") return renderDesign(V);
  return renderPrices(V);
}

init();
