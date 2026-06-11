"""驗證 /api/images 的路徑解析：穿越攻擊全擋、合法圖片可解析。

用法：uv run python scripts/test_kb_image_guard.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import _IMG_BASE, _resolve_kb_image

print("IMG_BASE:", _IMG_BASE, "exists:", _IMG_BASE.is_dir())

# 路徑穿越 payload — 全部應為 None
attacks = [
    "..\\..\\.env",
    "../../.env",
    "../../app/main.py",
    "../../../certs/x",
    "C:/Windows/win.ini",
    "....//....//.env",
]
for a in attacks:
    r = _resolve_kb_image(a)
    print(f"  attack {a!r:35} -> {r}")
    assert r is None, f"TRAVERSAL NOT BLOCKED: {a}"

# 兄弟目錄 prefix 繞過（舊 startswith 寫法的漏洞）：img_sibling 不該可達
sibling = _IMG_BASE.parent / (_IMG_BASE.name + "_sibling")
made_sibling = False
try:
    if not sibling.exists():
        sibling.mkdir()
        (sibling / "leak.txt").write_text("secret")
        made_sibling = True
    r = _resolve_kb_image("../" + sibling.name + "/leak.txt")
    print(f"  sibling-prefix bypass -> {r}")
    assert r is None, "SIBLING PREFIX BYPASS NOT BLOCKED"
finally:
    if made_sibling:
        (sibling / "leak.txt").unlink()
        sibling.rmdir()

# 合法圖片：挑一張實際存在的（直接路徑 + 括號父目錄 fallback 都靠 walk 覆蓋）
legit = None
for root, dirs, files in os.walk(_IMG_BASE):
    for f in files:
        if f.lower().endswith(".png"):
            legit = os.path.relpath(os.path.join(root, f), _IMG_BASE).replace("\\", "/")
            break
    if legit:
        break
print("legit path:", legit)
if legit:
    r = _resolve_kb_image(legit)
    print("  direct resolve ->", r)
    assert r is not None, "LEGIT IMAGE NOT RESOLVED"

print("ALL PASS")
