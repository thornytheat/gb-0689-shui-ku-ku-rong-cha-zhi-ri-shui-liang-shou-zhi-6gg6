import pytest
from decimal import Decimal as D
from app.normalize import instant
from app.errors import DomainError
from app.pipeline import run
from app import store
from app.modules.m3_integrate.rules import integrate
from app.modules.m5_budget.rules import day_budget
from app.modules.m4_storage.service import level_to_volume
from app.modules.m4_storage.rules import storage
from app.modules.curves import curve_at, parse_switch

OLD=[(D(100),D(0)),(D(102),D(30000))]
NEW=[(D(100),D(0)),(D(102),D(36000))]
def p(t,level,qin=1,qout=0):
    return dict(station='S',time=instant(t),inflow=D(qin),outflow=D(qout),level=D(level))
def switch(t):return {'effective_at':instant(t),'curve':NEW}

def test_adjustment_separate_from_storage_change():
    # 恒水位改版：物理库变为0，曲线调整量=同水位新旧库容差，且不计入收支差。
    parts=integrate([p('2026-11-16T23:00:00+08:00',101),p('2026-11-17T01:00:00+08:00',101)],D(2))[0]
    rows=day_budget(parts,OLD,level_to_volume,switch('2026-11-17T00:00:00+08:00'))
    day17=[r for r in rows if r['date']=='2026-11-17'][0]
    assert day17['storage_change']==0
    assert day17['curve_adjust']==3000          # 15000 -> 18000
    assert day17['residual']==-day17['in_m3']+day17['out_m3']
    assert len(day17['segments'])==1
    assert day17['curve_basis']=='新曲线'

def test_physical_change_uses_both_curves():
    # 水位在切换前后都有变化：库变=旧曲线段+新曲线段，调整只算一次。
    parts=integrate([p('2026-11-16T23:00:00+08:00',100),p('2026-11-17T01:00:00+08:00',102)],D(2))[0]
    rows=day_budget(parts,OLD,level_to_volume,switch('2026-11-17T00:00:00+08:00'))
    by={r['date']:r for r in rows}
    # 16日 100->101 旧曲线，17日 101->102 新曲线；T点调整 15000->18000。
    assert by['2026-11-16']['storage_change']==15000
    assert by['2026-11-17']['storage_change']==18000
    assert by['2026-11-17']['curve_adjust']==3000
    assert sum(r['curve_adjust'] for r in rows)==3000

def test_no_switch_keeps_legacy_shape():
    parts=integrate([p('2026-11-16T23:00:00+08:00',101),p('2026-11-17T01:00:00+08:00',101)],D(2))[0]
    rows=day_budget(parts,OLD,level_to_volume)
    assert all(r['curve_adjust']==0 and r['segments']==[] and r['curve_basis']=='旧曲线' for r in rows)

def test_switch_inside_interval_keeps_integral_conservation():
    parts=integrate([p('2026-11-16T23:00:00+08:00',100),p('2026-11-17T01:00:00+08:00',102)],D(2))[0]
    rows=day_budget(parts,OLD,level_to_volume,switch('2026-11-17T00:30:00+08:00'))
    assert abs(sum(r['in_m3'] for r in rows)-sum(x['in_m3'] for x in parts))<D('0.000000001')

def test_switch_in_gap_fails_and_old_ledger_remains(isolate):
    # 生效时刻落在缺测区间（dirty.csv 19:00→23:00 有4h缺口）：报错且不产生批次，旧版日账保留。
    before=store.history()
    params={'curve_switch':{'effective_at':'2026-11-16T21:00:00+08:00','curve':[['100','0'],['102','36000']]}}
    with pytest.raises(DomainError) as ei:
        run(None,params)
    assert ei.value.code=='CURVE_SWITCH'
    assert store.history()==before

def test_switch_outside_coverage_fails():
    parts=integrate([p('2026-11-16T00:00:00+08:00',101),p('2026-11-16T01:00:00+08:00',101)],D(2))[0]
    with pytest.raises(DomainError) as ei:
        day_budget(parts,OLD,level_to_volume,switch('2026-12-01T00:00:00+08:00'))
    assert ei.value.code=='CURVE_SWITCH'

def test_switch_requires_every_station_covered():
    # S站覆盖生效时刻；T站观测在生效时刻前已结束，无法登记调整，整次切换失败。
    t0=dict(p('2026-11-16T20:00:00+08:00',101),station='T')
    t1=dict(p('2026-11-16T22:00:00+08:00',101),station='T')
    rows=[p('2026-11-16T23:00:00+08:00',101),p('2026-11-17T01:00:00+08:00',101),t0,t1]
    parts=integrate(rows,D(2))[0]
    with pytest.raises(DomainError) as ei:
        day_budget(parts,OLD,level_to_volume,switch('2026-11-17T00:00:00+08:00'))
    assert ei.value.code=='CURVE_SWITCH' and 'T' in ei.value.message

def test_revision_conflict_prechecked_before_persist(client):
    raw=_full_day_csv()
    created=client.post('/api/runs',json={'text':raw.decode()}).json
    client.post('/api/review/'+created['manifest']['run_id'],json={'version':1,'decision':'通过'})
    n_before=len(client.get('/api/history').json)
    body={'curve_switch':{'effective_at':'2026-11-16T12:00:00+08:00','curve':[['100','0'],['102','36000']]}}
    reply=client.post('/api/m2/revisions',json=body)
    assert reply.status_code==422 and reply.json['code']=='SWITCH_CONFLICT'
    assert len(client.get('/api/history').json)==n_before   # 拦截发生在试算落库之前

