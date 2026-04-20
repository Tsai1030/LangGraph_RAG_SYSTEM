"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Image from "next/image";
import { Plus, Trash2, LogOut, Pencil, Check, X, PanelLeft, MessageSquare } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { logout } from "@/lib/auth";
import { useChatStore } from "@/store/chatStore";
import type { ConversationOut } from "@/types";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

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

function TipBtn({
  onClick, title, children, danger = false, className = "",
}: {
  onClick?: (e: React.MouseEvent) => void;
  title: string;
  children: React.ReactNode;
  danger?: boolean;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            onClick={onClick}
            className={cn(
              "flex items-center justify-center rounded-md transition-colors",
              danger
                ? "text-zinc-500 hover:text-red-500 hover:bg-red-500/10"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700",
              className
            )}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="right">{title}</TooltipContent>
    </Tooltip>
  );
}

export default function Sidebar({ collapsed, onToggle }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { conversations, setConversations, addConversation, removeConversation, updateConversationTitle } =
    useChatStore();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const editRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<ConversationOut[]>("/conversations").then(({ data }) => setConversations(data)).catch(() => {});
  }, []); // eslint-disable-line

  useEffect(() => {
    if (editingId) editRef.current?.focus();
  }, [editingId]);

  const activeId = pathname.match(/\/chat\/([^/]+)/)?.[1] ?? null;

  const handleNew = () => {
    router.push("/new");
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.delete(`/conversations/${id}`);
      removeConversation(id);
      if (activeId === id) router.push("/new");
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

  const handleLogout = async () => {
    try { await logout(); } catch {}
    router.replace("/login");
  };

  return (
    <aside className="flex flex-col h-full overflow-hidden bg-zinc-950 text-zinc-400">
      {/* Header */}
      <div className={cn("flex items-center h-14 shrink-0 px-3 gap-2", collapsed && "justify-center")}>
        {!collapsed && (
          <div className="flex-1 flex items-center gap-2.5 min-w-0">
            <button
              onClick={() => router.push("/new")}
              className="shrink-0 rounded-md overflow-hidden hover:opacity-80 transition-opacity cursor-pointer"
              title="回到新對話"
            >
              <Image src="/logo.png" alt="營造知識助理" width={24} height={24} className="size-6 object-contain" />
            </button>
            <span className="text-zinc-100 font-medium text-sm truncate">營造知識助理</span>
          </div>
        )}
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                onClick={onToggle}
                className="size-7 flex items-center justify-center rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors shrink-0"
              />
            }
          >
            <PanelLeft size={15} />
          </TooltipTrigger>
          <TooltipContent side="right">{collapsed ? "展開" : "收合"}</TooltipContent>
        </Tooltip>
      </div>

      <Separator className="bg-zinc-800/60" />

      {/* New Chat */}
      <div className="px-2 pt-2 pb-1">
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  onClick={handleNew}
                  className="w-full flex items-center justify-center size-8 rounded-md text-zinc-500 hover:text-zinc-100 hover:bg-zinc-800 transition-colors mx-auto"
                />
              }
            >
              <Plus size={16} />
            </TooltipTrigger>
            <TooltipContent side="right">新對話</TooltipContent>
          </Tooltip>
        ) : (
          <button
            onClick={handleNew}
            className="w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
          >
            <Plus size={14} className="shrink-0" />
            <span>新對話</span>
          </button>
        )}
      </div>

      {/* Conversation list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-2 sidebar-scroll">
        {!collapsed && conversations.length === 0 && (
          <p className="text-center text-zinc-600 text-xs py-10">尚無對話紀錄</p>
        )}
        <div className="flex flex-col gap-0.5">
          {conversations.map((conv) => {
            const isActive = conv.id === activeId;
            const isEditing = editingId === conv.id;

            if (collapsed) {
              return (
                <Tooltip key={conv.id}>
                  <TooltipTrigger
                    render={
                      <button
                        onClick={() => router.push(`/chat/${conv.id}`)}
                        className={cn(
                          "w-full flex items-center justify-center h-8 rounded-md transition-colors",
                          isActive ? "bg-zinc-800 text-zinc-100" : "hover:bg-zinc-800/60 text-zinc-500"
                        )}
                      />
                    }
                  >
                    <MessageSquare size={13} />
                  </TooltipTrigger>
                  <TooltipContent side="right">{conv.title ?? "新對話"}</TooltipContent>
                </Tooltip>
              );
            }

            return (
              <div
                key={conv.id}
                onClick={() => !isEditing && router.push(`/chat/${conv.id}`)}
                className={cn(
                  "group relative flex flex-col px-2.5 py-2 rounded-md cursor-pointer transition-colors",
                  isActive ? "bg-zinc-800 text-zinc-100" : "hover:bg-zinc-800/60 text-zinc-400 hover:text-zinc-200"
                )}
              >
                {isEditing ? (
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <input
                      ref={editRef}
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") confirmRename(conv.id);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      className="flex-1 bg-zinc-700 text-zinc-100 text-xs rounded-md px-2 py-1 outline-none border border-zinc-600 min-w-0"
                    />
                    <button onClick={() => confirmRename(conv.id)} className="text-emerald-400 hover:text-emerald-300 p-0.5">
                      <Check size={13} />
                    </button>
                    <button onClick={() => setEditingId(null)} className="text-zinc-500 hover:text-zinc-300 p-0.5">
                      <X size={13} />
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="text-xs font-medium truncate pr-12 leading-snug">
                      {conv.title ?? "新對話"}
                    </span>
                    <span className="text-[10px] text-zinc-600 mt-0.5">
                      {timeAgo(conv.updated_at)}
                    </span>
                    <div className="absolute right-1.5 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5">
                      <TipBtn onClick={(e) => startEdit(e, conv)} title="重新命名" className="size-6">
                        <Pencil size={11} />
                      </TipBtn>
                      <TipBtn onClick={(e) => handleDelete(e, conv.id)} title="刪除" danger className="size-6">
                        <Trash2 size={11} />
                      </TipBtn>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </nav>

      <Separator className="bg-zinc-800/60" />

      {/* Logout */}
      <div className="px-2 py-2">
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center justify-center h-8 rounded-md text-zinc-600 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
                />
              }
            >
              <LogOut size={14} />
            </TooltipTrigger>
            <TooltipContent side="right">登出</TooltipContent>
          </Tooltip>
        ) : (
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs text-zinc-600 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
          >
            <LogOut size={13} className="shrink-0" />
            <span>登出</span>
          </button>
        )}
      </div>
    </aside>
  );
}
