import { create } from "zustand";
import type {
  ConversationOut,
  FormData,
  FormFile,
  MessageOut,
  Source,
} from "@/types";

interface ConversationStreamingState {
  isStreaming: boolean;
  isFormLoading: boolean;
  streamingMessage: MessageOut | null;
  streamingFormData: FormData | null;
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

  pendingMessage: string | null;
  setPendingMessage: (msg: string | null) => void;

  streamingByConversation: Record<string, ConversationStreamingState>;
  startStreaming: (conversationId: string, message: MessageOut) => void;
  appendStreamingText: (conversationId: string, chunk: string) => void;
  setStreamingFormLoading: (conversationId: string, loading: boolean) => void;
  setStreamingFormData: (conversationId: string, data: FormData | null) => void;
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

  pendingMessage: null,
  setPendingMessage: (msg) => set({ pendingMessage: msg }),

  streamingByConversation: {},
  startStreaming: (conversationId, message) =>
    set((s) => ({
      streamingByConversation: {
        ...s.streamingByConversation,
        [conversationId]: {
          isStreaming: true,
          isFormLoading: false,
          streamingMessage: message,
          streamingFormData: null,
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
  setStreamingFormData: (conversationId, data) =>
    set((s) => {
      const current = s.streamingByConversation[conversationId];
      if (!current) return s;
      return {
        streamingByConversation: {
          ...s.streamingByConversation,
          [conversationId]: {
            ...current,
            isFormLoading: false,
            streamingFormData: data,
          },
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
