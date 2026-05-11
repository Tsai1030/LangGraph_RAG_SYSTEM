"""
Responder dynamic-form-export done confirmation prompt v1.

用途：intent=dynamic_form_export 完成後，產生「已將《標題》匯出為 Excel，請點選下方下載」短句。
呼叫節點：app/graph/nodes/generation.py 的 responder() dynamic_form_export 分支
無 template 變數。

Target models: gpt-5.4 family (grader_model)
Last revised: 2026-05-11 (initial extraction from generation.py)
"""

PROMPT = """\
動態表單已匯出為下載檔。請用一句繁體中文（30字內）告知使用者並提示點擊下方下載。
範例：「已將《標題》匯出為 Excel，請點選下方下載。」
直接從「已將」或「已為您匯出」開始；禁止確認語。"""
