from __future__ import annotations
import base64, json, os, re, secrets, tempfile
from pathlib import Path
from manager.auth.auth_store import derive_password_hash, PBKDF2_ITERATIONS
BASE=Path("/var/lib/traccar-manager-account")
PROFILE=BASE/"profile.json"; CRED=BASE/"password.json"; AVATAR=BASE/"avatar.bin"; ALERT_STATE=BASE/"alert-state.json"
_EMAIL=re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}$")
def _atomic(path,data):
    BASE.mkdir(mode=0o700,parents=True,exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=BASE, prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        # Persist the directory entry as well as the file contents.
        dir_fd = os.open(BASE, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
def read_profile():
    try:
        d=json.loads(PROFILE.read_text("utf-8"))
        if not isinstance(d,dict): raise ValueError()
        return {"name":str(d.get("name",""))[:80],"email":str(d.get("email",""))[:254],"has_avatar":AVATAR.is_file()}
    except Exception:return {"name":"","email":"","has_avatar":AVATAR.is_file()}
def save_profile(name,email):
    name=name.strip(); email=email.strip().lower()
    if not 1<=len(name)<=80 or (email and (len(email)>254 or not _EMAIL.fullmatch(email))): raise ValueError("invalid profile")
    _atomic(PROFILE,json.dumps({"name":name,"email":email},separators=(",",":")).encode())
    return read_profile()
def _valid_webp_header(data):
    # RIFF length excludes its eight-byte header; reject truncated/extra payloads.
    if (len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP"
            or int.from_bytes(data[4:8], "little") + 8 != len(data)
            or data[12:16] not in (b"VP8 ", b"VP8L", b"VP8X")):
        return False
    # Each RIFF chunk contains a four-byte type, four-byte size and even-byte padding.
    offset = 12
    while offset < len(data):
        if len(data) - offset < 8:
            return False
        chunk_size = int.from_bytes(data[offset + 4:offset + 8], "little")
        payload_end = offset + 8 + chunk_size
        if payload_end + (chunk_size & 1) > len(data):
            return False
        if chunk_size & 1 and data[payload_end] != 0:
            return False
        offset = payload_end + (chunk_size & 1)
    return offset == len(data)

def save_avatar(data):
    if not isinstance(data,bytes) or not 16<=len(data)<=2097152: raise ValueError("invalid avatar")
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or _valid_webp_header(data)): raise ValueError("invalid avatar")
    _atomic(AVATAR,data)
def read_avatar():
    try:
        d=AVATAR.read_bytes()
        if not 16 <= len(d) <= 2097152:return None
        if d.startswith(b"\x89PNG\r\n\x1a\n"):return d,"image/png"
        if d.startswith(b"\xff\xd8\xff"):return d,"image/jpeg"
        if _valid_webp_header(d):return d,"image/webp"
    except Exception:pass
    return None
def save_password(password):
    if not isinstance(password,str) or not 10<=len(password)<=1024: raise ValueError("invalid password")
    salt=secrets.token_bytes(16); digest=derive_password_hash(password,salt,PBKDF2_ITERATIONS)
    _atomic(CRED,json.dumps({"salt_b64":base64.b64encode(salt).decode(),"password_hash_b64":base64.b64encode(digest).decode(),"iterations":PBKDF2_ITERATIONS},separators=(",",":")).encode())
def read_password_record():
    try:
        d=json.loads(CRED.read_text("utf-8"))
        salt=base64.b64decode(d["salt_b64"],validate=True); digest=base64.b64decode(d["password_hash_b64"],validate=True); it=d["iterations"]
        if len(salt)!=16 or len(digest)!=32 or not isinstance(it,int):return None
        return salt,digest,it
    except Exception:return None

def alert_unread(key):
    import hashlib
    if not isinstance(key,str) or len(key)>8192: raise ValueError("invalid alert key")
    digest=hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
    try:
        d=json.loads(ALERT_STATE.read_text("utf-8")); seen=d.get("seen_digest","") if isinstance(d,dict) else ""
    except Exception: seen=""
    return bool(key) and digest!=seen
def mark_alert_seen(key):
    import hashlib
    if not isinstance(key,str) or len(key)>8192: raise ValueError("invalid alert key")
    digest=hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
    _atomic(ALERT_STATE,json.dumps({"seen_digest":digest},separators=(",",":")).encode())
