from .rules import day_budget
from app.modules.m4_storage.service import level_to_volume
def execute(ctx):
    switch=ctx.get('curve_switch')
    rows=day_budget(ctx['flows'],ctx['curve'],level_to_volume,switch);ctx['budgets']=rows
    metrics={'日账':len(rows),'缺测日':sum(x['state']=='缺测' for x in rows),
             '收支差 m³':str(sum((x['residual'] for x in rows),0)),
             '曲线调整 m³':str(sum((x['curve_adjust'] for x in rows),0))}
    if switch is not None:metrics['改版生效']=switch['effective_at'].isoformat()
    ctx['stages'].append({'title':'日水量收支','rows':rows,'metrics':metrics});return ctx
