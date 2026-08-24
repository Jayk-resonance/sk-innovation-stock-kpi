"""사이트 데이터가 계산 엔진과 어긋나지 않는지 확인한다.

사이트는 계산하지 않으므로, 여기서 보증할 것은 **JSON이 엔진 결과를 그대로 담았는가**다.
"""
from datetime import date

import pytest

from core.evaluate import evaluate
from core.schema import load_candidates
from pipeline.build_site import (
    _market_cap_rating,
    build_bars,
    build_history,
    build_latest,
    build_scenarios,
    sync_asset_versions,
    write_site_data,
)


def test_views_match_engine(prices, universe, rules, calibration):
    """오늘 화면 + 확정 평가일마다, 잠정·최종 두 방식 모두 엔진 결과와 일치해야 한다."""
    payload = build_latest(prices, universe, rules, calibration)
    method = rules["vwap_primary"]
    for view in payload["views"]:
        eval_date = date.fromisoformat(view["date"])
        for mode in ("잠정", "최종"):
            got = view["modes"][mode]
            want = evaluate(prices, universe, rules, calibration, eval_date, mode, method)
            assert got["eval_price"] == pytest.approx(want.eval_price, abs=0.01)
            assert got["relative_change"] == pytest.approx(want.relative_change, abs=1e-6)
            for key, score in want.scores.items():
                assert got["scores"][key]["value"] == pytest.approx(score.value, abs=0.01)


def test_views_include_today_and_confirmed_evaluations(prices, universe, rules, calibration):
    payload = build_latest(prices, universe, rules, calibration)
    keys = [v["key"] for v in payload["views"]]
    assert keys[0] == "today"
    assert len(payload["views"]) == 1 + len([e for e in rules["eval_dates"] if e["date"]])
    assert payload["views"][0]["confirmed"] is False
    assert all(v["confirmed"] for v in payload["views"][1:])


def test_sidebar_change_is_previous_trading_day_close_return(prices, universe, rules, calibration):
    """좌측 평가대상 등락률은 최신 종가의 직전 거래일 종가 대비 변화다."""
    payload = build_latest(prices, universe, rules, calibration)
    sk = universe.subject.code
    latest, previous = prices[sk][-1], prices[sk][-2]
    ticker = next(t for t in payload["tickers"] if t["code"] == sk)
    assert payload["as_of"] == latest.day.isoformat()
    assert ticker["previous_close"] == previous.close
    assert ticker["change_pct"] == pytest.approx(latest.close / previous.close - 1, abs=1e-6)


def test_price_status_uses_same_final_method_as_today_score(prices, universe, rules, calibration):
    """주가현황의 평가 주가와 연말 대비 증감률은 오늘의 점수 최종 방식과 같아야 한다."""
    payload = build_latest(prices, universe, rules, calibration)
    final = payload["views"][0]["modes"]["최종"]
    tickers = {ticker["code"]: ticker for ticker in payload["tickers"]}

    subject = tickers[universe.subject.code]
    assert subject["evaluation_price"] == pytest.approx(final["subject_price"], abs=0.01)
    assert subject["change_from_base"] == pytest.approx(final["subject_change"], abs=1e-6)

    for group in final["groups"].values():
        for member in group["members"]:
            ticker = tickers[member["code"]]
            assert ticker["evaluation_price"] == pytest.approx(member["price"], abs=0.01)
            assert ticker["change_from_base"] == pytest.approx(member["change"], abs=1e-6)


def test_h1_zero_score_surfaces_with_raw(prices, universe, rules, calibration):
    """0점으로 잘린 사실과 원값이 함께 실려야 한다."""
    payload = build_latest(prices, universe, rules, calibration)
    h1 = next(v for v in payload["views"] if v["label"] == "2026 상반기")
    prov = h1["modes"]["잠정"]["scores"]["V3"]
    assert prov["value"] == 0
    assert prov["raw"] < 0
    assert prov["clipped"] is True


def test_method_compare_present_for_today(prices, universe, rules, calibration):
    payload = build_latest(prices, universe, rules, calibration)
    assert set(payload["method_compare"]) == set(rules["vwap_methods"])
    diff = abs(payload["method_compare"]["A"]["scores"]["V3"]["raw"]
               - payload["method_compare"]["B"]["scores"]["V3"]["raw"])
    assert diff > 0


