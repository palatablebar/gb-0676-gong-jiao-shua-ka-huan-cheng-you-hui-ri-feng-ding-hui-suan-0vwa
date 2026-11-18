from app.reasons import reject
from app.values import instant
from datetime import timezone,timedelta

CN=timezone(timedelta(hours=8))


def evaluate(rows,context):
    good=[];bad=[];seen=set()
    for row in sorted(rows,key=lambda r:(r.get("card",""),r["at"],r.get("event_id",""))):
        if row.get("result")!="success":
            bad.append(reject(row,"FAILED_TAP","失败刷卡不构成行程"));continue
        key=(row["card"],row["at"])
        if key in seen:
            bad.append(reject(row,"SIMULTANEOUS_TAP","同卡同刻多行程"));continue
        seen.add(key)
        at=instant(row["at"])
        good.append({**row,
                     "business_day":at.astimezone(CN).date().isoformat(),
                     "journey":row["card"]+"-"+row["event_id"]})

    # 换乘链：同卡同业务日内按时间排序的连续成功行程即一条链。
    # 链本身不锁票价版——票价由 M3 在每条腿的刷卡时点裁决，这里只标记跨版事实。
    chains={}
    ordered=sorted(good,key=lambda r:(r["card"],r["business_day"],instant(r["at"]),r["event_id"]))
    current=None
    for row in ordered:
        key=(row["card"],row["business_day"])
        if current is None or current["key"]!=key:
            current={"key":key,"chain_id":f"{row['card']}-{row['business_day']}","versions":[]}
            chains[key]=current
        current["versions"].append(row.get("fare_version",""))
    cross={key for key,ch in chains.items() if len(set(v for v in ch["versions"] if v))>1}

    for row in good:
        key=(row["card"],row["business_day"])
        versions=[v for v in chains[key]["versions"] if v]
        row["chain_id"]=chains[key]["chain_id"]
        row["chain_versions"]=">".join(versions) if versions else "—"
        row["chain_cross_version"]=key in cross
        row["chain_basis"]=("同卡同业务日连续行程，链内票价版由各腿刷卡时点裁决："+row["chain_versions"]) \
            if row["chain_cross_version"] else "链内各腿同一票价版"

    return {"rows":good,
            "quarantine":bad,
            "metrics":{"journeys":len(good),
                       "cards":len(set(r["card"] for r in good)),
                       "chains":len(chains),
                       "cross_version_chains":len(cross)}}
