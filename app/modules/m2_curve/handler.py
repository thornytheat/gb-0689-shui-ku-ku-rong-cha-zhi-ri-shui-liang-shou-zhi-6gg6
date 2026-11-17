from flask import Blueprint,request,jsonify
from datetime import timedelta, timezone
from app.pipeline import run
from app import store
from app.errors import DomainError
from app.normalize import serial, instant
bp=Blueprint("m2",__name__)
@bp.route("/api/m2",methods=["GET","POST"])
def endpoint():
    payload=request.get_json(silent=True) if request.method=="POST" else {}
    if not isinstance(payload,dict): raise DomainError("BODY","请求必须是对象")
    raw=payload.get("text")
    if raw is not None and not isinstance(raw,str): raise DomainError("TEXT","数据必须为文本")
    return jsonify(run(raw,payload.get("params"),stop=2,persist=False))
@bp.route("/api/m2/revisions",methods=["GET","POST"])
def revisions():
    if request.method=="GET":return jsonify(store.list_revisions())
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):raise DomainError("BODY","请求必须是对象")
    switch=payload.get("curve_switch")
    if not isinstance(switch,dict):raise DomainError("BODY","curve_switch 必须是对象")
    # 预拦截：生效时刻所在+08日已复核确认则直接拒绝，不试算、不落库，旧版日账原样保留。
    local_day=instant(switch["effective_at"]).astimezone(timezone(timedelta(hours=8))).date().isoformat()
    if any(d["date"]==local_day for d in store.confirmed_dates()):
        raise DomainError("SWITCH_CONFLICT","生效时刻所在日账已复核确认，不得改版")
    params=payload.get("params") or {}
    params=dict(params);params["curve_switch"]=switch
    # 先跑完整管线完成校验；任何阶段抛错都不会写入登记，旧版日账原样保留。
    result=run(payload.get("text"),params)
    record=store.register_revision(switch["effective_at"],result["curve_switch"]["curve"],
                                   result["manifest"]["run_id"],result["manifest"]["created"])
    return jsonify({"revision":serial(record),"run_id":result["manifest"]["run_id"]})
