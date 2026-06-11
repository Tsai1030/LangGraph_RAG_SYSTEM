"""驗證 _route_rewriter 路由 + graph 編譯。

用法：uv run python scripts/test_route_rewriter.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph.builder import _route_rewriter, build_graph

# 1. 改寫成功 → retriever
r = _route_rewriter({"query": "工地安全", "retrieval_query": "工地 安全衛生 規定", "intent": "qa"})
print("rewritten ok ->", r)
assert r == "retriever"

# 2. fallback 回原 query（qa）→ 並行終端
r = _route_rewriter({"query": "工地安全", "retrieval_query": "工地安全", "intent": "qa"})
print("fallback qa  ->", r)
assert r == ["responder", "source_filter"]

# 3. fallback（form intent）→ form_structurer
r = _route_rewriter({
    "query": "做一份檢核表", "retrieval_query": "做一份檢核表",
    "intent": "dynamic_form_generate",
})
print("fallback form->", r)
assert r == "form_structurer"

# 4. retrieval_query 為空（防禦）→ 終端路由
r = _route_rewriter({"query": "工地安全", "retrieval_query": "", "intent": "qa"})
print("empty rq     ->", r)
assert r == ["responder", "source_filter"]

# 5. 空白差異也算相同（與 retrieval.py 的 .strip() gate 一致）
r = _route_rewriter({"query": " 工地安全 ", "retrieval_query": "工地安全", "intent": "qa"})
print("strip equal  ->", r)
assert r == ["responder", "source_filter"]

# 6. graph 編譯
g = build_graph()
nodes = sorted(g.get_graph().nodes)
print("graph nodes:", nodes)
assert "query_rewriter" in nodes and "retriever" in nodes
print("ALL PASS")
