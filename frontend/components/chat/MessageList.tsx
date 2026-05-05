"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { MessageOut, FormFile, Source } from "@/types";
import MessageBubble from "./MessageBubble";

const SUGGESTIONS = [
  "動員開工需要哪些初期計畫？",
  "採購發包的金額分級是如何規定的？",
  "請幫我生成動員開工作業檢核表",
  "工務所辦公室要符合哪些 5S 標準？",
];

interface Props {
  messages: MessageOut[];
  streamingMessage: MessageOut | null;
  streamingFormFiles: FormFile[];
  streamingSources: Source[];
  isFormLoading?: boolean;
  onSuggestedQuery: (q: string) => void;
  loading?: boolean;
  onAtBottomChange?: (atBottom: boolean) => void;
  scrollToBottomRef?: React.RefObject<(() => void) | null>;
}

function WelcomeScreen({ onQuery }: { onQuery: (q: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-16 select-none">
      <div className="mb-8 text-center">
        <div className="size-10 rounded-xl bg-zinc-900 flex items-center justify-center mx-auto mb-4">
          <span className="text-white text-xs font-bold tracking-tight">AI</span>
        </div>
        <h2 className="text-lg font-semibold text-zinc-800">有什麼可以幫您？</h2>
        <p className="text-sm text-zinc-400 mt-1">查詢工地作業規範，或生成結構化作業表單</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onQuery(q)}
            className="text-left px-4 py-3 rounded-xl border border-zinc-200 bg-white text-sm text-zinc-600 hover:text-zinc-900 hover:border-zinc-300 hover:shadow-sm transition-all leading-snug"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex-1 flex flex-col gap-6 px-6 py-8">
      {[1, 2].map((i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="size-6 rounded-full shrink-0" />
          <div className="flex flex-col gap-2 flex-1">
            <Skeleton className="h-3.5 w-3/4" />
            <Skeleton className="h-3.5 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function MessageList({
  messages, streamingMessage, streamingFormFiles,
  streamingSources, isFormLoading = false, onSuggestedQuery, loading = false,
  onAtBottomChange, scrollToBottomRef,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  // 檢查滾動容器是否已到底部
  const checkAtBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) { setAtBottom(true); return; }
    setAtBottom(el.scrollTop + el.clientHeight >= el.scrollHeight - 60);
  }, []);

  // 監聽滾動事件
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", checkAtBottom, { passive: true });
    checkAtBottom();
    return () => el.removeEventListener("scroll", checkAtBottom);
  }, [checkAtBottom, loading]);

  // 串流時內容增加 → 更新底部狀態
  useEffect(() => {
    checkAtBottom();
  }, [streamingMessage?.content, checkAtBottom]);

  // 進入聊天室載入完成 → 自動滾到最底（不含串流）
  useEffect(() => {
    if (!loading && messages.length > 0) {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [loading]); // eslint-disable-line react-hooks/exhaustive-deps

  // 通知 parent atBottom 狀態變化
  useEffect(() => {
    onAtBottomChange?.(atBottom);
  }, [atBottom, onAtBottomChange]);

  // 暴露 scrollToBottom 給 parent 呼叫
  useEffect(() => {
    if (!scrollToBottomRef) return;
    scrollToBottomRef.current = () => {
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      });
    };
  }, [scrollToBottomRef]);

  return (
    <>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {loading ? (
          <LoadingSkeleton />
        ) : !messages.length && !streamingMessage ? (
          <WelcomeScreen onQuery={onSuggestedQuery} />
        ) : (
          <div className={cn("max-w-3xl mx-auto pt-8 flex flex-col gap-6", streamingMessage ? "pb-40" : "pb-8")}>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {streamingMessage && (
              <MessageBubble
                message={streamingMessage}
                isStreaming
                isFormLoading={isFormLoading}
                streamingFormFiles={streamingFormFiles}
                streamingSources={streamingSources}
              />
            )}
          </div>
        )}
      </div>
    </>
  );
}
