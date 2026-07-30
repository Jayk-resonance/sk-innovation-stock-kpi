/* 사이트는 계산하지 않는다. pipeline/build_site.py 가 만든 JSON을 그리기만 한다.
 * 계산이 두 곳에 있으면 검증한 값과 화면의 값이 갈라진다.
 *
 * 색은 여기에 하나도 박지 않는다. SVG 는 CSS 변수를 직접 못 쓰므로
 * tok() 으로 style.css 의 토큰을 읽어 쓴다. 팔레트 변경은 CSS 한 곳에서 끝난다.
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
const WINDOW_OPTS = ["1D", "1W", "1M", "2M", "3M", "6M"];
let SIM = null;   // 탭4 파라미터 상태. D.latest 로딩 후 첫 방문 시 simDefaults() 로 채운다.

const tok = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g,
  m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
const won = n => n == null ? "—" : Math.round(n).toLocaleString("ko-KR");
const signed = (n, d = 2) => n == null ? "—" : (n >= 0 ? "+" : "") + (n * 100).toFixed(d) + "%";
const dirClass = n => n == null ? "" : (n > 0 ? "up" : n < 0 ? "down" : "");
const pts = n => n == null ? "—" : n.toFixed(2);
const signedPts = n => n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "점";

/* 그룹 → 시리즈 슬롯. 고정 순서이며 순환하지 않는다. */
const SLOT = { 본사: "--series-1", 에화: "--series-2", 배소: "--series-3" };
const slotColor = group => tok(SLOT[group] || "--muted");

