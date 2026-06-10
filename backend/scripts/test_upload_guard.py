"""驗證 upload_guard + save_upload：magic bytes 判型、分塊大小限制、假冒 mime 拒絕。

用法：uv run python scripts/test_upload_guard.py
"""
import asyncio
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.datastructures import Headers, UploadFile

from app.services.upload_guard import read_limited, sniff_audio_ok, sniff_image_mime

# 1x1 透明 PNG
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def make_upload(data: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        io.BytesIO(data),
        size=len(data),
        filename="t",
        headers=Headers({"content-type": content_type}),
    )


async def main():
    # ── sniff_image_mime ───────────────────────────────
    assert sniff_image_mime(PNG_1PX) == "image/png"
    assert sniff_image_mime(b"\xff\xd8\xff\xe0" + b"x" * 20) == "image/jpeg"
    assert sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_image_mime(b"<html>evil</html>") is None
    print("sniff_image_mime PASS")

    # ── sniff_audio_ok ─────────────────────────────────
    assert sniff_audio_ok(b"\x1aE\xdf\xa3" + b"\x00" * 20, "audio/webm")
    assert sniff_audio_ok(b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav")
    assert sniff_audio_ok(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 8, "audio/mp4")
    assert not sniff_audio_ok(b"<html>not audio</html>", "audio/webm")
    print("sniff_audio_ok PASS")

    # ── read_limited：超限早斷 ─────────────────────────
    big = make_upload(b"x" * (3 * 1024 * 1024), "image/png")
    try:
        await read_limited(big, 2 * 1024 * 1024)
        raise AssertionError("oversize not rejected")
    except ValueError as e:
        print(f"read_limited oversize PASS ({e})")

    empty = make_upload(b"", "image/png")
    try:
        await read_limited(empty, 100)
        raise AssertionError("empty not rejected")
    except ValueError:
        print("read_limited empty PASS")

    ok = await read_limited(make_upload(PNG_1PX, "image/png"), 1024)
    assert ok == PNG_1PX
    print("read_limited normal PASS")

    # ── save_upload 整合 ───────────────────────────────
    from app.config import settings
    with tempfile.TemporaryDirectory() as tmp:
        orig = settings.upload_dir
        settings.upload_dir = tmp
        try:
            from app.services.image_store import save_upload

            # 合法 PNG
            r = await save_upload("u1", make_upload(PNG_1PX, "image/png"))
            assert r["mime_type"] == "image/png"
            print("save_upload valid PNG PASS")

            # PNG bytes 假冒 jpeg：以 sniff 為準（存成 png）
            r = await save_upload("u1", make_upload(PNG_1PX, "image/jpeg"))
            assert r["mime_type"] == "image/png"
            print("save_upload mislabeled PASS (sniffed as png)")

            # 文字假冒 png：拒絕
            try:
                await save_upload("u1", make_upload(b"<script>alert(1)</script>", "image/png"))
                raise AssertionError("fake png not rejected")
            except ValueError as e:
                print(f"save_upload fake content PASS ({e})")

            # 不在 allowlist 的 mime：快篩拒絕
            try:
                await save_upload("u1", make_upload(PNG_1PX, "image/svg+xml"))
                raise AssertionError("svg not rejected")
            except ValueError:
                print("save_upload disallowed mime PASS")
        finally:
            settings.upload_dir = orig

    print("ALL PASS")


asyncio.run(main())
