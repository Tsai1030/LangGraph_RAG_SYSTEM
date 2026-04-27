"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { ArrowDown } from "lucide-react";
import api from "@/lib/api";
import { streamChat } from "@/lib/sse";
import { useChatStore } from "@/store/chatStore";
import MessageList from "@/components/chat/MessageList";
import InputBar from "@/components/chat/InputBar";
import type { MessageOut, FormData as FormDataType, FormFile, Source, ConversationDetail } from "@/types";

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const { setCurrentMessages, appendMessage, pendingMessage, setPendingMessage, conversations, updateConversationTitle } = useChatStore();

  const [loading, setLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isFormLoading, setIsFormLoading] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState<MessageOut | null>(null);
  const [streamingFormData, setStreamingFormData] = useState<FormDataType | null>(null);
  const [streamingFormFiles, setStreamingFormFiles] = useState<FormFile[]>([]);
  const [streamingSources, setStreamingSources] = useState<Source[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const scrollToBottomRef = useRef<(() => void) | null>(null);

  const showDots = !isAtBottom && isStreaming;
  const showArrow = !isAtBottom && !isStreaming;

  const abortRef = useRef<AbortController | null>(null);
  const messages = useChatStore((s) => s.currentMessages);

  // Load conversation messages
  useEffect(() => {
    if (!conversationId) return;
    setLoading(true);
    setCurrentMessages([]);
    setStreamingMessage(null);
    setStreamingFormData(null);
    setStreamingFormFiles([]);
    setStreamingSources([]);

    api
      .get<ConversationDetail>(`/conversations/${conversationId}`)
      .then(({ data }) => {
        const mapped: MessageOut[] = data.messages
          .filter((m) => m.role !== "system")
          .map((m) => ({
            ...m,
            meta: m.meta ?? null,
          }));
        setCurrentMessages(mapped);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 消費從 /new 頁帶來的第一則訊息
  useEffect(() => {
    if (loading || !pendingMessage) return;
    const msg = pendingMessage;
    setPendingMessage(null);
    handleSend(msg);
  }, [loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSend = useCallback(async (text: string) => {
    if (isStreaming) return;

    // 若對話尚無標題，樂觀更新 sidebar
    const conv = conversations.find((c) => c.id === conversationId);
    if (conv && !conv.title) {
      updateConversationTitle(conversationId, text.slice(0, 30));
    }

    // Optimistic user message
    const userMsg: MessageOut = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      role: "user",
      content: text,
      meta: null,
      created_at: new Date().toISOString(),
    };
    appendMessage(userMsg);
    scrollToBottomRef.current?.();

    // Streaming assistant placeholder
    const assistantId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setStreamingMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      meta: null,
      created_at: new Date().toISOString(),
    });
    setStreamingFormData(null);
    setStreamingFormFiles([]);
    setStreamingSources([]);
    setIsFormLoading(false);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulated = "";
    let latestSources: Source[] = [];
    let latestFormData: FormDataType | null = null;
    let latestFormFiles: FormFile[] = [];

    try {
      await streamChat(
        conversationId,
        text,
        (chunk) => {
          accumulated += chunk;
          setStreamingMessage((prev) =>
            prev ? { ...prev, content: accumulated } : null
          );
        },
        () => { setIsFormLoading(true); },
        (formData) => { setIsFormLoading(false); latestFormData = formData; setStreamingFormData(formData); },
        (files) => { latestFormFiles = files; setStreamingFormFiles(files); },
        (sources) => { latestSources = sources; setStreamingSources(sources); },
        () => {
          // on done
          setIsFormLoading(false);
          const finalMsg: MessageOut = {
            id: assistantId,
            role: "assistant",
            content: accumulated,
            meta: {
              sources: latestSources,
              form_data: latestFormData ?? undefined,
              form_files: latestFormFiles.length ? latestFormFiles : undefined,
            },
            created_at: new Date().toISOString(),
          };
          appendMessage(finalMsg);
          setStreamingMessage(null);
          setIsStreaming(false);
          abortRef.current = null;
        },
        controller.signal
      );
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setStreamingMessage((prev) =>
          prev ? { ...prev, content: accumulated || "發生錯誤，請重試。" } : null
        );
      }
      if (accumulated || streamingFormData) {
        appendMessage({
          id: assistantId,
          role: "assistant",
          content: accumulated,
          meta: null,
          created_at: new Date().toISOString(),
        });
      }
      setStreamingMessage(null);
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [conversationId, isStreaming, appendMessage, streamingFormData, streamingSources]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleStop = () => {
    abortRef.current?.abort();
  };

  return (
    <div className="relative flex flex-col h-full bg-background">
      <MessageList
        messages={messages}
        streamingMessage={streamingMessage}
        streamingFormData={streamingFormData}
        streamingFormFiles={streamingFormFiles}
        streamingSources={streamingSources}
        isFormLoading={isFormLoading}
        onSuggestedQuery={handleSend}
        loading={loading}
        onAtBottomChange={setIsAtBottom}
        scrollToBottomRef={scrollToBottomRef}
      />

      {/* 串流中：三點動畫 */}
      {showDots && (
        <div className="absolute bottom-[124px] left-1/2 -translate-x-1/2 z-20">
          <button
            onClick={() => scrollToBottomRef.current?.()}
            className="flex items-center gap-[4px] px-2 py-3 rounded-2xl bg-white border border-zinc-200 shadow-md cursor-pointer"
          >
            <span className="size-[4px] rounded-full bg-zinc-600" style={{ animation: "pulseDot 1.4s ease-in-out 0ms infinite" }} />
            <span className="size-[4px] rounded-full bg-zinc-600" style={{ animation: "pulseDot 1.4s ease-in-out 160ms infinite" }} />
            <span className="size-[4px] rounded-full bg-zinc-600" style={{ animation: "pulseDot 1.4s ease-in-out 320ms infinite" }} />
          </button>
        </div>
      )}

      {/* 串流結束但未在底部：向下箭頭 */}
      {showArrow && (
        <div className="absolute bottom-[124px] left-1/2 -translate-x-1/2 z-20">
          <button
            onClick={() => scrollToBottomRef.current?.()}
            className="flex items-center justify-center size-8 rounded-full bg-white border border-zinc-200 shadow-md cursor-pointer hover:bg-zinc-50 transition-colors"
          >
            <ArrowDown size={14} className="text-zinc-600" />
          </button>
        </div>
      )}

      <InputBar
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={loading}
      />
    </div>
  );
}
