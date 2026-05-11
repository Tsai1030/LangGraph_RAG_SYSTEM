"""
Source filter prompt v1.

用途：與 responder 並行，評估 retrieved chunks 中哪些對回答問題有實質貢獻。
輸出：SourceFilterOutput.relevant_indices（chunk 索引 list）。
呼叫節點：app/graph/nodes/source_filter.py
無 template 變數（user message 由節點端拼接 query + chunks 文字）。

Target models: gpt-5.4 family
Last revised: 2026-05-11 (initial extraction from source_filter.py)
"""

PROMPT = """\
你是來源評估助理。根據問題與文件片段，列出真正能回答此問題的 chunk 索引。
只列出有實質貢獻的索引，不相關的不要列入。"""