async function j(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} (${r.status})`);
  return r.json();
}

function visibleViews() {
  return D.latest.views.filter(v => !HIDDEN_EVAL_KEYS.has(v.key));
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
    if (MAIN_TABS.some(t => t.key === hTab)) S.tab = hTab;
    if (hSub && visibleViews().some(v => v.key === hSub)) S.evalKey = hSub;
    document.getElementById("todayStr").textContent = "기준 " + D.latest.as_of;
    renderMainNav(); renderTickerList(); renderSubtabs(); render();
  } catch (e) {
    document.getElementById("view").innerHTML =
      `<div class="empty"><span class="ico">⚠️</span><b style="color:var(--ink)">데이터를 불러오지 못했습니다</b><br><small>${esc(e.message)}</small></div>`;
  }
}

function pushHash() {
  location.hash = S.tab === "score"
    ? `${S.tab}/${encodeURIComponent(S.evalKey)}` : S.tab;
}

function renderMainNav() {
  document.getElementById("mainNav").innerHTML = MAIN_TABS.map(t => `
    <button class="nav-main-item ${S.tab === t.key ? "active" : ""}" data-main="${t.key}">
      <span class="nav-ico" aria-hidden="true">${t.icon}</span>
      <span class="nav-lbl">${esc(t.label)}</span>
    </button>`).join("");
  document.querySelectorAll("[data-main]").forEach(b =>
    b.addEventListener("click", () => {
      S.tab = b.dataset.main;
      if (S.tab === "score" && !visibleViews().some(v => v.key === S.evalKey)) S.evalKey = "today";
      pushHash(); renderMainNav(); renderSubtabs(); render();
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
function subjectTable(m, weighted = true) {
  const unit = weighted ? "VWAP" : "종가평균";
  const rows = m.windows_now.map((w, i) => {
    const base = m.windows_base[i];
    const chg = w.vwap / base.vwap - 1;
    return `<tr><td>${esc(w.spec)} ${unit}</td>
      <td class="num">${won(w.vwap)}원</td>
      <td class="num">${won(base.vwap)}원</td>
      <td class="num ${dirClass(chg)}">${signed(chg)}</td></tr>`;
  });
  return `<div class="group-sec">
    <div class="group-sec-h">SK이노베이션 ${weighted ? "거래량 보정 주가" : "종가평균 (거래량 무시)"}</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>구간</th><th>평가일 ${unit}</th><th>기준일 ${unit}</th><th>증감율</th></tr></thead>
      <tbody>
        <tr><td>종가</td><td class="num">${won(m.subject_close)}원</td><td colspan="2"></td></tr>
        ${rows.join("")}
        <tr class="subject"><td><b>${m.windows_now.length > 1 ? `평균 ${unit}` : unit}</b></td>
          <td class="num"><b>${won(m.subject_price)}원</b></td>
          <td class="num"><b>${won(m.subject_base_price)}원</b></td>
          <td class="num ${dirClass(m.subject_change)}"><b>${signed(m.subject_change)}</b></td></tr>
      </tbody></table></div>
  </div>`;
}

/** Peer 보정 — 그룹별로 묶는다. 60:40 가중치가 그룹 단위이므로 개별사가 아니라
 *  그룹 평균이 실제로 점수에 들어가는 값이다. */
function peerSection(m) {
  const grp = (name) => {
    const g = m.groups[name];
    return `<div class="peer-grp">
      <div class="peer-grp-h"><span>${esc(name)} 그룹</span><span class="w">가중치 ${(g.weight * 100).toFixed(0)}%</span></div>
      ${g.members.map(mem =>
        `<div class="m"><span>${esc(mem.name)}</span><span class="${dirClass(mem.change)}">${signed(mem.change)}</span></div>`
      ).join("")}
      <div class="m"><b>그룹 평균</b><b class="${dirClass(g.average)}">${signed(g.average)}</b></div>
    </div>`;
  };
  return `<div class="group-sec">
    <div class="group-sec-h">Peer 보정 — 그룹별 증감율</div>
    ${grp("에화")}${grp("배소")}
    <div class="wtable"><div class="r sum"><span class="k">Peer 증감율 (0.6×에화 + 0.4×배소)</span>
      <span class="v ${dirClass(m.peer_change)}">${signed(m.peer_change)}</span></div></div>
  </div>`;
}

function calcSection(m, xLabel) {
  return `<div class="group-sec">
    <div class="group-sec-h">평가주가 산출</div>
    <div class="calc-final">
      <div class="r"><span>${esc(xLabel || "상대 증감율 x = SK − Peer")}</span><span class="${dirClass(m.relative_change)}">${signed(m.relative_change)}</span></div>
      <div class="r"><span>배수 1/(1−x)</span><span>${m.multiplier.toFixed(4)}배</span></div>
      <div class="r big"><span>평가주가</span><span>${won(m.eval_price)}원</span></div>
    </div>
  </div>`;
}

function modeBlock(m, label, sub) {
  const s = m.scores.V3;
  return `<div class="mode-block">
    <div class="mode-block-head">
      <div class="name">${esc(label)}<span class="sub">${esc(sub)}</span></div>
      <div class="mode-block-score">
        <b class="${dirClass(s.value - 40)}">${pts(s.value)}점</b>
        <span class="raw">원값 ${pts(s.raw)}점${s.clipped ? " · 클리핑 적용" : ""}</span>
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

