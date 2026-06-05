import { create } from "zustand";
import type {
  ConversationOut,
  FormFile,
  MessageOut,
  Source,
} from "@/types";

interface ConversationStreamingState {
  isStreaming: boolean;
  isFormLoading: boolean;
  isImageReading: boolean;
  streamingMessage: MessageOut | null;
  streamingFormFiles: FormFile[];
  streamingSources: Source[];
}

interface ChatState {
  conversations: ConversationOut[];
  setConversations: (convs: ConversationOut[]) => void;
  addConversation: (conv: ConversationOut) => void;
  removeConversation: (id: string) => void;
  updateConversationTitle: (id: string, title: string) => void;

  currentMessages: MessageOut[];
  setCurrentMessages: (msgs: MessageOut[]) => void;
  appendMessage: (msg: MessageOut) => void;
  updateLastAssistantMessage: (content: string) => void;
  truncateMessagesFrom: (messageId: string) => void;

  pendingMessage: string | null;
  setPendingMessage: (msg: string | null) => void;
  pendingImageIds: string[];
  setPendingImageIds: (ids: string[]) => void;

  streamingByConversation: Record<string, ConversationStreamingState>;
  startStreaming: (conversationId: string, message: MessageOut) => void;
  appendStreamingText: (conversationId: string, chunk: string) => void;
  setStreamingFormLoading: (conversationId: string, loading: boolean) => void;
  setStreamingImageReading: (conversationId: string, reading: boolean) => void;
  setStreamingFormFiles: (conversationId: string, files: FormFile[]) => void;
  setStreamingSources: (conversationId: string, sources: Source[]) => void;
  clearStreaming: (conversationId: string) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  setConversations: (convs) => set({ conversations: convs }),
  addConversation: (conv) =>
    set((s) => ({ conversations: [conv, ...s.conversations] })),
  removeConversation: (id) =>
    set((s) => ({ conversations: s.conversations.filter((c) => c.id !== id) })),
  updateConversationTitle: (id, title) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === id ? { ...c, title } : c
      ),
    })),

  currentMessages: [],
  setCurrentMessages: (msgs) => set({ currentMessages: msgs }),
  appendMessage: (msg) =>
    set((s) => ({ currentMessages: [...s.currentMessages, msg] })),
  updateLastAssistantMessage: (content) =>
    set((s) => {
      const msgs = [...s.currentMessages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content };
      }
      return { currentMessages: msgs };
    }),
  truncateMessagesFrom: (messageId) =>
    set((s) => {
      const idx = s.currentMessages.findIndex((m) => m.id === messageId);
      if (idx === -1) return s;
      return { currentMessages: s.currentMessages.slice(0, idx) };
    }),

  pendingMessage: null,
  setPendingMessage: (msg) => set({ pendingMessage: msg }),
  pendingImageIds: [],
  setPendingImageIds: (ids) => set({ pendingImageIds: ids }),

  streamingByConversation: {},
  startStreaming: (conversationId, message) =>
    set((s) => ({
      streamingByConversation: {
        ...s.streamingByConversation,
        [conversationId]: {
          isStreaming: true,
          isFormLoading: false,
          isImageReading: false,
          streamingMessage: message,
          streamingFormFiles: [],
          streamingSources: [],
        },
      },
    })),
  appendStreamingText: (conversationId, chunk) =>
    set((s) => {
      const current = s.streamingByConversation[conversationId];
      if (!current?.streamingMessage) return s;

      return {
        streamingByConversation: {
          ...s.streamingByConversation,
          [conversationId]: {
            ...current,
            // 收到 token → 表示生成階段已過、進入回覆階段，自動關掉 loading
            isFormLoading: false,
            isImageReading: false,
            streamingMessage: {
              ...current.streamingMessage,
              content: current.streamingMessage.content + chunk,
            },
          },
        },
      };
    }),
  setStreamingFormLoading: (conversationId, loading) =>
    set((s) => {
      const current = s.streamingByConversation[conversationId];
      if (!current) return s;
      return {
        streamingByConversation: {
          ...s.streamingByConversation,
          [conversationId]: { ...current, isFormLoading: loading },
        },
      };
    }),
  setStreamingImageReading: (conversationId, reading) =>
    set((s) => {
      const current = s.streamingByConversation[conversationId];
      if (!current) return s;
      return {
        streamingByConversation: {
          ...s.streamingByConversation,
          [conversationId]: { ...current, isImageReading: reading },
        },
      };
    }),
  setStreamingFormFiles: (conversationId, files) =>
    set((s) => {
      const current = s.streamingByConversation[conversationId];
      if (!current) return s;
      return {
        streamingByConversation: {
          ...s.streamingByConversation,
          [conversationId]: { ...current, streamingFormFiles: files },
        },
      };
    }),
  setStreamingSources: (conversationId, sources) =>
    set((s) => {
      const current = s.streamingByConversation[conversationId];
      if (!current) return s;
      return {
        streamingByConversation: {
          ...s.streamingByConversation,
          [conversationId]: { ...current, streamingSources: sources },
        },
      };
    }),
  clearStreaming: (conversationId) =>
    set((s) => {
      const next = { ...s.streamingByConversation };
      delete next[conversationId];
      return { streamingByConversation: next };
    }),
}));
