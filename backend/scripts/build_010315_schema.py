"""build_010315_schema.py — 一次性產生 010315 工地文件管制與保存表的 schema。

010315 表單結構複雜（cell-marker、跨頁延續表、合併儲存格中的多個 label），
通用解析器 build_form_schemas.py 抓不全。此腳本以 docx 真實結構為依據手寫，
產出帶 `manual: true` 旗標的 schema，build_form_schemas.py 會跳過不覆蓋。

執行：
    cd backend && python scripts/build_010315_schema.py

來源依據：scripts/output/inspect_010315*.txt（python-docx dump）

章節對應（以 user 確認的分組為準）：
    附件 1 - 封面            ：表 0 r1c2/c3 = 版次/修訂日期
    附件 1 - 版本資訊         ：表 1 r1-r5 c6 = 版本/發行日期(上欄)/發行日期(下欄)/機密等級/頁數
    附件 1 - 修訂歷程         ：表 2 r1-r17 (5 欄) = 修訂日期/章節/版次/認可/備註
    附件 2 - 封面            ：表 3 r1c2/c3 = 版次/修訂日期
    附件 2 - 計畫書內容       ：段落 7 marker = ---計畫書內容
    附件 3 - 文件編號紀錄表   ：表 4 r1-r21 + 表 5 r1-r21（邏輯第 1-42 列）× (文件名稱/編號/備註)
    文件異動會簽單 - 抬頭     ：段落 23 markers = 單位/主辦/年月日
    文件異動會簽單 - 主旨說明  ：表 6 r0/r1 = 主旨/說明
    文件異動會簽單 - 會簽 N   ：表 6 r3-r9 各列 (會簽單位/職稱/姓名/簽名/會辦意見) — 7 組
    文件異動會簽單 - 審核意見  ：表 6 r10/r11 = 審查意見/審查簽名/核准意見/核准簽名

cell_marker 模式（表 1 / 表 6 r10 r11）：
    cell 內已有 label 文字（如「版本：」），值寫在 marker 後。
    需要 form_fill_writer 支援 kind="cell_marker"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT_PATH = Path(__file__).parent.parent / "app" / "rag" / "form_schemas" / "010315.json"


# ──────────────────────────────────────────────────────────────────
# helper：建構各種 field 樣板
# ──────────────────────────────────────────────────────────────────

def cell_field(key: str, sub_label: str, type_: str, section: str,
               table_idx: int, row: int, col: int) -> dict[str, Any]:
    return {
        "key": key,
        "label": f"{section}・{sub_label}",
        "sub_label": sub_label,
        "section": section,
        "type": type_,
        "required": False,
        "loc": {"kind": "cell", "table_idx": table_idx, "row": row, "col": col},
    }


def cell_marker_field(key: str, sub_label: str, type_: str, section: str,
                      table_idx: int, row: int, col: int,
                      marker: str, marker_end: str | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": f"{section}・{sub_label}",
        "sub_label": sub_label,
        "section": section,
        "type": type_,
        "required": False,
        "loc": {
            "kind": "cell_marker",
            "table_idx": table_idx, "row": row, "col": col,
            "marker": marker,
            "marker_end": marker_end,
        },
    }


def para_field(key: str, sub_label: str, type_: str, section: str,
               para_idx: int, marker: str, marker_end: str | None,
               required: bool = False) -> dict[str, Any]:
    return {
        "key": key,
        "label": f"{section}・{sub_label}",
        "sub_label": sub_label,
        "section": section,
        "type": type_,
        "required": required,
        "loc": {
            "kind": "para",
            "para_idx": para_idx,
            "marker": marker,
            "marker_end": marker_end,
        },
    }


# ──────────────────────────────────────────────────────────────────
# 各章節欄位
# ──────────────────────────────────────────────────────────────────

def fields_attachment_1_cover() -> list[dict[str, Any]]:
    """附件 1 - 封面（表 0 r1）"""
    sec = "附件 1 - 封面"
    return [
        cell_field("att1_cover_version",  "版次",     "text", sec, 0, 1, 2),
        cell_field("att1_cover_revdate",  "修訂日期",  "date", sec, 0, 1, 3),
    ]


def fields_attachment_1_version_info() -> list[dict[str, Any]]:
    """附件 1 - 版本資訊（表 1 c6 各列；cell-marker 模式）

    從 dump（↹ 代表 \\t）：
        r0c6: '文件編號：CM-01'   ← 預填，不放
        r1c6: '版↹本：'           ← marker 含 \\t
        r2c6: '發行日期：'
        r3c6: '發行日期：'        ← 重複，命名為「發行日期(下欄)」
        r4c6: '機密等級：'
        r5c6: '頁↹數：'           ← marker 含 \\t
    """
    sec = "附件 1 - 版本資訊"
    return [
        cell_marker_field("att1_ver_version",     "版本",         "text", sec, 1, 1, 6, "版\t本："),
        cell_marker_field("att1_ver_issuedate1",  "發行日期(上欄)", "date", sec, 1, 2, 6, "發行日期："),
        cell_marker_field("att1_ver_issuedate2",  "發行日期(下欄)", "date", sec, 1, 3, 6, "發行日期："),
        cell_marker_field("att1_ver_classify",    "機密等級",      "text", sec, 1, 4, 6, "機密等級："),
        cell_marker_field("att1_ver_pages",       "頁數",         "text", sec, 1, 5, 6, "頁\t數："),
    ]


def fields_attachment_1_revision_history() -> list[dict[str, Any]]:
    """附件 1 - 修訂歷程（表 2 r1-r17，5 欄）"""
    sec = "附件 1 - 修訂歷程"
    cols = [
        ("revdate", "修訂日期", "date"),
        ("chapter", "修訂章節", "text"),
        ("version", "修訂版次", "text"),
        ("approve", "認可",    "text"),
        ("remark",  "備註",    "text"),
    ]
    out: list[dict[str, Any]] = []
    for row in range(1, 18):  # r1..r17
        for c_idx, (cname, clabel, ctype) in enumerate(cols):
            out.append(cell_field(
                f"att1_hist_r{row}_{cname}",
                f"第 {row} 列・{clabel}",
                ctype, sec, 2, row, c_idx,
            ))
    return out


def fields_attachment_2_cover() -> list[dict[str, Any]]:
    """附件 2 - 封面（表 3 r1）"""
    sec = "附件 2 - 封面"
    return [
        cell_field("att2_cover_version", "版次",    "text", sec, 3, 1, 2),
        cell_field("att2_cover_revdate", "修訂日期", "date", sec, 3, 1, 3),
    ]


def fields_attachment_2_content() -> list[dict[str, Any]]:
    """附件 2 - 計畫書內容（段落 7）"""
    sec = "附件 2 - 計畫書內容"
    return [
        para_field("att2_content", "計畫書內容", "text", sec,
                   para_idx=7, marker="---計畫書內容", marker_end="......"),
    ]


def fields_attachment_3_record_table() -> list[dict[str, Any]]:
    """附件 3 - 文件編號紀錄表（表 4 r1-r21 + 表 5 r1-r21，邏輯 1-42 列）

    跨頁邏輯：使用者描述「第 N 列」時 N=1..42，前 21 列寫表 4，後 21 列寫表 5。
    sub_label 統一使用「第 N 列」連續編號，loc 各自指向對應實體 cell。
    """
    sec = "附件 3 - 文件編號紀錄表"
    cols = [
        ("name",   "文件名稱", "text", 0),
        ("code",   "文件編號", "text", 1),
        ("remark", "備註",     "text", 2),
    ]
    out: list[dict[str, Any]] = []
    # 第 1-21 列 → 表 4 r1-r21
    for logical in range(1, 22):
        physical_row = logical
        for cname, clabel, ctype, c_idx in cols:
            out.append(cell_field(
                f"att3_r{logical}_{cname}",
                f"第 {logical} 列・{clabel}",
                ctype, sec, 4, physical_row, c_idx,
            ))
    # 第 22-42 列 → 表 5 r1-r21
    for logical in range(22, 43):
        physical_row = logical - 21
        for cname, clabel, ctype, c_idx in cols:
            out.append(cell_field(
                f"att3_r{logical}_{cname}",
                f"第 {logical} 列・{clabel}",
                ctype, sec, 5, physical_row, c_idx,
            ))
    return out


def fields_signoff_header() -> list[dict[str, Any]]:
    """文件異動會簽單 - 抬頭（段落 23）

    段落實際文字（含 tab）：'單\\t位：\\t主 辦：\\t年\\t月\\t日'
    - 「單 位：」：marker 必須含 \\t（單\\t位：），marker_end="\\t" 吃到下一個 tab
    - 「主 辦：」：實實在在用空格分隔，marker_end="\\t"
    - 「年月日」：marker="年" + marker_end="日" → 整段「年\\t月\\t日」取代為 value
    """
    sec = "文件異動會簽單 - 抬頭"
    return [
        para_field("signoff_unit",   "單位", "text", sec,
                   para_idx=23, marker="單\t位：", marker_end="\t"),
        para_field("signoff_owner",  "主辦", "text", sec,
                   para_idx=23, marker="主 辦：", marker_end="\t"),
        para_field("signoff_date",   "年月日", "date", sec,
                   para_idx=23, marker="年", marker_end="日"),
    ]


def fields_signoff_subject() -> list[dict[str, Any]]:
    """文件異動會簽單 - 主旨說明（表 6 r0 / r1，整 cell 寫入）"""
    sec = "文件異動會簽單 - 主旨說明"
    return [
        cell_field("signoff_subject",     "主旨", "text", sec, 6, 0, 1),
        cell_field("signoff_description", "說明", "text", sec, 6, 1, 1),
    ]


def fields_signoff_signers() -> list[dict[str, Any]]:
    """文件異動會簽單 - 會簽 N（表 6 r3-r9，每列 5 欄）

    每列為一位會簽人；7 列共 7 位。每位以「會簽 N」當 section 分組，
    使用者填寫時可逐位推進；不熟悉者也能跳過某幾列空著。
    """
    cols = [
        ("unit",   "會簽單位", "text", 0),
        ("title",  "職稱",    "text", 1),
        ("name",   "姓名",    "text", 2),
        ("sign",   "簽名",    "text", 3),
        ("opinion","會辦意見", "text", 4),
    ]
    out: list[dict[str, Any]] = []
    for slot, row in enumerate(range(3, 10), start=1):  # r3..r9 → slot 1..7
        sec = f"文件異動會簽單 - 會簽 {slot}"
        for cname, clabel, ctype, c_idx in cols:
            out.append(cell_field(
                f"signoff_s{slot}_{cname}",
                clabel, ctype, sec, 6, row, c_idx,
            ))
    return out


def fields_signoff_review() -> list[dict[str, Any]]:
    """文件異動會簽單 - 審核意見（表 6 r10 / r11，cell_marker 模式）

    從 dump：
        r10c0-c2 合併 = '審查意見'   → 審查意見內容（寫在 cell 內）
        r10c3-c4 合併 = '核准意見'   → 核准意見內容
        r11c0-c2 合併 = '簽 名：'    → 審查者簽名（marker="簽\t名："）
        r11c3-c4 合併 = '簽 名：'    → 核准者簽名

    user 確認 r10/r11 共 4 個邏輯欄位（審查意見、審查簽名、核准意見、核准簽名）。
    審查/核准意見 cell 文字本身就是「審查意見」「核准意見」這個 label，
    我們用 cell_marker 模式以該 label 為 marker，讓 writer 把值寫在 label 後。
    """
    sec = "文件異動會簽單 - 審核意見"
    return [
        cell_marker_field("signoff_review_opinion",  "審查意見",  "text", sec,
                          6, 10, 0, marker="審查意見"),
        cell_marker_field("signoff_review_sign",     "審查簽名",  "text", sec,
                          6, 11, 0, marker="簽\t名："),
        cell_marker_field("signoff_approve_opinion", "核准意見",  "text", sec,
                          6, 10, 3, marker="核准意見"),
        cell_marker_field("signoff_approve_sign",    "核准簽名",  "text", sec,
                          6, 11, 3, marker="簽\t名："),
    ]


# ──────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────

def build() -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    fields.extend(fields_attachment_1_cover())
    fields.extend(fields_attachment_1_version_info())
    fields.extend(fields_attachment_1_revision_history())
    fields.extend(fields_attachment_2_cover())
    fields.extend(fields_attachment_2_content())
    fields.extend(fields_attachment_3_record_table())
    fields.extend(fields_signoff_header())
    fields.extend(fields_signoff_subject())
    fields.extend(fields_signoff_signers())
    fields.extend(fields_signoff_review())

    return {
        "form_id": "010315",
        "title": "工地文件管制與保存表",
        "file_name": "010315工地文件管制與保存表.docx",
        "manual": True,
        "fields": fields,
    }


def main() -> None:
    schema = build()
    OUT_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 統計每個 section 的欄位數
    sections: dict[str, int] = {}
    for f in schema["fields"]:
        sections[f["section"]] = sections.get(f["section"], 0) + 1

    print(f"OK → {OUT_PATH.name}  共 {len(schema['fields'])} 欄")
    print("各章節欄位數：")
    for sec, n in sections.items():
        print(f"  {n:>4}  {sec}")


if __name__ == "__main__":
    main()
