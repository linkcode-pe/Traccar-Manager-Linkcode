"""Read-only bounded health trend reader."""
from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta

PATH=Path('/var/lib/traccar-manager-health/health-history.jsonl')
MAX_BYTES=2*1024*1024
BASE_FIELDS={'observed_at_utc','disk_total_bytes','disk_used_bytes','disk_used_percent','memory_total_bytes','memory_used_bytes','logs_bytes','database_total_bytes'}
COMPONENT_FIELDS={'mysql_files_bytes','journal_bytes','binlogs_bytes','manager_history_bytes'}

def disk_projection(rows):
    if len(rows)<12: return {'status':'COLLECTING','sample_count':len(rows),'minimum_samples':12}
    points=[]
    for row in rows[-288:]:
        ts=datetime.strptime(row['observed_at_utc'],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()/86400
        points.append((ts,float(row['disk_used_percent'])))
    span=points[-1][0]-points[0][0]
    if span<0.04: return {'status':'COLLECTING','sample_count':len(points),'minimum_span_hours':1}
    mx=sum(x for x,_ in points)/len(points); my=sum(y for _,y in points)/len(points)
    denom=sum((x-mx)**2 for x,_ in points)
    slope=sum((x-mx)*(y-my) for x,y in points)/denom if denom else 0.0
    current=points[-1][1]
    if slope<=0.05: return {'status':'STABLE','sample_count':len(points),'current_percent':current,'growth_percent_per_day':round(slope,3)}
    result={'status':'GROWING','sample_count':len(points),'current_percent':current,'growth_percent_per_day':round(slope,3)}
    for threshold in (80,90):
        days=max(0.0,(threshold-current)/slope) if current<threshold else 0.0
        result[f'days_to_{threshold}']=round(days,1)
    d80=result['days_to_80']; d90=result['days_to_90']
    if current>=90 or d90<=3:
        priority='CRITICAL'
    elif current>=80 or d90<=7 or d80<=3:
        priority='HIGH'
    elif d80<=14:
        priority='MEDIUM'
    else:
        priority='LOW'
    result['capacity_risk']={
        'priority':priority,
        'warning_threshold_percent':80,
        'critical_threshold_percent':90,
        'horizon_days':{'warning':d80,'critical':d90},
        'basis':'linear_regression',
        'automatic_destructive_action':False,
    }
    return result

def _linear_rate(points):
    """Return units/day from timestamped values using least-squares regression."""
    if len(points)<2: return 0.0
    origin=points[0][0]
    normalized=[((ts-origin).total_seconds()/86400.0,float(value)) for ts,value in points]
    mx=sum(x for x,_ in normalized)/len(normalized)
    my=sum(y for _,y in normalized)/len(normalized)
    denom=sum((x-mx)**2 for x,_ in normalized)
    return sum((x-mx)*(y-my) for x,y in normalized)/denom if denom else 0.0

def component_growth(rows):
    usable=[r for r in rows if COMPONENT_FIELDS.issubset(r)][-288:]
    if len(usable)<12: return {'status':'COLLECTING','sample_count':len(usable),'minimum_samples':12}
    parsed=[(datetime.strptime(r['observed_at_utc'],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc),r) for r in usable]
    hours=(parsed[-1][0]-parsed[0][0]).total_seconds()/3600
    if hours<1: return {'status':'COLLECTING','sample_count':len(usable),'minimum_span_hours':1}
    def values(key):
        return [(ts,int(r[key])) for ts,r in parsed]
    component_points={
        'mysql':[(ts,int(r['mysql_files_bytes'])-int(r['binlogs_bytes'])) for ts,r in parsed],
        'traccar_logs':values('logs_bytes'),'journal':values('journal_bytes'),
        'binlogs':values('binlogs_bytes'),'manager_history':values('manager_history_bytes'),
    }
    disk_points=values('disk_used_bytes')
    rates={k:_linear_rate(v) for k,v in component_points.items()}
    disk_rate=_linear_rate(disk_points)
    rates['other']=disk_rate-sum(rates.values())
    observed_deltas={k:int(v[-1][1]-v[0][1]) for k,v in component_points.items()}
    observed_disk=int(disk_points[-1][1]-disk_points[0][1])
    observed_deltas['other']=observed_disk-sum(observed_deltas.values())
    positive={k:v for k,v in rates.items() if v>0}
    dominant=max(positive,key=positive.get) if positive else None
    total=max(1,int(usable[-1]['disk_total_bytes']))
    rate_pct_day=disk_rate*100/total
    severity='NONE'
    if disk_rate>0 and rate_pct_day>=1.0: severity='CRITICAL'
    elif disk_rate>0 and rate_pct_day>=0.25: severity='WARNING'
    status='GROWING' if disk_rate>0 else 'STABLE'
    recommendations={
        'mysql':'Revisar crecimiento de datos e índices MySQL; no optimizar ni eliminar datos sin un plan verificado.',
        'traccar_logs':'Revisar rotación y retención de logs Traccar; conservar la política segura de 90 días.',
        'journal':'Revisar el límite y la retención de systemd-journald antes de considerar cualquier limpieza.',
        'binlogs':'Vigilar la retención de binlogs MySQL y confirmar que la política de 7 días continúa protegida.',
        'manager_history':'Verificar la retención acotada del histórico del Manager; no requiere acción destructiva inmediata.',
        'other':'Identificar el consumo no atribuido antes de realizar cualquier limpieza.',
    }
    result={'status':status,'severity':severity,'method':'linear_regression','sample_count':len(usable),
            'window_hours':round(hours,2),'disk_delta_bytes':observed_disk,
            'growth_bytes_per_day':round(disk_rate),'growth_percent_per_day':round(rate_pct_day,3),
            'dominant_component':dominant,'component_deltas':observed_deltas,
            'component_rates_per_day':{k:round(v) for k,v in rates.items()}}
    if dominant:
        result['recommendation']=recommendations[dominant]
        rate=max(0.0,rates[dominant])
        result['diagnostic']={
            'component':dominant,
            'rate_bytes_per_day':round(rate),
            'share_of_positive_growth_percent':round(rate*100/max(1.0,sum(v for v in rates.values() if v>0)),1),
            'risk':severity if severity!='NONE' else 'OBSERVE',
            'action_mode':'READ_ONLY_RECOMMENDATION',
            'automatic_destructive_action':False,
        }
    return result

def read_health_history(hours: int=24):
    hours=168 if hours==168 else 24
    try:
        st=PATH.stat()
        if st.st_size>MAX_BYTES: raise ValueError('history too large')
        cutoff=datetime.now(timezone.utc)-timedelta(hours=hours); rows=[]
        with PATH.open('r',encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                row=json.loads(line)
                if not BASE_FIELDS.issubset(row) or not set(row).issubset(BASE_FIELDS|COMPONENT_FIELDS): continue
                ts=datetime.strptime(row['observed_at_utc'],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                if ts>=cutoff: rows.append(row)
        # Bound response while retaining shape: ~5m for 24h, ~30m for 7d.
        step=1 if hours==24 else 6
        sampled=rows[::step]
        if rows and (not sampled or sampled[-1] is not rows[-1]): sampled.append(rows[-1])
        return {'window_hours':hours,'samples':sampled[-340:],'sample_count':len(sampled[-340:]),'projection':disk_projection(rows),'component_growth':component_growth(rows),'persistent':True,'read_only':True}
    except FileNotFoundError:
        return {'window_hours':hours,'samples':[],'sample_count':0,'persistent':True,'read_only':True}
