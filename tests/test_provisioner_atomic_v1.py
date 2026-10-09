"""Isolated provisioner tests using synthetic credentials and /etc temporary dirs."""
from __future__ import annotations
import contextlib,errno,grp,io,json,os,secrets,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from manager.auth import provision_admin
from manager.auth.auth_store import AuthStore
@unittest.skipUnless(os.geteuid()==0,"requires root for ownership/group tests")
class ProvisionerAtomicTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix=".tm-provision-test-",dir="/etc");self.root=Path(self.tmp.name)
  self.gid=grp.getgrnam("traccar-manager-web").gr_gid;self.username="fixture-"+secrets.token_hex(5);self.password=secrets.token_urlsafe(24)
 def tearDown(self):self.tmp.cleanup()
 def invoke(self,path,*,passwords=None,fsync=None,link=None,fdopen=None,dirsync=None):
  out=io.StringIO();err=io.StringIO();pp=iter(passwords if passwords is not None else [self.password,self.password])
  patches=[patch.object(provision_admin,"AUTH_STORE_PATH",path),patch("builtins.input",return_value=self.username),patch.object(provision_admin.getpass,"getpass",side_effect=lambda *_:next(pp)),patch("sys.stdout",out),patch("sys.stderr",err)]
  if fsync:patches.append(patch("os.fsync",side_effect=fsync))
  if link:patches.append(patch("os.link",side_effect=link))
  if fdopen:patches.append(patch("os.fdopen",side_effect=fdopen))
  if dirsync:patches.append(patch.object(provision_admin,"_fsync_directory",side_effect=dirsync))
  with contextlib.ExitStack() as stack:
   for p in patches:stack.enter_context(p)
   code=provision_admin.main()
  return code,out.getvalue(),err.getvalue()
 def assert_clean_secret_output(self,out,err):
  self.assertNotIn(self.password,out+err);self.assertNotIn(self.username,out+err)
 def test_success_hash_role_permissions_owner_group_and_temp_cleanup(self):
  path=self.root/"success"/"auth-store.json";code,out,err=self.invoke(path);self.assertEqual(0,code)
  raw=path.read_bytes();doc=json.loads(raw);self.assertNotIn(self.password.encode(),raw);self.assert_clean_secret_output(out,err)
  self.assertEqual(["dashboard.read"],doc["users"][0]["roles"]);self.assertIsNotNone(AuthStore(path).authenticate(self.username,self.password))
  f=path.stat();d=path.parent.stat();self.assertEqual((0,self.gid,0o640),(f.st_uid,f.st_gid,stat.S_IMODE(f.st_mode)))
  self.assertEqual((0,self.gid,0o750),(d.st_uid,d.st_gid,stat.S_IMODE(d.st_mode)));self.assertEqual([],list(path.parent.glob(".auth-store.*.tmp")))
 def test_password_mismatch_reaches_validation_creates_no_store_or_temp(self):
  path=self.root/"mismatch"/"auth-store.json";code,out,err=self.invoke(path,passwords=[self.password,"different-synthetic-confirmation"])
  self.assertEqual(1,code);self.assertIn("STAGE=password_validation",err);self.assertIn("PROVISION_DIAGNOSTIC=AuthStoreError",err)
  self.assertFalse(path.exists());self.assertFalse(path.parent.exists());self.assert_clean_secret_output(out,err)
 def test_empty_password_rejected_before_filesystem_mutation(self):
  path=self.root/"empty"/"auth-store.json";code,out,err=self.invoke(path,passwords=["",""])
  self.assertEqual(1,code);self.assertIn("STAGE=password_validation",err);self.assertFalse(path.parent.exists());self.assert_clean_secret_output(out,err)
 def test_existing_store_never_overwritten(self):
  path=self.root/"existing"/"auth-store.json";self.assertEqual(0,self.invoke(path)[0]);before=path.read_bytes()
  out=io.StringIO();err=io.StringIO()
  with patch.object(provision_admin,"AUTH_STORE_PATH",path),patch("builtins.input",side_effect=AssertionError("prompt")),patch("sys.stdout",out),patch("sys.stderr",err):code=provision_admin.main()
  self.assertEqual(1,code);self.assertEqual(before,path.read_bytes());self.assertIn("STAGE=target_precheck",err.getvalue());self.assert_clean_secret_output(out.getvalue(),err.getvalue())
 def test_file_fsync_failure_cleans_temp_and_reports_stage(self):
  path=self.root/"fsync-file"/"auth-store.json";real=os.fsync;calls=[]
  def fail_once(fd):
   if not calls:calls.append(1);raise OSError(errno.EIO,"Input/output error")
   return real(fd)
  code,out,err=self.invoke(path,fsync=fail_once);self.assertEqual(1,code);self.assertFalse(path.exists());self.assertEqual([],list(path.parent.glob(".auth-store.*.tmp")))
  self.assertIn("ERRNO=5",err);self.assertIn("STAGE=file_fsync",err);self.assertIn("CLEANUP=PASS",err);self.assert_clean_secret_output(out,err)
 def test_write_failure_cleans_temp(self):
  path=self.root/"write"/"auth-store.json"
  class FailingWriter:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def write(self,_data):raise OSError(errno.ENOSPC,"No space left on device")
   def flush(self):return None
  code,out,err=self.invoke(path,fdopen=lambda *_a,**_k:FailingWriter());self.assertEqual(1,code);self.assertFalse(path.exists());self.assertEqual([],list(path.parent.glob(".auth-store.*.tmp")))
  self.assertIn("STAGE=temp_write",err);self.assertIn("CLEANUP=PASS",err);self.assert_clean_secret_output(out,err)
 def test_atomic_install_failure_cleans_temp(self):
  path=self.root/"link"/"auth-store.json"
  def fail(*_a,**_k):raise OSError(errno.EOPNOTSUPP,"Operation not supported")
  code,out,err=self.invoke(path,link=fail);self.assertEqual(1,code);self.assertFalse(path.exists());self.assertEqual([],list(path.parent.glob(".auth-store.*.tmp")))
  self.assertIn("ERRNO=95",err);self.assertIn("STAGE=atomic_install",err);self.assertIn("CLEANUP=PASS",err);self.assert_clean_secret_output(out,err)
 def test_directory_fsync_failure_rolls_back_owned_target(self):
  path=self.root/"fsync-dir"/"auth-store.json";real=provision_admin._fsync_directory;calls=[]
  def fail_once(directory):
   if not calls:calls.append(1);raise OSError(errno.EIO,"Input/output error")
   return real(directory)
  code,out,err=self.invoke(path,dirsync=fail_once);self.assertEqual(1,code);self.assertFalse(path.exists());self.assertEqual([],list(path.parent.glob(".auth-store.*.tmp")))
  self.assertIn("STAGE=directory_fsync",err);self.assertIn("CLEANUP=PASS",err);self.assert_clean_secret_output(out,err)
if __name__=="__main__":unittest.main()
