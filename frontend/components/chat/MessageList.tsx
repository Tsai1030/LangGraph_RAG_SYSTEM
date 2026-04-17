"use client";

import { useEffect, useRef } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { MessageOut, FormData as FormDataType, Source } from "@/types";
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
  streamingFormData: FormDataType | null;
  streamingSources: Source[];
  onSuggestedQuery: (q: string) => void;
  loading?: boolean;
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
  messages, streamingMessage, streamingFormData,
  streamingSources, onSuggestedQuery, loading = false,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingMessage?.content]);

  if (loading) return <LoadingSkeleton />;
  if (!messages.length && !streamingMessage) return <WelcomeScreen onQuery={onSuggestedQuery} />;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto py-8 flex flex-col gap-6">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {streamingMessage && (
          <MessageBubble
            message={streamingMessage}
            isStreaming
            streamingFormData={streamingFormData}
            streamingSources={streamingSources}
          />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
