"""Root-only interactive account provisioner; never run by Web/API."""
from __future__ import annotations
import getpass,grp,json,os
from pathlib import Path
import secrets,stat,sys,uuid
from manager.auth.auth_store import AUTH_STORE_PATH,SERVICE_GROUP,AuthStoreError,make_password_record,valid_username

def _prepare_directory(path:Path,gid:int)->None:
    created=False
    try:os.mkdir(path,0o750);created=True
    except FileExistsError:pass
    if created:
        os.chown(path,0,gid,follow_symlinks=False)
        os.chmod(path,0o750,follow_symlinks=False)
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_gid!=gid or stat.S_IMODE(info.st_mode)!=0o750:
        raise AuthStoreError("authentication store directory is not safely provisioned")

def _fsync_directory(path:Path)->None:
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_CLOEXEC",0))
    try:os.fsync(fd)
    finally:os.close(fd)

def _safe_error(exc:BaseException)->tuple[str,str]:
    if isinstance(exc,OSError):
        value=exc.strerror if isinstance(exc.strerror,str) and exc.strerror else "OS operation failed"
        value=" ".join(value.replace("\r"," ").replace("\n"," ").split())[:120]
        return str(exc.errno) if exc.errno is not None else "NONE",value
    if isinstance(exc,AuthStoreError):return "NONE","authentication store validation failed"
    if isinstance(exc,(KeyError,ValueError)):return "NONE","input or configuration validation failed"
    if isinstance(exc,EOFError):return "NONE","interactive input ended"
    return "NONE","operation failed"

def main()->int:
    stage="root_check";path=AUTH_STORE_PATH;temp=None;temp_owned=False;fd=None
    target_linked=False;target_identity=None;password="";confirmation="";modified_directory=False
    try:
        if os.geteuid()!=0:raise AuthStoreError("root required")
        stage="target_precheck"
        if path.exists() or path.is_symlink():raise AuthStoreError("authentication store already exists")
        stage="username_prompt";username=input("Initial Manager username: ").strip()
        stage="username_validation"
        if not valid_username(username):raise AuthStoreError("username does not meet the allowed format")
        stage="password_prompt";password=getpass.getpass("Initial Manager password: ")
        confirmation=getpass.getpass("Confirm password: ")
        stage="password_validation"
        if not password or password!=confirmation or len(password)<12:
            raise AuthStoreError("password confirmation or minimum length check failed")
        # No filesystem mutation occurs for a password mismatch.
        stage="service_group_lookup";gid=grp.getgrnam(SERVICE_GROUP).gr_gid
        stage="directory_prepare";_prepare_directory(path.parent,gid)
        stage="password_hash"
        user={"username":username,"subject_id":uuid.uuid4().hex,
              **make_password_record(password),"roles":["dashboard.read"],"enabled":True}
        payload=(json.dumps({"version":1,"users":[user]},sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
        stage="temp_name";temp=path.parent/(".auth-store."+secrets.token_hex(12)+".tmp")
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0)
        stage="temp_open";fd=os.open(temp,flags,0o640);temp_owned=True
        stage="temp_chown";os.fchown(fd,0,gid)
        stage="temp_chmod";os.fchmod(fd,0o640)
        stage="temp_write"
        with os.fdopen(fd,"wb",closefd=False) as stream:stream.write(payload);stream.flush()
        temp_stat=os.fstat(fd);target_identity=(temp_stat.st_dev,temp_stat.st_ino)
        stage="file_fsync";os.fsync(fd)
        stage="temp_close";os.close(fd);fd=None
        stage="atomic_install";os.link(temp,path,follow_symlinks=False);target_linked=True;modified_directory=True
        stage="temp_cleanup";os.unlink(temp);temp_owned=False
        stage="directory_fsync";_fsync_directory(path.parent)
        target_linked=False;password="";confirmation=""
        print("Initial Manager account provisioned with the dashboard.read role.")
        return 0
    except BaseException as exc:
        original_stage=stage;cleanup_ok=True
        if fd is not None:
            try:os.close(fd)
            except OSError:cleanup_ok=False
            fd=None
        if target_linked and target_identity is not None:
            try:
                info=os.stat(path,follow_symlinks=False)
                if (info.st_dev,info.st_ino)==target_identity:
                    os.unlink(path);modified_directory=True;target_linked=False
                else:cleanup_ok=False
            except FileNotFoundError:pass
            except OSError:cleanup_ok=False
        if temp_owned and temp is not None:
            try:os.unlink(temp);temp_owned=False;modified_directory=True
            except FileNotFoundError:temp_owned=False
            except OSError:cleanup_ok=False
        if modified_directory:
            try:_fsync_directory(path.parent)
            except OSError:cleanup_ok=False
        password="";confirmation=""
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):
            print("Provisioning interrupted; no credentials were logged.",file=sys.stderr);return 1
        err_no,error=_safe_error(exc)
        print("Authentication store was not installed; provisioner stopped safely.",file=sys.stderr)
        print("PROVISION_DIAGNOSTIC="+type(exc).__name__,file=sys.stderr)
        print("ERRNO="+err_no,file=sys.stderr)
        print("ERROR="+error,file=sys.stderr)
        print("STAGE="+original_stage,file=sys.stderr)
        print("CLEANUP="+("PASS" if cleanup_ok and not temp_owned and not target_linked else "INCOMPLETE"),file=sys.stderr)
        return 1

if __name__=="__main__":raise SystemExit(main())
