import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 載入 .env 檔案中的環境變數
load_dotenv()

# 使用 Google AI Studio 的 Gemini 模型
MODEL = "gemini-3.5-flash"

# 指定的報告輸出格式範本
OUTPUT_FORMAT = """以下是豐興鋼鐵在 {日期}（週X）開出的內銷盤價（請用一句話簡述本週調整，例如：廢鋼、鋼筋同步上調 200 元，止步連續四週平盤）：

1. 牌價（產品售價/收購價）
這是豐興對外公告的實際牌價：
*   鋼筋產品價格（牌價）：[價格] 元 / 公噸（即每公噸 [X.XX] 萬元）
*   國內廢鋼收購價格：[價格] 元 / 公噸（即每公噸 [X.XX] 萬元）
*   型鋼產品基價：[價格] 元 / 公噸（即每公噸 [X.X] 萬元）

2. 基價（市場交易基準價）
有些下游鋼廠與合約商會以「基價」來對應波動：
*   鋼筋基價：[價格] 元 / 公噸（即每公噸 [X.XX] 萬元）
*   國內廢鋼基價：[價格] 元 / 公噸（即每公噸 [X] 萬元）
*   型鋼基價：[價格] 元 / 公噸（即每公噸 [X.X] 萬元）

---

🌐 國際原物料行情參考（[日期] 當週）：
*   美國大船廢鋼、日本 2H 廢鋼：[報價，若無則寫「當週無報價」]
*   美國貨櫃廢鋼：[價格] 美元 / 公噸（[漲跌情形]）
*   澳洲鐵礦砂：[價格] 美元 / 公噸（[漲跌情形]）"""


def generate_report(date_str):
    """Agentic 模式：讓 Gemini 自行使用 Google 搜尋查詢並產生報告"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ 未找到 GEMINI_API_KEY 環境變數。請在 .env 檔案中設定。")
        return

    prompt = f"""你是一個專業的鋼鐵產業分析助手。
請使用 Google 搜尋，查詢「豐興鋼鐵」在 {date_str} 公告的最新內銷盤價，
包含鋼筋、國內廢鋼、型鋼的「牌價」與「基價」，以及該週的國際原物料行情
（美國大船/貨櫃廢鋼、日本 2H 廢鋼、澳洲鐵礦砂）。

請務必遵守：
1. 提供直接的絕對數值（例如 19,100），不要只寫漲跌幅。
2. 標明每個品項的漲跌情形（上調 / 下調 / 持平）與調整金額。
3. 若某項資料查不到，請填寫「資料未提供」或「當週無報價」，絕對不要編造數字。
4. 嚴格依照以下格式輸出，不要加上任何額外的開場白或結論：

{OUTPUT_FORMAT}"""

    client = genai.Client(api_key=api_key)
    google_search_tool = types.Tool(google_search=types.GoogleSearch())

    print(f"🧠 正在以 agentic 模式（{MODEL} + Google 搜尋）查詢 {date_str} 的資料...\n")
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
            ),
        )
    except Exception as e:
        print(f"❌ 呼叫 Gemini API 時發生錯誤: {e}")
        return

    print("-" * 40)
    print(response.text)
    print("-" * 40)

    # 顯示 Gemini 實際進行的搜尋與參考來源（grounding 證據）
    try:
        metadata = response.candidates[0].grounding_metadata
    except Exception:
        metadata = None

    if metadata:
        queries = getattr(metadata, "web_search_queries", None)
        if queries:
            print("\n🔎 實際搜尋關鍵字：")
            for q in queries:
                print(f"  • {q}")

        chunks = getattr(metadata, "grounding_chunks", None)
        if chunks:
            print("\n📚 參考來源：")
            for i, chunk in enumerate(chunks, 1):
                if chunk.web:
                    print(f"  [{i}] {chunk.web.title}\n      {chunk.web.uri}")


if __name__ == "__main__":
    date_to_search = input("📅 請輸入要查詢的日期 (例如: 2026年5月25日): ")
    generate_report(date_to_search)