def test_score_marks_bracket_official_anchor(prices, universe, rules, calibration):
    """0·40·80·100점 눈금이 앵커를 기준으로 올바른 위치에 있어야 한다."""
    payload = build_latest(prices, universe, rules, calibration)
    marks = payload["views"][0]["modes"]["잠정"]["score_marks"]["V3"]
    by_pt = {m["points"]: m["price"] for m in marks}
    assert by_pt[0] == pytest.approx(113109 * 0.85, abs=0.5)
    assert by_pt[40] == pytest.approx(113109, abs=0.5)
    assert by_pt[80] == pytest.approx(113109 * 1.10, abs=0.5)
    assert by_pt[100] == pytest.approx(113109 * 1.15, abs=0.5)


def test_today_uses_manual_final_target(prices, universe, rules, calibration):
    """오늘의 점수는 수기 검산한 109,922원을 40점 기준으로 사용한다."""
    payload = build_latest(prices, universe, rules, calibration)
    score = payload["views"][0]["modes"]["최종"]["scores"]["V2"]
    marks = payload["views"][0]["modes"]["최종"]["score_marks"]["V2"]
    by_pt = {m["points"]: m["price"] for m in marks}
    assert score["anchor"] == 109_922
    assert by_pt[0] == pytest.approx(109_922 * 0.85, abs=0.5)
    assert by_pt[40] == pytest.approx(109_922, abs=0.5)
    assert by_pt[100] == pytest.approx(109_922 * 1.15, abs=0.5)


def test_mode_detail_groups_have_members_and_windows(prices, universe, rules, calibration):
    payload = build_latest(prices, universe, rules, calibration)
    fin = payload["views"][0]["modes"]["최종"]
    assert {w["spec"] for w in fin["windows_now"]} == {"2M", "1M", "1W"}
    windows = {w["spec"]: w for w in fin["windows_now"]}
    assert {w["end_date"] for w in windows.values()} == {payload["as_of"]}
    assert (
        date.fromisoformat(windows["2M"]["start_date"])
        < date.fromisoformat(windows["1M"]["start_date"])
        < date.fromisoformat(windows["1W"]["start_date"])
        <= date.fromisoformat(payload["as_of"])
    )
    base_windows = {w["spec"]: w for w in fin["windows_base"]}
    assert (base_windows["2M"]["start_date"], base_windows["2M"]["end_date"]) == (
        "2025-11-03", "2025-12-30"
    )
    assert (base_windows["1M"]["start_date"], base_windows["1M"]["end_date"]) == (
        "2025-12-01", "2025-12-30"
    )
    assert (base_windows["1W"]["start_date"], base_windows["1W"]["end_date"]) == (
        "2025-12-23", "2025-12-30"
    )
    assert fin["subject_base_price"] == pytest.approx(109_922, abs=1)
    samsung = next(m for m in fin["groups"]["배소"]["members"] if m["name"] == "삼성SDI")
    assert samsung["base_price"] == pytest.approx(292_042, abs=1)
    assert len(fin["groups"]["에화"]["members"]) == 4
    assert len(fin["groups"]["배소"]["members"]) == 4
    assert fin["groups"]["에화"]["weight"] == pytest.approx(0.6)


def test_mode_detail_carries_daily_and_weighted_price_chart(prices, universe, rules, calibration):
    payload = build_latest(prices, universe, rules, calibration)
    fin = payload["views"][0]["modes"]["최종"]
    chart = fin["subject_chart"]
    base = next(point for point in chart if point["date"] == payload["base_date"])
    assert chart[-1]["date"] == fin["eval_date"]
    assert chart[-1]["close"] == fin["subject_close"]
    assert base["close"] == fin["subject_base_close"]
    assert chart[-1]["daily_weighted_price"] == fin["subject_daily_weighted_price"]
    assert base["daily_weighted_price"] == fin["subject_base_daily_weighted_price"]
    # 기본 산식 B는 종가×거래량을 사용하므로 1일 값은 그날 종가와 같다.
    assert fin["method"] == "B"
    assert fin["subject_daily_weighted_price"] == pytest.approx(fin["subject_close"])
    assert fin["subject_base_daily_weighted_price"] == pytest.approx(fin["subject_base_close"])
    assert chart[-1]["vwap_2m"] == pytest.approx(fin["windows_now"][0]["vwap"])
    assert chart[-1]["vwap_final"] == pytest.approx(fin["subject_price"])


