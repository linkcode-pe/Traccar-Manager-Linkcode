from datetime import datetime,timezone
from manager.incident_decisions import intervention_stall
NOW=datetime(2026,10,7,12,0,tzinfo=timezone.utc)

def test_authorized_stalls_after_two_hours():
    x=intervention_stall({'result_code':'AUTHORIZED','last_event_at':'2026-10-07T09:30:00Z'},NOW)
    assert x['stalled'] and x['threshold_hours']==2 and x['reason']=='Autorizada sin ejecución'

def test_prepared_uses_longer_six_hour_threshold():
    assert not intervention_stall({'result_code':'PREPARED','last_event_at':'2026-10-07T07:00:00Z'},NOW)['stalled']
    assert intervention_stall({'result_code':'PREPARED','last_event_at':'2026-10-07T05:00:00Z'},NOW)['stalled']

def test_completed_or_invalid_timestamp_never_stalls():
    assert not intervention_stall({'result_code':'EXECUTED','last_event_at':'2026-10-01T00:00:00Z'},NOW)['stalled']
    assert not intervention_stall({'result_code':'AUTHORIZED','last_event_at':'bad'},NOW)['stalled']