def test_rerun_same_switch_adjusts_once(raw,isolate):
    params={'curve_switch':{'effective_at':'2026-11-17T00:00:00+08:00','curve':[['100','0'],['102','30000'],['105','100000'],['108','220000']]}}
    a=run(raw,params);b=run(raw,params)
    assert a['manifest']['run_id']==b['manifest']['run_id']
    assert sum(D(r['curve_adjust']) for r in a['budgets'])==sum(D(r['curve_adjust']) for r in b['budgets'])
    assert sum(1 for r in a['budgets'] for s in r['segments'])==1

def test_m4_storage_picks_curve_by_time():
    sw=parse_switch({'effective_at':'2026-11-17T00:00:00+08:00','curve':NEW})
    rows=storage([p('2026-11-16T00:00:00+08:00',101),p('2026-11-17T00:00:00+08:00',101)],OLD,
                 lambda moment:curve_at(moment,OLD,sw))
    assert [r['curve_basis'] for r in rows]==['旧曲线','新曲线']
    assert [r['volume'] for r in rows]==[15000,18000]

def test_new_curve_extends_level_window(raw,isolate):
    # 新曲线把上限抬到109：dirty.csv 中水位99仍隔离（低于两曲线下限），但范围内测次不因扩界被误隔离。
    params={'curve_switch':{'effective_at':'2026-11-17T00:00:00+08:00',
                            'curve':[['100','0'],['102','30000'],['105','100000'],['109','260000']]}}
    r=run(raw,params,stop=2,persist=False)
    assert any(q['code']=='RANGE' for q in r['quarantine'])      # 水位99越界仍隔离
    assert len(r['records'])==40                                  # 其余测次全部采信
    r5=run(raw,params,stop=5,persist=False)
    assert all('curve_adjust' in b for b in r5['budgets'])

def _full_day_csv():
    # 49个整点覆盖两个完整24h日（含11-18T00终点）；恒水位零流量，残差为0可判通过。
    lines=['id,station,time,level,inflow,outflow,flow_unit,version']
    i=1
    for day in range(2):
        for h in range(24):
            d=f'2026-11-{16+day}'
            lines.append(f"{i:05d},S,{d}T{h:02d}:00:00+08:00,101.000,0,0,m3/s,1");i+=1
    lines.append(f"{i:05d},S,2026-11-18T00:00:00+08:00,101.000,0,0,m3/s,1")
    return '\n'.join(lines).encode()

def test_confirmed_day_keeps_old_curve_on_rerun(isolate):
    raw=_full_day_csv()
    first=run(raw)                                   # 无改版基线
    store.review(first['manifest']['run_id'],1,'通过')
    # 模拟“从已确认日续跑”：解除17日确认，16日保持原曲线快照。
    store.unconfirm_days([{'station':'S','date':'2026-11-17'}])
    params={'curve_switch':{'effective_at':'2026-11-17T12:00:00+08:00',
                            'curve':[['100','0'],['102','36000']]}}
    rerun=run(raw,params)
    keys={(r['station'],r['date']):r for r in rerun['budgets']}
    # 已确认的16日整行沿用确认时快照（旧曲线、无调整），17日按改版重算。
    snap=keys[('S','2026-11-16')]
    assert snap['curve_basis']=='旧曲线' and D(snap['curve_adjust'])==0
    assert D(keys[('S','2026-11-17')]['curve_adjust'])!=0
    assert rerun['resume_from']=='2026-11-16'
    assert {d['date'] for d in rerun['confirmed_days']}=={'2026-11-16'}

def test_revision_registry_idempotent_and_conflict(client):
    body={'curve_switch':{'effective_at':'2026-11-17T00:00:00+08:00',
                          'curve':[['100','0'],['102','30000'],['105','100000'],['108','220000']]}}
    r1=client.post('/api/m2/revisions',json=body)
    r2=client.post('/api/m2/revisions',json=body)
    assert r1.status_code==200 and r2.status_code==200
    assert r1.json['revision']['effective_at']==r2.json['revision']['effective_at']
    assert r2.json['revision']['status']=='已存在'
    listed=client.get('/api/m2/revisions').json
    assert len(listed)==1

def test_revision_blocked_on_confirmed_day(client):
    raw=_full_day_csv()
    created=client.post('/api/runs',json={'text':raw.decode()}).json
    client.post('/api/review/'+created['manifest']['run_id'],json={'version':1,'decision':'通过'})
    body={'curve_switch':{'effective_at':'2026-11-16T12:00:00+08:00','curve':[['100','0'],['102','36000']]}}
    reply=client.post('/api/m2/revisions',json=body)
    assert reply.status_code==422 and reply.json['code']=='SWITCH_CONFLICT'

def test_reject_review_unconfirms_days(isolate):
    raw=_full_day_csv()
    created=run(raw)
    store.review(created['manifest']['run_id'],1,'通过')
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM confirmed_days').fetchone()[0]==2
    store.review(created['manifest']['run_id'],2,'退回')
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM confirmed_days').fetchone()[0]==0

def test_pages_render_with_switch(client):
    body={'curve_switch':{'effective_at':'2026-11-17T00:00:00+08:00',
                          'curve':[['100','0'],['102','30000'],['105','100000'],['108','220000']]}}
    created=client.post('/api/runs',json=body).json
    for stage in (2,4,5,6):
        assert client.get(f'/m/{stage}?run={created["manifest"]["run_id"]}').status_code==200