function renderScore(V) {
  const view = currentView();
  const result = view.modes["최종"];
  const score = result.scores.V2;
  const marks = result.score_marks.V2;

  V.innerHTML = `
    <div class="hero">
      <div class="eyebrow">${esc(view.label)} · ${esc(view.date)} 기준</div>
      <div class="score-main">
        <b>${pts(score.value)}</b><span class="unit">점</span>
        <span class="raw">점수 산정가격 ${won(result.eval_price)}원</span>
      </div>
      ${scoreGauge(marks, score.value)}
      <div class="hero-note"><b>평가주가</b> = SK 거래량가중평균 ÷ [1 − (SK 증감률 − Peer 증감률)]<br>
        <span><b>Peer 증감률</b> = 0.6 × 에화 그룹 평균 + 0.4 × 배소 그룹 평균</span></div>
    </div>

    <div class="card">
      <h3>점수 산출 <span class="sub">평가주가를 만드는 다섯 단계</span></h3>
      <div class="mode-block">
        <div class="hero-note"><b>① SK 거래량가중평균</b> · 2개월·1개월·1주의 거래량가중평균을 같은 비중으로 평균합니다.</div>
        ${subjectTable(result)}
        <div class="hero-note"><b>② SK 증감률</b> · 평가일 SK 거래량가중평균을 기준일 SK 거래량가중평균과 비교합니다.</div>
        <div class="hero-note"><b>③ Peer 증감률</b> · 각 그룹 안의 종목 증감률을 단순 평균한 뒤, 에화 그룹 60%와 배소 그룹 40%를 가중 평균합니다.</div>
        ${peerSection(result)}
        <div class="hero-note"><b>④ 상대 증감률</b> · SK 증감률에서 Peer 증감률을 뺍니다.</div>
        <div class="hero-note"><b>⑤ 평가주가</b> · SK 거래량가중평균을 1 − 상대 증감률로 나눕니다.</div>
        ${calcSection(result)}
      </div>
    </div>

    <div class="card">
      <h3>점수 기준 <span class="sub">기준 가격을 40점으로 환산</span></h3>
      <div class="hero-note"><b>⑥ 점수 환산</b> · 기준 가격의 85%는 0점, 기준 가격은 40점, 기준 가격의 115%는 100점입니다. 범위 밖 값은 0~100점으로 제한합니다.</div>
      <div class="statpair">
        <span class="k">기준 가격</span><span class="v r">${won(score.anchor)}원</span>
        <span class="k">점수 산정가격</span><span class="v r">${won(result.eval_price)}원</span>
        <span class="k">현재 점수</span><span class="v r">${pts(score.value)}점</span>
      </div>
    </div>`;
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
  V.innerHTML = `
    <div class="card">
      <h3>SK이노베이션 <span class="sub">${esc(L.as_of)} 종가 기준</span></h3>
      ${statPair(["종가", `${won(sk.close)}<span style="font-size:13px">원</span>`],
                 ["전일 대비", `<span class="${dirClass(sk.change_pct)}">${signed(sk.change_pct)}</span>`])}
      ${statPair(["2개월 거래량 보정 주가", `${won(sk.vwap_2m)}<span style="font-size:13px">원</span>`],
                 ["기준일 대비", `<span class="${dirClass(sk.change_from_base)}">${signed(sk.change_from_base)}</span>`])}
    </div>

    <div class="card">
      <h3>기준일 대비 주가 지수 <span class="sub">${esc(L.base_date)} = 100 · 종가 기준 · 개별 Peer 는 아래 표 스파크라인 참조</span>
        ${pngButton("indexChartSvg", "기준일대비주가지수.png")}</h3>
      ${indexChart()}
    </div>

    <div class="card">
      <h3>종목별 현황 <span class="sub">거래량 보정 주가는 2개월 VWAP · 산식 ${esc(L.method_primary)}</span>
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

    ${coverageNotice()}`;
}

/* ── Case 시뮬레이션 탭 ───────────────────────────────────── */

/** 12칸 매트릭스 — 윈도우(잠정/최종) × 산식(A/B) × 기준선(V1/V2/V3).
 *  극단값만 옅게 표시한다(연속 그라데이션은 검증되지 않은 임의 색상이 되므로
 *  피하고, 이미 검증된 상태색 토큰 2개만 재사용한다). */
