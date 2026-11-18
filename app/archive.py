import csv,io,json


def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[]),ensure_ascii=False),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[]),ensure_ascii=False),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    # 票价窗快照与分版日结口径一并入证：换乘链、优惠、清分、日结引用同一票价版可追溯。
    settlement=run["stages"][-1]["metrics"]
    for window in settlement.get("fare_windows",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"fare_window","",window.get("version",""),json.dumps(window,ensure_ascii=False)])
    for version,basis in settlement.get("settlement_versions",{}).items():
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"settlement_version","",version,json.dumps(basis,ensure_ascii=False)])
    return "﻿"+stream.getvalue()
