from app.normalize import instant
def parse_switch(switch):
    """解析 curve_switch 参数：{'effective_at': ISO8601, 'curve': [[水位,库容],...]}。"""
    if not switch:return None
    if not isinstance(switch,dict):raise_switch("改版参数必须是对象")
    if "effective_at" not in switch or "curve" not in switch:raise_switch("改版需含生效时刻与新曲线")
    return {"effective_at":instant(switch["effective_at"]),"curve":switch["curve"]}
def raise_switch(message):
    from app.errors import DomainError
    raise DomainError("CURVE_SWITCH",message)
def curve_at(moment,curve,switch):
    """按时刻选择曲线：生效时刻起用新曲线，此前沿用旧曲线。"""
    if switch is None or moment<switch["effective_at"]:return curve
    return switch["curve"]
