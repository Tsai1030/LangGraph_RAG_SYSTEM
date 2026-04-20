"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { useChatStore } from "@/store/chatStore";
import type { ConversationOut } from "@/types";

const SUGGESTIONS = [
  "工地施工動線規劃",
  "採購發包的金額分級",
  "安全衛生管理規定",
  "工務所辦公室設置",
];

export default function NewPage() {
  const router = useRouter();
  const { addConversation, setPendingMessage } = useChatStore();
  const [creating, setCreating] = useState(false);
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自動調整 textarea 高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [value]);

  const handleSend = useCallback(async (text: string) => {
    const msg = text.trim();
    if (!msg || creating) return;
    setCreating(true);
    try {
      const { data } = await api.post<ConversationOut>("/conversations", {});
      addConversation(data);
      setPendingMessage(msg);
      router.push(`/chat/${data.id}`);
    } catch {
      setCreating(false);
    }
  }, [creating, router, addConversation, setPendingMessage]);

  const canSend = value.trim().length > 0 && !creating;

  return (
    <div className="flex flex-col h-full items-center bg-background px-4 select-none overflow-y-auto">
      {/* 固定頂部偏移置中：避免 textarea 高度變化時 justify-center 觸發整頁 reflow 閃爍 */}
      <div className="w-full max-w-2xl flex flex-col gap-4 pt-[28vh]">

        {/* 標題 */}
        <div className="text-center mb-1">
          <h2 className="text-xl font-semibold text-zinc-800">有什麼可以幫您？</h2>
          <p className="text-sm text-zinc-400 mt-1">查詢工地作業規範，或生成結構化作業表單</p>
        </div>

        {/* Input 框 */}
        <div className={cn(
          "flex items-end gap-2 rounded-4xl border bg-white shadow-sm px-4 py-3 transition-shadow",
          creating
            ? "border-zinc-200 opacity-60"
            : "border-zinc-200 hover:border-zinc-300 focus-within:border-zinc-400 focus-within:shadow-md"
        )}>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(value); }
            }}
            disabled={creating}
            placeholder="輸入問題，例如：動員開工需要哪些初期計畫？"
            rows={1}
            className="flex-1 text-sm text-zinc-800 placeholder-zinc-400 bg-transparent outline-none resize-none leading-relaxed disabled:cursor-not-allowed"
            style={{ maxHeight: "180px", overflowY: "auto" }}
          />
          <button
            onClick={() => handleSend(value)}
            disabled={!canSend}
            className={cn(
              "shrink-0 size-8 rounded-full flex items-center justify-center transition-all",
              canSend ? "bg-zinc-900 hover:bg-zinc-700" : "bg-zinc-100 cursor-not-allowed"
            )}
            title="送出"
          >
            <ArrowUp size={14} className={canSend ? "text-white" : "text-zinc-400"} />
          </button>
        </div>

        {/* 免責聲明 */}
        <p className="text-center text-[11px] text-zinc-400 -mt-2 select-none">
          AI 有時會犯錯，需要二次查驗
        </p>

        {/* 建議問題 */}
        <div className="flex gap-2">
          {SUGGESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => handleSend(q)}
              disabled={creating}
              className="flex-1 px-3 py-3 rounded-2xl border border-zinc-200 bg-white text-xs text-zinc-600 hover:text-zinc-900 hover:border-zinc-300 hover:shadow-sm transition-all text-center disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {q}
            </button>
          ))}
        </div>

      </div>
    </div>
  );
}
