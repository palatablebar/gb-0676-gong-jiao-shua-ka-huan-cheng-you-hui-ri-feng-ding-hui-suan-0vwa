from app.values import instant,number
from app.errors import DomainError
from app.reasons import reject
from decimal import Decimal

# 裁决口径（见 docs/FARE-VERSION-RULING.md）：
# 票价版在【刷卡时点】按本腿接管，不按整条换乘链锁定起始版。
# 生效区间统一为 [start, end)；版本窗必须无缝、不重叠，否则整批切换失败、不写入新结果。
FARES=[{"start":"2026-01-01T00:00:00+08:00","end":"2026-11-01T00:00:00+08:00","version":"F1","amount":"2.00"},
       {"start":"2026-11-01T00:00:00+08:00","end":"2027-01-01T00:00:00+08:00","version":"F2","amount":"2.50"}]

REQUIRED_WINDOW_FIELDS=("version","start","end","amount")


def validate_fares(fares):
    """整表校验票价窗：字段齐备、金额合法、时间升序、无缝且不重叠。

    任何一条不合法都抛出 FARE_WINDOW_INVALID，使本次切换/计算整体失败，
    由保存层保证上一版已发布结果不被覆盖。
    """
    if not isinstance(fares,list) or not fares:
        raise DomainError("FARE_WINDOW_INVALID","票价窗为空，无法裁决票价版")
    seen_versions=set()
    for i,rule in enumerate(fares):
        if not isinstance(rule,dict) or any(k not in rule for k in REQUIRED_WINDOW_FIELDS):
            raise DomainError("FARE_WINDOW_INVALID",f"票价窗第{i+1}条字段不完整，需要 {REQUIRED_WINDOW_FIELDS}")
        if rule["version"] in seen_versions:
            raise DomainError("FARE_WINDOW_INVALID",f"票价版 {rule['version']} 重复")
        seen_versions.add(rule["version"])
        try:
            amount=number(rule["amount"])
            start=instant(rule["start"]);end=instant(rule["end"])
        except DomainError as e:
            raise DomainError("FARE_WINDOW_INVALID",f"票价窗 {rule['version']} {e.message}")
        if amount<0:
            raise DomainError("FARE_WINDOW_INVALID",f"票价窗 {rule['version']} 金额不能为负")
        if not start<end:
            raise DomainError("FARE_WINDOW_INVALID",f"票价窗 {rule['version']} 生效起止顺序错误")
    ordered=sorted(fares,key=lambda r:instant(r["start"]))
    for prev,nxt in zip(ordered,ordered[1:]):
        if instant(prev["end"])!=instant(nxt["start"]):
            raise DomainError("FARE_WINDOW_INVALID",
                              f"票价窗在 {prev['version']} 与 {nxt['version']} 之间存在缝隙或重叠")
        if instant(prev["end"])<=instant(prev["start"]) or instant(nxt["end"])<=instant(nxt["start"]):
            raise DomainError("FARE_WINDOW_INVALID","票价窗生效区间无效")
    return ordered


def select_fare(at,fares):
    hits=[r for r in fares if instant(r["start"])<=at<instant(r["end"])]
    if len(hits)!=1:
        raise DomainError("FARE_CONFLICT","票价无效或生效窗重叠")
    return hits[0]


def evaluate(rows,context):
    params=context.get("parameters",{})
    fares=validate_fares(params.get("fares",FARES))
    context["fare_windows"]=fares
    good=[];bad=[]
    for row in rows:
        try:
            at=instant(row["event_time"])
            rule=select_fare(at,fares)
            reported=number(row["reported"])
            if reported<0:
                raise DomainError("NEGATIVE_FARE","实扣金额不能为负")
            good.append({**row,
                         "at":at.isoformat(),
                         "base_fare":rule["amount"],
                         "fare_version":rule["version"],
                         "fare_effective_from":rule["start"],
                         "fare_effective_to":rule["end"],
                         "fare_basis":f"刷卡时点 {row['event_time']} 落在 {rule['version']} 生效窗 [{rule['start']}, {rule['end']})",
                         "reported":str(reported)})
        except (DomainError,KeyError) as e:
            bad.append(reject(row,getattr(e,"code","MISSING_FIELD"),str(e)))
    metrics={"accepted":len(good),
             "versions":sorted(set(r["fare_version"] for r in good)),
             "fare_windows":[{"version":r["version"],"start":r["start"],"end":r["end"],"amount":r["amount"]} for r in fares]}
    return {"rows":good,"quarantine":bad,"metrics":metrics}
