import { create } from "zustand";
import type { ConversationOut, MessageOut } from "@/types";

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

  // 從 /new 頁跳轉至 /chat 時，帶入第一則待送訊息
  pendingMessage: string | null;
  setPendingMessage: (msg: string | null) => void;
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
}));
