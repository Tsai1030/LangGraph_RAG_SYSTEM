"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowDown } from "lucide-react";
import api from "@/lib/api";
import { streamChat } from "@/lib/sse";
import { useAuthStore } from "@/store/authStore";
import { useChatStore } from "@/store/chatStore";
import MessageList from "@/components/chat/MessageList";
import InputBar from "@/components/chat/InputBar";
import type {
  ConversationDetail,
  MessageOut,
  Source,
} from "@/types";

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const router = useRouter();
  const {
    setCurrentMessages,
    appendMessage,
    pendingMessage,
    setPendingMessage,
    conversations,
    updateConversationTitle,
    startStreaming,
    appendStreamingText,
    setStreamingFormLoading,
    setStreamingFormFiles,
    setStreamingSources,
    clearStreaming,
    truncateMessagesFrom,
  } = useChatStore();

  const [loading, setLoading] = useState(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const scrollToBottomRef = useRef<(() => void) | null>(null);
  const activeConversationRef = useRef(conversationId);
  const abortControllersRef = useRef<Record<string, AbortController>>({});

  const messages = useChatStore((s) => s.currentMessages);
  const streamingState = useChatStore(
    (s) => s.streamingByConversation[conversationId]
  );

  const isStreaming = streamingState?.isStreaming ?? false;
  const isFormLoading = streamingState?.isFormLoading ?? false;
  const streamingMessage = streamingState?.streamingMessage ?? null;
  const streamingFormFiles = streamingState?.streamingFormFiles ?? [];
  const streamingSources = streamingState?.streamingSources ?? [];

  const showDots = !isAtBottom && isStreaming;
  const showArrow = !isAtBottom && !isStreaming;

  useEffect(() => {
    activeConversationRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId) return;

    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setLoading(true);
      setCurrentMessages([]);
    });

    api
      .get<ConversationDetail>(`/conversations/${conversationId}`)
      .then(({ data }) => {
        if (cancelled) return;
        const mapped: MessageOut[] = data.messages
          .filter((m) => m.role !== "system")
          .map((m) => ({
            ...m,
            meta: m.meta ?? null,
          }));
        setCurrentMessages(mapped);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId, setCurrentMessages]);

  const handleSend = useCallback(
    async (text: string) => {
      if (!conversationId || isStreaming) return;

      const conv = conversations.find((c) => c.id === conversationId);
      if (conv && !conv.title) {
        updateConversationTitle(conversationId, text.slice(0, 30));
      }

      const userMsg: MessageOut = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        role: "user",
        content: text,
        meta: null,
        created_at: new Date().toISOString(),
      };
      appendMessage(userMsg);
      scrollToBottomRef.current?.();

      const assistantId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      startStreaming(conversationId, {
        id: assistantId,
        role: "assistant",
        content: "",
        meta: null,
        created_at: new Date().toISOString(),
      });

      const controller = new AbortController();
      abortControllersRef.current[conversationId] = controller;

      let accumulated = "";
      let latestSources: Source[] = [];
      let latestFormFiles: NonNullable<MessageOut["meta"]>["form_files"] = [];

      try {
        await streamChat(
          conversationId,
          text,
          (chunk) => {
            accumulated += chunk;
            appendStreamingText(conversationId, chunk);
          },
          () => {
            setStreamingFormLoading(conversationId, true);
          },
          (files) => {
            latestFormFiles = files;
            setStreamingFormFiles(conversationId, files);
          },
          (sources) => {
            latestSources = sources;
            setStreamingSources(conversationId, sources);
          },
          () => {
            const finalMsg: MessageOut = {
              id: assistantId,
              role: "assistant",
              content: accumulated,
              meta: {
                sources: latestSources,
                form_files: latestFormFiles?.length ? latestFormFiles : undefined,
              },
              created_at: new Date().toISOString(),
            };

            if (activeConversationRef.current === conversationId) {
              appendMessage(finalMsg);
            }

            clearStreaming(conversationId);
            delete abortControllersRef.current[conversationId];
          },
          controller.signal
        );
      } catch (err: unknown) {
        clearStreaming(conversationId);
        delete abortControllersRef.current[conversationId];

        if (err instanceof Error && err.message === "UNAUTHORIZED") {
          useAuthStore.getState().clearAuth();
          router.push("/login");
          return;
        }

        if (err instanceof Error && err.message === "OVERLOADED") {
          if (activeConversationRef.current === conversationId) {
            appendMessage({
              id: assistantId,
              role: "assistant",
              content: "The server is busy. Please try again later.",
              meta: null,
              created_at: new Date().toISOString(),
            });
          }
          return;
        }

        // STREAM_ERROR：後端 graph 內部例外（已被 chat.py 的 try/except 捕捉並 emit error 事件）
        if (err instanceof Error && err.message === "STREAM_ERROR") {
          if (activeConversationRef.current === conversationId) {
            appendMessage({
              id: assistantId,
              role: "assistant",
              content: "Something went wrong. Please try again later.",
              meta: null,
              created_at: new Date().toISOString(),
            });
          }
          return;
        }

        if (err instanceof Error && err.name !== "AbortError") {
          if (activeConversationRef.current === conversationId) {
            appendMessage({
              id: assistantId,
              role: "assistant",
              content: accumulated || "Something went wrong. Please try again later.",
              meta: null,
              created_at: new Date().toISOString(),
            });
          }
        }
      }
    },
    [
      conversationId,
      isStreaming,
      conversations,
      updateConversationTitle,
      appendMessage,
      startStreaming,
      appendStreamingText,
      setStreamingFormLoading,
      setStreamingFormFiles,
      setStreamingSources,
      clearStreaming,
      router,
    ]
  );

  useEffect(() => {
    if (loading || !pendingMessage) return;
    const msg = pendingMessage;
    setPendingMessage(null);
    handleSend(msg);
  }, [handleSend, loading, pendingMessage, setPendingMessage]);

  const handleStop = () => {
    if (!conversationId) return;
    abortControllersRef.current[conversationId]?.abort();
  };

  const handleRetry = useCallback(
    async (assistantMessageId: string) => {
      if (!conversationId || isStreaming) return;

      // 找到要重答的 assistant 訊息，往前抓最近一則 user 訊息當作 prompt
      const currentMsgs = useChatStore.getState().currentMessages;
      const idx = currentMsgs.findIndex((m) => m.id === assistantMessageId);
      if (idx === -1) return;

      let userIdx = -1;
      for (let i = idx - 1; i >= 0; i--) {
        if (currentMsgs[i].role === "user") {
          userIdx = i;
          break;
        }
      }
      if (userIdx === -1) return;

      const userMsg = currentMsgs[userIdx];

      try {
        // 後端：把 user 訊息與其後所有訊息一併刪掉，並清 LangGraph thread state
        await api.delete(
          `/conversations/${conversationId}/messages/${userMsg.id}/onward`
        );
      } catch {
        return;
      }

      // 前端：把 store 內這段截掉，再走一次正常的 send 流程
      truncateMessagesFrom(userMsg.id);
      handleSend(userMsg.content);
    },
    [conversationId, isStreaming, truncateMessagesFrom, handleSend]
  );

  return (
    <div className="relative flex flex-col h-full bg-background">
      <MessageList
        messages={messages}
        streamingMessage={streamingMessage}
        streamingFormFiles={streamingFormFiles}
        streamingSources={streamingSources}
        isFormLoading={isFormLoading}
        onSuggestedQuery={handleSend}
        loading={loading}
        onAtBottomChange={setIsAtBottom}
        scrollToBottomRef={scrollToBottomRef}
        onRetry={handleRetry}
        retryDisabled={isStreaming}
      />

      {showDots && (
        <div className="absolute bottom-[124px] left-1/2 -translate-x-1/2 z-20">
          <button
            onClick={() => scrollToBottomRef.current?.()}
            className="flex items-center gap-[4px] px-2 py-3 rounded-2xl bg-white border border-zinc-200 shadow-md cursor-pointer"
          >
            <span
              className="size-[4px] rounded-full bg-zinc-600"
              style={{ animation: "pulseDot 1.4s ease-in-out 0ms infinite" }}
            />
            <span
              className="size-[4px] rounded-full bg-zinc-600"
              style={{ animation: "pulseDot 1.4s ease-in-out 160ms infinite" }}
            />
            <span
              className="size-[4px] rounded-full bg-zinc-600"
              style={{ animation: "pulseDot 1.4s ease-in-out 320ms infinite" }}
            />
          </button>
        </div>
      )}

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
