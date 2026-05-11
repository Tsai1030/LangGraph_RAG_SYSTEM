"""一次性腳本：分析 LangSmith LLM-run CSV，輸出多維度 token 報告。

輸出：
  1. 每 thread 的呼叫鏈與 token 合計（含 query 開頭，幫助辨識 scenario）
  2. 各節點跨 thread 統計：count, sum, mean, median, min, max
  3. Thread 排名（依 token 合計）
  4. 整體合計
"""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

CSV_PATH = Path(r"c:\Users\226376\Desktop\data\token test.csv")

csv.field_size_limit(10 * 1024 * 1024)

with CSV_PATH.open(encoding="utf-8") as f:
    rows = list(csv.DictReader(f))


def parse_usage(s: str) -> tuple[int, int, int]:
    try:
        u = json.loads(s or "{}")
    except json.JSONDecodeError:
        return 0, 0, 0
    inp = u.get("input_tokens") or u.get("prompt_tokens") or 0
    out = u.get("output_tokens") or u.get("completion_tokens") or 0
    tot = u.get("total_tokens") or (inp + out)
    return inp, out, tot


def first_human_query(messages_raw: str) -> str:
    """從 generations 的 messages 抽出該 LLM call 看到的最早 human message 開頭。"""
    try:
        data = json.loads(messages_raw or "[]")
    except json.JSONDecodeError:
        return ""
    msgs = data[0] if data and isinstance(data[0], list) else data
    for m in msgs:
        if not isinstance(m, dict):
            continue
        # LangChain dump 結構
        kwargs = m.get("kwargs") or {}
        type_ = kwargs.get("type") or m.get("type")
        if type_ == "human":
            content = kwargs.get("content") or m.get("content") or ""
            content = str(content).replace("\n", " ").strip()
            return content[:60]
    return ""


print(f"=== 總體 ===")
print(f"LLM 呼叫數: {len(rows)}")

# 群組
threads: dict[str, list[dict]] = defaultdict(list)
for r in rows:
    threads[r.get("thread_id") or "?"].append(r)
print(f"distinct thread 數: {len(threads)}\n")

# 每 thread 細節
print("=" * 110)
print("每 thread 細節（依 langgraph_step 排序，列出所有 LLM call）")
print("=" * 110)

thread_summaries = []
for tid, calls in sorted(threads.items()):
    calls.sort(key=lambda r: int(r.get("langgraph_step") or 0))
    qhint = ""
    for r in calls:
        qhint = first_human_query(r.get("messages", ""))
        if qhint:
            break
    in_sum = out_sum = tot_sum = 0
    print(f"\nthread {tid[:12]}…  query: {qhint!r}")
    print(f"  {'step':>4}  {'node':<22}  {'in':>7}  {'out':>7}  {'total':>7}")
    for r in calls:
        inp, out, tot = parse_usage(r.get("usage_metadata") or "")
        step = r.get("langgraph_step") or "?"
        node = r.get("langgraph_node") or "?"
        print(f"  {step:>4}  {node:<22}  {inp:>7}  {out:>7}  {tot:>7}")
        in_sum += inp
        out_sum += out
        tot_sum += tot
    print(f"  {'':>4}  {'thread 合計':<22}  {in_sum:>7}  {out_sum:>7}  {tot_sum:>7}")
    thread_summaries.append({
        "tid": tid,
        "query": qhint,
        "calls": len(calls),
        "in": in_sum,
        "out": out_sum,
        "total": tot_sum,
    })

# Thread 排名
print("\n" + "=" * 110)
print(f"Thread 排名（依 total token；共 {len(thread_summaries)} 個 thread）")
print("=" * 110)
print(f"{'#':>3}  {'tid':<14}  {'calls':>5}  {'in':>7}  {'out':>7}  {'total':>7}  query")
print("-" * 110)
for i, t in enumerate(sorted(thread_summaries, key=lambda x: -x["total"]), 1):
    print(f"{i:>3}  {t['tid'][:12]:<14}  {t['calls']:>5}  {t['in']:>7}  {t['out']:>7}  {t['total']:>7}  {t['query']!r}")

# 節點維度
print("\n" + "=" * 110)
print("各節點跨所有 thread 統計")
print("=" * 110)
by_node_in: dict[str, list[int]] = defaultdict(list)
by_node_out: dict[str, list[int]] = defaultdict(list)
by_node_total: dict[str, list[int]] = defaultdict(list)
for r in rows:
    inp, out, tot = parse_usage(r.get("usage_metadata") or "")
    node = r.get("langgraph_node") or "?"
    by_node_in[node].append(inp)
    by_node_out[node].append(out)
    by_node_total[node].append(tot)

print(f"{'node':<22}  {'count':>5}  {'sum':>9}  {'mean':>7}  {'median':>7}  {'min':>7}  {'max':>7}  {'in_avg':>7}  {'out_avg':>7}")
print("-" * 110)
for node in sorted(by_node_total, key=lambda n: -sum(by_node_total[n])):
    vals = by_node_total[node]
    print(
        f"{node:<22}  {len(vals):>5}  {sum(vals):>9}  {statistics.mean(vals):>7.0f}  "
        f"{statistics.median(vals):>7.0f}  {min(vals):>7}  {max(vals):>7}  "
        f"{statistics.mean(by_node_in[node]):>7.0f}  {statistics.mean(by_node_out[node]):>7.0f}"
    )

# 整體
all_in = sum(sum(v) for v in by_node_in.values())
all_out = sum(sum(v) for v in by_node_out.values())
all_total = sum(sum(v) for v in by_node_total.values())
print("\n" + "=" * 110)
print(f"整體合計：input {all_in:,}  output {all_out:,}  total {all_total:,}")
print(f"ratio in:out = {all_in/max(all_out,1):.2f} : 1")
print(f"平均每 thread total: {all_total // max(len(threads), 1):,}")
print(f"平均每 LLM call total: {all_total // max(len(rows), 1):,}")
