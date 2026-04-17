"use client";

import { useEffect, useRef } from "react";
import { MessageCircle } from "lucide-react";
import type { MessageOut, FormData as FormDataType, Source } from "@/types";
import MessageBubble from "./MessageBubble";

const SUGGESTED_QUERIES = [
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
  onSuggestedQuery: (query: string) => void;
}

export default function MessageList({
  messages,
  streamingMessage,
  streamingFormData,
  streamingSources,
  onSuggestedQuery,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom when content changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingMessage?.content]);

  const isEmpty = messages.length === 0 && !streamingMessage;

  if (isEmpty) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 text-center">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center mb-4 shadow-lg">
          <MessageCircle size={28} className="text-white" />
        </div>
        <h2 className="text-xl font-semibold text-slate-800 mb-1">營造知識助理</h2>
        <p className="text-sm text-slate-500 mb-8 max-w-sm">
          您好！我可以幫您查詢工地作業程序、管理規範，也能生成結構化的作業表單。
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
          {SUGGESTED_QUERIES.map((q) => (
            <button
              key={q}
              onClick={() => onSuggestedQuery(q)}
              className="text-left px-4 py-3 rounded-xl border border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50 transition-all text-sm text-slate-700 shadow-sm hover:shadow"
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto py-6 space-y-5">
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
  );
}
