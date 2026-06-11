"""驗證 cleanup_old_generated：過期檔刪除、.gitkeep 與新檔保留。

用法：uv run python scripts/test_cleanup.py
"""
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.form_fill_writer import GENERATED_DIR, cleanup_old_generated

GENERATED_DIR.mkdir(parents=True, exist_ok=True)

tag = uuid.uuid4().hex[:8]
old_file = GENERATED_DIR / f"_test_old_{tag}.docx"
new_file = GENERATED_DIR / f"_test_new_{tag}.docx"
gitkeep = GENERATED_DIR / ".gitkeep"
had_gitkeep = gitkeep.exists()

try:
    old_file.write_text("old")
    new_file.write_text("new")
    if not had_gitkeep:
        gitkeep.write_text("")

    # 把 old_file 的 mtime 倒回 31 天前
    past = time.time() - 31 * 86400
    os.utime(old_file, (past, past))

    removed = cleanup_old_generated(max_age_days=30)
    print(f"removed={removed}")
    assert not old_file.exists(), "過期檔未被刪除"
    assert new_file.exists(), "新檔被誤刪"
    assert gitkeep.exists(), ".gitkeep 被誤刪"
    print("ALL PASS")
finally:
    for p in (old_file, new_file):
        if p.exists():
            p.unlink()
    if not had_gitkeep and gitkeep.exists():
        gitkeep.unlink()
