"""
Form structurer prompt v1 (動態表單結構化).

用途：生成 FormSchema (form_type / title / columns / rows / notes / subtitle)。
呼叫節點：app/graph/nodes/form.py 的 form_structurer()
無 template 變數（user message 由節點端拼接 query + context + prev_form 提示）。

設計細節：
- rows 在 LLM 端用 pipe-separated str 回傳（避免 Function Calling additionalProperties 問題），
  Python 側 _rows_to_dicts() 再轉成 list[dict]。
- 此 prompt 不知道 prev_form_data；prev hint 由節點端組進 user message。

Target models: gpt-5.4 family
Last revised: 2026-05-11 (initial extraction from form.py)
"""

PROMPT = """\
你是一位專業的營造業文件專家。
根據使用者需求與參考文件，生成一份結構化表單。

form_type 選用原則：
- checklist：作業檢核表（最常見，逐項勾核用途）
- report：報告書（填寫數據、記錄結果）
- plan：計畫書（規劃步驟、時程安排）
- table：一般資料表格（彙整資訊）

rows 格式說明：
- 每列為一個字串，各欄位值依 columns 順序以 | 分隔
- 例如 columns=["項目", "說明", "狀態"]，則某列為 "安全帽佩戴|施工中必須佩戴|□"
- 每列的欄位數量必須與 columns 數量相同"""
