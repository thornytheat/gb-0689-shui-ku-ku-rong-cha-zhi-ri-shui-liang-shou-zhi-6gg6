from app.errors import DomainError
def interpolate(level,curve):
    if not curve[0][0]<=level<=curve[-1][0]:raise DomainError('RANGE','水位超出曲线范围')
    for (ha,va),(hb,vb) in zip(curve,curve[1:]):
        if ha<=level<=hb:return va+(vb-va)*(level-ha)/(hb-ha)
    raise DomainError('CURVE','曲线没有覆盖水位')
def storage(rows,curve,curve_for=None):
    out=[]
    for row in rows:
        used=curve_for(row['time']) if curve_for else curve
        item={**row,'volume':interpolate(row['level'],used),'curve_basis':'新曲线' if curve_for is not None and used is not curve else '旧曲线'}
        out.append(item)
    return out
