from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from collections import defaultdict
from app.errors import DomainError
# Public pure interpolation is deliberately passed in by the service.
def day_budget(flows,curve,interpolate,switch=None):
    zone=timezone(timedelta(hours=8))
    buckets=defaultdict(lambda:{'in_m3':D(0),'out_m3':D(0),'storage_change':D(0),'coverage_hours':D(0),
                                'curve_adjust':D(0),'segments':[]})
    def fail(message):raise DomainError('CURVE_SWITCH',message)
    adjusted=set()
    for part in flows:
        left,right=part['left'],part['right'];start,end=part['start'],part['end']
        duration=D(str((end-start).total_seconds()));cursor=start
        def at(t,key):return left[key]+(right[key]-left[key])*D(str((t-start).total_seconds()))/duration
        while cursor<end:
            local=cursor.astimezone(zone);midnight=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),zone)
            stop=min(end,midnight)
            if switch is not None and cursor<switch['effective_at']<stop:stop=switch['effective_at']
            b=buckets[(part['station'],local.date().isoformat())]
            seconds=D(str((stop-cursor).total_seconds()))
            b['in_m3']+=(at(cursor,'inflow')+at(stop,'inflow'))/2*seconds
            b['out_m3']+=(at(cursor,'outflow')+at(stop,'outflow'))/2*seconds
            level_cursor,level_stop=at(cursor,'level'),at(stop,'level')
            t=switch['effective_at'] if switch is not None else None
            if switch is None or stop<=t:
                v_change=interpolate(level_stop,curve)-interpolate(level_cursor,curve)
            elif cursor>=t:
                if cursor==t and part['station'] not in adjusted:
                    # 生效时刻恰与观测/日界重合：在该点一次性登记改版调整。
                    old_v=interpolate(level_cursor,curve);new_v=interpolate(level_cursor,switch['curve'])
                    b['curve_adjust']+=new_v-old_v
                    b['segments'].append({'effective_at':t.isoformat(),'level':str(level_cursor),
                                          'old_volume':str(old_v),'new_volume':str(new_v),'adjust':str(new_v-old_v)})
                    adjusted.add(part['station'])
                v_change=interpolate(level_stop,switch['curve'])-interpolate(level_cursor,switch['curve'])
            else:
                # 切换点落在本子段内：物理库变用两侧各自曲线，改版调整在T点只认一次。
                level_t=at(t,'level')
                v_change=(interpolate(level_t,curve)-interpolate(level_cursor,curve))+(interpolate(level_stop,switch['curve'])-interpolate(level_t,switch['curve']))
                if part['station'] in adjusted:fail('同一改版被重复计算')
                old_v=interpolate(level_t,curve);new_v=interpolate(level_t,switch['curve'])
                b['curve_adjust']+=new_v-old_v
                b['segments'].append({'effective_at':t.isoformat(),'level':str(level_t),
                                      'old_volume':str(old_v),'new_volume':str(new_v),'adjust':str(new_v-old_v)})
                adjusted.add(part['station'])
            b['storage_change']+=v_change
            b['coverage_hours']+=seconds/3600
            cursor=stop
    if switch is not None:
        missing=sorted({p['station'] for p in flows}-adjusted)
        if missing:
            # 生效时刻落在缺口或观测范围外：切换失败，由调用方整体保留旧版日账。
            fail('生效时刻缺少覆盖测次，切换失败：'+','.join(missing))
    result=[]
    for (station,day),values in sorted(buckets.items()):
        end_moment=datetime.combine(datetime.fromisoformat(day),datetime.min.time(),zone)+timedelta(days=1)
        # 切换后的日账按新曲线列示现行库容依据，曲线调整量单列、不参与收支差。
        result.append({'station':station,'date':day,**values,
                       'residual':values['storage_change']-values['in_m3']+values['out_m3'],
                       'state':'完整' if values['coverage_hours']==24 else '缺测',
                       'curve_basis':'新曲线' if switch is not None and end_moment>switch['effective_at'] else '旧曲线'})
    return result