def test_mode_detail_carries_target_waterfall_sensitivity(prices, universe, rules, calibration):
    payload = build_latest(prices, universe, rules, calibration)
    prov = payload["views"][0]["modes"]["잠정"]
    assert set(prov["targets"]) == {0, 40, 80, 100}
    assert prov["targets"][100]["needed_vwap"] > prov["targets"][0]["needed_vwap"]
    assert len(prov["waterfall"]) == 9  # 출발점 + 8개 Peer
    assert len(prov["sensitivity"]["rows"]) == 6  # SK/에화/배소 각 ±1%p


def test_build_scenarios_has_final_baseline_comparison_and_paths(prices, universe, rules, calibration):
    sc = build_scenarios(prices, universe, rules, calibration)
    assert len(sc["matrix"]) == 3
    assert {r["mode"] for r in sc["matrix"]} == {"최종"}
    assert {r["method"] for r in sc["matrix"]} == {rules["vwap_primary"]}
    assert set(sc["remaining_paths"]) == {1, 2, 3}
    assert len(sc["timeseries"]) > 0
    assert sc["timeseries"][-1]["date"] == sc["as_of"]
    want = evaluate(
        prices, universe, rules, calibration, date.fromisoformat(sc["as_of"]),
        "최종", rules["vwap_primary"],
    )
    assert sc["timeseries"][-1]["value"] == pytest.approx(
        want.scores["V2"].value, abs=0.01
    )
    assert sc["timeseries"][-1]["subject_price"] == pytest.approx(want.subject_price, abs=0.01)
    assert sc["timeseries"][-1]["peer_change"] == pytest.approx(want.peer_change, abs=0.000001)
    assert sc["timeseries"][-1]["eval_price"] == pytest.approx(want.eval_price, abs=0.01)


def test_build_bars_has_raw_series_for_every_ticker(prices, universe):
    bars = build_bars(prices)
    for ticker in universe.all_tickers:
        assert ticker.code in bars
        b = bars[ticker.code]
        assert len(b["dates"]) == len(b["close"]) == len(b["volume"]) == len(b["trading_value"])


def test_coverage_is_clean_after_backfill(prices, universe, rules, calibration):
    """백필 완료: 공백 0, 검증불가 0, 불일치 0."""
    cov = build_latest(prices, universe, rules, calibration)["coverage"]
    assert cov["gaps"] == []
    assert cov["unverified_months"] == []
    assert cov["mismatched_months"] == []
    assert len(cov["verified_months"]) == 11


def test_next_eval_is_null_when_unannounced(prices, universe, rules, calibration):
    """평가일을 추정하지 않는다 — 미확정이면 null 이다."""
    payload = build_latest(prices, universe, rules, calibration)
    assert payload["next_eval"] is None


def test_history_is_continuous_after_backfill(prices, rules):
    hist = build_history(prices, rules["base_date"])
    assert len(hist["dates"]) == len(hist["close"]["096770"])
    assert hist["gap_after"] == [], "수집 공백이 남아 있다"
    anchor_idx = hist["dates"].index(hist["base_date"])
    assert hist["indexed"]["096770"][anchor_idx] == pytest.approx(100.0)


def test_history_indexes_every_ticker(prices, universe, rules):
    hist = build_history(prices, rules["base_date"])
    for ticker in universe.all_tickers:
        assert ticker.code in hist["indexed"]


def test_write_site_data(prices, universe, rules, calibration, tmp_path):
    paths = write_site_data(prices, universe, rules, calibration, out_dir=tmp_path)
    assert {p.name for p in paths} == {
        "latest.json", "history.json", "scenarios.json", "bars.json", "changelog.json",
    }
    non_empty = {p.name for p in paths} - {"changelog.json"}  # 커밋 전이면 changelog 는 빈 배열일 수 있다
    assert all(p.stat().st_size > 500 for p in paths if p.name in non_empty)


def test_sync_asset_versions_rewrites_stale_hash(tmp_path):
    """app.js 내용이 바뀌었는데 index.html 의 ?v= 해시가 그대로면, 브라우저가
    캐시된 옛 파일을 계속 쓴다 — 2026-08-13 hover 버그가 정확히 이렇게 났다.
    빌드할 때마다 해시를 자동으로 맞춰야 이 문제가 재발하지 않는다."""
    import hashlib

    def blob_hash(text: str) -> str:
        data = text.encode()
        return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()[:7]

    docs = tmp_path / "docs"
    (docs / "assets").mkdir(parents=True)
    app_js, style_css, sim_js = "console.log('v2')", "body{color:red}", "// sim"
    (docs / "assets" / "app.js").write_text(app_js, encoding="utf-8")
    (docs / "assets" / "style.css").write_text(style_css, encoding="utf-8")
    (docs / "assets" / "sim.js").write_text(sim_js, encoding="utf-8")
    (docs / "index.html").write_text(
        '<link rel="stylesheet" href="assets/style.css?v=0000000">\n'
        '<script src="assets/sim.js?v=1111111"></script>\n'
        '<script src="assets/app.js?v=stale00"></script>\n',
        encoding="utf-8",
    )

    result = sync_asset_versions(docs)
    assert result == docs / "index.html"
    html = result.read_text(encoding="utf-8")
    assert f"app.js?v={blob_hash(app_js)}" in html
    assert f"style.css?v={blob_hash(style_css)}" in html
    assert f"sim.js?v={blob_hash(sim_js)}" in html

    # 다시 돌리면(내용 변화 없음) 더 손대지 않는다 — 반복 실행이 안전해야 한다.
    assert sync_asset_versions(docs) is None


