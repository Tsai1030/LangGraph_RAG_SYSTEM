"use client";

import { useRef, useState, useEffect } from "react";
import { ArrowUp, Square } from "lucide-react";

interface Props {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export default function InputBar({ onSend, onStop, isStreaming, disabled }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [value]);

  const handleSend = () => {
    const msg = value.trim();
    if (!msg || isStreaming || disabled) return;
    setValue("");
    onSend(msg);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = value.trim().length > 0 && !isStreaming && !disabled;

  return (
    <div
      className="px-4 py-3"
      style={{
        background: "rgba(255, 255, 255, 0.75)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
      }}
    >
      <div className="max-w-3xl mx-auto">
        <div className={`flex items-end gap-2 rounded-2xl border px-4 py-2.5 shadow-sm transition-colors ${
          disabled ? "border-slate-200 bg-slate-50" : "border-slate-300 bg-white focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100"
        }`}>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={isStreaming ? "AI 回覆中..." : "輸入問題，例如：動員開工需要哪些初期計畫？"}
            rows={1}
            className="flex-1 bg-transparent text-sm text-slate-800 placeholder-slate-400 outline-none resize-none auto-resize leading-relaxed disabled:cursor-not-allowed"
            style={{ maxHeight: "200px", overflowY: "auto" }}
          />

          {isStreaming ? (
            <button
              onClick={onStop}
              className="shrink-0 w-8 h-8 rounded-full bg-slate-700 hover:bg-slate-800 flex items-center justify-center transition-colors"
              title="停止生成"
            >
              <Square size={13} className="text-white fill-white" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                canSend
                  ? "bg-blue-600 hover:bg-blue-700 shadow-sm scale-100"
                  : "bg-slate-200 cursor-not-allowed scale-95"
              }`}
              title="送出 (Enter)"
            >
              <ArrowUp size={15} className={canSend ? "text-white" : "text-slate-400"} />
            </button>
          )}
        </div>
        <p className="text-center text-[11px] text-slate-400 mt-1.5">
          Enter 送出 · Shift+Enter 換行
        </p>
      </div>
    </div>
  );
}
