"""
Compact / summarizer prompt v1.

用途：對話超過 token 閾值時，把舊訊息壓成一段前情提要，塞回後續 system prompt。
呼叫節點：app/graph/nodes/compact.py 的 summarizer()
Template 變數：{history}（由節點端 .format(history=...) 帶入）

Target models: gpt-5.4 family
Last revised: 2026-05-11 (initial extraction from compact.py)
"""

PROMPT = """\
你是對話記錄整理員。請將以下對話記錄濃縮成一段清晰的前情提要（繁體中文，300 字以內），
保留所有重要的問答內容與關鍵資訊，供後續回答時參考使用。

對話記錄：
{history}

請輸出前情提要："""
