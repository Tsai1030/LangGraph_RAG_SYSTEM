"""
Responder static-form-download confirmation prompt v1.

用途：intent=static_form_download 時，產生「《表單名稱》，請點擊下方下載」這類短確認句。
呼叫節點：app/graph/nodes/generation.py 的 responder() static_form_download 分支
無 template 變數。

Target models: gpt-5.4 family (grader_model)
Last revised: 2026-05-11 (initial extraction from generation.py)
"""

PROMPT = """\
使用者明確索取了一份作業表單。請用一句繁體中文（20字以內）提示使用者點擊下方下載。
格式範例：《表單名稱》，請點擊下方下載。
禁止在句首加上「已找到」、「為您找到」等確認語，直接從《表單名稱》開始。"""
