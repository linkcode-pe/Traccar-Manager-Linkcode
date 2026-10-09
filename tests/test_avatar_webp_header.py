from manager.account_profile import _valid_webp_header


def _webp(fourcc=b"VP8 ", payload=b"1234"):
    chunk = fourcc + len(payload).to_bytes(4, "little") + payload + (b"\0" if len(payload) % 2 else b"")
    body = b"WEBP" + chunk
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def test_webp_header_accepts_known_chunk_types():
    for fourcc in (b"VP8 ", b"VP8L", b"VP8X"):
        assert _valid_webp_header(_webp(fourcc))


def test_webp_header_rejects_truncated_and_extra_data():
    good = _webp()
    assert not _valid_webp_header(good[:-1])
    assert not _valid_webp_header(good + b"x")
    assert not _valid_webp_header(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8 " + b"1234")
    assert not _valid_webp_header(_webp(b"JUNK"))
    assert not _valid_webp_header(b"RIFFxxxxWEBP")


def test_webp_header_rejects_invalid_chunk_lengths():
    good = _webp(payload=b"1234")
    assert not _valid_webp_header(good[:16] + (999).to_bytes(4, "little") + good[20:])
    assert not _valid_webp_header(good[:16] + (1).to_bytes(4, "little") + good[20:])
    assert not _valid_webp_header(_webp(payload=b"123")[:-1])
    assert _valid_webp_header(_webp(payload=b"123"))


def test_read_avatar_requires_complete_png_signature(tmp_path, monkeypatch):
    import manager.account_profile as account
    avatar = tmp_path / "avatar.bin"
    monkeypatch.setattr(account, "AVATAR", avatar)
    avatar.write_bytes(b"\x89PNG" + b"X" * 20)
    assert account.read_avatar() is None
    avatar.write_bytes(b"\x89PNG\r\n\x1a\n" + b"X" * 20)
    assert account.read_avatar() == (avatar.read_bytes(), "image/png")


def test_read_avatar_preserves_jpeg_signature(tmp_path, monkeypatch):
    import manager.account_profile as account
    avatar = tmp_path / "avatar.bin"
    monkeypatch.setattr(account, "AVATAR", avatar)
    avatar.write_bytes(b"\xff\xd8\xff" + b"X" * 20)
    assert account.read_avatar() == (avatar.read_bytes(), "image/jpeg")


def test_read_avatar_rejects_too_small_files(tmp_path, monkeypatch):
    import manager.account_profile as account
    avatar = tmp_path / "avatar.bin"
    monkeypatch.setattr(account, "AVATAR", avatar)
    for data in (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n" + b"X" * 7):
        avatar.write_bytes(data)
        assert account.read_avatar() is None


def test_webp_header_requires_zero_odd_chunk_padding():
    good = _webp(payload=b"123")
    assert _valid_webp_header(good)
    assert not _valid_webp_header(good[:-1] + b"X")
