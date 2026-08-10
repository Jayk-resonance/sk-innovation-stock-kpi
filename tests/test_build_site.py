"""사이트 데이터가 계산 엔진과 어긋나지 않는지 확인한다.

사이트는 계산하지 않으므로, 여기서 보증할 것은 **JSON이 엔진 결과를 그대로 담았는가**다.
"""
from datetime import date

import pytest

from core.evaluate import evaluate
from pipeline.build_site import build_bars, build_history, build_latest, build_scenarios, write_site_data


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
    assert diff < 1.0  # PLAN.md §2


def test_score_marks_bracket_official_anchor(prices, universe, rules, calibration):
    """0·40·80·100점 눈금이 앵커를 기준으로 올바른 위치에 있어야 한다."""
    payload = build_latest(prices, universe, rules, calibration)
    marks = payload["views"][0]["modes"]["잠정"]["score_marks"]["V3"]
    by_pt = {m["points"]: m["price"] for m in marks}
    assert by_pt[0] == pytest.approx(113109 * 0.85, abs=0.5)
    assert by_pt[40] == pytest.approx(113109, abs=0.5)
    assert by_pt[80] == pytest.approx(113109 * 1.10, abs=0.5)
    assert by_pt[100] == pytest.approx(113109 * 1.15, abs=0.5)


def test_mode_detail_groups_have_members_and_windows(prices, universe, rules, calibration):
    payload = build_latest(prices, universe, rules, calibration)
    fin = payload["views"][0]["modes"]["최종"]
    assert {w["spec"] for w in fin["windows_now"]} == {"2M", "1M", "1W"}
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
        want.scores["V3"].value, abs=0.01
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
