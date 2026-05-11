"""
Responder fill-done confirmation prompt v1.

用途：static_form_fill + status=completed 時，產生「已將您的資料填入《...》，請點選下方下載」短句。
呼叫節點：app/graph/nodes/generation.py 的 responder() completed 分支
無 template 變數。

Target models: gpt-5.4 family (grader_model)
Last revised: 2026-05-11 (initial extraction from generation.py)
"""

PROMPT = """\
表單已填寫完成。請用一句繁體中文（30字內）告知使用者並提示點擊下方下載。
範例：「已將您的資料填入《動員開工作業檢核表》，請點選下方下載。」
直接從「已將」或「已為您填好」開始；禁止確認語。"""
