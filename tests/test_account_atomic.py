import os
from concurrent.futures import ThreadPoolExecutor
import pytest
from manager import account_profile as account


def test_atomic_concurrent_writes_do_not_mix_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(account, 'BASE', tmp_path)
    target = tmp_path / 'profile.json'
    payloads = [bytes([n]) * 5000 for n in range(1, 17)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda data: account._atomic(target, data), payloads))
    assert target.read_bytes() in payloads
    assert not list(tmp_path.glob('*.tmp'))
    assert os.stat(target).st_mode & 0o777 == 0o600


def test_atomic_failed_replace_cleans_unique_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(account, 'BASE', tmp_path)
    target = tmp_path / 'avatar.bin'
    target.write_bytes(b'original')
    def reject(*args):
        raise OSError('simulated replace failure')
    monkeypatch.setattr(account.os, 'replace', reject)
    with pytest.raises(OSError, match='simulated'):
        account._atomic(target, b'new')
    assert target.read_bytes() == b'original'
    assert not list(tmp_path.glob('*.tmp'))


def test_atomic_fsyncs_directory_after_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(account, 'BASE', tmp_path)
    target = tmp_path / 'profile.json'
    real_fsync = account.os.fsync
    synced = []
    def tracked_fsync(fd):
        synced.append(os.fstat(fd).st_mode)
        return real_fsync(fd)
    monkeypatch.setattr(account.os, 'fsync', tracked_fsync)
    account._atomic(target, b'hello')
    assert len(synced) == 2
    assert target.read_bytes() == b'hello'
