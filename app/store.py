import sqlite3,json
from pathlib import Path
from app.config import DATA_DIR
from app.errors import DomainError

PUBLISHED="已复核"


def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    return db


def save(run_id,payload):
    """内容寻址保存：同输入+同参数+同规则版本得到同一 run_id。

    重跑同一调整只复用已有批次，绝不新增第二份、也不覆盖已发布结果；
    事务内任一步失败整体回滚，上一版结果保持可读。
    """
    encoded=json.dumps(payload,ensure_ascii=False)
    with connect() as db:
        existing=db.execute("SELECT decision FROM runs WHERE id=?",(run_id,)).fetchone()
        if existing is not None:
            # 已存在（含已发布）批次：幂等复用，INSERT OR IGNORE 不改写 payload/version/decision。
            db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,encoded))
            return get(run_id)
        db.execute("INSERT INTO runs(id,payload) VALUES (?,?)",(run_id,encoded))
    return get(run_id)


def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}


def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None


def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]


def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        # 乐观锁条件更新：陈旧版本号只能得到 409，已发布结果不会被并发提交覆盖。
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
