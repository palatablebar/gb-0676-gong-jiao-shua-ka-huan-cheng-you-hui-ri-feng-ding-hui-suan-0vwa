from decimal import Decimal
from app.values import number,instant,money
from app.errors import DomainError

DEFAULT_VERSION="__default__"


def _param(versioned,name,fallback):
    """优惠参数按腿的票价版取口径；该版未单独公布时回退到全局参数。"""
    if isinstance(versioned,dict) and name in versioned:
        return versioned[name]
    return fallback


def evaluate(rows,context):
    params=context.get("parameters",{})
    cap=number(params.get("daily_cap","6.00"))
    off=number(params.get("transfer_discount","1.00"))
    window=number(params.get("transfer_minutes","60"))
    version_params=params.get("version_params",{})
    if not isinstance(version_params,dict):
        raise DomainError("BAD_DISCOUNT","分版优惠参数需要对象")
    if cap<0 or off<0 or window<0:
        raise DomainError("BAD_DISCOUNT","优惠参数不能为负")
    for ver,cfg in version_params.items():
        if not isinstance(cfg,dict):
            raise DomainError("BAD_DISCOUNT",f"票价版 {ver} 的优惠参数需要对象")
        for name in ("daily_cap","transfer_discount","transfer_minutes"):
            if name in cfg and number(cfg[name])<0:
                raise DomainError("BAD_DISCOUNT",f"票价版 {ver} 的 {name} 不能为负")

    spent={};anchor={};good=[]
    # 优惠/封顶按【本腿刷卡时点的票价版】取口径；日封顶是卡日维度，跨版累计同一钱包。
    for row in sorted(rows,key=lambda r:(r["card"],instant(r["at"]),r["event_id"])):
        key=(row["card"],row["business_day"])
        version=row.get("fare_version",DEFAULT_VERSION)
        cfg=version_params.get(version,{})
        leg_off=number(_param(cfg,"transfer_discount",off))
        leg_window=number(_param(cfg,"transfer_minutes",window))
        leg_cap=number(_param(cfg,"daily_cap",cap))

        base=number(row["base_fare"])
        previous=anchor.get(key)
        eligible=False
        if previous:
            delta=Decimal(str((instant(row["at"])-instant(previous["at"])).total_seconds()))/60
            eligible=previous["route"]!=row["route"] and Decimal(0)<=delta<leg_window
        transfer=min(base,leg_off) if eligible else Decimal(0)
        after_transfer=base-transfer
        # 日封顶跨版累计：已花金额不随换版清零，剩余额度按本腿版的封顶计算。
        remaining=max(Decimal(0),leg_cap-spent.get(key,Decimal(0)))
        charge=min(after_transfer,remaining)
        cap_discount=after_transfer-charge
        spent[key]=spent.get(key,Decimal(0))+charge
        good.append({**row,
                     "transfer_anchor":previous["event_id"] if eligible else "—",
                     "anchor_fare_version":previous.get("fare_version",DEFAULT_VERSION) if eligible else "—",
                     "discount_fare_version":version,
                     "transfer_discount":money(transfer),
                     "cap_discount":money(cap_discount),
                     "expected":money(charge),
                     "day_paid":money(spent[key]),
                     "version_basis":(f"本腿 {version} 口径：换乘优惠 {money(leg_off)} 元 / 换乘窗 {leg_window} 分钟 / 日封顶 {money(leg_cap)} 元"
                                      +("；锚点 "+previous.get("fare_version",DEFAULT_VERSION)+" 版，仅用于时间窗与换线判定" if eligible else ""))})
        if charge>0:
            anchor[key]=row

    per_version={}
    for r in good:
        v=r.get("fare_version",DEFAULT_VERSION)
        bucket=per_version.setdefault(v,{"expected":Decimal(0),"transfer":Decimal(0),"cap":Decimal(0),"legs":0})
        bucket["expected"]+=number(r["expected"])
        bucket["transfer"]+=number(r["transfer_discount"])
        bucket["cap"]+=number(r["cap_discount"])
        bucket["legs"]+=1
    metrics={"expected_total":money(sum((number(r["expected"]) for r in good),Decimal(0))),
             "daily_caps":len(spent),
             "transfer_hits":sum(r["transfer_anchor"]!="—" for r in good),
             "cross_version_transfers":sum(1 for r in good if r["transfer_anchor"]!="—" and r["anchor_fare_version"]!=r.get("fare_version",DEFAULT_VERSION)),
             "per_version":{v:{"legs":b["legs"],"expected_total":money(b["expected"]),
                               "transfer_discount_total":money(b["transfer"]),
                               "cap_discount_total":money(b["cap"])} for v,b in sorted(per_version.items())}}
    return {"rows":good,"quarantine":[],"metrics":metrics}
