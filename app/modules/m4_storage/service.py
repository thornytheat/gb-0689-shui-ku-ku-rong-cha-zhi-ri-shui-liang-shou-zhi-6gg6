from .rules import storage
from app.modules.curves import curve_at
def execute(ctx):
    switch=ctx.get('curve_switch')
    curve_for=(lambda moment:curve_at(moment,ctx['curve'],switch)) if switch else None
    rows=storage(ctx['records'],ctx['curve'],curve_for);ctx['storage']=rows
    ctx['stages'].append({'title':'库容换算','rows':rows,'metrics':{'换算测次':len(rows),'最小库容 m³':str(min((x['volume'] for x in rows),default=0)),'最大库容 m³':str(max((x['volume'] for x in rows),default=0)),'新曲线测次':sum(x['curve_basis']=='新曲线' for x in rows)}});return ctx

from .rules import interpolate
def level_to_volume(level,curve):return interpolate(level,curve)
