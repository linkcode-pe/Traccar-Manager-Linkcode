#!/usr/bin/env python3
"""Validate static vehicle WebP assets without dependencies or GPS data access."""
from pathlib import Path
from struct import unpack
from urllib.request import urlopen
import argparse

BASE = Path(__file__).resolve().parent.parent / 'manager/assets/vehicle-icons-webp'

def validate(directory=BASE):
    names = sorted(directory.glob('*.webp'))
    errors = []
    if len(names) != 30:
        errors.append(f'Expected 30 icons, found {len(names)}')
    for path in names:
        data = path.read_bytes()
        if len(data) < 20 or data[:4] != b'RIFF' or data[8:12] != b'WEBP' or unpack('<I', data[4:8])[0] + 8 != len(data):
            errors.append(f'Invalid WebP container: {path.name}')
    return names, errors

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Optional Manager base URL to verify public asset delivery')
    args = parser.parse_args()
    names, errors = validate()
    if args.url:
        for icon in names:
            try:
                with urlopen(args.url.rstrip('/') + '/assets/vehicle-icons-webp/' + icon.name, timeout=8) as response:
                    if response.status != 200 or response.headers.get_content_type() != 'image/webp' or response.read() != icon.read_bytes():
                        errors.append(f'Asset differs from local file: {icon.name}')
            except Exception as exc:
                errors.append(f'Unavailable {icon.name}: {type(exc).__name__}')
    print(f'Checked {len(names)} WebP icons; errors: {len(errors)}')
    for error in errors:
        print('ERROR:', error)
    raise SystemExit(bool(errors))
