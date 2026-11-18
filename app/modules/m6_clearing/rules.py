from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError


def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:
        m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    output=[]
    per_version={}
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        difference=expected-reported
        output.append({**row,"difference":str(difference),"status":"通过" if expected==reported else "差异"})
        bucket=per_version.setdefault(row.get("fare_version","—"),
                                      {"expected":Decimal(0),"reported":Decimal(0),"difference":Decimal(0),"rows":0,"differences":0})
        bucket["expected"]+=expected;bucket["reported"]+=reported;bucket["difference"]+=difference
        bucket["rows"]+=1;bucket["differences"]+=1 if difference else 0
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),
             reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),
             differences=sum(r["status"]=="差异" for r in output),
             per_version={v:{"rows":b["rows"],"expected_total":str(b["expected"]),"reported_total":str(b["reported"]),
                             "difference_total":str(b["difference"]),"differences":b["differences"]}
                          for v,b in sorted(per_version.items())})
    return {"rows":output,"quarantine":[],"metrics":m}
