from datetime import datetime, timedelta, timezone
from manager.health_history import component_growth

BASE=datetime(2026,10,7,tzinfo=timezone.utc)
TOTAL=100*1024**3

def row(i, disk, binlogs, logs=3*1024**3):
    return {
        'observed_at_utc':(BASE+timedelta(minutes=5*i)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'disk_total_bytes':TOTAL,'disk_used_bytes':disk,'disk_used_percent':disk*100/TOTAL,
        'memory_total_bytes':4*1024**3,'memory_used_bytes':2*1024**3,
        'logs_bytes':logs,'database_total_bytes':6*1024**3,
        'mysql_files_bytes':26*1024**3+binlogs,'journal_bytes':1024**3,
        'binlogs_bytes':binlogs,'manager_history_bytes':10000+i*200,
    }

def test_component_growth_uses_regression_and_identifies_binlogs():
    rows=[row(i,50*1024**3+i*4*1024**2,2*1024**3+i*3*1024**2) for i in range(25)]
    result=component_growth(rows)
    assert result['method']=='linear_regression'
    assert result['status']=='GROWING'
    assert result['dominant_component']=='binlogs'
    assert result['component_rates_per_day']['binlogs']>0
    assert '7 días' in result['recommendation']

def test_component_growth_not_driven_only_by_endpoints():
    # First and last are slightly higher, while the full series trends down.
    rows=[]
    for i in range(25):
        disk=50*1024**3-i*2*1024**2
        if i==24: disk=50*1024**3+1024**2
        rows.append(row(i,disk,2*1024**3))
    result=component_growth(rows)
    assert result['method']=='linear_regression'
    assert result['status']=='STABLE'
    assert result['growth_bytes_per_day']<0
