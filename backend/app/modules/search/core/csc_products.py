"""中鋼盤價產品清單 — single source of truth.

Edit this if 中鋼 adds / drops a product line; everything else (admin form,
slot schema, Word template) derives from these lists.
"""
from __future__ import annotations

from typing import Final

# 八.1 月盤鋼品（10 項）— 順序與 5/4 PDF 一致
MONTHLY_PRODUCTS: Final[list[str]] = [
    "熱軋鋼板(一般料)",
    "熱軋鋼捲(軋延料)",
    "熱軋鋼捲(一般料)",
    "冷軋鋼捲(一般料)",
    "電鍍鋅鋼捲(抗指紋)",
    "電鍍鋅鋼捲(建材)",
    "熱浸鍍鋅鋼捲(建材、烤漆料)",
    "熱浸鍍鋅鋼捲(家電、電腦、其他料)",
    "電磁鋼捲(中低規)",
    "電磁鋼捲(高規)",
]

# 八.2 季盤鋼品（16 項）
QUARTERLY_PRODUCTS: Final[list[str]] = [
    "棒線(中高碳)",
    "棒線(低合金)",
    "棒線(低碳)",
    "棒線(冷打)",
    "鋼板(A36/SS400)",
    "鋼板(船板)",
    "鋼板(其他板)",
    "鋼板(SM570 系列)",
    "熱軋鋼板(中高碳)",
    "熱軋鋼板(工具鋼)",
    "熱軋鋼捲(中高碳)",
    "熱軋鋼捲(工具鋼)",
    "冷軋鋼捲(中高碳)",
    "冷軋鋼捲(工具鋼)",
    "冷軋鋼捲(製桶)",
    "汽車料",
]


def product_count(group: str) -> int:
    return len(MONTHLY_PRODUCTS) if group == "monthly" else len(QUARTERLY_PRODUCTS)


def product_name(group: str, slot_index: int) -> str:
    products = MONTHLY_PRODUCTS if group == "monthly" else QUARTERLY_PRODUCTS
    return products[slot_index]