def test_market_cap_rating_thresholds():
    """0.5~2배는 적정, 그 밖은 격차 — 경계값에서 뒤집히지 않는지 고정한다."""
    assert _market_cap_rating(None) == "확인 불가"
    assert _market_cap_rating(1.0) == "적정"
    assert _market_cap_rating(0.5) == "적정"
    assert _market_cap_rating(2.0) == "적정"
    assert _market_cap_rating(0.49) == "격차 있음"
    assert _market_cap_rating(3.0) == "격차 있음"
    assert _market_cap_rating(0.1) == "격차 큼"
    assert _market_cap_rating(5.0) == "격차 큼"


def test_load_candidates_returns_experimental_peers():
    """27년 과제 설계 탭 전용 후보 — universe.groups 와는 별도 섹션이다."""
    candidates = load_candidates()
    codes = {c.ticker.code for c in candidates}
    assert codes == {"006650", "004690"}
    assert all(c.group in ("에화", "배소") for c in candidates)


def test_candidates_excluded_from_official_score_but_present_in_payload(prices, universe, rules, calibration):
    """실험용 후보는 오늘의 점수(tickers/views)에는 나타나지 않고, candidates 필드에만 실린다."""
    payload = build_latest(prices, universe, rules, calibration)
    official_codes = {t["code"] for t in payload["tickers"]}
    assert {"006650", "004690"}.isdisjoint(official_codes)

    candidate_codes = {c["code"] for c in payload["candidates"]}
    assert candidate_codes == {"006650", "004690"}
    for c in payload["candidates"]:
        for key in ("business_match", "independence", "market_cap", "liquidity"):
            assert key in c["peer_eval"]


def test_build_bars_includes_candidate_codes(prices):
    """sim.js 가 후보를 켰을 때 계산할 수 있도록 원자료가 있어야 한다."""
    bars = build_bars(prices)
    assert "006650" in bars
    assert "004690" in bars


def test_peer_eval_present_for_every_peer_and_absent_for_subject(prices, universe, rules, calibration):
    """Peer 선정 적정성은 8개 Peer 전부에 붙고, 본사(SK이노베이션)에는 붙지 않는다."""
    payload = build_latest(prices, universe, rules, calibration)
    by_code = {t["code"]: t for t in payload["tickers"]}
    assert "peer_eval" not in by_code[universe.subject.code]
    pool_size = len(universe.peers) + len(load_candidates())
    for peer in universe.peers:
        evaluation = by_code[peer.code]["peer_eval"]
        for key in ("business_match", "independence", "market_cap", "liquidity"):
            assert key in evaluation
        cap = evaluation["market_cap"]
        assert cap["rating"] in {"적정", "격차 있음", "격차 큼", "확인 불가"}
        liquidity = evaluation["liquidity"]
        if liquidity["rank"] is not None:
            assert 1 <= liquidity["rank"] <= liquidity["of"] == pool_size


def test_peer_and_candidate_liquidity_share_same_ranking_pool(prices, universe, rules, calibration):
    """공식 Peer hover 와 후보 hover 의 "n개사 중" 이 같은 모집단을 가리켜야 한다 —
    그룹별로 따로 매기면 8개사 중/5개사 중 처럼 기준이 달라 보여 혼란스럽다."""
    payload = build_latest(prices, universe, rules, calibration)
    pool_size = len(universe.peers) + len(load_candidates())
    peer_ofs = {t["peer_eval"]["liquidity"]["of"] for t in payload["tickers"] if "peer_eval" in t}
    candidate_ofs = {c["peer_eval"]["liquidity"]["of"] for c in payload["candidates"]}
    assert peer_ofs == candidate_ofs == {pool_size}
