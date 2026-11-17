import os,sqlite3,json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.errors import DomainError
from app.normalize import serial, instant
_ZONE=timezone(timedelta(hours=8))
def connection():
    path=Path(os.environ.get("DATA_DIR","data"));path.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path/"runs.sqlite",timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,review TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS curve_revisions (effective_at TEXT NOT NULL,curve TEXT NOT NULL,run_id TEXT NOT NULL,created TEXT NOT NULL DEFAULT '',PRIMARY KEY(effective_at))")
    db.execute("CREATE TABLE IF NOT EXISTS confirmed_days (station TEXT NOT NULL,date TEXT NOT NULL,run_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(station,date))")
    return db
def save(result):
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES(?,?)",(result["manifest"]["run_id"],json.dumps(result,ensure_ascii=False)))
    return fetch(result["manifest"]["run_id"])
def _replace_stage_rows(payload,stage_title,keyed_rows):
    for stage in payload.get("stages",[]):
        if stage.get("title")==stage_title:
            stage["rows"]=[keyed_rows.get((x["station"],x["date"]),x) for x in stage["rows"]]
            return
def _apply_confirmed(payload):
    """已复核日账保持原曲线：重算结果中属于已确认日的行整行替换为确认时快照，行仍在日账中展示。"""
    with connection() as db:
        snap=db.execute("SELECT station,date,payload FROM confirmed_days").fetchall()
    if not snap:return payload
    keyed={(r["station"],r["date"]):json.loads(r["payload"]) for r in snap}
    if payload.get("budgets"):
        payload["budgets"]=[keyed.get((x["station"],x["date"]),x) for x in payload["budgets"]]
    if payload.get("review_rows"):
        payload["review_rows"]=[keyed.get((x["station"],x["date"]),x) for x in payload["review_rows"]]
    _replace_stage_rows(payload,"日水量收支",keyed)
    _replace_stage_rows(payload,"异常复核",keyed)
    payload["confirmed_days"]=sorted(({"station":r["station"],"date":r["date"]} for r in snap),key=lambda x:(x["date"],x["station"]))
    payload["resume_from"]=min((r["date"] for r in snap),default=None)
    return payload
def fetch(run_id):
    with connection() as db: row=db.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
    if row is None: raise DomainError("NOT_FOUND","批次不存在",404)
    result=json.loads(row["payload"]);result["version"]=row["version"];result["review"]=row["review"]
    return _apply_confirmed(result)
def history():
    with connection() as db: rows=db.execute("SELECT id,version,review FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]
def list_revisions():
    with connection() as db: rows=db.execute("SELECT effective_at,curve,run_id,created FROM curve_revisions ORDER BY effective_at").fetchall()
    out=[]
    for row in rows:
        item=dict(row);item["curve"]=json.loads(item["curve"]);out.append(item)
    return out
def confirmed_dates():
    with connection() as db:
        rows=db.execute("SELECT DISTINCT station,date FROM confirmed_days").fetchall()
    return [dict(row) for row in rows]
def register_revision(effective_at,curve,run_id,created):
    """登记改版。同一生效时刻重复登记返回既有记录，不产生第二次曲线调整。"""
    key=instant(effective_at).isoformat()
    curve_text=json.dumps(serial(curve),ensure_ascii=False)
    with connection() as db:
        existing=db.execute("SELECT effective_at,curve,run_id,created FROM curve_revisions WHERE effective_at=?",(key,)).fetchone()
        if existing is not None:
            item=dict(existing);item["curve"]=json.loads(item["curve"]);item["status"]="已存在";return item
        local_day=instant(effective_at).astimezone(_ZONE).date().isoformat()
        hit=db.execute("SELECT date FROM confirmed_days WHERE date=?",(local_day,)).fetchone()
        if hit is not None:raise DomainError("SWITCH_CONFLICT","生效时刻所在日账已复核确认，不得改版")
        db.execute("INSERT INTO curve_revisions(effective_at,curve,run_id,created) VALUES(?,?,?,?)",(key,curve_text,run_id,created))
    item={"effective_at":key,"curve":json.loads(curve_text),"run_id":run_id,"created":created,"status":"已登记"}
    return item
def _confirmed_candidates(rows):
    # 持久化后数值已序列化为字符串，用 Decimal 判定完整24h覆盖。
    return [x for x in rows if x.get("state")=="通过" and Decimal(str(x.get("coverage_hours")))==24]
def confirm_days(run_id,rows):
    pairs=((x["station"],x["date"],run_id,json.dumps(x,ensure_ascii=False)) for x in _confirmed_candidates(rows))
    with connection() as db:db.executemany("INSERT OR REPLACE INTO confirmed_days(station,date,run_id,payload) VALUES(?,?,?,?)",pairs)
def unconfirm_days(rows):
    with connection() as db:
        for x in rows:db.execute("DELETE FROM confirmed_days WHERE station=? AND date=?",(x["station"],x["date"]))
def review(run_id,version,decision):
    if decision not in ("通过","退回"): raise DomainError("REVIEW","请选择通过或退回")
    if not isinstance(version,int): raise DomainError("STALE","版本必须为整数")
    with connection() as db:
        cur=db.execute("UPDATE runs SET review=?,version=version+1 WHERE id=? AND version=?",(decision,run_id,version))
        if cur.rowcount!=1: raise DomainError("STALE","复核版本已更新",409)
        row=db.execute("SELECT payload FROM runs WHERE id=?",(run_id,)).fetchone()
        rows=json.loads(row["payload"]).get("review_rows",[])
    # 事务连接已关闭，再写确认表，避免SQLite嵌套连接写锁。
    if decision=="通过":confirm_days(run_id,rows)
    else:unconfirm_days(rows)
    return fetch(run_id)
