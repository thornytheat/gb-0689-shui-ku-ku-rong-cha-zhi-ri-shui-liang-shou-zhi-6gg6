from .rules import validate_curve,normalize,select
from app.modules.curves import parse_switch
from app.normalize import number
from app.errors import DomainError
from app.reasons import rejected
def execute(ctx):
    curve=validate_curve(ctx['params']['curve']);gap=number(ctx['params']['max_gap_hours']);tol=number(ctx['params']['tolerance_m3'])
    if gap<=0 or gap>24 or tol<0:raise DomainError('RANGE','缺口或容差参数无效')
    switch=parse_switch(ctx['params'].get('curve_switch'))
    if switch is not None:
        switch['curve']=validate_curve(switch['curve'])
        if switch['effective_at'].tzinfo is None:raise DomainError('CURVE_SWITCH','生效时刻必须包含偏移')
        ctx['curve_switch']=switch
        # 改版后水位可能落在新曲线范围内：越界判定取两条曲线的联合包络，M4/M5 再按时刻精确选线。
        lo=min(curve[0][0],switch['curve'][0][0]);hi=max(curve[-1][0],switch['curve'][-1][0])
        envelope=[(lo,curve[0][1]),(hi,curve[-1][1])]
    else:
        envelope=curve
    good=[]
    for row in ctx['records']:
        try:good.append(normalize(row,envelope))
        except DomainError as exc:ctx['quarantine'].append(rejected(row,exc.code,exc.message))
    watermarks={}
    for row in good:
        old=watermarks.get(row['station'])
        row['arrival']='迟到' if old is not None and row['time']<old else '顺序'
        watermarks[row['station']]=max(old,row['time']) if old else row['time']
    good,bad=select(good);ctx['quarantine'].extend(bad);ctx['records']=good;ctx['curve']=curve
    metrics={'曲线点':len(curve),'有效测次':len(good),'最大缺口 h':str(gap)}
    if switch is not None:metrics.update({'改版生效':switch['effective_at'].isoformat(),'新曲线点':len(switch['curve'])})
    ctx['stages'].append({'title':'曲线校核','rows':[{'level':h,'volume':v} for h,v in curve],'metrics':metrics});return ctx
