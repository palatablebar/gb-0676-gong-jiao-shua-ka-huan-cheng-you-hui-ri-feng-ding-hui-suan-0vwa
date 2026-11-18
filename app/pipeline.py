import time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import digest,manifest
from app import store
from app.modules.m1_taps.rules import evaluate as stage1
from app.modules.m2_routes.rules import evaluate as stage2
from app.modules.m3_fares.rules import evaluate as stage3
from app.modules.m4_journeys.rules import evaluate as stage4
from app.modules.m5_discounts.rules import evaluate as stage5
from app.modules.m6_clearing.rules import evaluate as stage6
from app.modules.m7_settlement.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]

SAMPLES={"dirty.csv","clean.csv","legacy.csv","switch.csv"}

# 票价调整演示批：调整时点设在 2026-11-16 08:00 (+08:00)，
# 让同一业务日内的换乘链真实跨过生效时点；票价窗 [start,end) 半开，
# 08:00 当刻即由新版接管，参数随输入摘要进入 run_id 与清单。
SWITCH_PARAMS={
    "fares":[
        {"start":"2026-01-01T00:00:00+08:00","end":"2026-11-16T08:00:00+08:00","version":"F1","amount":"2.00"},
        {"start":"2026-11-16T08:00:00+08:00","end":"2027-01-01T00:00:00+08:00","version":"F2","amount":"2.50"},
    ],
    "transfer_discount":"1.00",
    "transfer_minutes":"60",
    "daily_cap":"6.00",
}


def load_sample(name):
    if name not in SAMPLES: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()


def default_params(name):
    return dict(SWITCH_PARAMS) if name=="switch.csv" else {}


def calculate(raw,params=None,stop=6):
    params=params or {};started=time.monotonic();context={"parameters":params,"raw":raw,"quarantine":[]};stages=[];rows=[]
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        if index==0: context["intake"]=result["metrics"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        stages.append(result)
    return {"run_id":digest(raw,params)[:20],"stages":stages,"manifest":manifest(raw,params,started),"parameters":params}


def execute(raw,params=None):
    result=calculate(raw,params);return store.save(result["run_id"],result)


def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    sample=payload.get("sample","dirty.csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(sample)
    params=payload.get("parameters") or default_params(sample)
    return calculate(raw,params,index)["stages"][-1]
