"""票价调整时点接管裁决（TRAP-27 跨版换乘链）。

裁决：新价在生效时点对尚未开始的行程【按刷卡时点接管】，不整条链锁定起始版；
换乘锚点、优惠、清分、日结引用同一票价版；切换失败保住上一版、重跑不覆盖已发布结果。
"""
import csv
import io
import pytest

from app.errors import DomainError
from app.pipeline import calculate, execute, load_sample, default_params
from app.modules.m3_fares.rules import select_fare, validate_fares, FARES
from app.modules.m4_journeys.rules import evaluate as journeys
from app.modules.m5_discounts.rules import evaluate as discounts
from app.values import instant, number


@pytest.fixture
def switch():
    raw = load_sample("switch.csv")
    return raw, default_params("switch.csv")


@pytest.fixture
def result(switch):
    return calculate(*switch)


def test_switch_sample_loaded_with_two_windows(switch):
    raw, params = switch
    windows = validate_fares(params["fares"])
    assert [w["version"] for w in windows] == ["F1", "F2"]
    assert windows[0]["end"] == windows[1]["start"]


def test_half_open_boundary_new_price_takes_over_at_effective_instant(switch):
    _, params = switch
    cut = instant("2026-11-16T08:00:00+08:00")
    assert select_fare(cut, params["fares"])["version"] == "F2"
    assert select_fare(instant("2026-11-16T07:59:59+08:00"), params["fares"])["version"] == "F1"


def test_cross_version_chain_uses_tap_time_version_per_leg(result):
    rows = {r["event_id"]: r for r in result["stages"][3]["rows"]}
    chain = [rows[e] for e in ("0100", "0101", "0102")]
    assert [r["fare_version"] for r in chain] == ["F1", "F2", "F2"]
    assert all(r["chain_cross_version"] for r in chain)
    assert chain[0]["chain_versions"] == "F1>F2>F2"
    # 选版依据必须可解释
    assert "F1" in chain[0]["fare_basis"] and "刷卡时点" in chain[0]["fare_basis"]


def test_cross_version_transfer_anchor_kept_but_priced_at_new_leg_version(result):
    rows = {r["event_id"]: r for r in result["stages"][4]["rows"]}
    leg = rows["0101"]
    assert leg["transfer_anchor"] == "0100"
    assert leg["anchor_fare_version"] == "F1"          # 锚点是旧版行程
    assert leg["discount_fare_version"] == "F2"        # 优惠口径按本腿新版
    assert leg["transfer_discount"] == "1.00"
    assert leg["expected"] == "1.50"                    # 2.50 新价 - 1.00 换乘优惠


def test_daily_cap_accumulates_across_version_switch(result):
    rows = [r for r in result["stages"][4]["rows"] if r["card"] == "0100"]
    assert rows[-1]["day_paid"] == "5.00"               # 2.00 + 1.50 + 1.50 跨版累计
    assert all(r["cap_discount"] == "0.00" for r in rows)


def test_metrics_count_cross_version_chains_and_transfers(result):
    assert result["stages"][3]["metrics"]["cross_version_chains"] == 2
    assert result["stages"][4]["metrics"]["cross_version_transfers"] == 2


def test_chain_discount_clearing_settlement_share_same_version(result):
    m5 = result["stages"][4]["metrics"]["per_version"]
    m6 = result["stages"][5]["metrics"]["per_version"]
    m7 = result["stages"][6]["metrics"]["settlement_versions"]
    assert set(m5) == set(m6) == set(m7) == {"F1", "F2"}
    # 日结直接复用清分分版口径
    assert m7 == m6
    for version in ("F1", "F2"):
        assert m6[version]["expected_total"] == m5[version]["expected_total"]
    # 分版合计与总额一致
    assert sum(number(v["expected_total"]) for v in m6.values()) == number(result["stages"][5]["metrics"]["expected_total"])


