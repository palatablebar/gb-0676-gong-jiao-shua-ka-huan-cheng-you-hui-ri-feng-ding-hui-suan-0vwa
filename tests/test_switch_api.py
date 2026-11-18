"""票价调整批的对外接口与页面可见性。"""
import csv
import io


def test_switch_run_via_api(client):
    r = client.post("/api/runs", json={"sample": "switch.csv"})
    assert r.status_code == 200
    p = r.get_json()
    m4 = p["stages"][3]["metrics"]
    assert m4["cross_version_chains"] >= 1
    assert p["stages"][5]["metrics"]["balanced"] is True
    # 清单带票价窗参数，run_id 因此与普通批不同
    assert p["manifest"]["parameters"]["fares"][0]["version"] == "F1"


def test_invalid_fare_window_returns_422_and_persists_nothing(client):
    base = client.post("/api/runs", json={"sample": "switch.csv"}).get_json()
    gapped = {"start": "2026-01-01T00:00:00+08:00", "end": "2026-11-15T08:00:00+08:00",
              "version": "F1", "amount": "2.00"}
    payload = {"sample": "switch.csv",
               "parameters": {"fares": [gapped, base["manifest"]["parameters"]["fares"][1]]}}
    r = client.post("/api/runs", json=payload)
    assert r.status_code == 422
    assert r.get_json()["code"] == "FARE_WINDOW_INVALID"
    # 失败切换不新增批次：历史里只有此前那一版
    runs = client.get("/api/runs").get_json()["runs"]
    assert len(runs) == 1 and runs[0]["run_id"] == base["run_id"]


def test_pages_explain_cross_version_chain(client):
    client.post("/api/runs", json={"sample": "switch.csv"})
    for slug in ("fares", "journeys", "discounts", "clearing", "settlement"):
        html = client.get("/" + slug).get_data(as_text=True)
        assert "票价版裁决" in html
        assert "刷卡时点接管" in html


def test_archive_contains_fare_window_and_settlement_rows(client):
    p = client.post("/api/runs", json={"sample": "switch.csv"}).get_json()
    text = client.get(f"/api/runs/{p['run_id']}/archive").get_data(as_text=True).lstrip("﻿")
    kinds = {row[3] for row in csv.reader(io.StringIO(text))}
    assert "fare_window" in kinds and "settlement_version" in kinds and "accepted" in kinds
