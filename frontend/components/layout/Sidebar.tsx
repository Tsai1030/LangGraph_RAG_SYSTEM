"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Image from "next/image";
import { Plus, Trash2, LogOut, Pencil, X, PanelLeft, MessageSquare, MoreHorizontal, HelpCircle, ChevronUp, ChevronDown, Shield } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { logout } from "@/lib/auth";
import { useChatStore } from "@/store/chatStore";
import { useAuthStore } from "@/store/authStore";
import HelpPanel from "./HelpPanel";
import type { ConversationOut } from "@/types";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  onMobileClose?: () => void;
}

function timeAgo(iso: string): string {
  // SQLite 回傳的 datetime 不帶 timezone，補 Z 確保 JS 以 UTC 解析
  const normalized = /[Zz+]/.test(iso) ? iso : iso + "Z";
  const diff = Date.now() - new Date(normalized).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "剛剛";
  if (m < 60) return `${m} 分鐘前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小時前`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} 天前`;
  return new Date(iso).toLocaleDateString("zh-TW");
}

export default function Sidebar({ collapsed, onToggle, onMobileClose }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { conversations, setConversations, addConversation, removeConversation, updateConversationTitle } =
    useChatStore();

  const user = useAuthStore((s) => s.user);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const editRef = useRef<HTMLInputElement>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [userMenuPos, setUserMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<ConversationOut[]>("/conversations").then(({ data }) => setConversations(data)).catch(() => {});
  }, []); // eslint-disable-line

  useEffect(() => {
    if (editingId) editRef.current?.focus();
  }, [editingId]);

  // ── Dropdown: 點外面 / Esc / sidebar scroll → 關閉 ─────────
  useEffect(() => {
    if (!menuOpenId) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (menuRef.current && !menuRef.current.contains(target)) {
        setMenuOpenId(null);
        setMenuPos(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpenId(null);
        setMenuPos(null);
      }
    };
    const onScroll = () => {
      setMenuOpenId(null);
      setMenuPos(null);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    navRef.current?.addEventListener("scroll", onScroll);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
      navRef.current?.removeEventListener("scroll", onScroll);
    };
  }, [menuOpenId]);

  const openMenu = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    // 往下展開、靠右對齊三點按鈕，避免手機模式超出畫面
    const MENU_W = 176; // w-44
    setMenuPos({
      top: rect.bottom + 4,
      left: rect.right - MENU_W,
    });
    setMenuOpenId(id);
  };

  const closeMenu = () => {
    setMenuOpenId(null);
    setMenuPos(null);
  };

  // ── User dropdown: 點外面 / Esc → 關閉 ─────────
  useEffect(() => {
    if (!userMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (userMenuRef.current && !userMenuRef.current.contains(target)) {
        setUserMenuOpen(false);
        setUserMenuPos(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setUserMenuOpen(false);
        setUserMenuPos(null);
      }
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [userMenuOpen]);

  const openUserMenu = (e: React.MouseEvent) => {
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setUserMenuPos({
      // 往上展開（profile 在 sidebar 底部），底邊靠近 trigger 頂部
      top: rect.top - 8,
      left: rect.left,
    });
    setUserMenuOpen(true);
  };

  const closeUserMenu = () => {
    setUserMenuOpen(false);
    setUserMenuPos(null);
  };

  const displayName = user?.display_name || user?.email?.split("@")[0] || "User";
  const initial = (displayName.trim()[0] || "?").toUpperCase();

  const activeId = pathname.match(/\/chat\/([^/]+)/)?.[1] ?? null;

  const handleNew = () => {
    router.push("/new");
  };

  const handleDeleteRequest = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setConfirmingId(id);
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

  const menuConv = conversations.find((c) => c.id === menuOpenId);
  const editingConv = conversations.find((c) => c.id === editingId);
  const confirmingConv = conversations.find((c) => c.id === confirmingId);

  return (
    <>
    <aside className="flex flex-col h-full overflow-hidden bg-[#1F1F1E] text-zinc-400">
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
        {onMobileClose ? (
          <button
            onClick={onMobileClose}
            className="size-7 flex items-center justify-center rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors shrink-0"
            title="關閉"
          >
            <X size={15} />
          </button>
        ) : (
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
        )}
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
      <nav ref={navRef} className="flex-1 overflow-y-auto px-2 pb-2 sidebar-scroll">
        {!collapsed && conversations.length === 0 && (
          <p className="text-center text-zinc-600 text-xs py-10">尚無對話紀錄</p>
        )}
        <div className="flex flex-col gap-0.5">
          {conversations.map((conv) => {
            const isActive = conv.id === activeId;

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

            const isMenuOpen = menuOpenId === conv.id;

            return (
              <div
                key={conv.id}
                onClick={() => router.push(`/chat/${conv.id}`)}
                className={cn(
                  "group relative flex flex-col px-2.5 py-2 rounded-md cursor-pointer transition-colors",
                  isActive ? "bg-zinc-800 text-zinc-100" : "hover:bg-zinc-800/60 text-zinc-400 hover:text-zinc-200"
                )}
              >
                <span className="text-[13px] font-medium truncate pr-12 leading-snug">
                  {conv.title ?? "新對話"}
                </span>
                <span className="text-xs text-zinc-600 mt-0.5">
                  {timeAgo(conv.updated_at)}
                </span>
                {/* 三個圓點按鈕：手機常駐顯示；桌機 hover 列才顯示，選單開啟時也顯示 */}
                <button
                  onClick={(e) => openMenu(e, conv.id)}
                  aria-label="更多選項"
                  className={cn(
                    "absolute right-1.5 top-1/2 -translate-y-1/2",
                    "size-6 flex items-center justify-center rounded-md transition-colors",
                    "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700",
                    "md:opacity-0 md:group-hover:opacity-100",
                    isMenuOpen && "md:opacity-100"
                  )}
                >
                  <MoreHorizontal size={13} />
                </button>
              </div>
            );
          })}
        </div>
      </nav>

      <Separator className="bg-zinc-800/60" />

      {/* User profile — 點擊往上彈出選單 */}
      <div className="px-2 py-2">
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  onClick={openUserMenu}
                  className="w-full flex items-center justify-center h-8 rounded-md transition-colors hover:bg-zinc-800"
                />
              }
            >
              <span
                className="size-7 rounded-full flex items-center justify-center text-[12px] font-bold"
                style={{ background: "#B2B1A7", color: "#1F1F1E" }}
              >
                {initial}
              </span>
            </TooltipTrigger>
            <TooltipContent side="right">{displayName}</TooltipContent>
          </Tooltip>
        ) : (
          <button
            onClick={openUserMenu}
            className="w-full flex items-center gap-2 px-2 h-10 rounded-md hover:bg-zinc-800 transition-colors"
          >
            <span
              className="shrink-0 size-7 rounded-full flex items-center justify-center text-[12px] font-bold"
              style={{ background: "#B2B1A7", color: "#1F1F1E" }}
            >
              {initial}
            </span>
            <span
              className="flex-1 min-w-0 text-left text-[13px] font-semibold truncate"
              style={{ color: "#B2B1A7" }}
            >
              {displayName}
            </span>
            <span className="shrink-0 flex flex-col items-center text-zinc-300">
              <ChevronUp size={11} strokeWidth={2.25} />
              <ChevronDown size={11} strokeWidth={2.25} className="-mt-1" />
            </span>
          </button>
        )}
      </div>
    </aside>

    {/* 對話 Dropdown 選單 — fixed 定位避開 sidebar overflow 切割 */}
    {menuConv && menuPos && (
      <div
        ref={menuRef}
        style={{ top: menuPos.top, left: menuPos.left }}
        className={cn(
          "fixed z-50 w-44 rounded-lg border border-zinc-700 bg-zinc-800 shadow-lg",
          "p-1"
        )}
      >
        <button
          onClick={(e) => {
            closeMenu();
            startEdit(e, menuConv);
          }}
          className={cn(
            "w-full flex items-center gap-2 px-2.5 py-2 rounded-md",
            "text-[13px] text-zinc-200 hover:bg-zinc-700 transition-colors",
            "border-b border-zinc-700/60"
          )}
        >
          <Pencil size={13} className="text-zinc-400" />
          Rename
        </button>
        <button
          onClick={(e) => {
            closeMenu();
            handleDeleteRequest(e, menuConv.id);
          }}
          className={cn(
            "w-full flex items-center gap-2 px-2.5 py-2 rounded-md",
            "text-[13px] text-red-400 hover:bg-zinc-700 transition-colors",
            "border-b border-zinc-700/60"
          )}
        >
          <Trash2 size={13} className="text-red-400" />
          Delete
        </button>
      </div>
    )}

    {/* Rename modal — 置中卡片 + blur 遮罩 */}
    {editingConv && (
      <div
        className="fixed inset-0 z-[60] flex items-center justify-center bg-black/20 bg-opacity-40 backdrop-blur-[2px] p-4"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) setEditingId(null);
        }}
      >
        <div className="w-[min(420px,100%)] rounded-2xl bg-white shadow-2xl p-5 sm:p-6">
          <h3 className="text-zinc-900 text-lg font-bold">Rename chat</h3>
          <input
            ref={editRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") confirmRename(editingConv.id);
              if (e.key === "Escape") setEditingId(null);
            }}
            className={cn(
              "mt-4 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2",
              "text-[14px] text-zinc-900 outline-none",
              "focus:border-zinc-500"
            )}
          />
          <div className="mt-5 flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
            <button
              onClick={() => setEditingId(null)}
              className="px-4 h-9 rounded-lg border border-zinc-300 bg-white text-[13px] font-medium text-zinc-900 hover:bg-zinc-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => confirmRename(editingConv.id)}
              className="px-4 h-9 rounded-lg border border-zinc-900 bg-zinc-900 text-[13px] font-medium text-white hover:bg-zinc-800 transition-colors"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    )}

    {/* User Dropdown — fixed 定位往上彈出 */}
    {userMenuOpen && userMenuPos && (
      <div
        ref={userMenuRef}
        style={{ left: userMenuPos.left, bottom: window.innerHeight - userMenuPos.top }}
        className={cn(
          "fixed z-50 w-56 rounded-lg border border-zinc-700 bg-zinc-800 shadow-lg",
          "p-1"
        )}
      >
        {/* Email — 純資訊列 */}
        <div className="px-2.5 py-2 text-[12px] text-zinc-400 truncate border-b border-zinc-700/60">
          {user?.email ?? "—"}
        </div>
        {user?.role === "admin" && (
          <button
            onClick={() => {
              closeUserMenu();
              router.push("/admin");
            }}
            className={cn(
              "w-full flex items-center gap-2 px-2.5 py-2 rounded-md",
              "text-[13px] text-zinc-200 hover:bg-zinc-700 transition-colors",
              "border-b border-zinc-700/60"
            )}
          >
            <Shield size={13} className="text-zinc-400" />
            管理後台
          </button>
        )}
        <button
          onClick={() => {
            closeUserMenu();
            setHelpOpen(true);
          }}
          className={cn(
            "w-full flex items-center gap-2 px-2.5 py-2 rounded-md",
            "text-[13px] text-zinc-200 hover:bg-zinc-700 transition-colors",
            "border-b border-zinc-700/60"
          )}
        >
          <HelpCircle size={13} className="text-zinc-400" />
          Get help
        </button>
        <button
          onClick={() => {
            closeUserMenu();
            handleLogout();
          }}
          className={cn(
            "w-full flex items-center gap-2 px-2.5 py-2 rounded-md",
            "text-[13px] text-zinc-200 hover:bg-zinc-700 transition-colors",
            "border-b border-zinc-700/60"
          )}
        >
          <LogOut size={13} className="text-zinc-400" />
          Log out
        </button>
      </div>
    )}

    <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} />

    {/* Delete confirmation modal */}
    {confirmingConv && (
      <div
        className="fixed inset-0 z-[60] flex items-center justify-center bg-black/20 bg-opacity-40 backdrop-blur-[2px] p-4"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) setConfirmingId(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setConfirmingId(null);
        }}
      >
        <div className="w-[min(420px,100%)] rounded-2xl bg-white shadow-2xl p-5 sm:p-6">
          <h3 className="text-zinc-900 text-lg font-bold">Delete chat</h3>
          <p className="mt-3 text-[14px] text-zinc-700 leading-relaxed">
            Are you sure you want to delete this chat?
          </p>
          <div className="mt-5 flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
            <button
              onClick={() => setConfirmingId(null)}
              className="px-4 h-9 rounded-lg border border-zinc-300 bg-white text-[13px] font-medium text-zinc-900 hover:bg-zinc-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={async () => {
                const id = confirmingConv.id;
                setConfirmingId(null);
                try {
                  await api.delete(`/conversations/${id}`);
                  removeConversation(id);
                  if (activeId === id) router.push("/new");
                } catch {}
              }}
              className="px-4 h-9 rounded-lg border border-red-500 bg-red-500 text-[13px] font-medium text-white hover:bg-red-600 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
