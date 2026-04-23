"use client";

import { useRef, useState, useEffect } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export default function InputBar({ onSend, onStop, isStreaming, disabled }: Props) {
  const [value, setValue] = useState("");
  const [isMobile, setIsMobile] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [value]);

  const handleSend = () => {
    const msg = value.trim();
    if (!msg || isStreaming || disabled) return;
    setValue("");
    onSend(msg);
  };

  const canSend = value.trim().length > 0 && !isStreaming && !disabled;

  return (
    <div className="px-4 pb-4">
      <div className="max-w-3xl mx-auto">
        <div className={cn(
          "flex items-end gap-2 rounded-4xl border bg-white shadow-sm px-4 py-3 transition-all duration-200",
          disabled ? "border-zinc-200 opacity-60" : "border-zinc-200 hover:border-zinc-300 focus-within:border-zinc-400 focus-within:shadow-lg"
        )}>
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
            }}
            disabled={disabled}
            placeholder={isStreaming ? "回覆中…" : isMobile ? "想問就問" : "輸入問題，例如：動員開工需要哪些初期計畫？"}
            rows={1}
            className="flex-1 text-base text-zinc-800 placeholder-zinc-400 bg-transparent outline-none resize-none leading-relaxed disabled:cursor-not-allowed"
            style={{ maxHeight: "180px", overflowY: "auto" }}
          />

          {isStreaming ? (
            <button
              onClick={onStop}
              className="shrink-0 size-8 rounded-full bg-zinc-900 hover:bg-zinc-700 flex items-center justify-center transition-colors"
              title="停止"
            >
              <Square size={12} className="text-white fill-white" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              className={cn(
                "shrink-0 size-8 rounded-full flex items-center justify-center transition-all duration-150",
                canSend ? "bg-zinc-900 hover:bg-zinc-700 active:scale-95" : "bg-zinc-100 cursor-not-allowed"
              )}
              title="送出"
            >
              <ArrowUp size={14} className={canSend ? "text-white" : "text-zinc-400"} />
            </button>
          )}
        </div>
        <p className="text-center text-[11px] text-zinc-400 mt-1.5 select-none">
          AI有時會犯錯·需要二次查驗
        </p>
      </div>
    </div>
  );
}
