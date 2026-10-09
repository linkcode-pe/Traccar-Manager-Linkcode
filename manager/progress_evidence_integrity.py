"""Bounded, no-follow report verification for the authorized progress snapshot."""
import hashlib
import os
import re
import stat
from pathlib import Path


def check_report(repo: Path, relative: str, expected_digest: str) -> str:
    if not isinstance(relative, str) or not re.fullmatch(r'docs/test-runs/[A-Za-z0-9._-]{1,180}\.md', relative):
        return 'invalid'
    if not isinstance(expected_digest, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_digest):
        return 'invalid'
    directory = repo / 'docs' / 'test-runs'
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unavailable'
    try:
        try:
            fd = os.open(relative.rsplit('/', 1)[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except FileNotFoundError:
            return 'missing'
        except OSError:
            return 'invalid'
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > 200000:
                return 'invalid'
            data = bytearray()
            while len(data) <= 200000:
                chunk = os.read(fd, min(65536, 200001 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) != info.st_size:
                return 'invalid'
            return 'ok' if hashlib.sha256(data).hexdigest() == expected_digest else 'mismatch'
        except OSError:
            return 'unavailable'
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
