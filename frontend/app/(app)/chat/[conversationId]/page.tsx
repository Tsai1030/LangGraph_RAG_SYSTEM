"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import api from "@/lib/api";
import { streamChat } from "@/lib/sse";
import { useChatStore } from "@/store/chatStore";
import MessageList from "@/components/chat/MessageList";
import InputBar from "@/components/chat/InputBar";
import type { MessageOut, FormData as FormDataType, Source, ConversationDetail } from "@/types";

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const { setCurrentMessages, appendMessage, updateLastAssistantMessage } = useChatStore();

  const [loading, setLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState<MessageOut | null>(null);
  const [streamingFormData, setStreamingFormData] = useState<FormDataType | null>(null);
  const [streamingSources, setStreamingSources] = useState<Source[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const messages = useChatStore((s) => s.currentMessages);

  // Load conversation messages
  useEffect(() => {
    if (!conversationId) return;
    setLoading(true);
    setCurrentMessages([]);
    setStreamingMessage(null);
    setStreamingFormData(null);
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

  const handleSend = useCallback(async (text: string) => {
    if (isStreaming) return;

    // Optimistic user message
    const userMsg: MessageOut = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      meta: null,
      created_at: new Date().toISOString(),
    };
    appendMessage(userMsg);

    // Streaming assistant placeholder
    const assistantId = crypto.randomUUID();
    setStreamingMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      meta: null,
      created_at: new Date().toISOString(),
    });
    setStreamingFormData(null);
    setStreamingSources([]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulated = "";

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
        (formData) => setStreamingFormData(formData),
        (sources) => setStreamingSources(sources),
        () => {
          // on done
          const finalMsg: MessageOut = {
            id: assistantId,
            role: "assistant",
            content: accumulated,
            meta: { sources: streamingSources, form_data: streamingFormData ?? undefined },
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
      // Finalize even on error/abort
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
    <div className="flex flex-col h-full bg-background">
      <MessageList
        messages={messages}
        streamingMessage={streamingMessage}
        streamingFormData={streamingFormData}
        streamingSources={streamingSources}
        onSuggestedQuery={handleSend}
        loading={loading}
      />
      <InputBar
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={loading}
      />
    </div>
  );
}
