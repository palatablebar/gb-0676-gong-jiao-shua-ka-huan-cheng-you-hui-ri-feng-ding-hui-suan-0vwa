import hashlib,json
from app.errors import DomainError
from app.reasons import sources
from decimal import Decimal


def evaluate(rows,context):
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"]["balanced"] for s in stages if "balanced" in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行未对平，不能归档")
    ids=[str(r.get("event_id",r.get("_line",""))) for r in rows]
    if len(ids)!=len(set(ids)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    # 日结必须引用与换乘链、优惠、清分同一票价版：直接沿用 M6 的分版口径，
    # 另把票价窗快照一并封存，保证四个环节指向同一票价版。
    fare_windows=context.get("fare_windows",[])
    versions=sorted(set(r.get("fare_version","—") for r in rows))
    reconcile=context.get("clearing",{})
    settlement_versions=reconcile.get("metrics",{}).get("per_version")
    if settlement_versions is None:
        per_version={}
        for r in rows:
            v=r.get("fare_version","—")
            bucket=per_version.setdefault(v,{"rows":0,"expected_total":"0.00","reported_total":"0.00","difference_total":"0.00","differences":0})
            bucket["rows"]+=1
            for src,dst in (("expected","expected_total"),("reported","reported_total"),("difference","difference_total")):
                bucket[dst]=str(Decimal(bucket[dst])+Decimal(str(r.get(src,"0"))))
            bucket["differences"]+=1 if Decimal(str(r.get("difference","0"))) else 0
        settlement_versions=dict(sorted(per_version.items()))
    seal_payload={"rows":rows,"fare_windows":fare_windows,"settlement_versions":settlement_versions}
    encoded=json.dumps(seal_payload,ensure_ascii=False,sort_keys=True,default=str).encode()
    return {"rows":rows,"quarantine":[],
            "metrics":{"records":len(rows),
                       "source_lines":len(set(x for row in rows for x in sources(row))),
                       "sha256":hashlib.sha256(encoded).hexdigest(),
                       "ready":True,
                       "differences":sum(r.get("status")=="差异" for r in rows),
                       "fare_versions":versions,
                       "fare_windows":fare_windows,
                       "settlement_versions":settlement_versions}}