function scoreTier(v) {
  if (v <= 20) return "--down-soft";
  if (v >= 70) return "--ok-soft";
  return null;
}
function matrixTable() {
  const M = D.scenarios.matrix, combos = [["잠정", "A"], ["잠정", "B"], ["최종", "A"], ["최종", "B"]];
  const baselines = ["V3", "V1", "V2"];
  const cellOf = (mode, method, baseline) => M.find(r => r.mode === mode && r.method === method && r.baseline === baseline);
  const rows = combos.map(([mode, method]) => {
    const cells = baselines.map(b => {
      const c = cellOf(mode, method, b), tier = scoreTier(c.value);
      return `<td class="num" style="${tier ? `background:var(${tier})` : ""}">
        <b>${pts(c.value)}점</b>${c.clipped ? ` <span class="badge warn" style="padding:1px 5px">하한</span>` : ""}
        <div style="font-size:10.5px;color:var(--muted);font-weight:var(--w-reg)">원값 ${pts(c.raw)}</div></td>`;
    }).join("");
    return `<tr><td><b>${esc(mode)}</b> <span class="badge grp">산식 ${esc(method)}</span></td>${cells}</tr>`;
  }).join("");
  return `<div class="card">
    <h3>12개 조합 매트릭스 <span class="sub">윈도우 × 산식 × 기준선 — 기준일 ${esc(D.scenarios.as_of)}</span>
      ${csvButton("matrixTbl", "12조합매트릭스.csv")}</h3>
    <div class="tbl-wrap"><table id="matrixTbl">
      <thead><tr><th>윈도우 · 산식</th>${baselines.map(b =>
        `<th>${esc(b)}${D.latest.baselines[b].official ? ' <span class="badge brand" style="padding:1px 5px">공식</span>' : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="hero-note">빨간 배경은 20점 이하, 초록 배경은 70점 이상 — 같은 날 같은 데이터인데
      어느 축을 바꾸느냐에 따라 이 정도로 갈립니다.</div>
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
    <h3>잔여기간 경로 시나리오 <span class="sub">가상 평가일 ${esc(p.horizon)} · Peer 현재 수준 고정</span></h3>
    <div class="tabs" style="padding-bottom:2px">
      ${[1, 2, 3].map(m => `<button class="tab ${S.horizon === m ? "active" : ""}" data-horizon="${m}">${m}개월 후</button>`).join("")}
    </div>
    <div style="display:flex;flex-direction:column;gap:9px">${rows}</div>
    <div class="range"><div class="range-track" style="background:var(--track)">
      <span class="range-fill" style="width:${(p.lock_in_pct * 100).toFixed(1)}%;opacity:.6"></span>
    </div></div>
    <div class="hero-note">윈도우 고착도(이미 확정된 구간 비중) <b>${(p.lock_in_pct * 100).toFixed(0)}%</b> —
      2개월 윈도우 시작일 ${esc(p.window_start)}. 100%에 가까울수록 남은 기간에 주가가 움직여도 점수를 바꿀 여지가 적습니다.</div>
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
  return `<div class="chart"><svg id="timeseriesSvg" viewBox="0 0 ${W} ${HT}" role="img"
    aria-label="일별 점수 시계열, 확정 평가일 마커 포함">${grid}${path}${markers}${ticks}</svg></div>`;
}

function renderCase(V) {
  V.innerHTML = `
    ${matrixTable()}
    ${remainingPathCard()}
    <div class="card">
      <h3>점수 시계열 <span class="sub">연초 이후 일별 "그날 평가했다면" 점수 · 잠정 방식 · 산식 ${esc(D.latest.method_primary)} · 기준선 V3</span>
        ${pngButton("timeseriesSvg", "점수시계열.png")}</h3>
      ${timeseriesChart()}
    </div>
    ${coverageNotice()}`;
  document.querySelectorAll("[data-horizon]").forEach(b =>
    b.addEventListener("click", () => { S.horizon = Number(b.dataset.horizon); renderCase(V); }));
}

/* ── 27년 과제 설계 탭 ─────────────────────────────────────── */

function simDefaults() {
  const today = D.latest.views.find(v => v.key === "today").modes["잠정"];
  return {
    method: D.latest.method_primary,
    weighted: true,
    windows: [...today.specs],
    weight: today.groups["에화"].weight,
    excluded: new Set(),
    scaleWidth: D.latest.score_scale.upper_bound_pct,
    formula: "relative",
  };
}

/** 기본값(잠정·산식B·에화60:배소40·전종목·±15%·상대)이 탭2 "오늘의 점수"와
 *  정확히 같은 값을 내는지 확인한다. sim.js 는 core/ 의 공식을 옮겨 적은
 *  두 번째 구현이므로, 이 확인이 둘이 어긋나지 않았다는 유일한 안전장치다. */
function verifyDefaultsMatchToday() {
  try {
    const today = D.latest.views.find(v => v.key === "today").modes["잠정"];
    const params = simDefaults();
    const baseDate = parseISOJS(D.latest.base_date), evalDate = parseISOJS(D.latest.as_of);
    const anchor = today.scores.V3.anchor;
    const result = computeSim(D.bars, D.latest.tickers, params, baseDate, evalDate, anchor, D.latest.score_scale);
    const diff = Math.abs(result.scores.V3.value - today.scores.V3.value);
    if (diff > 0.05) {
      console.error(`[sim.js] 기본값이 탭2 오늘의 점수와 어긋납니다 — 차이 ${diff.toFixed(4)}점. ` +
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
    <h3>파라미터 <span class="sub">바꾸면 아래 산출 과정이 즉시 다시 계산됩니다</span></h3>
    <div style="display:flex;flex-direction:column;gap:16px">
      <div>
        <div class="group-sec-h">거래량가중 적용 여부</div>
        <div class="tabs" style="padding-bottom:0">
          <button class="tab ${SIM.weighted ? "active" : ""}" data-sim-weighted="1">거래량가중 (VWAP)</button>
          <button class="tab ${!SIM.weighted ? "active" : ""}" data-sim-weighted="0">단순 종가평균</button>
        </div>
      </div>
      <div ${SIM.weighted ? "" : 'style="opacity:.4;pointer-events:none"'}>
        <div class="group-sec-h">VWAP 산식 <span style="font-weight:var(--w-reg)">(단순 종가평균 선택 시 무의미)</span></div>
        <div class="tabs" style="padding-bottom:0">
          ${["A", "B"].map(m => `<button class="tab ${SIM.method === m ? "active" : ""}" data-sim-method="${m}">산식 ${m}</button>`).join("")}
        </div>
      </div>
      <div>
        <div class="group-sec-h">윈도우 조합 <span style="font-weight:var(--w-reg)">(2개 이상 선택 시 산술평균 — 최종 방식이 2M·1M·1W 세 개를 고르는 경우다)</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:10px 16px">
          ${WINDOW_OPTS.map(w => `<label style="display:flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer">
            <input type="checkbox" data-sim-window="${w}" ${SIM.windows.includes(w) ? "checked" : ""}>${w}</label>`).join("")}
        </div>
      </div>
      <div>
        <div class="group-sec-h">그룹 가중치 — 에화 ${(SIM.weight * 100).toFixed(0)}% · 배소 ${(100 - SIM.weight * 100).toFixed(0)}%</div>
        <input type="range" id="simWeight" min="0" max="100" step="5" value="${SIM.weight * 100}" style="width:100%">
      </div>
      <div>
        <div class="group-sec-h">Peer 종목 포함/제외 <span style="font-weight:var(--w-reg)">(그룹당 최소 1종목)</span></div>
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
                  return `<label style="display:flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer">
                    <input type="checkbox" data-sim-peer="${t.code}" ${checked ? "checked" : ""} ${lockedOn ? "disabled" : ""}>${esc(t.name)}</label>`;
                }).join("")}
              </div>
            </div>`;
          }).join("")}
        </div>
      </div>
      <div>
        <div class="group-sec-h">점수 스케일 — 기준선 ±${(SIM.scaleWidth * 100).toFixed(0)}%</div>
        <input type="range" id="simScale" min="5" max="30" step="1" value="${SIM.scaleWidth * 100}" style="width:100%">
      </div>
      <div>
        <div class="group-sec-h">공식 해석</div>
        <div class="tabs" style="padding-bottom:0">
          <button class="tab ${SIM.formula === "relative" ? "active" : ""}" data-sim-formula="relative">상대 (SK − Peer)</button>
          <button class="tab ${SIM.formula === "absolute" ? "active" : ""}" data-sim-formula="absolute">절대 (SK 단독, Peer 무시)</button>
        </div>
      </div>
      <button class="btn-mini" id="simReset" style="align-self:flex-start">기본값으로 초기화 (잠정 방식과 동일)</button>
    </div>
  </div>`;
}

function wireDesignEvents(V) {
  document.getElementById("simReset")?.addEventListener("click", () => { SIM = simDefaults(); renderDesign(V); });
  document.querySelectorAll("[data-sim-weighted]").forEach(b =>
    b.addEventListener("click", () => { SIM.weighted = b.dataset.simWeighted === "1"; renderDesign(V); }));
  document.querySelectorAll("[data-sim-method]").forEach(b =>
    b.addEventListener("click", () => { SIM.method = b.dataset.simMethod; renderDesign(V); }));
  document.querySelectorAll("[data-sim-window]").forEach(cb =>
    cb.addEventListener("change", () => {
      const w = cb.dataset.simWindow;
      if (cb.checked) { if (!SIM.windows.includes(w)) SIM.windows.push(w); }
      else if (SIM.windows.length > 1) { SIM.windows = SIM.windows.filter(x => x !== w); }
      renderDesign(V);
    }));
  document.getElementById("simWeight")?.addEventListener("change", e => { SIM.weight = Number(e.target.value) / 100; renderDesign(V); });
  document.querySelectorAll("[data-sim-peer]").forEach(cb =>
    cb.addEventListener("change", () => {
      const code = cb.dataset.simPeer;
      if (cb.checked) SIM.excluded.delete(code); else SIM.excluded.add(code);
      renderDesign(V);
    }));
  document.getElementById("simScale")?.addEventListener("change", e => { SIM.scaleWidth = Number(e.target.value) / 100; renderDesign(V); });
  document.querySelectorAll("[data-sim-formula]").forEach(b =>
    b.addEventListener("click", () => { SIM.formula = b.dataset.simFormula; renderDesign(V); }));
}

function renderDesign(V) {
  if (!SIM) SIM = simDefaults();
  const baseDate = parseISOJS(D.latest.base_date), evalDate = parseISOJS(D.latest.as_of);
  const anchor = D.latest.views.find(v => v.key === "today").modes["잠정"].scores.V3.anchor;

  let result, error = null;
  try {
    result = computeSim(D.bars, D.latest.tickers, SIM, baseDate, evalDate, anchor, D.latest.score_scale);
  } catch (e) {
    error = e.message;
  }

  const xLabel = SIM.formula === "absolute" ? "절대 증감율 x = SK (Peer 무시)" : "상대 증감율 x = SK − Peer";
  V.innerHTML = `
    ${controlsPanel()}
    ${error ? `<div class="empty"><span class="ico">⚠️</span>계산할 수 없습니다 — ${esc(error)}</div>` : `
    <div class="card">
      <h3>산출 결과 <span class="sub">기준일 ${esc(D.latest.base_date)} · 평가일(오늘) ${esc(D.latest.as_of)} · 기준선 V3(${won(anchor)}원) 고정</span></h3>
      <div class="mode-block" style="border:none;padding:0">
        <div class="mode-block-head">
          <div class="name">시뮬레이션 결과<span class="sub">파라미터를 기본값으로 두면 탭2 "오늘의 점수" · 잠정 방식과 같습니다</span></div>
          <div class="mode-block-score">
            <b class="${dirClass(result.scores.V3.value - 40)}">${pts(result.scores.V3.value)}점</b>
            <span class="raw">원값 ${pts(result.scores.V3.raw)}점${result.scores.V3.clipped ? " · 클리핑 적용" : ""}</span>
          </div>
        </div>
        ${scoreGauge(result.score_marks.V3, result.scores.V3.value)}
        ${subjectTable(result, SIM.weighted)}
        ${peerSection(result)}
        ${calcSection(result, xLabel)}
      </div>
    </div>`}
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
