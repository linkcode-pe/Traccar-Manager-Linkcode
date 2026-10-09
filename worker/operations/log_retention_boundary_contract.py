"""Pure contract for the future privileged retention boundary. No deletion/import side effects."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import re
_HIST=re.compile(r'^tracker-server\.log\.\d{8}$')
@dataclass(frozen=True)
class BoundaryContract:
 component:str='traccar-manager-retention-boundary'
 mode:str='DENY_PRODUCTION'
 separate_identity_required:bool=True
 production_access:bool=False
 active_log_denied:bool=True
 allowed_operation:str='DELETE_EXPIRED_HISTORICAL_LOGS'
 allowed_name_pattern:str='tracker-server.log.YYYYMMDD'
 network_access:bool=False
 shell_access:bool=False
 def public_status(self): return asdict(self)
def validate_request(operation:str,names:list[str]|tuple[str,...])->bool:
 if operation!='DELETE_EXPIRED_HISTORICAL_LOGS': return False
 if not names or len(names)!=len(set(names)): return False
 return all(n!='tracker-server.log' and bool(_HIST.fullmatch(n)) for n in names)
