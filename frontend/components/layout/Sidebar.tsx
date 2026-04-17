"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  Plus, Trash2, LogOut, HardHat, Pencil, Check, X,
} from "lucide-react";
import api from "@/lib/api";
import { logout } from "@/lib/auth";
import { useChatStore } from "@/store/chatStore";
import type { ConversationOut } from "@/types";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "剛剛";
  if (m < 60) return `${m} 分鐘前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小時前`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} 天前`;
  return new Date(iso).toLocaleDateString("zh-TW");
}

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { conversations, setConversations, addConversation, removeConversation, updateConversationTitle } =
    useChatStore();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);

  // Fetch conversation list on mount
  useEffect(() => {
    api.get<ConversationOut[]>("/conversations").then(({ data }) => {
      setConversations(data);
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const activeId = pathname.match(/\/chat\/([^/]+)/)?.[1] ?? null;

  const handleNewChat = async () => {
    try {
      const { data } = await api.post<ConversationOut>("/conversations", {});
      addConversation(data);
      router.push(`/chat/${data.id}`);
    } catch {}
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.delete(`/conversations/${id}`);
      removeConversation(id);
      if (activeId === id) {
        router.push("/new");
      }
    } catch {}
  };

  const startEdit = (e: React.MouseEvent, conv: ConversationOut) => {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditValue(conv.title ?? "");
  };

  const confirmRename = async (id: string) => {
    const title = editValue.trim();
    if (title) {
      try {
        await api.patch(`/conversations/${id}`, { title });
        updateConversationTitle(id, title);
      } catch {}
    }
    setEditingId(null);
  };

  const cancelEdit = () => setEditingId(null);

  const handleLogout = async () => {
    try { await logout(); } catch {}
    router.replace("/login");
  };

  return (
    <aside
      className="flex flex-col h-full"
      style={{ background: "var(--sidebar-bg)" }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-slate-700/60">
        <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shrink-0">
          <HardHat size={15} className="text-white" />
        </div>
        <div className="min-w-0">
          <p className="text-slate-100 font-semibold text-sm leading-tight truncate">
            營造知識助理
          </p>
          <p className="text-slate-500 text-[10px] truncate">RAG 智能查詢系統</p>
        </div>
      </div>

      {/* New Chat */}
      <div className="px-3 pt-3 pb-1">
        <button
          onClick={handleNewChat}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-slate-300 hover:text-white hover:bg-slate-700 transition-colors group"
        >
          <Plus size={15} className="text-blue-400 group-hover:text-blue-300" />
          新對話
        </button>
      </div>

      {/* Conversation List */}
      <nav className="flex-1 overflow-y-auto px-3 pb-2 sidebar-scroll space-y-0.5">
        {conversations.length === 0 && (
          <p className="text-center text-slate-600 text-xs py-8">還沒有對話紀錄</p>
        )}
        {conversations.map((conv) => {
          const isActive = conv.id === activeId;
          const isEditing = editingId === conv.id;

          return (
            <div
              key={conv.id}
              onClick={() => !isEditing && router.push(`/chat/${conv.id}`)}
              className={`group relative rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                isActive
                  ? "bg-slate-700 text-slate-100"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              }`}
            >
              {isEditing ? (
                <div
                  className="flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    ref={editInputRef}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") confirmRename(conv.id);
                      if (e.key === "Escape") cancelEdit();
                    }}
                    className="flex-1 bg-slate-600 text-slate-100 text-xs rounded px-2 py-1 outline-none min-w-0"
                  />
                  <button
                    onClick={() => confirmRename(conv.id)}
                    className="p-1 rounded hover:bg-slate-600 text-emerald-400"
                  >
                    <Check size={12} />
                  </button>
                  <button
                    onClick={cancelEdit}
                    className="p-1 rounded hover:bg-slate-600 text-slate-400"
                  >
                    <X size={12} />
                  </button>
                </div>
              ) : (
                <>
                  <p className="text-xs font-medium leading-tight truncate pr-10">
                    {conv.title ?? "新對話"}
                  </p>
                  <p className="text-[10px] mt-0.5 opacity-50 truncate">
                    {timeAgo(conv.updated_at)}
                  </p>

                  {/* Hover actions */}
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5">
                    <button
                      onClick={(e) => startEdit(e, conv)}
                      className="p-1 rounded hover:bg-slate-600 text-slate-500 hover:text-slate-200 transition-colors"
                      title="重新命名"
                    >
                      <Pencil size={11} />
                    </button>
                    <button
                      onClick={(e) => handleDelete(e, conv.id)}
                      className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400 transition-colors"
                      title="刪除對話"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </nav>

      {/* Logout */}
      <div className="px-3 py-3 border-t border-slate-700/60">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
        >
          <LogOut size={13} />
          登出
        </button>
      </div>
    </aside>
  );
}