def test_settlement_seals_fare_windows(result):
    metrics = result["stages"][6]["metrics"]
    assert [w["version"] for w in metrics["fare_windows"]] == ["F1", "F2"]
    assert metrics["fare_versions"] == ["F1", "F2"]
    assert len(metrics["sha256"]) == 64 and metrics["ready"] is True


def test_per_version_discount_parameter_overrides_leg_caliber(switch):
    raw, params = switch
    params = dict(params)
    params["version_params"] = {"F2": {"transfer_discount": "0.50"}}
    r = calculate(raw, params)
    leg = next(x for x in r["stages"][4]["rows"] if x["event_id"] == "0101")
    assert leg["transfer_discount"] == "0.50" and leg["expected"] == "2.00"


def test_gap_window_fails_whole_switch_and_keeps_previous_run(switch, monkeypatch, tmp_path):
    import pathlib
    from app import store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    raw, params = switch
    saved = execute(raw, params)
    store.review(saved["run_id"], 1, "已复核")
    bad = dict(params)
    bad["fares"] = [{"start": "2026-01-01T00:00:00+08:00", "end": "2026-11-15T08:00:00+08:00",
                     "version": "F1", "amount": "2.00"},
                    {"start": "2026-11-16T08:00:00+08:00", "end": "2027-01-01T00:00:00+08:00",
                     "version": "F2", "amount": "2.50"}]
    with pytest.raises(DomainError) as e:
        execute(raw, bad)
    assert e.value.code == "FARE_WINDOW_INVALID"
    latest = store.latest()
    assert latest["run_id"] == saved["run_id"] and latest["decision"] == "已复核"
    assert len(store.history()) == 1


def test_overlapping_window_rejected():
    with pytest.raises(DomainError):
        validate_fares(FARES + [FARES[1]])


def test_rerun_same_adjustment_is_idempotent_and_cannot_overwrite_published(switch, monkeypatch, tmp_path):
    from app import store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    raw, params = switch
    first = execute(raw, params)
    store.review(first["run_id"], 1, "已复核")
    again = execute(raw, params)
    assert again["run_id"] == first["run_id"]
    assert again["version"] == 2 and again["decision"] == "已复核"
    assert len(store.history()) == 1


def test_original_taps_and_basis_preserved_in_archive(result, monkeypatch, tmp_path):
    from app import store
    from app.archive import build_archive
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    saved = store.save(result["run_id"], result)
    text = build_archive(saved).lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    kinds = {r[3] for r in rows[1:]}
    assert {"accepted", "quarantine", "fare_window", "settlement_version"} <= kinds
    accepted = [r for r in rows[1:] if r[3] == "accepted"]
    # 每条采纳记录都保留来源行与完整证据（含 fare_basis/chain_basis）
    assert all(r[4] and "fare_version" in r[6] for r in accepted)


def test_chain_marking_unit():
    rows = [
        {"event_id": "1", "card": "c", "result": "success", "at": "2026-11-16T00:00:00Z",
         "route": "01", "fare_version": "F1", "base_fare": "2.00"},
        {"event_id": "2", "card": "c", "result": "success", "at": "2026-11-16T00:30:00Z",
         "route": "02", "fare_version": "F2", "base_fare": "2.50"},
    ]
    out = journeys(rows, {})["rows"]
    assert all(r["chain_cross_version"] for r in out)
    assert out[0]["chain_versions"] == "F1>F2"


def test_discounts_without_version_field_still_defaults():
    rows = [
        {"event_id": "1", "card": "c", "business_day": "2026-11-16", "at": "2026-11-16T00:00:00Z",
         "route": "01", "base_fare": "2.50"},
        {"event_id": "2", "card": "c", "business_day": "2026-11-16", "at": "2026-11-16T00:30:00Z",
         "route": "02", "base_fare": "2.50"},
    ]
    out = discounts(rows, {"parameters": {}})
    assert out["rows"][1]["transfer_discount"] == "1.00"
    assert out["rows"][1]["anchor_fare_version"] == "__default__"
